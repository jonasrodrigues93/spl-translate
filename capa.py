"""Gera build/capa.png (1600x2400, tons de cinza) para o EPUB.

Desenho original: uma matriz de atenção — grade de quadrados cujo cinza mede
quanto cada token "olha" para os outros — sob o título. Contraste alto e só
cinza, porque a capa será vista em tinta eletrônica.
"""
import math
import random
from pathlib import Path

import fitz

W, H = 1600, 2400
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
SERIF_B = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

TITULO = ["Processamento", "de Fala e", "Linguagem"]
SUB = "Introdução a modelos de linguagem, NLP e reconhecimento de fala"
AUTORES = "Daniel Jurafsky  ·  James H. Martin"
EDICAO = "Tradução para o português do Brasil  ·  3ª edição (rascunho)"


def cinza(v):
    v = max(0.0, min(1.0, v))
    return (v, v, v)


def centro(page, y, texto, size, fonte, cor):
    f = fitz.Font(fontfile=fonte)
    w = f.text_length(texto, fontsize=size)
    page.insert_text(((W - w) / 2, y), texto, fontsize=size,
                     fontname="f" + str(abs(hash(fonte)) % 999),
                     fontfile=fonte, color=cor)


def main():
    doc = fitz.open()
    p = doc.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(0, 0, W, H), color=None, fill=cinza(0.96))

    # faixa do título
    topo = 120
    p.draw_rect(fitz.Rect(0, topo, W, topo + 640), color=None, fill=cinza(0.08))
    for i, linha in enumerate(TITULO):
        centro(p, topo + 235 + i * 175, linha, 140, SERIF_B, cinza(1))

    # matriz de atenção: causal (triangular inferior), com diagonal forte
    n = 12
    lado = 72
    gap = 7
    total = n * lado + (n - 1) * gap
    x0, y0 = (W - total) / 2, topo + 640 + 110
    rnd = random.Random(2026)
    for i in range(n):
        for j in range(n):
            x = x0 + j * (lado + gap)
            y = y0 + i * (lado + gap)
            r = fitz.Rect(x, y, x + lado, y + lado)
            if j > i:                       # futuro mascarado
                p.draw_rect(r, color=cinza(0.80), fill=None, width=2)
                continue
            d = i - j
            v = math.exp(-d / 3.2) * 0.75 + rnd.random() * 0.35
            if j == 0:
                v += 0.25                   # token inicial atrai atenção
            v = min(1.0, v)
            p.draw_rect(r, color=None, fill=cinza(1 - v * 0.92))

    ybase = y0 + total
    centro(p, ybase + 130, SUB, 40, SERIF, cinza(0.15))
    p.draw_line((300, ybase + 190), (W - 300, ybase + 190), color=cinza(0.15), width=3)
    centro(p, ybase + 290, AUTORES, 58, SERIF_B, cinza(0.05))
    centro(p, H - 90, EDICAO, 34, SANS, cinza(0.35))

    out = Path(__file__).parent / "build" / "capa.png"
    p.get_pixmap(dpi=72, colorspace=fitz.csGRAY).save(out)
    print(f"capa: {out}")


if __name__ == "__main__":
    main()
