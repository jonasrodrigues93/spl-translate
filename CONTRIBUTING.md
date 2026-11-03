# Como colaborar

Obrigado por ajudar a melhorar esta tradução. Ela nasceu automática, então há
muito o que corrigir: erros de sentido, termos técnicos em inglês por engano,
inconsistência de terminologia e falhas de formatação.

## O que ajuda

- **Corrigir a tradução** de um trecho.
- **Padronizar um termo** (propor uma entrada no glossário).
- **Corrigir formatação**: negrito perdido, parágrafo quebrado, figura fora de
  lugar.
- **Melhorar o código** do pipeline.

## Antes de começar

- O livro é de Jurafsky & Martin, com todos os direitos reservados. Não envie
  o PDF nem trechos grandes do original; cite só o necessário para localizar o
  erro (capítulo, seção e algumas palavras).
- Ao enviar uma correção, você concorda que ela siga as mesmas condições do
  arquivo que altera: MIT para código e documentação; para o texto traduzido,
  as condições descritas no README (seção "Direitos autorais").

## Corrigir a tradução

1. Abra uma *issue* "Erro de tradução" com: **capítulo e seção**, **trecho
   original**, **tradução atual** e **sugestão**. Ou vá direto ao passo 2.
2. Edite `traducao/livro.jsonl`: cada linha é um bloco, `{"i": 64, "pt": "..."}`.
   Ache a linha buscando o texto atual em português e altere só o campo `pt`.
   Abra um *pull request*.
3. Mantenha os marcadores intactos: `«i»…«/i»`, `«b»…«/b»`, `«code»…«/code»`,
   `«sup»`/`«sub»`. O texto dentro deles **pode e deve ser traduzido**; só os
   marcadores se preservam. Não mude o campo `i`.
4. Um PR por capítulo ou por tema. PRs pequenos são revisados mais rápido.

O EPUB é gerado automaticamente a cada *release*; não há `.epub` no repositório.

## Regras de tradução

- Exemplos linguísticos ficam em inglês (com glosa entre colchetes quando
  ajuda). Código e fórmulas ficam no original.
- Use o mesmo termo para o mesmo conceito em todo o livro; consulte o glossário
  no `translate.py` antes de propor outro.
- Registro acadêmico, claro, na 1ª pessoa do plural quando o original usar
  *we* ("vemos que", "definimos").

## Mexer no código

```
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

- Qualquer mudança em `extract.py` invalida os `.jsonl` já traduzidos: os
  índices de bloco não são estáveis entre extrações.
- O extrator e os scripts que o usam têm de ler igual. Funções compartilhadas
  vivem em `extract.py` e são importadas por `bib.py`, `translate.py` e
  `build_epub.py`; não as reescreva em outro lugar.
- Ao mexer na montagem, confira o XML do EPUB gerado (`xml.dom.minidom`); o
  workflow já faz isso.
- Não remova o `validar()` do `extract.py` sem substituí-lo. O `AGENTS.md`
  explica por quê.

## Commits e branches

- `main` é protegida: todo trabalho entra por *pull request*.
- Branches: `cap-NN/assunto` (tradução), `codigo/assunto`, `docs/assunto`.
- Mensagens em português, no estilo Conventional Commits:
  `fix(cap3): corrige tradução de "perplexity"`, `feat(build): ...`,
  `docs: ...`, `refactor: ...`.
- Nunca inclua chaves de API, caminhos da sua máquina, o PDF ou qualquer
  arquivo de `build/`.

## Versionamento

Há duas coisas versionadas, de forma independente.

**Edição do livro** — tag `ed3-AAAA.MM-rN`, em que `AAAA.MM` é o mês do
rascunho de origem e `N` é a revisão da tradução. Exemplo: `ed3-2026.08-r1` é a
primeira versão, automática, sobre o rascunho de agosto de 2026;
`ed3-2026.08-r2` incorpora as primeiras correções. Quando os autores publicarem
um rascunho novo, a série recomeça: `ed3-2027.01-r1`.

**Código** — SemVer (`vMAJOR.MINOR.PATCH`). Uma mudança que invalida traduções
já feitas (em geral, no `extract.py`) é `MAJOR`.

Publicar uma *release* com a tag da edição dispara o workflow, que gera o EPUB
e o anexa à release. Cada tag vem com uma entrada no `CHANGELOG.md` (o que foi
corrigido, por capítulo).
