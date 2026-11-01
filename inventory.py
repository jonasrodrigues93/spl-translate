#!/usr/bin/env python3
"""
Inventário de estilos do PDF — o que existe, e o que fazemos com cada um.

O PDF não é marcado (sem StructTreeRoot): o pdfTeX não grava semântica.
O que existe é a assinatura tipográfica que o LaTeX deixou — fonte, corpo,
cor — mais os desenhos que delimitam tabela, quadro e nota. Cada combinação
distinta corresponde a um comando do fonte original, e é o mais próximo de
uma "tag" que este arquivo oferece.

Este script lista TODAS as combinações, com contagem, páginas e amostra, e
diz em que tipo de bloco cada uma está caindo hoje. Serve para revisar o
tratamento por classe em vez de descobrir defeito a defeito na leitura.

    ./venv/bin/python inventory.py            # estilos de texto
    ./venv/bin/python inventory.py --desenhos # padrões de desenho
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

import fitz

from extract import (PDF, OUT, base_font, decode_span, unlig, HEADER_Y_MAX,
                     FOOTER_Y_MIN, MARGIN_X_MAX)


MARCA = re.compile(r"«/?[a-z]+»")


def norm(t: str) -> str:
    """Compara span com bloco apesar dos marcadores e da desifenização.

    O bloco traz «i»/«b» no meio das palavras, já perdeu o hífen de fim de
    linha e teve o espaço normalizado. Sem desfazer isso, a busca por
    substring falha até para a fonte do corpo — e o diagnóstico acusa 100%
    de perda onde não há perda nenhuma.
    """
    # o bloco já passou por unlig (ligadura e acento partido); sem aplicar o
    # mesmo aqui, "ﬁve" não casa com "five" e "p´aginas" não casa com
    # "páginas" — e o diagnóstico acusa perda em texto que está lá
    t = unlig(MARCA.sub("", t))
    t = re.sub(r"[-\u00ad]\s*", "", t)
    return re.sub(r"\s+", "", t).lower()


def bloco_por_texto(blocks_por_pag: dict, pno: int, txt: str,
                    cache: dict | None = None, bbox=None,
                    imagens=None) -> str:
    """Em que tipo de bloco este texto foi parar (na mesma página).

    Distingue as duas razões para um texto não estar em bloco nenhum:
    EM-IMAGEM (está dentro de figura ou equação rasterizada, e portanto é
    lido, só não é texto) e PERDIDO (sumiu de verdade). Sem separar as duas,
    metade da fonte do corpo aparece como perda e o diagnóstico não serve.
    """
    alvo = norm(txt)
    if len(alvo) < 8:
        return "?"
    # páginas vizinhas também: um parágrafo que cruza a virada é religado no
    # bloco da página ANTERIOR, e procurar só na própria acusa perda que não
    # existe
    viz = (blocks_por_pag.get(pno, []) + blocks_por_pag.get(pno - 1, [])
           + blocks_por_pag.get(pno + 1, []))
    for b in viz:
        if cache is not None:
            key = id(b)
            nb = cache.get(key)
            if nb is None:
                nb = cache[key] = norm(b["text"])
        else:
            nb = norm(b["text"])
        if alvo in nb:
            return b["kind"]
    if bbox is not None and imagens:
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        for r in imagens.get(pno, ()):
            if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                return "EM-IMAGEM"
    return "PERDIDO"


def estilos(doc, blocks_por_pag, imagens, so_perdas=False) -> None:
    uso: dict[tuple, Counter] = defaultdict(Counter)
    pags: dict[tuple, set] = defaultdict(set)
    amostra: dict[tuple, tuple] = {}
    # várias amostras por estilo: uma só não diz nada sobre a classe
    provas: dict[tuple, list] = defaultdict(list)

    for pno in range(doc.page_count):
        for b in doc[pno].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                y, x = l["bbox"][1], l["bbox"][0]
                if y < HEADER_Y_MAX or y > FOOTER_Y_MIN:
                    continue
                for s in l["spans"]:
                    t = decode_span(s).strip()
                    if not t:
                        continue
                    k = (base_font(s["font"]), round(s["size"], 1),
                         f"#{s['color']:06x}", "margem" if x < MARGIN_X_MAX
                         else "corpo")
                    uso[k][len(t)] += 1
                    pags[k].add(pno)
                    if k not in amostra or len(t) > len(amostra[k][1]):
                        amostra[k] = (pno, t[:56])
                    # uma amostra por página, para depois espalhar pelo
                    # livro: pegar as 12 primeiras concentra tudo no miolo
                    # inicial — e as páginas de rosto e sumário nem são
                    # extraídas, o que fazia a fonte do corpo acusar 100%
                    # de perda
                    if len(t) >= 12 and (not provas[k]
                                         or provas[k][-1][0] != pno):
                        provas[k].append((pno, t[:60], l["bbox"]))

    _cache: dict = {}
    linhas = []
    for k, c in uso.items():
        n = sum(c.values())
        pno, txt = amostra[k]
        # taxa de perda: das amostras longas deste estilo, quantas não
        # aparecem em bloco nenhum?
        pv = provas[k]
        if len(pv) > 12:
            passo = len(pv) / 12
            pv = [pv[int(i * passo)] for i in range(12)]
        kinds = Counter()
        for pp, tt, bb in pv:
            kinds[bloco_por_texto(blocks_por_pag, pp, tt, _cache,
                                  bb, imagens)] += 1
        tot = sum(kinds.values())
        perda = kinds.get("PERDIDO", 0) / tot if tot else None
        dest = ", ".join(f"{a}" for a, _ in kinds.most_common(2)) or "?"
        exs = [(pp, tt) for pp, tt, bb in pv
               if bloco_por_texto(blocks_por_pag, pp, tt, _cache, bb,
                                  imagens) == "PERDIDO"]
        linhas.append((n, k, len(pags[k]), perda, dest, txt, exs))
    linhas.sort(reverse=True)

    print(f"{len(linhas)} combinações distintas de (fonte, corpo, cor, coluna)")
    perdidos = [l for l in linhas if l[3] is not None and l[3] >= 0.5]
    print(f"{len(perdidos)} com metade ou mais das amostras fora de qualquer "
          f"bloco\n")
    print(f"{'n':>7} {'pág':>4} {'perda':>6}  {'fonte':24} {'pt':>5} "
          f"{'cor':>8} {'col':6} {'destino':22} amostra")
    print("-" * 132)
    if so_perdas:
        print("\n=== perdas reais (fora de bloco E fora de imagem) ===")
        for n, k, npg, perda, dest, txt, exs in linhas:
            if not exs or n < 40:
                continue
            fonte, sz, cor, col = k
            print(f"\n  {fonte} {sz}pt {cor} [{col}] — {n} spans em {npg} "
                  f"páginas, {len(exs)}/12 amostras perdidas")
            for pp, tt in exs[:3]:
                print(f"      p{pp}: {tt[:70]!r}")
        return
    for n, k, npg, perda, dest, txt, exs in linhas:
        if n < 60:
            continue
        fonte, sz, cor, col = k
        pc = f"{perda*100:.0f}%" if perda is not None else "  -"
        print(f"{n:>7} {npg:>4} {pc:>6}  {fonte:24} {sz:>5} {cor:>8} {col:6} "
              f"{dest:22} {txt[:34]!r}")


def desenhos(doc) -> None:
    """Padrões de desenho: é deles que saem tabela, quadro, nota e figura."""
    cat: Counter = Counter()
    amostra: dict[str, tuple] = {}
    for pno in range(doc.page_count):
        pg = doc[pno]
        for d in pg.get_drawings():
            r = fitz.Rect(d["rect"])
            tipo = d.get("type", "?")
            if r.height <= 1.5 and r.width > 40:
                k = f"filete horizontal  largura {int(r.width // 50) * 50}-" \
                    f"{int(r.width // 50) * 50 + 49}pt"
            elif r.width <= 1.5 and r.height > 10:
                k = f"filete vertical    altura {int(r.height // 50) * 50}-" \
                    f"{int(r.height // 50) * 50 + 49}pt"
            elif r.width <= 3 and r.height <= 3:
                k = "ponto/traço curto"
            elif tipo == "f":
                k = "retângulo PREENCHIDO (faixa de tabela?)"
            else:
                k = "traço de desenho (figura)"
            cat[k] += 1
            amostra.setdefault(k, (pno, [round(v) for v in r]))
    print(f"{sum(cat.values())} objetos de desenho, {len(cat)} padrões\n")
    for k, n in cat.most_common():
        pno, r = amostra[k]
        print(f"  {n:>7}  {k:52} ex.: p{pno} {r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desenhos", action="store_true")
    ap.add_argument("--perdas", action="store_true",
                    help="só o que sumiu de verdade, com página e exemplo")
    args = ap.parse_args()

    doc = fitz.open(PDF)
    if args.desenhos:
        desenhos(doc)
        return 0

    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    por_pag: dict[int, list] = defaultdict(list)
    for b in blocks:
        por_pag[b["page"]].append(b)
    # regiões que viraram imagem: figura e equação rasterizada
    imagens: dict[int, list] = defaultdict(list)
    for b in blocks:
        mb = b.get("meta") or {}
        if b["kind"] == "figure" and mb.get("bbox"):
            imagens[b["page"]].append(mb["bbox"])
        elif b["kind"] == "math" and b.get("image") and mb.get("bbox"):
            imagens[b["page"]].append(mb["bbox"])
    estilos(doc, por_pag, imagens, args.perdas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
