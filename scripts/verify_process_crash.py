#!/usr/bin/env python3
"""Verify the independent-process crash/restart result surface."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
spec = importlib.util.spec_from_file_location("process_crash_checker", ROOT / "checker" / "verify.py")
checker = importlib.util.module_from_spec(spec)
if spec.loader is None:
    raise RuntimeError("could not load checker")
spec.loader.exec_module(checker)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    with (RESULTS / "process_crash.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 3, "process campaign must retain three cases")
    require({int(row["seed"]) for row in rows} == {1, 2, 3}, "process seed set changed")
    verified = 0
    for row in rows:
        require(int(row["services"]) == 100 and int(row["input_cells"]) == 2_200, "process workload dimensions changed")
        require(int(row["processes"]) == 4 and int(row["sources"]) == 5, "process/source count changed")
        require(int(row["partition_ambiguous"]) == 4, "partition returned a non-ambiguous answer")
        require(int(row["abrupt_crashes"]) == 2 and int(row["successful_restarts"]) == 2, "crash recovery count changed")
        require(int(row["final_states_equal"]) == 1 and int(row["expected_state_equal"]) == 1, "final state predicate failed")
        require(row["final_kind"] == "same", "recovered final decision changed")
        require(int(row["certificates_verified"]) == 10, "certificate count changed")
        require(int(row["orchestrator_requests"]) <= 100, "orchestrator request cap exceeded")
        require(float(row["elapsed_seconds"]) < 120.0, "process case timeout exceeded")
        detail = json.loads((RESULTS / "process_crash" / f"seed-{row['seed']}.json").read_text(encoding="utf-8"))
        require(detail["partition_kinds"] == ["ambiguous"] * 4, "detail partition decisions changed")
        require(detail["recovered_partition_kind"] == "ambiguous", "partition restart changed decision")
        for key in ("final_answer", "postheal_recovered_answer"):
            answer = detail[key]
            checker.verify(answer["state"], answer["certificate"])
            require(answer["certificate"]["kind"] == "same", "detail final certificate changed")
            verified += 1
    summary = json.loads((RESULTS / "process_crash_summary.json").read_text(encoding="utf-8"))
    require(summary["cases"] == 3 and summary["abrupt_crashes"] == 6, "process summary dimensions changed")
    require(summary["successful_restarts"] == 6, "process summary restart count changed")
    require(summary["all_partition_answers_ambiguous"] is True, "process summary partition predicate failed")
    require(summary["all_final_states_equal"] is True and summary["all_expected_states_equal"] is True, "process summary state predicate failed")
    require(summary["all_final_same"] is True, "process summary final predicate failed")
    require(summary["certificates_verified"] == 30, "process summary certificate count changed")
    require(summary["crash_boundary"] == "SIGKILL after acknowledged commits; no mid-write or power-loss injection", "process crash boundary changed")
    print(f"PASS: 3 independent-process cases; 6 abrupt restarts; {verified} retained state-coupled certificates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
