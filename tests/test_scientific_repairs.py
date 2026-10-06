"""Benign regressions for workload bounds and executed scientific counters."""
from __future__ import annotations

import copy
import csv
from dataclasses import replace
import importlib.util
import itertools
from pathlib import Path
import unittest
from unittest.mock import patch

from cie.model import EvidenceCell, Replica, Vote
from cie.workload import generate_to_observation_cap, generate_workload

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sealing = load("repair_sealing_driver", "experiments/run_all.py")
equal = load("repair_equal_verifier", "scripts/verify_equal_work.py")


class WorkloadBoundTests(unittest.TestCase):
    def test_infeasible_caps_are_rejected(self):
        minimum = generate_workload(2).observation_count
        self.assertEqual(minimum, 50)
        for cap in range(minimum):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                generate_to_observation_cap(cap)

    def test_feasible_small_caps_are_respected_and_maximal(self):
        candidates = [generate_workload(n) for n in range(2, 12)]
        for cap in range(50, 201):
            with self.subTest(cap=cap):
                result = generate_to_observation_cap(cap)
                self.assertLessEqual(result.observation_count, cap)
                expected = max(w.service_count for w in candidates if w.observation_count <= cap)
                self.assertEqual(result.service_count, expected)

    def test_caps_require_integer_counts(self):
        for cap in (True, 50.0, "50", -1):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                generate_to_observation_cap(cap)

    def test_zero_collision_control_has_only_within_service_edges(self):
        for n in (2, 20):
            workload = generate_workload(n, collision_fraction=0.0, sparse_fraction=0.0)
            self.assertEqual(workload.observation_count, n * 2 * 5 * 2)
            self.assertTrue(all(workload.truth[c.left] == workload.truth[c.right] for c in workload.cells))
        # Preserve the original positive-fraction minimum and default family.
        self.assertEqual(generate_workload(2, collision_fraction=0.01).observation_count, 50)


class CompactionDomainTests(unittest.TestCase):
    def replica(self):
        result = Replica("n", ["s"], 1, ["a", "b"])
        result.add(EvidenceCell("a", "b", 1, "s", Vote.SAME, "synthetic"))
        return result

    def test_noninteger_floors_cannot_corrupt_exported_state(self):
        for floor in (True, 1.0, -2, "1"):
            replica = self.replica()
            before = replica.export_state()
            with self.subTest(floor=floor), self.assertRaises(ValueError):
                replica.compact({("a", "b"): floor}, 0)
            self.assertEqual(replica.export_state(), before)

    def test_pending_allowance_requires_integer_counts(self):
        for pending in (True, 0.5, "0", -1):
            replica = self.replica()
            before = replica.export_state()
            with self.subTest(pending=pending), self.assertRaises(ValueError):
                replica.compact({("a", "b"): 1}, pending)
            self.assertEqual(replica.export_state(), before)

    def test_integer_floor_and_no_floor_sentinel_roundtrip(self):
        replica = self.replica()
        self.assertEqual(replica.compact({("a", "b"): -1}, 0), 0)
        replica.compact({("a", "b"): 1}, 0)
        self.assertEqual(Replica.import_state(replica.export_state()).export_state(), replica.export_state())


class SealingMeasurementTests(unittest.TestCase):
    def test_every_small_conflicting_schedule_runs_both_rules(self):
        votes = ["same", "same", "different", "unknown", "unknown"]
        outcomes = [sealing.transient_merges(order) for order in itertools.permutations(votes)]
        self.assertEqual(sum(unsafe for unsafe, _ in outcomes), 40)
        self.assertEqual(sum(sealed for _, sealed in outcomes), 0)

    def test_counter_observes_a_changed_model_instead_of_assuming_zero(self):
        class PositiveModel(Replica):
            def decisions(self):
                return {key: replace(value, vote=Vote.SAME) for key, value in super().decisions().items()}

        with patch.object(sealing, "Replica", PositiveModel):
            _, observed = sealing.transient_merges(["same", "same", "different", "unknown", "unknown"])
        self.assertTrue(observed)


class EqualWorkTimingTests(unittest.TestCase):
    def rows(self):
        with (ROOT / "results/equal_work.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def test_new_environment_timings_reaggregate_without_historical_gate(self):
        rows = self.rows()
        for row in rows:
            row["elapsed_seconds"] = str(float(row["elapsed_seconds"]) + 1.0)
        summary = {"cases": len(rows), "architectures": equal.independently_aggregate(rows)}
        equal.verify_summary(rows, summary)

    def test_incorrect_current_aggregation_and_scientific_predicates_still_fail(self):
        rows = self.rows()
        summary = {"cases": len(rows), "architectures": equal.independently_aggregate(rows)}
        bad = copy.deepcopy(summary)
        bad["architectures"]["peer-evidence"]["elapsed_seconds_median"] += 1
        with self.assertRaisesRegex(RuntimeError, "numeric value differs"):
            equal.verify_summary(rows, bad)
        for row in rows:
            if row["architecture"] == "peer-evidence":
                row["restart_recovered"] = "0"
        bad = {"cases": len(rows), "architectures": equal.independently_aggregate(rows)}
        with self.assertRaisesRegex(RuntimeError, "restart predicate"):
            equal.verify_summary(rows, bad)


if __name__ == "__main__":
    unittest.main()
