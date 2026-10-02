import sys
import unittest
from fractions import Fraction
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from topology_campaign import partitions, responsiveness
class TopologyTests(unittest.TestCase):
    def test_bell_counts(self):
        for n, expected in enumerate((1,2,5,15,52),1):
            values=list(partitions(n))
            self.assertEqual(len(values),expected)
            self.assertEqual(len(set(values)),expected)
            for blocks in values:
                self.assertEqual(sorted(v for b in blocks for v in b),list(range(n)))
    def test_majority_and_central_can_reverse(self):
        blocks=((0,1),(2,3,4))
        self.assertEqual(responsiveness(blocks,0,(0,2,4))[:2],(Fraction(2,5),Fraction(3,5)))
        self.assertEqual(responsiveness(blocks,2,(0,1,2))[:2],(Fraction(3,5),Fraction(2,5)))
    def test_singletons_no_quorum(self):
        self.assertEqual(responsiveness(((0,),(1,),(2,),(3,),(4,)),0,(0,1,2)),(Fraction(1,5),0,1))
