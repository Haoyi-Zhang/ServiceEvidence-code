"""Deliberately simple comparison baselines."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Tuple

from .model import EvidenceCell, PartitionView, Relation, Vote


class _DisjointSet:
    def __init__(self, handles: Iterable[str]):
        self.parent = {handle: handle for handle in handles}

    def find(self, handle: str) -> str:
        while self.parent[handle] != handle:
            self.parent[handle] = self.parent[self.parent[handle]]
            handle = self.parent[handle]
        return handle

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        if root_left > root_right:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left

    def components(self) -> Tuple[Tuple[str, ...], ...]:
        groups: Dict[str, List[str]] = defaultdict(list)
        for handle in self.parent:
            groups[self.find(handle)].append(handle)
        return tuple(sorted(tuple(sorted(group)) for group in groups.values()))


def _view(components: Tuple[Tuple[str, ...], ...]) -> PartitionView:
    component_of: Dict[str, int] = {}
    for index, component in enumerate(components):
        for handle in component:
            component_of[handle] = index
    return PartitionView(
        components=components,
        component_of=component_of,
        accepted_same_edges=(),
        rejected_same_edges=(),
        different_edges=(),
        unknown_edges=(),
        decisions={},
    )


def union_find(cells: Iterable[EvidenceCell], handles: Iterable[str]) -> PartitionView:
    """Merge forever on any positive cell."""
    dsu = _DisjointSet(handles)
    for cell in cells:
        if cell.vote == Vote.SAME:
            dsu.union(cell.left, cell.right)
    return _view(dsu.components())


def last_arrival(cells: Iterable[EvidenceCell], handles: Iterable[str]) -> PartitionView:
    """Trust the last delivered cell for each relation."""
    latest: Dict[Relation, EvidenceCell] = {}
    for cell in cells:
        latest[cell.pair] = cell
    dsu = _DisjointSet(handles)
    for pair, cell in sorted(latest.items()):
        if cell.vote == Vote.SAME:
            dsu.union(*pair)
    return _view(dsu.components())


def local_only(
    cells: Iterable[EvidenceCell], handles: Iterable[str], source: str
) -> PartitionView:
    """Use only one vantage's most recent cells."""
    latest: Dict[Relation, EvidenceCell] = {}
    for cell in cells:
        if cell.source != source:
            continue
        if cell.pair not in latest or cell.epoch >= latest[cell.pair].epoch:
            latest[cell.pair] = cell
    dsu = _DisjointSet(handles)
    for pair, cell in sorted(latest.items()):
        if cell.vote == Vote.SAME:
            dsu.union(*pair)
    return _view(dsu.components())


def name_only(handle_names: Mapping[str, str]) -> PartitionView:
    """Equate handles exposing the same normalized name token."""
    dsu = _DisjointSet(handle_names)
    representative: Dict[str, str] = {}
    for handle in sorted(handle_names):
        token = handle_names[handle]
        if token in representative:
            dsu.union(handle, representative[token])
        else:
            representative[token] = handle
    return _view(dsu.components())
