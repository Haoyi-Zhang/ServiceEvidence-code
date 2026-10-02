"""Regression tests for common-floor holes and serialized-state boundaries."""
import copy
import unittest
from cie.model import EvidenceCell, Replica, Vote
from cie.simulator import stable_epochs


def filled(name, epochs):
    replica = Replica(name, ["x", "y"], 2, ["a", "b"])
    for epoch in epochs:
        for source in replica.sources:
            replica.add(EvidenceCell("a", "b", epoch, source, Vote.SAME, "fixture"))
    return replica


class BoundaryTests(unittest.TestCase):
    def test_disjoint_latest_epochs_are_not_a_common_floor(self):
        left, right = filled("left", [2]), filled("right", [3])
        self.assertEqual(stable_epochs({"left": left, "right": right}), {})
        with self.assertRaises(ValueError):
            right.compact({("a", "b"): 2}, 1)

    def test_holes_retain_the_greatest_actually_common_epoch(self):
        left, right = filled("left", [1, 3]), filled("right", [1, 2, 4])
        self.assertEqual(stable_epochs({"left": left, "right": right}), {("a", "b"): 1})

    def test_empty_and_mismatched_registries(self):
        self.assertEqual(stable_epochs({}), {})
        with self.assertRaises(ValueError):
            stable_epochs({"a": filled("a", [1]), "b": Replica("b", ["z"], 1)})

    def test_import_rejects_coercions_duplicates_and_unregistered_handles(self):
        state = filled("a", [0]).export_state()
        changes = [
            lambda s: s.update(threshold=True),
            lambda s: s.update(threshold="2"),
            lambda s: s.update(node_id=17),
            lambda s: s["cells"][0].update(epoch=True),
            lambda s: s["cells"][0].update(epoch=0.4),
            lambda s: s["cells"][0].update(epoch="0"),
            lambda s: s["cells"][0].update(reason=9),
            lambda s: s["cells"].append(s["cells"][0].copy()),
            lambda s: s["handles"].append("a"),
            lambda s: s.update(handles=["a"]),
            lambda s: s.update(stable_floors=[{"left": "b", "right": "a", "epoch": 0}]),
            lambda s: s.update(stable_floors=[{"left": "a", "right": "b", "epoch": False}]),
        ]
        for change in changes:
            bad = copy.deepcopy(state)
            change(bad)
            with self.assertRaises(ValueError):
                Replica.import_state(bad)

    def test_failed_handle_batch_is_atomic(self):
        replica = filled("a", [0])
        prior = replica.export_state()
        with self.assertRaises(ValueError):
            replica.register_handles(["new", 17])
        self.assertEqual(replica.export_state(), prior)

    def test_failed_equivocating_join_does_not_add_handles(self):
        replica = filled("a", [0])
        other = Replica("b", ["x", "y"], 2, ["a", "b", "new"])
        other.add(EvidenceCell("a", "b", 0, "x", Vote.DIFFERENT, "contradiction"))
        before = replica.export_state()
        with self.assertRaises(ValueError):
            replica.join(other)
        self.assertEqual(replica.export_state(), before)

    def test_direct_cell_types_are_strict(self):
        for epoch in (True, 1.2, "1", -1):
            with self.assertRaises(ValueError):
                EvidenceCell("a", "b", epoch, "x", Vote.SAME, "fixture")


if __name__ == "__main__":
    unittest.main()
