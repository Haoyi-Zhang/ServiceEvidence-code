#!/usr/bin/env python3
"""Check paper tables, macros, prose anchors, and metadata against retained data."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MIB = 1024**2
ARCH = {
    "central-recompute": ("Central", "EqualCentralTime", "40/60"),
    "coordinated-quorum": ("Quorum", "EqualQuorumTime", "60/60"),
    "peer-evidence": ("Peer evidence", "EqualPeerTime", "100/100"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def raw_rows() -> list[dict[str, str]]:
    with (RESULTS / "equal_work.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 30, "equal-work raw matrix must contain 30 rows")
    require(
        len({(row["architecture"], row["layout"], row["seed"]) for row in rows}) == 30,
        "equal-work raw matrix contains duplicate or missing tuples",
    )
    return rows


def aggregate(rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for architecture in ARCH:
        selected = [row for row in rows if row["architecture"] == architecture]
        require(len(selected) == 10, f"{architecture} must have ten rows")
        item: dict[str, object] = {
            "availability": statistics.mean(
                float(row["partition_query_availability"]) for row in selected
            ),
            "availability_by_layout": {
                layout: statistics.mean(
                    float(row["partition_query_availability"])
                    for row in selected
                    if row["layout"] == layout
                )
                for layout in sorted({row["layout"] for row in selected})
            },
        }
        for field in (
            "wire_bytes",
            "persistence_bytes_written",
            "final_durable_bytes",
            "elapsed_seconds",
        ):
            values = [float(row[field]) for row in selected]
            item[field + "_median"] = statistics.median(values)
            item[field + "_range"] = (min(values), max(values))
        result[architecture] = item
    return result


def main_table_rows(text: str) -> dict[str, tuple[str, str, str, str, str]]:
    result: dict[str, tuple[str, str, str, str, str]] = {}
    for label, _, _ in ARCH.values():
        match = re.search(
            rf"^{re.escape(label)}\s*&\s*([0-9]+)\s*&\s*([0-9.]+)\s*&\s*"
            rf"([0-9.]+)\s*&\s*([0-9.]+)\s*&\s*([0-9.]+)\\\\$",
            text,
            flags=re.MULTILINE,
        )
        require(match is not None, f"missing equal-work table row for {label}")
        result[label] = match.groups()
    return result


def range_table_rows(text: str) -> dict[str, tuple[str, str, str, str]]:
    result: dict[str, tuple[str, str, str, str]] = {}
    labels = ("Central", "Quorum", "Peer")
    for label in labels:
        match = re.search(
            rf"^{label}\s*&\s*([0-9]+/[0-9]+)\\%\s*&\s*"
            rf"([0-9.]+--[0-9.]+)\s*&\s*([0-9.]+--[0-9.]+)\s*&\s*"
            rf"([0-9.]+--[0-9.]+)\\\\$",
            text,
            flags=re.MULTILINE,
        )
        require(match is not None, f"missing equal-work range row for {label}")
        result[label] = match.groups()
    return result


def macro_values(text: str) -> dict[str, str]:
    return dict(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{([^}]*)\}", text))


def close(left: object, right: object) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-dir", type=Path, required=True)
    args = parser.parse_args()
    paper = args.paper_dir.resolve()

    values = aggregate(raw_rows())
    expected_times = {
        key: f"{float(item['elapsed_seconds_median']):.2f}"
        for key, item in values.items()
    }
    require(
        expected_times
        == {
            "central-recompute": "0.24",
            "coordinated-quorum": "1.16",
            "peer-evidence": "2.55",
        },
        "retained equal-work medians no longer match the frozen 30 cases",
    )

    retained_summary = json.loads(
        (RESULTS / "equal_work_summary.json").read_text(encoding="utf-8")
    )["architectures"]
    generated = json.loads(
        (paper / "tables" / "generated-summary.json").read_text(encoding="utf-8")
    )
    require(
        generated.get("equal_work_source")
        == "artifact/results/equal_work.csv (30 retained rows)",
        "generated summary does not identify the retained raw source",
    )

    main_rows = main_table_rows(
        (paper / "tables" / "equal-work.tex").read_text(encoding="utf-8")
    )
    range_rows = range_table_rows(
        (paper / "tables" / "equal-ranges.tex").read_text(encoding="utf-8")
    )
    macros = macro_values(
        (paper / "tables" / "measured-values.tex").read_text(encoding="utf-8")
    )

    for key, (main_label, macro, expected_availability_pair) in ARCH.items():
        item = values[key]
        exact_time = float(item["elapsed_seconds_median"])
        summary_item = retained_summary[key]
        generated_item = generated["equal_work"][key]
        require(close(summary_item["elapsed_seconds_median"], exact_time), f"retained summary time differs for {key}")
        require(close(generated_item["exact_seconds"], exact_time), f"generated exact time differs for {key}")
        require(generated_item["rendered_seconds"] == expected_times[key], f"generated rendered time differs for {key}")
        require(macros.get(macro) == expected_times[key], f"measured macro differs for {macro}")

        expected_main = (
            f"{100 * float(item['availability']):.0f}",
            f"{float(item['wire_bytes_median'])/MIB:.2f}",
            f"{float(item['persistence_bytes_written_median'])/MIB:.2f}",
            f"{float(item['final_durable_bytes_median'])/MIB:.2f}",
            expected_times[key],
        )
        require(main_rows[main_label] == expected_main, f"main equal-work row differs for {main_label}")
        require(close(generated_item["wire_bytes_median"], item["wire_bytes_median"]), f"generated wire median differs for {key}")
        require(close(generated_item["persistence_bytes_written_median"], item["persistence_bytes_written_median"]), f"generated persistence median differs for {key}")
        require(close(generated_item["final_durable_bytes_median"], item["final_durable_bytes_median"]), f"generated final-durable median differs for {key}")
        require(close(generated_item["partition_query_availability_mean"], item["availability"]), f"generated availability differs for {key}")

        range_label = "Peer" if main_label == "Peer evidence" else main_label
        expected_ranges = []
        for field in ("wire_bytes", "persistence_bytes_written", "elapsed_seconds"):
            low, high = item[field + "_range"]
            divisor = 1 if field == "elapsed_seconds" else MIB
            expected_ranges.append(f"{low/divisor:.2f}--{high/divisor:.2f}")
        require(
            range_rows[range_label]
            == (expected_availability_pair, *expected_ranges),
            f"supplement equal-work range row differs for {range_label}",
        )
        generated_range = generated_item["elapsed_seconds_range"]
        low, high = item["elapsed_seconds_range"]
        require(close(generated_range["min"], low) and close(generated_range["max"], high), f"generated time range differs for {key}")

    main_tex = (paper / "main.tex").read_text(encoding="utf-8")
    supplement = (paper / "supplement-content.tex").read_text(encoding="utf-8")
    authors = (paper / "authors.tex").read_text(encoding="utf-8")
    require(
        "\\EqualPeerTime{}, \\EqualQuorumTime{}, \\EqualCentralTime{}" in main_tex,
        "main text must use generated equal-work macros",
    )
    require(
        "\\input{tables/equal-ranges.tex}" in supplement,
        "supplement does not use the generated equal-work range table",
    )
    require(
        "\\input{tables/materializer-provenance.tex}" in supplement,
        "supplement does not use the generated materializer provenance table",
    )
    require(
        "three retained executions" not in main_tex.lower(),
        "paper overstates materializer raw retention",
    )
    require(
        re.search(r"Author\s*[3-6]", main_tex + supplement + authors, flags=re.I) is None,
        "fictional author placeholder remains on a publication surface",
    )

    provenance = generated.get("materializer_evidence", {})
    require(provenance["summary-only-primary"]["raw_records"] == 0, "primary materializer raw status differs")
    require(provenance["summary-only-primary"]["independently_reaggregatable"] is False, "primary materializer status is overstated")
    require(provenance["retained-clean"]["raw_records"] == 600, "clean materializer raw count differs")
    require(provenance["final-current"]["raw_records"] == 600, "final materializer raw count differs")

    print(
        "PASS: raw equal-work rows independently match the main table, supplement ranges, "
        "exact generated summary fields, macros, author surface, and materializer provenance"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
