"""Finite certificate oracle and checker-local reconstruction regressions.

The reference scans raw cells and enumerates whole quotient paths by literal
permutations/products. It imports no producer or checker reconstruction helper.
All fixtures are in memory; no services, campaigns, saved receipts or timings.
"""
from __future__ import annotations

import copy
import importlib.util
import itertools
from pathlib import Path
import unittest
from unittest.mock import patch

from cie.model import EvidenceCell, Replica, Vote
from cie.service import compact_certificate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("context_checker", ROOT / "checker/verify.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def fixture(handles="abcd", sources=("s0", "s1", "s2"), threshold=2):
    return Replica("finite", sources, threshold, handles)


def add_vector(replica, edge, votes, epoch=0):
    for source, vote in zip(replica.sources, votes):
        if vote is not None:
            replica.add(EvidenceCell(*edge, epoch, source, Vote(vote), "finite"))


def finite_reference(state, left, right):
    """Complete canonical public certificate for admitted built-in JSON states."""
    sources = sorted(state["sources"])
    threshold = state["threshold"]
    raw = state["cells"]
    relations = sorted({(c["left"], c["right"]) for c in raw})
    selected = {}
    for edge in relations:
        cells = [c for c in raw if (c["left"], c["right"]) == edge]
        epochs = sorted({c["epoch"] for c in cells})
        complete = [e for e in epochs
                    if all(any(c["epoch"] == e and c["source"] == s for c in cells)
                           for s in sources)]
        epoch = max(complete or epochs)
        vector = sorted([c for c in cells if c["epoch"] == epoch],
                        key=lambda c: c["source"])
        sealed = bool(complete)
        votes = [c["vote"] for c in vector]
        vote = ("different" if "different" in votes else
                "same" if votes.count("same") >= threshold else "unknown") if sealed else "unknown"
        selected[edge] = (vote, epoch, vector, sealed)

    negative = [e for e in relations if selected[e][0] == "different"]
    blocks = [{h} for h in sorted(state["handles"])]
    accepted = []
    for edge in [e for e in relations if selected[e][0] == "same"]:
        a = next(b for b in blocks if edge[0] in b)
        b = next(b for b in blocks if edge[1] in b)
        combined = a | b
        if any(x in combined and y in combined for x, y in negative):
            continue
        accepted.append(edge)
        if a is not b:
            blocks = [g for g in blocks if g is not a and g is not b] + [combined]
    components = sorted(tuple(sorted(g)) for g in blocks)
    component_of = {h: i for i, g in enumerate(components) for h in g}
    separators = {(min(component_of[a], component_of[b]), max(component_of[a], component_of[b]))
                  for a, b in negative}
    start, end = component_of[left], component_of[right]
    if start == end:
        # Breadth levels, not the producer's predecessor loop.
        paths = [(left,)]
        while not any(p[-1] == right for p in paths):
            paths = [p + (n,) for p in paths
                     for n in sorted({b if a == p[-1] else a for a, b in accepted
                                      if p[-1] in (a, b)})
                     if n not in p]
        path = next(p for p in paths if p[-1] == right)
        support = []
        for a, b in zip(path, path[1:]):
            edge = tuple(sorted((a, b)))
            _, epoch, cells, _ = selected[edge]
            support.append({"pair": list(edge), "epoch": epoch,
                            "cells": [copy.deepcopy(c) for c in cells if c["vote"] == "same"]})
        cert = {"kind": "same", "query": [left, right], "path": list(path), "support": support}
    elif tuple(sorted((start, end))) in separators:
        edge = next(e for e in negative if {component_of[e[0]], component_of[e[1]]} == {start, end})
        cell = next(c for c in selected[edge][2] if c["vote"] == "different")
        cert = {"kind": "different", "query": [left, right],
                "separator_pair": list(edge), "cell": copy.deepcopy(cell)}
    else:
        choices = []
        for edge in relations:
            vote, epoch, cells, sealed = selected[edge]
            if vote != "unknown":
                continue
            same = sorted(c["source"] for c in cells if c["vote"] == "same")
            different = sorted(c["source"] for c in cells if c["vote"] == "different")
            unknown = sorted(c["source"] for c in cells if c["vote"] == "unknown")
            missing = [s for s in sources if not any(c["source"] == s for c in cells)]
            needed = max(0, threshold - len(same) - len(missing) - len(different))
            gap = missing + different + unknown[:needed]
            choices.append({"pair": list(edge), "observed": True, "epoch": epoch,
                            "sealed": sealed, "same_sources": same, "missing_sources": missing,
                            "different_sources": different, "unknown_sources": unknown,
                            "authorization_gap": len(gap), "gap_sources": gap})
        direct = tuple(sorted((left, right)))
        if direct not in selected or selected[direct][0] != "unknown":
            choices.append({"pair": list(direct), "observed": False, "epoch": None,
                            "sealed": False, "same_sources": [], "missing_sources": sources,
                            "different_sources": [], "unknown_sources": [],
                            "authorization_gap": len(sources), "gap_sources": sources})
        candidates = []
        middle = [i for i in range(len(components)) if i not in (start, end)]
        for length in range(len(middle) + 1):
            for order in itertools.permutations(middle, length):
                path = (start, *order, end)
                if any(tuple(sorted(p)) in separators for p in itertools.combinations(path, 2)):
                    continue
                options = [[dict(step, from_component=a, to_component=b) for step in choices
                            if {component_of[step["pair"][0]], component_of[step["pair"][1]]} == {a, b}]
                           for a, b in zip(path, path[1:])]
                for steps in itertools.product(*options):
                    cost = sum(s["authorization_gap"] for s in steps)
                    objective = (cost, len(steps), tuple(tuple(s["pair"]) for s in steps), path)
                    candidates.append((objective, list(steps)))
        objective, steps = min(candidates, key=lambda item: item[0])
        cert = {"kind": "ambiguous", "query": [left, right], "globally_sufficient": True,
                "authorization_gap": objective[0], "edge_count": objective[1],
                "component_path": list(objective[3]), "steps": steps}
    return cert, separators, component_of


def ternary_fixtures():
    pairs = tuple(itertools.combinations("abcd", 2))
    vectors = (("same", "same", "unknown"), ("different", "unknown", "unknown"),
               ("same", "unknown", "unknown"))
    for labels in itertools.product(range(3), repeat=6):
        replica = fixture()
        for edge, label in zip(pairs, labels):
            add_vector(replica, edge, vectors[label])
        yield replica


def partial_fixtures():
    for threshold in (1, 2, 3):
        for votes in itertools.product((None, "same", "different", "unknown"), repeat=3):
            for older in (False, True):
                replica = fixture("ab", threshold=threshold)
                if older:
                    add_vector(replica, ("a", "b"), ("same", "same", "unknown"), 0)
                add_vector(replica, ("a", "b"), votes, 2)
                yield replica


def named_fixtures():
    negative = fixture(sources=tuple(f"s{i}" for i in range(5)))
    for edge in (("a", "b"), ("b", "c"), ("c", "d")):
        add_vector(negative, edge, ("same", "unknown", "unknown", "unknown", "unknown"))
    add_vector(negative, ("b", "d"), ("different", "unknown", "unknown", "unknown", "unknown"))
    yield "nonadjacent-negative", negative
    tied = fixture(sources=tuple(f"s{i}" for i in range(5)))
    for edge in (("a", "b"), ("b", "d"), ("a", "c"), ("c", "d")):
        add_vector(tied, edge, ("same", "unknown", "unknown", "unknown", "unknown"))
    yield "lexicographic-tie", tied
    parallel = fixture()
    add_vector(parallel, ("a", "b"), ("same", "same", "unknown"))
    for edge in (("a", "c"), ("b", "c"), ("c", "d")):
        add_vector(parallel, edge, ("same", "unknown", "unknown"))
    yield "parallel-quotient-edges", parallel
    floor = fixture("ab")
    for epoch in (0, 1):
        add_vector(floor, ("a", "b"), ("same", "same", "unknown"), epoch)
    stale = Replica.import_state(floor.export_state())
    floor.compact({("a", "b"): 1}, 0)
    floor.join(stale)
    add_vector(floor, ("a", "b"), ("different", None, None), 2)
    yield "floor-stale-and-newer-open", floor


class CheckerContextTests(unittest.TestCase):
    def check_all_queries(self, replica):
        state = replica.export_state()
        for left, right in itertools.permutations(replica.handles, 2):
            expected, separators, component_of = finite_reference(state, left, right)
            actual = replica.certificate(left, right)
            self.assertEqual(actual, expected)
            self.assertIsNone(checker.verify(state, actual))
            self.assertIsNone(checker.verify(state, compact_certificate(actual)))
            if actual["kind"] == "ambiguous":
                self.assertEqual(checker.minimal_ambiguity(checker.validate_state(state), left, right),
                                 ((expected["authorization_gap"], expected["edge_count"]),
                                  expected["steps"], expected["component_path"], separators, component_of))

    def test_all_four_handle_ternary_graphs_both_query_orientations(self):
        for replica in ternary_fixtures():
            self.check_all_queries(replica)

    def test_partial_vectors_thresholds_and_epoch_selection(self):
        for replica in partial_fixtures():
            self.check_all_queries(replica)

    def test_named_negative_ties_parallel_edges_and_compacted_state(self):
        for name, replica in named_fixtures():
            with self.subTest(name=name):
                self.check_all_queries(replica)
        cert = dict(named_fixtures())["nonadjacent-negative"].certificate("a", "d")
        self.assertEqual((cert["authorization_gap"], cert["edge_count"]), (5, 1))
        self.assertFalse(cert["steps"][0]["observed"])
        cert = dict(named_fixtures())["lexicographic-tie"].certificate("a", "d")
        self.assertEqual([s["pair"] for s in cert["steps"]], [["a", "b"], ["b", "d"]])

    def test_certificate_and_key_reference_mutations_are_rejected(self):
        same = fixture("ab")
        add_vector(same, ("a", "b"), ("same", "same", "unknown"))
        different = fixture("ab")
        add_vector(different, ("a", "b"), ("different", "unknown", "unknown"))
        ambiguous = dict(named_fixtures())["lexicographic-tie"]
        mutations = []
        for replica, query in ((same, ("a", "b")), (different, ("a", "b")), (ambiguous, ("a", "d"))):
            cert = replica.certificate(*query)
            for compressed in (False, True):
                value = compact_certificate(cert) if compressed else copy.deepcopy(cert)
                mutations.append((replica, value, lambda c: c.update(query=["a", "absent"])))
                if cert["kind"] == "same":
                    mutations.extend((replica, value, change) for change in (
                        lambda c: c.update(path=["b", "a"]),
                        lambda c: c["support"][0].update(epoch=9),
                        lambda c: c["support"][0].update(pair=["a", "d"]),
                        lambda c, k=("cell_keys" if compressed else "cells"): c["support"][0].update({k: []}),
                    ))
                elif cert["kind"] == "different":
                    mutations.extend((replica, value, change) for change in (
                        lambda c: c.update(separator_pair=["a", "d"]),
                        lambda c, keys=compressed: c["cell_key"].__setitem__(2, 9) if keys else c["cell"].update(vote="same"),
                    ))
                else:
                    mutations.extend((replica, value, change) for change in (
                        lambda c: c.update(authorization_gap=99),
                        lambda c: c.update(edge_count=True),
                        lambda c: c.update(globally_sufficient=False),
                        lambda c: c.update(component_path=[0, 3]),
                    ))
                    for field, replacement in (("epoch", 9), ("sealed", False), ("observed", False),
                                               ("same_sources", []), ("missing_sources", ["s4"]),
                                               ("different_sources", ["s4"]), ("unknown_sources", []),
                                               ("gap_sources", []), ("authorization_gap", 7),
                                               ("pair", ["a", "d"]), ("from_component", 3), ("to_component", 3)):
                        mutations.append((replica, value, lambda c, f=field, v=replacement: c["steps"][0].update({f: v})))
        for replica, cert, change in mutations:
            bad = copy.deepcopy(cert)
            change(bad)
            self.assertNotEqual(bad, cert)
            with self.assertRaises((checker.VerificationError, KeyError, TypeError, ValueError)):
                checker.verify(replica.export_state(), bad)

    def test_schema_rejection_and_no_cross_call_cache(self):
        replica = fixture("ab")
        add_vector(replica, ("a", "b"), ("same", "same", "unknown"))
        state = replica.export_state()
        cert = replica.certificate("a", "b")
        for change in (lambda s: s.update(threshold=True),
                       lambda s: s["sources"].append("s0"),
                       lambda s: s["cells"].append(copy.deepcopy(s["cells"][0])),
                       lambda s: s["cells"][0].update(source="absent"),
                       lambda s: s["cells"][0].update(epoch=True),
                       lambda s: s.update(stable_floors=[{"left": "a", "right": "b", "epoch": 9}])):
            bad = copy.deepcopy(state)
            change(bad)
            with self.assertRaises(checker.VerificationError):
                checker.verify(bad, cert)
        checker.verify(state, cert)
        state["cells"][0]["vote"] = "different"
        with self.assertRaises(checker.VerificationError):
            checker.verify(state, cert)
        cert, _, _ = finite_reference(state, "a", "b")
        checker.verify(state, cert)

    def test_checker_owned_single_reconstruction_and_public_helper(self):
        replicas = [fixture("ab"), dict(named_fixtures())["lexicographic-tie"]]
        add_vector(replicas[0], ("a", "b"), ("same", "same", "unknown"))
        for replica, query in zip(replicas, (("a", "b"), ("a", "d"))):
            state, cert = replica.export_state(), replica.certificate(*query)
            with patch.object(Replica, "materialize", side_effect=AssertionError("producer view used")), \
                 patch.object(checker, "decisions", wraps=checker.decisions) as decide, \
                 patch.object(checker, "materialize", wraps=checker.materialize) as rebuild:
                checker.verify(state, cert)
                self.assertEqual((decide.call_count, rebuild.call_count), (1, 1))
            if cert["kind"] == "ambiguous":
                with patch.object(checker, "decisions", wraps=checker.decisions) as decide, \
                     patch.object(checker, "materialize", wraps=checker.materialize) as rebuild:
                    checker.minimal_ambiguity(checker.validate_state(state), *query)
                    self.assertEqual((decide.call_count, rebuild.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
