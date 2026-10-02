from __future__ import annotations

import itertools
import unittest

from cie.model import EvidenceCell, Replica, Vote, relation


class ExhaustiveScheduleTests(unittest.TestCase):
    def test_all_small_delivery_orders_converge(self):
        sources = ("v0", "v1", "v2")
        edge = relation("a", "b")
        cells = (
            EvidenceCell(*edge, 0, "v0", Vote.SAME, "x"),
            EvidenceCell(*edge, 0, "v1", Vote.SAME, "x"),
            EvidenceCell(*edge, 0, "v2", Vote.UNKNOWN, "x"),
            EvidenceCell(*edge, 1, "v0", Vote.UNKNOWN, "y"),
            EvidenceCell(*edge, 1, "v1", Vote.UNKNOWN, "y"),
            EvidenceCell(*edge, 1, "v2", Vote.DIFFERENT, "y"),
        )
        expected = None
        for order in itertools.permutations(cells):
            replica = Replica("n", sources, 2)
            for cell in order:
                replica.add(cell)
            signature = replica.materialize().components
            expected = signature if expected is None else expected
            self.assertEqual(signature, expected)
        self.assertEqual(expected, (("a",), ("b",)))


if __name__ == "__main__":
    unittest.main()
