"""Deterministic generated multi-vantage Web-discovery workloads."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Dict, List, Mapping, Sequence, Tuple

from .model import EvidenceCell, Relation, Vote, relation


@dataclass(frozen=True)
class Workload:
    handles: Tuple[str, ...]
    truth: Mapping[str, str]
    names: Mapping[str, str]
    sources: Tuple[str, ...]
    cells: Tuple[EvidenceCell, ...]
    query_pairs: Tuple[Relation, ...]
    observation_count: int
    service_count: int
    epochs: int


def _cell(pair: Relation, epoch: int, source: str, vote: Vote, reason: str) -> EvidenceCell:
    return EvidenceCell(pair[0], pair[1], epoch, source, vote, reason)


def generate_workload(
    service_count: int,
    sources: Sequence[str] = ("v0", "v1", "v2", "v3", "v4"),
    handles_per_service: int = 3,
    epochs: int = 2,
    sparse_fraction: float = 0.08,
    collision_fraction: float = 0.20,
    seed: int = 7,
) -> Workload:
    """Generate aliases, redirects, endpoint reuse, stale views, and collisions.

    Epoch zero supplies an initially plausible view.  The final epoch represents
    a later deployment view.  Every source emits SAME, DIFFERENT, or UNKNOWN for
    every candidate relation, so completion of an epoch is explicit.
    """
    if service_count < 2:
        raise ValueError("at least two services are required")
    if handles_per_service < 2:
        raise ValueError("at least two handles per service are required")
    if epochs < 1:
        raise ValueError("at least one epoch is required")
    if not 0.0 <= sparse_fraction <= 1.0:
        raise ValueError("sparse_fraction must lie in [0,1]")
    if not 0.0 <= collision_fraction <= 1.0:
        raise ValueError("collision_fraction must lie in [0,1]")

    rng = random.Random(seed)
    source_ids = tuple(sources)
    handles: List[str] = []
    truth: Dict[str, str] = {}
    names: Dict[str, str] = {}
    service_handles: List[List[str]] = []

    for service_index in range(service_count):
        service = f"svc{service_index:05d}"
        group: List[str] = []
        for handle_index in range(handles_per_service):
            handle = f"h{service_index:05d}-{handle_index}"
            handles.append(handle)
            group.append(handle)
            truth[handle] = service
            if handle_index == 0:
                token = f"site-{service_index:05d}"
            elif handle_index == 1:
                token = f"site-{service_index:05d}-new"
            else:
                # Periodically reused front-door names create name-only
                # collisions across distinct services.
                bucket_count = max(2, service_count // 25 + 1)
                token = f"front-{service_index % bucket_count:04d}"
            names[handle] = token
        service_handles.append(group)

    candidate_truth: Dict[Relation, bool] = {}
    relation_reason: Dict[Relation, str] = {}

    # Each true service is connected by a short alias/redirect chain.
    for group in service_handles:
        for left, right in zip(group, group[1:]):
            pair = relation(left, right)
            candidate_truth[pair] = True
            relation_reason[pair] = "redirect-and-asset continuity"

    # Shared front doors connect distinct services.  Half receive an explicit
    # separator from a different source; half remain underdetermined.
    collision_count = max(1, int(service_count * collision_fraction))
    for offset in range(collision_count):
        left_service = offset % service_count
        right_service = (offset * 17 + 3) % service_count
        if left_service == right_service:
            right_service = (right_service + 1) % service_count
        pair = relation(
            service_handles[left_service][-1], service_handles[right_service][-1]
        )
        candidate_truth[pair] = False
        relation_reason[pair] = (
            "shared endpoint with incompatible redirect"
            if offset % 2 == 0
            else "shared endpoint without separator"
        )

    true_edges = sorted(pair for pair, is_same in candidate_truth.items() if is_same)
    sparse_count = min(int(len(true_edges) * sparse_fraction), len(true_edges))
    sparse_edges = set(rng.sample(true_edges, k=sparse_count)) if sparse_count else set()

    cells: List[EvidenceCell] = []
    for epoch in range(epochs):
        for pair, is_same in sorted(candidate_truth.items()):
            if is_same:
                positive_sources = {source_ids[0], source_ids[1]}
                if pair in sparse_edges and epoch == epochs - 1:
                    positive_sources = {source_ids[0]}
                for source in source_ids:
                    vote = Vote.SAME if source in positive_sources else Vote.UNKNOWN
                    reason = (
                        relation_reason[pair]
                        if vote == Vote.SAME
                        else "no discriminating observation"
                    )
                    cells.append(_cell(pair, epoch, source, vote, reason))
                continue

            has_separator = "incompatible" in relation_reason[pair]
            for source_index, source in enumerate(source_ids):
                if has_separator and source_index < 2:
                    vote = Vote.SAME
                    reason = (
                        "shared weak endpoint"
                        if epoch == 0
                        else "stale shared endpoint"
                    )
                elif has_separator and source_index == 2:
                    vote = Vote.DIFFERENT
                    reason = "incompatible redirect destinations"
                elif not has_separator and source_index == 0:
                    vote = Vote.SAME
                    reason = "single-vantage shared endpoint"
                else:
                    vote = Vote.UNKNOWN
                    reason = "no discriminating observation"
                cells.append(_cell(pair, epoch, source, vote, reason))

    queries: List[Relation] = []
    for group in service_handles[: min(20, service_count)]:
        queries.append(relation(group[0], group[-1]))
    for pair, is_same in sorted(candidate_truth.items()):
        if not is_same or pair in sparse_edges:
            queries.append(pair)
    for service_index in range(min(10, service_count - 1)):
        queries.append(
            relation(
                service_handles[service_index][0],
                service_handles[service_index + 1][0],
            )
        )

    return Workload(
        handles=tuple(handles),
        truth=truth,
        names=names,
        sources=source_ids,
        cells=tuple(cells),
        query_pairs=tuple(dict.fromkeys(queries)),
        observation_count=len(cells),
        service_count=service_count,
        epochs=epochs,
    )


def generate_to_observation_cap(
    cap: int = 80_000,
    sources: Sequence[str] = ("v0", "v1", "v2", "v3", "v4"),
    seed: int = 23,
) -> Workload:
    """Return the largest generated workload with at most ``cap`` cells."""
    if cap < len(sources) * 4:
        raise ValueError("cap is too small for a two-service workload")
    low, high = 2, max(3, cap // (len(sources) * 2))
    best = generate_workload(2, sources=sources, seed=seed)
    while low <= high:
        middle = (low + high) // 2
        candidate = generate_workload(middle, sources=sources, seed=seed)
        if candidate.observation_count <= cap:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best
