"""Benign finite signed graphs; no transport or external inputs."""
import itertools
import random
import unittest

from cie.model import EvidenceCell, Replica, Vote
from cie.mutex_baseline import (SignedEdge, controlled_materialize, mutex_watershed,
                                priority_preserving_mws, violated_negatives)


def weighted_oracle(handles, edges):
    """Algorithm 2 specification with explicit blocks and endpoint scans."""
    blocks = [{h} for h in handles]
    forest, redundant, rejected, active, ignored = [], [], [], [], []
    for edge in sorted(edges, key=lambda e: (-e.weight, e.vote != Vote.DIFFERENT, e.pair)):
        a = next(g for g in blocks if edge.pair[0] in g)
        b = next(g for g in blocks if edge.pair[1] in g)
        if edge.vote == Vote.DIFFERENT:
            (ignored if a is b else active).append(edge.pair)
        elif a is b:
            redundant.append(edge.pair)
        elif any((x in a and y in b) or (y in a and x in b) for x, y in active):
            rejected.append(edge.pair)
        else:
            blocks.remove(a); blocks.remove(b); blocks.append(a | b)
            forest.append(edge.pair)
    return (tuple(sorted(tuple(sorted(g)) for g in blocks)), tuple(forest),
            tuple(redundant), tuple(rejected), tuple(active), tuple(ignored))


def triangle():
    r = Replica('triangle', ('s0', 's1', 's2'), 2, 'abc')
    for pair, votes in ((('a', 'b'), (Vote.SAME, Vote.SAME, Vote.UNKNOWN)),
                        (('b', 'c'), (Vote.SAME, Vote.SAME, Vote.UNKNOWN)),
                        (('a', 'c'), (Vote.UNKNOWN, Vote.UNKNOWN, Vote.DIFFERENT))):
        for s, v in zip(r.sources, votes):
            r.add(EvidenceCell(*pair, 0, s, v, 'constructed conflicting triangle'))
    return r


class MutexBaselineTests(unittest.TestCase):
    def test_exhaustive_same_semantics_and_factorial(self):
        pairs = list(itertools.combinations('abcd', 2))
        for labels in itertools.product(tuple(Vote), repeat=6):
            r = Replica('finite', ['s'], 1, 'abcd')
            for p, v in zip(pairs, labels):
                r.add(EvidenceCell(*p, 0, 's', v, 'finite'))
            view = r.materialize()
            self.assertEqual(view, r.materialize_reference())
            self.assertEqual(view, priority_preserving_mws(r))
            self.assertEqual(view, controlled_materialize(r))
            # Fix decisions and change only the component guard.
            off = controlled_materialize(r, component_veto=False)
            self.assertEqual(off.decisions, view.decisions)
            self.assertEqual(controlled_materialize(r, relation_veto=False),
                             controlled_materialize(r, relation_veto=False, component_veto=False))

    def test_weighted_mws_against_block_oracle(self):
        pairs = list(itertools.combinations('abc', 2))
        states = (None,) + tuple((v, w) for v in (Vote.SAME, Vote.DIFFERENT) for w in (1, 2))
        for choices in itertools.product(states, repeat=3):
            edges = [SignedEdge(p, *c) for p, c in zip(pairs, choices) if c is not None]
            result = mutex_watershed('abc', edges)
            self.assertEqual(tuple(result.__dict__.values()), weighted_oracle('abc', edges))
        rng = random.Random(2018)
        pairs = list(itertools.combinations('abcdefgh', 2))
        for _ in range(200):
            edges = [SignedEdge(p, rng.choice((Vote.SAME, Vote.DIFFERENT)), rng.randrange(5))
                     for p in rng.sample(pairs, rng.randrange(29))]
            result = mutex_watershed('abcdefgh', edges)
            self.assertEqual(tuple(result.__dict__.values()), weighted_oracle('abcdefgh', edges))

    def test_weighted_priority_is_not_always_negative_first(self):
        edges = [SignedEdge(('a','b'), Vote.SAME, 3),
                 SignedEdge(('b','c'), Vote.SAME, 2),
                 SignedEdge(('a','c'), Vote.DIFFERENT, 1)]
        weighted = mutex_watershed('abc', edges)
        self.assertEqual(weighted.components, (('a','b','c'),))
        self.assertEqual(weighted.ignored_negative, (('a','c'),))
        special = mutex_watershed('abc', [SignedEdge(e.pair, e.vote,
            2 if e.vote == Vote.DIFFERENT else 1) for e in edges])
        self.assertEqual(special.components, (('a','b'), ('c',)))
        self.assertEqual(special.rejected_positive, (('b','c'),))

    def test_reachable_component_veto(self):
        r = triangle()
        on = r.materialize()
        off = controlled_materialize(r, component_veto=False)
        self.assertEqual(on, controlled_materialize(r))
        self.assertEqual(on.decisions, off.decisions)
        self.assertEqual(on.components, (('a','b'), ('c',)))
        self.assertEqual(off.components, (('a','b','c'),))
        self.assertEqual(violated_negatives(on, on.different_edges), 0)
        self.assertEqual(violated_negatives(off, on.different_edges), 1)
        self.assertEqual(on.rejected_same_edges, (('b','c'),))

    def test_relation_veto_only_keeps_closure_and_cells(self):
        r = Replica('mixed', ['s0','s1','s2'], 2, 'abc')
        for s, v in zip(r.sources, (Vote.SAME, Vote.SAME, Vote.DIFFERENT)):
            r.add(EvidenceCell('a','b',0,s,v,'mixed vector'))
        for s in r.sources[:2]:
            r.add(EvidenceCell('b','c',1,s,Vote.SAME,'open vector'))
        before = r.export_state()
        on = controlled_materialize(r)
        off = controlled_materialize(r, relation_veto=False)
        self.assertEqual(on.decisions['a','b'].vote, Vote.DIFFERENT)
        self.assertEqual(off.decisions['a','b'].vote, Vote.SAME)
        self.assertEqual(off.decisions['b','c'].vote, Vote.UNKNOWN)
        self.assertFalse(off.decisions['b','c'].sealed)
        self.assertEqual(before, r.export_state())
        self.assertEqual(on.decisions['a','b'].cells, off.decisions['a','b'].cells)

    def test_partial_epochs_floors_and_extra_handles(self):
        rng = random.Random(24018)
        for _ in range(80):
            r = Replica('partial', ['s0','s1','s2'], 2, 'abcdef')
            for p in itertools.combinations('abcdef',2):
                for e in range(3):
                    for s in r.sources:
                        if e == 0 or rng.random() < 0.6:
                            r.add(EvidenceCell(*p,e,s,rng.choice(tuple(Vote)),''))
            stale = Replica.import_state(r.export_state())
            r.compact({p:0 for p in itertools.combinations('abcdef',2)},2)
            r.join(stale)
            self.assertEqual(r.materialize(['z']), priority_preserving_mws(r,['z']))

    def test_redundant_positive_bookkeeping(self):
        r = Replica('cycle',['s'],1,'abc')
        for p in itertools.combinations('abc',2):
            r.add(EvidenceCell(*p,0,'s',Vote.SAME,''))
        result = mutex_watershed('abc',[SignedEdge(p,Vote.SAME,1) for p in itertools.combinations('abc',2)])
        self.assertEqual(len(result.positive_forest),2)
        self.assertEqual(len(result.redundant_positive),1)
        self.assertEqual(len(priority_preserving_mws(r).accepted_same_edges),3)
        self.assertEqual(r.materialize(),priority_preserving_mws(r))

    def test_signed_parallel_edges_and_input_boundaries(self):
        result = mutex_watershed('ab',[SignedEdge(('a','b'),Vote.SAME,3),
                                       SignedEdge(('a','b'),Vote.DIFFERENT,2)])
        self.assertEqual(result.ignored_negative,(('a','b'),))
        for w in (-1, float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                SignedEdge(('a','b'),Vote.SAME,w)
        with self.assertRaises(ValueError):
            mutex_watershed('a',[SignedEdge(('a','b'),Vote.SAME,1)])
        edge = SignedEdge(('a','b'),Vote.SAME,1)
        with self.assertRaises(ValueError):
            mutex_watershed('ab',[edge,edge])
        self.assertEqual(priority_preserving_mws(Replica('empty',['s'],1),['z']).components,(('z',),))


if __name__ == '__main__':
    unittest.main()
