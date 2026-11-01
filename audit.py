#!/usr/bin/env python3
"""
Auditoria de fidelidade: confronta o EPUB gerado com as páginas do PDF.

Não compara pixel a pixel — o Kindle reflui, e a diagramação de duas colunas
não é o alvo. Compara CONTEÚDO e ESTRUTURA:

  * cobertura   — que texto do PDF não chegou ao EPUB (e o contrário)
  * ordem       — o texto do EPUB segue a ordem de leitura do PDF?
  * estrutura   — títulos, figuras, legendas, fórmulas e tabelas por página
  * marcação    — tags/citações/epígrafes bem formadas e no lugar

Uso:  ./venv/bin/python audit.py --cap 2
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import fitz

from extract import (PDF, OUT, unlig, dehyphenate, line_dominant_size,
                     build_vocab, HEADER_Y_MAX, FOOTER_Y_MIN, MARGIN_X_MAX,
                     column_origins, col_index, backmatter_start, toc_pages,
                     chapter_pages)

# Tag INLINE some sem deixar espaço; tag de BLOCO vira espaço. Trocar tudo
# por espaço partia "R<em>n</em>" em "R n" e o auditor acusava como perda a
# notação matemática inteira dos capítulos com muita fórmula.
INLINE_TAG = re.compile(r"</?(?:em|strong|code|span|a|i|b|sub|sup)\b[^>]*>",
                        re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def norm(t: str) -> str:
    """Normaliza para comparação: sem acento, sem pontuação, minúsculo."""
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"[^\w\s]", " ", t)
    return WS.sub(" ", t).strip().lower()


def words(t: str) -> list[str]:
    return norm(t).split()


def pdf_page_text(doc, pno: int, figs: list = None,
                  colunas: bool = False) -> tuple[str, str, str]:
    """(texto de leitura, texto dentro de figura) de uma página.

    A separação importa: as figuras deste livro são desenhos vetoriais do
    LaTeX rasterizados em PNG, e as TABELAS estão entre elas. O texto dessas
    tabelas existe na camada de texto do PDF mas, no EPUB, está dentro da
    imagem — ausente do texto e presente na leitura. Cobrá-lo como perda
    produz um falso negativo de 6% que esconde as perdas reais.
    """
    figs = figs or []
    livre, dentro, marg = [], [], []
    frags = []
    for bno, b in enumerate(doc[pno].get_text("dict")["blocks"]):
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            y = l["bbox"][1]
            if y < HEADER_Y_MAX or y > FOOTER_Y_MIN:
                continue
            t = "".join(s["text"] for s in l["spans"]).strip()
            if not t or t.isdigit():
                continue
            frags.append([y, l["bbox"][0], l, t, bno])
    # ORDEM DE LEITURA: o PyMuPDF devolve os blocos agrupados por coluna, e
    # nos exemplos interlineares isso intercala o chinês com a glosa
    # ("姚 yao 明 ming 进 enter"). Reordenar por faixa de linha de base e
    # depois por x reproduz a leitura real — sem isso o auditor acusa como
    # perda o que é só ordem dele.
    #
    # No pós-livro (3 colunas na bibliografia, 4 no índice) essa mesma regra
    # é que passa a mentir: ler por linha de base costura três entradas
    # distintas. Ali a leitura é por COLUNA, como no extract.py — e tem de ser
    # a mesma, senão o auditor cobra do EPUB uma ordem que o PDF não tem.
    if colunas:
        og = column_origins([r[1] for r in frags])
        if len(og) >= 2:
            frags.sort(key=lambda r: (col_index(r[1], og),
                                      round(r[0] / 3.0), r[1]))
        else:
            frags.sort(key=lambda r: (round(r[0] / 3.0), r[1]))
    else:
        frags.sort(key=lambda r: (round(r[0] / 3.0), r[1]))

    for y, x, l, t, bno in frags:
        # a coluna da margem é TAG, não corpo: no PDF ela cai no meio da
        # linha de texto ("the process of seg tokenization menting") e
        # apareceria como divergência que não existe
        #
        # No pós-livro não há nota de margem, e a primeira coluna começa em
        # x≈95 — dentro da faixa da margem. Sem desligar aqui (como o
        # extract.py já desliga com `no_margin`), a coluna esquerda INTEIRA
        # da bibliografia era contabilizada como tag: sobravam só os
        # fragmentos à direita das linhas justificadas, que lidos em
        # sequência parecem colunas embaralhadas e acusavam perda que o EPUB
        # não tem.
        banda = round(y / 3.0)
        if not colunas and x < MARGIN_X_MAX and line_dominant_size(l) <= 8.0:
            marg.append((banda, t))
            continue
        r = fitz.Rect(l["bbox"])
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if any(f.x0 <= cx <= f.x1 and f.y0 <= cy <= f.y1 for f in figs):
            dentro.append((banda, t))
        else:
            livre.append((banda, t))
    return montar(livre), montar(dentro), montar(marg)


def montar(itens: list[tuple[int, str]]) -> str:
    """Junta os fragmentos de uma coluna de destino, religando a hifenização.

    A palavra hifenizada continua na LINHA seguinte. A ordem por faixa de
    linha de base, porém, intercala fragmentos que dividem a mesma altura: o
    rótulo "tree" de um desenho caía entre "il-" e "lustrated" e a
    re-hifenização, que só olha vizinhos imediatos, produzia "iltree
    lustrated" — acusado como perda embora o EPUB grafe "illustrated". Daí a
    continuação ser procurada na primeira faixa SEGUINTE, saltando o que
    divide a faixa da metade de cima.

    Não serve casar pelo bloco do PyMuPDF: quando há figura no meio, as duas
    metades caem em blocos diferentes. E a junção tem de rodar DEPOIS de
    separar corpo, figura e tags — feita antes, o intruso colado era a própria
    nota de margem, e "repre-" + "sentational" saía "reprerepresentational
    sentational", que troca um artefato por outro.
    """
    itens = [list(p) for p in itens]
    for i, (banda, t) in enumerate(itens):
        if not t.endswith("-"):
            continue
        for j in range(i + 1, len(itens)):
            if itens[j][0] != banda:
                if itens[j][1]:
                    itens[i][1] += " " + itens[j][1]
                    itens[j][1] = ""
                break
    return dehyphenate(unlig(" ".join(t for _b, t in itens if t)))


def epub_texts(path: Path) -> dict[str, str]:
    """{arquivo: texto visível} de cada XHTML do EPUB."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".xhtml") and "nav" not in n:
                raw = z.read(n).decode("utf-8")
                body = raw.split("<body", 1)[-1]
                body = INLINE_TAG.sub("", body)
                txt = html.unescape(TAG_RE.sub(" ", body))
                out[n] = dehyphenate(WS.sub(" ", txt).strip())
    return out


def epub_html(path: Path) -> dict[str, str]:
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".xhtml"):
                out[n] = z.read(n).decode("utf-8")
    return out


def shingles(ws: list[str], k: int = 4) -> set[tuple]:
    return {tuple(ws[i:i + k]) for i in range(len(ws) - k + 1)}


def cobertura_caracteres(pw: list[str], ew: list[str],
                         desconto: list[str]) -> tuple[int, int, Counter]:
    """(caracteres do PDF, caracteres sem contrapartida, o que faltou).

    Presença, não ordem: cada ocorrência de palavra no PDF precisa de uma
    ocorrência correspondente no EPUB, contada com multiplicidade. É o que a
    meta pede — "o texto do PDF está todo no EPUB" —, e é diferente da
    continuidade medida por 4-gramas mais abaixo.

    As duas medidas se completam e nenhuma basta sozinha: a continuidade
    reprova diferença de ORDEM que não é perda (o rótulo de um desenho caindo
    entre as duas metades de uma palavra hifenizada respondia por 1.389 dos
    1.771 caracteres que ela acusava), e a presença isolada não perceberia um
    EPUB embaralhado, que preserva todas as palavras.
    """
    falta = Counter(pw) - Counter(ew) - Counter(desconto)
    tot = sum(len(w) * n for w, n in Counter(pw).items())
    per = sum(len(w) * n for w, n in falta.items())
    return tot, per, falta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=2)
    ap.add_argument("--epub", default="cap2-estrutura.epub")
    ap.add_argument("--livro", action="store_true",
                    help="audita o livro inteiro (usa --epub livro-*.epub)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    if args.livro:
        pages = sorted({b["page"] for b in blocks})
        lo, hi = min(pages), max(pages)
        print(f"livro inteiro: páginas {lo}–{hi} do PDF\n")
    else:
        faixa = chapter_pages(blocks, args.cap)   # o mesmo do build_epub
        if faixa is None:
            print(f"capítulo {args.cap} não encontrado")
            return 1
        lo, hi = faixa
        print(f"capítulo {args.cap}: páginas {lo}–{hi} do PDF\n")

    # bboxes das figuras, por página, para saber o que virou imagem
    # figuras E equações: as duas viram imagem, e o texto delas fica na
    # imagem — presente na leitura, ausente do texto
    figs_by_page: dict[int, list] = {}
    for b in blocks:
        mb = b.get("meta") or {}
        if b["kind"] == "figure" and mb.get("bbox"):
            figs_by_page.setdefault(b["page"], []).append(
                fitz.Rect(*mb["bbox"]))
        elif b["kind"] == "math" and b.get("image") and mb.get("bbox"):
            figs_by_page.setdefault(b["page"], []).append(
                fitz.Rect(*mb["bbox"]) + (-4, -3, 4, 3))

    doc = fitz.open(PDF)
    # `dehyphenate` só distingue hífen de quebra de hífen LEXICAL consultando
    # o vocabulário do próprio livro, e quem o preenche é `build_vocab`. Sem
    # esta chamada o auditor emendava "information-" + "retrieval" em
    # "informationretrieval" e acusava como perda a palavra que o EPUB grafa
    # certo — eram 186 das 367 divergências do corpo.
    build_vocab(doc)
    bm = backmatter_start(doc)
    pular = toc_pages(doc)
    if pular:
        print(f"(fora da comparação: sumário do original, páginas "
              f"{sorted(pular)} — substituído pelo nav.xhtml)")
    livres, dentros, margens = [], [], []
    for p in range(lo, hi + 1):
        if p in pular:
            continue
        a, b_, m_ = pdf_page_text(doc, p, figs_by_page.get(p), colunas=p >= bm)
        livres.append(a)
        dentros.append(b_)
        margens.append(m_)
    pdf_all = " ".join(livres)
    pdf_fig = " ".join(dentros)
    pdf_marg = " ".join(margens)

    ep = epub_texts(OUT / args.epub)
    # a bibliografia e a nota do tradutor são ACRÉSCIMOS nossos: não existem
    # nas páginas do PDF e inflariam o "sobra" em 9%
    #
    # No livro inteiro a bibliografia ENTRA: as páginas dela estão no recorte
    # do PDF, e tirá-la de um lado só cobraria 50 mil caracteres que o EPUB
    # tem. A nota do tradutor continua fora — essa não existe no original.
    extras = {k: v for k, v in ep.items()
              if (not args.livro and "bibliografia" in k) or "nota" in k}
    ep = {k: v for k, v in ep.items() if k not in extras}
    ep_all = " ".join(ep[k] for k in sorted(ep))
    if extras:
        print("(fora da comparação: " +
              ", ".join(f"{Path(k).name} {len(words(v)):,} palavras"
                        for k, v in extras.items()) + ")\n")

    pw, ew = words(pdf_all), words(ep_all)
    print(f"palavras  PDF: {len(pw):>7,}   EPUB: {len(ew):>7,}   "
          f"({len(ew)/max(len(pw),1)*100:.1f}%)")

    # --- COBERTURA DE CARACTERES (a meta) -----------------------------------
    desconto = words(pdf_fig) + words(pdf_marg)
    tot, per, falta_w = cobertura_caracteres(pw, ew, desconto)
    print(f"\nCOBERTURA DE CARACTERES: {(tot - per) / max(tot, 1) * 100:.4f}%"
          f"   ({per:,} de {tot:,} sem contrapartida no EPUB)")
    if falta_w:
        print("  o que ficou sem contrapartida:")
        for w, n in sorted(falta_w.items(),
                           key=lambda kv: -len(kv[0]) * kv[1])[:12]:
            print(f"    {w[:30]:<32} ×{n:<4} {len(w) * n:>4} car")

    # --- cobertura por shingles (tolera reordenação local) ------------------
    ps, es = shingles(pw), shingles(ew)
    fs = shingles(words(pdf_fig)) | shingles(words(pdf_marg))
    falta = ps - es
    em_fig = falta & fs
    falta = falta - fs
    print(f"(dentro de figura/equação ou na coluna de tags: "
          f"{len(em_fig):,} trechos)")
    print(f"(tags no PDF: {len(words(pdf_marg)):,} palavras)")
    sobra = es - ps
    print(f"continuidade — 4-gramas do PDF ausentes no EPUB: {len(falta):,} "
          f"de {len(ps):,}  ({len(falta)/max(len(ps),1)*100:.1f}%)")
    print(f"trechos do EPUB que não estão no PDF:       {len(sobra):,}")

    # --- o que sumiu, agrupado em passagens contíguas ----------------------
    if falta:
        miss_idx = [i for i in range(len(pw) - 3)
                    if tuple(pw[i:i + 4]) in falta]
        runs, cur = [], []
        for i in miss_idx:
            if cur and i - cur[-1] <= 4:
                cur.append(i)
            else:
                if cur:
                    runs.append(cur)
                cur = [i]
        if cur:
            runs.append(cur)
        runs.sort(key=len, reverse=True)
        print(f"\n--- maiores passagens ausentes ({len(runs)} trechos) ---")
        for r in runs[:12]:
            frag = " ".join(pw[r[0]:r[-1] + 5])
            print(f"  [{len(r)+3:>4} palavras] {frag[:150]}")

    # --- estrutura ----------------------------------------------------------
    hs = epub_html(OUT / args.epub)
    corpo = "\n".join(v for k, v in hs.items() if "nav" not in k)
    print("\n--- estrutura no EPUB ---")
    for nome, pat in (("aberturas", r'class="abertura"'),
                      ("epígrafes", r'class="epigrafe"'),
                      ("atribuições", r'class="atrib"'),
                      ("tags", r'class="tagchip"'),
                      ("citações", r'class="cite"'),
                      ("figuras", r"<figure"),
                      ("legendas", r"<figcaption"),
                      ("fórmulas", r'class="formula"'),
                      ("exemplos", r'class="exemplo"'),
                      ("código", r"<pre>"),
                      ("h1", r"<h1"), ("h2", r"<h2"), ("h3", r"<h3")):
        print(f"  {nome:12} {len(re.findall(pat, corpo)):>4}")

    # --- contagem equivalente no PDF ---------------------------------------
    sel = [b for b in blocks if lo <= b["page"] <= hi]
    c = Counter(b["kind"] for b in sel)
    print("\n--- blocos extraídos do PDF (mesmo intervalo) ---")
    for k, v in c.most_common():
        print(f"  {k:16} {v:>4}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
