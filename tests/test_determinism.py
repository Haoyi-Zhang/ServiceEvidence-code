import os
from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CrossProcessDeterminismTests(unittest.TestCase):
    def test_state_view_and_certificate_ignore_hash_seed(self):
        program = textwrap.dedent(
            """
            import json
            from cie.model import EvidenceCell, Replica, Vote

            sources = ("v0", "v1", "v2")
            cells = {
                EvidenceCell("a", "b", 0, "v0", Vote.SAME, "x"),
                EvidenceCell("a", "b", 0, "v1", Vote.SAME, "x"),
                EvidenceCell("a", "b", 0, "v2", Vote.UNKNOWN, "x"),
                EvidenceCell("b", "c", 0, "v0", Vote.UNKNOWN, "x"),
                EvidenceCell("b", "c", 0, "v1", Vote.UNKNOWN, "x"),
                EvidenceCell("b", "c", 0, "v2", Vote.UNKNOWN, "x"),
                EvidenceCell("c", "d", 0, "v0", Vote.SAME, "x"),
                EvidenceCell("c", "d", 0, "v1", Vote.SAME, "x"),
                EvidenceCell("c", "d", 0, "v2", Vote.UNKNOWN, "x"),
                EvidenceCell("a", "d", 0, "v0", Vote.DIFFERENT, "x"),
                EvidenceCell("a", "d", 0, "v1", Vote.UNKNOWN, "x"),
                EvidenceCell("a", "d", 0, "v2", Vote.UNKNOWN, "x"),
            }
            replica = Replica("n0", sources, 2, handles={"d", "c", "b", "a"})
            for cell in cells:
                replica.add(cell)
            view = replica.materialize()
            payload = {
                "state": replica.export_state(),
                "components": view.components,
                "accepted": view.accepted_same_edges,
                "rejected": view.rejected_same_edges,
                "different": view.different_edges,
                "certificate": replica.certificate("b", "d"),
            }
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            """
        )
        outputs = []
        for seed in ("0", "1", "2", "17", "101"):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = str(ROOT / "src")
            completed = subprocess.run(
                ["python3", "-c", program],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            outputs.append(completed.stdout)
        self.assertTrue(all(output == outputs[0] for output in outputs[1:]))


if __name__ == "__main__":
    unittest.main()
