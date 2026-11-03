# spl-translate

**Português** · [English](README.en.md)

*Speech and Language Processing* em português do Brasil, para ler no Kindle.

Uma tradução gratuita e colaborativa da 3ª edição (rascunho de 19 de agosto de
2026) do livro de Daniel Jurafsky e James H. Martin, referência mundial para
quem quer aprender processamento de linguagem natural e modelos de linguagem.

## Por que existe

Material técnico dessa qualidade quase não existe em português. A barreira do
idioma afasta estudantes e profissionais brasileiros de uma das áreas que mais
crescem, principalmente quem não tem como pagar um curso em inglês. Este projeto
quer abrir esse conhecimento, de graça.

## Baixe o livro

Pegue o e-book na página da [última versão](https://github.com/jonasrodrigues93/spl-translate/releases/latest).
É um EPUB pronto para o Kindle e para a maioria dos leitores de e-book, e o
número da versão aparece no nome do arquivo.

## Como funciona

1. O livro original é lido página por página: textos, títulos, figuras,
   tabelas, citações e bibliografia.
2. Um modelo de inteligência artificial, rodando no próprio computador, traduz o
   texto trecho a trecho. Um glossário fixo garante que o mesmo termo técnico
   seja sempre traduzido do mesmo jeito.
3. O que não deve ser traduzido é preservado: os exemplos de linguagem ficam em
   inglês (às vezes com o equivalente em português ao lado), e o código e as
   fórmulas permanecem como no original.
4. Tudo é montado em um e-book com capa, sumário, figuras e uma nota do
   tradutor, pensado para a tela do Kindle.
5. A cada nova versão publicada, o e-book é gerado de novo e disponibilizado
   automaticamente.

## Estado atual

A primeira versão é uma tradução automática, **sem revisão humana**: pode haver
erros de tradução, termos técnicos em inglês por engano e falhas de formatação.
Ela melhora com a ajuda de quem lê.

## Ajude a melhorar

Encontrou um erro? Abra uma *issue* com o trecho do texto e o que deveria estar
no lugar. O passo a passo está no [CONTRIBUTING](CONTRIBUTING.md).

## Direitos autorais

O livro é © 2026 Jurafsky & Martin, "all rights reserved" (página 1 do PDF). O
PDF original é distribuído pelos autores para leitura, e este repositório não o
inclui.

- **Código e documentação** deste repositório: licença MIT ([LICENSE](LICENSE)).
- **Texto traduzido** e **e-book** das versões: obra derivada do livro, que
  continua sob os direitos dos autores. A licença MIT **não** os cobre.

## Para desenvolvedores

Como o pipeline é montado e executado: [DESENVOLVIMENTO](DESENVOLVIMENTO.md).
