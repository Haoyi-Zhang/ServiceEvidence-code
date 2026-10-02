#!/usr/bin/env python3
"""Independent equal-work aggregation shared only by artifact-side generators.

The retained CSV is the source of truth.  The JSON summary is a checked derived
surface, not an input to paper asset generation.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

ARCHITECTURES = (
    "central-recompute",
    "coordinated-quorum",
    "peer-evidence",
)
NUMERIC_FIELDS = (
    "wire_bytes",
    "persistence_bytes_written",
    "final_durable_bytes",
    "elapsed_seconds",
    "rpc_p95_ms",
    "certificate_verification_ms",
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 30:
        raise ValueError("equal-work raw matrix must contain exactly 30 rows")
    tuples = {(row["architecture"], row["layout"], row["seed"]) for row in rows}
    if len(tuples) != 30:
        raise ValueError("equal-work raw matrix contains a duplicate or missing tuple")
    if {row["architecture"] for row in rows} != set(ARCHITECTURES):
        raise ValueError("equal-work architecture set changed")
    return rows


def aggregate(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for architecture in ARCHITECTURES:
        selected = [row for row in rows if row["architecture"] == architecture]
        if len(selected) != 10:
            raise ValueError(f"{architecture} must contain ten cases")
        item: dict[str, Any] = {
            "cases": len(selected),
            "partition_write_availability_mean": statistics.mean(
                float(row["partition_write_availability"]) for row in selected
            ),
            "partition_query_availability_mean": statistics.mean(
                float(row["partition_query_availability"]) for row in selected
            ),
            "partition_availability_by_layout": {
                layout: statistics.mean(
                    float(row["partition_query_availability"])
                    for row in selected
                    if row["layout"] == layout
                )
                for layout in sorted({row["layout"] for row in selected})
            },
            "partition_ambiguous_total": sum(
                int(row["partition_ambiguous"]) for row in selected
            ),
            "partition_same_total": sum(int(row["partition_same"]) for row in selected),
            "all_final_same": all(row["final_kind"] == "same" for row in selected),
            "all_zero_false_merge": all(
                int(row["final_false_merge_pairs"]) == 0 for row in selected
            ),
            "all_zero_false_split": all(
                int(row["final_false_split_pairs"]) == 0 for row in selected
            ),
            "all_restart_recovered": all(
                int(row["restart_recovered"]) == 1 for row in selected
            ),
        }
        for field in NUMERIC_FIELDS:
            values = [float(row[field]) for row in selected]
            median = statistics.median(values)
            item[field + "_median"] = median
            item[field + "_range"] = {
                "min": min(values),
                "median": median,
                "max": max(values),
            }
        result[architecture] = item
    return result
