#!/usr/bin/env python3
"""
Template de estilo e estrutura do EPUB — este arquivo é o que você aprova.

Princípio: o Kindle reflui o texto. Reproduzir a diagramação de duas colunas
com notas na margem trabalharia contra o dispositivo. O que se preserva é a
HIERARQUIA e a FUNÇÃO de cada elemento, não sua posição na página impressa.

ESTILO APROVADO: A1 · B1 · C2 · D1  (ver docs/style-proofs.html)

Como trocar de estilo
---------------------
A marcação emitida é a MESMA para todas as variantes: a abertura sempre traz
rótulo, numeral, filete e título como elementos separados; a tag sempre sai
como <span class="tagchip"> dentro de <p class="tag">; a citação sempre sai
como <a class="cite"> com autor e ano marcados. Quem decide a aparência é a
classe no <body> — `op-a1 op-b1 op-c2 op-d1`.

Trocar A1→A2, B1→B2 ou D1→D2 é, portanto, SÓ CSS: basta editar a constante
ESTILO abaixo, ou a classe do <body> nos arquivos já gerados. Não é preciso
retraduzir nem remontar o conteúdo.

Exceções, que exigem remontagem porque mudam a marcação e não só a pintura:
  * C3 (marca inline no termo) — a tag deixa de ser um elemento e passa a
    envolver a palavra dentro do parágrafo;
  * C4 (barra de termos da seção) — as tags são reagrupadas sob o título;
  * D3 (marcador sobrescrito) — a citação vira "[1]" e o autor sai do texto.

Decisões de estrutura
---------------------
1. UM ARQUIVO POR CAPÍTULO. O sumário do Kindle lista capítulos; seções e
   subseções viram âncoras dentro do arquivo.

2. A PALAVRA NA MARGEM É UMA TAG, NÃO UM SUBTÍTULO. No impresso ela marca,
   da margem, a linha onde o termo é DEFINIDO, e o Subject Index do fim do
   livro aponta de volta para essas páginas. Sai aqui como etiqueta em caixa,
   sem serifa e menor que o corpo — três sinais de que é metadado.

3. FIGURA E LEGENDA ANDAM JUNTAS, dentro de um <figure>.

4. EXEMPLO LINGUÍSTICO ≠ CÓDIGO. O exemplo ganha caixa clara; código fica em
   <pre>. O exemplo está sempre no original — a caixa é que o distingue da
   prosa, sem rótulo repetido em cada bloco.

5. A EPÍGRAFE TEM ESTILO PRÓPRIO, com a atribuição alinhada à direita e
   ligada à bibliografia quando é uma citação.

6. CITAÇÃO É REFERÊNCIA. As citações do livro são destinos nomeados no PDF
   (`cite.<chave>`), então cada uma vira link para a sua entrada.

Nota sobre cor
--------------
O impresso distingue numeral, tag, citação e epígrafe SÓ pelo azul. Em tinta
eletrônica isso é um único cinza. Aqui cada um carrega a distinção primeiro em
peso, caixa, filete ou recuo — a cor é bônus onde existir cor.
"""

# ---------------------------------------------------------------- estilo ---
CSS = """
/* ==========================================================================
   BASE
   ========================================================================== */
/* @FONTES@ — as declarações @font-face entram aqui na montagem, a partir de
   build/fonts/manifesto.json. São subconjuntos: contêm SÓ os caracteres que
   o livro usa e que uma serifada comum não tem (AFI, grego, operadores,
   tâmil, árabe, CJK). Não trazem o latim básico de propósito — assim o
   corpo do texto continua na fonte escolhida pelo leitor, e a reserva só
   entra glifo a glifo, onde faz falta. */

/* Kindle: serifada para corpo, entrelinha generosa, sem justificar
   (justificação sem hifenização abre rios de espaço em telas estreitas). */
body { font-family: @STACK@; line-height: 1.6; margin: 0 6%;
       text-align: left; }

h1 { font-size: 1.7em; line-height: 1.25; margin: 2em 0 .2em; }
h2 { font-size: 1.3em; margin: 1.8em 0 .4em; color: #1a1a1a; }
h3 { font-size: 1.1em; margin: 1.4em 0 .3em; color: #333; }
h4 { font-size: 1em; font-style: italic; margin: 1.2em 0 .25em; color: #444; }

p  { margin: 0 0 .8em; }
p.primeiro { text-indent: 0; }
p + p { text-indent: 1.2em; margin-top: -.4em; }   /* parágrafo corrido */

/* Folha de rosto e divisor de volume: no impresso, cada linha é composta
   como título ("Third Edition draft", "Daniel Jurafsky", "Volume I"). No
   EPUB seguem no mesmo arquivo da página, centradas e sem o espaço de
   respiro que um h2 de seção pede — senão a folha de rosto vira uma
   sequência de seções soltas. */
h2.rosto { font-size: 1.15em; font-weight: normal; text-align: center;
           margin: .9em 0 .3em; color: #1a1a1a; }
h2.rosto + p { text-align: center; text-indent: 0; }

/* ==========================================================================
   A — ABERTURA DE CAPÍTULO
   A marcação é sempre a mesma; a variante ativa decide se o numeral fica ao
   lado do título (A1) ou empilhado sobre ele (A2).
   ========================================================================== */
.abertura { margin: 0 0 1.6em; }
.abertura .rotulo { font-size: .78em; letter-spacing: .16em;
                    text-transform: uppercase; color: #666;
                    margin: 0 0 .15em; line-height: 1; text-indent: 0; }
.abertura .numeral { font-size: 3.4em; line-height: .92; color: #1c1ce6;
                     margin: 0; text-indent: 0; }
.abertura .titulo { font-size: 1.8em; font-weight: bold; line-height: 1.14;
                    margin: 0; }

/* --- A1: mastro fiel — rótulo e numeral à esquerda, filete, título ------- */
/* display:table e nao flexbox: leitores KF8 antigos nao implementam flex,
   mas implementam tabela. */
.op-a1 .abertura { display: table; width: 100%; }
.op-a1 .abertura .lado { display: table-cell; vertical-align: bottom;
                         width: 1%; white-space: nowrap; padding-right: 1em; }
.op-a1 .abertura .filete { display: table-cell; width: 1px;
                           background: #999; }
.op-a1 .abertura .titulo { display: table-cell; vertical-align: bottom;
                           padding-left: 1em; }

/* --- A2: prancha empilhada (mais robusta em 6") ------------------------- */
.op-a2 .abertura .lado { display: block; }
.op-a2 .abertura .filete { display: block; height: 2px; background: #333;
                           margin: .35em 0 .5em; }
.op-a2 .abertura .titulo { display: block; }

/* --- A4: so folio, sem numeral ------------------------------------------ */
.op-a4 .abertura .numeral { display: none; }
.op-a4 .abertura .filete { display: block; height: 1px; background: #bbb;
                           margin: .6em 0 0; }

/* ==========================================================================
   B — EPIGRAFE
   ========================================================================== */
.epigrafe { margin: 0 0 1.7em; }
.epigrafe .texto { margin: 0; }
.epigrafe .texto.verso { font-style: italic; }
.epigrafe .atrib { text-align: right; font-size: .84em; margin: .7em 0 0;
                   text-indent: 0; }

/* dialogo: interlocutor e fala como duas celulas, para que uma fala longa
   quebre embaixo de si mesma em vez de arrebentar a coluna */
.epigrafe .fala { display: table; width: 100%; margin: 0 0 .15em;
                  font-family: monospace; font-size: .8em; line-height: 1.5; }
.epigrafe .quem { display: table-cell; width: 1%; white-space: nowrap;
                  padding-right: .9em; color: #666; }
.epigrafe .diz { display: table-cell; }

/* --- B1: recuo fiel (aprovado) ------------------------------------------ */
.op-b1 .epigrafe { padding-left: 8%; }

/* --- B2: banda com filetes ---------------------------------------------- */
.op-b2 .epigrafe { padding: .9em 0; border-top: 1px solid #ccc;
                   border-bottom: 1px solid #ccc; }
.op-b2 .epigrafe .atrib { color: #555; font-style: italic; }

/* --- B3: painel ---------------------------------------------------------- */
.op-b3 .epigrafe { background: #f4f2ec; padding: 1em 1.1em;
                   border-left: 3px solid #ccc; }

/* ==========================================================================
   EXEMPLO NUMERADO — "(2.3) 姚 明 进入 总 决赛" com glosa embaixo
   ========================================================================== */
.numex { display: table; width: 100%; margin: 1em 0; text-indent: 0; }
.numex .nx-num { display: table-cell; width: 1%; white-space: nowrap;
                 padding-right: 1em; vertical-align: top; color: #1c1ce6;
                 font-size: .9em; }
.numex .nx-corpo { display: table-cell; vertical-align: top;
                   line-height: 1.45; }

/* ==========================================================================
   C — TAGS (as palavras que no impresso ficam na margem)
   ========================================================================== */
.tag { margin: 1.1em 0 .3em; line-height: 1; text-indent: 0; }
.tagchip { font-family: sans-serif; font-size: .68em; letter-spacing: .07em;
           text-transform: uppercase; font-weight: bold; color: #555;
           border: 1px solid #bbb; padding: .12em .5em;
           margin: 0 .3em .1em 0; display: inline-block; }

/* --- C1: trilho de margem (fiel ao impresso, fragil em KF8) ------------- */
.op-c1 .tag { float: left; clear: left; width: 22%; margin: .25em 0 .4em -26%;
              text-align: right; }
.op-c1 .tagchip { border: 0; padding: 0; text-transform: none;
                  font-family: Georgia, serif; font-size: .72em;
                  color: #1c1ce6; letter-spacing: 0; }

/* --- C2: etiqueta em caixa (aprovada) ----------------------------------- */
/* nada a acrescentar: e o estilo base de .tag/.tagchip acima */

/* ==========================================================================
   D — CITACOES E BIBLIOGRAFIA
   ========================================================================== */
a.cite { text-decoration: none; }

/* --- D1: link fiel (aprovado) ------------------------------------------- */
.op-d1 a.cite { color: #1c1ce6; }

/* --- D2: autor em versalete, ano com a cor ------------------------------ */
.op-d2 a.cite { color: inherit; }
.op-d2 a.cite .au { font-variant: small-caps; letter-spacing: .02em; }
.op-d2 a.cite .an { color: #1c1ce6; }

.bibliografia .entrada { padding-left: 1.4em; text-indent: -1.4em;
                         margin: 0 0 .6em; font-size: .9em; line-height: 1.5; }

/* Índice remissivo: mesma lógica de recuo pendente da bibliografia, mais
   apertado — no original é uma lista densa em quatro colunas. Sem a classe,
   a regra do parágrafo corrido (p + p) recuava a partir da SEGUNDA entrada,
   invertendo o degrau. O número da página do impresso não navega num texto
   que reflui; fica como referência, em negrito onde o original destaca. */
p.entrada { padding-left: 1.2em; text-indent: -1.2em;
            margin: 0 0 .25em; font-size: .9em; line-height: 1.4; }

/* ==========================================================================
   QUADRO — caixa de algoritmo/pseudocódigo, moldurada no original
   ========================================================================== */
.quadro { border: 1px solid #999; padding: .7em .9em; margin: 1.4em 0 .4em;
          page-break-inside: avoid; }
.quadro p { margin: 0 0 .35em; text-indent: 0; font-size: .92em;
            line-height: 1.4; }
.quadro p + p { text-indent: 0; margin-top: 0; }
.quadro .formula { margin: .4em 0; }
.quadro pre { margin: .4em 0; border: 0; background: transparent;
              padding: 0; }

/* ==========================================================================
   DEMAIS ELEMENTOS
   ========================================================================== */
/* A legenda tem de medir o MESMO que a imagem, não a largura da página:
   solta na medida inteira, ela flutuava longe de uma figura estreita.
   display:table faz a figura encolher até a imagem, e a legenda como
   table-caption herda essa largura. Tabela e não flexbox: leitores KF8
   antigos implementam a primeira, não a segunda. */
figure { display: table; margin: 1.6em auto; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
figcaption { display: table-caption; caption-side: bottom;
             font-size: .82em; color: #444; text-align: left;
             padding-top: .5em; line-height: 1.45; }
figcaption .rot { font-weight: bold; }

/* Exemplo linguistico: preservado em ingles por decisao editorial. */
.exemplo { background: #f7f5f0; border-left: 4px solid #b0a68c;
           padding: .7em .9em; margin: 1.1em 0; font-family: monospace;
           font-size: .85em; line-height: 1.45; white-space: pre-wrap;
           text-indent: 0; }
/* (o exemplo não tem mais rótulo: está sempre no original, e a tarja à
   esquerda mais a monoespaçada já o distinguem da prosa) */

pre { background: #f2f2f2; border-left: 4px solid #999; padding: .7em .9em;
      margin: 1.1em 0; font-size: .82em; line-height: 1.4;
      white-space: pre-wrap; word-wrap: break-word; text-indent: 0; }

.formula { text-align: center; font-style: italic; margin: 1em 0;
           font-size: .95em; text-indent: 0; }
/* equação numerada: fórmula centrada, número encostado à direita */
.formula.num { display: table; width: 100%; text-align: left; }
.formula.num .eq { display: table-cell; text-align: center; width: 100%; }
/* a imagem da equação acompanha o corpo do texto, sem estourar a medida */
img.eqimg { max-width: 100%; height: auto; vertical-align: middle; }
.formula.num .eq-num { display: table-cell; white-space: nowrap;
                       text-align: right; font-style: normal;
                       font-size: .9em; vertical-align: middle; }

/* legenda de um bloco que não é imagem (pseudocódigo, trace) — mesma
   tipografia de figcaption, para ler como legenda e não como nota solta */
.legenda { font-size: .82em; color: #444; margin: -.4em 0 1.2em;
           line-height: 1.45; text-indent: 0; }
.legenda .rot { font-weight: bold; }

/* ==========================================================================
   NOTA DE RODAPÉ — no impresso, corpo menor abaixo de um filete curto
   ========================================================================== */
.notas { margin: 2.2em 0 0; border-top: 1px solid #999;
         padding-top: .7em; }
.nota { display: block; margin: 0 0 .5em; }
.nota p { font-size: .82em; line-height: 1.45; margin: 0;
          text-indent: 0; color: #333; }
.nota .nota-volta { font-weight: bold; text-decoration: none;
                    color: #1c1ce6; margin-right: .4em; }
a.notaref { text-decoration: none; color: #1c1ce6; }
a.notaref sup { font-size: .7em; }

.nota-tradutor { border: 1px solid #bbb; background: #fbfaf7;
                 padding: 1.2em; margin: 1.5em 0; font-size: .95em; }
.nota-tradutor h2 { margin-top: 0; border: none; }
"""

# Classes que ativam a variante escolhida. Trocar aqui re-pinta o livro
# inteiro sem tocar no conteudo — desde que a variante nao mude a marcacao
# (ver o cabecalho deste arquivo).
ESTILO = "op-a1 op-b1 op-c2 op-d1"

# ------------------------------------------------------------ nota inicial ---
NOTA_TRADUTOR = """
<div class="nota-tradutor">
<h2>Nota do tradutor</h2>
<p>Tradução automática para o português do Brasil de <i>Speech and Language
Processing</i> (3ª edição, rascunho de 6 de janeiro de 2026), de Daniel
Jurafsky e James H. Martin, produzida para leitura pessoal.</p>

<p><b>Os exemplos linguísticos ficam em inglês.</b> Este é um livro sobre
processamento de linguagem natural, e neles a língua é o objeto de estudo, não
o veículo:</p>

<ul>
<li><b>Mantidos no original</b>, sempre. O exemplo deste livro não é ilustração
solta: é o objeto que o texto ao redor mede. A frase que abre a seção 2.1 existe
para ser contada — o parágrafo seguinte diz que ela tem 16 palavras —, e o
exemplo de tokenização vale pela saída <i>does n’t charge $ 10</i>, não pelo
sentido. Traduzir faria o livro se contradizer a um parágrafo de distância.</li>

<li><b>Glosados</b> quando são linguagem corrente e o sentido ajuda: o original
fica intacto e o equivalente em português vem entre colchetes. É o caso da
epígrafe francesa do capítulo 1 e dos exemplos em chinês e cantonês.</li>
</ul>

<p>Código e fórmulas permanecem sempre no original.</p>

<p>Os termos que o livro impresso destaca na margem são <b>marcas de índice</b>:
apontam a passagem onde o termo é definido, e o índice remissivo do original
remete a elas. Aqui aparecem como etiqueta, imediatamente antes do parágrafo
que define o termo.</p>

<p>As citações mantêm autor e ano do original e remetem à bibliografia, que
não foi traduzida — títulos de obras ficam como publicados.</p>

<p>A terminologia técnica segue um glossário fixo aplicado às 626 páginas,
para que um mesmo termo não apareça traduzido de duas formas em capítulos
diferentes.</p>
</div>
"""
