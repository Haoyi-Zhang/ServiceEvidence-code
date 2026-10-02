#!/usr/bin/env python3
"""Render paper-ready LaTeX tables from retained result summaries."""
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
MIB = 1024 * 1024


def public_table() -> str:
    data = json.loads((RESULTS / "public_target_summary.json").read_text(encoding="utf-8"))
    rows = {row["predicate"]: row for row in data["predicates"]}
    selected = rows["conservative-two-signal"]
    control = rows["closed-world-endpoint-negative-control"]
    return rf"""\begin{{table}}[t]
\centering
\caption{{Public probe/control target-equivalence check over {selected['pairs']} pairs. ``Err.'' counts asserted labels inconsistent with exact normalized input-target equality; it is not an ownership or operator label.}}
\label{{tab:public-target}}
\scriptsize
\setlength{{\tabcolsep}}{{3.5pt}}
\begin{{tabular}}{{lrrrrr}}
\toprule
Predicate & Same & Diff. & Unknown & Err. & Coverage\\
\midrule
Two-signal & {selected['predicted_same']} & {selected['predicted_different']} & {selected['predicted_unknown']} & {selected['false_same'] + selected['false_different']} & {100*selected['coverage']:.1f}\%\\
Closed-world endpoint & {control['predicted_same']} & {control['predicted_different']} & {control['predicted_unknown']} & {control['false_same'] + control['false_different']} & {100*control['coverage']:.1f}\%\\
\bottomrule
\end{{tabular}}
\end{{table}}
"""


def equal_table() -> str:
    data = aggregate_equal_work(read_equal_work_rows(RESULTS / "equal_work.csv"))
    labels = [
        ("central-recompute", "Central"),
        ("coordinated-quorum", "Quorum"),
        ("peer-evidence", "Peer evidence"),
    ]
    body=[]
    for key,label in labels:
        row=data[key]
        body.append(
            f"{label} & {100*row['partition_query_availability_mean']:.0f} & "
            f"{row['wire_bytes_median']/MIB:.2f} & "
            f"{row['persistence_bytes_written_median']/MIB:.2f} & "
            f"{row['final_durable_bytes_median']/MIB:.2f} & "
            f"{row['elapsed_seconds_median']:.2f}\\\\"
        )
    return """\\begin{table}[t]
\\centering
\\caption{Equal-work loopback comparison: medians over ten cases per architecture (five seeds, two partition layouts). Response rate is the fraction of partition-time query sites that receive a response; all such answers are ambiguous. Bytes are MiB.}
\\label{tab:equal-work}
\\scriptsize
\\begin{tabular}{lrrrrr}
\\toprule
Architecture & Response \\% & Wire & Persisted & Final & Time (s)\\\\
\\midrule
""" + "\n".join(body) + "\n" + """\\bottomrule
\\end{tabular}
\\end{table}
"""


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("public","equal"))
    args=parser.parse_args()
    print(public_table() if args.kind=="public" else equal_table(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
