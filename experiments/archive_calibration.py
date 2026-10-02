#!/usr/bin/env python3
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "external_inputs" / "public_http_calibration.csv"
OUTPUT = ROOT / "results" / "archive_calibration.csv"


def authority(url: str) -> str:
    return urlsplit(url).netloc.lower()


def main() -> int:
    with INPUT.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_site = defaultdict(list)
    for row in rows:
        by_site[row["site"]].append(row)
    output = []
    for site, entries in sorted(by_site.items()):
        entries.sort(key=lambda row: int(row["step"]))
        authorities = [authority(row["request_url"]) for row in entries]
        endpoints = [row["server_ip"] for row in entries]
        redirect_edges = sum(bool(row["redirect_url"]) for row in entries)
        output.append(
            {
                "site": site,
                "navigation_entries": len(entries),
                "redirect_edges": redirect_edges,
                "distinct_authorities": len(set(authorities)),
                "distinct_endpoints": len(set(endpoints)),
                "authority_changes": sum(a != b for a, b in zip(authorities, authorities[1:])),
                "endpoint_changes": sum(a != b for a, b in zip(endpoints, endpoints[1:])),
                "terminal_status": entries[-1]["status"],
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(f"PASS: {len(rows)} observations across {len(output)} archived navigations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
