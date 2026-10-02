#!/usr/bin/env python3
"""Summarize materializer timing evidence without inventing missing raw records."""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = RESULTS / "tpds" / "materializer_replications.csv"
PROVENANCE = RESULTS / "tpds" / "materializer_provenance.json"
FIELDS = [
    "execution",
    "evidence_level",
    "raw_records",
    "independently_reaggregatable",
    "family",
    "handles",
    "cases",
    "reference_median_ms",
    "indexed_median_ms",
    "paired_speedup_median",
    "paired_speedup_min",
    "paired_speedup_max",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def select_summary(
    rows: list[dict[str, str]],
    execution: str,
    evidence_level: str,
    raw_records: int,
    reaggregatable: bool,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for row in rows:
        if int(row["handles"]) != 512:
            continue
        selected.append(
            {
                "execution": execution,
                "evidence_level": evidence_level,
                "raw_records": raw_records,
                "independently_reaggregatable": str(reaggregatable).lower(),
                **{
                    key: row[key]
                    for key in FIELDS
                    if key
                    not in {
                        "execution",
                        "evidence_level",
                        "raw_records",
                        "independently_reaggregatable",
                    }
                },
            }
        )
    return selected


def aggregate_raw(raw_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Recreate the campaign summary from per-call raw rows."""
    grouped: dict[tuple[str, int, int, str], list[float]] = defaultdict(list)
    for row in raw_rows:
        grouped[
            (
                row["family"],
                int(row["handles"]),
                int(row["seed"]),
                row["implementation"],
            )
        ].append(float(row["seconds"]))
    cases: list[dict[str, object]] = []
    for family in sorted({row["family"] for row in raw_rows}):
        for handles in sorted({int(row["handles"]) for row in raw_rows}):
            for seed in sorted({int(row["seed"]) for row in raw_rows}):
                reference = grouped[(family, handles, seed, "reference")]
                indexed = grouped[(family, handles, seed, "indexed")]
                if not reference or not indexed:
                    continue
                reference_median = statistics.median(reference)
                indexed_median = statistics.median(indexed)
                cases.append(
                    {
                        "family": family,
                        "handles": handles,
                        "seed": seed,
                        "reference_seconds": reference_median,
                        "indexed_seconds": indexed_median,
                        "reference_over_indexed": reference_median / indexed_median,
                    }
                )
    summary: list[dict[str, str]] = []
    for family in sorted({str(row["family"]) for row in cases}):
        for handles in sorted({int(row["handles"]) for row in cases}):
            selected = [
                row
                for row in cases
                if row["family"] == family and row["handles"] == handles
            ]
            ratios = [float(row["reference_over_indexed"]) for row in selected]
            summary.append(
                {
                    "family": family,
                    "handles": str(handles),
                    "cases": str(len(selected)),
                    "reference_median_ms": str(
                        1000
                        * statistics.median(
                            float(row["reference_seconds"]) for row in selected
                        )
                    ),
                    "indexed_median_ms": str(
                        1000
                        * statistics.median(
                            float(row["indexed_seconds"]) for row in selected
                        )
                    ),
                    "paired_speedup_median": str(statistics.median(ratios)),
                    "paired_speedup_min": str(min(ratios)),
                    "paired_speedup_max": str(max(ratios)),
                }
            )
    return summary


def main() -> None:
    retained = json.loads((RESULTS / "reproduction.json").read_text(encoding="utf-8"))[
        "timing_replication"
    ]
    primary_summary = retained["primary_summary"]
    clean_raw = retained["clean_raw_timings"]
    clean_summary = aggregate_raw(clean_raw)
    final_summary = read_csv(RESULTS / "tpds" / "materializer_summary.csv")

    rows: list[dict[str, object]] = []
    rows += select_summary(
        primary_summary,
        "summary-only-primary",
        "summary-only; per-call records unavailable",
        0,
        False,
    )
    rows += select_summary(
        clean_summary,
        "retained-clean",
        "per-call raw timings retained in reproduction.json",
        len(clean_raw),
        True,
    )
    rows += select_summary(
        final_summary,
        "final-current",
        "per-call raw timings retained in materializer_raw.csv",
        len(read_csv(RESULTS / "tpds" / "materializer_raw.csv")),
        True,
    )
    if len(rows) != 9:
        raise ValueError("expected three summaries by three families at 512 handles")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    provenance = {
        "summary-only-primary": {
            "summary_source": "results/reproduction.json:timing_replication.primary_summary",
            "raw_source": None,
            "raw_records": 0,
            "independently_reaggregatable": False,
            "interpretation": (
                "The 3.03-fold sparse-cut value survives only as an aggregate summary. "
                "It cannot be independently recomputed and is not counted as a complete "
                "raw-retained execution."
            ),
        },
        "retained-clean": {
            "summary_source": "independently regenerated from clean_raw_timings",
            "raw_source": "results/reproduction.json:timing_replication.clean_raw_timings",
            "raw_records": len(clean_raw),
            "independently_reaggregatable": True,
        },
        "final-current": {
            "summary_source": "results/tpds/materializer_summary.csv",
            "raw_source": "results/tpds/materializer_raw.csv",
            "raw_records": len(read_csv(RESULTS / "tpds" / "materializer_raw.csv")),
            "independently_reaggregatable": True,
        },
    }
    PROVENANCE.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(
        "Wrote three execution summaries: two independently reaggregatable raw "
        "sets and one explicitly summary-only historical execution."
    )


if __name__ == "__main__":
    main()
