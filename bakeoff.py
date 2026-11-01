#!/usr/bin/env python3
"""
Bancada de comparação de modelos para EN->pt-BR neste livro.

Não mede fluência genérica: mede o que quebra uma tradução técnica —
terminologia consagrada de PLN e preservação da marcação inline «i»/«b»/«code».

Sobe um llama-server por modelo, roda os mesmos trechos, derruba, mede.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

BIN = Path("/mnt/data/ai/bin/llama-server")
GGUF = Path("/mnt/data/ai/models/gguf")
PORT = 8099
HERE = Path(__file__).resolve().parent

# ncmoe conservador: errar para baixo trava a GPU e mata o compositor.
# Ver gotchas/radeon-780m-vulkan-moe-expert-vram-deadlock.
MODELS = [
    ("gemma-4-26b-a4b", "gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf", 8),
    ("qwen3-30b-a3b",   "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf", 14),
    ("tower-plus-9b",   "Tower-Plus-9B.i1-Q5_K_M.gguf",            0),
]

SYSTEM = """Você é tradutor técnico especializado em Processamento de Linguagem Natural.
Traduza do inglês para o português do Brasil.

REGRAS OBRIGATÓRIAS:
1. Preserve EXATAMENTE os marcadores «i»...«/i», «b»...«/b», «code»...«/code».
   Não os traduza, não os remova, não invente novos.
2. NÃO traduza exemplos linguísticos em inglês nem trechos entre «code».
3. Terminologia consagrada em português:
   token->token | embedding->embedding | attention->atenção
   language model->modelo de linguagem | fine-tuning->ajuste fino
   perplexity->perplexidade | word type->tipo de palavra
   word instance->instância de palavra | tokenization->tokenização
   corpus->corpus | corpora->corpora | greedy->guloso
4. Responda APENAS com a tradução. Sem preâmbulo, sem comentário, sem aspas."""

# Trechos reais do livro, escolhidos por serem representativos do que é difícil.
CASES = [
    ("terminologia",
     'How many words are in a corpus? To answer this question we need to '
     'distinguish two ways of talking about words. «i»Word instances«/i» are the '
     'individual instances that occur in a text; if we ignore punctuation, the '
     'sentence has 9 word instances. «i»Word types«/i» are the number of distinct '
     'words in a corpus.'),
    ("marcacao_inline",
     'the «b»disjunction«/b» operator, also called the pipe symbol «code»|«/code». '
     'The pattern «code»r"cat|dog"«/code» matches either the string «code»cat«/code» '
     'or the string «code»dog«/code».'),
    ("legenda",
     '«b»Figure 2.2 «/b»The thick blue line shows Vocabulary size |«i»V«/i»| as a '
     'function of corpus size, illustrating Heaps\' Law.'),
]


def wait_ready(timeout=600) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(3)
    return False


def translate(text: str) -> tuple[str, float]:
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": text}],
        "temperature": 0.2, "max_tokens": 900, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    dt = time.time() - t0
    out = d["choices"][0]["message"]["content"].strip()
    n = d.get("usage", {}).get("completion_tokens", 0)
    return out, (n / dt if dt else 0)


TAG = re.compile(r"«/?(?:i|b|code)»")


INNER = re.compile(r"«(i|b|code)»(.*?)«/\1»", re.S)


def markup_ok(src: str, out: str) -> tuple[bool, str]:
    """Compara a sequência de tags E o conteúdo dentro delas.

    Só comparar a sequência dá falso OK: o EuroLLM emitiu «b»...«/b»
    literalmente, descartando a palavra, e a sequência bateu.
    """
    if TAG.findall(src) != TAG.findall(out):
        return False, "sequência de tags diferente"
    si, oi = INNER.findall(src), INNER.findall(out)
    if len(si) != len(oi):
        return False, "número de pares diferente"
    for (_, a), (_, b) in zip(si, oi):
        a, b = a.strip(), b.strip()
        # inalterado é sempre válido: símbolos e variáveis ("|", "V") não
        # se traduzem. Sem esta guarda a heurística abaixo os reprova.
        if a == b:
            continue
        if not b or set(b) <= set(". "):
            return False, "conteúdo descartado dentro da tag"
        # conteúdo some se encolher demais (heurística de perda)
        if len(b) < max(2, len(a) * 0.3):
            return False, f"conteúdo encolheu: {a!r} -> {b!r}"
    # trechos «code» não podem ser traduzidos
    for (t, a), (_, b) in zip(si, oi):
        if t == "code" and a.strip() != b.strip():
            return False, f"código alterado: {a.strip()!r} -> {b.strip()!r}"
    return True, ""


def main() -> int:
    results = {}
    for name, fname, ncmoe in MODELS:
        path = GGUF / fname
        if not path.exists():
            print(f"[pular] {name}: {fname} ausente")
            continue
        print(f"\n=== {name} (ncmoe={ncmoe}) ===", flush=True)
        cmd = [str(BIN), "-m", str(path), "--port", str(PORT), "-ngl", "99",
               "--ctx-size", "8192", "--threads", "8", "--flash-attn", "on",
               "--cache-type-k", "q8_0", "--cache-type-v", "q8_0", "--jinja",
               "--reasoning-budget", "0", "--no-warmup"]
        if ncmoe:
            cmd += ["--n-cpu-moe", str(ncmoe)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            if not wait_ready():
                print("  FALHOU ao subir"); proc.terminate(); continue
            res = []
            for label, src in CASES:
                try:
                    out, tps = translate(src)
                except Exception as e:
                    out, tps = f"<erro: {e}>", 0.0
                ok, why = markup_ok(src, out)
                res.append({"caso": label, "saida": out, "tps": round(tps, 1),
                            "marcacao_ok": ok, "motivo": why})
                print(f"  [{label}] {tps:5.1f} t/s  marcação={'OK' if ok else 'QUEBROU: '+why}")
                print(f"    {out[:180]}")
            results[name] = res
        finally:
            proc.terminate()
            try: proc.wait(timeout=60)
            except subprocess.TimeoutExpired: proc.kill()
            time.sleep(5)

    (HERE / "build" / "bakeoff.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== resumo ===")
    for n, r in results.items():
        tps = sum(x["tps"] for x in r) / len(r)
        ok = sum(x["marcacao_ok"] for x in r)
        print(f"  {n:18s} {tps:5.1f} t/s   marcação {ok}/{len(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
