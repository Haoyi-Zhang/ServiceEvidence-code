#!/usr/bin/env python3
"""Audit the frozen public-input census and its minimized extraction tables."""
from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "external_inputs"
DATA = INPUTS / "ooni_dual_vantage_targets.csv"
MAPPING = INPUTS / "ooni_field_mapping.csv"
SELECTION = INPUTS / "ooni_fixture_selection.csv"


class AuditError(ValueError):
    pass


def rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise AuditError(f"missing input ledger: {path.name}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise AuditError(f"missing header: {path.name}")
        result = list(reader)
    if not result:
        raise AuditError(f"empty input ledger: {path.name}")
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def official_github_url(value: str, filename: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and parsed.path
        == f"/ooni/pipeline/blob/master/af/fastpath/fastpath/tests/data/{filename}"
    )


def main() -> int:
    data = rows(DATA)
    mapping = rows(MAPPING)
    selection = rows(SELECTION)

    included = [row for row in selection if row["decision"] == "include"]
    excluded = [row for row in selection if row["decision"] == "exclude"]
    require(len(included) == 12, "fixture census must retain 12 unique measurement records")
    require(len(excluded) == 4, "fixture census must document four exclusions")
    require({row["decision"] for row in selection} == {"include", "exclude"}, "invalid selection decision")
    require(len({row["filename"] for row in selection}) == len(selection), "duplicate selection filename")
    require(all(row["rationale"].strip() for row in selection), "selection rationale is missing")
    require(
        all(official_github_url(row["source_url"], row["filename"]) for row in selection),
        "selection URL is not the declared upstream fixture path",
    )

    case_ids = [row["case_id"] for row in data]
    require(len(data) == 12, "minimized table must contain 12 cases")
    require(len(set(case_ids)) == len(case_ids), "duplicate minimized case identifier")
    require(set(case_ids) == {row["case_id"] for row in included}, "selection/data case sets differ")
    require(
        {(row["case_id"], row["target_id"], row["source_url"]) for row in data}
        == {(row["case_id"], row["target_id"], row["source_url"]) for row in included},
        "selection and minimized rows disagree",
    )

    mapping_by_case = {row["case_id"]: row for row in mapping}
    require(len(mapping_by_case) == len(mapping), "duplicate field-mapping case")
    require(set(mapping_by_case) == set(case_ids), "field mapping does not cover every included case")
    required_paths = {
        "target_path",
        "probe_endpoint_path",
        "control_endpoint_path",
        "probe_tcp_success_path",
        "control_tcp_success_path",
        "probe_status_path",
        "control_status_path",
        "probe_headers_path",
        "control_headers_path",
        "probe_title_path",
        "control_title_path",
    }
    for case_id, row in mapping_by_case.items():
        require(all(row[field].strip() for field in required_paths), f"empty mapping path for {case_id}")
        source_name = next(item["filename"] for item in included if item["case_id"] == case_id)
        require(row["source_file"] == source_name, f"mapping source mismatch for {case_id}")

    targets = {row["target_id"] for row in data}
    require(len(targets) == 11, "expected 11 normalized targets")
    require(sum(row["target_id"] == "https://fa.wikipedia.org" for row in data) == 2,
            "two independent Persian-Wikipedia records must share one normalized target")
    require(len({row["probe_cc"] for row in data}) == 10, "expected ten countries")
    require(len({row["probe_asn"] for row in data}) == 10, "expected ten probe ASNs")

    # Freeze known missingness boundaries that would be easy to over-impute.
    by_case = {row["case_id"]: row for row in data}
    require(not by_case["sk-wikispaces"]["probe_endpoints"], "null probe transport was imputed")
    require(not by_case["sk-wikispaces"]["control_endpoints"], "empty control transport was imputed")
    require(by_case["nl-fa-wikipedia"]["probe_status"] == "", "empty probe request list gained an HTTP status")
    require(by_case["ir-fa-wikipedia"]["control_endpoints"] == "", "control HTTP/DNS evidence became a TCP endpoint")
    require(by_case["ir-fa-wikipedia"]["control_tcp_success"] == "0", "control HTTP evidence became TCP success")

    print(
        "PASS: 16 inspected upstream fixture files; 12 unique records retained; "
        "11 normalized targets; 12 field mappings; missingness boundaries preserved"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, KeyError) as error:
        print(f"FAIL: {error}")
        raise SystemExit(1)
