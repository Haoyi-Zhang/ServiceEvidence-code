#!/usr/bin/env python3
"""Verify timing-environment provenance and future capture coverage."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
REQUIRED = {
    "equal-work-retained-30",
    "process-crash-retained-3",
    "socket-retained-7",
    "scale-retained-5",
    "witness-retained-207",
    "materializer-summary-only-primary",
    "materializer-retained-clean",
    "materializer-final-current",
}
ENV_FIELDS = (
    "cpu_model",
    "cpu_core_allocation",
    "memory_constraint",
    "os",
    "python_version",
    "container_or_virtualization",
    "persistence_medium",
    "filesystem",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    path = RESULTS / "timing_environment_inventory.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    require({row["execution_id"] for row in rows} == REQUIRED, "timing inventory execution set differs")
    for row in rows:
        require(row["result_surface"], "timing inventory lacks a result surface")
        require(row["environment_status"], "timing inventory lacks status")
        require(row["notes"], "timing inventory lacks notes")
        for field in ENV_FIELDS:
            require(row[field] == "unknown", f"historical field {field} must not be guessed")
    primary = next(row for row in rows if row["execution_id"] == "materializer-summary-only-primary")
    require(primary["raw_timing_records_retained"] == "no", "primary raw-retention status is inaccurate")
    for execution in ("materializer-retained-clean", "materializer-final-current", "equal-work-retained-30"):
        row = next(item for item in rows if item["execution_id"] == execution)
        require(row["raw_timing_records_retained"] == "yes", f"{execution} raw-retention status is inaccurate")

    runtime = RESULTS / "runtime_environment"
    if runtime.exists():
        for record_path in runtime.glob("*.json"):
            record = json.loads(record_path.read_text(encoding="utf-8"))
            require(record.get("scope_note"), "runtime environment lacks scope note")
            require(record.get("cpu", {}).get("logical_cores_visible") is not None, "runtime environment lacks core count")
            require(record.get("os", {}).get("system"), "runtime environment lacks OS")
            require(record.get("python", {}).get("version"), "runtime environment lacks Python version")
            require("persistence_medium" in record.get("persistence", {}), "runtime environment lacks persistence medium field")
            require("filesystem_type" in record.get("persistence", {}), "runtime environment lacks filesystem field")
    print("PASS: timing environment inventory is complete; historical unknowns remain explicit; future capture schema validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
