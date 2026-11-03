#!/usr/bin/env python3
"""
Fase 1b - Bibliografia, indexada pela chave BibTeX.

O PDF grava cada citação como destino nomeado `cite.<chave>` apontando para a
COORDENADA da entrada na bibliografia. Isso permite ligar citação e referência
sem casar strings: a chave é a mesma dos dois lados.

A bibliografia é composta em duas colunas com recuo pendente — a primeira
linha de cada entrada encosta na margem da coluna, as seguintes são recuadas.
É esse degrau que delimita uma entrada.

Saída: build/bib.json  {chave: {"text": ..., "page": n}}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from extract import (PDF, OUT, unlig, dehyphenate, COL_GAP_MIN,
                     column_origins, col_index)

# A bibliografia é composta em TRÊS colunas (margens em x≈77, 213, 349), com
# recuo pendente de ~10pt. As colunas são detectadas por página, não fixadas:
# o PyMuPDF ainda quebra uma linha visual em vários objetos quando há espaço
# horizontal, então fragmentar por x fixo misturaria colunas vizinhas.
# `column_origins`/`col_index` vivem no extract.py: o extrator, o auditor e
# esta fase precisam concordar sobre onde cada coluna começa.
INDENT_STEP = 4.0        # tolerância sobre a margem, para achar início de entrada
HANG_MIN = 5.0           # degrau do recuo pendente
BASELINE_TOL = 2.5       # variação de linha de base entre fragmentos da mesma linha


def bib_pages(doc) -> list[int]:
    """Páginas da bibliografia (antes do Subject Index)."""
    pages = []
    for pno in range(doc.page_count):
        head = doc[pno].get_text()[:300]
        if "Bibliography" in head:
            pages.append(pno)
        elif pages and "Subject Index" in head:
            break
    return pages


def page_entries(page) -> tuple[list[tuple[int, float, str]], list[float]]:
    """((coluna, y_topo, texto)…, margens das colunas) desta página."""
    frags = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"]).strip()
            if not t or t.isdigit() or t.startswith("Bibliography"):
                continue
            frags.append((l["bbox"][1], l["bbox"][0], t))
    if not frags:
        return [], []

    origins = column_origins([x for y, x, t in frags])

    def col_of(x: float) -> int:
        return col_index(x, origins)

    # junta os fragmentos da MESMA linha visual dentro da MESMA coluna.
    # A linha de base varia alguns décimos entre fragmentos ("Weizenbaum, J.
    # 1966." em y=111.8 e "ELIZA – A" em y=111.9), então a chave é uma FAIXA
    # de y, não o valor: com igualdade exata metade do título se perdia.
    lines = []
    by_col: dict[int, list[tuple[float, float, str]]] = {}
    for y, x, t in frags:
        by_col.setdefault(col_of(x), []).append((y, x, t))
    for c, items in by_col.items():
        items.sort()
        band: list[tuple[float, str]] = []
        band_y = None
        for y, x, t in items:
            if band_y is not None and y - band_y <= BASELINE_TOL:
                band.append((x, t))
            else:
                if band:
                    band.sort()
                    lines.append((c, band_y, band[0][0],
                                  " ".join(p[1] for p in band)))
                band, band_y = [(x, t)], y
        if band:
            band.sort()
            lines.append((c, band_y, band[0][0],
                          " ".join(p[1] for p in band)))
    lines.sort(key=lambda r: (r[0], r[1]))

    out: list[tuple[int, float, str]] = []
    for c in range(len(origins)):
        sel = [(y, x, t) for cc, y, x, t in lines if cc == c]
        if not sel:
            continue
        left = min(x for y, x, t in sel)
        # sem degrau de recuo pendente a coluna é de uma entrada só (ou de
        # linhas soltas): não dá para segmentar, e forçar produziria lixo
        has_hang = any(x > left + HANG_MIN for y, x, t in sel)
        cur: list[str] = []
        cur_y = 0.0
        for y, x, t in sel:
            starts = (x <= left + INDENT_STEP) if has_hang else True
            if starts:
                if cur:
                    out.append((c, cur_y, " ".join(cur)))
                cur, cur_y = [t], y
            else:
                cur.append(t)
        if cur:
            out.append((c, cur_y, " ".join(cur)))
    return out, origins


def main() -> int:
    doc = fitz.open(PDF)
    pages = bib_pages(doc)
    print(f"páginas da bibliografia: {pages[0]}–{pages[-1]} ({len(pages)})")

    # entradas por página, com posição
    entries: dict[int, list[tuple[int, float, str]]] = {}
    origins: dict[int, list[float]] = {}
    for pno in pages:
        entries[pno], origins[pno] = page_entries(doc[pno])
    total = sum(len(v) for v in entries.values())
    print(f"entradas detectadas: {total}")

    # destinos nomeados -> (página, ponto)
    names = doc.resolve_names()
    cites = {k[5:]: v for k, v in names.items() if k.startswith("cite.")}
    print(f"chaves cite.*: {len(cites)}")

    bib: dict[str, dict] = {}
    unresolved = 0
    for key, d in cites.items():
        pno = d.get("page")
        to = d.get("to")
        if pno is None or to is None or pno not in entries:
            unresolved += 1
            continue
        h = doc[pno].rect.height
        # o destino vem em coordenada PDF (origem embaixo); as linhas vêm em
        # coordenada de topo
        y_top = h - to[1]
        # A coluna vem do x do destino: sem esse filtro, uma entrada de
        # outra coluna com y parecido vence por proximidade — era assim que
        # "Weizenbaum 1976" resolvia para "Wiseman 2016".
        og = origins.get(pno) or []
        col = min(range(len(og)), key=lambda i: abs(to[0] - og[i])) if og else 0
        cands = [e for e in entries[pno] if e[0] == col] or entries[pno]
        if not cands:
            unresolved += 1
            continue
        # a entrada cujo topo está mais próximo do destino
        best = min(cands, key=lambda e: abs(e[1] - y_top))
        bib[key] = {"text": dehyphenate(unlig(best[2])), "page": pno}

    print(f"resolvidas: {len(bib)}  sem destino utilizável: {unresolved}")
    (OUT / "bib.json").write_text(
        json.dumps(bib, ensure_ascii=False, indent=1), encoding="utf-8")

    for k in ("Eliza", "j:weiz", "trnka07"):
        if k in bib:
            print(f"  {k:10} -> {bib[k]['text'][:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
