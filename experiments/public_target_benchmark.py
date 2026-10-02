#!/usr/bin/env python3
"""Evaluate the fixed conservative predicate on public probe/control records."""
from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path

from cie.model import Vote
from cie.public_benchmark import (
    conservative_vote,
    endpoint_only_vote,
    leave_one_case_out,
    leave_one_target_out,
    load_observations,
    pair_decisions,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "external_inputs" / "ooni_dual_vantage_targets.csv"
RESULTS = ROOT / "results"


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("cannot write an empty result")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summary_dict(label: str, rows) -> dict:
    summary = summarize(rows)
    # The pairs reuse observations and were selected as upstream fixtures.
    # Independent-binomial intervals would misstate the sampling design.
    return {"predicate": label, **asdict(summary)}


def main() -> int:
    observations = load_observations(INPUT)
    cases = {row.case_id for row in observations}
    targets = {row.target_id for row in observations}
    countries = {row.probe_cc for row in observations}
    probe_asns = {row.probe_asn for row in observations}
    if len(observations) != 24 or len(cases) != 12 or len(targets) != 11:
        raise RuntimeError("frozen public benchmark dimensions changed")
    if len(countries) != 10 or len(probe_asns) != 10:
        raise RuntimeError("frozen country/ASN diversity changed")

    conservative = pair_decisions(observations)
    endpoint_only = pair_decisions(observations, predicate=endpoint_only_vote)
    result = {
        "records": len(cases),
        "observations": len(observations),
        "targets": len(targets),
        "countries": len(countries),
        "probe_asns": len(probe_asns),
        "inspected_upstream_fixtures": 16,
        "excluded_upstream_fixtures": 4,
        "label_scope": "exact normalized input-target equality; not service ownership or operator identity",
        "sampling_scope": "frozen set of 16 inspected upstream Web Connectivity fixture candidates; 12 unique extractable records retained after identity deduplication; not a representative Web sample",
        "uncertainty_scope": "no independent-pair confidence intervals: pairs share observations and the fixtures are not a probability sample; target-block and case-block leave-one-out ranges are finite-family sensitivity checks, not population confidence intervals",
        "pair_labels": {"same": 16, "different": 260},
        "predicates": [
            summary_dict("conservative-two-signal", conservative),
            summary_dict("closed-world-endpoint-negative-control", endpoint_only),
        ],
    }

    loo = leave_one_target_out(observations)
    result["leave_one_target_out"] = {
        "folds": len(loo),
        "coverage_range": [min(row.coverage for row in loo), max(row.coverage for row in loo)],
        "asserted_error_rate_range": [
            min(row.asserted_error_rate for row in loo),
            max(row.asserted_error_rate for row in loo),
        ],
        "false_same_range": [min(row.false_same for row in loo), max(row.false_same for row in loo)],
        "false_different_range": [
            min(row.false_different for row in loo), max(row.false_different for row in loo)
        ],
    }

    case_loo = leave_one_case_out(observations)
    result["leave_one_case_out"] = {
        "folds": len(case_loo),
        "coverage_range": [
            min(row.coverage for row in case_loo), max(row.coverage for row in case_loo)
        ],
        "asserted_error_rate_range": [
            min(row.asserted_error_rate for row in case_loo),
            max(row.asserted_error_rate for row in case_loo),
        ],
        "false_same_range": [
            min(row.false_same for row in case_loo), max(row.false_same for row in case_loo)
        ],
        "false_different_range": [
            min(row.false_different for row in case_loo),
            max(row.false_different for row in case_loo),
        ],
    }

    pair_rows = []
    for row in conservative:
        pair_rows.append(
            {
                "left": row.left.observation_id,
                "right": row.right.observation_id,
                "truth": row.truth.value,
                "prediction": row.prediction.value,
                "reason": row.reason,
            }
        )
    write_csv(RESULTS / "public_target_pairs.csv", pair_rows)

    sensitivity = []
    for threshold in (0.10, 0.25, 0.50):
        rows = pair_decisions(
            observations,
            predicate=conservative_vote,
            header_conflict_threshold=threshold,
        )
        summary = summarize(rows)
        sensitivity.append({"header_conflict_threshold": threshold, **asdict(summary)})
    write_csv(RESULTS / "public_target_sensitivity.csv", sensitivity)

    (RESULTS / "public_target_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    selected = result["predicates"][0]
    if selected["false_same"] or selected["false_different"]:
        raise RuntimeError("conservative public predicate made an unsupported assertion")
    if selected["predicted_unknown"] == 0:
        raise RuntimeError("conservative public predicate failed to expose uncertainty")
    negative = result["predicates"][1]
    if negative["false_same"] == 0 or negative["false_different"] == 0:
        raise RuntimeError(
            "closed-world endpoint negative control did not expose both false-merge and false-split hazards"
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
