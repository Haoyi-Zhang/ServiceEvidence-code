"""Owned set-work regression for the primary MWS Section 3.4 comparator."""
import unittest
from unittest.mock import patch

from cie import mutex_baseline as mws
from cie.model import Vote


class CountedSet(set):
    transfers = []

    def update(self, other):
        # This is the number of attempted input insertions, not bytes or time.
        type(self).transfers.append((len(self), len(other)))
        return super().update(other)


def unequal_incidence_fixture():
    large = [f'a{i:02d}' for i in range(8)]
    outside = [f'x{i:02d}' for i in range(16)]
    names = large + ['b'] + outside
    edges = [mws.SignedEdge(('b', x), Vote.DIFFERENT, 3) for x in outside]
    edges += [mws.SignedEdge((a, b), Vote.SAME, 2) for a, b in zip(large, large[1:])]
    edges += [mws.SignedEdge((large[0], 'b'), Vote.SAME, 1)]
    return names, edges


class MutexMergeCostTests(unittest.TestCase):
    def test_hash_merge_uses_smaller_incidence_table_not_smaller_component(self):
        names, edges = unequal_incidence_fixture()
        CountedSet.transfers = []
        with patch.object(mws, 'set', CountedSet, create=True):
            result = mws.mutex_watershed(names, edges)
        self.assertEqual(result.components[0], tuple(sorted(names[:9])))
        self.assertEqual(len(result.active_negative), 16)
        self.assertEqual(len(CountedSet.transfers), 8)
        self.assertTrue(all(moved <= destination for destination, moved in CountedSet.transfers),
                        f'non-small-to-large ID merge: {CountedSet.transfers}')
        self.assertEqual(sum(moved for _, moved in CountedSet.transfers), 0)


if __name__ == '__main__':
    unittest.main()
