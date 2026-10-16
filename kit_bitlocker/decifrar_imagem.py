# -*- coding: utf-8 -*-
"""Gera uma NOVA imagem de disco com a(s) partição(ões) BitLocker decifrada(s), em uma passada.

- A imagem original é só lida, do início ao fim; calcula SHA-256/MD5 da ORIGEM (e confere com o hash do
  relatório da extração, se informado em --sha256).
- Copia tudo como está, exceto as partições BitLocker, que saem decifradas.
- Calcula SHA-256/MD5 da imagem DECIFRADA enquanto grava (arquivo .parcial, renomeado só ao fim).
- Grava <nome>_registro.txt com origem, método, hashes e resultado (cadeia de custódia).

Uso:
  python decifrar_imagem.py <imagem .dd/.001> <pasta_saida> [--sha256 HASH] [--chave-recuperacao 48DIGITOS]
                            [--nome NOME]
"""
import argparse
import datetime as dt
import hashlib
import os
import platform
import sys
import threading
import time
from importlib.metadata import version
from queue import Queue

from dissect.volume.disk import Disk

from bde_rapido import abrir_volume
from imagem import Segmentos, abrir

BLOCO = 64 * 1024 * 1024


def agora():
    return dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")


class Hasher:
    """SHA-256 + MD5 em threads (hashlib libera o GIL)."""

    def __init__(self):
        self.h = [hashlib.sha256(), hashlib.md5()]
        self.q = [Queue(maxsize=3) for _ in self.h]
        self.t = [threading.Thread(target=self._run, args=(h, q), daemon=True) for h, q in zip(self.h, self.q)]
        for t in self.t:
            t.start()

    @staticmethod
    def _run(h, q):
        while (b := q.get()) is not None:
            h.update(b)

    def update(self, b):
        for q in self.q:
            q.put(b)

    def fim(self):
        for q in self.q:
            q.put(None)
        for t in self.t:
            t.join()
        return self.h[0].hexdigest(), self.h[1].hexdigest()


class CacheBloco:
    """Leitura que serve do bloco já lido pelo laço principal (evita ler o disco duas vezes)."""

    def __init__(self, fh):
        self.fh, self.ini, self.buf, self.pos = fh, -1, b"", 0

    def carregar(self, ini, buf):
        self.ini, self.buf = ini, buf

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        a = self.pos - self.ini
        if 0 <= a and a + n <= len(self.buf):
            b = self.buf[a:a + n]
        else:
            self.fh.seek(self.pos)
            b = self.fh.read(n)
        self.pos += len(b)
        return b


def particoes_bitlocker(fh):
    """[(nº, início, tamanho)] das partições (GPT ou MBR) cujo setor de boot tem a assinatura -FVE-FS-."""
    achadas = []
    for i, p in enumerate(Disk(fh).partitions, 1):
        fh.seek(p.offset + 3)
        if fh.read(8) == b"-FVE-FS-":
            achadas.append((i, p.offset, p.size))
    if not achadas:
        raise SystemExit("Nenhuma partição BitLocker encontrada: processe a imagem original no IPED.")
    return achadas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagem")
    ap.add_argument("pasta_saida")
    ap.add_argument("--sha256", help="SHA-256 da imagem no relatório da extração (para conferência)")
    ap.add_argument("--chave-recuperacao", help="chave de recuperação de 48 dígitos (só se não houver chave em claro)")
    ap.add_argument("--nome", help="nome do arquivo de saída, sem extensão (padrão: <imagem>_decifrado)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    f_raw, segs, total = abrir(a.imagem)
    base = a.nome or os.path.splitext(os.path.basename(segs[0]))[0] + "_decifrado"
    os.makedirs(a.pasta_saida, exist_ok=True)
    destino = os.path.join(a.pasta_saida, base + ".dd")
    parcial = destino + ".parcial"
    registro = os.path.join(a.pasta_saida, base + "_registro.txt")
    if os.path.exists(destino):
        sys.exit(f"[ERRO] {destino} já existe; nada foi sobrescrito.")
    if os.path.abspath(a.pasta_saida).startswith(os.path.dirname(os.path.abspath(segs[0]))):
        print("[AVISO] A saída está dentro da pasta da evidência. Recomendado: pasta irmã, fora da evidência.")
    if os.environ.get("LIMITE_TESTE"):  # só para teste: processa os N primeiros bytes
        total = int(os.environ["LIMITE_TESTE"])
    inicio_txt, t0 = agora(), time.time()

    cache = CacheBloco(Segmentos(segs))
    parts = []
    for num, ini, tam in particoes_bitlocker(f_raw):
        bde, vol, protetor = abrir_volume(cache, ini, tam, a.chave_recuperacao)
        vol.seek(0)
        if vol.read(11)[3:11] != b"NTFS    ":
            sys.exit(f"[ERRO] Partição {num}: o volume decifrado não começa com NTFS. Nada foi gravado.")
        parts.append((num, ini, tam, vol, bde._fvek_type.name, protetor))
        print(f"[{agora()}] Partição {num}: início {ini}, tamanho {tam}, {bde._fvek_type.name}, {protetor}")

    h_orig, h_dec = Hasher(), Hasher()
    fila_lida, fila_grava = Queue(maxsize=4), Queue(maxsize=4)
    erros = []

    def leitor():
        try:
            o = 0
            while o < total:
                f_raw.seek(o)
                raw = f_raw.read(min(BLOCO, total - o))
                if not raw:
                    raise IOError(f"leitura vazia em {o}")
                fila_lida.put((o, raw))
                o += len(raw)
        except Exception as e:  # noqa: BLE001
            erros.append(e)
        fila_lida.put(None)

    def gravador(out):
        try:
            while (b := fila_grava.get()) is not None:
                out.write(b)
                h_dec.update(b)
        except Exception as e:  # noqa: BLE001
            erros.append(e)
            while fila_grava.get() is not None:  # drena para não travar a decifragem
                pass

    off, ultimo = 0, 0.0
    with open(parcial, "wb") as out:
        tl = threading.Thread(target=leitor, daemon=True)
        tg = threading.Thread(target=gravador, args=(out,), daemon=True)
        tl.start()
        tg.start()
        while (item := fila_lida.get()) is not None:
            off, raw = item
            h_orig.update(raw)
            cache.carregar(off, raw)
            fim = off + len(raw)
            saida = raw
            for _, ini, tam, vol, _, _ in parts:
                x, y = max(off, ini), min(fim, ini + tam)
                if x < y:  # trecho dentro de partição BitLocker -> decifrado
                    vol.seek(x - ini)
                    dec = vol.read(y - x)
                    if len(dec) != y - x:
                        raise IOError(f"decifragem curta em {x}: {len(dec)} != {y - x}")
                    saida = saida[:x - off] + dec + saida[y - off:]
            fila_grava.put(saida)
            off = fim
            if time.time() - ultimo > 20:
                ultimo = time.time()
                vel = off / (ultimo - t0) / 1e6
                resta = (total - off) / (vel * 1e6) if vel else 0
                print(f"[{agora()}] {off / total * 100:6.2f}%  {vel:6.1f} MB/s  faltam ~{resta / 60:.0f} min", flush=True)
        fila_grava.put(None)
        tg.join()
        tl.join()
        if erros:
            raise erros[0]
        if off != total:
            raise IOError(f"processado {off} de {total} bytes")
        out.flush()
        os.fsync(out.fileno())
    s_orig, m_orig = h_orig.fim()
    s_dec, m_dec = h_dec.fim()
    os.replace(parcial, destino)
    dur = time.time() - t0
    confere = None if not a.sha256 else s_orig.lower() == a.sha256.strip().lower()

    linhas = [
        "REGISTRO DE DECIFRAGEM DE VOLUME BITLOCKER",
        "",
        f"Início: {inicio_txt}   Fim: {agora()}   Duração: {dur / 3600:.2f} h",
        f"Máquina: {platform.node()}   Python {platform.python_version()}   dissect.fve {version('dissect.fve')}"
        f"   pycryptodome {version('pycryptodome')}",
        "",
        "ORIGEM (lida somente em leitura, não alterada)",
        *[f"  Arquivo: {s}" for s in segs],
        f"  Tamanho: {total} bytes",
        f"  SHA-256: {s_orig.upper()}",
        f"  MD5:     {m_orig.upper()}",
    ]
    if a.sha256:
        linhas += [f"  SHA-256 do relatório da extração: {a.sha256.strip().upper()}",
                   f"  Conferência: {'CONFERE' if confere else 'NÃO CONFERE'}"]
    linhas += ["", "VOLUME(S) CIFRADO(S)"]
    for num, ini, tam, _, tipo, protetor in parts:
        linhas.append(f"  Partição nº {num}, início {ini} bytes, tamanho {tam} bytes, {tipo}, aberta com: {protetor}")
    linhas += [
        "",
        "MÉTODO",
        "  A imagem decifrada é cópia byte a byte da origem, exceto o intervalo da(s) partição(ões) BitLocker,",
        "  substituído pelo conteúdo decifrado (setores de cabeçalho realocados restaurados e regiões de",
        "  metadados do BitLocker zeradas, como faz o Windows ao montar o volume). Demais partições e a tabela",
        "  de partições ficam idênticas à origem.",
        "",
        "IMAGEM DECIFRADA",
        f"  Arquivo: {destino}",
        f"  Tamanho: {os.path.getsize(destino)} bytes",
        f"  SHA-256: {s_dec.upper()}",
        f"  MD5:     {m_dec.upper()}",
    ]
    with open(registro, "w", encoding="utf-8") as r:
        r.write("\n".join(linhas) + "\n")
    print("\n" + "\n".join(linhas))
    print(f"\nRegistro gravado em: {registro}")
    if confere is False:
        print("\n[ALERTA] O SHA-256 da origem NÃO confere com o do relatório. Não prossiga sem conferir.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
