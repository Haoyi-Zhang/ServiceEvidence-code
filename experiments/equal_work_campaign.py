#!/usr/bin/env python3
"""Paired loopback comparison of peer, central, and quorum architectures.

All three architectures use the same evidence semantics, TCP framing, atomic
snapshot replacement, query certificates, workload, and client partition.  The
fault is an application-level reachability partition, not packet manipulation.
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
import statistics
import tempfile
import time
from typing import Iterable

from cie.metrics import partition_metrics
from cie.model import EvidenceCell, Replica
from cie.service import Service, WireStats, fsync_directory, rpc
from cie.workload import generate_workload

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
AUTHORITY_PLACEMENTS = {"q0": 0, "q1": 2, "q2": 4}
LAYOUTS = {
    "authority-minority": ((0, 1), (2, 3, 4)),
    "authority-majority": ((0, 2, 4), (1, 3)),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def scientific_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if key != "node_id"}


def group_for(client: int, groups: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    for group in groups:
        if client in group:
            return group
    raise ValueError("client is absent from partition layout")


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[int(quantile * (len(ordered) - 1))]


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


@dataclass
class SpoolStats:
    fsyncs: int = 0
    bytes_written: int = 0


def spool_batch(path: Path, cells: Iterable[EvidenceCell], stats: SpoolStats) -> None:
    raw = json.dumps(
        [cell.to_dict() for cell in cells], sort_keys=True, separators=(",", ":")
    )
    temporary = path.with_suffix(".pending")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)
    stats.fsyncs += 2
    stats.bytes_written += len(raw.encode("utf-8"))


def load_spool(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("client spool must contain a cell list")
    return raw


def load_checker():
    path = ROOT / "checker" / "verify.py"
    specification = importlib.util.spec_from_file_location("equal_work_checker", path)
    module = importlib.util.module_from_spec(specification)
    if specification.loader is None:
        raise RuntimeError("could not load certificate checker")
    specification.loader.exec_module(module)
    return module


def source_batches(workload) -> dict[int, list[EvidenceCell]]:
    return {
        index: [cell for cell in workload.cells if cell.source == source]
        for index, source in enumerate(workload.sources)
    }


def answer_counts(answers: list[dict | None]) -> dict[str, int]:
    result = {"same": 0, "different": 0, "ambiguous": 0, "unavailable": 0}
    for answer in answers:
        if answer is None:
            result["unavailable"] += 1
        else:
            result[answer["certificate"]["kind"]] += 1
    return result


def common_row(
    *,
    architecture: str,
    layout: str,
    seed: int,
    workload,
    stats: WireStats,
    spool: SpoolStats,
    partition_write_acks: int,
    partition_answers: list[dict | None],
    partition_durable_bytes: int,
    final_durable_bytes: int,
    final_state: dict,
    final_certificate: dict,
    restart_recovered: bool,
    heal_rounds: int,
    elapsed_seconds: float,
    endpoint_count: int,
    authority_replicas: int,
) -> dict:
    checker = load_checker()
    started = time.perf_counter()
    checker.verify(final_state, final_certificate)
    checker_ms = (time.perf_counter() - started) * 1000.0
    replica = Replica.import_state(final_state)
    metric = partition_metrics(replica.materialize(), workload.truth)
    counts = answer_counts(partition_answers)
    return {
        "architecture": architecture,
        "layout": layout,
        "seed": seed,
        "services": workload.service_count,
        "input_cells": len(workload.cells),
        "endpoints": endpoint_count,
        "authority_replicas": authority_replicas,
        "partition_write_attempts": 5,
        "partition_write_acks": partition_write_acks,
        "partition_write_availability": partition_write_acks / 5,
        "partition_query_attempts": 5,
        "partition_query_acks": 5 - counts["unavailable"],
        "partition_query_availability": (5 - counts["unavailable"]) / 5,
        "partition_same": counts["same"],
        "partition_different": counts["different"],
        "partition_ambiguous": counts["ambiguous"],
        "partition_unavailable": counts["unavailable"],
        "heal_rounds": heal_rounds,
        "final_kind": final_certificate["kind"],
        "final_false_merge_pairs": metric.false_merge_pairs,
        "final_false_split_pairs": metric.false_split_pairs,
        "final_cells": len(replica),
        "requests": stats.requests,
        "wire_bytes": stats.total_bytes,
        "rpc_median_ms": statistics.median(stats.latency_ms) if stats.latency_ms else 0.0,
        "rpc_p95_ms": percentile(stats.latency_ms, 0.95),
        "certificate_generation_median_ms": (
            statistics.median(stats.certificate_generation_ms)
            if stats.certificate_generation_ms
            else 0.0
        ),
        "certificate_verification_ms": checker_ms,
        "snapshot_commits": stats.commits,
        "snapshot_fsyncs": stats.fsyncs,
        "snapshot_bytes_written": stats.snapshot_bytes,
        "client_spool_fsyncs": spool.fsyncs,
        "client_spool_bytes_written": spool.bytes_written,
        "persistence_fsyncs": stats.fsyncs + spool.fsyncs,
        "persistence_bytes_written": stats.snapshot_bytes + spool.bytes_written,
        "partition_durable_bytes": partition_durable_bytes,
        "final_durable_bytes": final_durable_bytes,
        "restart_recovered": int(restart_recovered),
        "elapsed_seconds": elapsed_seconds,
    }


async def run_peer(layout: str, groups, seed: int, workload) -> tuple[dict, dict]:
    started = time.perf_counter()
    stats = WireStats()
    spool = SpoolStats()
    members = [f"n{index}" for index in range(5)]
    batches = source_batches(workload)
    query = workload.query_pairs[0]
    with tempfile.TemporaryDirectory(prefix="cie-equal-peer-") as temporary:
        directory = Path(temporary)
        nodes = [
            Service(
                member,
                list(workload.sources),
                2,
                list(workload.handles),
                members,
                directory / f"{member}.json",
                stats,
            )
            for member in members
        ]
        ports = [await node.start() for node in nodes]
        try:
            for index, port in enumerate(ports):
                await rpc(port, {"op": "ingest", "cells": [cell.to_dict() for cell in batches[index]]}, stats)

            for group in groups:
                for destination in group:
                    for peer in group:
                        if destination != peer:
                            await rpc(ports[destination], {"op": "pull", "peer_port": ports[peer]}, stats)

            partition_answers = [
                await rpc(port, {"op": "query", "left": query[0], "right": query[1]}, stats)
                for port in ports
            ]
            partition_durable = directory_bytes(directory)

            heal_rounds = 0
            snapshots = []
            for _ in range(4):
                heal_rounds += 1
                for destination in range(5):
                    for peer in range(5):
                        if destination != peer:
                            await rpc(ports[destination], {"op": "pull", "peer_port": ports[peer]}, stats)
                snapshots = [await rpc(port, {"op": "state"}, stats) for port in ports]
                if all(scientific_state(state) == scientific_state(snapshots[0]) for state in snapshots[1:]):
                    break
            require(snapshots and all(
                scientific_state(state) == scientific_state(snapshots[0]) for state in snapshots[1:]
            ), "peer architecture failed to converge")

            expected = Replica("expected", workload.sources, 2, workload.handles)
            for cell in workload.cells:
                expected.add(cell)
            require(
                scientific_state(snapshots[0]) == scientific_state(expected.export_state()),
                "peer architecture lost scheduled evidence",
            )

            final_answer = await rpc(
                ports[0], {"op": "query", "left": query[0], "right": query[1]}, stats
            )
            old_port = ports[-1]
            await nodes[-1].close()
            nodes[-1] = Service(
                members[-1],
                list(workload.sources),
                2,
                list(workload.handles),
                members,
                directory / f"{members[-1]}.json",
                stats,
            )
            ports[-1] = await nodes[-1].start(old_port)
            recovered = await rpc(ports[-1], {"op": "state"}, stats)
            restart_recovered = scientific_state(recovered) == scientific_state(snapshots[0])
            final_durable = directory_bytes(directory)

            row = common_row(
                architecture="peer-evidence",
                layout=layout,
                seed=seed,
                workload=workload,
                stats=stats,
                spool=spool,
                partition_write_acks=5,
                partition_answers=partition_answers,
                partition_durable_bytes=partition_durable,
                final_durable_bytes=final_durable,
                final_state=final_answer["state"],
                final_certificate=final_answer["certificate"],
                restart_recovered=restart_recovered,
                heal_rounds=heal_rounds,
                elapsed_seconds=time.perf_counter() - started,
                endpoint_count=5,
                authority_replicas=0,
            )
            detail = {
                "partition_answers": partition_answers,
                "final_answer": final_answer,
                "final_states_equal": True,
            }
            return row, detail
        finally:
            for node in nodes:
                await node.close()


async def run_central(layout: str, groups, seed: int, workload) -> tuple[dict, dict]:
    started = time.perf_counter()
    stats = WireStats()
    spool = SpoolStats()
    batches = source_batches(workload)
    query = workload.query_pairs[0]
    authority_group = group_for(0, groups)
    with tempfile.TemporaryDirectory(prefix="cie-equal-central-") as temporary:
        directory = Path(temporary)
        snapshot = directory / "central.json"
        service = Service(
            "central",
            list(workload.sources),
            2,
            list(workload.handles),
            ["central"],
            snapshot,
            stats,
        )
        port = await service.start()
        try:
            write_acks = 0
            spool_paths: dict[int, Path] = {}
            for index, cells in batches.items():
                path = directory / "spool" / f"source-{index}.json"
                spool_batch(path, cells, spool)
                spool_paths[index] = path
                if index in authority_group:
                    await rpc(port, {"op": "ingest", "cells": load_spool(path)}, stats)
                    path.unlink()
                    write_acks += 1

            partition_answers: list[dict | None] = []
            for client in range(5):
                if client in authority_group:
                    partition_answers.append(
                        await rpc(port, {"op": "query", "left": query[0], "right": query[1]}, stats)
                    )
                else:
                    partition_answers.append(None)
            partition_durable = directory_bytes(directory)

            for index, path in spool_paths.items():
                if path.exists():
                    await rpc(port, {"op": "ingest", "cells": load_spool(path)}, stats)
                    path.unlink()
            final_answer = await rpc(
                port, {"op": "query", "left": query[0], "right": query[1]}, stats
            )
            expected = Replica("expected", workload.sources, 2, workload.handles)
            for cell in workload.cells:
                expected.add(cell)
            require(
                scientific_state(final_answer["state"]) == scientific_state(expected.export_state()),
                "central architecture lost scheduled evidence",
            )

            await service.close()
            service = Service(
                "central",
                list(workload.sources),
                2,
                list(workload.handles),
                ["central"],
                snapshot,
                stats,
            )
            port = await service.start(port)
            recovered = await rpc(port, {"op": "state"}, stats)
            restart_recovered = scientific_state(recovered) == scientific_state(final_answer["state"])
            final_durable = directory_bytes(directory)
            row = common_row(
                architecture="central-recompute",
                layout=layout,
                seed=seed,
                workload=workload,
                stats=stats,
                spool=spool,
                partition_write_acks=write_acks,
                partition_answers=partition_answers,
                partition_durable_bytes=partition_durable,
                final_durable_bytes=final_durable,
                final_state=final_answer["state"],
                final_certificate=final_answer["certificate"],
                restart_recovered=restart_recovered,
                heal_rounds=1,
                elapsed_seconds=time.perf_counter() - started,
                endpoint_count=1,
                authority_replicas=1,
            )
            detail = {"partition_answers": partition_answers, "final_answer": final_answer}
            return row, detail
        finally:
            await service.close()


async def run_quorum(layout: str, groups, seed: int, workload) -> tuple[dict, dict]:
    started = time.perf_counter()
    stats = WireStats()
    spool = SpoolStats()
    batches = source_batches(workload)
    query = workload.query_pairs[0]
    names = tuple(AUTHORITY_PLACEMENTS)
    with tempfile.TemporaryDirectory(prefix="cie-equal-quorum-") as temporary:
        directory = Path(temporary)
        services = [
            Service(
                name,
                list(workload.sources),
                2,
                list(workload.handles),
                list(names),
                directory / f"{name}.json",
                stats,
            )
            for name in names
        ]
        ports = [await service.start() for service in services]
        try:
            write_acks = 0
            spool_paths: dict[int, Path] = {}
            for source_index, cells in batches.items():
                path = directory / "spool" / f"source-{source_index}.json"
                spool_batch(path, cells, spool)
                spool_paths[source_index] = path
                group = group_for(source_index, groups)
                reachable = [
                    authority_index
                    for authority_index, name in enumerate(names)
                    if AUTHORITY_PLACEMENTS[name] in group
                ]
                if len(reachable) >= 2:
                    payload = load_spool(path)
                    for authority_index in reachable:
                        await rpc(ports[authority_index], {"op": "ingest", "cells": payload}, stats)
                    path.unlink()
                    write_acks += 1

            partition_answers: list[dict | None] = []
            for client in range(5):
                group = group_for(client, groups)
                reachable = [
                    authority_index
                    for authority_index, name in enumerate(names)
                    if AUTHORITY_PLACEMENTS[name] in group
                ]
                if len(reachable) >= 2:
                    partition_answers.append(
                        await rpc(
                            ports[reachable[0]],
                            {"op": "query", "left": query[0], "right": query[1]},
                            stats,
                        )
                    )
                else:
                    partition_answers.append(None)
            partition_durable = directory_bytes(directory)

            for source_index, path in spool_paths.items():
                if path.exists():
                    payload = load_spool(path)
                    for port in ports:
                        await rpc(port, {"op": "ingest", "cells": payload}, stats)
                    path.unlink()

            heal_rounds = 0
            states = []
            for _ in range(3):
                heal_rounds += 1
                for destination in range(3):
                    for peer in range(3):
                        if destination != peer:
                            await rpc(ports[destination], {"op": "pull", "peer_port": ports[peer]}, stats)
                states = [await rpc(port, {"op": "state"}, stats) for port in ports]
                if all(scientific_state(state) == scientific_state(states[0]) for state in states[1:]):
                    break
            require(states and all(
                scientific_state(state) == scientific_state(states[0]) for state in states[1:]
            ), "coordinated architecture failed to converge")

            expected = Replica("expected", workload.sources, 2, workload.handles)
            for cell in workload.cells:
                expected.add(cell)
            require(
                scientific_state(states[0]) == scientific_state(expected.export_state()),
                "coordinated architecture lost scheduled evidence",
            )
            final_answer = await rpc(
                ports[0], {"op": "query", "left": query[0], "right": query[1]}, stats
            )

            old_port = ports[-1]
            await services[-1].close()
            services[-1] = Service(
                names[-1],
                list(workload.sources),
                2,
                list(workload.handles),
                list(names),
                directory / f"{names[-1]}.json",
                stats,
            )
            ports[-1] = await services[-1].start(old_port)
            recovered = await rpc(ports[-1], {"op": "state"}, stats)
            restart_recovered = scientific_state(recovered) == scientific_state(states[0])
            final_durable = directory_bytes(directory)

            row = common_row(
                architecture="coordinated-quorum",
                layout=layout,
                seed=seed,
                workload=workload,
                stats=stats,
                spool=spool,
                partition_write_acks=write_acks,
                partition_answers=partition_answers,
                partition_durable_bytes=partition_durable,
                final_durable_bytes=final_durable,
                final_state=final_answer["state"],
                final_certificate=final_answer["certificate"],
                restart_recovered=restart_recovered,
                heal_rounds=heal_rounds,
                elapsed_seconds=time.perf_counter() - started,
                endpoint_count=3,
                authority_replicas=3,
            )
            detail = {
                "partition_answers": partition_answers,
                "final_answer": final_answer,
                "final_states_equal": True,
            }
            return row, detail
        finally:
            for service in services:
                await service.close()


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict]) -> dict:
    result = {"cases": len(rows), "architectures": {}}
    for architecture in sorted({row["architecture"] for row in rows}):
        selected = [row for row in rows if row["architecture"] == architecture]
        def median_range(field: str) -> dict:
            values = [row[field] for row in selected]
            return {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }

        result["architectures"][architecture] = {
            "cases": len(selected),
            "partition_write_availability_mean": statistics.mean(
                row["partition_write_availability"] for row in selected
            ),
            "partition_query_availability_mean": statistics.mean(
                row["partition_query_availability"] for row in selected
            ),
            "partition_availability_by_layout": {
                layout: statistics.mean(
                    row["partition_query_availability"]
                    for row in selected
                    if row["layout"] == layout
                )
                for layout in sorted({row["layout"] for row in selected})
            },
            "partition_ambiguous_total": sum(row["partition_ambiguous"] for row in selected),
            "partition_same_total": sum(row["partition_same"] for row in selected),
            "wire_bytes_median": statistics.median(row["wire_bytes"] for row in selected),
            "wire_bytes_range": median_range("wire_bytes"),
            "persistence_bytes_written_median": statistics.median(
                row["persistence_bytes_written"] for row in selected
            ),
            "persistence_bytes_written_range": median_range("persistence_bytes_written"),
            "final_durable_bytes_median": statistics.median(
                row["final_durable_bytes"] for row in selected
            ),
            "final_durable_bytes_range": median_range("final_durable_bytes"),
            "elapsed_seconds_median": statistics.median(
                row["elapsed_seconds"] for row in selected
            ),
            "elapsed_seconds_range": median_range("elapsed_seconds"),
            "rpc_p95_ms_median": statistics.median(row["rpc_p95_ms"] for row in selected),
            "rpc_p95_ms_range": median_range("rpc_p95_ms"),
            "certificate_verification_ms_median": statistics.median(
                row["certificate_verification_ms"] for row in selected
            ),
            "certificate_verification_ms_range": median_range("certificate_verification_ms"),
            "all_final_same": all(row["final_kind"] == "same" for row in selected),
            "all_zero_false_merge": all(row["final_false_merge_pairs"] == 0 for row in selected),
            "all_zero_false_split": all(row["final_false_split_pairs"] == 0 for row in selected),
            "all_restart_recovered": all(row["restart_recovered"] == 1 for row in selected),
        }
    return result


async def campaign(services: int, seeds: tuple[int, ...]) -> list[dict]:
    rows: list[dict] = []
    detail_root = RESULTS / "equal_work"
    for seed in seeds:
        workload = generate_workload(services, sparse_fraction=0.0, seed=seed)
        require(len(workload.cells) <= 2_300, "equal-work cell cap exceeded")
        for layout, groups in LAYOUTS.items():
            for runner in (run_peer, run_central, run_quorum):
                row, detail = await asyncio.wait_for(
                    runner(layout, groups, seed, workload), timeout=120.0
                )
                require(row["final_kind"] == "same", "final query did not become same")
                require(row["partition_same"] == 0, "partial closure authorized a same answer")
                require(row["restart_recovered"] == 1, "snapshot restart did not recover")
                rows.append(row)
                directory = detail_root / f"{layout}-seed-{seed}"
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f"{row['architecture']}.json").write_text(
                    json.dumps({"result": row, "detail": detail}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", type=int, choices=[20, 100], default=100)
    parser.add_argument("--seeds", default="1,2,3,4,5")
    args = parser.parse_args()
    seeds = tuple(int(piece) for piece in args.seeds.split(",") if piece)
    if not seeds or any(seed not in range(1, 6) for seed in seeds):
        parser.error("seeds must be a non-empty subset of 1..5")
    rows = asyncio.run(campaign(args.services, seeds))
    write_csv(RESULTS / "equal_work.csv", rows)
    summary = aggregate(rows)
    require(summary["cases"] == len(seeds) * len(LAYOUTS) * 3, "campaign row count mismatch")
    require(
        summary["architectures"]["peer-evidence"]["partition_write_availability_mean"] == 1.0,
        "peer architecture lost local write availability",
    )
    require(
        summary["architectures"]["peer-evidence"]["partition_query_availability_mean"] == 1.0,
        "peer architecture lost local query availability",
    )
    require(
        summary["architectures"]["central-recompute"]["partition_query_availability_mean"] < 1.0,
        "central negative control did not lose partition availability",
    )
    require(
        summary["architectures"]["coordinated-quorum"]["partition_query_availability_mean"] < 1.0,
        "quorum negative control did not lose partition availability",
    )
    (RESULTS / "equal_work_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
