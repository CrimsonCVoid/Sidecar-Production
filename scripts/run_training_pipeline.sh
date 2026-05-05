#!/usr/bin/env bash
#
# End-to-end training driver.
#
#   ./scripts/run_training_pipeline.sh [edge|msgp|all] [--smoke]
#
# Targets:
#   edge   — Phase 4 edge classifier (XGBoost). CPU-OK, ~30s on a small set.
#            Builds data/edge_training/edges.csv via build_edge_training_set.py
#            then trains roof_pipeline.edge_classifier.train.
#   msgp   — Phase 5 panel segmenter (PyTorch). GPU recommended; will run
#            on CPU but slowly. Builds data/msgp/all/ via msgp_prepare_data.py
#            then trains roof_pipeline.msgp.train.
#   all    — Both, in order.
#
# Flags:
#   --smoke — Tight limits (--limit 5 on data extract, --max-epochs 1 on
#             MSGP). Verifies the wiring without spending real compute.
#
# Required env (sourced from .env or shell):
#   SUPABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY
#
# Resume: data extractors are resumable (skip already-processed samples).
# Re-run after labeling more projects to grow the set incrementally.
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${1:-all}"
SMOKE=""
if [[ "${2:-}" == "--smoke" ]]; then
  SMOKE="--smoke"
fi

# Sanity check — refuse to run without Supabase creds. Both data
# extractors will fail anyway; failing here gives a clearer message.
if [[ -z "${SUPABASE_URL:-}" ]] || [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  if [[ -f ".env" ]]; then
    echo "[run_training] sourcing .env"
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
fi
if [[ -z "${SUPABASE_URL:-}" ]] || [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  echo "[run_training] FATAL: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY must be set" >&2
  exit 2
fi

PYTHON="${PYTHON:-python3}"
mkdir -p data/edge_training data/msgp/all

train_edge() {
  echo "[run_training] === Phase 4: edge classifier ==="
  local extra=()
  if [[ "$SMOKE" == "--smoke" ]]; then
    extra=(--limit 5)
  fi
  $PYTHON scripts/build_edge_training_set.py \
    --out data/edge_training/edges.csv \
    "${extra[@]}"

  if [[ ! -s data/edge_training/edges.csv ]]; then
    echo "[run_training] No edge rows produced — skipping train step." >&2
    return 0
  fi

  $PYTHON -m roof_pipeline.edge_classifier.train \
    --data data/edge_training/edges.csv \
    --out roof_pipeline/edge_classifier/artifacts \
    --folds 5
  echo "[run_training] Edge classifier artifact: roof_pipeline/edge_classifier/artifacts/model.json"
}

train_msgp() {
  echo "[run_training] === Phase 5: MSGP segmenter ==="
  local extra=()
  local epochs=50
  if [[ "$SMOKE" == "--smoke" ]]; then
    extra=(--limit 5)
    epochs=1
  fi
  $PYTHON scripts/msgp_prepare_data.py \
    --out data/msgp/all \
    "${extra[@]}"

  local pair_count
  pair_count=$(find data/msgp/all -name '*.input.npy' | wc -l)
  if [[ "$pair_count" -lt 2 ]]; then
    echo "[run_training] Only $pair_count input pair(s) — need at least 2 for train/val split. Skipping." >&2
    return 0
  fi

  mkdir -p data/msgp/checkpoints
  $PYTHON -m roof_pipeline.msgp.train \
    --data data/msgp/all \
    --out data/msgp/checkpoints \
    --max-epochs "$epochs"
  echo "[run_training] MSGP checkpoints: data/msgp/checkpoints/"
}

case "$TARGET" in
  edge) train_edge ;;
  msgp) train_msgp ;;
  all)  train_edge; train_msgp ;;
  *)
    echo "Usage: $0 [edge|msgp|all] [--smoke]" >&2
    exit 2
    ;;
esac

echo "[run_training] Done."
