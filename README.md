# spl-translate

**Português** · [English](README.en.md)

Tradução colaborativa para o português do Brasil de *Speech and Language
Processing* (3ª edição, rascunho de 19 de agosto de 2026), de Daniel Jurafsky e
James H. Martin, em EPUB para Kindle.

A primeira versão é **automática**: o texto é extraído do PDF, traduzido por um
modelo de linguagem local (Gemma 4 E4B) e montado em EPUB. Não passou por
revisão humana. A ideia é que leitores e revisores a melhorem — veja o
[CONTRIBUTING.md](CONTRIBUTING.md).

## Direitos autorais

O livro é © 2026 Jurafsky & Martin, "all rights reserved" (página 1 do PDF). O
PDF original é distribuído pelos autores para leitura, e **este repositório não
o inclui**: baixe-o você mesmo e aponte para ele.

- **Código e documentação** deste repositório: licença MIT ([LICENSE](LICENSE)).
- **Tradução** (`OEBPS/`, `traducao/`) e **EPUB** das releases: obra derivada
  do livro, que continua sob os direitos dos autores. A licença MIT **não** os
  cobre.

## Onde está o EPUB

O EPUB **não fica no repositório**. O conteúdo do livro está em `OEBPS/` (XHTML,
CSS, imagens, fontes), na raiz, e pode ser corrigido à mão. Quando uma *release*
é publicada, o GitHub Actions (`.github/workflows/release.yml`) empacota
`OEBPS/` em um EPUB e o anexa à release, com a versão no nome:
`spl-ptBR-<tag>.epub` (por exemplo, `spl-ptBR-ed3-2026.08-r1.epub`). O workflow
não traduz nada.

`traducao/livro.jsonl` guarda a saída da tradução automática (um bloco por
linha: `i` é o índice do bloco, `pt` é a tradução).

## Requisitos

- Python 3.10+ e `llama.cpp` (`llama-server`) para o backend local.
- O PDF do livro (`ed3book_aug26.pdf` ou outro, via `ED3BOOK_PDF`).
- `fontTools` no Python do sistema (usado só pelo `fonts.py`).

```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Gerar o EPUB

```
./venv/bin/python extract.py        # PDF -> build/blocks.json + build/images/
./venv/bin/python bib.py            # chaves de citação -> build/bib.json
python3 fonts.py                    # fontes de reserva -> build/fonts/ (Python do SISTEMA)
./venv/bin/python capa.py           # capa -> build/capa.png

./venv/bin/python translate.py --out livro.jsonl --porta 8099 --workers 2 --sem-thinking
./venv/bin/python build_epub.py --jsonl livro.jsonl --sem-links --out livro.epub
```

- `translate.py` é **retomável**: grava JSONL de acréscimo e, depois de uma
  queda, reexecutar continua de onde parou. `--cap N` traduz só o capítulo N.
- `--sem-thinking` desliga o raciocínio do modelo. Com ele ligado, o modelo gasta
  o limite de tokens pensando e devolve resposta vazia.
- `--sem-links` tira o link das citações para a bibliografia (no Kindle o toque
  acidental leva ao fim do livro e não há como voltar).
- A nota do tradutor está em `nota-tradutor.html`; edite e remonte.
- Backends remotos (`--backend deepseek|openrouter`) leem `DEEPSEEK_API_KEY` ou
  `OPENROUTER_API_KEY` do ambiente.

### Servidor local — atenção

Suba o `llama-server` **sempre com `--n-cpu-moe`**. Em máquina com iGPU que
também desenha a tela, rodar o modelo inteiro na GPU congela o desktop.
Exemplo (Gemma 4 26B-A4B):

```
llama-server -m MODELO.gguf --port 8099 -ngl 99 --n-cpu-moe 8 \
  --ctx-size 16384 --parallel 4 --threads 8 --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 --jinja --reasoning-budget 0
```

Não deixe dois modelos no ar ao mesmo tempo: a memória não comporta.

## Estrutura

| Arquivo | Papel |
|---|---|
| `extract.py` | PDF → blocos (`build/blocks.json`) e imagens |
| `bib.py` | chaves de citação → `build/bib.json` |
| `fonts.py` | fontes de reserva para glifos que o Kindle não tem |
| `translate.py` | traduz os blocos com o prompt e o glossário |
| `build_epub.py` | monta o EPUB (e a árvore `OEBPS`) |
| `template.py` | CSS e estilo do livro |
| `capa.py` | gera a capa |
| `OEBPS/` | conteúdo do EPUB, corrigível à mão |
| `traducao/livro.jsonl` | saída da tradução automática |
| `.github/workflows/release.yml` | empacota `OEBPS/` em EPUB ao publicar uma release |
| `nota-tradutor.html` | texto da nota do tradutor |

## Decisões de tradução

- Exemplos linguísticos **nunca** são traduzidos: ficam em inglês, às vezes
  com a glosa em português entre colchetes.
- Código e fórmulas ficam no original.
- Terminologia segue o glossário em `translate.py`; termos de uso corrente
  (*token*, *embedding*, *prompt*…) ficam em inglês.
- O estilo do EPUB muda só no CSS (`ESTILO` em `template.py`).

Mais detalhes e armadilhas já encontradas estão no [AGENTS.md](AGENTS.md).
