# spl-translate

Tradução para pt-BR de *Speech and Language Processing* (Jurafsky & Martin,
3ª ed., rascunho de 6/1/2026) em EPUB para Kindle, para leitura pessoal.

Fonte: `./ed3book_jan26.pdf` — 626 páginas, pdfTeX. Para usar outra cópia,
defina `ED3BOOK_PDF`.

## Commits

Use **Conventional Commits**, em português.

```
tipo(escopo): descrição
```

- **Tipos:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`,
  `chore`, `revert`. Mudança de aparência do EPUB (CSS) é `feat` ou `fix` com
  escopo `estilo`.
- **Escopo** (opcional): `capNN` para correção de tradução, ou `extract`,
  `translate`, `build`, `template`, `capa`, `ci`, `docs`.
- **Descrição:** no imperativo, em minúscula, sem ponto final, até 72
  caracteres.
- **Corpo** (opcional): explica o porquê, não o quê.
- **Mudança incompatível:** `!` depois do tipo/escopo e rodapé `BREAKING CHANGE:`.
  Qualquer mudança no `extract.py` que invalide as traduções já feitas é
  incompatível.
- Um assunto por commit. Nunca inclua chaves de API, caminhos da sua máquina,
  o PDF ou arquivos de `build/`.

Exemplos: `fix(cap3): corrige tradução de "perplexity"`,
`feat(build): adiciona flag --sem-links`, `ci: anexa o EPUB à release`,
`feat(extract)!: muda a ordem de leitura das colunas`.

## Preparar o ambiente

Este checkout não inclui o ambiente virtual. Prepare-o uma vez, sem usar o
Python do sistema para as fases que importam `fitz`:

```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

`fonts.py` continua sendo executado com `python3` do sistema, porque o
`fontTools` é uma dependência do sistema neste ambiente.

## Rodar

Não há script único: rode o pipeline abaixo, passo a passo. O servidor local
sobe com o comando do `DESENVOLVIMENTO.md` — **sempre com `--n-cpu-moe`**.

**É retomável.** O `translate.py` grava JSONL append-only e relê o que já
traduziu; depois de uma queda, reexecutar continua de onde parou. Antes de
subir um servidor, confira que não há outro `llama-server` no ar — 23 GB não
comportam dois modelos destes.

## Pipeline, passo a passo

```
./venv/bin/python extract.py      # PDF -> build/blocks.json + build/images/
./venv/bin/python bib.py          # chaves de citação -> build/bib.json
python3 fonts.py                  # fontes de reserva -> build/fonts/
./venv/bin/python translate.py --cap N --out N.jsonl [--porta 8099]
./venv/bin/python build_epub.py --jsonl N.jsonl --out livro.epub
```

**`fonts.py` roda no Python do SISTEMA**, não no venv: o `fontTools` está lá.

Prévia sem tradução: `./venv/bin/python build_epub.py --cap N --jsonl NADA.jsonl`.

## Rede de segurança

**`extract.py` → `validar()`** — acusa glifo de fonte não decodificada e
caractere ilegível chegando ao texto do leitor. Nasceu do exemplo (2.9), que
saía `t-@-nk'e-mejN-@-...` porque a fonte fonética WSUIPA desenha AFI em slots
ASCII. Não a remova sem substituí-la. Ao mexer na montagem, confira também o XML
do EPUB com `xml.dom.minidom`.

**Extrator e consumidores têm de ler igual.** `column_origins`, `col_index`,
`backmatter_start`, `toc_pages`, `build_vocab` e `chapter_pages` vivem no
`extract.py` e são importados por `bib.py`, `translate.py` e `build_epub.py`,
em vez de reescritos em cada um.

`chapter_pages` é o recorte de um capítulo, e vale para o tradutor e o montador: recorte
diferente entre tradutor e montador desalinha índice de bloco com tradução e o
EPUB sai como recorte aleatório. Ele cobre dois casos que a regra "páginas das
seções N.x, mais 3" erra sozinha: o capítulo **sem seção numerada** (o 1 deste
rascunho é só título e epígrafe, e dava "capítulo 1 não encontrado") e a folga
de 3 páginas **invadindo o capítulo seguinte** (o 2 ia até a 45, onde o 3
começa, e a prévia saía com um capítulo 3 truncado).

## Armadilhas já pagas

- **`llama-server` sem `--n-cpu-moe` trava a máquina.** A Radeon 780M
  também desenha a tela; com o modelo inteiro na iGPU o compositor não pega
  slot e o desktop congela — o kernel segue vivo. Foi o que causou o
  desligamento forçado de 27/07. Suba sempre com a flag (comando no
  `DESENVOLVIMENTO.md`).
- **Dois modelos não cabem.** São 23 GB de RAM; o Gemma pede 14 e o Qwen 18.
  Antes de subir, confira se não há outro `llama-server` no ar — com `--mlock`
  ele não devolve memória, e a disputa reproduz o congelamento acima.
- **O PDF não é marcado** (sem `StructTreeRoot`). A única "tag" disponível é
  a assinatura tipográfica mais os desenhos que delimitam tabela, quadro e
  nota de rodapé.
- **Editar `translate.py` com uma tradução em voo não afeta o processo em
  execução** — o módulo já está carregado. Foi assim que o bake-off
  Qwen×Gemma saiu inválido: cada modelo rodou uma versão diferente do código.
- **Índices de bloco não são estáveis entre extrações.** Qualquer mudança em
  `extract.py` invalida os `.jsonl` de tradução já produzidos.
- **O pós-livro é composto em colunas** — três na bibliografia, quatro no
  índice remissivo — e com recuo PENDENTE, ao contrário do corpo: a entrada
  encosta na margem da coluna e as continuações é que entram. Lido com a regra
  do corpo, saía uma entrada por linha e o texto costurado atravessando as
  colunas ("Department, Istanbul University (3), tic Coreference. Bamman, D.").
- **Capítulo curto era descartado em silêncio.** O `render` terminava com
  `if len(c) > 2` e engolia a folha de rosto, a abertura do Volume I e o
  capítulo 1 inteiro — que neste rascunho é só título e epígrafe.
- **Epígrafe sem atribuição deixava `<div>` aberta.** São 23 epígrafes para 21
  atribuições; os capítulos 8 e 13 saíam com XHTML mal formado, que um leitor
  estrito recusa abrir. Vale conferir com `xml.dom.minidom` a cada mudança na
  montagem.

## A bibliografia sai do texto extraído, nunca do bib.json

Duas fontes, cada uma boa numa coisa. O **texto** vem da extração, que desde a
leitura por coluna sai completo. As **chaves** vêm do `bib.json`, que as tem do
destino nomeado `cite.<chave>` gravado pelo LaTeX — a extração não tem como
sabê-las. Casam pelo início da entrada: 1.256 de 1.263.

O `bib.json` **trunca** a entrada que atravessa a virada de página, então ele
nunca é fonte de texto. Havia uma segunda rota que o usava, para a prévia de
capítulo, e ela saía com "EMNLP. and 2017b. Adversarial multi-criteria" no
lugar da referência. A colheita agora roda **antes de qualquer recorte** e vale
para os dois modos; na prévia só as obras citadas aparecem, com o texto do
original.

**Posição**: depois do último capítulo e ANTES do índice remissivo, como no
impresso. Escrita no fim da montagem, caía depois do índice.

## O exemplo linguístico nunca é traduzido

Duas vias em `translate.py`: **MANTER** ou **GLOSAR** (original intacto mais o
equivalente entre colchetes). Havia uma terceira, TRADUZIR, e ela não se
sustentou — o exemplo deste livro não é ilustração solta, é o objeto que a
prosa ao redor mede, e ela está sempre a um parágrafo de distância:

- *"They picnicked by the pool…"* abre a seção 2.1 para ser CONTADO; o
  parágrafo seguinte diz "16 palavras sem a pontuação, 18 com". Traduzido,
  virou uma frase de 18 e o parágrafo abaixo passou a mentir.
- O exemplo de tokenização vale pela linha `Output` (`" does n't charge $ 10 " .`).
  A tradução devolveu só o `Input`.

`preserva_original` **confere** que o material analisado sobreviveu, em vez de
confiar na instrução: rotular GLOSAR e reescrever daria o mesmo furo. Dois
trechos podem mudar de idioma — a glosa entre colchetes que o próprio livro
traz (a epígrafe francesa do cap. 1) e a glosa em linha própria ao lado de
outra ESCRITA (o chinês) —, porque são auxílio de leitura, não objeto. Um
exemplo todo em inglês não tem glosa a substituir e é cobrado inteiro.

Rodado no cap. 2 (Gemma 4): 18 MANTER, 18 GLOSAR, 2 barrados pela conferência,
**0 tentativas de traduzir** — o prompt sozinho resolveu e a trava ficou de
rede. Sem rótulo por bloco: com o exemplo sempre no original ele saía em 24 dos
24, e o que não informa, atrapalha; a regra é dita uma vez na nota do tradutor.

**Para o review final** — a glosa passou de 7 para 18 e ficou generosa demais em
alguns pontos. Não viola nada (o original está sempre intacto), é gosto:
`lunch?.` → "[em português: almoço?]", os SONETOS de Shakespeare glosados
inteiros, e `The date is 10/15/2011` → "[em português: A data é 15/10/2011]" —
correta, mas o exemplo é sobre o FORMATO de data americano, não sobre a data.
Aperta-se com uma frase no `EXAMPLE_SYSTEM` mandando MANTER quando o exemplo
for amostra de corpus ou listagem de dados.

## Estilo

Aprovado em `docs/style-proofs.html`: **A1** (mastro fiel), **B1** (epígrafe
recuada), **C2** (tag em etiqueta), **D1** (citação como link).

Trocar A/B/D é **só CSS** — editar `ESTILO` em `template.py`. A marcação
emitida é a mesma para todas as variantes. Exceções que exigem remontagem:
C3, C4 e D3, que mudam a marcação e não só a pintura.

O impresso distingue numeral, tag, citação e epígrafe **só pelo azul**, que
em tinta eletrônica é um cinza único. Toda distinção nova deve estar em
peso, caixa, filete ou recuo — cor é bônus.
