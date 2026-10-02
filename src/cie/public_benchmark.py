"""Conservative target-equivalence checks over public dual-vantage records.

The benchmark label is the exact normalized input target carried by the public
fixture.  The predicate deliberately does not inspect that label: it uses only
endpoint, transport, status, header-name, and title observations.  It returns
UNKNOWN whenever the evidence is insufficient for a supported assertion.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
from math import sqrt
from pathlib import Path
from typing import Iterable, Sequence

from .model import Vote


@dataclass(frozen=True)
class Observation:
    case_id: str
    target_id: str
    vantage: str
    probe_cc: str
    probe_asn: str
    endpoints: frozenset[str]
    tcp_success: bool
    status: int | None
    headers: frozenset[str]
    title: str
    failure: str

    @property
    def observation_id(self) -> str:
        return f"{self.case_id}:{self.vantage}"


@dataclass(frozen=True)
class PairDecision:
    left: Observation
    right: Observation
    truth: Vote
    prediction: Vote
    reason: str


@dataclass(frozen=True)
class Summary:
    pairs: int
    true_same: int
    true_different: int
    predicted_same: int
    predicted_different: int
    predicted_unknown: int
    false_same: int
    false_different: int
    coverage: float
    asserted_error_rate: float
    same_precision: float
    same_recall: float
    different_precision: float
    different_recall: float


def _split_set(value: str) -> frozenset[str]:
    return frozenset(piece.strip().lower() for piece in value.split(";") if piece.strip())


def _status(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def load_observations(path: Path) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {
            "case_id", "target_id", "probe_cc", "probe_asn",
            "probe_endpoints", "control_endpoints",
            "probe_tcp_success", "control_tcp_success",
            "probe_status", "control_status", "probe_headers",
            "control_headers", "probe_title", "control_title",
            "probe_failure", "control_failure", "source_url",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("public target input has an incompatible schema")
        seen_cases: set[str] = set()
        for row in reader:
            case_id = row["case_id"].strip()
            target = row["target_id"].strip()
            if not case_id or case_id in seen_cases or not target:
                raise ValueError("case identifiers and target labels must be unique and non-empty")
            seen_cases.add(case_id)
            for vantage in ("probe", "control"):
                observations.append(
                    Observation(
                        case_id=case_id,
                        target_id=target,
                        vantage=vantage,
                        probe_cc=row["probe_cc"].strip(),
                        probe_asn=row["probe_asn"].strip(),
                        endpoints=_split_set(row[f"{vantage}_endpoints"]),
                        tcp_success=_bool(row[f"{vantage}_tcp_success"]),
                        status=_status(row[f"{vantage}_status"]),
                        headers=_split_set(row[f"{vantage}_headers"]),
                        title=row[f"{vantage}_title"].strip().lower(),
                        failure=row[f"{vantage}_failure"].strip().lower(),
                    )
                )
    if len(observations) < 4:
        raise ValueError("public target family is too small")
    return tuple(observations)


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def conservative_vote(
    left: Observation,
    right: Observation,
    *,
    header_conflict_threshold: float = 0.25,
) -> tuple[Vote, str]:
    """Return a supported SAME/DIFFERENT vote or abstain.

    SAME requires both a successful endpoint overlap and a matching successful
    HTTP signature. DIFFERENT requires disjoint successful endpoints plus two
    independent HTTP conflicts. The target labels are not inspected.
    """
    if left.observation_id == right.observation_id:
        raise ValueError("a comparison requires distinct observations")
    if not 0.0 <= header_conflict_threshold <= 1.0:
        raise ValueError("header threshold must be in [0,1]")

    overlap = left.endpoints & right.endpoints

    both_http = (
        left.status is not None
        and right.status is not None
        and 100 <= left.status <= 599
        and 100 <= right.status <= 599
    )
    header_similarity = jaccard(left.headers, right.headers)
    matching_title = bool(left.title and right.title and left.title == right.title)
    matching_http = bool(
        both_http
        and left.status == right.status
        and (
            matching_title
            or (left.headers and right.headers and header_similarity >= 0.5)
        )
    )
    if overlap and left.tcp_success and right.tcp_success and matching_http:
        return Vote.SAME, "successful-endpoint-and-http-signature"

    if (
        left.endpoints
        and right.endpoints
        and not overlap
        and left.tcp_success
        and right.tcp_success
        and both_http
    ):
        conflicts = 0
        if left.status // 100 != right.status // 100:
            conflicts += 1
        if left.title and right.title and left.title != right.title:
            conflicts += 1
        if left.headers and right.headers and header_similarity <= header_conflict_threshold:
            conflicts += 1
        if conflicts >= 2:
            return Vote.DIFFERENT, "disjoint-endpoints-and-two-http-conflicts"

    return Vote.UNKNOWN, "insufficient-independent-evidence"


def endpoint_only_vote(left: Observation, right: Observation) -> tuple[Vote, str]:
    """Closed-world negative control: no observed overlap means different.

    This deliberately overconfident rule treats a missing endpoint observation
    as evidence of inequality.  It is retained only to expose the false-split
    hazard that the conservative predicate avoids.
    """
    overlap = left.endpoints & right.endpoints
    if overlap:
        return Vote.SAME, "endpoint-overlap"
    return Vote.DIFFERENT, "no-observed-endpoint-overlap"


def pair_decisions(
    observations: Sequence[Observation],
    *,
    predicate=conservative_vote,
    **predicate_kwargs,
) -> tuple[PairDecision, ...]:
    rows: list[PairDecision] = []
    for index, left in enumerate(observations):
        for right in observations[index + 1 :]:
            truth = Vote.SAME if left.target_id == right.target_id else Vote.DIFFERENT
            prediction, reason = predicate(left, right, **predicate_kwargs)
            rows.append(PairDecision(left, right, truth, prediction, reason))
    return tuple(rows)


def summarize(rows: Sequence[PairDecision]) -> Summary:
    pairs = len(rows)
    true_same = sum(row.truth == Vote.SAME for row in rows)
    true_different = sum(row.truth == Vote.DIFFERENT for row in rows)
    predicted_same = sum(row.prediction == Vote.SAME for row in rows)
    predicted_different = sum(row.prediction == Vote.DIFFERENT for row in rows)
    predicted_unknown = sum(row.prediction == Vote.UNKNOWN for row in rows)
    false_same = sum(row.prediction == Vote.SAME and row.truth != Vote.SAME for row in rows)
    false_different = sum(
        row.prediction == Vote.DIFFERENT and row.truth != Vote.DIFFERENT for row in rows
    )
    asserted = predicted_same + predicted_different
    same_true_positive = predicted_same - false_same
    different_true_positive = predicted_different - false_different
    return Summary(
        pairs=pairs,
        true_same=true_same,
        true_different=true_different,
        predicted_same=predicted_same,
        predicted_different=predicted_different,
        predicted_unknown=predicted_unknown,
        false_same=false_same,
        false_different=false_different,
        coverage=asserted / pairs if pairs else 0.0,
        asserted_error_rate=(false_same + false_different) / asserted if asserted else 0.0,
        same_precision=same_true_positive / predicted_same if predicted_same else 0.0,
        same_recall=same_true_positive / true_same if true_same else 0.0,
        different_precision=(
            different_true_positive / predicted_different if predicted_different else 0.0
        ),
        different_recall=(
            different_true_positive / true_different if true_different else 0.0
        ),
    )


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("invalid binomial counts")
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    half = z * sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def leave_one_target_out(
    observations: Sequence[Observation], *, predicate=conservative_vote, **kwargs
) -> tuple[Summary, ...]:
    targets = sorted({observation.target_id for observation in observations})
    summaries = []
    for target in targets:
        retained = [observation for observation in observations if observation.target_id != target]
        summaries.append(summarize(pair_decisions(retained, predicate=predicate, **kwargs)))
    return tuple(summaries)


def leave_one_case_out(
    observations: Sequence[Observation], *, predicate=conservative_vote, **kwargs
) -> tuple[Summary, ...]:
    """Return case-block robustness summaries.

    A case is one public measurement record and its probe/control observations.
    Case blocking complements target blocking when multiple records carry the
    same normalized target.
    """
    cases = sorted({observation.case_id for observation in observations})
    summaries = []
    for case in cases:
        retained = [observation for observation in observations if observation.case_id != case]
        summaries.append(summarize(pair_decisions(retained, predicate=predicate, **kwargs)))
    return tuple(summaries)
