#!/usr/bin/env python3
"""Print manuscript TeX derived from the recorded five generated TCP cases."""
import argparse
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
rows = [json.loads((ROOT / f"results/socket/generated-{seed}/result.json").read_text()) for seed in range(1,6)]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--numbers", action="store_true")
args = parser.parse_args()
if args.numbers:
    for name, field, fn in [("SocketMin","elapsed_seconds",min),("SocketMax","elapsed_seconds",max),
                            ("CentralMin","centralized_seconds",min),("CentralMax","centralized_seconds",max)]:
        value = fn(row[field] for row in rows)
        print(f"\\newcommand{{\\{name}}}{{{value:.3f}}}")
else:
    print(r"\begin{table}[t]\centering")
    print(r"\caption{Five-endpoint TCP campaigns, 2,200 cells each. Wire bytes include all request/response frames and diagnostic reads; endpoints share one event loop.}")
    print(r"\label{tab:socket}\small\begin{tabular}{rrrr}")
    print(r"\toprule Seed & RPCs & Wire (MiB) & Time (s)\\\midrule")
    for row in rows:
        print(f"{row['seed']} & {row['requests']} & {row['wire_bytes']/1024**2:.2f} & {row['elapsed_seconds']:.3f} " + r"\\")
    print(r"\bottomrule\end{tabular}\end{table}")
