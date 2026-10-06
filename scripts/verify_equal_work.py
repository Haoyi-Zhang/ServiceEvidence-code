#!/usr/bin/env python3
"""Verify paired central/quorum/peer result surfaces and certificates."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
spec = importlib.util.spec_from_file_location("equal_work_checker", ROOT / "checker" / "verify.py")
checker = importlib.util.module_from_spec(spec)
if spec.loader is None:
    raise RuntimeError("could not load checker")
spec.loader.exec_module(checker)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def number(row: dict[str, str], field: str) -> float:
    return float(row[field])


def integer(row: dict[str, str], field: str) -> int:
    return int(row[field])


def independently_aggregate(rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    numeric_fields = (
        "wire_bytes",
        "persistence_bytes_written",
        "final_durable_bytes",
        "elapsed_seconds",
        "rpc_p95_ms",
        "certificate_verification_ms",
    )
    for architecture in sorted({row["architecture"] for row in rows}):
        selected = [row for row in rows if row["architecture"] == architecture]
        item: dict[str, object] = {
            "cases": len(selected),
            "partition_write_availability_mean": statistics.mean(
                number(row, "partition_write_availability") for row in selected
            ),
            "partition_query_availability_mean": statistics.mean(
                number(row, "partition_query_availability") for row in selected
            ),
            "partition_availability_by_layout": {
                layout: statistics.mean(
                    number(row, "partition_query_availability")
                    for row in selected
                    if row["layout"] == layout
                )
                for layout in sorted({row["layout"] for row in selected})
            },
            "partition_ambiguous_total": sum(
                integer(row, "partition_ambiguous") for row in selected
            ),
            "partition_same_total": sum(
                integer(row, "partition_same") for row in selected
            ),
            "all_final_same": all(row["final_kind"] == "same" for row in selected),
            "all_zero_false_merge": all(
                integer(row, "final_false_merge_pairs") == 0 for row in selected
            ),
            "all_zero_false_split": all(
                integer(row, "final_false_split_pairs") == 0 for row in selected
            ),
            "all_restart_recovered": all(
                integer(row, "restart_recovered") == 1 for row in selected
            ),
        }
        for field in numeric_fields:
            values = [number(row, field) for row in selected]
            item[field + "_median"] = statistics.median(values)
            item[field + "_range"] = {
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
        result[architecture] = item
    return result


def same_number(left: object, right: object) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def compare_aggregate(expected: object, observed: object, path: str = "summary") -> None:
    if isinstance(expected, dict):
        require(isinstance(observed, dict), f"{path} type changed")
        require(set(expected) == set(observed), f"{path} fields changed")
        for key in expected:
            compare_aggregate(expected[key], observed[key], f"{path}.{key}")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        require(same_number(expected, observed), f"{path} numeric value differs")
    else:
        require(expected == observed, f"{path} value differs")


def verify_summary(rows: list[dict[str, str]], summary: dict) -> None:
    """Reaggregate current records without fixing environment-sensitive times."""
    require(summary["cases"] == 30, "summary case count changed")
    independent = independently_aggregate(rows)
    compare_aggregate(independent, summary["architectures"], "equal_work_summary.architectures")
    for architecture, availability in {
        "peer-evidence": 1.0,
        "central-recompute": 0.5,
        "coordinated-quorum": 0.6,
    }.items():
        item = summary["architectures"][architecture]
        require(item["cases"] == 10, "summary architecture count changed")
        require(item["partition_write_availability_mean"] == availability, "summary write availability changed")
        require(item["partition_query_availability_mean"] == availability, "summary query availability changed")
        require(item["partition_same_total"] == 0, "summary records a partial SAME answer")
        require(item["all_final_same"] is True, "summary final decision predicate failed")
        require(item["all_zero_false_merge"] is True and item["all_zero_false_split"] is True, "summary correctness predicate failed")
        require(item["all_restart_recovered"] is True, "summary restart predicate failed")


def main() -> int:
    with (RESULTS / "equal_work.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 30, "equal-work comparison must contain 30 paired rows")
    architectures = {"peer-evidence", "central-recompute", "coordinated-quorum"}
    layouts = {"authority-minority", "authority-majority"}
    require({row["architecture"] for row in rows} == architectures, "architecture set changed")
    require({row["layout"] for row in rows} == layouts, "partition layout set changed")
    require({int(row["seed"]) for row in rows} == set(range(1, 6)), "seed set changed")
    require(
        len({(row["architecture"], row["layout"], row["seed"]) for row in rows}) == 30,
        "paired comparison contains a duplicate or missing tuple",
    )

    expected_case_availability = {
        ("peer-evidence", "authority-minority"): 1.0,
        ("peer-evidence", "authority-majority"): 1.0,
        ("central-recompute", "authority-minority"): 0.4,
        ("central-recompute", "authority-majority"): 0.6,
        ("coordinated-quorum", "authority-minority"): 0.6,
        ("coordinated-quorum", "authority-majority"): 0.6,
    }
    verified = 0
    for row in rows:
        architecture = row["architecture"]
        expected_case = expected_case_availability[(architecture, row["layout"])]
        require(float(row["partition_write_availability"]) == expected_case, "write availability changed")
        require(float(row["partition_query_availability"]) == expected_case, "query availability changed")
        require(int(row["partition_same"]) == 0, "partial closure authorized SAME")
        require(int(row["partition_different"]) == 0, "partial closure authorized DIFFERENT")
        require(row["final_kind"] == "same", "final query did not become SAME")
        require(int(row["final_false_merge_pairs"]) == 0, "final comparison has a false merge")
        require(int(row["final_false_split_pairs"]) == 0, "final comparison has a false split")
        require(int(row["restart_recovered"]) == 1, "restart did not recover")
        require(int(row["input_cells"]) == 2_200 and int(row["services"]) == 100, "frozen workload dimensions changed")
        require(int(row["requests"]) <= 5_000, "request cap exceeded")
        require(int(row["wire_bytes"]) <= 100 * 1024**2, "wire cap exceeded")
        require(float(row["elapsed_seconds"]) < 120.0, "case timeout exceeded")
        require(int(row["persistence_fsyncs"]) > 0, "persistence work was not counted")
        require(int(row["persistence_bytes_written"]) > 0, "persistence bytes were not counted")

        detail_path = (
            RESULTS
            / "equal_work"
            / f"{row['layout']}-seed-{row['seed']}"
            / f"{architecture}.json"
        )
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        final_answer = detail["detail"]["final_answer"]
        checker.verify(final_answer["state"], final_answer["certificate"])
        require(final_answer["certificate"]["kind"] == "same", "detail final certificate changed")
        verified += 1
        available = 0
        for answer in detail["detail"]["partition_answers"]:
            if answer is None:
                continue
            checker.verify(answer["state"], answer["certificate"])
            require(answer["certificate"]["kind"] == "ambiguous", "partial answer was not ambiguous")
            available += 1
            verified += 1
        require(available == int(row["partition_query_acks"]), "detail availability count changed")

    summary = json.loads((RESULTS / "equal_work_summary.json").read_text(encoding="utf-8"))
    verify_summary(rows, summary)
    measured_medians = "/".join(
        f"{summary['architectures'][architecture]['elapsed_seconds_median']:.9g}"
        for architecture in ("central-recompute", "coordinated-quorum", "peer-evidence")
    )

    print(
        "PASS: 30 equal-work rows independently aggregated; "
        f"{verified} state-coupled certificates; current-record medians "
        f"{measured_medians} s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
