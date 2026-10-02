#!/usr/bin/env python3
"""Five-endpoint loopback campaign; no global-state oracle is used for repair."""
from __future__ import annotations
import argparse
import asyncio
import csv
import json
from pathlib import Path
import random
import resource
import statistics
import tempfile
import time

from cie.model import Replica
from cie.service import Service, WireStats, rpc, common_floor_reports
from cie.workload import generate_workload

ROOT = Path(__file__).resolve().parents[1]


def scientific_state(state):
    return {k: v for k, v in state.items() if k != "node_id"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


async def case(service_count: int, seed: int, output: Path, public=None):
    start = time.perf_counter()
    cpu_start = time.process_time()
    rng = random.Random(seed)
    workload = generate_workload(service_count, seed=seed, sparse_fraction=0)
    handles = list(workload.handles) if public is None else public[0]
    cells = list(workload.cells) if public is None else public[1]
    sources = list(workload.sources)
    require(len(cells) <= (500 if service_count == 20 else 2300), "frozen cell cap")
    members = [f"n{i}" for i in range(5)]
    stats = WireStats()
    events = []
    with tempfile.TemporaryDirectory(prefix="cie-sockets-") as directory:
        nodes = [Service(m, sources, 2, handles, members, Path(directory) / (m + ".json"), stats)
                 for m in members]
        ports = [await node.start() for node in nodes]
        try:
            # Every cell initially exists at exactly its source's owner. This is
            # fixture injection, not repair, and all injection crosses TCP.
            for i, port in enumerate(ports):
                await rpc(port, {"op": "ingest", "cells": [c.to_dict() for c in cells if c.source == sources[i]]}, stats)
            snapshots = [await rpc(p, {"op": "state"}, stats) for p in ports]
            stale = snapshots[-1]
            require(any(scientific_state(s) != scientific_state(snapshots[0]) for s in snapshots[1:]),
                    "repair-disabled negative control unexpectedly converged")
            negative_control = True
            query_pair = [cells[0].left, cells[0].right]
            omitted = duplicates = 0
            for round_no in range(3):
                links = [(i, j) for i in range(5) for j in range(5) if i != j]
                rng.shuffle(links)
                for i, j in links:
                    if (i < 2) != (j < 2) or rng.random() < 0.2:
                        omitted += 1
                        events.append({"round": round_no, "destination": members[i], "peer": members[j], "action": "omit"})
                        continue
                    await asyncio.sleep(rng.randint(0, 2) / 1000)
                    await rpc(ports[i], {"op": "pull", "peer_port": ports[j]}, stats)
                    events.append({"round": round_no, "destination": members[i], "peer": members[j], "action": "pull"})
                    if rng.random() < 0.25:
                        await rpc(ports[i], {"op": "pull", "peer_port": ports[j]}, stats)
                        duplicates += 1
                        events.append({"round": round_no, "destination": members[i], "peer": members[j], "action": "duplicate"})
            before_heal = [await rpc(p, {"op": "state"}, stats) for p in ports]
            require(any(scientific_state(s) != scientific_state(before_heal[0]) for s in before_heal[1:]),
                    "partition negative control unexpectedly converged")
            partition_answers = [await rpc(p, {"op": "query", "left": query_pair[0], "right": query_pair[1]}, stats) for p in ports]
            require(all(answer["certificate"]["kind"] == "ambiguous" for answer in partition_answers), "partial source groups authorized the example query")
            fair_rounds = 0
            for round_no in range(3, 11):
                fair_rounds += 1
                links = [(i, j) for i in range(5) for j in range(5) if i != j]
                rng.shuffle(links)
                for i, j in links:
                    await rpc(ports[i], {"op": "pull", "peer_port": ports[j]}, stats)
                    events.append({"round": round_no, "destination": members[i], "peer": members[j], "action": "pull"})
                snapshots = [await rpc(p, {"op": "state"}, stats) for p in ports]
                if all(scientific_state(s) == scientific_state(snapshots[0]) for s in snapshots[1:]):
                    break
            require(all(scientific_state(s) == scientific_state(snapshots[0]) for s in snapshots[1:]), "peer repair did not converge")
            # The oracle is consulted only now, never by a node or repair RPC.
            central_start = time.perf_counter()
            oracle = Replica("expected", sources, 2, handles)
            for cell in cells:
                oracle.add(cell)
            central_view = oracle.materialize()
            centralized_seconds = time.perf_counter() - central_start
            require(scientific_state(snapshots[0]) == scientific_state(oracle.export_state()), "converged state lacks injected evidence")
            healed_answers = [await rpc(p, {"op": "query", "left": query_pair[0], "right": query_pair[1]}, stats) for p in ports]
            expected_answer = "same" if public is None else "ambiguous"
            require(all(answer["certificate"]["kind"] == expected_answer for answer in healed_answers), "completed source vector has wrong query result")
            reports = [await rpc(p, {"op": "report"}, stats) for p in ports]
            floors = common_floor_reports([r["sealed"] for r in reports])
            acks = [await rpc(p, {"op": "ack", "floors": floors}, stats) for p in ports]
            try:
                await rpc(ports[0], {"op": "compact", "floors": floors, "acks": acks[:-1]}, stats)
            except ValueError:
                rejected_missing_ack = True
            else:
                raise RuntimeError("missing acknowledgement accepted")
            require(await rpc(ports[0], {"op": "state"}, stats) == snapshots[0], "failed compaction changed state")
            await rpc(ports[0], {"op": "compact", "floors": floors, "acks": acks, "pending": 1}, stats)
            compacted = await rpc(ports[0], {"op": "state"}, stats)
            for i in range(1, 5):
                await rpc(ports[i], {"op": "pull", "peer_port": ports[0]}, stats)
            # An obsolete snapshot must not resurrect cells, even after a restart.
            await rpc(ports[-1], {"op": "merge", "state": stale}, stats)
            old_port = ports[-1]
            await nodes[-1].close()
            nodes[-1] = Service(members[-1], sources, 2, handles, members, Path(directory) / (members[-1] + ".json"), stats)
            ports[-1] = await nodes[-1].start(old_port)
            after = [await rpc(p, {"op": "state"}, stats) for p in ports]
            require(all(scientific_state(s) == scientific_state(compacted) for s in after), "floors or stale suppression disagree after restart")
            final = Replica.import_state(after[0])
            require(final.materialize().components == oracle.materialize().components, "compaction changed view")
            # Failure after a valid first cell in a batch must be atomic.
            bad_batch = [cells[0].to_dict(), dict(cells[0].to_dict(), epoch=True)]
            prior = await rpc(ports[0], {"op": "state"}, stats)
            try:
                await rpc(ports[0], {"op": "ingest", "cells": bad_batch}, stats)
            except ValueError:
                pass
            else:
                raise RuntimeError("malformed batch accepted")
            require(await rpc(ports[0], {"op": "state"}, stats) == prior, "malformed batch partially committed")
            row = {
                "case": "public" if public is not None else ("pilot" if service_count == 20 else "generated"),
                "seed": seed, "services": service_count if public is None else 0,
                "handles": len(handles), "input_cells": len(cells), "endpoints": 5,
                "fault_rounds": 3, "fair_rounds": fair_rounds, "omitted_pulls": omitted,
                "partition_query_kind": "ambiguous", "healed_query_kind": expected_answer,
                "centralized_seconds": centralized_seconds,
                "duplicate_pulls": duplicates, "requests": stats.requests,
                "request_bytes": stats.request_bytes, "response_bytes": stats.response_bytes,
                "wire_bytes": stats.total_bytes, "cells_after_compaction": len(final),
                "converged": True, "matches_oracle": True, "repair_disabled_not_converged": negative_control,
                "missing_ack_rejected": rejected_missing_ack, "restart_preserves_floor": True,
                "stale_state_not_resurrected": True, "malformed_batch_atomic": True,
                "elapsed_seconds": time.perf_counter() - start,
                "cpu_seconds": time.process_time() - cpu_start,
                "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "rpc_median_ms": statistics.median(stats.latency_ms),
                "rpc_p95_ms": sorted(stats.latency_ms)[int(0.95 * (len(stats.latency_ms) - 1))],
            }
            output.mkdir(parents=True, exist_ok=True)
            (output / "result.json").write_text(json.dumps(row, indent=2) + "\n")
            (output / "query_answers.json").write_text(json.dumps({"partition": partition_answers, "healed": healed_answers}, indent=2) + "\n")
            (output / "events.json").write_text(json.dumps(events, indent=2) + "\n")
            (output / "final_state.json").write_text(json.dumps(after[0], indent=2) + "\n")
            return row
        finally:
            for node in nodes:
                await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", type=int, choices=[20, 100], default=20)
    parser.add_argument("--seed", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    public = None
    if args.public:
        from cie.http_adapter import archived_candidates
        public = archived_candidates(ROOT / "external_inputs/public_http_calibration.csv")
    name = "public" if args.public else ("pilot" if args.services == 20 else f"generated-{args.seed}")
    result = asyncio.run(asyncio.wait_for(case(args.services, args.seed, ROOT / "results/socket" / name, public), 120))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
