import asyncio
from pathlib import Path
import tempfile
import unittest

from cie.service import Service, WireStats, rpc
from cie.workload import generate_workload


class EqualWorkPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_query_work_is_counted_and_recoverable(self):
        workload = generate_workload(2, sparse_fraction=0.0, seed=1)
        stats = WireStats()
        with tempfile.TemporaryDirectory(prefix="cie-test-authority-") as temporary:
            snapshot = Path(temporary) / "authority.json"
            service = Service(
                "authority",
                list(workload.sources),
                2,
                list(workload.handles),
                ["authority"],
                snapshot,
                stats,
            )
            port = await service.start()
            try:
                await rpc(
                    port,
                    {"op": "ingest", "cells": [cell.to_dict() for cell in workload.cells]},
                    stats,
                )
                query = workload.query_pairs[0]
                answer = await rpc(
                    port,
                    {"op": "query", "left": query[0], "right": query[1]},
                    stats,
                )
                self.assertEqual(answer["certificate"]["kind"], "same")
                self.assertEqual(stats.commits, 1)
                self.assertEqual(stats.fsyncs, 2)
                self.assertGreater(stats.snapshot_bytes, 0)
                self.assertEqual(stats.certificate_generations, 1)
                self.assertEqual(len(stats.certificate_generation_ms), 1)
            finally:
                await service.close()

            recovered = Service(
                "authority",
                list(workload.sources),
                2,
                list(workload.handles),
                ["authority"],
                snapshot,
                stats,
            )
            recovered_port = await recovered.start()
            try:
                state = await rpc(recovered_port, {"op": "state"}, stats)
                self.assertEqual(len(state["cells"]), len(workload.cells))
            finally:
                await recovered.close()


if __name__ == "__main__":
    unittest.main()
