# spl-translate

[Português](README.md) · **English**

A collaborative Brazilian Portuguese translation of *Speech and Language
Processing* (3rd edition, draft of August 19, 2026) by Daniel Jurafsky and
James H. Martin, as an EPUB for Kindle.

The first version is **machine-made**: the text is extracted from the PDF,
translated by a local language model (Gemma 4 E4B) and assembled into an EPUB.
It has not been reviewed by a human. The goal is for readers and reviewers to
improve it — see [CONTRIBUTING.md](CONTRIBUTING.md) (Portuguese).

## Copyright

The book is © 2026 Jurafsky & Martin, "all rights reserved" (page 1 of the
PDF). The authors distribute the original PDF for reading, and **this
repository does not include it**: download it yourself and point the scripts
at it.

- **Code and documentation** in this repository: MIT license
  ([LICENSE](LICENSE)).
- **Translation** (`traducao/`) and the **EPUB** attached to releases: derivative
  work of the book, which remains under the authors' rights. The MIT license
  does **not** cover them. Status of the authors' permission to redistribute:
  **pending**.

## Where the EPUB is

The EPUB is **not stored in the repository**. GitHub Actions
(`.github/workflows/release.yml`) builds it automatically when a *release* is
published and attaches it to that release, with the version in the file name:
`spl-ptBR-<tag>.epub` (for example `spl-ptBR-ed3-2026.08-r1.epub`). The
translated text lives in `traducao/livro.jsonl` (one block per line: `i` is the
block index, `pt` is the translation). Assembly does not call any LLM.

The workflow downloads the source PDF from the `PDF_URL` repository variable and
checks its SHA-256: block indices only match the PDF of August 19, 2026.

## Requirements

- Python 3.10+ and `llama.cpp` (`llama-server`) for the local backend.
- The book PDF (`ed3book_aug26.pdf` or another, via `ED3BOOK_PDF`).
- `fontTools` on the SYSTEM Python (used only by `fonts.py`).

```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Building the EPUB

```
./venv/bin/python extract.py        # PDF -> build/blocks.json + build/images/
./venv/bin/python bib.py            # citation keys -> build/bib.json
python3 fonts.py                    # fallback fonts -> build/fonts/ (SYSTEM Python)
./venv/bin/python capa.py           # cover -> build/capa.png

./venv/bin/python translate.py --out book.jsonl --porta 8099 --workers 2 --sem-thinking
./venv/bin/python build_epub.py --jsonl book.jsonl --sem-links --out book.epub
```

To build from the versioned translation, with no LLM:
`build_epub.py --jsonl "$PWD/traducao/livro.jsonl" --sem-links`.

- `translate.py` is **resumable**: it appends to a JSONL file, so after a crash
  you just run it again. `--cap N` translates chapter N only.
- `--sem-thinking` turns the model's reasoning off. With it on, the model spends
  the token limit thinking and returns an empty answer.
- `--sem-links` removes the links from citations to the bibliography (on Kindle
  an accidental tap jumps to the end of the book with no way back).
- The translator's note is `nota-tradutor.html`; edit it and rebuild.
- Remote backends (`--backend deepseek|openrouter`) read `DEEPSEEK_API_KEY` or
  `OPENROUTER_API_KEY` from the environment.

### Local server — warning

**Always** start `llama-server` with `--n-cpu-moe`. On a machine whose iGPU also
draws the screen, running the whole model on the GPU freezes the desktop.
Example (Gemma 4 26B-A4B):

```
llama-server -m MODEL.gguf --port 8099 -ngl 99 --n-cpu-moe 8 \
  --ctx-size 16384 --parallel 4 --threads 8 --flash-attn on \
  --cache-type-k q8_0 --cache-type-v q8_0 --jinja --reasoning-budget 0
```

Do not keep two models loaded at once: memory cannot hold them.

## Layout

| File | Role |
|---|---|
| `extract.py` | PDF → blocks (`build/blocks.json`) and images |
| `bib.py` | citation keys → `build/bib.json` |
| `fonts.py` | fallback fonts for glyphs Kindle lacks |
| `translate.py` | translates the blocks with the prompt and glossary |
| `build_epub.py` | builds the EPUB (and the `OEBPS` tree) |
| `template.py` | CSS and book style |
| `capa.py` | generates the cover |
| `traducao/livro.jsonl` | the versioned translation (EPUB input) |
| `.github/workflows/release.yml` | builds the EPUB when a release is published |
| `nota-tradutor.html` | text of the translator's note |

## Translation decisions

- Linguistic examples are **never** translated: they stay in English, sometimes
  with a Portuguese gloss in brackets.
- Code and formulas stay as in the original.
- Terminology follows the glossary in `translate.py`; common technical terms
  (*token*, *embedding*, *prompt*…) stay in English.
- The EPUB style changes through CSS only (`ESTILO` in `template.py`).

More details and pitfalls already paid for are in [AGENTS.md](AGENTS.md)
(Portuguese).
