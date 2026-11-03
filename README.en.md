# spl-translate

[Português](README.md) · **English**

*Speech and Language Processing* in Brazilian Portuguese, for your Kindle.

A free, collaborative translation of the 3rd edition (draft of August 19, 2026)
of the book by Daniel Jurafsky and James H. Martin, a worldwide reference for
learning natural language processing and language models.

## Why it exists

Technical material of this quality barely exists in Portuguese. The language
barrier keeps Brazilian students and professionals away from one of the
fastest-growing fields, especially those who cannot afford an English-language
course. This project aims to open that knowledge up, for free.

## Get the book

Download the e-book from the [latest release](https://github.com/jonasrodrigues93/spl-translate/releases/latest).
It is an EPUB ready for Kindle and most e-readers, and the version number is
part of the file name.

## How it works

1. The original book is read page by page: text, headings, figures, tables,
   citations and bibliography.
2. An artificial-intelligence model, running on a local computer, translates the
   text piece by piece. A fixed glossary makes sure the same technical term is
   always translated the same way.
3. What should not be translated is preserved: language examples stay in English
   (sometimes with the Portuguese equivalent next to them), and code and
   formulas remain as in the original.
4. Everything is assembled into an e-book with a cover, table of contents,
   figures and a translator's note, designed for the Kindle screen.
5. Each time a new version is published, the e-book is rebuilt and made
   available automatically.

## Current status

The first version is a machine translation with **no human review**: it may
contain translation errors, technical terms left in English by mistake, and
formatting glitches. It improves with the help of its readers.

## Help improve it

Found a mistake? Open an *issue* with the passage of text and what it should say
instead. Step by step in [CONTRIBUTING](CONTRIBUTING.md) (Portuguese).

## Copyright

This is an **unofficial**, **non-profit** project: whoever makes this
translation seeks no income from it.

The book is by Daniel Jurafsky and James H. Martin, and its official page, with
the English original free to read, is
**[web.stanford.edu/~jurafsky/slp3](https://web.stanford.edu/~jurafsky/slp3/)**.
When in doubt, the original is always the reference.

*Speech and Language Processing* © 2026 Daniel Jurafsky and James H. Martin.
All rights reserved (page 1 of the PDF). The original PDF is not included in
this repository.

- **Code and documentation** in this repository: MIT license
  ([LICENSE](LICENSE)).
- **Translated text** and the **e-book** of each version: derivative work of the
  book. The rights remain with the authors, and the MIT license does **not**
  cover them.

## For developers

How the pipeline is built and run: [DESENVOLVIMENTO](DESENVOLVIMENTO.md)
(Portuguese).
