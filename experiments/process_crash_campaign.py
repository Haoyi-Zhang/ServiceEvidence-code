#!/usr/bin/env python3
"""Independent-process recovery campaign for acknowledged evidence snapshots.

Four localhost service processes own separate snapshot files.  The orchestrator
injects source-local batches, creates a two-by-two reachability partition,
forces an abrupt process exit after an acknowledged commit, restarts that node
from its snapshot, heals through peer pulls, and repeats an abrupt restart after
convergence.  The campaign does not inject a crash inside a write and therefore
makes no torn-write or power-loss claim.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from cie.model import Replica
from cie.service import WireStats, rpc
from cie.workload import generate_workload

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MEMBERS = ("p0", "p1", "p2", "p3")
PARTITIONS = ((0, 1), (2, 3))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def scientific_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if key != "node_id"}


def load_checker():
    path = ROOT / "checker" / "verify.py"
    specification = importlib.util.spec_from_file_location("process_crash_checker", path)
    module = importlib.util.module_from_spec(specification)
    if specification.loader is None:
        raise RuntimeError("could not load certificate checker")
    specification.loader.exec_module(module)
    return module


@dataclass
class Child:
    node: str
    snapshot: Path
    process: asyncio.subprocess.Process
    port: int


async def start_child(node: str, snapshot: Path, sources: tuple[str, ...]) -> Child:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "cie.service",
        "--node",
        node,
        "--members",
        ",".join(MEMBERS),
        "--sources",
        ",".join(sources),
        "--threshold",
        "2",
        "--snapshot",
        str(snapshot),
        "--port",
        "0",
        cwd=str(ROOT),
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if not line:
        error = (await process.stderr.read()).decode("utf-8", "replace")
        await process.wait()
        raise RuntimeError(f"service process failed before readiness: {error[:500]}")
    try:
        ready = json.loads(line)
        port = ready["port"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        process.kill()
        await process.wait()
        raise RuntimeError("service process emitted an invalid readiness record") from error
    if ready.get("node") != node or type(port) is not int:
        process.kill()
        await process.wait()
        raise RuntimeError("service process readiness record does not match configuration")
    return Child(node=node, snapshot=snapshot, process=process, port=port)


async def abrupt_stop(child: Child) -> None:
    if child.process.returncode is None:
        child.process.kill()
        await asyncio.wait_for(child.process.wait(), timeout=10.0)


async def orderly_cleanup(child: Child) -> None:
    if child.process.returncode is not None:
        return
    child.process.terminate()
    try:
        await asyncio.wait_for(child.process.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        child.process.kill()
        await asyncio.wait_for(child.process.wait(), timeout=10.0)


async def pull_partition(children: list[Child], stats: WireStats) -> None:
    for group in PARTITIONS:
        for destination in group:
            for peer in group:
                if destination != peer:
                    await rpc(
                        children[destination].port,
                        {"op": "pull", "peer_port": children[peer].port},
                        stats,
                    )


async def query_all(children: list[Child], query: tuple[str, str], stats: WireStats) -> list[dict]:
    return [
        await rpc(
            child.port,
            {"op": "query", "left": query[0], "right": query[1]},
            stats,
        )
        for child in children
    ]


async def run_case(services: int, seed: int) -> tuple[dict, dict]:
    started = time.perf_counter()
    checker = load_checker()
    workload = generate_workload(services, sparse_fraction=0.0, seed=seed)
    require(len(workload.cells) <= 2_300, "process campaign cell cap exceeded")
    require(len(workload.sources) == 5, "process campaign source layout changed")
    query = workload.query_pairs[0]
    owner = {source: (0 if index == 4 else index) for index, source in enumerate(workload.sources)}
    batches = {
        index: [cell.to_dict() for cell in workload.cells if owner[cell.source] == index]
        for index in range(len(MEMBERS))
    }
    stats = WireStats(request_cap=1_000, byte_cap=40 * 1024 * 1024)
    certificates_verified = 0

    with tempfile.TemporaryDirectory(prefix="cie-process-crash-") as temporary:
        directory = Path(temporary)
        children: list[Child] = []
        try:
            for member in MEMBERS:
                children.append(
                    await start_child(member, directory / f"{member}.json", workload.sources)
                )
            require(len(children) == 4, "campaign must use exactly four child processes")

            # Acknowledged source-local commits. p0 owns v0 and v4 so that all
            # five sources fit inside the four-child process cap.
            for index, child in enumerate(children):
                await rpc(child.port, {"op": "ingest", "cells": batches[index]}, stats)

            await pull_partition(children, stats)
            partition_answers = await query_all(children, query, stats)
            for answer in partition_answers:
                checker.verify(answer["state"], answer["certificate"])
                certificates_verified += 1
                require(
                    answer["certificate"]["kind"] == "ambiguous",
                    "incomplete partition authorized a non-ambiguous answer",
                )

            # Crash one partitioned node only after its state RPC has returned.
            pre_crash = await rpc(children[1].port, {"op": "state"}, stats)
            old = children[1]
            await abrupt_stop(old)
            children[1] = await start_child(old.node, old.snapshot, workload.sources)
            recovered = await rpc(children[1].port, {"op": "state"}, stats)
            preheal_recovered = scientific_state(recovered) == scientific_state(pre_crash)
            require(preheal_recovered, "partition-time acknowledged snapshot did not recover")
            recovered_answer = await rpc(
                children[1].port,
                {"op": "query", "left": query[0], "right": query[1]},
                stats,
            )
            checker.verify(recovered_answer["state"], recovered_answer["certificate"])
            certificates_verified += 1
            require(
                recovered_answer["certificate"]["kind"] == "ambiguous",
                "restarted partitioned node changed the incomplete decision",
            )

            # Repair is peer-driven. The complete expected state is consulted
            # only after convergence as an oracle, never as a repair input.
            heal_rounds = 0
            states: list[dict] = []
            for _ in range(4):
                heal_rounds += 1
                for destination in range(len(children)):
                    for peer in range(len(children)):
                        if destination != peer:
                            await rpc(
                                children[destination].port,
                                {"op": "pull", "peer_port": children[peer].port},
                                stats,
                            )
                states = [await rpc(child.port, {"op": "state"}, stats) for child in children]
                if all(
                    scientific_state(state) == scientific_state(states[0])
                    for state in states[1:]
                ):
                    break
            final_states_equal = bool(states) and all(
                scientific_state(state) == scientific_state(states[0]) for state in states[1:]
            )
            require(final_states_equal, "independent processes failed to converge")

            expected = Replica("expected", workload.sources, 2, workload.handles)
            for cell in workload.cells:
                expected.add(cell)
            expected_state_equal = (
                scientific_state(states[0]) == scientific_state(expected.export_state())
            )
            require(expected_state_equal, "process campaign lost scheduled evidence")

            final_answers = await query_all(children, query, stats)
            for answer in final_answers:
                checker.verify(answer["state"], answer["certificate"])
                certificates_verified += 1
                require(answer["certificate"]["kind"] == "same", "healed query is not SAME")

            # Repeat an abrupt restart after convergence and verify both state
            # and a freshly generated certificate from the recovered process.
            final_reference = states[0]
            old = children[3]
            await abrupt_stop(old)
            children[3] = await start_child(old.node, old.snapshot, workload.sources)
            postheal_answer = await rpc(
                children[3].port,
                {"op": "query", "left": query[0], "right": query[1]},
                stats,
            )
            checker.verify(postheal_answer["state"], postheal_answer["certificate"])
            certificates_verified += 1
            postheal_recovered = (
                scientific_state(postheal_answer["state"])
                == scientific_state(final_reference)
                and postheal_answer["certificate"]["kind"] == "same"
            )
            require(postheal_recovered, "converged acknowledged snapshot did not recover")

            final_snapshot_bytes = sum(child.snapshot.stat().st_size for child in children)
            row = {
                "seed": seed,
                "services": services,
                "input_cells": len(workload.cells),
                "processes": len(children),
                "sources": len(workload.sources),
                "partition_groups": 2,
                "partition_ambiguous": sum(
                    answer["certificate"]["kind"] == "ambiguous"
                    for answer in partition_answers
                ),
                "abrupt_crashes": 2,
                "successful_restarts": int(preheal_recovered) + int(postheal_recovered),
                "heal_rounds": heal_rounds,
                "final_cells": len(Replica.import_state(final_reference)),
                "final_kind": postheal_answer["certificate"]["kind"],
                "final_states_equal": int(final_states_equal),
                "expected_state_equal": int(expected_state_equal),
                "certificates_verified": certificates_verified,
                "orchestrator_requests": stats.requests,
                "final_snapshot_bytes": final_snapshot_bytes,
                "elapsed_seconds": time.perf_counter() - started,
            }
            detail = {
                "result": row,
                "partition_kinds": [
                    answer["certificate"]["kind"] for answer in partition_answers
                ],
                "recovered_partition_kind": recovered_answer["certificate"]["kind"],
                "final_answer": final_answers[0],
                "postheal_recovered_answer": postheal_answer,
                "crash_boundary": (
                    "SIGKILL after acknowledged commits; no mid-write or power-loss injection"
                ),
            }
            return row, detail
        finally:
            for child in children:
                await orderly_cleanup(child)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


async def campaign(services: int, seeds: tuple[int, ...]) -> list[dict]:
    rows = []
    detail_root = RESULTS / "process_crash"
    detail_root.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        row, detail = await asyncio.wait_for(run_case(services, seed), timeout=120.0)
        rows.append(row)
        (detail_root / f"seed-{seed}.json").write_text(
            json.dumps(detail, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", type=int, choices=[20, 100], default=100)
    parser.add_argument("--seeds", default="1,2,3")
    args = parser.parse_args()
    seeds = tuple(int(piece) for piece in args.seeds.split(",") if piece)
    if not seeds or len(set(seeds)) != len(seeds) or any(seed not in range(1, 6) for seed in seeds):
        parser.error("seeds must be a unique non-empty subset of 1..5")
    rows = asyncio.run(campaign(args.services, seeds))
    write_csv(RESULTS / "process_crash.csv", rows)
    summary = {
        "cases": len(rows),
        "processes_per_case": 4,
        "services_per_case": args.services,
        "input_cells_per_case": rows[0]["input_cells"],
        "abrupt_crashes": sum(row["abrupt_crashes"] for row in rows),
        "successful_restarts": sum(row["successful_restarts"] for row in rows),
        "all_partition_answers_ambiguous": all(row["partition_ambiguous"] == 4 for row in rows),
        "all_final_states_equal": all(row["final_states_equal"] == 1 for row in rows),
        "all_expected_states_equal": all(row["expected_state_equal"] == 1 for row in rows),
        "all_final_same": all(row["final_kind"] == "same" for row in rows),
        "certificates_verified": sum(row["certificates_verified"] for row in rows),
        "heal_rounds_range": [min(row["heal_rounds"] for row in rows), max(row["heal_rounds"] for row in rows)],
        "elapsed_seconds_range": [min(row["elapsed_seconds"] for row in rows), max(row["elapsed_seconds"] for row in rows)],
        "crash_boundary": "SIGKILL after acknowledged commits; no mid-write or power-loss injection",
    }
    require(summary["successful_restarts"] == 2 * len(rows), "not every abrupt restart recovered")
    require(summary["all_partition_answers_ambiguous"], "partition safety predicate failed")
    require(summary["all_final_states_equal"], "convergence predicate failed")
    require(summary["all_expected_states_equal"], "evidence-completeness predicate failed")
    require(summary["all_final_same"], "final certificate predicate failed")
    (RESULTS / "process_crash_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
