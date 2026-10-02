#!/usr/bin/env python3
"""Check every stable result surface used by the paper."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


class ResultError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ResultError(message)


def rows(name: str) -> List[Mapping[str, str]]:
    path = RESULTS / name
    require(path.is_file(), f"missing result file: {name}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_int(row: Mapping[str, str], field: str) -> int:
    return int(float(row[field]))


def as_float(row: Mapping[str, str], field: str) -> float:
    return float(row[field])


def close(actual: float, expected: float, tolerance: float = 1e-12) -> bool:
    return abs(actual - expected) <= tolerance


def main(include_extended: bool = True) -> int:
    archived = rows("archive_calibration.csv")
    require(len(archived) == 3, "archive calibration must contain three navigations")
    require(sum(as_int(row, "navigation_entries") for row in archived) == 6, "archive calibration must summarize six observations")
    require(sum(as_int(row, "redirect_edges") for row in archived) == 3, "archive calibration redirect count changed")
    require(any(as_int(row, "endpoint_changes") > 0 for row in archived), "archive calibration lost the endpoint-change example")

    correctness = rows("correctness.csv")
    methods = {
        "sealed-evidence q=2",
        "sealed-evidence q=1",
        "no negative veto",
        "merge-forever union-find",
        "single-vantage local",
        "name-only",
        "last-arrival",
    }
    require(len(correctness) == 105, "correctness matrix must contain 105 rows")
    require(set(row["method"] for row in correctness) == methods, "correctness method set changed")
    for method in methods:
        require(sum(row["method"] == method for row in correctness) == 15, f"method {method!r} must have 15 trials")
    proposed = [row for row in correctness if row["method"] == "sealed-evidence q=2"]
    require(all(as_float(row, "false_merge_pairs") == 0 for row in proposed), "selected method has a generated false merge")
    expected_splits = {"0.00": 0.0, "0.08": 0.10455555555555555, "0.20": 0.2542222222222222}
    for sparse, expected in expected_splits.items():
        selected = [row for row in proposed if f"sparse={sparse}" in row["trial"]]
        require(len(selected) == 5, f"sparse={sparse} must have five selected-method trials")
        mean = statistics.mean(as_float(row, "false_split_rate") for row in selected)
        require(close(mean, expected), f"sparse={sparse} false-split result changed: {mean}")

    faults = rows("faults.csv")
    require(len(faults) == 25, "fault matrix must contain 25 rows")
    require(set(row["configuration"] for row in faults) == {"reorder-only", "loss", "duplication", "partition", "combined"}, "fault configuration set changed")
    require(all(as_int(row, "post_repair_converged") == 1 for row in faults), "a fault trial failed to converge after repair")
    require(all(as_float(row, "false_merge_pairs") == 0 for row in faults), "a fault trial has a final false merge")
    require(all(as_float(row, "false_split_pairs") == 0 for row in faults), "a fully supported fault trial has a final false split")

    sealing = rows("unsealed_safety.csv")
    require(len(sealing) == 2, "sealing surface must contain two schedules")
    by_schedule: Dict[str, Mapping[str, str]] = {row["schedule"]: row for row in sealing}
    random_row = by_schedule["uniform random delivery order"]
    adversarial_row = by_schedule["adversarial same-votes first"]
    require(as_int(random_row, "trials") == 20_000 and as_int(adversarial_row, "trials") == 20_000, "sealing trial count changed")
    require(as_int(random_row, "unsealed_transient_false_merges") == 6_798, "random unsealed counterexample count changed")
    require(as_int(adversarial_row, "unsealed_transient_false_merges") == 20_000, "adversarial unsealed counterexample count changed")
    require(all(as_int(row, "sealed_transient_false_merges") == 0 for row in sealing), "sealed rule authorized a transient merge")

    witnesses = rows("witnesses.csv")
    require(len(witnesses) == 207, "certificate surface must contain 207 rows")
    witness_counts = {
        kind: sum(row["kind"] == kind for row in witnesses)
        for kind in ("same", "different", "ambiguous")
    }
    require(witness_counts == {"same": 15, "different": 44, "ambiguous": 148}, f"certificate-kind counts changed: {witness_counts}")
    require(all(as_float(row, "authorization_gap") >= 0 for row in witnesses), "a certificate has a negative authorization gap")

    compaction = rows("compaction.csv")
    require(len(compaction) == 3, "compaction surface must contain three epoch depths")
    expected_compaction = {
        2: (15_400, 7_700, 0.5, 1_867_624, 1_021_113),
        4: (30_800, 7_700, 0.75, 3_711_844, 1_021_113),
        6: (46_200, 7_700, 5.0 / 6.0, 5_556_064, 1_021_113),
    }
    for row in compaction:
        epoch = as_int(row, "epochs")
        require(epoch in expected_compaction, f"unexpected compaction depth: {epoch}")
        before, after, reduction, bytes_before, bytes_after = expected_compaction[epoch]
        require(as_int(row, "relations") == 1_540, "compaction relation count changed")
        require(as_int(row, "cells_before") == before and as_int(row, "cells_after") == after, f"compaction cell counts changed at {epoch} epochs")
        require(close(as_float(row, "cell_reduction"), reduction), f"compaction reduction changed at {epoch} epochs")
        require(as_int(row, "bytes_before") == bytes_before and as_int(row, "bytes_after") == bytes_after, f"compaction byte counts changed at {epoch} epochs")
        require(as_int(row, "partition_preserved") == 1, f"compaction changed the partition at {epoch} epochs")

    scale = rows("scale.csv")
    require(len(scale) == 5, "scale surface must contain five cases")
    labels = [row["label"] for row in scale]
    require(labels == ["services-50", "services-200", "services-800", "services-2000", "cap-80000"], f"scale labels changed: {labels}")
    cap = scale[-1]
    stable_cap = {
        "services": 3_636,
        "handles": 10_908,
        "relations": 7_999,
        "observations": 79_990,
        "delivered_messages": 419_348,
        "repair_messages": 94_076,
        "duplicate_messages": 24_321,
        "payload_bytes": 49_803_904,
        "state_cells_before": 79_990,
        "state_cells_after": 39_995,
        "state_bytes_before": 9_700_265,
        "state_bytes_after": 5_303_366,
    }
    for field, expected in stable_cap.items():
        require(as_int(cap, field) == expected, f"cap-case {field} changed: {cap[field]}")
    require(as_float(cap, "false_merge_pairs") == 0, "cap case has a false merge")
    require(close(as_float(cap, "false_split_rate"), 0.10432709937660432), "cap-case false-split rate changed")
    require(as_float(cap, "total_seconds") < 180.0, "cap case exceeded the 180-second limit")
    require(as_float(cap, "peak_rss_mib") < 3_584.0, "cap case exceeded the 3.5-GiB RSS limit")
    require(as_int(cap, "delivered_messages") <= 500_000, "cap case exceeded the delivery limit")

    public_summary_path = RESULTS / "public_target_summary.json"
    require(public_summary_path.is_file(), "missing public target summary")
    public_summary = json.loads(public_summary_path.read_text(encoding="utf-8"))
    require(
        public_summary["records"] == 12
        and public_summary["observations"] == 24
        and public_summary["targets"] == 11,
        "public target dimensions changed",
    )
    require(
        public_summary["countries"] == 10 and public_summary["probe_asns"] == 10,
        "public vantage diversity changed",
    )
    require(
        public_summary["inspected_upstream_fixtures"] == 16
        and public_summary["excluded_upstream_fixtures"] == 4,
        "public fixture census changed",
    )
    require(public_summary["pair_labels"] == {"same": 16, "different": 260}, "public target label counts changed")
    selected_public = public_summary["predicates"][0]
    require(selected_public["predicate"] == "conservative-two-signal", "selected public predicate changed")
    require(selected_public["predicted_same"] == 3 and selected_public["predicted_different"] == 17, "public asserted-vote counts changed")
    require(selected_public["predicted_unknown"] == 256, "public abstention count changed")
    require(selected_public["false_same"] == 0 and selected_public["false_different"] == 0, "public predicate made an unsupported assertion")
    require(close(selected_public["coverage"], 20 / 276), "public coverage changed")
    require(
        public_summary["label_scope"]
        == "exact normalized input-target equality; not service ownership or operator identity",
        "public label scope changed",
    )
    endpoint_control = public_summary["predicates"][1]
    require(endpoint_control["predicate"] == "closed-world-endpoint-negative-control", "public negative control changed")
    require(
        endpoint_control["false_same"] == 2
        and endpoint_control["false_different"] == 7
        and endpoint_control["predicted_unknown"] == 0,
        "closed-world endpoint control no longer exposes both error types",
    )
    target_loo = public_summary["leave_one_target_out"]
    require(target_loo["folds"] == 11, "public leave-one-target-out fold count changed")
    require(
        target_loo["false_same_range"] == [0, 0]
        and target_loo["false_different_range"] == [0, 0],
        "public target-block leave-one-out error changed",
    )
    case_loo = public_summary["leave_one_case_out"]
    require(case_loo["folds"] == 12, "public leave-one-case-out fold count changed")
    require(
        case_loo["false_same_range"] == [0, 0]
        and case_loo["false_different_range"] == [0, 0],
        "public case-block leave-one-out error changed",
    )
    public_pairs = rows("public_target_pairs.csv")
    require(len(public_pairs) == 276, "public target pair surface must contain 276 rows")
    sensitivity = rows("public_target_sensitivity.csv")
    require(len(sensitivity) == 3, "public threshold sensitivity must contain three rows")
    expected_sensitivity = {
        "0.1": (14, 262, 0),
        "0.25": (20, 256, 0),
        "0.5": (24, 252, 0),
    }
    for row in sensitivity:
        asserted = as_int(row, "predicted_same") + as_int(row, "predicted_different")
        expected = expected_sensitivity[row["header_conflict_threshold"]]
        require((asserted, as_int(row, "predicted_unknown"), as_int(row, "false_same") + as_int(row, "false_different")) == expected, "public sensitivity row changed")

    summary_path = RESULTS / "summary.json"
    require(summary_path.is_file(), "missing aggregate summary")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(summary["proposed_all_trials_zero_false_merge"] is True, "aggregate safety predicate failed")
    require(summary["fault_all_post_repair_converged"] is True, "aggregate convergence predicate failed")
    require(summary["fault_all_zero_false_merge"] is True, "aggregate fault merge predicate failed")
    require(summary["fault_all_zero_false_split"] is True, "aggregate fault split predicate failed")

    if not include_extended:
        print(
            "PASS: 105 correctness rows; 25 fault trials; 40,000 sealing schedules; "
            "207 certificates; three compaction depths; five scale cases; "
            "276 public target pairs (core result surfaces)"
        )
        return 0

    equal_work = rows("equal_work.csv")
    require(len(equal_work) == 30, "equal-work surface must contain 30 rows")
    expected_availability = {"peer-evidence": 1.0, "central-recompute": 0.5, "coordinated-quorum": 0.6}
    expected_equal_bytes = {
        "central-recompute": (1_149_719.5, 1_067_960.0, 266_853.0),
        "coordinated-quorum": (3_068_092.5, 3_966_571.0, 800_544.0),
        "peer-evidence": (5_530_409.5, 6_674_914.0, 1_334_240.0),
    }
    for architecture, expected in expected_availability.items():
        selected = [row for row in equal_work if row["architecture"] == architecture]
        require(len(selected) == 10, f"{architecture} must have ten paired cases")
        require(close(statistics.mean(as_float(row, "partition_write_availability") for row in selected), expected), f"{architecture} write availability changed")
        require(close(statistics.mean(as_float(row, "partition_query_availability") for row in selected), expected), f"{architecture} query availability changed")
        require(all(as_int(row, "partition_same") == 0 for row in selected), f"{architecture} authorized SAME before closure")
        require(all(row["final_kind"] == "same" for row in selected), f"{architecture} failed final SAME")
        require(all(as_int(row, "restart_recovered") == 1 for row in selected), f"{architecture} failed restart recovery")
        require(all(as_int(row, "final_false_merge_pairs") == 0 and as_int(row, "final_false_split_pairs") == 0 for row in selected), f"{architecture} final correctness changed")
        medians = (
            statistics.median(as_int(row, "wire_bytes") for row in selected),
            statistics.median(as_int(row, "persistence_bytes_written") for row in selected),
            statistics.median(as_int(row, "final_durable_bytes") for row in selected),
        )
        require(medians == expected_equal_bytes[architecture], f"{architecture} equal-work byte accounting changed")

    equal_summary = json.loads((RESULTS / "equal_work_summary.json").read_text(encoding="utf-8"))
    require(equal_summary["cases"] == 30, "equal-work summary case count changed")
    require(equal_summary["architectures"]["central-recompute"]["partition_availability_by_layout"] == {"authority-majority": 0.6, "authority-minority": 0.4}, "central layout availability changed")
    require(equal_summary["architectures"]["coordinated-quorum"]["partition_availability_by_layout"] == {"authority-majority": 0.6, "authority-minority": 0.6}, "quorum layout availability changed")
    require(equal_summary["architectures"]["peer-evidence"]["partition_availability_by_layout"] == {"authority-majority": 1.0, "authority-minority": 1.0}, "peer layout availability changed")

    print(
        "PASS: 105 correctness rows; 25 fault trials; 40,000 sealing schedules; "
        "207 certificates; three compaction depths; five scale cases; "
        "276 public target pairs; 30 equal-work rows; process-crash surface verified separately"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="verify outputs generated by reproduce.sh without requiring extended campaigns",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(main(include_extended=not args.core_only))
    except (ResultError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
