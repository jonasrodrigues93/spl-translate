#!/usr/bin/env bash
# Traduz cada capítulo em um processo separado e monta um EPUB único.
# Uso: BACKEND=deepseek ./rodar-paralelo.sh
set -uo pipefail
cd "$(dirname "$0")"

PY=./venv/bin/python
BACKEND=${BACKEND:-deepseek}
PREFIX=${PREFIX:-deepseek-full}
WORKERS=${WORKERS:-4}
EPUB=${EPUB:-${PREFIX}.epub}
OEBPS=${OEBPS:-${PREFIX}-OEBPS}

[ -x "$PY" ] || { echo "venv não preparado"; exit 1; }
[ -f build/blocks.json ] || { echo "extração ausente: rode extract.py antes"; exit 1; }

mapfile -t CAPS < <("$PY" -W ignore -c '
import json
from extract import chapter_pages
b = json.load(open("build/blocks.json", encoding="utf-8"))
for n in range(1, 100):
    if chapter_pages(b, n):
        print(n)
' 2>/dev/null | rg '^[0-9]+$')
[ "${#CAPS[@]}" -gt 0 ] || { echo "nenhum capítulo encontrado"; exit 1; }

mkdir -p build/parallel-logs
declare -A PIDS
for cap in "${CAPS[@]}"; do
  jsonl="${PREFIX}-cap${cap}.jsonl"
  log="build/parallel-logs/${PREFIX}-cap${cap}.log"
  echo "iniciando capítulo ${cap} -> build/${jsonl}"
  BACKEND="$BACKEND" "$PY" -u translate.py --cap "$cap" \
    --out "$jsonl" --backend "$BACKEND" --workers "$WORKERS" \
    >"$log" 2>&1 &
  PIDS["$cap"]=$!
done

status=0
for cap in "${CAPS[@]}"; do
  if ! wait "${PIDS[$cap]}"; then
    echo "falhou o capítulo ${cap}; ver build/parallel-logs/${PREFIX}-cap${cap}.log"
    status=1
  fi
done
[ "$status" -eq 0 ] || exit "$status"

MERGED="${PREFIX}.jsonl"
"$PY" - "$MERGED" "${CAPS[@]}" <<'PY'
import json
import sys
from pathlib import Path

out = Path("build") / sys.argv[1]
caps = sys.argv[2:]
rows = {}
for cap in caps:
    path = Path("build") / f"{out.stem}-cap{cap}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            old = rows.get(row["i"])
            if old is None or (not old.get("ok") and row.get("ok")):
                rows[row["i"]] = row
        except (ValueError, KeyError):
            pass
out.write_text("".join(json.dumps(rows[i], ensure_ascii=False) + "\n"
                           for i in sorted(rows)), encoding="utf-8")
print(f"consolidadas: {len(rows)} linhas -> {out}")
PY

"$PY" build_epub.py --jsonl "$MERGED" --out "$EPUB" --oebps "$OEBPS"
