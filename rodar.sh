#!/usr/bin/env bash
# Tradução do livro inteiro, de ponta a ponta.
#
#   ./rodar.sh              # livro todo (~1,7 M caracteres, ~5-6 h)
#   ./rodar.sh 5            # só o capítulo 5
#   SO_MONTAR=1 ./rodar.sh  # não traduz: só remonta o EPUB do que já existe
#
# É RETOMÁVEL. O translate.py grava em JSONL append-only e relê o que já
# traduziu, então reexecutar depois de uma queda continua de onde parou. Se o
# servidor cair no meio, basta rodar de novo.
set -uo pipefail
cd "$(dirname "$0")"

BIN=${LLAMA_SERVER_BIN:-/mnt/data/ai/bin/llama-server}
MODELO=${LLAMA_MODEL:-/mnt/data/ai/models/gguf/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf}
NCMOE=8            # ver "por que --n-cpu-moe" abaixo
PORTA=8099
SLOTS=4
BACKEND=${BACKEND:-local}
CAP="${1:-}"
if [ -n "$CAP" ]; then
  ESCOPO="capítulo $CAP"
else
  ESCOPO="o livro inteiro"
fi
JSONL="${JSONL:-livro.jsonl}"
EPUB="${EPUB:-ed3book-ptBR.epub}"
LOG=/tmp/ed3book-llama.log
PY=./venv/bin/python

[ -x "$PY" ] || {
  echo "venv não preparado: rode python3 -m venv venv e instale requirements.txt"
  exit 1
}
[ -f build/blocks.json ] || {
  echo "extração ausente: rode $PY extract.py antes de rodar.sh"
  exit 1
}

# --n-cpu-moe NÃO É AJUSTE DE DESEMPENHO, É O QUE IMPEDE A MÁQUINA DE TRAVAR.
# A Radeon 780M também desenha a tela; com o modelo inteiro na iGPU o
# compositor não pega slot e o desktop congela — o kernel segue vivo, mas só
# resta o botão. Foi o que causou o desligamento forçado de 27/07.
[ -z "${NCMOE}" ] && { echo "recusando: NCMOE vazio travaria a máquina"; exit 1; }

subir() {
  [ -x "$BIN" ] || { echo "llama-server ausente ou sem permissão: $BIN"; exit 1; }
  [ -f "$MODELO" ] || { echo "modelo ausente: $MODELO"; exit 1; }
  if curl -sf "http://127.0.0.1:${PORTA}/health" >/dev/null 2>&1; then
    echo "[$(date +%H:%M)] servidor já responde na ${PORTA}, reaproveitando"
    return 0
  fi
  # Um servidor de OUTRO modelo pode estar no ar e ocupar a memória: 23 GB no
  # total não comportam dois modelos destes. Avisa em vez de subir por cima.
  if pgrep -f "^${BIN}" >/dev/null; then
    echo "AVISO: há um llama-server de outro modelo/porta no ar."
    pgrep -af "^${BIN}" | sed 's/^/  /'
    echo "Encerre-o antes (não cabem dois na memória) ou aponte --porta para ele."
    exit 1
  fi
  echo "[$(date +%H:%M)] subindo Gemma 4 (--n-cpu-moe ${NCMOE})..."
  "$BIN" -m "$MODELO" --port "$PORTA" -ngl 99 --n-cpu-moe "$NCMOE" \
    --ctx-size 16384 --parallel "$SLOTS" --threads 8 --flash-attn on \
    --cache-type-k q8_0 --cache-type-v q8_0 --jinja --reasoning-budget 0 \
    > "$LOG" 2>&1 &
  SRV=$!
  for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:${PORTA}/health" >/dev/null 2>&1 && {
      echo "[$(date +%H:%M)] servidor pronto"; return 0; }
    kill -0 "$SRV" 2>/dev/null || { echo "servidor morreu; ver $LOG"; exit 1; }
    sleep 5
  done
  echo "servidor não subiu em 10 min; ver $LOG"; exit 1
}

derrubar() {
  [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null && echo "[$(date +%H:%M)] servidor encerrado"
}
trap derrubar EXIT

if [ -z "${SO_MONTAR:-}" ]; then
  if [ "$BACKEND" = local ]; then
    subir
  elif [ "$BACKEND" != openrouter ] && [ "$BACKEND" != deepseek ]; then
    echo "backend inválido: $BACKEND (use local, openrouter ou deepseek)"; exit 1
  fi
  echo "[$(date +%H:%M)] traduzindo ${ESCOPO} -> build/${JSONL}"
  "$PY" -u translate.py ${CAP:+--cap "$CAP"} \
    --out "$JSONL" --backend "$BACKEND" --porta "$PORTA" \
    --workers "$SLOTS" || {
      echo "tradução interrompida — reexecute para retomar de onde parou"; exit 1; }
  if [ "$BACKEND" = local ]; then
    derrubar; SRV=""      # libera a memória antes de montar
  fi
fi

echo "[$(date +%H:%M)] montando o EPUB..."
"$PY" build_epub.py ${CAP:+--cap "$CAP"} --jsonl "$JSONL" --out "$EPUB" || exit 1

echo "[$(date +%H:%M)] conferindo..."
# A conferência segue o ESCOPO do que foi montado. Auditar um EPUB de dois
# capítulos contra o livro inteiro devolve "7,7% de cobertura" — número que
# não quer dizer nada e assusta à toa.
if [ -n "$CAP" ]; then
  "$PY" audit.py --cap "$CAP" --epub "$EPUB" 2>&1 | grep -E "COBERTURA|continuidade"
else
  "$PY" audit.py --livro --epub "$EPUB" 2>&1 | grep -E "COBERTURA|continuidade"
  "$PY" inventory.py --perdas 2>&1 | head -2
fi
"$PY" - "$EPUB" <<'PY'
import sys, zipfile, re, xml.dom.minidom as M
z = zipfile.ZipFile(f"build/{sys.argv[1]}")
ruins = []
for n in z.namelist():
    if n.endswith((".xhtml", ".opf", ".xml")):
        try:
            M.parseString(z.read(n))
        except Exception:
            ruins.append(n)
alvos = set()
for n in z.namelist():
    if n.endswith(".xhtml"):
        alvos |= set(re.findall(r'href="bibliografia\.xhtml#c-([^"]+)"',
                                z.read(n).decode("utf-8")))
if "OEBPS/bibliografia.xhtml" in z.namelist():
    bib = z.read("OEBPS/bibliografia.xhtml").decode("utf-8")
    anc = set(re.findall(r'id="c-([^"]+)"', bib))
    mortos = len(alvos - anc)
else:
    mortos = 0
print(f"XHTML mal formado: {len(ruins)}   links de citação mortos: {mortos}")
PY
echo "[$(date +%H:%M)] pronto: build/${EPUB}"
