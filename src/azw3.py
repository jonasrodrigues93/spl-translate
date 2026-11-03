"""Converte o EPUB em AZW3 para o Kindle e corrige o tipo do documento.

Uso: python3 src/azw3.py build/livro.epub [saida.azw3]

O Calibre grava o tipo EXTH 501 como EBOK (livro da loja) com um ASIN
inventado. O Kindle então busca a capa online por esse ASIN e a biblioteca
mostra o livro sem capa. Trocar para PDOC (documento pessoal) faz o Kindle
usar a capa embutida. A troca tem o mesmo tamanho (4 bytes).
"""
import struct
import subprocess
import sys
from pathlib import Path


def pdoc(caminho):
    d = bytearray(Path(caminho).read_bytes())
    n = struct.unpack(">H", d[76:78])[0]
    off = [struct.unpack(">L", d[78 + 8 * i:82 + 8 * i])[0] for i in range(n)]
    i = d.find(b"EXTH", off[0], off[1])
    if i < 0:
        sys.exit("EXTH não encontrado no registro 0")
    cnt = struct.unpack(">L", d[i + 8:i + 12])[0]
    q = i + 12
    for _ in range(cnt):
        t, tam = struct.unpack(">LL", d[q:q + 8])
        if t == 501:
            d[q + 8:q + tam] = b"PDOC"
            Path(caminho).write_bytes(d)
            return
        q += tam
    sys.exit("EXTH 501 não encontrado")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    epub = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else epub.with_suffix(".azw3")
    subprocess.run(["ebook-convert", str(epub), str(out)], check=True,
                   stdout=subprocess.DEVNULL)
    pdoc(out)
    print(f"azw3: {out}  (tipo PDOC)")


if __name__ == "__main__":
    main()
