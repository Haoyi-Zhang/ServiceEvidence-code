"""Owned future vectors, including higher open epochs and compatible paths."""
import importlib.util
from pathlib import Path
import unittest

from cie.model import Replica, EvidenceCell, Vote
from cie.mutex_baseline import priority_preserving_mws

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('plan_fixture_execution',ROOT/'experiments/plan_execution.py')
execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)


def vector(r,edge,votes,epoch=0):
    for source,vote in zip(r.sources,votes):
        if vote is not None:
            r.add(EvidenceCell(*edge,epoch,source,Vote(vote),'owned vector'))


class PlanExecutionTests(unittest.TestCase):
    def test_three_edge_plan_is_actually_executed(self):
        r = Replica('owned',tuple(f's{i}' for i in range(5)),2,'abcd')
        for edge in (('a','b'),('b','c'),('c','d')):
            vector(r,edge,('same',)+('unknown',)*4)
        cert = r.certificate('a','d')
        self.assertEqual((cert['authorization_gap'],cert['edge_count']),(3,3))
        after = execution.complete(r,cert)
        self.assertEqual(after.materialize().components,(('a','b','c','d'),))
        self.assertEqual(after.materialize(),priority_preserving_mws(after))
        self.assertEqual(len(after)-len(r),15)

    def test_fresh_epoch_exceeds_open_epoch_not_just_selected_epoch(self):
        r = Replica('owned',['s0','s1','s2'],2,'ab')
        vector(r,('a','b'),('same','unknown','unknown'))
        vector(r,('a','b'),('different',None,None),epoch=9)
        cert = r.certificate('a','b')
        self.assertEqual(cert['steps'][0]['epoch'],0)
        after = execution.complete(r,cert)
        self.assertEqual(after.decisions()['a','b'].epoch,10)
        self.assertEqual(after.certificate('a','b')['kind'],'same')

    def test_preserves_old_components_support_and_floor(self):
        r = Replica('owned',['s0','s1','s2'],2,'abcde')
        for epoch in (0,1):
            vector(r,('a','b'),('same','same','unknown'),epoch)
        vector(r,('c','d'),('same','same','unknown'))
        vector(r,('b','c'),('same','unknown','unknown'))
        vector(r,('d','e'),('unknown','unknown','different'))
        r.compact({('a','b'):1},0)
        before = r.materialize()
        after = execution.complete(r,r.certificate('a','d'))
        view = after.materialize()
        self.assertEqual(view.components,(('a','b','c','d'),('e',)))
        self.assertTrue(set(before.accepted_same_edges) <= set(view.accepted_same_edges))
        self.assertEqual(r.stable_floors,after.stable_floors)
        self.assertEqual(before.different_edges,view.different_edges)


if __name__ == '__main__':
    unittest.main()
