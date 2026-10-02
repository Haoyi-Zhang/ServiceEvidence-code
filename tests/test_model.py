from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cie.model import EvidenceCell, Replica, Vote, relation
from cie.simulator import emulate, stable_epochs
from cie.workload import generate_workload


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.sources = ("v0", "v1", "v2", "v3", "v4")
        self.root = Path(__file__).resolve().parents[1]
        self.checker = self.root / "checker" / "verify.py"

    def cells_for(self, left, right, epoch, votes):
        edge = relation(left, right)
        return [
            EvidenceCell(edge[0], edge[1], epoch, source, Vote(vote), "test")
            for source, vote in zip(self.sources, votes)
        ]

    def run_checker(self, state, certificate, optimized=False):
        with tempfile.TemporaryDirectory() as temp_directory:
            state_path = Path(temp_directory) / "state.json"
            certificate_path = Path(temp_directory) / "certificate.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            certificate_path.write_text(json.dumps(certificate), encoding="utf-8")
            command = ["python"]
            if optimized:
                command.append("-O")
            command.extend([str(self.checker), str(state_path), str(certificate_path)])
            return subprocess.run(command, check=False, capture_output=True, text=True)

    def test_sealed_epoch_required(self):
        replica = Replica("n0", self.sources, 2)
        cells = self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        )
        for cell in cells[:-1]:
            replica.add(cell)
        self.assertEqual(replica.decisions()[relation("a", "b")].vote, Vote.UNKNOWN)
        self.assertFalse(replica.decisions()[relation("a", "b")].sealed)
        replica.add(cells[-1])
        self.assertEqual(replica.decisions()[relation("a", "b")].vote, Vote.SAME)
        self.assertTrue(replica.decisions()[relation("a", "b")].sealed)

    def test_negative_veto_and_split(self):
        replica = Replica("n0", self.sources, 2)
        for cell in self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        self.assertEqual(len(replica.materialize().components), 1)
        for cell in self.cells_for(
            "a", "b", 1, ["same", "unknown", "different", "unknown", "unknown"]
        ):
            replica.add(cell)
        self.assertEqual(len(replica.materialize().components), 2)

    def test_negative_safe_partition(self):
        replica = Replica("n0", self.sources, 2)
        for cell in self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        for cell in self.cells_for(
            "b", "c", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        for cell in self.cells_for(
            "a", "c", 0, ["different", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        view = replica.materialize()
        self.assertNotEqual(view.component_of["a"], view.component_of["c"])
        self.assertTrue(view.rejected_same_edges)

    def test_join_commutative_associative_idempotent(self):
        workload = generate_workload(12, seed=31)
        chunks = [workload.cells[index::3] for index in range(3)]
        replicas = []
        for index, chunk in enumerate(chunks):
            replica = Replica(
                f"n{index}", workload.sources, 2, handles=workload.handles
            )
            for cell in chunk:
                replica.add(cell)
            replicas.append(replica)
        left = Replica("left", workload.sources, 2, handles=workload.handles)
        left.join(replicas[0])
        left.join(replicas[1])
        left.join(replicas[2])
        left.join(left)
        right = Replica("right", workload.sources, 2, handles=workload.handles)
        temporary = Replica(
            "temporary", workload.sources, 2, handles=workload.handles
        )
        temporary.join(replicas[2])
        temporary.join(replicas[1])
        right.join(temporary)
        right.join(replicas[0])
        self.assertEqual(left.cells, right.cells)
        self.assertEqual(left.handles, right.handles)
        self.assertEqual(left.materialize().components, right.materialize().components)

    def test_floor_aware_join_commutative_associative_idempotent(self):
        edge = relation("a", "b")

        def built(node_id, epochs, floor=None):
            replica = Replica(node_id, self.sources, 2, handles=("a", "b"))
            for epoch, votes in epochs:
                for cell in self.cells_for("a", "b", epoch, votes):
                    replica.add(cell)
            if floor is not None:
                replica.compact({edge: floor}, retain_pending=2)
            return replica

        epoch_zero = ["same", "same", "unknown", "unknown", "unknown"]
        epoch_one = ["same", "unknown", "different", "unknown", "unknown"]
        epoch_two = ["same", "same", "unknown", "unknown", "unknown"]
        replicas = (
            built("a", [(0, epoch_zero), (1, epoch_one)], floor=1),
            built("b", [(0, epoch_zero), (1, epoch_one), (2, epoch_two)], floor=0),
            built("c", [(0, epoch_zero), (1, epoch_one), (2, epoch_two)]),
        )

        left = Replica("left", self.sources, 2, handles=("a", "b"))
        left.join(replicas[0])
        left.join(replicas[1])
        left.join(replicas[2])
        left.join(left)

        temporary = Replica("temporary", self.sources, 2, handles=("a", "b"))
        temporary.join(replicas[2])
        temporary.join(replicas[0])
        right = Replica("right", self.sources, 2, handles=("a", "b"))
        right.join(replicas[1])
        right.join(temporary)

        self.assertEqual(left.stable_floors, {edge: 1})
        self.assertEqual(left.stable_floors, right.stable_floors)
        self.assertEqual(left.cells, right.cells)
        self.assertTrue(all(cell.epoch >= 1 for cell in left.cells))
        self.assertEqual(left.materialize().components, right.materialize().components)

    def test_fault_emulator_converges(self):
        workload = generate_workload(50, seed=9)
        result = emulate(
            workload.cells,
            ("n0", "n1", "n2", "n3", "n4"),
            workload.sources,
            seed=19,
            loss_rate=0.12,
            duplicate_rate=0.20,
            partition_fraction=0.40,
            handles=workload.handles,
        )
        states = [replica.cells for replica in result.replicas.values()]
        self.assertTrue(all(state == states[0] for state in states[1:]))
        self.assertFalse(result.pre_repair_converged)

    def test_compaction_preserves_view(self):
        workload = generate_workload(30, epochs=3, seed=5)
        result = emulate(
            workload.cells,
            ("n0", "n1", "n2", "n3", "n4"),
            workload.sources,
            seed=12,
            handles=workload.handles,
        )
        stable = stable_epochs(result.replicas)
        for replica in result.replicas.values():
            before = replica.materialize().components
            removed = replica.compact(stable, retain_pending=1)
            after = replica.materialize().components
            self.assertGreater(removed, 0)
            self.assertEqual(before, after)

    def test_compaction_without_acknowledged_floor_keeps_every_cell(self):
        replica = Replica("n0", self.sources, 2)
        for epoch in range(3):
            for cell in self.cells_for(
                "a", "b", epoch, ["same", "same", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        before = replica.cells
        removed = replica.compact({}, retain_pending=0)
        self.assertEqual(removed, 0)
        self.assertEqual(replica.cells, before)
        self.assertEqual(replica.stable_floors, {})

    def test_compaction_refuses_excess_pending_epochs_without_mutation(self):
        replica = Replica("n0", self.sources, 2)
        for epoch in range(3):
            for cell in self.cells_for(
                "a", "b", epoch, ["same", "same", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        before = replica.export_state()
        with self.assertRaises(ValueError):
            replica.compact({relation("a", "b"): 0}, retain_pending=1)
        self.assertEqual(replica.export_state(), before)

    def test_compaction_refuses_floor_regression_without_mutation(self):
        replica = Replica("n0", self.sources, 2)
        for epoch in range(2):
            for cell in self.cells_for(
                "a", "b", epoch, ["same", "same", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        replica.compact({relation("a", "b"): 1}, retain_pending=0)
        before = replica.export_state()
        with self.assertRaises(ValueError):
            replica.compact({relation("a", "b"): 0}, retain_pending=0)
        self.assertEqual(replica.export_state(), before)

    def test_compaction_retains_newer_pending_epoch(self):
        replica = Replica("n0", self.sources, 2)
        for cell in self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        pending = self.cells_for(
            "a", "b", 1, ["different", "unknown", "unknown", "unknown", "unknown"]
        )
        replica.add(pending[0])
        before = replica.materialize().components
        replica.compact({relation("a", "b"): 0}, retain_pending=1)
        self.assertEqual(replica.materialize().components, before)
        self.assertIn(pending[0], replica.cells)
        for cell in pending[1:]:
            replica.add(cell)
        self.assertEqual(replica.materialize().components, (("a",), ("b",)))

    def test_compaction_rejects_unsealed_floor(self):
        replica = Replica("n0", self.sources, 2)
        cells = self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        )
        for cell in cells[:-1]:
            replica.add(cell)
        before = replica.export_state()
        with self.assertRaises(ValueError):
            replica.compact({relation("a", "b"): 0}, retain_pending=0)
        self.assertEqual(replica.export_state(), before)

    def test_compaction_floor_prevents_history_resurrection(self):
        compacted = Replica("n0", self.sources, 2)
        stale = Replica("n1", self.sources, 2)
        epoch_zero = self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        )
        epoch_one = self.cells_for(
            "a", "b", 1, ["different", "unknown", "unknown", "unknown", "unknown"]
        )
        for cell in epoch_zero + epoch_one:
            compacted.add(cell)
        for cell in epoch_zero:
            stale.add(cell)
        compacted.compact({relation("a", "b"): 1}, retain_pending=0)
        compacted.join(stale)
        self.assertEqual(len(compacted), len(self.sources))
        self.assertTrue(all(cell.epoch == 1 for cell in compacted.cells))
        self.assertEqual(compacted.materialize().components, (("a",), ("b",)))

    def test_export_import_preserves_handles_floor_and_view(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b", "isolated"))
        for cell in self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        replica.compact({relation("a", "b"): 0}, retain_pending=0)
        restored = Replica.import_state(replica.export_state())
        self.assertEqual(restored.handles, ("a", "b", "isolated"))
        self.assertEqual(restored.stable_floors, {relation("a", "b"): 0})
        self.assertEqual(restored.cells, replica.cells)
        self.assertEqual(restored.materialize().components, replica.materialize().components)

    def test_certificate_rejects_unregistered_query_handle(self):
        replica = Replica("n0", self.sources, 2, handles=("a",))
        with self.assertRaises(ValueError):
            replica.certificate("a", "b")

    def test_ambiguity_diagnostic_for_observed_unknown_relation(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        for cell in self.cells_for(
            "a", "b", 0, ["same", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        certificate = replica.certificate("a", "b")
        self.assertEqual(certificate["kind"], "ambiguous")
        self.assertEqual(certificate["authorization_gap"], 1)
        self.assertTrue(certificate["steps"][0]["observed"])
        self.assertTrue(certificate["steps"][0]["sealed"])
        self.assertEqual(certificate["steps"][0]["same_sources"], ["v0"])
        completed = self.run_checker(replica.export_state(), certificate)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_unsealed_authorization_gap_counts_closure_slots(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        cells = self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        )
        for cell in cells[:2]:
            replica.add(cell)
        certificate = replica.certificate("a", "b")
        step = certificate["steps"][0]
        self.assertEqual(certificate["kind"], "ambiguous")
        self.assertFalse(step["sealed"])
        self.assertEqual(step["same_sources"], ["v0", "v1"])
        self.assertEqual(step["missing_sources"], ["v2", "v3", "v4"])
        self.assertEqual(step["authorization_gap"], 3)
        self.assertEqual(step["gap_sources"], ["v2", "v3", "v4"])
        completed = self.run_checker(replica.export_state(), certificate, optimized=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_ambiguity_diagnostic_for_unobserved_query_relation(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        certificate = replica.certificate("a", "b")
        self.assertEqual(certificate["kind"], "ambiguous")
        self.assertEqual(certificate["authorization_gap"], 5)
        self.assertFalse(certificate["steps"][0]["observed"])
        self.assertIsNone(certificate["steps"][0]["epoch"])
        completed = self.run_checker(replica.export_state(), certificate)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_independent_checker_for_all_certificate_kinds_and_optimized_mode(self):
        workload = generate_workload(20, sparse_fraction=0.20, seed=42)
        replica = Replica("n0", workload.sources, 2, handles=workload.handles)
        for cell in workload.cells:
            replica.add(cell)
        examples = {}
        for left, right in workload.query_pairs:
            certificate = replica.certificate(left, right)
            examples.setdefault(certificate["kind"], certificate)
        self.assertEqual(set(examples), {"same", "different", "ambiguous"})
        state = replica.export_state()
        for certificate in examples.values():
            for optimized in (False, True):
                completed = self.run_checker(state, certificate, optimized=optimized)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("PASS", completed.stdout)

    def test_checker_rejects_tampering_even_with_python_optimized(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        for cell in self.cells_for(
            "a", "b", 0, ["same", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        certificate = replica.certificate("a", "b")
        tampered = copy.deepcopy(certificate)
        tampered["authorization_gap"] += 1
        completed = self.run_checker(
            replica.export_state(), tampered, optimized=True
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("FAIL", completed.stderr)

    def test_checker_rejects_ambiguous_label_when_negative_separator_exists(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        for cell in self.cells_for(
            "a", "b", 0, ["different", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        fake = {
            "kind": "ambiguous",
            "query": ["a", "b"],
            "authorization_gap": 5,
            "edge_count": 1,
            "steps": [
                {
                    "pair": ["a", "b"],
                    "from_component": 0,
                    "to_component": 1,
                    "observed": False,
                    "epoch": None,
                    "sealed": False,
                    "same_sources": [],
                    "missing_sources": ["v0", "v1", "v2", "v3", "v4"],
                    "different_sources": [],
                    "unknown_sources": [],
                    "authorization_gap": 5,
                    "gap_sources": ["v0", "v1", "v2", "v3", "v4"],
                }
            ],
        }
        completed = self.run_checker(replica.export_state(), fake, optimized=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("negative separator", completed.stderr)

    def test_checker_rejects_duplicate_and_equivocating_state_keys(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b"))
        for cell in self.cells_for(
            "a", "b", 0, ["same", "same", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        state = replica.export_state()
        certificate = replica.certificate("a", "b")
        duplicate = copy.deepcopy(state)
        duplicate["cells"].append(copy.deepcopy(duplicate["cells"][0]))
        completed = self.run_checker(duplicate, certificate)
        self.assertNotEqual(completed.returncode, 0)

        equivocation = copy.deepcopy(state)
        conflict = copy.deepcopy(equivocation["cells"][0])
        conflict["vote"] = "different"
        equivocation["cells"].append(conflict)
        completed = self.run_checker(equivocation, certificate, optimized=True)
        self.assertNotEqual(completed.returncode, 0)

    def test_global_ambiguity_avoids_internal_negative_separator(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b", "c", "d"))
        for left, right in (("a", "b"), ("b", "c"), ("c", "d")):
            for cell in self.cells_for(
                left, right, 0, ["same", "unknown", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        for cell in self.cells_for(
            "b", "d", 0, ["different", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        certificate = replica.certificate("a", "d")
        self.assertEqual(certificate["kind"], "ambiguous")
        self.assertTrue(certificate["globally_sufficient"])
        self.assertEqual(certificate["authorization_gap"], 5)
        self.assertEqual(certificate["edge_count"], 1)
        self.assertEqual(certificate["steps"][0]["pair"], ["a", "d"])
        self.assertFalse(certificate["steps"][0]["observed"])
        completed = self.run_checker(replica.export_state(), certificate, optimized=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_global_ambiguity_prefers_safe_observed_path(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b", "c"))
        for left, right in (("a", "b"), ("b", "c")):
            for cell in self.cells_for(
                left, right, 0, ["same", "unknown", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        certificate = replica.certificate("a", "c")
        self.assertEqual(certificate["authorization_gap"], 2)
        self.assertEqual(certificate["edge_count"], 2)
        self.assertEqual(
            [step["pair"] for step in certificate["steps"]],
            [["a", "b"], ["b", "c"]],
        )
        completed = self.run_checker(replica.export_state(), certificate)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_checker_rejects_locally_short_but_globally_incompatible_path(self):
        replica = Replica("n0", self.sources, 2, handles=("a", "b", "c", "d"))
        for left, right in (("a", "b"), ("b", "c"), ("c", "d")):
            for cell in self.cells_for(
                left, right, 0, ["same", "unknown", "unknown", "unknown", "unknown"]
            ):
                replica.add(cell)
        for cell in self.cells_for(
            "b", "d", 0, ["different", "unknown", "unknown", "unknown", "unknown"]
        ):
            replica.add(cell)
        certificate = replica.certificate("a", "d")
        tampered = copy.deepcopy(certificate)
        tampered["authorization_gap"] = 3
        tampered["edge_count"] = 3
        tampered["component_path"] = [0, 1, 2, 3]
        tampered["steps"] = []
        completed = self.run_checker(replica.export_state(), tampered, optimized=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("optimum", completed.stderr)

    def test_equivocation_rejected(self):
        edge = relation("a", "b")
        replica = Replica("n0", self.sources, 2)
        replica.add(EvidenceCell(*edge, 0, "v0", Vote.SAME, "first"))
        with self.assertRaises(ValueError):
            replica.add(EvidenceCell(*edge, 0, "v0", Vote.DIFFERENT, "second"))


if __name__ == "__main__":
    unittest.main()
