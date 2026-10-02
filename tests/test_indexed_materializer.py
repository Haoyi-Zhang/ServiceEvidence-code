"""Differential and invariant tests for the component veto index."""
import itertools
import random
import unittest
from cie.model import Replica, EvidenceCell, Vote


class IndexedMaterializerTests(unittest.TestCase):
    def assert_equal(self, replica):
        self.assertEqual(replica.materialize(), replica.materialize_reference())

    def test_all_four_handle_ternary_graphs(self):
        pairs = list(itertools.combinations('abcd', 2))
        for labels in itertools.product(tuple(Vote), repeat=6):
            r = Replica('x', ['s'], 1, 'abcd')
            for p, v in zip(pairs, labels):
                r.add(EvidenceCell(*p, 0, 's', v, 'finite graph'))
            self.assert_equal(r)

    def test_random_multi_epoch_partial_states(self):
        rng = random.Random(3701)
        nodes = [f'h{i:02}' for i in range(12)]
        pairs = list(itertools.combinations(nodes, 2))
        for _ in range(160):
            r = Replica('x', ['s0', 's1', 's2'], 2, nodes)
            cells = [EvidenceCell(*p, e, source, rng.choice(tuple(Vote)), '')
                     for p in rng.sample(pairs, 24) for e in range(3)
                     for source in r.sources if rng.random() > 0.3]
            rng.shuffle(cells)
            for c in cells:
                r.add(c)
            self.assert_equal(r)

    def test_compaction_and_stale_join(self):
        r = Replica('x', ['s0','s1'], 1, 'abcd')
        for p in itertools.combinations('abcd', 2):
            for e in range(3):
                for s in r.sources:
                    r.add(EvidenceCell(*p, e, s, Vote.DIFFERENT if e == 2 and p == ('a','c') else Vote.SAME, ''))
        stale = Replica.import_state(r.export_state())
        r.compact({p: 2 for p in itertools.combinations('abcd', 2)}, 0)
        r.join(stale)
        self.assert_equal(r)

    def test_empty_and_additional_handles(self):
        r = Replica('x', ['s'], 1)
        self.assertEqual(r.materialize(['a','b']), r.materialize_reference(['b','a']))


if __name__ == '__main__':
    unittest.main()
