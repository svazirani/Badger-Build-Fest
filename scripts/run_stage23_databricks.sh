#!/usr/bin/env bash
# Stage 2/3 runs on Databricks Foundation Model APIs (Free Edition: no per-call charge).
# Same frozen plans and runner as Run-Stage23.ps1; only the backend/model differ. Resumable: re-run to finish failures.
#   bash scripts/run_stage23_databricks.sh [main-model] [cheap-model]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
MAIN=${1:-databricks-meta-llama-3-3-70b-instruct}
CHEAP=${2:-databricks-meta-llama-3-1-8b-instruct}
set -a; . ./.env; set +a
export ASSAY_ALLOW_MODEL_CALLS=1
OUT=results/stage-2-3-runs; P=results/stage-2-3-plans
mkdir -p "$OUT"
run() { $PY scripts/run_frozen_eval.py --plan "$P/$1.json" --out "$OUT/$2.jsonl" --model "$3" --backend databricks \
          --prompt "$4" --execute --i-accept-usage > "$OUT/$2.log" 2>&1 && echo "done $2" || echo "FAILED $2 (see $OUT/$2.log)"; }
run permission permission-v2 "$MAIN" v2 &
run gate gate-v1 "$MAIN" v1 &
run gate gate-v2 "$MAIN" v2 &
run stress stress-v1 "$MAIN" v1 &
run stress stress-bad "$MAIN" bad &
run permission permission-v2-cheap "$CHEAP" v2 &
wait
for f in "$OUT"/*.failures.jsonl; do [ -f "$f" ] && echo "failures: $f $(wc -l < "$f")"; done
echo "all runs finished"
