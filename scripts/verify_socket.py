#!/usr/bin/env python3
"""Verify all recorded socket-query certificates and fixed campaign predicates."""
import importlib.util
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checker", ROOT / "checker/verify.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    count = 0
    for name in ["pilot", "public"] + [f"generated-{seed}" for seed in range(1,6)]:
        directory = ROOT / "results/socket" / name
        row = json.loads((directory / "result.json").read_text())
        answers = json.loads((directory / "query_answers.json").read_text())
        state = json.loads((directory / "final_state.json").read_text())
        events = json.loads((directory / "events.json").read_text())
        checker.validate_state(state)
        require(row["endpoints"] == 5 and row["fault_rounds"] == 3 and 1 <= row["fair_rounds"] <= 8, "campaign dimensions")
        require(row["requests"] <= 5000 and row["wire_bytes"] <= 100*1024**2 and row["elapsed_seconds"] < 120, "campaign cap")
        require(row["wire_bytes"] == row["request_bytes"] + row["response_bytes"], "wire byte accounting")
        require(row["omitted_pulls"] == sum(e["action"] == "omit" for e in events), "omission count")
        require(row["duplicate_pulls"] == sum(e["action"] == "duplicate" for e in events), "duplicate count")
        require(len(state["cells"]) == row["cells_after_compaction"], "retained count")
        for key in ("converged", "matches_oracle", "repair_disabled_not_converged", "missing_ack_rejected",
                    "restart_preserves_floor", "stale_state_not_resurrected", "malformed_batch_atomic"):
            require(row[key] is True, f"failed predicate {key}")
        for phase in ("partition", "healed"):
            require(len(answers[phase]) == 5, "query endpoint count")
            for answer in answers[phase]:
                checker.verify(answer["state"], answer["certificate"])
                expected = "same" if phase == "healed" and name != "public" else "ambiguous"
                require(answer["certificate"]["kind"] == expected, "query phase result")
                count += 1
    print(f"PASS: 7 socket cases; {count} state-coupled query certificates; event counts and caps")

if __name__ == "__main__":
    main()
