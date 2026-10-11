"""Mutex Watershed comparator and controlled local ablations.

Algorithm 2 and the active-mutex-edge incidence sets of Section 3.4 in:
Wolf et al., The Mutex Watershed: Efficient, Parameter-Free Image Partitioning,
ECCV 2018, pp. 571--587, doi:10.1007/978-3-030-01225-0_34.
This is a local reimplementation, not the authors' optimized image code.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable

from .model import EdgeDecision, PartitionView, Relation, Replica, Vote


@dataclass(frozen=True)
class SignedEdge:
    pair: Relation
    vote: Vote
    weight: float

    def __post_init__(self):
        if (len(self.pair) != 2 or not all(isinstance(h, str) and h for h in self.pair)
                or self.pair[0] >= self.pair[1]):
            raise ValueError("edges require canonical distinct handle pairs")
        if self.vote not in (Vote.SAME, Vote.DIFFERENT):
            raise ValueError("MWS edges must be attractive or repulsive")
        if (type(self.weight) not in (int, float) or not math.isfinite(self.weight)
                or self.weight < 0):
            raise ValueError("edge strength must be finite and nonnegative")


@dataclass(frozen=True)
class MutexResult:
    components: tuple[tuple[str, ...], ...]
    positive_forest: tuple[Relation, ...]
    redundant_positive: tuple[Relation, ...]
    rejected_positive: tuple[Relation, ...]
    active_negative: tuple[Relation, ...]
    ignored_negative: tuple[Relation, ...]


def mutex_watershed(handles: Iterable[str], edges: Iterable[SignedEdge]) -> MutexResult:
    """Global descending-strength MWS; ties are negative-first then lexical.

    Each live component stores IDs of incident active negative edges. Two
    components are mutex iff their ID sets intersect. IDs are inherited on
    union. A negative arriving inside a component is ignored, not installed.
    """
    names = set(handles)
    if not all(isinstance(h, str) and h for h in names):
        raise ValueError("handles must be nonempty strings")
    ordered = sorted(edges, key=lambda e: (
        -e.weight, 0 if e.vote == Vote.DIFFERENT else 1, e.pair))
    if len({(e.pair, e.vote) for e in ordered}) != len(ordered):
        raise ValueError("duplicate signed edge")
    if any(h not in names for e in ordered for h in e.pair):
        raise ValueError("edge has an unregistered handle")
    parent = {h: h for h in names}
    members = {h: {h} for h in names}
    incident = {h: set() for h in names}
    forest, redundant, rejected, active, ignored = [], [], [], [], []

    def find(h):
        while parent[h] != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h

    for edge_id, edge in enumerate(ordered):
        a, b = map(find, edge.pair)
        if edge.vote == Vote.DIFFERENT:
            if a == b:
                ignored.append(edge.pair)
            else:
                active.append(edge.pair)
                incident[a].add(edge_id)
                incident[b].add(edge_id)
        elif a == b:
            redundant.append(edge.pair)
        elif not incident[a].isdisjoint(incident[b]):
            rejected.append(edge.pair)
        else:
            if len(members[a]) < len(members[b]) or (len(members[a]) == len(members[b]) and a > b):
                a, b = b, a
            parent[b] = a
            members[a].update(members.pop(b))
            incident[a].update(incident.pop(b))
            forest.append(edge.pair)
    return MutexResult(
        tuple(sorted(tuple(sorted(v)) for v in members.values())),
        tuple(forest), tuple(redundant), tuple(rejected), tuple(active), tuple(ignored))


def _view(components, accepted, rejected, decisions) -> PartitionView:
    return PartitionView(
        components=components,
        component_of={h: i for i, group in enumerate(components) for h in group},
        accepted_same_edges=tuple(sorted(accepted)),
        rejected_same_edges=tuple(sorted(rejected)),
        different_edges=tuple(sorted(p for p, d in decisions.items() if d.vote == Vote.DIFFERENT)),
        unknown_edges=tuple(sorted(p for p, d in decisions.items() if d.vote == Vote.UNKNOWN)),
        decisions=decisions)


def priority_preserving_mws(replica: Replica, handles: Iterable[str] = ()) -> PartitionView:
    """CIE decisions, all negatives at strength 2, positives at strength 1.

    Equal positive strengths use CIE's lexical order. MWS activates only a
    forest; CIE also lists redundant internal positives as accepted support.
    The adapter restores those records without making any additional union.
    Decision selection and sorting are included in complete-call timings.
    """
    decisions = replica.decisions()
    result = mutex_watershed(set(replica.handles) | set(handles), (
        SignedEdge(p, d.vote, 2 if d.vote == Vote.DIFFERENT else 1)
        for p, d in decisions.items() if d.vote != Vote.UNKNOWN))
    return _view(result.components, result.positive_forest + result.redundant_positive,
                 result.rejected_positive, decisions)


def ablation_decisions(replica: Replica, relation_veto: bool) -> dict[Relation, EdgeDecision]:
    """Change only negative vote dominance; keep cells/epochs/closure/q fixed.

    Off treats negative votes as unknown during aggregation. This reproduces
    the historical negative-cell masking comparator without rewriting cells.
    It consequently removes selected negatives, making the component guard
    inert in that column of the factorial design.
    """
    decisions = replica.decisions()
    if relation_veto:
        return decisions
    return {p: replace(d, vote=(Vote.SAME if d.sealed and d.same_count >= replica.threshold
                               else Vote.UNKNOWN)) for p, d in decisions.items()}


def controlled_materialize(replica: Replica, *, relation_veto: bool = True,
                           component_veto: bool = True) -> PartitionView:
    """Explicit block-set comparator; unsafe ablations are never query services."""
    decisions = ablation_decisions(replica, relation_veto)
    blocks = [{h} for h in replica.handles]
    negative = [p for p, d in decisions.items() if d.vote == Vote.DIFFERENT]
    accepted, rejected = [], []
    for p, d in sorted(decisions.items()):
        if d.vote != Vote.SAME:
            continue
        a = next(g for g in blocks if p[0] in g)
        b = next(g for g in blocks if p[1] in g)
        if a is b:
            accepted.append(p)
            continue
        veto = component_veto and any(
            (x in a and y in b) or (y in a and x in b) for x, y in negative)
        if veto:
            rejected.append(p)
        else:
            blocks.remove(a)
            blocks.remove(b)
            blocks.append(a | b)
            accepted.append(p)
    components = tuple(sorted(tuple(sorted(g)) for g in blocks))
    return _view(components, accepted, rejected, decisions)


def violated_negatives(view: PartitionView, negatives: Iterable[Relation]) -> int:
    return sum(view.component_of[a] == view.component_of[b] for a, b in negatives)
