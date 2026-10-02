from pathlib import Path
import unittest

from cie.model import Vote
from cie.public_benchmark import (
    conservative_vote,
    endpoint_only_vote,
    load_observations,
    pair_decisions,
    summarize,
    wilson_interval,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "external_inputs" / "ooni_dual_vantage_targets.csv"


class PublicTargetBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observations = load_observations(INPUT)

    def test_frozen_dimensions_and_vantage_pairs(self):
        self.assertEqual(len(self.observations), 24)
        self.assertEqual(len({row.case_id for row in self.observations}), 12)
        self.assertEqual(len({row.target_id for row in self.observations}), 11)
        for case in {row.case_id for row in self.observations}:
            selected = [row for row in self.observations if row.case_id == case]
            self.assertEqual(len(selected), 2)
            self.assertEqual({row.vantage for row in selected}, {"probe", "control"})

    def test_minimized_extraction_does_not_infer_missing_side_fields(self):
        by_id = {row.observation_id: row for row in self.observations}
        feminist_control = by_id["au-feminist:control"]
        self.assertIn("content-encoding", feminist_control.headers)
        self.assertTrue(feminist_control.title.startswith("feminist majority foundation"))

        facebook_control = by_id["ir-facebook:control"]
        self.assertEqual(facebook_control.endpoints, frozenset({"10.10.34.36:443"}))
        self.assertFalse(facebook_control.tcp_success)

        for case in ("my-religioustolerance", "us-collegehumor", "es-postmaster"):
            self.assertEqual(by_id[f"{case}:probe"].title, "")
            self.assertNotEqual(by_id[f"{case}:control"].title, "")

        wikispaces_probe = by_id["sk-wikispaces:probe"]
        wikispaces_control = by_id["sk-wikispaces:control"]
        self.assertEqual(wikispaces_probe.endpoints, frozenset())
        self.assertEqual(wikispaces_control.endpoints, frozenset())
        self.assertFalse(wikispaces_probe.tcp_success)
        self.assertFalse(wikispaces_control.tcp_success)

        fa_records = [row for row in self.observations if row.target_id == "https://fa.wikipedia.org"]
        self.assertEqual(len(fa_records), 4)

    def test_conservative_predicate_abstains_without_supported_error(self):
        summary = summarize(pair_decisions(self.observations))
        self.assertEqual(summary.false_same, 0)
        self.assertEqual(summary.false_different, 0)
        self.assertGreater(summary.predicted_unknown, 0)
        self.assertGreater(summary.predicted_same, 0)
        self.assertGreater(summary.predicted_different, 0)

    def test_endpoint_only_control_exposes_both_error_types(self):
        summary = summarize(pair_decisions(self.observations, predicate=endpoint_only_vote))
        self.assertGreater(summary.false_same, 0)
        self.assertGreater(summary.false_different, 0)

    def test_predicate_does_not_use_target_label(self):
        by_id = {row.observation_id: row for row in self.observations}
        probe = by_id["my-religioustolerance:probe"]
        control = by_id["my-religioustolerance:control"]
        vote, _ = conservative_vote(probe, control)
        self.assertEqual(vote, Vote.SAME)
        changed = type(control)(
            case_id=control.case_id,
            target_id="independent-label-not-read-by-predicate",
            vantage=control.vantage,
            probe_cc=control.probe_cc,
            probe_asn=control.probe_asn,
            endpoints=control.endpoints,
            tcp_success=control.tcp_success,
            status=control.status,
            headers=control.headers,
            title=control.title,
            failure=control.failure,
        )
        changed_vote, _ = conservative_vote(probe, changed)
        self.assertEqual(changed_vote, vote)

    def test_wilson_interval_is_bounded(self):
        low, high = wilson_interval(7, 7)
        self.assertGreater(low, 0.6)
        self.assertEqual(high, 1.0)


if __name__ == "__main__":
    unittest.main()
