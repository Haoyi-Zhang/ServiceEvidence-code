#!/usr/bin/env python3
"""Finite cross-checks using block enumeration and exhaustive simple paths.

The production checker remains a separate implementation. These tiny oracles
add algorithmic diversity without claiming exhaustive verification at scale.
"""
import importlib.util
import itertools
import json
from pathlib import Path
import resource
import time
from cie.model import EvidenceCell, Replica, Vote

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("certificate_checker", ROOT / "checker/verify.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def signature(replica):
    state = replica.export_state()
    state.pop("node_id")
    return state


def blocks_oracle(handles, labels):
    """Explicit set partitions; no disjoint-set data structure."""
    blocks = [{h} for h in handles]
    accepted = []
    negatives = [p for p, v in labels.items() if v == "different"]
    for pair, value in sorted(labels.items()):
        if value != "same":
            continue
        left = next(b for b in blocks if pair[0] in b)
        right = next(b for b in blocks if pair[1] in b)
        merged = left | right
        if any(a in merged and b in merged for a, b in negatives):
            continue
        accepted.append(pair)
        if left != right:
            blocks = [b for b in blocks if b != left and b != right] + [merged]
    return tuple(sorted(tuple(sorted(b)) for b in blocks)), accepted


def graph_oracle():
    handles = "abcd"
    pairs = list(itertools.combinations(handles, 2))
    kinds = {"same": 0, "different": 0, "ambiguous": 0}
    compatibility = {
        "ambiguous_queries": 0,
        "old_local_choice_globally_invalid": 0,
        "global_cost_exceeds_local": 0,
        "maximum_cost_increase": 0,
        "total_cost_increase": 0,
    }
    for values in itertools.product(("same", "different", "unknown"), repeat=6):
        labels = dict(zip(pairs, values))
        replica = Replica("fixture", ["x", "y", "z"], 2, handles)
        for pair, label in labels.items():
            vector = {"same": [Vote.SAME, Vote.SAME, Vote.UNKNOWN],
                      "different": [Vote.DIFFERENT, Vote.UNKNOWN, Vote.UNKNOWN],
                      "unknown": [Vote.SAME, Vote.UNKNOWN, Vote.UNKNOWN]}[label]
            for source, vote in zip(replica.sources, vector):
                replica.add(EvidenceCell(*pair, 0, source, vote, "finite graph"))
        expected, accepted = blocks_oracle(handles, labels)
        view = replica.materialize()
        require(view.components == expected and list(view.accepted_same_edges) == accepted, "partition mismatch")
        component = {h: i for i, block in enumerate(expected) for h in block}
        negative_components = {tuple(sorted((component[a], component[b])))
                               for (a, b), v in labels.items() if v == "different"}
        for a, b in pairs:
            cert = replica.certificate(a, b)
            checker.verify(replica.export_state(), cert)
            kinds[cert["kind"]] += 1
            x, y = component[a], component[b]
            expected_kind = ("same" if x == y else "different"
                             if tuple(sorted((x, y))) in negative_components else "ambiguous")
            require(cert["kind"] == expected_kind, "certificate classification mismatch")
            if expected_kind != "ambiguous":
                continue
            edges = {}
            for (u, v), label in labels.items():
                i, j = component[u], component[v]
                key = tuple(sorted((i, j)))
                if label == "unknown" and i != j and key not in negative_components:
                    edges[key] = 1  # canonical fixture vector has one positive.
            if labels[(a, b)] != "unknown":
                key = tuple(sorted((x, y)))
                edges[key] = min(edges.get(key, 3), 3)
            global_paths = []
            local_paths = []
            def visit(node, path, cost, globally_compatible):
                if node == y:
                    record = (cost, len(path) - 1, path)
                    local_paths.append(record)
                    if globally_compatible:
                        global_paths.append(record)
                    return
                for next_node in range(len(expected)):
                    key = tuple(sorted((node, next_node)))
                    if next_node in path or key not in edges:
                        continue
                    next_compatible = globally_compatible and not any(
                        tuple(sorted((prior, next_node))) in negative_components
                        for prior in path
                    )
                    visit(next_node, path + (next_node,), cost + edges[key], next_compatible)
            visit(x, (x,), 0, True)
            require(global_paths, "global ambiguity graph lacks a feasible path")
            global_best = min(global_paths)
            local_best = min(local_paths)
            require(global_best[:2] == (cert["authorization_gap"], cert["edge_count"]), "global path optimum mismatch")
            require(cert.get("globally_sufficient") is True, "global certificate marker missing")
            compatibility["ambiguous_queries"] += 1
            local_path = local_best[2]
            local_valid = not any(
                tuple(sorted((local_path[i], local_path[j]))) in negative_components
                for i in range(len(local_path))
                for j in range(i + 1, len(local_path))
            )
            if not local_valid:
                compatibility["old_local_choice_globally_invalid"] += 1
            increase = global_best[0] - local_best[0]
            require(increase >= 0, "global constraint reduced the optimum")
            if increase:
                compatibility["global_cost_exceeds_local"] += 1
                compatibility["total_cost_increase"] += increase
                compatibility["maximum_cost_increase"] = max(
                    compatibility["maximum_cost_increase"], increase
                )
    return {
        "labelled_graphs": 729,
        "queries": sum(kinds.values()),
        "kinds": kinds,
        "global_compatibility": compatibility,
    }



def compatibility_oracle():
    """Compare the former local path rule with global path compatibility.

    The quotient has four components, five registered sources, edge gaps of one
    or two source-slot interventions, explicit negative separators, and an
    unobserved direct fallback of cost five.  This finite diagnostic oracle is
    independent of service-state construction and exposes cases where every
    adjacent step is locally admissible but the whole path crosses a non-adjacent
    separator.
    """
    nodes = tuple(range(4))
    pairs = tuple(itertools.combinations(nodes, 2))
    result = {
        "labelled_quotient_graphs": 0,
        "query_cases": 0,
        "old_local_choice_globally_invalid": 0,
        "global_cost_exceeds_local": 0,
        "cost_increase_1": 0,
        "cost_increase_2": 0,
        "maximum_cost_increase": 0,
    }
    for values in itertools.product(("absent", "gap1", "gap2", "negative"), repeat=len(pairs)):
        labels = dict(zip(pairs, values))
        negatives = {pair for pair, value in labels.items() if value == "negative"}
        observed = {
            pair: 1 if value == "gap1" else 2
            for pair, value in labels.items()
            if value in ("gap1", "gap2")
        }
        result["labelled_quotient_graphs"] += 1
        for source, target in pairs:
            if (source, target) in negatives:
                continue
            edges = dict(observed)
            edges[(source, target)] = min(edges.get((source, target), 5), 5)
            local_paths = []
            global_paths = []

            def visit(node, path, cost, globally_compatible):
                if node == target:
                    record = (cost, len(path) - 1, path)
                    local_paths.append(record)
                    if globally_compatible:
                        global_paths.append(record)
                    return
                for next_node in nodes:
                    pair = tuple(sorted((node, next_node)))
                    if next_node in path or pair not in edges:
                        continue
                    next_compatible = globally_compatible and not any(
                        tuple(sorted((prior, next_node))) in negatives for prior in path
                    )
                    visit(next_node, path + (next_node,), cost + edges[pair], next_compatible)

            visit(source, (source,), 0, True)
            local_best = min(local_paths)
            global_best = min(global_paths)
            local_path = local_best[2]
            local_valid = not any(
                tuple(sorted((local_path[i], local_path[j]))) in negatives
                for i in range(len(local_path))
                for j in range(i + 1, len(local_path))
            )
            increase = global_best[0] - local_best[0]
            require(increase >= 0, "global compatibility reduced an optimum")
            result["query_cases"] += 1
            if not local_valid:
                result["old_local_choice_globally_invalid"] += 1
            if increase:
                result["global_cost_exceeds_local"] += 1
                result[f"cost_increase_{increase}"] += 1
                result["maximum_cost_increase"] = max(result["maximum_cost_increase"], increase)
            require((not local_valid) == bool(increase), "local invalidity and cost increase diverged")
    require(result["labelled_quotient_graphs"] == 4096, "quotient graph count changed")
    require(result["query_cases"] == 18432, "quotient query count changed")
    require(result["old_local_choice_globally_invalid"] == 144, "unsafe local count changed")
    require(result["cost_increase_1"] == 108 and result["cost_increase_2"] == 36, "cost distribution changed")
    return result

def gap_oracle():
    cases = 0
    for partial in itertools.product((None, "same", "different", "unknown"), repeat=3):
        for threshold in range(1, 4):
            p, m, d = partial.count("same"), partial.count(None), partial.count("different")
            formula = m + d + max(0, threshold - p - m - d)
            candidates = []
            for complete in itertools.product(("same", "different", "unknown"), repeat=3):
                if "different" not in complete and complete.count("same") >= threshold:
                    candidates.append(sum(old != new for old, new in zip(partial, complete)))
            require(min(candidates) == formula, "source-slot minimum mismatch")
            cases += 1
    return {"partial_vectors": 64, "threshold_cases": cases, "completions_per_case": 27}


def floor_oracle():
    cells = [EvidenceCell("a", "b", e, s, Vote.SAME, "floor algebra") for e in (0, 1) for s in ("x", "y")]
    states = []
    for mask in range(16):
        replica = Replica("fixture", ["x", "y"], 2, ["a", "b"])
        for i, cell in enumerate(cells):
            if mask & (1 << i):
                replica.add(cell)
        states.append(replica)
    # Floor zero retains its two cells and any of the four subsets of epoch one.
    for mask in range(4):
        replica = Replica("fixture", ["x", "y"], 2, ["a", "b"])
        for cell in cells[:2]:
            replica.add(cell)
        for i, cell in enumerate(cells[2:]):
            if mask & (1 << i):
                replica.add(cell)
        replica.compact({("a", "b"): 0}, 1)
        states.append(replica)
    replica = Replica("fixture", ["x", "y"], 2, ["a", "b"])
    for cell in cells[2:]:
        replica.add(cell)
    replica.compact({("a", "b"): 1}, 0)
    states.append(replica)
    def join(a, b):
        result = Replica.import_state(a.export_state())
        result.join(b)
        return result
    for a in states:
        require(signature(join(a, a)) == signature(a), "idempotence")
        for b in states:
            require(signature(join(a, b)) == signature(join(b, a)), "commutativity")
            for c in states:
                require(signature(join(join(a, b), c)) == signature(join(a, join(b, c))), "associativity")
    return {"admissible_states": len(states), "triples": len(states)**3, "pairs": len(states)**2}


def incompatible_local_path():
    # a--b--c--d are unknown with one missing positive each. b--d is
    # negative. The old local shortest path cost 3 but was globally invalid.
    # The repaired certificate must choose the safe direct fallback at cost 5.
    replica = Replica("fixture", ["v0", "v1", "v2", "v3", "v4"], 2, "abcd")
    for pair in (("a", "b"), ("b", "c"), ("c", "d")):
        for i, source in enumerate(replica.sources):
            replica.add(EvidenceCell(*pair, 0, source, Vote.SAME if i == 0 else Vote.UNKNOWN, "path"))
    for i, source in enumerate(replica.sources):
        replica.add(EvidenceCell("b", "d", 0, source, Vote.DIFFERENT if i == 0 else Vote.UNKNOWN, "separator"))
    cert = replica.certificate("a", "d")
    checker.verify(replica.export_state(), cert)
    require(cert["kind"] == "ambiguous" and cert["authorization_gap"] == 5, "global repair changed")
    require(cert["edge_count"] == 1 and cert["steps"][0]["pair"] == ["a", "d"], "safe fallback changed")
    require(cert.get("globally_sufficient") is True, "global marker missing")
    return {
        "state": replica.export_state(),
        "certificate": cert,
        "conflict": ["b", "d"],
        "rejected_local_path": [["a", "b"], ["b", "c"], ["c", "d"]],
        "rejected_local_gap": 3,
        "global_authorization_gap": 5,
        "globally_sufficient_plan": True,
    }


def main():
    begin = time.perf_counter()
    result = {"graph": graph_oracle(), "compatibility": compatibility_oracle(), "gap": gap_oracle(), "floors": floor_oracle()}
    counterexample = incompatible_local_path()
    result["global_path_regression_confirmed"] = True
    result["elapsed_seconds"] = time.perf_counter() - begin
    result["cpu_seconds"] = time.process_time()
    result["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    (ROOT / "results/exact_oracles.json").write_text(json.dumps(result, indent=2) + "\n")
    (ROOT / "results/local_gap_counterexample.json").write_text(json.dumps(counterexample, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
