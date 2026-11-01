#!/usr/bin/env python3
"""
Fase 3 - Montagem do EPUB a partir de blocks.json + translated.jsonl.

Preserva a hierarquia semântica (títulos, tags de índice, código, legendas,
figuras, epígrafes, citações), não os pontos tipográficos do PDF: o Kindle
reflui o texto, então fixar fontes do original seria trabalhar contra o
dispositivo.

A marcação emitida é a mesma para todas as variantes de estilo; quem escolhe a
aparência é a classe no <body> (template.ESTILO). Ver o cabeçalho de
template.py para o que é comutável só por CSS e o que exige remontagem.

Sem dependências externas — escreve o container OCF/EPUB3 na mão.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
import zipfile
from pathlib import Path

from extract import chapter_pages
from template import CSS, NOTA_TRADUTOR, ESTILO

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"

MARK = re.compile(r"«(/?)(i|b|code|sup|sub)»")

NAMES = {"i": "em", "b": "strong", "code": "code",
         "sup": "sup", "sub": "sub"}

BIB_FILE = "bibliografia.xhtml"

# Tipos MIME que o Kindle e os leitores EPUB3 aceitam para fonte embutida
FONT_MIME = {".ttf": "application/vnd.ms-opentype",
             ".otf": "application/vnd.ms-opentype"}


def checar_cobertura(chapters, fdir: Path, fontes: list[dict]) -> None:
    """Nenhum caractere do texto pode ficar sem fonte que o desenhe.

    O Latin-1 qualquer serifada tem; acima disso, ou está numa das fontes
    embutidas ou vira quadradinho no aparelho — e ninguém percebe até abrir
    o livro. Aqui a falha aparece na montagem.
    """
    cobre: set[int] = set()
    for f in fontes:
        cobre |= set(f.get("cobre") or [])
    if not cobre:
        print("  (manifesto sem code points: cobertura não verificada)")
        return
    texto = "".join(b for _, b in chapters)
    texto = re.sub(r"<[^>]+>", "", texto)
    faltam = {ch for ch in texto
              if ord(ch) > 0xFF and ord(ch) not in cobre
              and not (0xE000 <= ord(ch) <= 0xF8FF)}
    if faltam:
        print(f"  ATENÇÃO: {len(faltam)} caracteres sem fonte — "
              f"{''.join(sorted(faltam))[:60]}")
    else:
        print("  cobertura de fonte: todos os caracteres têm glifo")


def montar_css(fontes: list[dict]) -> str:
    """Injeta as @font-face e a pilha de fontes no CSS do template."""
    faces = []
    for f in fontes:
        faces.append(
            f'@font-face {{ font-family: "{f["familia"]}"; '
            f'src: url("fonts/{f["arquivo"]}"); '
            f'font-weight: normal; font-style: normal; }}')
    # Georgia primeiro: as reservas entram por queda glifo a glifo, e nunca
    # assumem o corpo do texto — não têm latim básico para isso.
    stack = ", ".join(["Georgia"]
                      + [f'"{f["familia"]}"' for f in fontes]
                      + ["serif"])
    css = CSS.replace("@STACK@", stack)
    return css.replace("/* @FONTES@", "\n".join(faces) + "\n/* @FONTES@")


def to_html(t: str) -> str:
    """Converte «i»/«b»/«code» em HTML, tolerando marcação desbalanceada.

    A marcação nem sempre chega bem-formada: um span estilizado pode cruzar
    a fronteira de um bloco na extração, e o modelo às vezes omite um
    fechamento. Emitir o </em> órfão correspondente produz XHTML inválido e
    quebra o EPUB inteiro. Aqui: fechamento sem abertura é descartado, e o
    que ficar aberto no fim é fechado na ordem correta.
    """
    parts = MARK.split(t)
    out: list[str] = [html.escape(parts[0])]
    stack: list[str] = []
    for i in range(1, len(parts), 3):
        closing, tag, tail = parts[i], parts[i + 1], parts[i + 2]
        name = NAMES[tag]
        if closing:
            if name in stack:                 # fecha até o par correspondente
                while stack:
                    top = stack.pop()
                    out.append(f"</{top}>")
                    if top == name:
                        break
            # fechamento órfão: descartado silenciosamente
        else:
            stack.append(name)
            out.append(f"<{name}>")
        out.append(html.escape(tail))
    while stack:                              # fecha o que sobrou aberto
        out.append(f"</{stack.pop()}>")
    return clean("".join(out))


# XML 1.0 proíbe a maioria dos caracteres de controle — e o PDF traz alguns
# (ex.: \x1a) vindos da codificação das fontes matemáticas. Escapar não
# resolve: eles são inválidos no documento, ponto. Precisam sair.
BAD_XML = re.compile(
    "[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD"
    "\U00010000-\U0010FFFF]")


def clean(t: str) -> str:
    return BAD_XML.sub("", t)


def plain(t: str) -> str:
    """Texto sem marcadores, para <title> — que não aceita marcação."""
    return clean(MARK.sub("", t))


# --------------------------------------------------------------- citações ---
YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})[a-z]?\b")


def cite_pattern(surface: str) -> re.Pattern | None:
    """Regex tolerante para reencontrar a citação dentro do texto traduzido.

    O texto de superfície vem dos spans azuis do PDF e chega sem a pontuação
    que os separa na página: "Weizenbaum 1966" para "(Weizenbaum, 1966)".
    Casar literalmente falharia em quase tudo, então os tokens são religados
    por um separador curto de não-palavra.
    """
    toks = [re.escape(t) for t in surface.split() if t]
    if not toks:
        return None
    return re.compile(r"[^\w<>]{0,4}".join(toks))


def link_cites(body: str, cites, used: set[str]) -> tuple[str, int, int]:
    """Envolve cada citação num <a> para a sua entrada na bibliografia.

    Opera sobre o HTML já montado, e não sobre o texto cru, porque é aí que a
    tradução final está. Autor e ano saem em <span> separados: é o que
    permite trocar D1 por D2 (autor em versalete) mexendo só no CSS.
    """
    hit = miss = 0
    for entry in cites or []:
        key, surface = entry[0], entry[1]
        pat = cite_pattern(surface)
        if pat is None:
            continue
        # não recasa dentro de um <a> já inserido nesta passagem
        m = None
        for cand in pat.finditer(body):
            before = body.rfind("<a ", 0, cand.start())
            if before == -1 or body.find("</a>", before) < cand.start():
                m = cand
                break
        if m is None:
            miss += 1
            continue
        txt = m.group(0)
        ym = YEAR.search(txt)
        if ym:
            au, an, tail = txt[:ym.start()], txt[ym.start():ym.end()], txt[ym.end():]
            # a pontuação entre autor e ano fica FORA dos dois spans: em D2 o
            # versalete pegaria também o "(" de "Weizenbaum (1966)"
            sep = ""
            pm = re.search(r"[\W_]+$", au)
            if pm:
                au, sep = au[:pm.start()], au[pm.start():]
            inner = (f'<span class="au">{au}</span>{sep}'
                     f'<span class="an">{an}</span>{tail}')
        else:
            inner = f'<span class="au">{txt}</span>'
        link = (f'<a class="cite" href="{BIB_FILE}#c-{html.escape(key)}">'
                f'{inner}</a>')
        body = body[:m.start()] + link + body[m.end():]
        used.add(key)
        hit += 1
    return body, hit, miss


# --------------------------------------------------------------- epígrafe ---
SPEAKER = re.compile(r"^\s*([A-Za-zÀ-ÿ][\w .'-]{0,14}):\s(.*)$")


def render_epigraph(txt: str, mono: bool) -> str:
    """Epígrafe: diálogo vira tabela interlocutor/fala; prosa vira parágrafo.

    O diálogo do ELIZA em <pre> quebrava a coluna em 6": cada fala mede mais
    que a medida da tela. Em duas células, a fala longa quebra embaixo de si
    mesma e a coluna do interlocutor fica intacta.
    """
    if mono:
        out = []
        for raw in txt.split("\n"):
            line = MARK.sub("", raw).rstrip()
            if not line.strip():
                continue
            m = SPEAKER.match(line)
            if m:
                out.append(f'<div class="fala">'
                           f'<span class="quem">{html.escape(clean(m.group(1)))}:</span>'
                           f'<span class="diz">{html.escape(clean(m.group(2)))}</span>'
                           f'</div>')
            else:
                out.append(f'<div class="fala"><span class="diz">'
                           f'{html.escape(clean(line))}</span></div>')
        return "\n".join(out)
    return f'<p class="texto verso">{to_html(txt)}</p>'


def pair_figures(blocks: list[dict]) -> dict[int, dict]:
    """Casa cada figura com sua legenda (mesma página, legenda logo abaixo).

    Solta, a legenda vira um parágrafo órfão do tipo "Figure 2.2 A linha azul
    grossa mostra…" sem imagem alguma ao lado.
    """
    pairs: dict[int, dict] = {}
    taken: set[int] = set()          # índices de figura já casados
    figs = [b for b in blocks if b["kind"] == "figure"]
    for cap in [b for b in blocks if b["kind"] == "caption"]:
        cands = [f for f in figs
                 if f["page"] == cap["page"] and f["_i"] not in taken]
        if not cands:
            # a figura ocupa o pé de uma página e a legenda vira para a
            # seguinte: sem esta segunda tentativa, as duas ficam órfãs
            cands = [f for f in figs
                     if f["page"] == cap["page"] - 1 and f["_i"] not in taken]
        if not cands:
            continue
        # As figuras são emitidas no TOPO da página, todas antes do texto,
        # então proximidade de índice não diz nada: a legenda da fig. 2.17
        # casava com o desenho da 2.18. O que vale é a geometria — a figura
        # é a que está imediatamente ACIMA da legenda na página.
        cy = (cap.get("meta") or {}).get("y")
        acima = [f for f in cands
                 if cy is not None and (f.get("meta") or {}).get("y") is not None
                 and f["meta"]["y"] < cy]
        if acima:
            best = max(acima, key=lambda f: f["meta"]["y"])
        else:
            best = min(cands, key=lambda f: abs(f["_i"] - cap["_i"]))
        pairs[cap["_i"]] = best
        taken.add(best["_i"])
    return pairs


SUP = re.compile(r"<sup>(\d{1,2})</sup>")


def ligar_notas(out: list[str], notas: list[dict], ncap: int) -> None:
    """Liga a chamada à nota — só onde a nota existe.

    Nem todo sobrescrito é chamada: expoentes usam o mesmo <sup>. Por isso a
    ligação é um pós-passo, feito quando já se sabe quais números de nota o
    capítulo tem, e cada número é ligado uma única vez (a primeira
    ocorrência, que é a chamada).
    """
    faltam = {n["num"] for n in notas}
    if not faltam:
        return
    for i, frag in enumerate(out):
        if not faltam:
            break

        def sub(m):
            n = m.group(1)
            if n not in faltam:
                return m.group(0)
            faltam.discard(n)
            return (f'<a class="notaref" epub:type="noteref" '
                    f'id="ref-{ncap}-{n}" href="#nota-{ncap}-{n}">'
                    f'<sup>{n}</sup></a>')
        out[i] = SUP.sub(sub, frag)


def emitir_notas(out: list[str], notas: list[dict], ncap: int) -> None:
    """Notas ao fim do capítulo, com volta para o ponto de chamada."""
    if not notas:
        return
    ligar_notas(out, notas, ncap)
    out.append('<div class="notas">')
    for n in notas:
        out.append(
            f'<aside class="nota" epub:type="footnote" '
            f'id="nota-{ncap}-{n["num"]}">'
            f'<p><a class="nota-volta" href="#ref-{ncap}-{n["num"]}">'
            f'{html.escape(n["num"])}</a> {n["html"]}</p></aside>')
    out.append('</div>')


def render(blocks: list[dict], pt: dict[int, str],
           used_cites: set[str]) -> tuple[list[tuple[str, str]], int, int]:
    """UM arquivo por capítulo; seções viram âncoras internas."""
    cap_by_cap = pair_figures(blocks)
    used_figs = {f["_i"] for f in cap_by_cap.values()}

    chapters: list[tuple[str, list[str]]] = []
    cur_title, cur = None, []
    pend_tags: list[str] = []            # tags de índice aguardando parágrafo
    hits = misses = 0
    open_q: str | None = None            # quadro (caixa de algoritmo) aberto
    cur_page = -1                        # página do título que abriu o arquivo
    cur_chapnum: str | None = None       # numeral do capítulo em curso
    no_indice = False                    # dentro do índice remissivo
    notas: list[dict] = []               # notas de rodapé do capítulo em curso
    ncap = 0                             # índice do capítulo, para os id

    def close_q(out: list[str]):
        nonlocal open_q
        if open_q is not None:
            out.append("</div>")
            open_q = None

    def flush_tags(out: list[str]):
        if pend_tags:
            chips = "".join(f'<span class="tagchip">{to_html(t)}</span>'
                            for t in pend_tags)
            out.append(f'<p class="tag">{chips}</p>')
            pend_tags.clear()

    for b in blocks:
        k = b["kind"]
        txt = pt.get(b["_i"], b["text"])
        meta = b.get("meta") or {}
        if k == "tocmark":
            continue

        # Caixa de algoritmo: o original a delimita com uma moldura. Aqui ela
        # é reconstruída em CSS, e não rasterizada, para o pseudocódigo
        # continuar sendo texto — e continuar traduzível.
        q = meta.get("quadro")
        if q != open_q:
            close_q(cur)
            if q:
                cur.append('<div class="quadro">')
                open_q = q

        if k in ("heading1", "heading2"):          # início de capítulo
            num = meta.get("chapnum")
            # A folha de rosto e o divisor de volume compõem CADA LINHA como
            # título próprio ("Speech and Language Processing", "Third Edition
            # draft", "Daniel Jurafsky", "Volume I", "LARGE LANGUAGE
            # MODELS"). Tratada cada uma como início de capítulo, a página
            # virava cinco arquivos de uma linha — e o filtro do fim do render
            # descartava os curtos, levando junto a folha de rosto inteira.
            # Títulos sem numeral na MESMA página do capítulo em curso seguem
            # dentro dele: uma página impressa, um arquivo.
            if (not num and not cur_chapnum and cur_title is not None
                    and cur_page == b["page"]):
                close_q(cur)
                flush_tags(cur)
                cur.append(f'<h2 class="rosto">{to_html(txt)}</h2>')
                continue
            close_q(cur)
            flush_tags(cur)
            if cur_title is not None and cur:
                emitir_notas(cur, notas, ncap)
                chapters.append((cur_title, cur))
                ncap += 1
            notas = []
            cur_page, cur_chapnum = b["page"], num
            no_indice = txt.strip().lower() == "subject index"
            if num:
                # Abertura fiel: rótulo, numeral, filete e título como
                # elementos irmãos — o CSS decide se ficam lado a lado (A1)
                # ou empilhados (A2).
                head = (f'<div class="abertura">'
                        f'<div class="lado">'
                        f'<p class="rotulo">Capítulo</p>'
                        f'<p class="numeral">{html.escape(num)}</p>'
                        f'</div>'
                        f'<div class="filete"></div>'
                        f'<h1 class="titulo">{to_html(txt)}</h1>'
                        f'</div>')
            else:
                head = f"<h1>{to_html(txt)}</h1>"
            cur_title, cur = txt, [head]
            continue
        if cur_title is None:                      # material antes do 1º cap.
            cur_title, cur = txt or "Início", []

        if k == "footnote":
            # A nota não entra no fluxo: no impresso ela vive no pé da
            # página, e um EPUB não tem página. Fica guardada e sai no fim
            # do capítulo, ligada à chamada nos dois sentidos.
            notas.append({"num": meta.get("num") or str(len(notas) + 1),
                          "html": to_html(txt)})
            continue
        if k == "numex":
            flush_tags(cur)
            # Exemplo numerado: rótulo pendurado à esquerda, conteúdo à
            # direita. A glosa interlinear do original alinha coluna a
            # coluna com a linha acima; numa tela que reflui isso não se
            # sustenta, então as linhas ficam empilhadas — a correspondência
            # palavra a palavra se perde, a leitura não.
            linhas = [ln for ln in txt.split("\n") if ln.strip()]
            corpo = "<br/>".join(to_html(ln) for ln in linhas)
            num = (meta.get("num") or "").strip()
            cur.append(f'<div class="numex">'
                       f'<span class="nx-num">({html.escape(num)})</span>'
                       f'<span class="nx-corpo">{corpo}</span></div>')
            continue
        if k == "epigraph":
            flush_tags(cur)
            # Já sai FECHADA. Antes ficava aberta à espera da atribuição, e
            # os dois capítulos cuja epígrafe não tem atribuição (8 e 13; são
            # 23 epígrafes para 21 atribuições) saíam com uma <div> pendurada
            # — XHTML mal formado, que um leitor estrito recusa abrir.
            cur.append('<div class="epigrafe">'
                       + render_epigraph(txt, bool(meta.get("mono")))
                       + '</div>')
            continue
        if k == "epigraph_attrib":
            body = to_html(txt)
            body, h, m = link_cites(body, meta.get("cites"), used_cites)
            hits += h
            misses += m
            # entra DENTRO da epígrafe anterior; sem corpo (capítulo com
            # atribuição solta), vira uma epígrafe só de atribuição
            atrib = f'<p class="atrib">{body}</p>'
            if (cur and cur[-1].startswith('<div class="epigrafe">')
                    and cur[-1].endswith('</div>')):
                cur[-1] = cur[-1][:-len('</div>')] + atrib + '</div>'
            else:
                cur.append(f'<div class="epigrafe">{atrib}</div>')
            continue

        if k == "heading3":
            flush_tags(cur); cur.append(f"<h2>{to_html(txt)}</h2>")
        elif k == "heading4":
            flush_tags(cur); cur.append(f"<h3>{to_html(txt)}</h3>")
        elif k == "margin":
            pend_tags.append(txt)                  # segura até o parágrafo
        elif k == "para":
            flush_tags(cur)
            body = to_html(txt)
            body, h, m = link_cites(body, meta.get("cites"), used_cites)
            hits += h
            misses += m
            # No índice remissivo cada parágrafo é uma ENTRADA, com recuo
            # pendente. Como <p> comum, a regra do parágrafo corrido recuava
            # a partir da segunda — o inverso do que o original faz.
            cur.append(f'<p class="entrada">{body}</p>' if no_indice
                       else f"<p>{body}</p>")
        elif k == "caption":
            flush_tags(cur)
            fig = cap_by_cap.get(b["_i"])
            cap_html = to_html(txt)
            if fig:
                cur.append(f'<figure><img src="images/{fig["image"]}" alt=""/>'
                           f'<figcaption>{cap_html}</figcaption></figure>')
            else:
                # Nem toda "Figure N" é desenho: várias são listagens de
                # pseudocódigo ou traces de Python, que chegam como <pre>
                # logo acima. A legenda descreve esse bloco, então recebe o
                # mesmo tratamento tipográfico de uma legenda de figura.
                cur.append(f'<p class="legenda">{cap_html}</p>')
        elif k == "figure" and b["_i"] not in used_figs:
            flush_tags(cur)
            cur.append(f'<figure><img src="images/{b["image"]}" alt=""/></figure>')
        elif k == "code":
            flush_tags(cur)
            cur.append(f"<pre>{html.escape(clean(b['text']))}</pre>")
        elif k == "example":
            flush_tags(cur)
            # Sem rótulo por bloco. Ele existia para distinguir o exemplo
            # preservado do traduzido, e fazia sentido enquanto traduzir era
            # uma das vias. Agora o exemplo está SEMPRE no original — o
            # rótulo saía em 24 dos 24 exemplos do cap. 2, e o que não
            # informa, atrapalha. A regra é dita uma vez na nota do tradutor;
            # os glosados se anunciam sozinhos, pelo "[em português: ...]".
            cur.append(f'<div class="exemplo">'
                       f'{html.escape(clean(txt))}</div>')
        elif k == "math":
            flush_tags(cur)
            num = meta.get("num")
            eq = html.escape(clean(b["text"]))
            if b.get("image"):
                # A equação vai como imagem: fração, chave, matriz e
                # somatório não sobrevivem à camada de texto do PDF, e
                # equação não tem prosa para traduzir.
                alt = html.escape(plain(b["text"])[:120])
                img = (f'<img class="eqimg" src="images/{b["image"]}" '
                       f'alt="{alt}"/>')
                # o número já está dentro do recorte, à direita da equação:
                # emiti-lo de novo em CSS o duplicava na página
                cur.append(f'<p class="formula">{img}</p>')
                continue
            if num:
                # número à direita, como no impresso — o texto remete a ele
                # ("Eq. 2.5"), então perdê-lo quebra a referência
                cur.append(f'<div class="formula num">'
                           f'<span class="eq">{eq}</span>'
                           f'<span class="eq-num">({html.escape(num)})</span>'
                           f'</div>')
            else:
                cur.append(f'<p class="formula">{eq}</p>')

    close_q(cur)
    flush_tags(cur)
    if cur_title is not None and cur:
        emitir_notas(cur, notas, ncap)
        chapters.append((cur_title, cur))
    # Sai tudo que tem conteúdo. O corte anterior (`len(c) > 2`) existia para
    # não gerar arquivo degenerado, mas descartava em silêncio: a folha de
    # rosto, a abertura do Volume I e o capítulo 1 — que neste rascunho é só
    # título e epígrafe, dois fragmentos — sumiam do EPUB sem aviso.
    return ([(t, "\n".join(c)) for t, c in chapters if c], hits, misses)


def xhtml(title: str, body: str) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'xml:lang="pt-BR" lang="pt-BR">\n'
            f'<head><meta charset="utf-8"/><title>{html.escape(plain(title))}</title>'
            f'<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            f'<body class="{ESTILO}">\n{body}\n</body></html>').encode("utf-8")


SEM_TEXTO = ("heading1", "heading2", "figure", "tocmark")


def colher_bibliografia(blocks: list[dict]) -> list[dict]:
    """As entradas da bibliografia impressa, na ordem em que ela as traz.

    As páginas dela chegam ao montador como parágrafos comuns e saíam como um
    capítulo "Bibliography" — 185 KB repetindo o arquivo com âncoras. Aqui são
    colhidas para virar o próprio bibliografia.xhtml e retiradas do fluxo dos
    capítulos.
    """
    lo = hi = None
    for b in blocks:
        if b["kind"] != "heading2":
            continue
        t = b["text"].strip().lower()
        if t == "bibliography":
            lo = b["page"]
        elif t == "subject index" and lo is not None and hi is None:
            hi = b["page"] - 1
    if lo is None:
        return []
    if hi is None:
        hi = max(b["page"] for b in blocks)

    # `para` abre entrada; o resto é cauda dela. A URL de uma referência sai em
    # fonte monoespaçada e é classificada como `example` — filtrar só `para`
    # descartava as 30 que existem, e com elas o endereço de cada obra na web.
    out: list[dict] = []
    for b in blocks:
        if not (lo <= b["page"] <= hi) or not b["text"].strip():
            continue
        if b["kind"] in SEM_TEXTO:
            continue
        if b["kind"] == "para" or not out:
            out.append(dict(b))
        else:
            out[-1]["text"] += " " + b["text"]
    return out


CHAVE_PREFIXO = 40


def _chave_norm(t: str) -> str:
    t = MARK.sub("", t)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def render_bib_extraido(entradas: list[dict], bib: dict,
                        só_citadas: set[str] | None = None) -> str:
    """A bibliografia como ela está no PDF, com as âncoras do bib.json.

    Duas fontes, cada uma boa numa coisa. O TEXTO vem da extração, que desde
    a leitura por coluna sai completo; o bib.json trunca as entradas que
    atravessam a virada de página, e montar por ele custava 0,12 ponto de
    cobertura. As CHAVES vêm do bib.json, que as tem do destino nomeado
    `cite.<chave>` gravado pelo próprio LaTeX — a extração não tem como
    sabê-las. O casamento é pelo início da entrada, que os dois lados
    escrevem igual: casa 1.256 das 1.263.
    """
    por_prefixo: dict[str, list[str]] = {}
    for k, v in bib.items():
        por_prefixo.setdefault(_chave_norm(v["text"])[:CHAVE_PREFIXO],
                               []).append(k)

    norm = [_chave_norm(b["text"]) for b in entradas]
    chaves: list[list[str]] = [[] for _ in entradas]
    ligadas: set[str] = set()
    for i, n in enumerate(norm):
        for k in por_prefixo.get(n[:CHAVE_PREFIXO], []):
            chaves[i].append(k)
            ligadas.add(k)

    # Sobra quem não abre a entrada: a obra que a virada de página fez a
    # anterior engolir, e aquela cujo começo a extração grafa diferente
    # ("MÉTÉO:" em versalete). Procurada por dentro do texto, com prefixo
    # cada vez mais curto. Sem isto o link da citação cai no vazio.
    for k in bib:
        if k in ligadas:
            continue
        p = _chave_norm(bib[k]["text"])
        for corte in (CHAVE_PREFIXO, 24, 16):
            alvo = p[:corte]
            if len(alvo) < corte:
                continue
            i = next((j for j, n in enumerate(norm) if alvo in n), None)
            if i is not None:
                chaves[i].append(k)
                ligadas.add(k)
                break

    linhas, mostradas = [], 0
    for b, ks in zip(entradas, chaves):
        # Numa prévia de capítulo a bibliografia inteira seria ruído; ficam as
        # obras que o recorte cita. O TEXTO continua sendo o extraído — é o que
        # garante que a prévia mostre a referência do original, e não a versão
        # truncada que o bib.json guarda das entradas que viram a página.
        if só_citadas is not None and not (set(ks) & só_citadas):
            continue
        mostradas += 1
        ident = f' id="c-{html.escape(ks[0])}"' if ks else ""
        âncoras = "".join(f'<span id="c-{html.escape(k)}"></span>'
                          for k in ks[1:])
        linhas.append(f'<p class="entrada"{ident}>{âncoras}'
                      f'{to_html(b["text"])}</p>')
    print(f"bibliografia: {mostradas} entradas de {len(entradas)} extraídas, "
          f"{len(ligadas)} de {len(bib)} chaves de citação ancoradas")
    return ('<h1>Bibliografia</h1>\n<div class="bibliografia">\n'
            + "\n".join(linhas) + "\n</div>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="translated.jsonl")
    ap.add_argument("--out", default="ed3book-ptBR.epub")
    ap.add_argument("--oebps", default="OEBPS",
                    help="pasta para preservar o conteúdo editável do EPUB")
    ap.add_argument("--titulo", default="Processamento de Fala e Linguagem")
    ap.add_argument("--cap", type=int,
                    help="monta só um capítulo (prévia de estrutura; sem "
                         "--jsonl sai no original, para conferir a marcação "
                         "sem esperar a tradução)")
    args = ap.parse_args()

    blocks = json.loads((BUILD / "blocks.json").read_text(encoding="utf-8"))
    bibp = BUILD / "bib.json"
    bib = json.loads(bibp.read_text(encoding="utf-8")) if bibp.exists() else {}

    pt: dict[int, str] = {}
    p = BUILD / args.jsonl
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                pt[d["i"]] = d["pt"]
            except Exception:
                pass
    print(f"blocos traduzidos disponíveis: {len(pt):,}")

    # Índice ESTÁVEL, atribuído antes de qualquer filtro; o casamento é por ele.
    # A versão anterior remapeava chaves por deslocamento, o que só funciona se
    # produtor e consumidor filtrarem igual — e não filtravam.
    for i, b in enumerate(blocks):
        b["_i"] = i
    # A bibliografia é colhida do livro INTEIRO, antes de qualquer recorte.
    # Colhida depois, uma prévia de capítulo não a enxergava (as páginas dela
    # ficam fora do recorte) e caía numa segunda rota, montada do bib.json —
    # que trunca a entrada atravessando a virada de página. A prévia saía com
    # "EMNLP. and 2017b. Adversarial multi-criteria" no lugar da referência.
    # Uma fonte só, o texto extraído, para os dois modos.
    entradas_bib = colher_bibliografia(blocks) if bib else []
    if entradas_bib:
        # Pelo INTERVALO, não pelo conjunto de páginas que têm entrada: uma
        # página da bibliografia sem nenhum parágrafo escaparia para o fluxo e
        # viraria capítulo solto.
        blo = min(b["page"] for b in entradas_bib)
        bhi = max(b["page"] for b in entradas_bib)
        blocks = [b for b in blocks if not (blo <= b["page"] <= bhi)]
        print(f"bibliografia: {len(entradas_bib)} entradas extraídas "
              f"(págs {blo}-{bhi}), retiradas do fluxo dos capítulos")

    if args.cap:
        # MESMO recorte que o translate.py usa — ver extract.chapter_pages
        faixa = chapter_pages(blocks, args.cap)
        if faixa is None:
            print(f"capítulo {args.cap} não encontrado")
            return 1
        lo, hi = faixa
        blocks = [b for b in blocks if lo <= b["page"] <= hi]
        print(f"prévia: capítulo {args.cap}, páginas {lo}-{hi}")
    elif pt:
        lo, hi = min(pt), max(pt)
        blocks = [b for b in blocks if lo <= b["_i"] <= hi]

    used_cites: set[str] = set()
    chapters, hits, misses = render(blocks, pt, used_cites)
    print(f"capítulos: {len(chapters)}")
    tot = hits + misses
    if tot:
        print(f"citações ligadas: {hits}/{tot} "
              f"({hits/tot*100:.0f}%) — obras na bibliografia: {len(used_cites)}")

    imgs = sorted({b["image"] for b in blocks
                   if b["kind"] in ("figure", "math") and b.get("image")})
    img_dir = BUILD / "images"

    out = BUILD / args.out
    with zipfile.ZipFile(out, "w") as z:
        # mimetype precisa ser o 1º item e sem compressão (spec OCF)
        z.writestr("mimetype", "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?>\n<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        fdir = BUILD / "fonts"
        fman = fdir / "manifesto.json"
        fontes = (json.loads(fman.read_text(encoding="utf-8"))
                  if fman.exists() else [])
        fontes = [f for f in fontes if (fdir / f["arquivo"]).exists()]
        z.writestr("OEBPS/style.css", montar_css(fontes))
        z.writestr("OEBPS/nota.xhtml", xhtml("Nota do tradutor", NOTA_TRADUTOR))

        items, spine, nav = [], [], []
        items.append('<item id="css" href="style.css" media-type="text/css"/>')
        for n, f in enumerate(fontes):
            src = fdir / f["arquivo"]
            z.writestr(f"OEBPS/fonts/{f['arquivo']}", src.read_bytes())
            mime = FONT_MIME.get(src.suffix, "application/vnd.ms-opentype")
            items.append(f'<item id="f{n}" href="fonts/{f["arquivo"]}" '
                         f'media-type="{mime}"/>')
        if fontes:
            kb = sum(f["bytes"] for f in fontes) / 1024
            print(f"fontes embutidas: {len(fontes)} "
                  f"({kb:.0f} KB, "
                  f"{sum(f['glifos'] for f in fontes)} glifos)")
            checar_cobertura(chapters, fdir, fontes)
        items.append('<item id="nota" href="nota.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="nota"/>')
        nav.append('<li><a href="nota.xhtml">Nota do tradutor</a></li>')

        # POSIÇÃO DA BIBLIOGRAFIA. No original ela vem depois do último
        # capítulo e ANTES do índice remissivo. Escrita no fim da montagem,
        # caía depois do índice — última do livro, que não é onde o leitor a
        # procura nem onde o original a põe.
        onde_bib = next((n for n, (t, _) in enumerate(chapters)
                         if plain(t).strip().lower() == "subject index"),
                        len(chapters))
        for n, (title, body) in enumerate(chapters):
            fn = f"cap{n:03d}.xhtml"
            z.writestr(f"OEBPS/{fn}", xhtml(title, body))
            items.append(f'<item id="c{n}" href="{fn}" media-type="application/xhtml+xml"/>')
            if n == onde_bib:
                spine.append('<itemref idref="bib"/>')
                nav.append(f'<li><a href="{BIB_FILE}">Bibliografia</a></li>')
            spine.append(f'<itemref idref="c{n}"/>')
            nav.append(f'<li><a href="{fn}">{html.escape(plain(title))}</a></li>')

        if entradas_bib and bib:
            # Numa prévia só as obras citadas; no livro, todas.
            só = used_cites if (args.cap or len(chapters) < 5) else None
            corpo_bib = render_bib_extraido(entradas_bib, bib, só)
            z.writestr(f"OEBPS/{BIB_FILE}", xhtml("Bibliografia", corpo_bib))
            items.append(f'<item id="bib" href="{BIB_FILE}" '
                         f'media-type="application/xhtml+xml"/>')
            if onde_bib >= len(chapters):      # sem índice remissivo: vai ao fim
                spine.append('<itemref idref="bib"/>')
                nav.append(f'<li><a href="{BIB_FILE}">Bibliografia</a></li>')

        for n, im in enumerate(imgs):
            f = img_dir / im
            if f.exists():
                z.writestr(f"OEBPS/images/{im}", f.read_bytes())
                items.append(f'<item id="i{n}" href="images/{im}" media-type="image/png"/>')

        z.writestr("OEBPS/nav.xhtml", xhtml("Sumário",
                   '<nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops">'
                   f'<h1>Sumário</h1><ol>{"".join(nav)}</ol></nav>'))
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')

        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                   'unique-identifier="bid"><metadata '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:identifier id="bid">ed3book-ptBR</dc:identifier>'
                   f'<dc:title>{html.escape(plain(args.titulo))}</dc:title>'
                   '<dc:language>pt-BR</dc:language>'
                   '<dc:creator>Daniel Jurafsky; James H. Martin</dc:creator>'
                   '<meta property="dcterms:modified">2026-07-27T00:00:00Z</meta>'
                   f'</metadata><manifest>{"".join(items)}</manifest>'
                   f'<spine>{"".join(spine)}</spine></package>')

    # Mantém uma cópia editável da árvore interna para correções manuais.
    # Não removemos arquivos existentes: uma nova montagem pode ser feita em
    # outro diretório se houver alterações manuais a preservar.
    oebps = Path(args.oebps)
    if not oebps.is_absolute():
        oebps = BUILD / oebps
    with zipfile.ZipFile(out) as z:
        for name in z.namelist():
            if not name.startswith("OEBPS/") or name.endswith("/"):
                continue
            target = oebps / name.removeprefix("OEBPS/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))

    print(f"gerado: {out}  ({out.stat().st_size/1048576:.1f} MB, {len(imgs)} imagens)")
    print(f"OEBPS preservado em: {oebps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
