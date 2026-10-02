#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
python "$ROOT/scripts/capture_environment.py" --output "$ROOT/results/runtime_environment/extended-reproduction.json" --context extended-reproduction --storage-path "$ROOT/results"
python "$ROOT/scripts/audit_public_inputs.py"
python "$ROOT/scripts/audit_bibliography.py"
python "$ROOT/experiments/exact_oracles.py"
python "$ROOT/experiments/public_target_benchmark.py"
python "$ROOT/experiments/equal_work_campaign.py" --services 100 --seeds 1,2,3,4,5
python "$ROOT/experiments/process_crash_campaign.py" --services 100 --seeds 1,2,3
python "$ROOT/experiments/socket_campaign.py" --services 20 --seed 1
for seed in 1 2 3 4 5; do
  python "$ROOT/experiments/socket_campaign.py" --services 100 --seed "$seed"
done
python "$ROOT/experiments/socket_campaign.py" --public
python "$ROOT/scripts/verify_socket.py"
python "$ROOT/scripts/verify_equal_work.py"
python "$ROOT/scripts/verify_process_crash.py"
python "$ROOT/scripts/verify_results.py"

python "$ROOT/experiments/materializer_campaign.py"
python "$ROOT/experiments/topology_campaign.py"
python "$ROOT/scripts/summarize_tpds_replications.py"
python "$ROOT/scripts/verify_tpds.py"
