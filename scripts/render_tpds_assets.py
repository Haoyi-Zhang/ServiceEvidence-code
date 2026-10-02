#!/usr/bin/env python3
"""Derive TPDS tables and scalar macros from retained experimental results."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from equal_work_data import aggregate as aggregate_equal_work
from equal_work_data import read_rows as read_equal_work_rows

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MIB = 1024**2


def rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def render_macros(output: Path, equal: dict[str, dict[str, object]]) -> dict[str, str]:
    scale = max(rows("scale.csv"), key=lambda row: int(row["observations"]))
    process = rows("process_crash.csv")
    values = {
        "ProcessMin": f"{min(float(row['elapsed_seconds']) for row in process):.2f}",
        "ProcessMax": f"{max(float(row['elapsed_seconds']) for row in process):.2f}",
        "ScaleRss": f"{float(scale['peak_rss_mib']):.1f}",
        "ScaleTime": f"{float(scale['total_seconds']):.2f}",
        "ScaleCertMedian": f"{float(scale['certificate_ms_median']):.1f}",
        "ScaleCertPtail": f"{float(scale['certificate_ms_p95']):.1f}",
        "EqualCentralTime": f"{float(equal['central-recompute']['elapsed_seconds_median']):.2f}",
        "EqualQuorumTime": f"{float(equal['coordinated-quorum']['elapsed_seconds_median']):.2f}",
        "EqualPeerTime": f"{float(equal['peer-evidence']['elapsed_seconds_median']):.2f}",
    }
    output.write_text(
        "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()),
        encoding="utf-8",
    )
    return values


def render_certificate_table(output: Path) -> None:
    witness = rows("witnesses.csv")
    lines = [
        r"\begin{table}[t]\centering",
        r"\caption{Independent certificate checks. Generation and verification are median milliseconds; size is median serialized bytes.}",
        r"\label{tab:certs}\small",
        r"\begin{tabular}{lrrrr}\toprule",
        r"Kind & Count & Bytes & Generate & Verify\\\midrule",
    ]
    for kind in ("same", "different", "ambiguous"):
        selected = [row for row in witness if row["kind"] == kind]
        median = lambda field: statistics.median(float(row[field]) for row in selected)
        lines.append(
            f"{kind} & {len(selected)} & {median('certificate_bytes'):.0f} & "
            f"{median('generation_ms'):.2f} & {median('verification_ms'):.2f}"
            + r"\\"
        )
    lines += [r"\bottomrule\end{tabular}\end{table}"]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_equal_ranges(output: Path, equal: dict[str, dict[str, object]]) -> None:
    lines = [
        r"\begin{table}[t]\centering",
        r"\caption{Equal-work ranges across ten cases per architecture. Response percentages use the two measured cuts; byte columns are MiB.}",
        r"\label{tab:equal-work-ranges}\scriptsize",
        r"\begin{tabular}{lrrrr}\toprule",
        r"Architecture & Response & Wire & Persisted & Time (s)\\\midrule",
    ]
    labels = (
        ("central-recompute", "Central", "40/60"),
        ("coordinated-quorum", "Quorum", "60/60"),
        ("peer-evidence", "Peer", "100/100"),
    )
    for key, label, availability in labels:
        item = equal[key]
        rendered: list[str] = []
        for field in ("wire_bytes", "persistence_bytes_written", "elapsed_seconds"):
            value = item[field + "_range"]
            divisor = 1 if field == "elapsed_seconds" else MIB
            rendered.append(f"{value['min']/divisor:.2f}--{value['max']/divisor:.2f}")
        lines.append(" & ".join([label, availability + r"\%", *rendered]) + r"\\")
    lines += [r"\bottomrule\end{tabular}\end{table}"]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_materializer_provenance(output: Path) -> dict[str, object]:
    provenance_path = RESULTS / "tpds" / "materializer_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    replications = rows("tpds/materializer_replications.csv")
    lookup = {(row["execution"], row["family"]): row for row in replications}
    lines = [
        r"\begin{table}[t]\centering",
        r"\caption{Materializer timing provenance at 512 handles. Values are median reference/indexed speedups. The primary historical execution is summary-only and cannot be independently reaggregated.}",
        r"\label{tab:materializer-provenance}\scriptsize",
        r"\begin{tabular}{lrrrr}\toprule",
        r"Execution & Sparse & Dense & Low conflict & Raw calls\\\midrule",
    ]
    for execution, label in (
        ("final-current", "Final current"),
        ("retained-clean", "Clean retained"),
        ("summary-only-primary", "Earlier primary"),
    ):
        values = [
            float(lookup[(execution, family)]["paired_speedup_median"])
            for family in ("sparse_cut", "dense_cut", "low_conflict")
        ]
        raw_records = int(lookup[(execution, "sparse_cut")]["raw_records"])
        raw_label = str(raw_records) if raw_records else "none"
        lines.append(
            f"{label} & {values[0]:.2f} & {values[1]:.2f} & "
            f"{values[2]:.2f} & {raw_label}" + r"\\"
        )
    lines += [r"\bottomrule\end{tabular}\end{table}"]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return provenance


def render_index_plot(output: Path) -> None:
    benchmark = rows("tpds/materializer_summary.csv")
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["handles", "sparse_cut", "dense_cut", "low_conflict"])
        for handles in (64, 128, 256, 512):
            writer.writerow(
                [handles]
                + [
                    next(
                        row["paired_speedup_median"]
                        for row in benchmark
                        if int(row["handles"]) == handles and row["family"] == family
                    )
                    for family in ("sparse_cut", "dense_cut", "low_conflict")
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    equal_rows = read_equal_work_rows(RESULTS / "equal_work.csv")
    equal = aggregate_equal_work(equal_rows)
    macros = render_macros(output / "measured-values.tex", equal)
    render_certificate_table(output / "certificates.tex")
    render_equal_ranges(output / "equal-ranges.tex", equal)
    provenance = render_materializer_provenance(output / "materializer-provenance.tex")
    render_index_plot(output / "index-speedup.csv")

    generated_equal = {}
    for key, item in equal.items():
        generated_equal[key] = {
            "exact_seconds": item["elapsed_seconds_median"],
            "rendered_seconds": f"{float(item['elapsed_seconds_median']):.2f}",
            "elapsed_seconds_range": item["elapsed_seconds_range"],
            "wire_bytes_median": item["wire_bytes_median"],
            "persistence_bytes_written_median": item["persistence_bytes_written_median"],
            "final_durable_bytes_median": item["final_durable_bytes_median"],
            "partition_query_availability_mean": item["partition_query_availability_mean"],
        }
    (output / "generated-summary.json").write_text(
        json.dumps(
            {
                "equal_work": generated_equal,
                "equal_work_source": "artifact/results/equal_work.csv (30 retained rows)",
                "materializer_evidence": provenance,
                "macros": macros,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Rendered TPDS values, certificates, ranges, provenance, and paired timing plot from retained raw data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
