import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cie.model import EvidenceCell, Vote
from cie.service import Service, WireStats, pack, rpc


class ServiceDurabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.snapshot = Path(self.temporary.name) / "state.json"
        self.sources = ["v0", "v1"]
        self.members = ["n0"]

    def service(self, *, stats=None):
        return Service(
            "n0",
            self.sources,
            1,
            [],
            self.members,
            self.snapshot,
            stats=stats,
        )

    @staticmethod
    def cell(left="a", right="b", epoch=0, source="v0", vote=Vote.SAME):
        return EvidenceCell(left, right, epoch, source, vote, "durability-test")

    async def ingest(self, service, *cells):
        return await service.dispatch(
            {"op": "ingest", "cells": [cell.to_dict() for cell in cells]}
        )

    async def test_replace_failure_preserves_memory_and_previous_snapshot(self):
        service = self.service()
        await self.ingest(service, self.cell())
        before_memory = service.replica.export_state()
        before_disk = self.snapshot.read_text(encoding="utf-8")

        with patch("cie.service.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                await self.ingest(service, self.cell("c", "d"))

        self.assertEqual(service.replica.export_state(), before_memory)
        self.assertEqual(self.snapshot.read_text(encoding="utf-8"), before_disk)
        self.assertFalse(self.snapshot.with_suffix(".pending").exists())

    async def test_directory_fsync_failure_has_idempotent_ambiguous_outcome(self):
        stats = WireStats()
        service = self.service(stats=stats)
        cell = self.cell()

        with patch("cie.service.fsync_directory", side_effect=OSError("directory fsync failed")):
            with self.assertRaises(OSError):
                await self.ingest(service, cell)

        # Replace already succeeded.  The RPC is unacknowledged, but the live
        # process and the visible snapshot agree; retrying the immutable cell is
        # idempotent rather than duplicating evidence.
        self.assertEqual(len(service.replica), 1)
        saved = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["cells"]), 1)
        self.assertEqual(stats.commits, 0)
        self.assertFalse(self.snapshot.with_suffix(".pending").exists())

        result = await self.ingest(service, cell)
        self.assertEqual(result["cells"], 1)
        self.assertEqual(stats.commits, 1)
        restarted = self.service()
        self.assertEqual(restarted.replica.export_state(), service.replica.export_state())

    async def test_concurrent_ingests_serialize_without_lost_update(self):
        service = self.service()
        cells = [
            self.cell(f"h{2 * index:02d}", f"h{2 * index + 1:02d}")
            for index in range(20)
        ]
        await asyncio.gather(*(self.ingest(service, cell) for cell in cells))
        self.assertEqual(len(service.replica), len(cells))
        restarted = self.service()
        self.assertEqual(restarted.replica.export_state(), service.replica.export_state())

    async def test_acknowledgement_is_read_only(self):
        stats = WireStats()
        service = self.service(stats=stats)
        await self.ingest(
            service,
            self.cell(source="v0"),
            self.cell(source="v1", vote=Vote.UNKNOWN),
        )
        before = self.snapshot.read_text(encoding="utf-8")
        commits = stats.commits
        answer = await service.dispatch({"op": "ack", "floors": [["a", "b", 0]]})
        self.assertEqual(answer["member"], "n0")
        self.assertEqual(len(answer["vectors"]), 2)
        self.assertEqual(stats.commits, commits)
        self.assertEqual(self.snapshot.read_text(encoding="utf-8"), before)


    async def test_rpc_does_not_hang_when_peer_close_never_completes(self):
        reader = asyncio.StreamReader()
        reader.feed_data(pack({"ok": True, "result": {"value": 7}}))
        reader.feed_eof()

        class HangingWriter:
            def __init__(self):
                self.closed = False

            def write(self, _payload):
                return None

            async def drain(self):
                return None

            def close(self):
                self.closed = True

            async def wait_closed(self):
                await asyncio.sleep(60)

        writer = HangingWriter()
        with patch("cie.service.asyncio.open_connection", return_value=(reader, writer)), \
             patch("cie.service.RPC_TIMEOUT", 0.01):
            answer = await rpc(1, {"op": "state"})
        self.assertEqual(answer, {"value": 7})
        self.assertTrue(writer.closed)

    async def test_unacknowledged_pending_file_is_discarded_on_restart(self):
        service = self.service()
        await self.ingest(service, self.cell())
        pending = self.snapshot.with_suffix(".pending")
        pending.write_text('{"incomplete":', encoding="utf-8")
        restarted = self.service()
        self.assertFalse(pending.exists())
        self.assertEqual(restarted.replica.export_state(), service.replica.export_state())


if __name__ == "__main__":
    unittest.main()
