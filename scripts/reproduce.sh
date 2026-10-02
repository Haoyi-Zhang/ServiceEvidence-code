#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
python "$ROOT/scripts/capture_environment.py" --output "$ROOT/results/runtime_environment/core-reproduction.json" --context core-reproduction --storage-path "$ROOT/results"
python "$ROOT/scripts/audit_public_inputs.py"
python "$ROOT/scripts/audit_bibliography.py"
echo "[reproduce] archived-input calibration" >&2
python "$ROOT/experiments/archive_calibration.py"
python "$ROOT/experiments/public_target_benchmark.py"
for stage in correctness faults unsealed witnesses compaction scale; do
  echo "[reproduce] $stage" >&2
  python "$ROOT/experiments/run_all.py" --stage "$stage"
done
python "$ROOT/experiments/run_all.py" --stage aggregate
python "$ROOT/scripts/verify_results.py" --core-only
