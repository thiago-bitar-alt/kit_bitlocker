# -*- coding: utf-8 -*-
"""Diz, só lendo a imagem, se alguma partição tem BitLocker e como a chave está protegida.

Uso: python checa_bitlocker.py <imagem .dd/.001>

Chave em claro: decifra sem senha.  Outros protetores: é preciso a chave de recuperação (48 dígitos),
que se pede informando o ID mostrado aqui.
"""
import sys

from dissect.fve.bde import BDE
from dissect.volume.disk import Disk

from imagem import abrir

PROTETORES = {"has_clear_key": "CHAVE EM CLARO (decifra sem senha)",
              "has_recovery_password": "chave de recuperação (48 dígitos)",
              "has_passphrase": "senha", "has_bek": "chave de inicialização (.BEK, pendrive)"}


def main(caminho):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fh, segs, total = abrir(caminho)
    print(f"Imagem: {caminho} ({len(segs)} arquivo(s), {total / 2**30:.1f} GiB)\n")
    achou = False
    for i, p in enumerate(Disk(fh).partitions, 1):
        fh.seek(p.offset + 3)
        bitlocker = fh.read(8) == b"-FVE-FS-"
        print(f"Partição {i}: início {p.offset} bytes, {p.size / 2**30:.1f} GiB - "
              + ("BITLOCKER" if bitlocker else "sem BitLocker"))
        if not bitlocker:
            continue
        achou = True
        bde = BDE(p.open())
        tem = [txt for m, txt in PROTETORES.items() if getattr(bde, m)()]
        print("   Protetores:", ", ".join(tem) or "nenhum reconhecido (provável TPM)")
        for ident in bde.identifiers:
            print("   ID do protetor:", ident)
        if bde.has_clear_key():
            print("   => Decifra sem senha: siga para o PASSO 4 do tutorial.")
        else:
            print("   => A imagem sozinha NÃO basta. Peça a chave de recuperação informando o ID acima (PASSO 5).")
    if not achou:
        print("\nNenhuma partição com BitLocker: processe a imagem no IPED normalmente.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
