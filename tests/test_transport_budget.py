"""Frame-budget regressions for state-coupled certificate responses."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from cie.model import EvidenceCell, Replica, Vote
from cie.service import FRAME_LIMIT, Service, pack, rpc

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "transport_budget_checker", ROOT / "checker" / "verify.py"
)
checker = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(checker)


def encoded_size(value: object) -> int:
    return len(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )


class TransportBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_admitted_large_state_uses_verifiable_key_references(self):
        # This is a static boundary regression, not a performance measurement.
        replica = Replica("node-0", ["x", "y"], 2, ["a", "b"])
        reason = "r" * 1_100_000
        for source in replica.sources:
            replica.add(EvidenceCell("a", "b", 0, source, Vote.SAME, reason))

        state = replica.export_state()
        full_certificate = replica.certificate("a", "b")
        self.assertEqual(encoded_size(state), 2_200_251)
        self.assertGreater(
            encoded_size(
                {"ok": True, "result": {"state": state, "certificate": full_certificate}}
            ),
            FRAME_LIMIT,
        )
        # State admission still succeeds: the response path must handle the
        # duplicated evidence rather than silently closing the connection.
        pack(state)

        with tempfile.TemporaryDirectory() as directory:
            service = Service(
                "node-0",
                ["x", "y"],
                2,
                ["a", "b"],
                ["node-0"],
                Path(directory) / "state.json",
            )
            service._commit(replica)
            port = await service.start()
            try:
                result = await rpc(port, {"op": "query", "left": "a", "right": "b"})
            finally:
                await service.close()

        certificate = result["certificate"]
        self.assertEqual(certificate.get("evidence_encoding"), "state-cell-keys")
        self.assertNotIn("cells", certificate["support"][0])
        checker.verify(result["state"], certificate)
        self.assertLessEqual(
            encoded_size({"ok": True, "result": result}), FRAME_LIMIT
        )

    async def test_uncompactable_query_returns_explicit_error_over_socket(self):
        # The admitted state is just below the payload limit, but adding even an
        # ambiguity certificate crosses it.  The peer must return a framed
        # rejection instead of closing before a response header is received.
        replica = Replica("node-0", ["x", "y"], 2, ["a", "b"])
        reason = "r" * 2_096_900
        for source in replica.sources:
            replica.add(EvidenceCell("a", "b", 0, source, Vote.UNKNOWN, reason))
        state = replica.export_state()
        self.assertLessEqual(encoded_size(state), FRAME_LIMIT)
        self.assertGreater(
            encoded_size(
                {
                    "ok": True,
                    "result": {
                        "state": state,
                        "certificate": replica.certificate("a", "b"),
                    },
                }
            ),
            FRAME_LIMIT,
        )

        with tempfile.TemporaryDirectory() as directory:
            service = Service(
                "node-0",
                ["x", "y"],
                2,
                ["a", "b"],
                ["node-0"],
                Path(directory) / "state.json",
            )
            service._commit(replica)
            port = await service.start()
            try:
                with self.assertRaisesRegex(
                    ValueError, "response exceeds bounded service limit"
                ):
                    await rpc(port, {"op": "query", "left": "a", "right": "b"})
            finally:
                await service.close()


if __name__ == "__main__":
    unittest.main()
