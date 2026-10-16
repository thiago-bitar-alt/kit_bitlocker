"""Abre a imagem de disco bruta, inteira ou em segmentos (.001, .002, ...), como um único arquivo só de leitura."""
import glob
import io
import os
import re


class Segmentos(io.RawIOBase):
    """Concatena DDCapture.001, DDCapture.002, ... (na ordem) em um arquivo só leitura."""

    def __init__(self, caminhos):
        self.fhs = [open(c, "rb") for c in caminhos]
        self.inis, total = [], 0
        for c in caminhos:
            self.inis.append(total)
            total += os.path.getsize(c)
        self.size, self.pos = total, 0

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
        partes = []
        while n > 0 and self.pos < self.size:
            i = max(k for k, ini in enumerate(self.inis) if ini <= self.pos)
            fh = self.fhs[i]
            fh.seek(self.pos - self.inis[i])
            b = fh.read(n)
            if not b:
                break
            partes.append(b)
            self.pos += len(b)
            n -= len(b)
        return b"".join(partes)

    def close(self):
        for fh in self.fhs:
            fh.close()
        super().close()


def segmentos(caminho):
    """Lista de arquivos da imagem: se for .001 e houver .002, .003..., todos em ordem; senão, só ele."""
    m = re.match(r"(.*\.)(\d{3})$", caminho)
    if not m:
        return [caminho]
    lista = sorted(glob.glob(glob.escape(m.group(1)) + "[0-9][0-9][0-9]"))
    return lista or [caminho]


def abrir(caminho):
    """(arquivo só leitura, lista de segmentos, tamanho total)."""
    segs = segmentos(caminho)
    if caminho.lower().endswith((".e01", ".ex01", ".aff", ".vmdk", ".vhd", ".vhdx")):
        raise SystemExit("Formato não suportado: converta para imagem bruta (.dd/.001), ver tutorial.")
    fh = Segmentos(segs)
    return fh, segs, fh.size
