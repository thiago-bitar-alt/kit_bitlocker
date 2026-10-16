"""Decifragem BitLocker (AES-XTS) rápida, reaproveitando a lógica de regiões do dissect.fve.

O dissect resolve setores realocados do cabeçalho, regiões de metadados e EOW; o lento
é o AES-XTS setor a setor em Python. Aqui só o decifrador é trocado por uma versão
vetorizada: tweak = E_k2(nº do setor), multiplicações por alfa em GF(2^128) via numpy,
e AES-ECB de k1 sobre o buffer inteiro numa chamada só.

Uso como módulo: abrir_volume(arquivo, offset_particao, tamanho_particao[, chave_recuperacao]).
"""
import io
import numpy as np
from Crypto.Cipher import AES
from dissect.fve.bde import BDE

SETOR = 512
BLOCOS = SETOR // 16


class Fatia(io.RawIOBase):
    """Janela somente leitura de um arquivo (a partição dentro da imagem)."""

    def __init__(self, fh, inicio, tamanho):
        self.fh, self.inicio, self.size, self.pos = fh, inicio, tamanho, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        self.fh.seek(self.inicio + self.pos)
        b = self.fh.read(n)
        self.pos += len(b)
        return b


def _potencias_alfa(t):
    """t: array (n,2) uint64 [lo, hi] -> array (n, 32, 2) com t*alfa^j, j=0..31 (XTS, little-endian)."""
    n = t.shape[0]
    out = np.empty((n, BLOCOS, 2), dtype=np.uint64)
    lo, hi = t[:, 0].copy(), t[:, 1].copy()
    for j in range(BLOCOS):
        out[:, j, 0], out[:, j, 1] = lo, hi
        carry = hi >> np.uint64(63)
        hi = (hi << np.uint64(1)) | (lo >> np.uint64(63))
        lo = (lo << np.uint64(1)) ^ (carry * np.uint64(0x87))
    return out


class XtsRapido:
    def __init__(self, fvek):
        assert len(fvek) in (32, 64), "FVEK XTS deve ter 32 ou 64 bytes"
        meio = len(fvek) // 2
        self.k1 = AES.new(fvek[:meio], AES.MODE_ECB)
        self.k2 = AES.new(fvek[meio:], AES.MODE_ECB)

    def decrypt(self, buf, setor):
        n = len(buf) // SETOR
        idx = np.arange(setor, setor + n, dtype=np.uint64)
        tw = np.zeros((n, 2), dtype=np.uint64)
        tw[:, 0] = idx
        t = np.frombuffer(self.k2.encrypt(tw.tobytes()), dtype=np.uint64).reshape(n, 2)
        mask = _potencias_alfa(t).reshape(-1)
        c = np.frombuffer(buf, dtype=np.uint64)
        p = np.frombuffer(self.k1.decrypt((c ^ mask).tobytes()), dtype=np.uint64) ^ mask
        return p.tobytes()


def abrir_volume(fh, inicio, tamanho, chave_recuperacao=None, rapido=True):
    """(bde, stream decifrado, protetor usado). Chave em claro se houver; senão, a chave de recuperação informada."""
    bde = BDE(Fatia(fh, inicio, tamanho))
    if bde.has_clear_key():
        bde.unlock_with_clear_key()
        protetor = "chave em claro (sem senha)"
    elif chave_recuperacao:
        bde.unlock_with_recovery_password(chave_recuperacao)
        protetor = "chave de recuperação informada pelo perito"
    else:
        raise RuntimeError("volume sem chave em claro: informe --chave-recuperacao")
    stream = bde.open()
    if rapido and "XTS" in bde._fvek_type.name:  # AES-CBC (Windows 7/8) fica com o decifrador do dissect
        stream.cipher = XtsRapido(bde._fvek)
    return bde, stream, protetor
