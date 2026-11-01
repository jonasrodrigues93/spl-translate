#!/usr/bin/env python3
"""
Fase 2 - Tradução EN->pt-BR via llama-server local.

Requisitos que moldaram o desenho:
  * ~10h de execução: precisa sobreviver a queda. Checkpoint por lote, em
    JSONL append-only. Reexecutar retoma de onde parou.
  * Marcação inline «i»/«b»/«code» não pode se perder: cada lote é validado
    e retraduzido individualmente se quebrar.
  * Terminologia consistente em 626 páginas: glossário fixo no prompt do
    sistema, que o llama.cpp mantém em cache entre requisições.

Uso:
    ./venv/bin/python translate.py            # traduz tudo
    ./venv/bin/python translate.py --cap 2    # só o capítulo 2 (piloto)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from extract import chapter_pages

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
# Servidor e concorrência vêm da linha de comando: mais de um llama-server
# pode estar no ar (portas e modelos diferentes), e apontar para o errado
# gasta horas de tradução com o modelo que não se queria. WORKERS tem de
# casar com o --parallel do servidor: contra um servidor de 1 slot, 4
# requisições concorrentes só formam fila.
URL = "http://127.0.0.1:8099/v1/chat/completions"
WORKERS = 4
BACKEND = "local"
MODEL = ""
HEADERS = {"Content-Type": "application/json"}

# Blocos que vão para o modelo. figure/code/example/math ficam em inglês.
TRANSLATABLE = {"para", "heading1", "heading2", "heading3", "heading4",
                "caption", "margin", "epigraph_attrib"}

GLOSSARY = """MANTER em inglês (o termo é usado assim no Brasil):
token | tokenizer | subword | prompt | prompting | embedding | word embedding
transformer | fine-tuning | instruction tuning | attention head | feedforward
overfitting | backoff | beam search | teacher forcing | corpus | corpora
zero-shot | few-shot | chain-of-thought
feature | tagging | recall | span

TRADUZIR (sempre o mesmo termo em português):
language model->modelo de linguagem | large language model->grande modelo de linguagem
language modeling->modelagem de linguagem | neural network->rede neural
deep learning->aprendizado profundo | machine learning->aprendizado de máquina
reinforcement learning->aprendizado por reforço | machine translation->tradução automática
speech recognition->reconhecimento de fala | tokenization->tokenização
attention->atenção | self-attention->autoatenção | cross-attention->atenção cruzada
encoder->codificador | decoder->decodificador | decoding->decodificação
greedy decoding->decodificação gulosa | inference->inferência
pretraining->pré-treinamento | training set->conjunto de treinamento
test set->conjunto de teste | development set->conjunto de desenvolvimento
loss function->função de perda | cross-entropy->entropia cruzada
gradient descent->gradiente descendente | backpropagation->retropropagação
logistic regression->regressão logística | hidden layer->camada oculta
hidden state->estado oculto | layer norm->normalização de camada
weight->peso | open weights->pesos abertos | closed weights->pesos fechados
dot product->produto escalar | context window->janela de contexto
reward model->modelo de recompensa | scaling law->lei de escala
hallucination->alucinação | smoothing->suavização | perplexity->perplexidade
vocabulary->vocabulário | word type->tipo de palavra | word instance->ocorrência de palavra
precision->precisão
parsing->análise sintática | parser->analisador sintático
dependency parsing->análise de dependência | part-of-speech->classe gramatical
sequence labeling->rotulagem de sequências
named entity->entidade nomeada | entity linking->vinculação de entidades
coreference->correferência | discourse->discurso | coherence->coerência
semantic role->papel semântico | word sense->sentido da palavra
question answering->resposta a perguntas | information retrieval->recuperação de informação
information extraction->extração de informação | hidden Markov model->modelo oculto de Markov
maximum likelihood->máxima verossimilhança | dynamic programming->programação dinâmica
edit distance->distância de edição | sentiment analysis->análise de sentimento"""

SYSTEM = f"""Você é tradutor técnico especializado em modelos de linguagem e NLP.

Este é um livro-texto acadêmico sobre modelos de linguagem e NLP. Traduza do
inglês para o português do Brasil, preservando o sentido, a precisão e o
registro acadêmico.

REGRAS:
1. Preserve EXATAMENTE os marcadores «i»...«/i», «b»...«/b», «code»...«/code»
   e «sup»/«sub» (expoente, índice ou chamada de nota: só um número, não traduza).
   Não invente marcadores novos, não os remova, não altere a ordem.
2. TRADUZA normalmente o texto dentro de «i» e «b» — são termos técnicos
   sendo definidos, não exemplos a preservar.
3. NÃO traduza o conteúdo dentro de «code»: é código, regex ou símbolo.
4. Mantenha números, fórmulas, nomes próprios e referências bibliográficas
   ("Jurafsky and Martin, 2026") como estão.
5. Use rigorosamente este glossário: os termos em MANTER ficam em inglês; os
   de TRADUZIR levam sempre a tradução indicada, sem variantes.
{GLOSSARY}
6. Para termo técnico fora do glossário, TRADUZA quando houver tradução
   corrente em português do Brasil; só mantenha o inglês se não houver.
7. Registro: acadêmico, claro, na 1ª pessoa do plural quando o original usar
   "we" ("vemos que", "definimos").
8. Responda APENAS com a tradução. Sem preâmbulo, sem aspas, sem comentário."""

# --------------------------------------------------------------------------
# Exemplos linguísticos: o exemplo NUNCA é traduzido. Duas vias, MANTER ou
# GLOSAR, e a glosa só ACRESCENTA.
#
# Havia uma terceira via, TRADUZIR, para quando o inglês parecesse incidental.
# Ela não se sustentou: o exemplo do livro não é ilustração solta, é objeto que
# o texto ao redor mede. Dois casos do cap. 2, ambos no EPUB gerado em 7/2026:
#
#   * "They picnicked by the pool, then lay back on the grass and looked at
#     the stars." abre a seção 2.1 e existe para ser CONTADO — o parágrafo
#     seguinte diz "esta frase tem 16 palavras se não contarmos a pontuação,
#     18 se contarmos". Traduzido, virou uma frase de 18 palavras e o
#     parágrafo abaixo dele passou a mentir.
#   * O exemplo de tokenização traz Input e Output ("does n't charge $ 10"),
#     e o Output é o fenômeno demonstrado. A tradução devolveu só o Input.
#
# Traduzir um exemplo custa a coerência com a prosa que o comenta, e essa
# prosa está sempre a um parágrafo de distância. Manter o original custa ao
# leitor uma frase em inglês — que a glosa resolve, sem tocar no original.
EXAMPLE_SYSTEM = """Você prepara exemplos de um livro de Processamento de Linguagem
Natural traduzido para o português do Brasil.

REGRA ABSOLUTA: o exemplo NUNCA é traduzido. Ele sai em inglês, palavra por
palavra, exatamente como no original, inclusive pontuação, espaçamento e
quebras de linha. O texto ao redor conta as palavras do exemplo e comenta a
forma delas; mudá-lo faz o livro se contradizer.

Sua única decisão é acrescentar ou não uma glosa em português.

MANTER — o exemplo se explica pela forma, e uma glosa seria ruído:
  segmentação em morfemas, sequências de letras (BPE), expressões regulares
  sobre grafia inglesa, fonemas, code points Unicode, dados hexadecimais,
  saída de comando, entrada e saída de um tokenizador, listas de tokens.

GLOSAR — é linguagem corrente, e o leitor de português ganha em saber o
  sentido: frase ilustrativa, diálogo, texto em terceira língua (francês,
  chinês, alemão). O original fica INALTERADO e a glosa vem depois.

Responda em UMA linha com o rótulo, e nas linhas seguintes o resultado:

MANTER
<o exemplo original, inalterado>

GLOSAR
<o exemplo original, inalterado>
[em português: <a glosa>]

Sem preâmbulo, sem comentário, sem aspas."""

# TRADUZIR continua reconhecida de propósito: o modelo às vezes a emite mesmo
# instruído a não fazê-lo, e é melhor detectar e recusar — contabilizando —
# do que deixar cair no ramo "sem rótulo claro" e não saber que aconteceu.
DECISION = re.compile(r"^\s*(TRADUZIR|MANTER|GLOSAR)\s*\n", re.I)

MARCA_EX = re.compile(r"«/?(?:i|b|code|sup|sub)»")
ESPACO = re.compile(r"\s+")
COLCHETE = re.compile(r"\[[^\[\]]*\]")
ASPAS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
# A partir dos radicais CJK: distingue OUTRA ESCRITA de latino acentuado. As
# aspas tipográficas ficam abaixo desse ponto, e o francês da epígrafe também.
FORA_DO_LATIM = 0x2E80


def _ex_norm(t: str) -> str:
    """Forma canônica de um exemplo, para comparar original com resposta."""
    t = MARCA_EX.sub(" ", t).translate(ASPAS)
    return ESPACO.sub(" ", t).strip().lower()


def _outra_escrita(t: str) -> bool:
    return any(ord(c) >= FORA_DO_LATIM for c in t)


def preserva_original(src: str, out: str) -> bool:
    """O material ANALISADO do exemplo sobreviveu na resposta?

    A instrução de não traduzir não é garantia: o modelo pode rotular GLOSAR e
    reescrever o exemplo assim mesmo. Sem esta conferência, a via nova teria
    exatamente o furo da que ela substitui — foi assim que o exemplo de
    tokenização perdeu a linha `Output` e a frase do piquenique passou de 16
    para 18 palavras.

    O que se protege é o material que a prosa ao redor analisa, não cada
    caractere. Dois trechos podem mudar de idioma sem que nada se perca,
    porque são auxílio de leitura do próprio livro e não objeto de estudo:

      * a glosa entre colchetes — a epígrafe do cap. 1 traz o francês seguido
        de "[The last thing you figure out...]", e trocar essa parte por
        português é o que uma edição em português faz;
      * a glosa em linha própria ao lado de outra ESCRITA — "姚明进入总决赛"
        seguido de "Yao Ming reaches the finals". Vale só quando a linha em
        escrita não latina sobreviveu: se o chinês mudou, não é glosa, é
        reescrita.

    Fora esses dois, tudo tem de sobreviver. Em particular um exemplo todo em
    inglês — que é a maioria, e onde o inglês É o objeto — não tem glosa a
    substituir e é cobrado inteiro.
    """
    alvo = _ex_norm(out)
    linhas = [l for l in src.split("\n") if _ex_norm(l)]
    faltam = [l for l in linhas if _ex_norm(COLCHETE.sub(" ", l)) not in alvo]
    if not faltam:
        return True
    ancora = [l for l in linhas if _outra_escrita(l) and _ex_norm(l) in alvo]
    if not ancora:
        return False
    return all(not _outra_escrita(l) for l in faltam)


def handle_example(text: str) -> tuple[str, str]:
    """Devolve (decisão, texto_final) para um bloco de exemplo.

    Em qualquer dúvida devolve o original: o custo de uma glosa perdida é o
    leitor ler uma frase em inglês; o de um exemplo alterado é o parágrafo
    seguinte deixar de bater com ele.
    """
    out = call(text, max_tokens=len(text) // 2 + 700, system=EXAMPLE_SYSTEM)
    m = DECISION.match(out)
    if not m:
        return "MANTER", text          # sem rótulo claro: não arrisca
    dec = m.group(1).upper()
    body = out[m.end():].strip()
    if dec == "TRADUZIR":
        return "RECUSADO", text        # a via não existe mais
    if dec == "MANTER" or not body:
        return "MANTER", text
    if not preserva_original(text, body):
        return "ALTERADO", text        # rotulou GLOSAR e reescreveu: descarta
    return dec, body


TAG = re.compile(r"«/?(?:i|b|code|sup|sub)»")
INNER = re.compile(r"«(i|b|code|sup|sub)»(.*?)«/\1»", re.S)
ITEM = re.compile(r"^\s*\[(\d+)\]\s?", re.M)


def pack(items: list[dict]) -> str:
    """Numera os itens do lote. Um separador solto («<<<->>>») o modelo perde
    com facilidade; a numeração ele mantém, e o número permite detectar
    omissão ou reordenação em vez de desalinhar tudo silenciosamente."""
    return "\n".join(f"[{n+1}] {it['text']}" for n, it in enumerate(items))


def unpack(out: str, n: int) -> list[str] | None:
    """Remonta pela numeração; None se algum item faltar ou vier fora de ordem."""
    idx = [(int(m.group(1)), m.start(), m.end()) for m in ITEM.finditer(out)]
    if len(idx) != n or [i for i, _, _ in idx] != list(range(1, n + 1)):
        return None
    res = []
    for k, (_, _, e) in enumerate(idx):
        stop = idx[k + 1][1] if k + 1 < len(idx) else len(out)
        res.append(out[e:stop].strip())
    return res


def markup_ok(src: str, out: str) -> tuple[bool, str]:
    if TAG.findall(src) != TAG.findall(out):
        return False, "sequência de tags diferente"
    si, oi = INNER.findall(src), INNER.findall(out)
    if len(si) != len(oi):
        return False, "número de pares diferente"
    for (t, a), (_, b) in zip(si, oi):
        a, b = a.strip(), b.strip()
        if a == b:
            continue                      # símbolo/variável: não se traduz
        if t == "code":
            return False, f"código alterado: {a!r} -> {b!r}"
        if not b or set(b) <= set(". "):
            return False, "conteúdo descartado dentro da tag"
        if len(b) < max(2, len(a) * 0.3):
            return False, f"conteúdo encolheu: {a!r} -> {b!r}"
    return True, ""


def call(text: str, max_tokens: int, retries: int = 3,
         system: str | None = None) -> str:
    body = json.dumps({
        **({"model": MODEL} if MODEL else {}),
        "messages": [{"role": "system", "content": system or SYSTEM},
                     {"role": "user", "content": text}],
        "temperature": 0.2, "max_tokens": max_tokens, "stream": False,
        **({"reasoning": {"exclude": True}}
           if BACKEND == "openrouter" else {}),
        **({"thinking": {"type": "disabled"}}
           if BACKEND == "deepseek" else {}),
    }).encode()
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                URL, data=body, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=1800) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            last = str(e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"servidor não respondeu: {last}")


def batches(items: list[dict], max_chars: int = 4000, max_items: int = 40):
    """Agrupa por tamanho, separando micro de macro.

    Notas de margem são 34% dos blocos do livro e têm ~15 caracteres. Misturadas
    com parágrafos, cada uma acabava numa requisição própria e dominava o tempo
    total. Agrupadas entre si, vão ~120 por requisição.
    """
    micro = [i for i in items if len(i["text"]) < 60]
    macro = [i for i in items if len(i["text"]) >= 60]
    for group, lim in ((micro, max_items * 3), (macro, max_items)):
        cur, n = [], 0
        for it in group:
            if cur and (n + len(it["text"]) > max_chars or len(cur) >= lim):
                yield cur
                cur, n = [], 0
            cur.append(it)
            n += len(it["text"])
        if cur:
            yield cur


def section_batches(items: list[dict], max_chars: int = 50000):
    """Agrupa uma seção inteira para backends com contexto amplo.

    heading3 inicia uma seção; heading4 permanece nela. heading2 separa o
    capítulo anterior do seguinte. O limite só protege contra seções fora do
    padrão, como a bibliografia; os cortes continuam entre blocos.
    """
    boundaries = {"heading2", "heading3"}
    cur, chars, has_body = [], 0, False
    for item in items:
        kind = item["kind"]
        if kind in boundaries and cur and has_body:
            yield cur
            cur, chars, has_body = [], 0, False
        if cur and chars + len(item["text"]) > max_chars:
            yield cur
            cur, chars, has_body = [], 0, False
        cur.append(item)
        chars += len(item["text"])
        has_body |= kind not in boundaries
    if cur:
        yield cur


def batch_max_tokens(text: str) -> int:
    """Dá às seções maiores espaço de saída sem estourar o backend local."""
    limit = 32768 if BACKEND in ("openrouter", "deepseek") else 6144
    return min(limit, len(text) // 2 + 1200)


def main() -> int:
    global URL, WORKERS, BACKEND, MODEL, HEADERS
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, help="traduzir só um capítulo (piloto)")
    ap.add_argument("--out", default="translated.jsonl")
    ap.add_argument("--repair", action="store_true",
                    help="refaz só os blocos com marcação quebrada")
    ap.add_argument("--porta", type=int, default=8099,
                    help="porta do llama-server (padrão 8099)")
    ap.add_argument("--workers", type=int, default=4,
                    help="requisições concorrentes; = --parallel do servidor")
    ap.add_argument("--backend", choices=("local", "openrouter", "deepseek"),
                    default="local",
                    help="backend de tradução (padrão: local)")
    ap.add_argument("--modelo", help="modelo no backend remoto")
    args = ap.parse_args()

    BACKEND = args.backend
    if BACKEND == "openrouter":
        MODEL = args.modelo or "deepseek/deepseek-v4-flash"
    elif BACKEND == "deepseek":
        MODEL = args.modelo or "deepseek-v4-flash"
    else:
        MODEL = ""
    HEADERS = {"Content-Type": "application/json"}
    if BACKEND in ("openrouter", "deepseek"):
        key = os.environ.get("OPENROUTER_API_KEY")
        provider = "openrouter"
        if BACKEND == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY")
            provider = "deepseek"
        if not key:
            auth_path = Path(os.environ.get(
                "OPENCODE_AUTH_FILE",
                str(Path.home() / ".local/share/opencode/auth.json")))
            try:
                auth = json.loads(auth_path.read_text(encoding="utf-8"))
                key = auth[provider]["key"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                print(f"chave {provider} não encontrada em {auth_path}",
                      file=sys.stderr)
                return 2
        if not key:
            print(f"chave {provider} vazia", file=sys.stderr)
            return 2
        if BACKEND == "openrouter":
            URL = "https://openrouter.ai/api/v1/chat/completions"
        else:
            URL = "https://api.deepseek.com/chat/completions"
        HEADERS["Authorization"] = f"Bearer {key}"
        if BACKEND == "openrouter":
            HEADERS["HTTP-Referer"] = "https://github.com/jonas/ed3book-ptbr"
            HEADERS["X-Title"] = "ed3book-ptbr"
    else:
        URL = f"http://127.0.0.1:{args.porta}/v1/chat/completions"
    WORKERS = args.workers
    print(f"backend: {BACKEND}  endpoint: {URL}  ({WORKERS} requisições concorrentes)")

    blocks = json.loads((BUILD / "blocks.json").read_text(encoding="utf-8"))

    # O índice é atribuído ANTES de qualquer filtro e nunca muda: é a chave
    # que o build_epub usa para casar tradução com bloco. Re-enumerar depois
    # de filtrar por capítulo desalinhava tudo — cada título recebia o texto
    # de outro bloco, e o EPUB saía como recorte aleatório.
    for i, b in enumerate(blocks):
        b["_i"] = i

    if args.cap:
        # MESMO recorte do build_epub.py — ver extract.chapter_pages
        faixa = chapter_pages(blocks, args.cap)
        if faixa is None:
            print(f"capítulo {args.cap} não encontrado"); return 1
        lo, hi = faixa
        blocks = [b for b in blocks if lo <= b["page"] <= hi]
        print(f"piloto: capítulo {args.cap}, páginas {lo}-{hi}")

    todo = [{"i": b["_i"], "kind": b["kind"], "text": b["text"]}
            for b in blocks
            if b["kind"] in TRANSLATABLE and b["text"].strip()]

    # Exemplos vão por outro caminho: decisão em três vias, um a um (são
    # poucos e a decisão é individual, não cabe em lote).
    # A epígrafe entra na decisão em três vias junto com os exemplos: o
    # diálogo do ELIZA se traduz (o inglês ali é incidental), mas a frase de
    # abertura do cap.3 é a SAÍDA de um trigrama treinado em Jane Austen —
    # traduzir destrói o artefato que a epígrafe exibe. É a mesma escolha
    # caso a caso, não uma regra fixa.
    exemplos = [{"i": b["_i"], "kind": b["kind"], "text": b["text"]}
                for b in blocks
                if b["kind"] in ("example", "epigraph", "numex")
                and b["text"].strip()]

    outp = BUILD / args.out
    done: set[int] = set()
    if outp.exists():
        rows, keep = [], []
        for line in outp.read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(line))
            except Exception: pass
        if args.repair:
            # descarta os quebrados para que voltem à fila
            keep = [r for r in rows if r.get("ok")]
            outp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                    for r in keep), encoding="utf-8")
            print(f"reparo: {len(rows)-len(keep)} blocos voltaram à fila")
            rows = keep
        done = {r["i"] for r in rows}
        print(f"retomando: {len(done)} blocos já traduzidos")

    todo = [t for t in todo if t["i"] not in done]
    total_chars = sum(len(t["text"]) for t in todo)
    print(f"a traduzir: {len(todo)} blocos, {total_chars:,} caracteres")
    if not todo:
        return 0

    fh = outp.open("a", encoding="utf-8")
    t0, chars = time.time(), 0
    broken = 0

    # --- passe dos exemplos -------------------------------------------------
    pend_ex = [e for e in exemplos if e["i"] not in done]
    if pend_ex:
        print(f"exemplos a classificar: {len(pend_ex)}")
        contagem: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(handle_example, e["text"]): e for e in pend_ex}
            for fut in as_completed(futs):
                e = futs[fut]
                try:
                    dec, txt = fut.result()
                except Exception:
                    dec, txt = "MANTER", e["text"]
                contagem[dec] = contagem.get(dec, 0) + 1
                fh.write(json.dumps({"i": e["i"], "kind": "example",
                                     "src": e["text"], "pt": txt,
                                     "ok": True, "decisao": dec},
                                    ensure_ascii=False) + "\n")
        fh.flush()
        print(f"exemplos: {contagem}")

    def do_batch(batch: list[dict]) -> tuple[list[dict], list[str]]:
        src = pack(batch)
        out = call(src, max_tokens=batch_max_tokens(src))
        parts = unpack(out, len(batch))
        if parts is None:                      # numeração perdida: item a item
            parts = [call(b["text"], max_tokens=len(b["text"]) // 2 + 500)
                     for b in batch]
        return batch, parts

    # O servidor tem 4 slots; requisições concorrentes são agrupadas pelo
    # continuous batching do llama.cpp e elevam bastante a vazão agregada.
    # as_completed, não map: o map entrega na ordem de submissão, então um
    # lote longo segura a gravação de todos que terminaram depois dele. Num
    # run de 6h isso faz o progresso congelar por minutos e parecer travamento.
    all_batches = list(section_batches(todo)
                       if BACKEND in ("openrouter", "deepseek")
                       else batches(todo))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
      futs = [pool.submit(do_batch, b) for b in all_batches]
      for bi, fut in enumerate(as_completed(futs)):
        batch, parts = fut.result()
        for b, p in zip(batch, parts):
            ok, why = markup_ok(b["text"], p)
            if not ok:
                p2 = call(b["text"], max_tokens=len(b["text"]) // 2 + 500)
                ok2, _ = markup_ok(b["text"], p2)
                if ok2:
                    p, ok = p2, True
                else:
                    # Irrecuperável. O modo de falha comum é o modelo
                    # INVENTAR ênfase que não existia no original; manter
                    # isso produz itálico espúrio no EPUB. Preferimos perder
                    # a ênfase a inventá-la: remove todos os marcadores.
                    p = TAG.sub("", p2 if len(p2) > len(p) // 2 else p)
                    broken += 1
            fh.write(json.dumps({"i": b["i"], "kind": b["kind"],
                                 "src": b["text"], "pt": p, "ok": ok},
                                ensure_ascii=False) + "\n")
        fh.flush()

        chars += sum(len(b["text"]) for b in batch)
        el = time.time() - t0
        rate = chars / el if el else 0
        eta = (total_chars - chars) / rate / 3600 if rate else 0
        print(f"  lote {bi+1}: {chars:,}/{total_chars:,} car "
              f"({chars*100//max(total_chars,1)}%) | {rate:.0f} car/s | "
              f"ETA {eta:.1f}h | marcação quebrada: {broken}", flush=True)

    fh.close()
    print(f"\nconcluído. blocos com marcação irrecuperável: {broken}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
