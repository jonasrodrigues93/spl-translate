#!/usr/bin/env python3
"""
Fase 1 - Extração estrutural do ed3book_jan26.pdf.

O PDF vem do pdfTeX e tem camada de texto nativa, então nada de OCR: lemos os
spans com fonte/tamanho/posição e reconstruímos a semântica a partir disso.

Saída: blocks.json (lista ordenada de blocos semânticos) + images/.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
# O PDF acompanha este checkout; ED3BOOK_PDF permite apontar para outra cópia.
PDF = (Path(os.environ["ED3BOOK_PDF"])
       if "ED3BOOK_PDF" in os.environ else HERE / "ed3book_jan26.pdf")
OUT = HERE / "build"

# --- perfil tipográfico, derivado da análise do PDF -------------------------
BODY = ("NimbusRomNo9L-Regu", 10.0)
MONO_FONTS = {"txtt", "tcxtt"}
BOLD_FONTS = {"NimbusRomNo9L-Medi", "CMSSBX10"}
ITAL_FONTS = {"NimbusRomNo9L-ReguItal", "PazoMath-Italic", "CMMI10"}
# Fontes de fórmula: se um bloco é majoritariamente delas, é matemática.
MATH_FONTS = {"CMSY10", "CMEX10", "CMMI10", "CMR10", "PazoMath-Italic",
              "StandardSymL-Slant_167", "TeX-xipasl10"}

MARGIN_X_MAX = 135.0   # notas de margem ficam à esquerda da caixa de texto
BODY_X_MIN = 138.0
HEADER_Y_MAX = 95.0    # cabeçalho corrente (CHAPTER N • TÍTULO)
FOOTER_Y_MIN = 730.0

# Numeral de capítulo: glifo de 59.8pt na abertura. Sem este piso ele cai na
# regra "linha só de dígitos = número de página" e some — era por isso que a
# abertura chegava ao EPUB como "CHAPTER" solto e um <h1> sem numeral.
CHAPNUM_MIN_SIZE = 40.0

# Rótulo "CHAPTER" da abertura: cinza, 12pt, na coluna da margem. É plataforma
# tipográfica do numeral, não conteúdo — o EPUB reconstrói esse rótulo.
CHAP_LABEL_RE = re.compile(r"^chapter$", re.I)

# Uma tag de duas linhas ("regular" / "expressions") tem entrelinha de ~6pt —
# a da própria margem, em corpo 7.2. Duas tags DISTINTAS ficam a ~12pt, que é
# a entrelinha do corpo, porque cada uma se alinha à linha que anota. A
# distribuição medida no livro é bimodal (6pt: 63 casos, 12pt: 18), então o
# corte fica no meio: acima de 8pt são termos diferentes.
MARGIN_LINE_GAP = 8.0

# Recuo de primeira linha de parágrafo (~15pt no original)
PARA_INDENT_MIN = 8.0
PARA_HANG_TOL = 4.0      # tolerância sobre a margem da coluna, no pós-livro

# Exemplo numerado de linguística: "(2.3)" em azul na margem do corpo, com o
# conteúdo recuado à direita e, quando há glosa interlinear, uma segunda
# linha alinhada às mesmas colunas. É estrutura, não parágrafo.
NUMEX_RE = re.compile(r"^\((\d+\.\d+)\)\s")

# Equação deslocada e numerada: o conteúdo vem centrado e o número encostado
# na margem direita, na mesma linha de base. A detecção por fonte matemática
# não pega: o LaTeX compõe |V| = kN^β com a romana do corpo em itálico, e o
# número "(2.5)" ainda derruba a proporção de glifos matemáticos abaixo do
# limiar. Resultado: a equação virava prosa colada no parágrafo seguinte.
EQNUM_RE = re.compile(r"\((\d+\.\d+)\)\s*$")

# Epígrafe: delimitada pela ATRIBUIÇÃO, não pelo recuo do corpo dela. O recuo
# varia demais (o diálogo do ELIZA entra em x=209, a citação de Austen em
# x=168), enquanto a atribuição é sempre uma linha curta encostada na borda
# direita. O corpo justificado também encosta na direita, mas começa em
# x=138 — daí o piso de recuo aplicado só à atribuição.
ATTRIB_INDENT_MIN = BODY_X_MIN + 60.0
RIGHT_ALIGN_TOL = 4.0
EPI_MAX_LINES = 25       # janela de busca da atribuição após o título
EPI_WINDOW = 16          # a epígrafe é curta: só as primeiras linhas contam


# --- fontes que mentem sobre o próprio conteúdo -----------------------------
# A WSUIPA (TeX-xipa10 / xipasl10) desenha símbolos do AFI nos slots ASCII e
# não traz ToUnicode, então o extrator devolvia o código cru: o exemplo (2.9)
# do coriaque saía "t-@-nk’e-mejN-@-jetem@-nni-k" em vez de
# "t-ə-nk’e-mejŋ-ə-jetemə-nni-k". A tabela abaixo foi lida do espécime — cada
# glifo foi recortado do PDF e conferido a olho, não deduzido da convenção.
XIPA = {
    "2": "ʌ", "@": "ə", "A": "ɑ", "D": "ð", "E": "ɛ", "I": "ɪ",
    "N": "ŋ", "O": "ɔ", "S": "ʃ", "T": "θ", "U": "ʊ", "Z": "ʒ",
    "Ç": "ɝ",
    # conferidos como idênticos à letra latina no mesmo espécime
    "a": "a", "e": "e", "i": "i", "o": "o", "p": "p", "u": "u",
    "w": "w", "y": "y", "æ": "æ", "[": "[", "]": "]",
}

# CMEX10 guarda delimitadores extensíveis em slots de controle. Quase todos
# acabam dentro da imagem da equação, mas dois escapam para o texto corrido:
# a chave grande de uma expressão por casos, e a barra do \not — que o TeX
# posiciona ANTES da letra, como faz com os acentos.
# Mesmo código, glifos diferentes conforme a fonte — daí o mapa ser por
# família, e cada entrada ter sido conferida recortando o glifo do PDF.
GLYPHS = {
    "CMEX": {"\x1a": "{", "\x13": ")"},        # chave e parêntese grandes
    "LINE": {"\x13": "\u0338"},                 # a barra do \not
}

# Famílias cujo glifo NÃO corresponde ao code point: matemáticas, de símbolo
# e fonéticas. Texto vindo delas precisa de tabela própria — ou é suspeito.
SUSPECT_FONTS = re.compile(
    r"^(CM(SY|EX|MI|BSY)|MSAM|MSBM|EUSM|EURM|StandardSymL|LINE\d|"
    r"TeX-(vect|xipa))", re.I)

# registro da validação: (fonte, caractere) sem mapeamento conhecido
UNMAPPED: "Counter[tuple[str, str]]" = Counter()


def decode_span(s: dict) -> str:
    """Texto de um span, com as fontes de glifo remapeadas para Unicode."""
    f = base_font(s["font"])
    t = s["text"]
    if f.startswith("TeX-xipa"):
        out = []
        for ch in t:
            if ch in XIPA:
                out.append(XIPA[ch])
            elif ch.strip():
                UNMAPPED[(f, ch)] += 1
                out.append(ch)
            else:
                out.append(ch)
        return "".join(out)
    for pref, tbl in GLYPHS.items():
        if f.startswith(pref) and any(c in tbl for c in t):
            return "".join(tbl.get(c, c) for c in t)
    if SUSPECT_FONTS.match(f):
        # Só o ASCII acusa: essas fontes resolvem bem os símbolos de verdade
        # (→, ∈, σ, ∂ saem certos), mas seus slots A-Z/a-z/0-9 guardam
        # glifos que NÃO são aquelas letras — é exatamente onde o texto sai
        # errado sem ninguém notar.
        for ch in t:
            if ch.isascii() and ch.isalnum():
                UNMAPPED[(f, ch)] += 1
    return t


# O pdfTeX emite ligaduras tipográficas como um único code point.
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
             "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


# O pdfTeX emite letra acentuada como DOIS glifos, o acento ANTES da base:
# "y´ao m´ıng j`ın r`u zˇong" em vez de "yáo míng jìn rù zǒng". E usa o i sem
# pingo (U+0131) sob acento, como manda a tipografia do LaTeX. Sem desfazer
# isso, todo pinyin, todo nome francês ("Tesni`ere") e todo título alemão da
# bibliografia chegam ao EPUB quebrados.
ACCENTS = {"\u00b4": "\u0301", "`": "\u0300", "\u02c6": "\u0302",
           "\u02dc": "\u0303", "\u00af": "\u0304", "\u02d8": "\u0306",
           "\u02d9": "\u0307", "\u00a8": "\u0308", "\u02da": "\u030a",
           "\u02c7": "\u030c", "\u00b8": "\u0327",
           "\u0338": "\u0338"}
DOTLESS = {"\u0131": "i", "\u0237": "j"}
ACCENT_RE = re.compile("([" + "".join(ACCENTS) + r"])([A-Za-z\u0131\u0237])")


def fix_accents(t: str) -> str:
    def sub(m):
        base = DOTLESS.get(m.group(2), m.group(2))
        return unicodedata.normalize("NFC", base + ACCENTS[m.group(1)])
    return ACCENT_RE.sub(sub, t)


def unlig(t: str) -> str:
    """Desfaz ligaduras tipográficas e acentos partidos do pdfTeX."""
    for k, v in LIGATURES.items():
        t = t.replace(k, v)
    return fix_accents(t)


# "intro-" no fim da linha + "duce" na seguinte = palavra quebrada pelo LaTeX.
# Mas o LaTeX também quebra em hífen LEXICAL, e aí colar destrói o termo:
# "byte- pair" virava "bytepair", "cross- entropy" virava "crossentropy".
# Medido no livro: de 2.148 quebras com hífen, 87 são lexicais.
#
# Quem decide é o vocabulário do próprio livro, colhido das linhas inteiras
# (onde não há quebra): se "byte-pair" aparece como composta e "bytepair"
# nunca aparece sólida, o hífen fica.
VOCAB_COMPOSTA: "Counter[str]" = Counter()
VOCAB_SOLIDA: "Counter[str]" = Counter()

PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)+|[A-Za-zÀ-ÿ]+")
DEHYPH = re.compile(r"([A-Za-zÀ-ÿ]{2,})-(\s+)([a-zà-ÿ]+)")
# marcador de estilo bem na quebra: "«i»dif-«/i» «i»ferent«/i»". O fecha-abre
# do mesmo marcador é ruído da quebra de linha, não mudança de estilo.
MARCA_QUEBRA = re.compile(r"-«/(i|b|code|sup|sub)»\s+«\1»")


def build_vocab(doc) -> None:
    """Colhe o vocabulário das linhas inteiras do PDF."""
    VOCAB_COMPOSTA.clear()
    VOCAB_SOLIDA.clear()
    for pno in range(doc.page_count):
        for b in doc[pno].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                t = unlig("".join(s["text"] for s in l["spans"]))
                for w in PALAVRA.findall(t):
                    if "-" in w:
                        VOCAB_COMPOSTA[w.lower()] += 1
                    else:
                        VOCAB_SOLIDA[w.lower()] += 1


def dehyphenate(t: str) -> str:
    t = MARCA_QUEBRA.sub("- ", t)

    def sub(m):
        a, b = m.group(1), m.group(3)
        comp = f"{a.lower()}-{b.lower()}"
        if (VOCAB_COMPOSTA.get(comp, 0) >= 2
                and VOCAB_SOLIDA.get(f"{a}{b}".lower(), 0) == 0):
            return f"{a}-{b}"          # hífen lexical: preserva
        return f"{a}{b}"
    return DEHYPH.sub(sub, t)


def norm_title(t: str) -> str:
    """'2.1 Words' e 'Words' colapsam na mesma chave, para casar com o sumário."""
    t = re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", t)
    t = re.sub(r"[^\w\s]", "", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip().lower()


def base_font(name: str) -> str:
    """OTTAOG+NimbusRomNo9L-Regu -> NimbusRomNo9L-Regu"""
    return name.split("+")[-1]


@dataclass
class Block:
    kind: str                 # heading1|heading2|heading3|para|margin|code|figure|caption|math|table
    text: str = ""
    page: int = 0             # índice 0-based no PDF
    level: int = 0
    image: str | None = None
    translate: bool = True
    meta: dict = field(default_factory=dict)


def span_style(s: dict) -> str:
    f = base_font(s["font"])
    if f in MONO_FONTS:
        return "mono"
    if f in BOLD_FONTS:
        return "bold"
    if f in ITAL_FONTS:
        return "ital"
    return "plain"


def line_text_styled(line: dict) -> str:
    """Serializa uma linha preservando itálico/negrito/mono como marcadores
    inline leves, que sobrevivem à tradução melhor que HTML puro."""
    out = []
    corpo = line_dominant_size(line)
    # Banda de referência: o fundo dos spans no corpo dominante da linha.
    # Um dígito pequeno acima dela é expoente ou chamada de nota; um dígito
    # pequeno sentado nela é índice. A distribuição medida no livro é
    # bimodal, com vale limpo em −3pt: −6/−4 de um lado, −1/+1 do outro.
    _ref = [sp for sp in line["spans"] if abs(sp["size"] - corpo) < 0.6]
    base = max((sp["bbox"][3] for sp in _ref), default=None)
    for s in line["spans"]:
        t = decode_span(s)
        if not t:
            continue
        # Dígito pequeno: sem marcá-lo, chegava colado à palavra —
        # "running words.1 If we" parecia erro de digitação, e "w1:n" perdia
        # o índice.
        if (corpo >= 9.5 and base is not None and s["size"] < corpo - 1.5
                and t.strip().isdigit() and len(t.strip()) <= 2):
            alto = s["bbox"][3] - base < -3.0
            tag = "sup" if alto else "sub"
            out.append(f"«{tag}»{t.strip()}«/{tag}»")
            continue
        st = span_style(s)
        if st == "mono":
            out.append(f"«code»{t}«/code»")
        elif st == "bold":
            out.append(f"«b»{t}«/b»")
        elif st == "ital":
            out.append(f"«i»{t}«/i»")
        else:
            out.append(t)
    txt = "".join(out)
    # colapsa marcadores adjacentes idênticos: «i»a«/i»«i»b«/i» -> «i»ab«/i»
    for tag in ("code", "b", "i", "sup", "sub"):
        txt = txt.replace(f"«/{tag}»«{tag}»", "")
    return txt


def page_cites(page) -> list[tuple[fitz.Rect, str]]:
    """Retângulos de citação da página, vindos das anotações de link.

    O PDF do pdfTeX grava cada citação como destino nomeado `cite.<chave>`
    apontando para a entrada na bibliografia — 3.788 delas no livro. Os rects
    são justos e por span, então casam 1:1 com o texto azul. Isso torna
    desnecessário adivinhar citação por regex sobre "Autor (ano)".
    """
    out = []
    for l in page.get_links():
        nd = l.get("nameddest", "")
        if l.get("kind") == fitz.LINK_NAMED and nd.startswith("cite."):
            out.append((fitz.Rect(l["from"]), nd[5:]))
    return out


def line_cite_spans(line: dict, cites: list[tuple[fitz.Rect, str]]
                    ) -> list[tuple[str, str]]:
    """(chave, texto de superfície) das citações presentes na linha.

    As marcas NÃO entram no texto que vai para o tradutor: uma chave como
    `j:weiz` no meio da frase é convite para o modelo "corrigir" o que não
    entende. Ficam nos metadados do bloco, e a montagem religa pelo texto de
    superfície — sobrenome e ano atravessam a tradução intactos.
    """
    found: list[tuple[str, str]] = []
    for s in line["spans"]:
        t = s["text"].strip()
        if not t:
            continue
        b = s["bbox"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for rect, key in cites:
            if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
                if found and found[-1][0] == key:
                    found[-1] = (key, f"{found[-1][1]} {t}")
                else:
                    found.append((key, t))
                break
    # desifeniza aqui: a quebra do LaTeX deixa "Sen- nrich et al. 2016", e a
    # montagem religa a citação procurando este texto DENTRO do parágrafo
    # traduzido — que já vem desifenizado. Sem isso, nada casa.
    return [(k, dehyphenate(unlig(v))) for k, v in found]


# --------------------------------------------------------------------------
# Colunas. Usadas pelo pós-livro (bibliografia em três, índice remissivo em
# quatro) tanto aqui quanto no bib.py e no audit.py — uma definição só, para
# que extrator e auditor concordem sobre o que é uma coluna.
COL_GAP_MIN = 40.0       # distância que separa uma coluna da seguinte


def column_origins(xs: list[float]) -> list[float]:
    """Margens das colunas, pelos x0 RECORRENTES da página.

    Agrupar os x0 crus não funciona: fragmentos de meio de linha aparecem em
    qualquer x, e um agrupamento por distância produzia sete "colunas" numa
    página de três. Os x0 que se repetem são só dois por coluna — a margem da
    entrada e o recuo pendente —, e a margem é o menor dos dois.
    """
    counts = Counter(round(x, 1) for x in xs)
    strong = sorted(v for v, n in counts.items() if n >= 3)
    if not strong:
        strong = sorted(set(round(x, 1) for x in xs))
    origins: list[float] = []
    for v in strong:
        if not origins or v - origins[-1] > COL_GAP_MIN:
            origins.append(v)
    return origins


def col_index(x: float, origins: list[float]) -> int:
    """Coluna a que pertence uma abscissa (a maior margem à esquerda dela)."""
    c = 0
    for i, o in enumerate(origins):
        if x >= o - 2.0:
            c = i
    return c


def toc_pages(doc) -> set[int]:
    """Páginas do sumário do original: "1 Introduction . . . . . 3".

    Não são traduzidas (trabalho perdido) nem entram no EPUB, que gera a
    própria navegação a partir do nav.xhtml. Detecta pelos pontos-guia.
    O auditor precisa da MESMA lista: cobrar do EPUB um sumário que se
    decidiu não ter acusava 1.311 passagens ausentes que são a decisão.
    """
    skip: set[int] = set()
    for pno in range(min(20, doc.page_count)):
        t = doc[pno].get_text()
        if t.count(". . .") >= 8 or t.count("....") >= 8:
            skip.add(pno)
    return skip


def chapter_pages(blocks: list[dict], cap: int) -> tuple[int, int] | None:
    """Intervalo de páginas do capítulo `cap`, ou None se não existir.

    O recorte vem das seções numeradas "N.x", ancorado na abertura do
    capítulo — que pode estar várias páginas antes da primeira seção (no
    cap. 23 são três). Um capítulo SEM seção numerada existe: o 1 deste
    rascunho é só título e epígrafe, e por ele o tradutor e o montador
    respondiam "capítulo 1 não encontrado". Nesse caso o intervalo vai da
    abertura até a véspera da abertura seguinte.

    Uma função só para os três: recorte diferente entre tradutor e montador
    desalinha índice de bloco com tradução, e o EPUB sai como recorte
    aleatório.
    """
    def num(b):
        return ((b.get("meta") or {}).get("num") or "")

    def chapnum(b):
        return (b.get("meta") or {}).get("chapnum")

    ab = [b["page"] for b in blocks if chapnum(b) == str(cap)]
    pgs = [b["page"] for b in blocks
           if b["kind"].startswith("heading") and num(b).startswith(f"{cap}.")]
    if not pgs and not ab:
        return None
    lo = min(ab) if ab else min(pgs) - 1
    if pgs:
        lo = min(lo, min(pgs) - 1)
    # A folga de 3 páginas cobre as seções finais (resumo, notas, exercícios),
    # que vêm depois da última "N.x". Mas cada capítulo abre em página nova, e
    # sem parar na véspera da seguinte a folga invadia o capítulo posterior:
    # o cap. 2 ia até a 45, onde o 3 começa, e a prévia saía com um capítulo 3
    # truncado no fim.
    seguintes = [b["page"] for b in blocks
                 if chapnum(b) and chapnum(b) != str(cap) and b["page"] > lo]
    hi = max(pgs) + 3 if pgs else lo
    if seguintes:
        hi = min(hi, min(seguintes) - 1)
    return lo, max(hi, lo)


def backmatter_start(doc) -> int:
    """Primeira página do pós-livro (Bibliography / Subject Index).

    Duas razões para conhecer esse limite: ali as notas de margem são
    desligadas — a coluna da esquerda cai inteira dentro da faixa x da margem,
    e entradas como "$ (re end-of-line), 21" entravam como nota (3.294 dos
    3.843 blocos margin vinham daí) — e ali a leitura passa a ser por coluna.
    O auditor precisa do MESMO limite: se ele ler em colunas uma página que o
    extrator leu em linhas (ou o inverso), a divergência é dele, não do EPUB.
    """
    start = doc.page_count
    for pno in range(doc.page_count - 1, max(doc.page_count - 60, 0), -1):
        head = doc[pno].get_text()[:400]
        if "Bibliography" in head or "Subject Index" in head:
            start = pno
    return start


def line_dominant_size(line: dict) -> float:
    best, n = 0.0, 0
    for s in line["spans"]:
        if len(s["text"]) > n:
            n, best = len(s["text"]), s["size"]
    return round(best, 1)


def line_math_ratio(line: dict) -> float:
    tot = sum(len(s["text"]) for s in line["spans"]) or 1
    m = sum(len(s["text"]) for s in line["spans"]
            if base_font(s["font"]) in MATH_FONTS)
    return m / tot


def is_mono_line(line: dict) -> bool:
    tot = sum(len(s["text"].strip()) for s in line["spans"]) or 1
    m = sum(len(s["text"].strip()) for s in line["spans"]
            if base_font(s["font"]) in MONO_FONTS)
    return m / tot > 0.6


# "2.1 Words" / "2.6.4 Disjunction, Grouping..." -> captura a numeração
SEC_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
# Sinais de código real, para separar de exemplos linguísticos em monoespaçada
CODEY_RE = re.compile(r"[=(){}\[\];|\\<>#]|\br\"|^\s*(def|for|if|while|import|return)\b")


FIG_DPI = 150          # legível no Kindle sem inflar o arquivo


def figure_regions(page, pd) -> list[fitz.Rect]:
    """Encontra as regiões de figura de uma página.

    Une os desenhos vetoriais (page.get_drawings) e as imagens embutidas em
    aglomerados, e descarta o que é régua de tabela ou filete tipográfico:
    faixas muito finas ou que ocupam quase toda a largura com 2pt de altura.
    """
    boxes: list[fitz.Rect] = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width < 3 or r.height < 3:        # filete/linha de tabela
            continue
        if r.height < 6 and r.width > 300:     # régua horizontal
            continue
        boxes.append(r)
    for b in pd["blocks"]:
        if b["type"] == 1:
            boxes.append(fitz.Rect(b["bbox"]))
    if not boxes:
        return []

    # aglomera caixas próximas (mesma figura desenhada em muitos traços)
    boxes.sort(key=lambda r: (r.y0, r.x0))
    clusters: list[fitz.Rect] = []
    for r in boxes:
        placed = False
        for k, c in enumerate(clusters):
            grown = fitz.Rect(c)
            grown.y1 += 18          # tolerância vertical entre traços
            grown.x0 -= 12
            grown.x1 += 12
            if grown.intersects(r):
                clusters[k] = c | r
                placed = True
                break
        if not placed:
            clusters.append(fitz.Rect(r))

    out = []
    for c in clusters:
        if c.width < 40 or c.height < 25:      # ruído
            continue
        if c.get_area() < 2500:
            continue
        c = c + (-4, -4, 4, 4)                 # respiro
        c &= page.rect
        out.append(c)

    # A legenda encosta na figura, e o aglomerado a engolia: a primeira linha
    # do figcaption saía ASSADA no PNG, cortada ao meio, e ainda repetida
    # embaixo como texto. Corta a região logo acima da legenda.
    cap_ys = []
    for b in pd["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            t = "".join(sp["text"] for sp in l["spans"]).strip()
            if re.match(r"^(Figure|Table)\s+\d", t):
                cap_ys.append(l["bbox"][1])
    keep = []
    for r in out:
        below = [y for y in cap_ys if r.y0 + 10 < y < r.y1]
        if below:
            r.y1 = min(below) - 3
        if r.height >= 25 and r.get_area() >= 2500:
            keep.append(r)
    return keep


# Nota de rodapé: o LaTeX desenha um \footnoterule de 0.4 da largura da
# coluna logo acima dela. O filete é o âncora — mais confiável que o corpo
# menor sozinho, que também descreve legenda e atribuição de epígrafe.
# Medido no livro: 37 páginas têm esse filete, e em TODAS o que vem abaixo é
# corpo < 9pt. Sem tratá-lo, a nota entrava no fluxo como se fosse prosa.
FOOTRULE_W = (60.0, 140.0)
FOOTRULE_Y_MIN = 600.0
FOOTNOTE_NUM = re.compile(r"^(\d{1,2})\s+(?=\S)")


def footnote_y(page, body_left: float) -> float | None:
    """Altura do filete que abre as notas de rodapé, se houver."""
    ys = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if (r.height <= 1.0 and FOOTRULE_W[0] < r.width < FOOTRULE_W[1]
                and abs(r.x0 - body_left) <= 3.0 and r.y0 > FOOTRULE_Y_MIN):
            ys.append(r.y0)
    return min(ys) if ys else None


def frame_regions(page) -> list[fitz.Rect]:
    """Molduras de caixa (algoritmo, pseudocódigo) desenhadas como 4 filetes.

    O LaTeX compõe esses quadros com dois filetes horizontais e dois
    verticais de espessura zero. O detector de figura descarta qualquer traço
    com menos de 3pt de lado, então a moldura era invisível e a listagem
    chegava ao EPUB como parágrafos soltos, sem o quadro que a delimita.

    O texto NÃO é rasterizado: virar imagem congelaria o pseudocódigo em
    inglês para sempre. Só a moldura é reconstruída, em CSS.
    """
    hs, vs = [], []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.height <= 1.5 and r.width > 150:
            hs.append(r)
        elif r.width <= 1.5 and r.height > 30:
            vs.append(r)
    out = []
    used = set()
    for i, top in enumerate(hs):
        for j, bot in enumerate(hs):
            if j <= i or j in used or i in used:
                continue
            if (abs(top.x0 - bot.x0) <= 3 and abs(top.x1 - bot.x1) <= 3
                    and bot.y0 - top.y1 > 30):
                # precisa de pelo menos um filete vertical ligando os dois
                # tolerância folgada nas pontas: no quadro da fig. 2.16 os
                # filetes verticais descem 9.8pt abaixo do filete inferior,
                # e com 6pt de folga a moldura não era reconhecida
                if any(abs(v.y0 - top.y0) <= 12 and abs(v.y1 - bot.y1) <= 12
                       for v in vs):
                    out.append(fitz.Rect(top.x0, top.y0, top.x1, bot.y1))
                    used.add(i)
                    used.add(j)
                    break
    return out


# Um quadro pode ser duas coisas muito diferentes. A listagem de algoritmo é
# texto corrido dentro de uma moldura: reflui bem e PRECISA continuar texto,
# para ser traduzida. Já o diagrama — o alinhamento da fig. 2.17, o caminho
# com setas da 2.19, as matrizes de atenção — tem o sentido no ARRANJO
# ESPACIAL: em coluna, com setas desenhadas. Como texto ele vira ruído
# ("intention delete i ntention substitute n by e"), então tem de virar
# imagem, como no impresso.
#
# Dois sinais separam os casos, medidos nos 236 quadros do livro:
#   * fração de tokens de um caractere — 1.00 no alinhamento da 2.17,
#     0.18-0.30 nas listagens "function ...";
#   * desenhos internos além da própria moldura — as setas, os nós, as
#     células das matrizes.
DIAG_UNIGRAM_MIN = 0.55
DIAG_DRAWINGS_MIN = 3


def is_diagram(rect, page, pd) -> bool:
    """O conteúdo do quadro depende do arranjo espacial?"""
    toks = []
    for b in pd["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            bb = l["bbox"]
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
                toks += "".join(sp["text"] for sp in l["spans"]).split()
    if not toks:
        return True                      # moldura sem texto é desenho
    uni = sum(1 for t in toks if len(t) == 1) / len(toks)
    inner = 0
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if (rect.x0 + 3 < cx < rect.x1 - 3 and rect.y0 + 3 < cy < rect.y1 - 3
                and not (r.width > rect.width * 0.9
                         or r.height > rect.height * 0.9)):
            inner += 1
    return uni > DIAG_UNIGRAM_MIN or inner >= DIAG_DRAWINGS_MIN


def extract(pdf_path: Path, out_dir: Path) -> list[Block]:
    doc = fitz.open(pdf_path)
    build_vocab(doc)
    print(f"vocabulário: {len(VOCAB_SOLIDA):,} palavras sólidas, "
          f"{len(VOCAB_COMPOSTA):,} compostas")
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # Índice: mapeia página -> entradas de sumário que começam nela.
    toc = doc.get_toc()  # [level, title, page(1-based)]
    toc_by_page: dict[int, list] = {}
    # Índice título-normalizado -> nível, para corrigir a classificação por
    # fonte. Esta é a hierarquia que o próprio LaTeX gravou: é autoritativa,
    # ao contrário do corpo da fonte, que não distingue seção de subseção.
    toc_level: dict[str, int] = {}
    for lvl, title, pg in toc:
        toc_by_page.setdefault(pg - 1, []).append((lvl, title))
        toc_level.setdefault(norm_title(title), lvl)

    skip_pages = toc_pages(doc)
    if skip_pages:
        print(f"páginas de sumário ignoradas: {sorted(skip_pages)}")

    backmatter_from = backmatter_start(doc)
    print(f"pós-livro (sem notas de margem) a partir da página {backmatter_from}")

    blocks: list[Block] = []
    img_seq = 0

    for pno in range(doc.page_count):
        if pno in skip_pages:
            continue
        page = doc[pno]
        pd = page.get_text("dict")
        no_margin = pno >= backmatter_from
        cites = page_cites(page)

        # --- figuras ------------------------------------------------------
        # As figuras deste livro são desenhos VETORIAIS do LaTeX (tikz/pgf),
        # não imagens embutidas: extrair só blocos type==1 pega 7 de 22 no
        # cap.2, e o que pega costuma ser fragmento ou máscara. O certo é
        # rasterizar a região da página ocupada pelo desenho.
        fig_rects = figure_regions(page, pd)
        all_frames = frame_regions(page)
        # o diagrama emoldurado vira figura (texto suprimido e rasterizado);
        # a caixa de algoritmo continua texto, com a moldura refeita em CSS
        frames = []
        for fr in all_frames:
            if is_diagram(fr, page, pd):
                if not any(abs(g.x0 - fr.x0) < 12 and abs(g.y0 - fr.y0) < 12
                           for g in fig_rects):
                    fig_rects.append(fr + (-2, -2, 2, 2))
            else:
                frames.append(fr)
        fig_rects.sort(key=lambda r: (r.y0, r.x0))
        for r in fig_rects:
            img_seq += 1
            name = f"fig{img_seq:04d}.png"
            try:
                pix = page.get_pixmap(clip=r, dpi=FIG_DPI)
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(img_dir / name)
            except Exception:
                continue
            blocks.append(Block(kind="figure", page=pno, image=name,
                                translate=False,
                                meta={"bbox": [round(v) for v in r],
                                      "y": r.y0}))

        # --- linhas de texto ----------------------------------------------
        # O PyMuPDF quebra uma linha visual em vários objetos quando há espaço
        # horizontal (ex.: "2.1" em x=142 e "Words" em x=178 são duas "linhas").
        # Sem juntar por linha de base, títulos viram dois blocos e o texto da
        # legenda vaza para o parágrafo seguinte.
        raw_lines = []
        for b in pd["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                txt = "".join(s["text"] for s in l["spans"])
                if not txt.strip():
                    continue
                raw_lines.append((l["bbox"][1], l["bbox"][0], l))

        # ORDEM DE LEITURA EM COLUNAS. O pós-livro é composto em três colunas
        # (bibliografia) e quatro (índice remissivo). Ordenar por (y, x) lê
        # ATRAVESSANDO as colunas e produz "Department, Istanbul University
        # (3), tic Coreference. Bamman, D., ..." — três entradas distintas
        # costuradas pela linha de base. Ordenar por (coluna, y) lê cada
        # coluna inteira antes da seguinte, que é a leitura real.
        #
        # Só no pós-livro: no corpo, a coluna da margem fica a menos de
        # COL_GAP_MIN do corpo e seria promovida a coluna, o que jogaria
        # todas as notas de margem da página para antes do texto.
        col_origins: list[float] = []
        if no_margin:
            og = column_origins([x for _y, x, _l in raw_lines])
            if len(og) >= 2:
                col_origins = og

        def col_of(x: float) -> int:
            """Coluna de uma abscissa; 0 fora do pós-livro (página de uma só).

            Deriva do x, não da identidade da linha: a linha que chega à
            segmentação de parágrafo é o objeto FUNDIDO da faixa, e um mapa
            por id() do objeto original não a encontra.
            """
            return col_index(x, col_origins) if col_origins else 0

        raw_lines.sort(key=lambda t: (col_of(t[1]), t[0], t[1]))

        # Agrupa fragmentos em FAIXAS de linha de base e ordena cada faixa
        # pelo x real. Concatenar na ordem de leitura (y, x) embaralha as
        # linhas cujos fragmentos têm linhas de base ligeiramente diferentes
        # — o caso dos exemplos com caracteres chineses, em que cada glifo
        # assenta 1 ou 2pt acima ou abaixo dos vizinhos e
        # "(2.4) 姚 明 进 入 总 决 赛" saía "明 (2.4) 入 决 进 总 姚 赛".
        def _marginish(x: float, l: dict) -> bool:
            return x < MARGIN_X_MAX and line_dominant_size(l) <= 8.0

        bands: list[list[tuple[float, float, dict]]] = []
        for y, x, l in raw_lines:
            mk = _marginish(x, l)
            if bands:
                ay, ax, al = bands[-1][0]
                # em página de colunas, mesma linha de base NÃO é a mesma
                # linha: é uma entrada por coluna, lado a lado
                same_col = col_of(ax) == col_of(x)
                if abs(ay - y) <= 2.5 and _marginish(ax, al) == mk and same_col:
                    bands[-1].append((y, x, l))
                    continue
            bands.append([(y, x, l)])

        lines = []
        for band in bands:
            band.sort(key=lambda t: t[1])          # ordem horizontal real
            base = dict(band[0][2])
            spans = list(base["spans"])
            x1 = base["bbox"][2]
            for _y, _x, l in band[1:]:
                # o espaço entre os fragmentos é geométrico, não textual:
                # reinsere-o para não colar "2.1"+"Words" -> "2.1Words"
                gap = l["bbox"][0] - x1
                if (gap > 0.5 and spans
                        and not spans[-1]["text"].endswith(" ")
                        and not l["spans"][0]["text"].startswith(" ")):
                    sep = dict(spans[-1])
                    sep["text"] = " "
                    spans.append(sep)
                spans.extend(l["spans"])
                x1 = max(x1, l["bbox"][2])
            base["spans"] = spans
            y0 = min(t[2]["bbox"][1] for t in band)
            base["bbox"] = (band[0][1], y0, x1,
                            max(t[2]["bbox"][3] for t in band))
            lines.append((y0, band[0][1], base))

        # --- notas de margem partidas em duas linhas ----------------------
        # "regular" (y=622) e "expressions" (y=628.5) são UM termo, mas há
        # linhas de corpo entre elas na ordem por y, então a junção que roda
        # no fim (blocos margin consecutivos) nunca dispara. Junta-se aqui,
        # por proximidade vertical DENTRO da coluna da margem.
        def _is_margin(x: float, l: dict) -> bool:
            return (not no_margin and x < MARGIN_X_MAX
                    and line_dominant_size(l) <= 8.0)

        midx = [i for i, (y, x, l) in enumerate(lines) if _is_margin(x, l)]
        drop: set[int] = set()
        host: int | None = None
        last_y = 0.0
        for i in midx:
            if host is not None and lines[i][0] - last_y <= MARGIN_LINE_GAP:
                yh, xh, lh = lines[host]
                merged = dict(lh)
                # a quebra entre as duas linhas da margem é geométrica, não
                # textual: sem reinserir o espaço sai "regularexpressions"
                sep = dict(lh["spans"][-1])
                sep["text"] = " "
                merged["spans"] = (list(lh["spans"]) + [sep]
                                   + list(lines[i][2]["spans"]))
                lines[host] = (yh, xh, merged)
                drop.add(i)
                last_y = lines[i][0]                   # encadeia 3+ linhas
            else:
                host, last_y = i, lines[i][0]
        if drop:
            lines = [t for i, t in enumerate(lines) if i not in drop]

        # --- título de capítulo em duas linhas -----------------------------
        # "Sequence Labeling for Parts of" / "Speech and Named Entities" são
        # UM título de 24.8pt quebrado pela medida da página. Como dois
        # blocos, o título não casa com o sumário, o segundo pedaço vira um
        # heading solto e — pior — a busca da epígrafe ancora na primeira
        # linha e trata a segunda como início do grupo recuado. Eram os 6
        # capítulos que apareciam sem epígrafe.
        i = 0
        while i + 1 < len(lines):
            y0, x0, l0 = lines[i]
            y1, x1, l1 = lines[i + 1]
            s0, s1 = line_dominant_size(l0), line_dominant_size(l1)
            if (s0 >= 16.0 and abs(s0 - s1) <= 0.5 and abs(x0 - x1) <= 2.0
                    and 0 < y1 - y0 <= s0 * 1.6):
                merged = dict(l0)
                sep = dict(l0["spans"][-1])
                sep["text"] = " "
                merged["spans"] = list(l0["spans"]) + [sep] + list(l1["spans"])
                merged["bbox"] = (l0["bbox"][0], l0["bbox"][1],
                                  max(l0["bbox"][2], l1["bbox"][2]),
                                  l1["bbox"][3])
                lines[i] = (y0, x0, merged)
                del lines[i + 1]
                continue
            i += 1

        # borda direita da caixa de texto, para reconhecer alinhamento à
        # direita (a atribuição da epígrafe)
        # A borda é a MODA, não o máximo: o texto justificado termina todas as
        # linhas cheias no mesmo x (475.2), mas uma figura ou fórmula que
        # avance para 482.4 levaria o máximo junto e a atribuição (472.4)
        # deixaria de parecer alinhada à direita.
        _edges = Counter(round(l["bbox"][2])
                         for y, x, l in lines if x >= BODY_X_MIN)
        right_edge = float(_edges.most_common(1)[0][0]) if _edges else 0.0

        # Margem esquerda do corpo: a maioria das linhas começa nela; a
        # primeira linha de cada parágrafo entra ~15pt. Era o único sinal de
        # fim de parágrafo que faltava — antes o corte vinha por acidente, da
        # nota de margem que interrompia o fluxo, e por isso uma página sem
        # notas saía como um parágrafo único.
        _lefts = Counter(round(x) for y, x, l in lines if x >= BODY_X_MIN)
        body_left = float(_lefts.most_common(1)[0][0]) if _lefts else BODY_X_MIN

        # RECUO PENDENTE, no pós-livro. No corpo, a primeira linha do parágrafo
        # é a recuada e as seguintes encostam na margem; na bibliografia e no
        # índice remissivo é o contrário — a entrada encosta na margem da sua
        # coluna e as continuações entram ~10pt. Com a regra do corpo, cada
        # linha das colunas 2..n fica "recuada" em relação ao body_left da
        # coluna 1 e vira um parágrafo próprio: era uma entrada por LINHA.
        def para_starts(x: float, l: dict) -> bool:
            if col_origins:
                return x <= col_origins[col_of(x)] + PARA_HANG_TOL
            return x > body_left + PARA_INDENT_MIN

        # --- zona da epígrafe, por antecipação -----------------------------
        # Localiza a atribuição PRIMEIRO; tudo entre o título do capítulo e
        # ela é epígrafe, qualquer que seja o recuo.
        epi_body: set[int] = set()
        epi_attrib = -1
        big_digit = next((i for i, (y, x, l) in enumerate(lines)
                          if line_dominant_size(l) >= CHAPNUM_MIN_SIZE
                          and "".join(s["text"] for s in l["spans"]).strip().isdigit()),
                         None)
        if big_digit is not None:
            title_i = next((i for i in range(big_digit, len(lines))
                            if line_dominant_size(lines[i][2]) >= 16.0
                            and not "".join(s["text"] for s in lines[i][2]["spans"]
                                            ).strip().isdigit()), None)
            if title_i is not None:
                # A atribuição é a ÚLTIMA linha do primeiro grupo recuado após
                # o título — não a primeira que "pareça" atribuição. Em vários
                # capítulos a própria epígrafe é alinhada à direita (cap.9
                # "Larvatus prodeo", cap.13 "Time will explain."), e a regra
                # do primeiro casamento devorava a epígrafe no lugar da
                # atribuição. O grupo precisa COMEÇAR logo após o título: mais
                # adiante na página já é corpo, e um exemplo deslocado ali
                # também é recuado.
                def _ok(i: int) -> bool:
                    # o número de página do rodapé também é "recuado"
                    return HEADER_Y_MAX <= lines[i][0] <= FOOTER_Y_MIN

                def _is_body(i: int) -> bool:
                    """Linha que pertence ao corpo: na margem ou no recuo."""
                    xx = lines[i][1]
                    return (abs(xx - body_left) <= 3.0
                            or abs(xx - (body_left + 15.0)) <= 3.0)

                # A atribuição é a ÚLTIMA linha "de atribuição" na janela
                # curta após o título. Três formas ocorrem no livro:
                #   * recuo profundo — "Pascal", "Jane Austen, Persuasion"
                #   * corpo 9pt e recuada — "Borges (1964)", "David Hume…"
                #   * encostada à direita — "Weizenbaum (1966)"
                # Não dá para parar na retomada do corpo: as epígrafes dos
                # capítulos 1 e 18 são compostas NA margem do corpo, e o
                # limite as descartaria inteiras.
                attrib = -1
                limit = min(title_i + 1 + EPI_WINDOW, len(lines))
                for i in range(title_i + 1, limit):
                    yy, xx, ll = lines[i]
                    if not (HEADER_Y_MAX <= yy <= FOOTER_Y_MIN):
                        continue
                    if is_mono_line(ll):
                        continue
                    deep = xx > body_left + 100.0
                    small = (line_dominant_size(ll) <= 9.2
                             and xx > body_left + 15.0)
                    right = (abs(ll["bbox"][2] - right_edge) <= RIGHT_ALIGN_TOL
                             and xx > body_left + 60.0)
                    if deep or small or right:
                        attrib = i
                if attrib > title_i:
                    epi_attrib = attrib
                    epi_body = {j for j in range(title_i + 1, attrib)
                                if HEADER_Y_MAX <= lines[j][0] <= FOOTER_Y_MIN
                                and not _is_margin(lines[j][1], lines[j][2])}

        foot_y = footnote_y(page, body_left)

        cur: Block | None = None
        chapnum: str | None = None      # numeral grande da abertura
        # Tags aguardando o parágrafo que anotam. No impresso a palavra fica
        # AO LADO de uma linha no meio do parágrafo; emiti-la ali partia o
        # parágrafo em dois ("...processing system" / "that could carry on
        # a limited conversation..."), e com a etiqueta em caixa a costura
        # ficava visível. Agora ela é emitida imediatamente ANTES do
        # parágrafo inteiro, que fica intacto.
        pend_margin: list[str] = []
        numex_x = 0.0                   # coluna do conteúdo do exemplo
        first_para = True               # 1º parágrafo desta página
        math_here: list[Block] = []     # equações desta página, p/ rasterizar

        def frame_of(l: dict):
            """Chave do quadro que contém esta linha, se houver."""
            b = l["bbox"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            for n, r in enumerate(frames):
                if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                    return f"{pno}:{n}"
            return None

        def flush():
            nonlocal cur
            for t in pend_margin:
                blocks.append(Block(kind="margin", text=t, page=pno))
            pend_margin.clear()
            if cur and cur.text.strip():
                # unlig ANTES de dehyphenate: "classi- ﬁcation" traz a ligadura
                # U+FB01, que não casa com [a-zà-ÿ], e o hífen sobreviveria.
                t = unlig(cur.text)
                # em código — e no diálogo de uma epígrafe — o hífen e a quebra
                # de linha são significativos
                verbatim = ((cur.kind in ("code", "example", "math")
                             or (cur.kind == "numex"
                                 and not cur.meta.get("prosa")))
                            or (cur.kind == "epigraph" and cur.meta.get("mono")))
                if not verbatim:
                    t = dehyphenate(re.sub(r"[ \t]+", " ", t))
                    t = re.sub(r"\s+", " ", t)
                cur.text = t.strip()
                # citação quebrada em duas linhas chega como duas entradas da
                # mesma chave ("Weizenbaum," / "1966)"): recompõe
                cs = cur.meta.get("cites")
                if cs:
                    j: list[tuple[str, str]] = []
                    for k, v in cs:
                        if j and j[-1][0] == k:
                            j[-1] = (k, f"{j[-1][1]} {v}")
                        else:
                            j.append((k, v))
                    cur.meta["cites"] = [list(p) for p in j]
                elif "cites" in cur.meta:
                    del cur.meta["cites"]
                blocks.append(cur)
            cur = None

        for li, (y, x, l) in enumerate(lines):
            txt = line_text_styled(l)
            raw = "".join(decode_span(s) for s in l["spans"]).strip()
            size = line_dominant_size(l)

            # descarta cabeçalho/rodapé corrente e números de página soltos
            if y < HEADER_Y_MAX or y > FOOTER_Y_MIN:
                continue

            # Texto DENTRO de uma figura já está na imagem rasterizada. As
            # tabelas deste livro são figuras: sem esta supressão, cada linha
            # da tabela voltava como parágrafo solto ("Shakespeare 31
            # thousand 884 thousand"), duplicando o conteúdo e injetando
            # colunas embaralhadas no meio da prosa.
            # Exige contenção TOTAL, e numa versão encolhida do retângulo:
            # figure_regions aglomera traços com folga de 18pt e ainda dá
            # respiro de 4pt, então o "centro dentro" engolia a legenda logo
            # abaixo e linhas de prosa ao lado — 241 legendas perdidas.
            # Contenção por ÁREA, não total: a última faixa de uma tabela
            # ultrapassa o retângulo em um ou dois pontos (o descendente da
            # letra), e a regra estrita a deixava vazar para a prosa — foi
            # o caso do "\B non-word boundary" da fig. 2.12. Exigir 80% da
            # linha dentro cobre isso sem engolir a legenda vizinha.
            lb = l["bbox"]
            area = max((lb[2] - lb[0]) * (lb[3] - lb[1]), 0.01)
            if not re.match(r"^(Figure|Table)\s+\d", raw):
                dentro = 0.0
                for r in fig_rects:
                    w = min(lb[2], r.x1) - max(lb[0], r.x0)
                    h = min(lb[3], r.y1) - max(lb[1], r.y0)
                    if w > 0 and h > 0:
                        dentro = max(dentro, w * h)
                if dentro / area >= 0.8:
                    continue
            if raw.isdigit():
                # ...exceto o numeral de abertura, que é dígito e é conteúdo.
                if size >= CHAPNUM_MIN_SIZE:
                    flush()
                    chapnum = raw
                continue

            # rótulo "CHAPTER" da abertura: o EPUB reconstrói esse rótulo a
            # partir do numeral, então o texto solto aqui só viraria um
            # parágrafo órfão antes do título.
            if chapnum is None and CHAP_LABEL_RE.match(raw) and size < 16.0:
                flush()
                continue

            # --- nota de rodapé ------------------------------------------
            if foot_y is not None and y > foot_y:
                m_fn = FOOTNOTE_NUM.match(raw)
                primeiro = l["spans"][0]["size"] if l["spans"] else 10.0
                if m_fn and primeiro < 7.5:
                    # marcador em corpo 6 abre uma nota nova
                    flush()
                    cur = Block(kind="footnote", page=pno,
                                text=txt[m_fn.end():].strip(),
                                meta={"num": m_fn.group(1)})
                elif cur and cur.kind == "footnote":
                    cur.text += " " + txt
                else:
                    flush()
                    cur = Block(kind="footnote", text=txt, page=pno)
                continue

            # nota de margem (termo-chave destacado à esquerda)
            if not no_margin and x < MARGIN_X_MAX and size <= 8.0:
                pend_margin.append(unlig(raw))
                continue

            # --- epígrafe de abertura ------------------------------------
            # Zona entre o título do capítulo e o primeiro parágrafo: bloco
            # recuado, fechado por uma linha alinhada à direita (a
            # atribuição). Sem tratar isso, a atribuição era absorvida pelo
            # parágrafo seguinte e o capítulo abria com
            # "Weizenbaum (1966) The dialogue above is from ELIZA...".
            if li == epi_attrib:
                flush()
                cs = line_cite_spans(l, cites)
                blocks.append(Block(
                    kind="epigraph_attrib", text=dehyphenate(unlig(txt)),
                    page=pno, meta={"cites": cs} if cs else {}))
                continue
            if li in epi_body:
                if cur and cur.kind == "epigraph":
                    cur.text += ("\n" if is_mono_line(l) else " ") + txt
                else:
                    flush()
                    cur = Block(kind="epigraph", text=txt, page=pno,
                                meta={"mono": is_mono_line(l)})
                continue

            # títulos: tamanho maior que o corpo. O nível vem da numeração
            # ("2.1 Words" -> 2, "2.6.4 Disjunction..." -> 3), não do tamanho,
            # porque o LaTeX usa o mesmo corpo para seção e subseção.
            m = SEC_NUM_RE.match(raw)
            is_big = size >= 16.0
            is_sec = 11.5 <= size < 16.0 and base_font(l["spans"][0]["font"]) in BOLD_FONTS
            if is_big or is_sec:
                flush()
                # 1ª escolha: o nível gravado pelo LaTeX no sumário do PDF.
                # O sumário guarda "Words", não "2.1 Words", daí a normalização.
                tl = toc_level.get(norm_title(raw))
                if tl is not None:
                    lvl = min(max(tl, 1), 4)      # 1=parte 2=capítulo 3=seção 4=subseção
                elif m:
                    lvl = min(m.group(1).count(".") + 2, 4)
                else:
                    lvl = 1 if is_big else 3
                meta = {"num": m.group(1) if m else None,
                        "from_toc": tl is not None}
                if chapnum is not None:
                    # o numeral grande pertence a ESTE título: é a abertura
                    meta["chapnum"] = chapnum
                    chapnum = None
                    pass
                blocks.append(Block(kind=f"heading{lvl}", text=unlig(raw),
                                    page=pno, level=lvl, meta=meta))
                continue

            # exemplo numerado: "(2.3) 姚 明 进入 总 决赛" + glosa embaixo
            nm = NUMEX_RE.match(raw)
            if nm and x <= body_left + PARA_INDENT_MIN:
                flush()
                # o conteúdo começa no 1º fragmento à direita do rótulo; as
                # linhas seguintes que se alinham a ele são a glosa
                numex_x = next((sp["bbox"][0] for sp in l["spans"]
                                if sp["bbox"][0] > x + 12
                                and sp["text"].strip()), x + 30)
                cur = Block(kind="numex", page=pno,
                            text=txt[nm.end():].strip(),
                            meta={"num": nm.group(1)})
                continue
            if cur and cur.kind == "numex":
                if x >= numex_x - 2:
                    if l["bbox"][2] >= right_edge - 30:
                        cur.meta["prosa"] = True
                    cur.text += "\n" + txt      # glosa interlinear
                    continue
                flush()

            # legenda de figura/tabela (agora com o texto junto, pós-merge)
            if size <= 9.2 and re.match(r"^(Figure|Table)\s+\d", raw):
                flush()
                # a legenda continua nas linhas seguintes, que não são
                # parágrafo novo: fica aberta em `cur` em vez de fechada aqui
                cur = Block(kind="caption", text=dehyphenate(unlig(txt)),
                            page=pno, meta={"y": round(y, 1)})
                continue
            if (cur and cur.kind == "caption"
                    and x <= body_left + PARA_INDENT_MIN and size <= 9.2):
                cur.text += " " + txt
                continue
            if cur and cur.kind == "caption":
                # voltou ao corpo de 10pt: a legenda acabou. Sem este corte
                # ela seguia engolindo o parágrafo seguinte inteiro —
                # "Eq. 6.34 e Eq. 6.33 thus require five intermediate
                # derivatives" saía dentro de uma legenda.
                flush()

            # monoespaçada: código de verdade vs. exemplo linguístico.
            # Ambos ficam em inglês, mas renderizam diferente no EPUB.
            if is_mono_line(l):
                kind = "code" if CODEY_RE.search(raw) else "example"
                # Dentro de um quadro a listagem é uma só: uma linha sem
                # sinais de código (`... '''`) não vira "exemplo
                # linguístico" no meio de um trace de Python — partia a
                # caixa em duas, com um painel bege dentro da moldura.
                fr = frame_of(l)
                if (fr and cur and cur.kind in ("code", "example")
                        and (cur.meta or {}).get("quadro") == fr):
                    kind = cur.kind
                if cur and cur.kind == kind:
                    cur.text += "\n" + raw
                else:
                    flush()
                    fr = frame_of(l)
                    cur = Block(kind=kind, text=raw, page=pno,
                                translate=False,
                                meta={"quadro": fr} if fr else {})
                continue

            # fórmula deslocada
            centered = x > body_left + 40.0
            eqm = EQNUM_RE.search(raw)
            numbered = (eqm is not None and centered
                        and abs(l["bbox"][2] - right_edge) <= RIGHT_ALIGN_TOL)

            # Equação aberta é "pegajosa": uma vez dentro de uma fórmula
            # deslocada, qualquer linha centrada e vertical­mente colada
            # continua a MESMA equação, mesmo que sua proporção de glifos
            # matemáticos caia abaixo do limiar. Sem isso, a linha do meio de
            # uma chave saía como parágrafo e partia a equação em três.
            # O corpo do texto começa na margem, nunca centrado, então não
            # há risco de engolir prosa.
            if (cur and cur.kind == "math" and centered and not numbered
                    and l["bbox"][1] - cur.meta["bbox"][3] < 8.0):
                cur.text += "\n" + raw
                ob, bb = cur.meta["bbox"], l["bbox"]
                cur.meta["bbox"] = [min(ob[0], bb[0]), ob[1],
                                    max(ob[2], bb[2]), max(ob[3], bb[3])]
                if len(raw.strip()) > 2:
                    tb = cur.meta.get("bbox_txt") or list(bb)
                    cur.meta["bbox_txt"] = [min(tb[0], bb[0]), min(tb[1], bb[1]),
                                            max(tb[2], bb[2]), max(tb[3], bb[3])]
                continue

            if numbered or line_math_ratio(l) > 0.5 or (
                    centered and line_math_ratio(l) > 0.30):
                # (sem flush aqui: ele zeraria `cur` antes do teste de fusão
                #  logo abaixo, e cada linha da chave viraria uma equação)
                txt_eq = raw[:eqm.start()].strip() if numbered else raw
                if txt_eq:      # "(4.1)" sozinho não é equação, é sobra
                    bb = l["bbox"]
                    solo = len(raw.strip()) <= 2      # só a chave
                    if (cur and cur.kind == "math"
                            and bb[1] - cur.meta["bbox"][3] < 8.0):
                        # linha seguinte da MESMA equação (chave, matriz):
                        # separá-las produzia "D[i−1, j]+del-cost(...)" solto
                        cur.text += "\n" + txt_eq
                        ob = cur.meta["bbox"]
                        cur.meta["bbox"] = [min(ob[0], bb[0]), ob[1],
                                            max(ob[2], bb[2]),
                                            max(ob[3], bb[3])]
                        if not solo:
                            tb = cur.meta.get("bbox_txt") or list(bb)
                            cur.meta["bbox_txt"] = [min(tb[0], bb[0]),
                                                    min(tb[1], bb[1]),
                                                    max(tb[2], bb[2]),
                                                    max(tb[3], bb[3])]
                        if numbered:
                            cur.meta["num"] = eqm.group(1)
                    else:
                        flush()
                        mm = {"bbox": [bb[0], bb[1], bb[2], bb[3]]}
                        if not solo:
                            mm["bbox_txt"] = [bb[0], bb[1], bb[2], bb[3]]
                        if numbered:
                            mm["num"] = eqm.group(1)
                        fr = frame_of(l)
                        if fr:
                            mm["quadro"] = fr
                        cur = Block(kind="math", text=txt_eq, page=pno,
                                    translate=False, meta=mm)
                        math_here.append(cur)
                continue

            # parágrafo: nova entrada se recuado (indentação de 1ª linha) ou,
            # no pós-livro, se encostar na margem da coluna (recuo pendente)
            if para_starts(x, l):
                flush()
            if cur and cur.kind == "para":
                cur.text += " " + txt
                cur.meta.setdefault("cites", []).extend(
                    line_cite_spans(l, cites))
            else:
                flush()
                m2 = {"cites": line_cite_spans(l, cites)}
                fr = frame_of(l)
                if fr:
                    m2["quadro"] = fr
                # Sem recuo de primeira linha e primeiro parágrafo da página:
                # é a CONTINUAÇÃO do parágrafo que ficou aberto na página
                # anterior. Sem religar, todo parágrafo que cruza a virada
                # sai partido em dois no EPUB.
                if first_para and not para_starts(x, l):
                    m2["cont"] = True
                first_para = False
                cur = Block(kind="para", text=txt, page=pno, meta=m2)

        flush()

        # --- equação deslocada vira imagem ---------------------------------
        # Só as linhas que COMEÇAM na margem do corpo servem de teto: são
        # prosa, nunca parte da equação. As linhas internas da fórmula ficam
        # recuadas, e a caixa de glifo das chaves ⎧⎨⎩ é mais alta que o
        # desenho — medir por ela deixava o recorte descer sobre o parágrafo.
        line_tops = sorted(t[0] for t in lines
                           if abs(t[1] - body_left) <= 3.0)
        # Reconstruir a estrutura (fração, chave, matriz, somatório) a partir
        # da tipografia daria uma aproximação; a imagem dá o original. E não
        # custa nada em tradução: equação não tem prosa.
        for mb in math_here:
            if not mb.text.strip():
                continue
            bx = mb.meta.get("bbox")
            if not bx:
                continue
            tb = mb.meta.get("bbox_txt") or bx
            # largura da união (para pegar a chave), altura do conteúdo (para
            # não invadir o parágrafo seguinte)
            y1 = max(tb[3], bx[1] + 6)
            # e um teto rígido: a próxima linha de texto da página. As chaves
            # ⎧⎨⎩ têm caixa de glifo mais alta que o desenho, e sem este
            # limite o recorte descia uma linha e duplicava a primeira linha
            # do parágrafo seguinte dentro da imagem.
            nxt = [t for t in line_tops if t > bx[1] + 4.0]
            if nxt:
                y1 = min(y1, min(nxt) - 2.0)
            bx = [bx[0], min(bx[1], tb[1]), bx[2], y1]
            r = fitz.Rect(bx) + (-3, -2, 3, 2)
            r &= page.rect
            if r.width < 6 or r.height < 5:
                continue
            img_seq += 1
            name = f"eq{img_seq:04d}.png"
            try:
                pix = page.get_pixmap(clip=r, dpi=FIG_DPI)
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(img_dir / name)
                mb.image = name
            except Exception:
                pass
        math_here.clear()

        # marca onde começam capítulos/seções segundo o sumário do PDF
        if pno in toc_by_page:
            for lvl, title in toc_by_page[pno]:
                blocks.append(Block(kind="tocmark", text=title, page=pno,
                                    level=lvl, translate=False))

    doc.close()

    # --- parágrafos partidos pela virada de página -------------------------
    out: list[Block] = []
    for b in blocks:
        if b.kind == "para" and (b.meta or {}).get("cont"):
            # As figuras são emitidas no topo de cada página, antes do
            # texto, e as tags da página nova também precedem o parágrafo:
            # nenhuma delas é barreira real entre as duas metades.
            k = len(out) - 1
            tags: list[Block] = []
            while k >= 0 and out[k].kind in ("margin", "figure", "tocmark"):
                tags.append(out[k])
                k -= 1
            if (k >= 0 and out[k].kind == "para"
                    and out[k].page == b.page - 1):
                # A palavra pode estar partida bem na virada — "proba-" no
                # fim de uma página e "bility" no começo da outra. Cada
                # metade passou pelo flush sem ter com o que casar, então a
                # junta precisa ser desifenizada aqui.
                out[k].text = dehyphenate(
                    out[k].text.rstrip() + " " + b.text.lstrip())
                cs = (b.meta or {}).get("cites")
                if cs:
                    out[k].meta.setdefault("cites", []).extend(cs)
                # as tags da página nova passam a preceder o parágrafo já
                # unificado, que é onde a marcação de índice pertence
                del out[k + 1:]
                out[k:k] = list(reversed(tags))
                continue
            b.meta.pop("cont", None)
        out.append(b)
    blocks = out

    # A junção de termos partidos em duas linhas ("regular" / "expressions")
    # é feita no nível da LINHA, por proximidade vertical na coluna da margem.
    # Fundir blocos margin consecutivos aqui juntaria também termos distintos
    # de uma mesma página — "ELIZA tokenization BPE regular expressions" numa
    # etiqueta só.
    return blocks


# Caracteres que só aparecem quando a decodificação falhou: área de uso
# privado (as chaves ⎧⎨⎩ do CMEX, por exemplo), controles e o U+FFFD.
BROKEN_CH = re.compile(r"[\ue000-\uf8ff\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")

# Blocos cujo texto vai para o leitor (e para o tradutor)
LEGIVEL = {"para", "heading1", "heading2", "heading3", "heading4",
           "caption", "margin", "numex", "epigraph", "epigraph_attrib",
           "example", "code"}


def validar(blocks: list[Block]) -> None:
    """Barra o texto que chegou ilegível ao bloco final.

    Existe porque o exemplo (2.9) passou meses saindo como
    "t-@-nk’e-mejN-@-jetem@-nni-k": a fonte fonética desenha o AFI em slots
    ASCII e ninguém percebeu. Falha silenciosa de decodificação não pode
    depender de alguém reparar na leitura.
    """
    print("\n--- validação de caracteres ---")
    # Fonética PRECISA estar mapeada: seu texto vai inteiro para o leitor.
    # Matemática pode ficar: aquele texto acaba dentro da imagem da equação.
    fon = Counter({k: v for k, v in UNMAPPED.items()
                   if k[0].startswith("TeX-xipa")})
    mat = Counter({k: v for k, v in UNMAPPED.items()
                   if not k[0].startswith("TeX-xipa")})
    if fon:
        print(f"  FALHA: {sum(fon.values())} glifos fonéticos sem mapa "
              f"— acrescente-os a XIPA")
        for (f, ch), n in fon.most_common(12):
            print(f"     {f:16} {ch!r:8} ×{n}")
    else:
        print("  fonética: todos os glifos mapeados")
    if mat:
        print(f"  matemática: {sum(mat.values())} glifos ASCII de fonte de "
              f"símbolo (vão para a imagem da equação)")
        for (f, ch), n in mat.most_common(4):
            print(f"     {f:16} {ch!r:8} ×{n}")

    ruins = Counter()
    exemplos: dict[str, str] = {}
    for b in blocks:
        if b.kind not in LEGIVEL:
            continue
        for m in BROKEN_CH.finditer(b.text):
            ch = m.group(0)
            ruins[ch] += 1
            exemplos.setdefault(ch, b.text[max(0, m.start() - 28):m.start() + 28])
    if ruins:
        print(f"  caracteres ilegíveis em texto legível: {sum(ruins.values())} "
              f"em {len(ruins)} formas")
        for ch, n in ruins.most_common(8):
            print(f"     U+{ord(ch):04X} ×{n:<5} …{exemplos[ch]!r}")
    else:
        print("  nenhum caractere ilegível no texto legível")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    blocks = extract(PDF, OUT)
    (OUT / "blocks.json").write_text(
        json.dumps([asdict(b) for b in blocks], ensure_ascii=False, indent=1),
        encoding="utf-8")

    validar(blocks)

    from collections import Counter
    c = Counter(b.kind for b in blocks)
    chars = sum(len(b.text) for b in blocks if b.translate)
    print(f"blocos: {len(blocks)}")
    for k, v in c.most_common():
        print(f"  {k:10s} {v}")
    print(f"caracteres a traduzir: {chars:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
