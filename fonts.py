#!/usr/bin/env python3
"""
Fase 2b - Fontes de recurso, reduzidas ao que o livro realmente usa.

O corpo do texto continua na fonte do leitor: estas entram só como reserva,
para os caracteres que Georgia (ou o que o Kindle estiver usando) não tem.
Por isso o subconjunto NÃO inclui o latim básico — se incluísse, um leitor
sem Georgia poderia adotar a fonte de reserva para o livro inteiro.

O livro pede 281 caracteres fora do Latin-1: AFI, grego, operadores
matemáticos, setas, e trechos em tâmil, árabe, chinês e japonês. Nenhuma
fonte livre cobre tudo; três cobrem, e cada caractere vai para a primeira
que o tiver.

Roda no Python do SISTEMA (o fontTools está lá, não no venv):
    python3 fonts.py
"""
from __future__ import annotations

import json
from pathlib import Path

from fontTools.ttLib import TTFont, TTCollection
from fontTools.subset import Subsetter, Options

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
OUT = BUILD / "fonts"

# Ordem de prioridade. A FreeSerif vem primeiro por ser um clone de Times:
# um ə dela cai bem ao lado da serifada do corpo. A Noto entra pelo CJK e
# pelas escritas índicas, a DejaVu fecha o resto.
CANDIDATOS = [
    ("Ed3Serif", "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
     "FreeSerif (GPL com exceção de fonte)"),
    ("Ed3CJK", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
     "Noto Serif CJK (OFL 1.1)"),
    ("Ed3Sym", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
     "DejaVu Serif (licença Bitstream Vera)"),
]


def carrega(path: str) -> TTFont:
    if path.endswith(".ttc"):
        return TTCollection(path).fonts[0]
    return TTFont(path, fontNumber=0)


def cobertura(f: TTFont) -> set[int]:
    cps: set[int] = set()
    for t in f["cmap"].tables:
        cps |= set(t.cmap)
    return cps


def main() -> int:
    blocks = json.loads((BUILD / "blocks.json").read_text(encoding="utf-8"))
    legivel = {"para", "heading1", "heading2", "heading3", "heading4",
               "caption", "margin", "numex", "epigraph", "epigraph_attrib",
               "example", "code"}
    need = set()
    for b in blocks:
        if b["kind"] in legivel:
            need |= {ch for ch in b["text"] if ord(ch) > 0xFF}
    legiveis = len(need - set("«»"))

    # Margem de segurança: inclui também o que está hoje DENTRO de figura ou
    # equação. Os símbolos do AFI, por exemplo, vivem quase todos nas cartas
    # de vogais do capítulo de fonética, que são imagens — mas basta uma
    # dessas figuras deixar de ser rasterizada para o texto voltar ao corpo
    # do livro, e aí a fonte precisa já cobri-lo. São poucas dezenas de
    # glifos; o barato é levá-los desde já.
    for b in blocks:
        need |= {ch for ch in b["text"] if ord(ch) > 0xFF}
    need -= set("«»")                       # marcadores internos
    # área de uso privado e controles não são texto: são restos de fonte
    # matemática que só existem dentro da imagem da equação
    need = {c for c in need
            if not (0xE000 <= ord(c) <= 0xF8FF) and ord(c) >= 0x20}
    print(f"caracteres fora do Latin-1: {len(need)} "
          f"({legiveis} no texto legível, o resto é margem)")

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()

    restante = set(need)
    manifesto = []
    for nome, path, lic in CANDIDATOS:
        if not restante or not Path(path).exists():
            continue
        fonte = carrega(path)
        cps = cobertura(fonte)
        meus = {c for c in restante if ord(c) in cps}
        if not meus:
            continue
        restante -= meus

        opt = Options()
        opt.layout_features = ["*"]
        opt.notdef_outline = True
        opt.recalc_bounds = True
        opt.drop_tables += ["DSIG"]
        sub = Subsetter(options=opt)
        sub.populate(unicodes=[ord(c) for c in meus])
        sub.subset(fonte)
        # o nome da família precisa ser único: é por ele que o CSS chama
        for rec in fonte["name"].names:
            if rec.nameID in (1, 4, 6):
                fonte["name"].setName(nome, rec.nameID, rec.platformID,
                                      rec.platEncID, rec.langID)
        ext = "otf" if fonte.sfntVersion == "OTTO" else "ttf"
        alvo = OUT / f"{nome}.{ext}"
        fonte.save(alvo)
        kb = alvo.stat().st_size / 1024
        print(f"  {nome:9} {len(meus):>4} glifos  {kb:7.1f} KB  {lic}")
        manifesto.append({"familia": nome, "arquivo": alvo.name,
                          "glifos": len(meus), "licenca": lic,
                          "bytes": alvo.stat().st_size,
                          # os code points vão no manifesto para a montagem
                          # poder conferir a cobertura sem depender do
                          # fontTools, que não está no venv
                          "cobre": sorted(ord(c) for c in meus)})

    if restante:
        print(f"  SEM COBERTURA: {len(restante)} — "
              f"{''.join(sorted(restante))[:80]}")
    (OUT / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(m["bytes"] for m in manifesto) / 1024
    print(f"total embutido: {total:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
