"""Evidence-replicating service identity reconciliation.

Replicas store immutable, source-indexed evidence cells. State joins are
order-independent; identity is a deterministic, negative-safe read view. The
implementation uses only the Python standard library.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
import heapq
import json
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


Relation = Tuple[str, str]


def relation(a: str, b: str) -> Relation:
    """Return a canonical unordered relation."""
    if a == b:
        raise ValueError("a relation requires distinct handles")
    return (a, b) if a < b else (b, a)


class Vote(str, Enum):
    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class EvidenceCell:
    """One source's immutable vote for one relation in one epoch."""

    left: str
    right: str
    epoch: int
    source: str
    vote: Vote
    reason: str

    def __post_init__(self) -> None:
        if not all(isinstance(x, str) and x for x in (self.left, self.right)):
            raise ValueError("cell handles must be non-empty strings")
        if self.left >= self.right:
            raise ValueError("cell handles must be in canonical order")
        if type(self.epoch) is not int or self.epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.vote, Vote) or not isinstance(self.reason, str):
            raise ValueError("cell vote or reason has an invalid type")

    @property
    def pair(self) -> Relation:
        return (self.left, self.right)

    def to_dict(self) -> Dict[str, object]:
        return {
            "left": self.left,
            "right": self.right,
            "epoch": self.epoch,
            "source": self.source,
            "vote": self.vote.value,
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(value: Mapping[str, object]) -> "EvidenceCell":
        if not isinstance(value, Mapping):
            raise ValueError("cell must be an object")
        required = {"left", "right", "epoch", "source", "vote"}
        if not required.issubset(value):
            raise ValueError("cell is missing required fields")
        if not isinstance(value["vote"], str):
            raise ValueError("vote must be a string")
        return EvidenceCell(
            left=value["left"], right=value["right"], epoch=value["epoch"],
            source=value["source"], vote=Vote(value["vote"]),
            reason=value.get("reason", ""),
        )


@dataclass(frozen=True)
class EdgeDecision:
    pair: Relation
    epoch: int
    vote: Vote
    cells: Tuple[EvidenceCell, ...]
    same_count: int
    different_count: int
    sealed: bool


@dataclass(frozen=True)
class PartitionView:
    components: Tuple[Tuple[str, ...], ...]
    component_of: Mapping[str, int]
    accepted_same_edges: Tuple[Relation, ...]
    rejected_same_edges: Tuple[Relation, ...]
    different_edges: Tuple[Relation, ...]
    unknown_edges: Tuple[Relation, ...]
    decisions: Mapping[Relation, EdgeDecision]


class Replica:
    """Evidence replica with deterministic read-time materialization.

    A source may emit at most one cell for a relation and epoch. An epoch is
    sealed only after every registered source has supplied a cell. Unsealed
    evidence is retained but cannot authorize a merge.

    The ordinary state is a grow-only cell set. Acknowledgement-gated
    compaction additionally advances a monotone per-relation floor. Cells below
    that floor are obsolete and cannot be resurrected by a later join.
    """

    def __init__(
        self,
        node_id: str,
        sources: Sequence[str],
        threshold: int = 2,
        handles: Optional[Iterable[str]] = None,
    ):
        if not isinstance(node_id, str):
            raise ValueError("node identifier must be a string")
        if not sources or not all(isinstance(x, str) and x for x in sources):
            raise ValueError("sources must be non-empty strings")
        canonical_sources = tuple(sorted(sources))
        if len(set(canonical_sources)) != len(canonical_sources):
            raise ValueError("source identifiers must be unique")
        if any(not source for source in canonical_sources):
            raise ValueError("source identifiers must be non-empty")
        if type(threshold) is not int or threshold < 1 or threshold > len(canonical_sources):
            raise ValueError("threshold must be between one and source count")
        self.node_id = node_id
        self.sources = canonical_sources
        self.threshold = threshold
        self._handles: Set[str] = set()
        self.register_handles(handles or ())
        self._cells: Set[EvidenceCell] = set()
        self._by_key: Dict[Tuple[Relation, int, str], EvidenceCell] = {}
        self._stable_floor: Dict[Relation, int] = defaultdict(lambda: -1)

    def __len__(self) -> int:
        return len(self._cells)

    @property
    def cells(self) -> Tuple[EvidenceCell, ...]:
        return tuple(sorted(self._cells))

    @property
    def handles(self) -> Tuple[str, ...]:
        return tuple(sorted(self._handles))

    @property
    def stable_floors(self) -> Mapping[Relation, int]:
        return {
            pair: floor
            for pair, floor in sorted(self._stable_floor.items())
            if floor >= 0
        }

    def register_handles(self, handles: Iterable[str]) -> None:
        incoming = tuple(handles)
        if not all(isinstance(handle, str) and handle for handle in incoming):
            raise ValueError("handle identifiers must be non-empty strings")
        self._handles.update(incoming)

    def _replace_cells(self, cells: Iterable[EvidenceCell]) -> None:
        by_key: Dict[Tuple[Relation, int, str], EvidenceCell] = {}
        retained: Set[EvidenceCell] = set()
        for cell in cells:
            key = (cell.pair, cell.epoch, cell.source)
            prior = by_key.get(key)
            if prior is not None and prior != cell:
                raise ValueError(
                    "source equivocation is outside the model: conflicting cells "
                    f"for {key!r}"
                )
            by_key[key] = cell
            retained.add(cell)
        self._cells = retained
        self._by_key = by_key

    def add(self, cell: EvidenceCell) -> bool:
        if cell.source not in self.sources:
            raise ValueError(f"unregistered source: {cell.source}")
        self.register_handles((cell.left, cell.right))
        if cell.epoch < self._stable_floor[cell.pair]:
            # The globally acknowledged floor dominates this historical cell.
            return False
        key = (cell.pair, cell.epoch, cell.source)
        prior = self._by_key.get(key)
        if prior is not None and prior != cell:
            raise ValueError(
                "source equivocation is outside the model: conflicting cells "
                f"for {key!r}"
            )
        if prior is not None:
            return False
        self._cells.add(cell)
        self._by_key[key] = cell
        return True

    def join(self, other: "Replica") -> int:
        """Join cells and acknowledged floors.

        Floors merge by pointwise maximum. The joined cell set is union filtered
        by the resulting floors, so compacted history cannot be resurrected.
        """
        if self.sources != other.sources or self.threshold != other.threshold:
            raise ValueError("replica configurations differ")
        target_handles = self._handles | other._handles
        target_floors: Dict[Relation, int] = defaultdict(lambda: -1)
        for pair in set(self._stable_floor) | set(other._stable_floor):
            target_floors[pair] = max(
                self._stable_floor[pair], other._stable_floor[pair]
            )

        joined: List[EvidenceCell] = []
        own_keys = set(self._by_key)
        inserted = 0
        for cell in sorted(self._cells | other._cells):
            if cell.epoch < target_floors[cell.pair]:
                continue
            joined.append(cell)
            key = (cell.pair, cell.epoch, cell.source)
            inserted += int(key not in own_keys and cell in other._cells)
        self._replace_cells(joined)
        self._handles = target_handles
        self._stable_floor = defaultdict(lambda: -1, target_floors)
        return inserted

    def serialized_bytes(self) -> int:
        return len(
            json.dumps(
                self.export_state(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )

    def relation_epochs(self) -> Dict[Relation, Dict[int, Dict[str, EvidenceCell]]]:
        grouped: Dict[Relation, Dict[int, Dict[str, EvidenceCell]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for cell in self._cells:
            grouped[cell.pair][cell.epoch][cell.source] = cell
        return grouped

    def highest_sealed_epoch(self, pair: Relation) -> Optional[int]:
        epochs = self.relation_epochs().get(pair, {})
        complete = [
            epoch
            for epoch, source_cells in epochs.items()
            if all(source in source_cells for source in self.sources)
        ]
        return max(complete) if complete else None

    def decisions(self) -> Dict[Relation, EdgeDecision]:
        result: Dict[Relation, EdgeDecision] = {}
        for pair, epochs in self.relation_epochs().items():
            complete = [
                epoch
                for epoch, source_cells in epochs.items()
                if all(source in source_cells for source in self.sources)
            ]
            if not complete:
                latest_epoch = max(epochs)
                cells = tuple(sorted(epochs[latest_epoch].values()))
                result[pair] = EdgeDecision(
                    pair=pair,
                    epoch=latest_epoch,
                    vote=Vote.UNKNOWN,
                    cells=cells,
                    same_count=sum(cell.vote == Vote.SAME for cell in cells),
                    different_count=sum(cell.vote == Vote.DIFFERENT for cell in cells),
                    sealed=False,
                )
                continue
            epoch = max(complete)
            cells = tuple(sorted(epochs[epoch].values()))
            same_count = sum(cell.vote == Vote.SAME for cell in cells)
            different_count = sum(cell.vote == Vote.DIFFERENT for cell in cells)
            if different_count:
                vote = Vote.DIFFERENT
            elif same_count >= self.threshold:
                vote = Vote.SAME
            else:
                vote = Vote.UNKNOWN
            result[pair] = EdgeDecision(
                pair=pair,
                epoch=epoch,
                vote=vote,
                cells=cells,
                same_count=same_count,
                different_count=different_count,
                sealed=True,
            )
        return result

    def compact(
        self, stable_epochs: Mapping[Relation, int], retain_pending: int = 2
    ) -> int:
        """Discard acknowledged history without dropping pending epochs.

        ``stable_epochs[p]`` is valid only after every active replica has sealed
        that floor. A successful call retains the floor and *all* newer epochs.
        It refuses, without mutation, when the caller's pending-epoch bound would
        be exceeded, a floor regresses, a floor is absent, or a floor is unsealed.
        Relations with no acknowledged floor retain all evidence.
        """
        if retain_pending < 0:
            raise ValueError("retain_pending must be non-negative")
        grouped = self.relation_epochs()
        unknown_pairs = set(stable_epochs) - set(grouped)
        if unknown_pairs:
            raise ValueError(f"stable floor supplied for unknown relation: {unknown_pairs!r}")

        target_floors: Dict[Relation, int] = defaultdict(lambda: -1)
        keep_epochs_by_pair: Dict[Relation, Set[int]] = {}
        for pair, epochs in grouped.items():
            current = self._stable_floor[pair]
            requested = stable_epochs.get(pair, current)
            if requested < current:
                raise ValueError(
                    f"stable floor regression for {pair!r}: {requested} < {current}"
                )
            target_floors[pair] = requested
            if requested < 0:
                keep_epochs_by_pair[pair] = set(epochs)
                continue
            if requested not in epochs:
                raise ValueError(
                    f"stable floor {requested} is not retained for relation {pair!r}"
                )
            floor_cells = epochs[requested]
            if not all(source in floor_cells for source in self.sources):
                raise ValueError(
                    f"stable floor {requested} is not sealed for relation {pair!r}"
                )
            newer = {epoch for epoch in epochs if epoch > requested}
            if len(newer) > retain_pending:
                raise ValueError(
                    f"relation {pair!r} has {len(newer)} newer epochs, exceeding "
                    f"retain_pending={retain_pending}"
                )
            keep_epochs_by_pair[pair] = {requested} | newer

        keep: Set[EvidenceCell] = set()
        for pair, epochs in grouped.items():
            for epoch in keep_epochs_by_pair[pair]:
                keep.update(epochs[epoch].values())

        removed = len(self._cells) - len(keep)
        self._replace_cells(keep)
        self._stable_floor = defaultdict(lambda: -1, target_floors)
        return removed

    def materialize(self, handles: Optional[Iterable[str]] = None) -> PartitionView:
        """Derive the canonical partition using a component-level veto index."""
        return self._materialize(handles, indexed=True)

    def materialize_reference(self, handles: Optional[Iterable[str]] = None) -> PartitionView:
        """Preserved member-scanning implementation for differential evaluation."""
        return self._materialize(handles, indexed=False)

    def _materialize(self, handles: Optional[Iterable[str]], indexed: bool) -> PartitionView:
        decisions = self.decisions()
        all_handles: Set[str] = set(self._handles)
        all_handles.update(handles or ())
        for left, right in decisions:
            all_handles.add(left)
            all_handles.add(right)

        parent: Dict[str, str] = {handle: handle for handle in all_handles}
        members: Dict[str, Set[str]] = {handle: {handle} for handle in all_handles}
        negative_neighbors: Dict[str, Set[str]] = defaultdict(set)

        different_edges = tuple(
            sorted(
                pair
                for pair, decision in decisions.items()
                if decision.vote == Vote.DIFFERENT
            )
        )
        for left, right in different_edges:
            negative_neighbors[left].add(right)
            negative_neighbors[right].add(left)

        # blocked[C] is the union of original negative neighbors of C's members.
        # Entries are original handle names, not changing union-find roots.
        blocked = {handle: set(negative_neighbors[handle]) for handle in all_handles} if indexed else {}

        def find(handle: str) -> str:
            while parent[handle] != handle:
                parent[handle] = parent[parent[handle]]
                handle = parent[handle]
            return handle

        def can_union(left: str, right: str) -> bool:
            root_left, root_right = find(left), find(right)
            if root_left == root_right:
                return True
            left_members, right_members = members[root_left], members[root_right]
            if indexed:
                # Both orientations are equivalent; choose the cheaper upper bound.
                if min(len(blocked[root_left]), len(right_members)) <= min(len(blocked[root_right]), len(left_members)):
                    return blocked[root_left].isdisjoint(right_members)
                return blocked[root_right].isdisjoint(left_members)
            small, large = (
                (left_members, right_members)
                if len(left_members) <= len(right_members)
                else (right_members, left_members)
            )
            return not any(negative_neighbors[node] & large for node in small)

        def union(left: str, right: str) -> bool:
            root_left, root_right = find(left), find(right)
            if root_left == root_right:
                return True
            if not can_union(root_left, root_right):
                return False
            if len(members[root_left]) < len(members[root_right]) or (
                len(members[root_left]) == len(members[root_right])
                and root_left > root_right
            ):
                root_left, root_right = root_right, root_left
            parent[root_right] = root_left
            members[root_left].update(members.pop(root_right))
            if indexed:
                blocked[root_left].update(blocked.pop(root_right))
            return True

        accepted: List[Relation] = []
        rejected: List[Relation] = []
        for left, right in sorted(
            pair for pair, decision in decisions.items() if decision.vote == Vote.SAME
        ):
            if union(left, right):
                accepted.append((left, right))
            else:
                rejected.append((left, right))

        components = sorted(
            (tuple(sorted(group)) for group in members.values()),
            key=lambda group: group[0],
        )
        component_of: Dict[str, int] = {}
        for index, group in enumerate(components):
            for handle in group:
                component_of[handle] = index
        unknown_edges = tuple(
            sorted(
                pair
                for pair, decision in decisions.items()
                if decision.vote == Vote.UNKNOWN
            )
        )
        return PartitionView(
            components=tuple(components),
            component_of=component_of,
            accepted_same_edges=tuple(accepted),
            rejected_same_edges=tuple(rejected),
            different_edges=different_edges,
            unknown_edges=unknown_edges,
            decisions=decisions,
        )

    @staticmethod
    def _component_separators(view: PartitionView) -> Set[Tuple[int, int]]:
        separators: Set[Tuple[int, int]] = set()
        for left, right in view.different_edges:
            component_left = view.component_of[left]
            component_right = view.component_of[right]
            if component_left != component_right:
                separators.add(
                    (min(component_left, component_right), max(component_left, component_right))
                )
        return separators

    def certificate(self, left: str, right: str) -> Dict[str, object]:
        if left not in self._handles or right not in self._handles:
            raise ValueError("certificate query handles must be registered")
        query_pair = relation(left, right)
        view = self.materialize()
        left_component = view.component_of[left]
        right_component = view.component_of[right]

        if left_component == right_component:
            adjacency: Dict[str, List[str]] = defaultdict(list)
            for a, b in view.accepted_same_edges:
                adjacency[a].append(b)
                adjacency[b].append(a)
            queue = deque([left])
            previous: Dict[str, Optional[str]] = {left: None}
            while queue and right not in previous:
                node = queue.popleft()
                for neighbor in sorted(adjacency[node]):
                    if neighbor not in previous:
                        previous[neighbor] = node
                        queue.append(neighbor)
            if right not in previous:
                raise RuntimeError("component lacks an accepted-edge path")
            path: List[str] = []
            node: Optional[str] = right
            while node is not None:
                path.append(node)
                node = previous[node]
            path.reverse()
            support = []
            for edge in [relation(a, b) for a, b in zip(path, path[1:])]:
                decision = view.decisions[edge]
                support.append(
                    {
                        "pair": list(edge),
                        "epoch": decision.epoch,
                        "cells": [
                            cell.to_dict()
                            for cell in decision.cells
                            if cell.vote == Vote.SAME
                        ],
                    }
                )
            return {
                "kind": "same",
                "query": [left, right],
                "path": path,
                "support": support,
            }

        left_members = set(view.components[left_component])
        right_members = set(view.components[right_component])
        for edge in view.different_edges:
            a, b = edge
            if (a in left_members and b in right_members) or (
                b in left_members and a in right_members
            ):
                decision = view.decisions[edge]
                negative = next(
                    cell for cell in decision.cells if cell.vote == Vote.DIFFERENT
                )
                return {
                    "kind": "different",
                    "query": [left, right],
                    "separator_pair": list(edge),
                    "cell": negative.to_dict(),
                }

        # Ambiguity is a globally feasible authorization plan over the current
        # quotient view.  The plan may use only UNKNOWN candidate relations (or
        # one clearly marked hypothetical direct relation).  Its component path
        # must be compatible with *every* selected negative separator, not just
        # separators adjacent to each step.  Authorizing all listed steps can
        # therefore merge the entire path without violating the frozen negative
        # set.  The search minimizes changed or supplied source slots, then edge
        # count, then a deterministic relation/component ordering.
        quotient: Dict[
            int,
            List[
                Tuple[
                    int,
                    int,
                    Relation,
                    Tuple[str, ...],
                    Tuple[str, ...],
                    Tuple[str, ...],
                    Tuple[str, ...],
                    Tuple[str, ...],
                    bool,
                    Optional[int],
                    bool,
                ]
            ],
        ] = defaultdict(list)
        source_set = set(self.sources)
        separators = self._component_separators(view)

        def add_unknown_edge(
            component_a: int,
            component_b: int,
            edge: Relation,
            decision: Optional[EdgeDecision],
        ) -> None:
            if component_a == component_b:
                return
            component_pair = (
                min(component_a, component_b), max(component_a, component_b)
            )
            if component_pair in separators:
                return
            if decision is None:
                missing_sources = tuple(sorted(self.sources))
                metadata = (
                    len(missing_sources),
                    edge,
                    missing_sources,
                    tuple(),
                    missing_sources,
                    tuple(),
                    tuple(),
                    False,
                    None,
                    False,
                )
            else:
                same_sources = tuple(
                    sorted(
                        cell.source
                        for cell in decision.cells
                        if cell.vote == Vote.SAME
                    )
                )
                different_sources = tuple(
                    sorted(
                        cell.source
                        for cell in decision.cells
                        if cell.vote == Vote.DIFFERENT
                    )
                )
                unknown_sources = tuple(
                    sorted(
                        cell.source
                        for cell in decision.cells
                        if cell.vote == Vote.UNKNOWN
                    )
                )
                present_sources = {cell.source for cell in decision.cells}
                missing_sources = tuple(sorted(source_set - present_sources))

                # A future sealed vector authorizes SAME only after every missing
                # slot is supplied, every currently DIFFERENT slot is revised,
                # and enough UNKNOWN slots are revised to reach q positives.
                # Unchanged source positions can repeat their current value in
                # that future vector and are not counted as interventions.
                mandatory = list(missing_sources) + list(different_sources)
                extra_needed = max(
                    0,
                    self.threshold
                    - len(same_sources)
                    - len(missing_sources)
                    - len(different_sources),
                )
                extra_unknown = list(unknown_sources[:extra_needed])
                gap_sources = tuple(mandatory + extra_unknown)
                metadata = (
                    len(gap_sources),
                    edge,
                    gap_sources,
                    same_sources,
                    missing_sources,
                    different_sources,
                    unknown_sources,
                    True,
                    decision.epoch,
                    decision.sealed,
                )
            quotient[component_a].append((component_b, *metadata))
            quotient[component_b].append((component_a, *metadata))

        for edge in view.unknown_edges:
            add_unknown_edge(
                view.component_of[edge[0]],
                view.component_of[edge[1]],
                edge,
                view.decisions[edge],
            )

        # If the exact query relation is not an observed UNKNOWN candidate, add
        # a direct hypothetical relation.  Because closure is required, all
        # source slots are missing; this also supplies a finite incumbent that
        # bounds the exact path search by |Sources|.
        query_decision = view.decisions.get(query_pair)
        if query_decision is None or query_decision.vote != Vote.UNKNOWN:
            add_unknown_edge(
                left_component, right_component, query_pair, None
            )

        def metadata_key(item: Tuple[object, ...]) -> Tuple[object, ...]:
            return (
                item[0], item[2], item[3], item[4], item[5], item[6],
                item[7], item[8], -1 if item[9] is None else item[9], item[10]
            )

        for node in quotient:
            quotient[node].sort(key=metadata_key)

        def compatible(path: Tuple[int, ...], neighbor: int) -> bool:
            return all(
                (min(component, neighbor), max(component, neighbor))
                not in separators
                for component in path
                if component != neighbor
            )

        def make_step(
            source_component: int,
            target_component: int,
            item: Tuple[object, ...],
        ) -> Dict[str, object]:
            (
                _,
                edge_cost,
                edge,
                gap_sources,
                same_sources,
                missing_sources,
                different_sources,
                unknown_sources,
                observed,
                epoch,
                sealed,
            ) = item
            return {
                "pair": list(edge),
                "from_component": source_component,
                "to_component": target_component,
                "observed": observed,
                "epoch": epoch,
                "sealed": sealed,
                "same_sources": list(same_sources),
                "missing_sources": list(missing_sources),
                "different_sources": list(different_sources),
                "unknown_sources": list(unknown_sources),
                "authorization_gap": edge_cost,
                "gap_sources": list(gap_sources),
            }

        def objective(
            cost: int,
            path: Tuple[int, ...],
            steps: Tuple[Dict[str, object], ...],
        ) -> Tuple[object, ...]:
            return (
                cost,
                len(steps),
                tuple(tuple(step["pair"]) for step in steps),
                path,
            )

        # Establish the best direct plan first.  It bounds all useful indirect
        # exploration because every edge has strictly positive intervention
        # cost and an equal-cost multi-edge path cannot beat a one-edge plan.
        best_objective: Optional[Tuple[object, ...]] = None
        best_path: Optional[Tuple[int, ...]] = None
        best_steps: Optional[Tuple[Dict[str, object], ...]] = None
        for item in quotient[left_component]:
            neighbor, edge_cost = item[0], item[1]
            if neighbor != right_component or not compatible((left_component,), neighbor):
                continue
            step = make_step(left_component, neighbor, item)
            candidate_path = (left_component, right_component)
            candidate_steps = (step,)
            candidate = objective(edge_cost, candidate_path, candidate_steps)
            if best_objective is None or candidate < best_objective:
                best_objective = candidate
                best_path = candidate_path
                best_steps = candidate_steps

        if best_objective is None:
            raise RuntimeError("ambiguity graph lacks a direct bounded fallback")

        def search(
            node: int,
            path: Tuple[int, ...],
            cost: int,
            steps: Tuple[Dict[str, object], ...],
        ) -> None:
            nonlocal best_objective, best_path, best_steps
            assert best_objective is not None
            for item in quotient[node]:
                neighbor, edge_cost = item[0], item[1]
                if neighbor in path or not compatible(path, neighbor):
                    continue
                new_cost = cost + edge_cost
                # Positive edge costs mean a nonterminal prefix at or above the
                # incumbent can never improve it.
                if neighbor != right_component and new_cost >= best_objective[0]:
                    continue
                step = make_step(node, neighbor, item)
                new_steps = steps + (step,)
                new_path = path + (neighbor,)
                if neighbor == right_component:
                    candidate = objective(new_cost, new_path, new_steps)
                    if candidate < best_objective:
                        best_objective = candidate
                        best_path = new_path
                        best_steps = new_steps
                    continue
                search(neighbor, new_path, new_cost, new_steps)

        search(left_component, (left_component,), 0, tuple())
        assert best_objective is not None and best_path is not None and best_steps is not None
        return {
            "kind": "ambiguous",
            "query": [left, right],
            "globally_sufficient": True,
            "authorization_gap": best_objective[0],
            "edge_count": best_objective[1],
            "component_path": list(best_path),
            "steps": list(best_steps),
        }

    def export_state(self) -> Dict[str, object]:
        return {
            "node_id": self.node_id,
            "sources": list(self.sources),
            "threshold": self.threshold,
            "handles": list(self.handles),
            "stable_floors": [
                {"left": pair[0], "right": pair[1], "epoch": floor}
                for pair, floor in self.stable_floors.items()
            ],
            "cells": [cell.to_dict() for cell in sorted(self._cells)],
        }

    @staticmethod
    def import_state(value: Mapping[str, object]) -> "Replica":
        """Validate a complete serialized state without coercion or mutation.

        Repeated cells belong in an idempotent delivery operation, not in a
        serialized state. Floors must retain their complete source vector.
        """
        if not isinstance(value, Mapping):
            raise ValueError("state must be an object")
        for field in ("sources", "handles", "cells"):
            if not isinstance(value.get(field), list):
                raise ValueError(f"state {field} must be a list")
        if "node_id" not in value or "threshold" not in value:
            raise ValueError("state is missing configuration fields")
        raw_handles = value["handles"]
        if not all(isinstance(h, str) and h for h in raw_handles):
            raise ValueError("state handles must be non-empty strings")
        if len(set(raw_handles)) != len(raw_handles):
            raise ValueError("state handles must be unique")
        replica = Replica(value["node_id"], value["sources"], value["threshold"], raw_handles)
        keys = set()
        for raw in value["cells"]:
            cell = EvidenceCell.from_dict(raw)
            if cell.left not in replica._handles or cell.right not in replica._handles:
                raise ValueError("cell references an unregistered handle")
            key = (cell.pair, cell.epoch, cell.source)
            if key in keys:
                raise ValueError("duplicate or equivocating cell key")
            keys.add(key)
            replica.add(cell)
        raw_floors = value.get("stable_floors", [])
        if not isinstance(raw_floors, list):
            raise ValueError("stable_floors must be a list")
        floors: Dict[Relation, int] = {}
        grouped = replica.relation_epochs()
        for raw in raw_floors:
            if not isinstance(raw, Mapping):
                raise ValueError("stable floor entries must be objects")
            left, right, floor = raw.get("left"), raw.get("right"), raw.get("epoch")
            if not all(isinstance(x, str) and x for x in (left, right)) or left >= right:
                raise ValueError("stable floor handles must be canonical strings")
            pair = (left, right)
            if pair in floors or type(floor) is not int or floor < 0:
                raise ValueError("invalid or duplicate stable floor")
            if floor not in grouped.get(pair, {}):
                raise ValueError("stable floor is not retained")
            if set(grouped[pair][floor]) != set(replica.sources):
                raise ValueError("stable floor is not sealed")
            if any(epoch < floor for epoch in grouped[pair]):
                raise ValueError("state retains cells below stable floor")
            floors[pair] = floor
        replica._stable_floor = defaultdict(lambda: -1, floors)
        return replica
