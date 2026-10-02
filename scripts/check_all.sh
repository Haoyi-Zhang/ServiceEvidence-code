#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s "$ROOT/tests" -v
python "$ROOT/scripts/audit_public_inputs.py"
python "$ROOT/scripts/audit_bibliography.py"
python "$ROOT/experiments/archive_calibration.py"
python "$ROOT/experiments/public_target_benchmark.py"
if [[ ! -f "$ROOT/results/example_state.json" ]]; then
  python "$ROOT/experiments/run_all.py" --stage witnesses
fi
for kind in same different ambiguous; do
  python "$ROOT/checker/verify.py" \
    "$ROOT/results/example_state.json" \
    "$ROOT/results/example_${kind}_certificate.json"
  python -O "$ROOT/checker/verify.py" \
    "$ROOT/results/example_state.json" \
    "$ROOT/results/example_${kind}_certificate.json"
done
python "$ROOT/scripts/verify_results.py"
python "$ROOT/scripts/verify_equal_work.py"
python "$ROOT/scripts/verify_process_crash.py"
python "$ROOT/scripts/verify_environment_inventory.py"

python "$ROOT/scripts/verify_tpds.py"
