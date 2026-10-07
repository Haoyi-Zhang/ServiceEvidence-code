#!/usr/bin/env python3
"""Independent verifier for evidence states and query certificates.

This module intentionally imports none of the reconciliation implementation. It
validates the serialized schema, reconstructs sealing, decisions and
negative-safe materialization, and checks each certificate obligation directly.
"""

from __future__ import annotations

from collections import defaultdict
import argparse
import heapq
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping, Sequence, Set, Tuple


Pair = Tuple[str, str]
Decision = Tuple[str, int, Mapping[str, Mapping[str, object]], bool]


class VerificationError(ValueError):
    """Raised when a state or certificate fails a semantic obligation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def pair(left: str, right: str) -> Pair:
    require(isinstance(left, str) and isinstance(right, str), "pair endpoints must be strings")
    require(bool(left) and bool(right), "pair endpoints must be non-empty")
    require(left != right, "query endpoints must differ")
    return (left, right) if left < right else (right, left)


def strict_int(value: object, field: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer")
    return int(value)


def load(path: Path) -> Mapping[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, Mapping), f"{path.name} must contain a JSON object")
    return value


def validate_state(state: Mapping[str, object]) -> Mapping[str, object]:
    node_id = state.get("node_id")
    require(isinstance(node_id, str), "state node_id must be a string")

    raw_sources = state.get("sources")
    require(isinstance(raw_sources, list) and raw_sources, "state sources must be a non-empty list")
    require(all(isinstance(item, str) and item for item in raw_sources), "source identifiers must be non-empty strings")
    sources = tuple(sorted(raw_sources))
    require(len(set(sources)) == len(sources), "source identifiers must be unique")

    threshold = strict_int(state.get("threshold"), "threshold")
    require(1 <= threshold <= len(sources), "threshold must be between one and source count")

    raw_handles = state.get("handles")
    require(isinstance(raw_handles, list), "state handles must be a list")
    require(all(isinstance(item, str) and item for item in raw_handles), "handle identifiers must be non-empty strings")
    handles = tuple(sorted(raw_handles))
    require(len(set(handles)) == len(handles), "handle identifiers must be unique")
    handle_set = set(handles)

    raw_cells = state.get("cells")
    require(isinstance(raw_cells, list), "state cells must be a list")
    grouped: Dict[Pair, Dict[int, Dict[str, Mapping[str, object]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    keys: Set[Tuple[Pair, int, str]] = set()
    for index, raw in enumerate(raw_cells):
        require(isinstance(raw, Mapping), f"cell {index} must be an object")
        left, right = raw.get("left"), raw.get("right")
        require(isinstance(left, str) and isinstance(right, str), f"cell {index} handles must be strings")
        relation = pair(left, right)
        require((left, right) == relation, f"cell {index} handles are not canonical")
        require(left in handle_set and right in handle_set, f"cell {index} references an unregistered handle")
        epoch = strict_int(raw.get("epoch"), f"cell {index} epoch")
        require(epoch >= 0, f"cell {index} epoch must be non-negative")
        source = raw.get("source")
        require(isinstance(source, str) and source in sources, f"cell {index} source is not registered")
        vote = raw.get("vote")
        require(vote in {"same", "different", "unknown"}, f"cell {index} has an invalid vote")
        reason = raw.get("reason", "")
        require(isinstance(reason, str), f"cell {index} reason must be a string")
        key = (relation, epoch, source)
        require(key not in keys, f"duplicate or equivocating cell key: {key!r}")
        keys.add(key)
        grouped[relation][epoch][source] = raw

    floors: Dict[Pair, int] = {}
    raw_floors = state.get("stable_floors", [])
    require(isinstance(raw_floors, list), "state stable_floors must be a list")
    for index, raw in enumerate(raw_floors):
        require(isinstance(raw, Mapping), f"stable floor {index} must be an object")
        left, right = raw.get("left"), raw.get("right")
        require(isinstance(left, str) and isinstance(right, str), f"stable floor {index} handles must be strings")
        relation = pair(left, right)
        require((left, right) == relation, f"stable floor {index} handles are not canonical")
        floor = strict_int(raw.get("epoch"), f"stable floor {index} epoch")
        require(floor >= 0, f"stable floor {index} must be non-negative")
        require(relation not in floors, f"duplicate stable floor for {relation!r}")
        require(relation in grouped and floor in grouped[relation], f"stable floor {floor} is not retained for {relation!r}")
        require(all(source in grouped[relation][floor] for source in sources), f"stable floor {floor} is not sealed for {relation!r}")
        require(not any(epoch < floor for epoch in grouped[relation]), f"state retains cells below stable floor for {relation!r}")
        floors[relation] = floor

    return {
        "node_id": node_id,
        "sources": sources,
        "threshold": threshold,
        "handles": handles,
        "grouped": grouped,
        "stable_floors": floors,
    }


def decisions(normalized: Mapping[str, object]) -> Tuple[Tuple[str, ...], int, Dict[Pair, Decision]]:
    sources = normalized["sources"]
    threshold = normalized["threshold"]
    grouped = normalized["grouped"]
    require(isinstance(sources, tuple), "internal source normalization failed")
    require(isinstance(threshold, int), "internal threshold normalization failed")
    require(isinstance(grouped, Mapping), "internal grouping failed")

    result: Dict[Pair, Decision] = {}
    for relation, raw_epochs in grouped.items():
        require(isinstance(relation, tuple) and isinstance(raw_epochs, Mapping), "internal relation grouping failed")
        epochs = raw_epochs
        complete = [
            epoch
            for epoch, source_cells in epochs.items()
            if all(source in source_cells for source in sources)
        ]
        if not complete:
            epoch = max(epochs)
            result[relation] = ("unknown", epoch, epochs[epoch], False)
            continue
        epoch = max(complete)
        source_cells = epochs[epoch]
        votes = [str(cell["vote"]) for cell in source_cells.values()]
        if "different" in votes:
            vote = "different"
        elif votes.count("same") >= threshold:
            vote = "same"
        else:
            vote = "unknown"
        result[relation] = (vote, epoch, source_cells, True)
    return sources, threshold, result


def materialize(normalized: Mapping[str, object]):
    _, _, relation_decisions = decisions(normalized)
    handles = set(normalized["handles"])
    negative_neighbors: Dict[str, Set[str]] = defaultdict(set)
    different: Set[Pair] = set()
    for (left, right), (vote, _, _, _) in relation_decisions.items():
        if vote == "different":
            negative_neighbors[left].add(right)
            negative_neighbors[right].add(left)
            different.add((left, right))

    parent = {handle: handle for handle in handles}
    members = {handle: {handle} for handle in handles}

    def find(handle: str) -> str:
        while parent[handle] != handle:
            parent[handle] = parent[parent[handle]]
            handle = parent[handle]
        return handle

    def safe(left: str, right: str) -> bool:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return True
        left_members, right_members = members[root_left], members[root_right]
        small, large = (
            (left_members, right_members)
            if len(left_members) <= len(right_members)
            else (right_members, left_members)
        )
        return not any(negative_neighbors[node] & large for node in small)

    accepted: Set[Pair] = set()
    rejected: Set[Pair] = set()
    for left, right in sorted(
        relation
        for relation, decision in relation_decisions.items()
        if decision[0] == "same"
    ):
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            accepted.add((left, right))
            continue
        if not safe(root_left, root_right):
            rejected.add((left, right))
            continue
        if len(members[root_left]) < len(members[root_right]) or (
            len(members[root_left]) == len(members[root_right])
            and root_left > root_right
        ):
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left
        members[root_left].update(members.pop(root_right))
        accepted.add((left, right))

    components = sorted(
        (tuple(sorted(group)) for group in members.values()), key=lambda group: group[0]
    )
    component_of: Dict[str, int] = {}
    for index, group in enumerate(components):
        for handle in group:
            component_of[handle] = index
    return (
        relation_decisions,
        tuple(components),
        component_of,
        accepted,
        rejected,
        different,
    )


def canonical_cell(raw: Mapping[str, object]) -> Tuple[object, ...]:
    require(isinstance(raw, Mapping), "certificate cell must be an object")
    left, right = raw.get("left"), raw.get("right")
    require(isinstance(left, str) and isinstance(right, str), "certificate cell handles must be strings")
    relation = pair(left, right)
    require((left, right) == relation, "certificate cell handles are not canonical")
    epoch = strict_int(raw.get("epoch"), "certificate cell epoch")
    source = raw.get("source")
    vote = raw.get("vote")
    reason = raw.get("reason", "")
    require(isinstance(source, str), "certificate cell source must be a string")
    require(vote in {"same", "different", "unknown"}, "certificate cell vote is invalid")
    require(isinstance(reason, str), "certificate cell reason must be a string")
    return (left, right, epoch, source, vote, reason)




def canonical_cell_key(raw: object) -> Tuple[object, ...]:
    require(isinstance(raw, list) and len(raw) == 4, "certificate cell key must contain four fields")
    left, right, epoch_raw, source = raw
    require(isinstance(left, str) and isinstance(right, str), "certificate cell-key handles must be strings")
    relation = pair(left, right)
    require((left, right) == relation, "certificate cell-key handles are not canonical")
    epoch = strict_int(epoch_raw, "certificate cell-key epoch")
    require(epoch >= 0, "certificate cell-key epoch must be non-negative")
    require(isinstance(source, str) and source, "certificate cell-key source must be a non-empty string")
    return (left, right, epoch, source)


def state_cell_key(raw: Mapping[str, object]) -> Tuple[object, ...]:
    return (raw["left"], raw["right"], raw["epoch"], raw["source"])

def query_of(normalized: Mapping[str, object], certificate: Mapping[str, object]) -> Tuple[str, str]:
    raw_query = certificate.get("query")
    require(isinstance(raw_query, list) and len(raw_query) == 2, "certificate query must contain two handles")
    left, right = raw_query
    require(isinstance(left, str) and isinstance(right, str), "certificate query handles must be strings")
    pair(left, right)
    handles = set(normalized["handles"])
    require(left in handles and right in handles, "certificate query references an unregistered handle")
    return left, right


def component_members(component_of: Mapping[str, int], handle: str) -> Set[str]:
    index = component_of[handle]
    return {candidate for candidate, value in component_of.items() if value == index}


def crosses_components(edge: Pair, left_members: Set[str], right_members: Set[str]) -> bool:
    return (edge[0] in left_members and edge[1] in right_members) or (
        edge[1] in left_members and edge[0] in right_members
    )


def verify_same(normalized: Mapping[str, object], certificate: Mapping[str, object]) -> None:
    relation_decisions, _, component_of, accepted, _, _ = materialize(normalized)
    threshold = normalized["threshold"]
    query = query_of(normalized, certificate)
    raw_path = certificate.get("path")
    require(isinstance(raw_path, list) and all(isinstance(item, str) for item in raw_path), "same path must be a list of handles")
    path = list(raw_path)
    require(len(path) >= 2, "same path must contain at least two handles")
    require(path[0] == query[0] and path[-1] == query[1], "same path endpoints do not match the query")
    raw_support = certificate.get("support")
    require(isinstance(raw_support, list), "same support must be a list")
    require(len(raw_support) == len(path) - 1, "same support length does not match the path")
    for (left, right), item in zip(zip(path, path[1:]), raw_support):
        require(isinstance(item, Mapping), "same support entries must be objects")
        edge = pair(left, right)
        require(edge in accepted, f"same path edge {edge!r} was not accepted")
        vote, epoch, cells, sealed = relation_decisions[edge]
        require(sealed and vote == "same", f"same path edge {edge!r} is not a selected sealed SAME decision")
        raw_pair = item.get("pair")
        require(isinstance(raw_pair, list) and raw_pair == list(edge), f"same support pair mismatch for {edge!r}")
        require(strict_int(item.get("epoch"), "same support epoch") == epoch, f"same support epoch mismatch for {edge!r}")
        raw_cells = item.get("cells")
        raw_keys = item.get("cell_keys")
        require(
            (raw_cells is None) != (raw_keys is None),
            "same support must use exactly one evidence representation",
        )
        expected_cells = [
            cell for cell in cells.values() if str(cell["vote"]) == "same"
        ]
        if raw_cells is not None:
            require(isinstance(raw_cells, list), "same support cells must be a list")
            supplied = {canonical_cell(cell) for cell in raw_cells}
            require(len(supplied) == len(raw_cells), "same support contains duplicate cells")
            expected = {canonical_cell(cell) for cell in expected_cells}
            require(supplied == expected, f"same support cells do not match selected evidence for {edge!r}")
            supplied_count = len(supplied)
        else:
            require(isinstance(raw_keys, list), "same support cell_keys must be a list")
            supplied_keys = {canonical_cell_key(cell_key) for cell_key in raw_keys}
            require(len(supplied_keys) == len(raw_keys), "same support contains duplicate cell keys")
            expected_keys = {state_cell_key(cell) for cell in expected_cells}
            require(supplied_keys == expected_keys, f"same support cell keys do not match selected evidence for {edge!r}")
            supplied_count = len(supplied_keys)
        require(supplied_count >= threshold, f"same support for {edge!r} does not meet the threshold")
    require(component_of[query[0]] == component_of[query[1]], "same query endpoints are not in one component")


def verify_different(normalized: Mapping[str, object], certificate: Mapping[str, object]) -> None:
    relation_decisions, _, component_of, _, _, _ = materialize(normalized)
    query_left, query_right = query_of(normalized, certificate)
    raw_separator = certificate.get("separator_pair")
    require(isinstance(raw_separator, list) and len(raw_separator) == 2, "different separator_pair must contain two handles")
    require(all(isinstance(item, str) for item in raw_separator), "different separator handles must be strings")
    edge = pair(raw_separator[0], raw_separator[1])
    require(edge in relation_decisions, "different separator relation is absent from the state")
    vote, _, cells, sealed = relation_decisions[edge]
    require(sealed and vote == "different", "different separator is not a selected sealed DIFFERENT decision")
    raw_cell = certificate.get("cell")
    raw_key = certificate.get("cell_key")
    require(
        (raw_cell is None) != (raw_key is None),
        "different certificate must use exactly one evidence representation",
    )
    expected_cells = [
        cell for cell in cells.values() if str(cell["vote"]) == "different"
    ]
    if raw_cell is not None:
        supplied = canonical_cell(raw_cell)
        expected = {canonical_cell(cell) for cell in expected_cells}
        require(supplied in expected, "different certificate cell is not selected negative evidence")
    else:
        supplied_key = canonical_cell_key(raw_key)
        expected_keys = {state_cell_key(cell) for cell in expected_cells}
        require(supplied_key in expected_keys, "different certificate cell key is not selected negative evidence")
    require(component_of[query_left] != component_of[query_right], "different query endpoints are in one component")
    left_members = component_members(component_of, query_left)
    right_members = component_members(component_of, query_right)
    require(crosses_components(edge, left_members, right_members), "different separator does not cross the query components")


def component_separators(
    component_of: Mapping[str, int], different: Set[Pair]
) -> Set[Tuple[int, int]]:
    result: Set[Tuple[int, int]] = set()
    for left, right in different:
        component_left = component_of[left]
        component_right = component_of[right]
        if component_left != component_right:
            result.add((min(component_left, component_right), max(component_left, component_right)))
    return result


def minimal_ambiguity(
    normalized: Mapping[str, object], query_left: str, query_right: str
):
    """Reconstruct a checker-owned view for the standalone public helper."""
    reconstructed = materialize(normalized)
    return _minimal_ambiguity_prepared(
        normalized, query_left, query_right, reconstructed
    )


def _minimal_ambiguity_prepared(
    normalized: Mapping[str, object], query_left: str, query_right: str,
    reconstructed,
):
    """Enumerate globally negative-compatible authorization paths.

    This verifier intentionally uses an explicit stack rather than the service
    implementation's recursive search.  A direct hypothetical query relation
    always provides a finite incumbent, so only positive-cost paths no more
    expensive than |sources| need consideration.
    """
    sources, threshold = normalized["sources"], normalized["threshold"]
    relation_decisions, _, component_of, _, _, different = reconstructed
    left_component = component_of[query_left]
    right_component = component_of[query_right]
    separators = component_separators(component_of, different)
    graph: Dict[int, List[Tuple[object, ...]]] = defaultdict(list)
    source_set = set(sources)

    def add_edge(
        component_left: int,
        component_right: int,
        edge: Pair,
        decision: Optional[Tuple[object, ...]],
    ) -> None:
        if component_left == component_right:
            return
        component_pair = (
            min(component_left, component_right),
            max(component_left, component_right),
        )
        if component_pair in separators:
            return
        if decision is None:
            missing_sources = tuple(sorted(sources))
            metadata = (
                len(missing_sources), edge, missing_sources, tuple(),
                missing_sources, tuple(), tuple(), False, None, False,
            )
        else:
            vote, epoch, cells, sealed = decision
            require(vote == "unknown", "non-unknown relation entered ambiguity graph")
            same_sources = tuple(sorted(
                source for source, cell in cells.items()
                if str(cell["vote"]) == "same"
            ))
            different_sources = tuple(sorted(
                source for source, cell in cells.items()
                if str(cell["vote"]) == "different"
            ))
            unknown_sources = tuple(sorted(
                source for source, cell in cells.items()
                if str(cell["vote"]) == "unknown"
            ))
            missing_sources = tuple(sorted(source_set - set(cells)))
            mandatory = list(missing_sources) + list(different_sources)
            extra_needed = max(
                0,
                threshold
                - len(same_sources)
                - len(missing_sources)
                - len(different_sources),
            )
            gap_sources = tuple(mandatory + list(unknown_sources[:extra_needed]))
            require(len(gap_sources) > 0, "UNKNOWN relation has zero authorization gap")
            metadata = (
                len(gap_sources), edge, gap_sources, same_sources,
                missing_sources, different_sources, unknown_sources,
                True, epoch, sealed,
            )
        graph[component_left].append((component_right, *metadata))
        graph[component_right].append((component_left, *metadata))

    for edge, decision in relation_decisions.items():
        if decision[0] == "unknown":
            add_edge(component_of[edge[0]], component_of[edge[1]], edge, decision)

    direct = pair(query_left, query_right)
    direct_decision = relation_decisions.get(direct)
    if direct_decision is None or direct_decision[0] != "unknown":
        add_edge(left_component, right_component, direct, None)

    def edge_key(item: Tuple[object, ...]) -> Tuple[object, ...]:
        return (
            item[0], item[2], item[3], item[4], item[5], item[6],
            item[7], item[8], -1 if item[9] is None else item[9], item[10]
        )

    for node in graph:
        graph[node].sort(key=edge_key)

    def compatible(path: Tuple[int, ...], neighbor: int) -> bool:
        return all(
            (min(component, neighbor), max(component, neighbor))
            not in separators
            for component in path
            if component != neighbor
        )

    def step_of(source_component: int, target_component: int, item: Tuple[object, ...]):
        (
            _, edge_cost, edge, gap_sources, same_sources, missing_sources,
            different_sources, unknown_sources, observed, epoch, sealed,
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

    def objective(cost: int, path: Tuple[int, ...], steps: Tuple[Mapping[str, object], ...]):
        return (
            cost,
            len(steps),
            tuple(tuple(step["pair"]) for step in steps),
            path,
        )

    direct_candidates = []
    for item in graph[left_component]:
        if item[0] == right_component and compatible((left_component,), right_component):
            step = step_of(left_component, right_component, item)
            path = (left_component, right_component)
            direct_candidates.append((objective(item[1], path, (step,)), path, (step,)))
    require(direct_candidates, "ambiguity graph lacks a direct bounded fallback")
    best_objective, best_path, best_steps = min(direct_candidates, key=lambda item: item[0])

    # Stack entries carry complete simple paths.  Reversed insertion preserves
    # the graph's canonical forward order while remaining implementation-
    # independent from the producer's recursive traversal.
    stack = [(left_component, (left_component,), 0, tuple())]
    while stack:
        node, path, cost, steps = stack.pop()
        extensions = []
        for item in graph[node]:
            neighbor, edge_cost = item[0], item[1]
            if neighbor in path or not compatible(path, neighbor):
                continue
            new_cost = cost + edge_cost
            if neighbor != right_component and new_cost >= best_objective[0]:
                continue
            step = step_of(node, neighbor, item)
            new_path = path + (neighbor,)
            new_steps = steps + (step,)
            if neighbor == right_component:
                candidate = objective(new_cost, new_path, new_steps)
                if candidate < best_objective:
                    best_objective, best_path, best_steps = candidate, new_path, new_steps
            else:
                extensions.append((neighbor, new_path, new_cost, new_steps))
        stack.extend(reversed(extensions))

    return best_objective[:2], list(best_steps), list(best_path), separators, component_of


def verify_ambiguous(normalized: Mapping[str, object], certificate: Mapping[str, object]) -> None:
    query_left, query_right = query_of(normalized, certificate)
    reconstructed = materialize(normalized)
    _, _, component_of, _, _, different = reconstructed
    separators = component_separators(component_of, different)
    left_component = component_of[query_left]
    right_component = component_of[query_right]
    require(left_component != right_component, "ambiguous query endpoints are in one component")
    query_components = (min(left_component, right_component), max(left_component, right_component))
    require(query_components not in separators, "ambiguous query has a selected negative separator")
    optimum, expected_steps, expected_path, rebuilt_separators, rebuilt_components = _minimal_ambiguity_prepared(
        normalized, query_left, query_right, reconstructed
    )
    require(rebuilt_separators == separators and rebuilt_components == component_of, "ambiguity reconstruction mismatch")
    require(certificate.get("globally_sufficient") is True, "ambiguity plan is not marked globally sufficient")
    supplied_gap = strict_int(certificate.get("authorization_gap"), "ambiguity authorization_gap")
    supplied_edges = strict_int(certificate.get("edge_count"), "ambiguity edge_count")
    require(optimum == (supplied_gap, supplied_edges), "ambiguity optimum does not match the certificate")
    supplied_path = certificate.get("component_path")
    require(isinstance(supplied_path, list), "ambiguity component_path must be a list")
    require(supplied_path == expected_path, "ambiguity component path is not the canonical global optimum")
    require(
        all(
            (min(left, right), max(left, right)) not in separators
            for index, left in enumerate(supplied_path)
            for right in supplied_path[index + 1 :]
        ),
        "ambiguity path contains an internal selected negative separator",
    )
    supplied_steps = certificate.get("steps")
    require(isinstance(supplied_steps, list), "ambiguity steps must be a list")
    require(supplied_steps == expected_steps, "ambiguity steps do not match the independently reconstructed optimum")


def verify(state: Mapping[str, object], certificate: Mapping[str, object]) -> None:
    normalized = validate_state(state)
    kind = certificate.get("kind")
    require(isinstance(kind, str), "certificate kind must be a string")
    if kind == "same":
        verify_same(normalized, certificate)
    elif kind == "different":
        verify_different(normalized, certificate)
    elif kind == "ambiguous":
        verify_ambiguous(normalized, certificate)
    else:
        raise VerificationError(f"unknown certificate kind: {kind!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state", type=Path)
    parser.add_argument("certificate", type=Path)
    args = parser.parse_args()
    try:
        verify(load(args.state), load(args.certificate))
    except (VerificationError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
