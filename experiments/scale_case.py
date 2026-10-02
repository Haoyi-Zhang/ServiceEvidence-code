#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import resource
import statistics
import time

from cie.metrics import partition_metrics
from cie.simulator import emulate, stable_epochs
from cie.workload import generate_to_observation_cap, generate_workload


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--services", type=int)
    group.add_argument("--cap", type=int)
    parser.add_argument("--seed", type=int, default=73)
    args = parser.parse_args()

    start = time.perf_counter()
    if args.cap is not None:
        workload = generate_to_observation_cap(args.cap, seed=args.seed)
        label = f"cap-{args.cap}"
    else:
        workload = generate_workload(args.services, seed=args.seed)
        label = f"services-{args.services}"
    generated_at = time.perf_counter()

    result = emulate(
        workload.cells,
        ("n0", "n1", "n2", "n3", "n4"),
        workload.sources,
        threshold=2,
        seed=args.seed + 101,
        loss_rate=0.05,
        duplicate_rate=0.08,
        partition_fraction=0.40,
        repair=True,
        delivery_cap=500_000,
        handles=workload.handles,
    )
    emulated_at = time.perf_counter()
    replica = result.replicas["n0"]
    view = replica.materialize(workload.handles)
    metrics = partition_metrics(view, workload.truth)
    materialized_at = time.perf_counter()

    certificate_times = []
    certificate_sizes = []
    for pair in workload.query_pairs[: min(30, len(workload.query_pairs))]:
        before = time.perf_counter()
        certificate = replica.certificate(*pair)
        certificate_times.append((time.perf_counter() - before) * 1000.0)
        certificate_sizes.append(
            len(json.dumps(certificate, sort_keys=True).encode("utf-8"))
        )
    certified_at = time.perf_counter()

    state_bytes_before = replica.serialized_bytes()
    cell_count_before = len(replica)
    stable = stable_epochs(result.replicas)
    for node in result.replicas.values():
        node.compact(stable, retain_pending=0)
    state_bytes_after = result.replicas["n0"].serialized_bytes()
    cell_count_after = len(result.replicas["n0"])
    compacted_at = time.perf_counter()

    peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ordered_times = sorted(certificate_times)
    p95_index = max(0, int(len(ordered_times) * 0.95) - 1)
    output = {
        "label": label,
        "services": workload.service_count,
        "handles": len(workload.handles),
        "observations": workload.observation_count,
        "relations": len(replica.decisions()),
        "delivered_messages": result.delivered_messages,
        "repair_messages": result.repair_messages,
        "duplicate_messages": result.duplicate_messages,
        "payload_bytes": result.payload_bytes,
        "false_merge_pairs": metrics.false_merge_pairs,
        "false_split_pairs": metrics.false_split_pairs,
        "false_merge_rate": metrics.false_merge_rate,
        "false_split_rate": metrics.false_split_rate,
        "state_cells_before": cell_count_before,
        "state_cells_after": cell_count_after,
        "state_bytes_before": state_bytes_before,
        "state_bytes_after": state_bytes_after,
        "compaction_fraction_cells": 1.0 - cell_count_after / cell_count_before,
        "compaction_fraction_bytes": 1.0 - state_bytes_after / state_bytes_before,
        "certificate_ms_median": statistics.median(certificate_times),
        "certificate_ms_p95": ordered_times[p95_index],
        "certificate_bytes_median": statistics.median(certificate_sizes),
        "generation_seconds": generated_at - start,
        "emulation_seconds": emulated_at - generated_at,
        "materialization_seconds": materialized_at - emulated_at,
        "certificate_seconds": certified_at - materialized_at,
        "compaction_seconds": compacted_at - certified_at,
        "total_seconds": compacted_at - start,
        "peak_rss_mib": peak_rss_kib / 1024.0,
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
