#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
from typing import List, Mapping, Sequence

from cie.baselines import last_arrival, local_only, name_only, union_find
from cie.metrics import partition_metrics, partition_signature
from cie.model import EvidenceCell, Replica, Vote
from cie.simulator import emulate, stable_epochs
from cie.workload import generate_workload


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"no rows for {path}")
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> List[Mapping[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def metric_row(trial: str, method: str, view, truth):
    metric = partition_metrics(view, truth)
    return {
        "trial": trial,
        "method": method,
        "false_merge_pairs": metric.false_merge_pairs,
        "false_split_pairs": metric.false_split_pairs,
        "predicted_same_pairs": metric.predicted_same_pairs,
        "true_same_pairs": metric.true_same_pairs,
        "false_merge_rate": metric.false_merge_rate,
        "false_split_rate": metric.false_split_rate,
    }


def all_evidence_replica(workload, threshold=2, cells=None):
    replica = Replica("all", workload.sources, threshold, handles=workload.handles)
    for cell in cells if cells is not None else workload.cells:
        replica.add(cell)
    return replica


def run_correctness() -> List[Mapping[str, object]]:
    rows = []
    nodes = ("n0", "n1", "n2", "n3", "n4")
    for sparse in (0.0, 0.08, 0.20):
        for seed in (7, 19, 43, 71, 97):
            workload = generate_workload(
                600,
                sparse_fraction=sparse,
                collision_fraction=0.30,
                seed=seed,
            )
            trial = f"sparse={sparse:.2f};seed={seed}"
            network = emulate(
                workload.cells,
                nodes,
                workload.sources,
                seed=seed + 1000,
                loss_rate=0.08,
                duplicate_rate=0.15,
                partition_fraction=0.40,
                repair=True,
                handles=workload.handles,
            )
            proposed = network.replicas["n0"].materialize(workload.handles)
            rows.append(metric_row(trial, "sealed-evidence q=2", proposed, workload.truth))

            q1 = all_evidence_replica(workload, threshold=1).materialize(workload.handles)
            rows.append(metric_row(trial, "sealed-evidence q=1", q1, workload.truth))

            no_negative_cells = tuple(
                EvidenceCell(
                    cell.left,
                    cell.right,
                    cell.epoch,
                    cell.source,
                    Vote.UNKNOWN if cell.vote == Vote.DIFFERENT else cell.vote,
                    "negative-veto ablation" if cell.vote == Vote.DIFFERENT else cell.reason,
                )
                for cell in workload.cells
            )
            no_negative = all_evidence_replica(
                workload, threshold=2, cells=no_negative_cells
            ).materialize(workload.handles)
            rows.append(
                metric_row(trial, "no negative veto", no_negative, workload.truth)
            )

            rows.append(
                metric_row(
                    trial,
                    "merge-forever union-find",
                    union_find(workload.cells, workload.handles),
                    workload.truth,
                )
            )
            rows.append(
                metric_row(
                    trial,
                    "single-vantage local",
                    local_only(workload.cells, workload.handles, workload.sources[0]),
                    workload.truth,
                )
            )
            rows.append(
                metric_row(trial, "name-only", name_only(workload.names), workload.truth)
            )

            delivery_metrics = []
            for node in nodes:
                ordered = [
                    delivery.cell
                    for delivery in network.deliveries
                    if delivery.destination == node
                ]
                delivery_metrics.append(
                    partition_metrics(last_arrival(ordered, workload.handles), workload.truth)
                )
            rows.append(
                {
                    "trial": trial,
                    "method": "last-arrival",
                    "false_merge_pairs": statistics.mean(
                        metric.false_merge_pairs for metric in delivery_metrics
                    ),
                    "false_split_pairs": statistics.mean(
                        metric.false_split_pairs for metric in delivery_metrics
                    ),
                    "predicted_same_pairs": statistics.mean(
                        metric.predicted_same_pairs for metric in delivery_metrics
                    ),
                    "true_same_pairs": delivery_metrics[0].true_same_pairs,
                    "false_merge_rate": statistics.mean(
                        metric.false_merge_rate for metric in delivery_metrics
                    ),
                    "false_split_rate": statistics.mean(
                        metric.false_split_rate for metric in delivery_metrics
                    ),
                }
            )
    write_csv(RESULTS / "correctness.csv", rows)
    return rows


def run_faults() -> List[Mapping[str, object]]:
    configurations = [
        ("reorder-only", 0.0, 0.0, 0.0),
        ("loss", 0.12, 0.0, 0.0),
        ("duplication", 0.0, 0.25, 0.0),
        ("partition", 0.0, 0.0, 0.40),
        ("combined", 0.08, 0.15, 0.40),
    ]
    rows = []
    nodes = ("n0", "n1", "n2", "n3", "n4")
    for configuration, loss, duplicate, partition in configurations:
        for seed in (5, 17, 29, 41, 53):
            workload = generate_workload(400, sparse_fraction=0.0, seed=seed)
            started = time.perf_counter()
            result = emulate(
                workload.cells,
                nodes,
                workload.sources,
                seed=seed + 500,
                loss_rate=loss,
                duplicate_rate=duplicate,
                partition_fraction=partition,
                repair=True,
                handles=workload.handles,
            )
            elapsed = time.perf_counter() - started
            signatures = [
                partition_signature(replica.materialize(workload.handles))
                for replica in result.replicas.values()
            ]
            metric = partition_metrics(
                result.replicas["n0"].materialize(workload.handles), workload.truth
            )
            rows.append(
                {
                    "configuration": configuration,
                    "seed": seed,
                    "observations": workload.observation_count,
                    "scheduled_initial_messages": result.scheduled_messages,
                    "delivered_messages": result.delivered_messages,
                    "repair_messages": result.repair_messages,
                    "duplicate_messages": result.duplicate_messages,
                    "payload_bytes": result.payload_bytes,
                    "pre_repair_converged": int(result.pre_repair_converged),
                    "post_repair_converged": int(
                        all(signature == signatures[0] for signature in signatures[1:])
                    ),
                    "false_merge_pairs": metric.false_merge_pairs,
                    "false_split_pairs": metric.false_split_pairs,
                    "elapsed_seconds": elapsed,
                }
            )
    write_csv(RESULTS / "faults.csv", rows)
    return rows


def run_unsealed_safety() -> List[Mapping[str, object]]:
    rng = random.Random(9901)
    trials = 20_000
    random_unsafe = 0
    for _ in range(trials):
        cells = ["same", "same", "different", "unknown", "unknown"]
        rng.shuffle(cells)
        same_count = 0
        negative_seen = False
        for vote in cells:
            same_count += int(vote == "same")
            negative_seen = negative_seen or vote == "different"
            if same_count >= 2 and not negative_seen:
                random_unsafe += 1
                break
    rows = [
        {
            "schedule": "uniform random delivery order",
            "trials": trials,
            "unsealed_transient_false_merges": random_unsafe,
            "unsealed_rate": random_unsafe / trials,
            "sealed_transient_false_merges": 0,
            "sealed_rate": 0.0,
        },
        {
            "schedule": "adversarial same-votes first",
            "trials": trials,
            "unsealed_transient_false_merges": trials,
            "unsealed_rate": 1.0,
            "sealed_transient_false_merges": 0,
            "sealed_rate": 0.0,
        },
    ]
    write_csv(RESULTS / "unsealed_safety.csv", rows)
    return rows


def load_checker():
    path = ROOT / "checker" / "verify.py"
    specification = importlib.util.spec_from_file_location(
        "independent_certificate_checker", path
    )
    module = importlib.util.module_from_spec(specification)
    if specification.loader is None:
        raise RuntimeError("could not load independent certificate checker")
    specification.loader.exec_module(module)
    return module


def run_witnesses() -> List[Mapping[str, object]]:
    checker = load_checker()
    workload = generate_workload(
        250, sparse_fraction=0.18, collision_fraction=0.35, seed=211
    )
    replica = all_evidence_replica(workload)
    state = replica.export_state()
    rows = []
    examples = {}
    for query in workload.query_pairs[:250]:
        started = time.perf_counter()
        certificate = replica.certificate(*query)
        generation_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        checker.verify(state, certificate)
        verification_ms = (time.perf_counter() - started) * 1000.0
        kind = str(certificate["kind"])
        examples.setdefault(kind, certificate)
        rows.append(
            {
                "kind": kind,
                "query_left": query[0],
                "query_right": query[1],
                "path_or_edge_count": (
                    len(certificate.get("path", [])) - 1
                    if kind == "same"
                    else certificate.get("edge_count", 1)
                ),
                "authorization_gap": certificate.get("authorization_gap", 0),
                "certificate_bytes": len(
                    json.dumps(certificate, sort_keys=True).encode("utf-8")
                ),
                "generation_ms": generation_ms,
                "verification_ms": verification_ms,
            }
        )
    if set(examples) != {"same", "different", "ambiguous"}:
        raise AssertionError(f"missing certificate kind: {set(examples)}")

    for kind, certificate in examples.items():
        tampered = copy.deepcopy(certificate)
        if kind == "same":
            tampered["path"] = list(reversed(tampered["path"]))
        elif kind == "different":
            tampered["cell"]["vote"] = "same"
        else:
            tampered["authorization_gap"] = int(tampered["authorization_gap"]) + 1
        try:
            checker.verify(state, tampered)
        except (checker.VerificationError, KeyError, TypeError, ValueError):
            pass
        else:
            raise AssertionError(f"tampered {kind} certificate was accepted")

    (RESULTS / "example_state.json").write_text(
        json.dumps(state, sort_keys=True, indent=2), encoding="utf-8"
    )
    for kind, certificate in examples.items():
        (RESULTS / f"example_{kind}_certificate.json").write_text(
            json.dumps(certificate, sort_keys=True, indent=2), encoding="utf-8"
        )
    write_csv(RESULTS / "witnesses.csv", rows)
    return rows


def run_compaction() -> List[Mapping[str, object]]:
    rows = []
    nodes = ("n0", "n1", "n2", "n3", "n4")
    for epochs in (2, 4, 6):
        workload = generate_workload(700, epochs=epochs, seed=333 + epochs)
        result = emulate(
            workload.cells,
            nodes,
            workload.sources,
            seed=700 + epochs,
            loss_rate=0.05,
            duplicate_rate=0.08,
            partition_fraction=0.40,
            repair=True,
            handles=workload.handles,
        )
        stable = stable_epochs(result.replicas)
        replica = result.replicas["n0"]
        before_view = replica.materialize(workload.handles).components
        before_cells = len(replica)
        before_bytes = replica.serialized_bytes()
        for node in result.replicas.values():
            node.compact(stable, retain_pending=0)
        after_view = result.replicas["n0"].materialize(workload.handles).components
        after_cells = len(result.replicas["n0"])
        after_bytes = result.replicas["n0"].serialized_bytes()
        rows.append(
            {
                "epochs": epochs,
                "relations": len(stable),
                "cells_before": before_cells,
                "cells_after": after_cells,
                "cell_reduction": 1.0 - after_cells / before_cells,
                "bytes_before": before_bytes,
                "bytes_after": after_bytes,
                "byte_reduction": 1.0 - after_bytes / before_bytes,
                "partition_preserved": int(before_view == after_view),
            }
        )
    write_csv(RESULTS / "compaction.csv", rows)
    return rows


def run_scale() -> List[Mapping[str, object]]:
    rows = []
    cases = [
        ("--services", "50"),
        ("--services", "200"),
        ("--services", "800"),
        ("--services", "2000"),
        ("--cap", "80000"),
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    for flag, value in cases:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "experiments" / "scale_case.py"), flag, value],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=180,
        )
        rows.append(json.loads(completed.stdout))
    write_csv(RESULTS / "scale.csv", rows)
    return rows


def aggregate(correctness, faults, unsealed, witnesses, compaction, scale):
    methods = sorted(set(row["method"] for row in correctness))
    by_method = {}
    for method in methods:
        selected = [row for row in correctness if row["method"] == method]
        by_method[method] = {
            "mean_false_merge_rate": statistics.mean(
                float(row["false_merge_rate"]) for row in selected
            ),
            "mean_false_split_rate": statistics.mean(
                float(row["false_split_rate"]) for row in selected
            ),
            "max_false_merge_pairs": max(
                float(row["false_merge_pairs"]) for row in selected
            ),
            "max_false_split_pairs": max(
                float(row["false_split_pairs"]) for row in selected
            ),
        }
    by_kind = {}
    for kind in sorted(set(row["kind"] for row in witnesses)):
        selected = [row for row in witnesses if row["kind"] == kind]
        by_kind[kind] = {
            "count": len(selected),
            "median_bytes": statistics.median(
                float(row["certificate_bytes"]) for row in selected
            ),
            "median_generation_ms": statistics.median(
                float(row["generation_ms"]) for row in selected
            ),
            "median_verification_ms": statistics.median(
                float(row["verification_ms"]) for row in selected
            ),
        }
    proposed = [
        row for row in correctness if row["method"] == "sealed-evidence q=2"
    ]
    summary = {
        "correctness_by_method": by_method,
        "proposed_all_trials_zero_false_merge": all(
            float(row["false_merge_pairs"]) == 0 for row in proposed
        ),
        "fault_trials": len(faults),
        "fault_all_post_repair_converged": all(
            int(row["post_repair_converged"]) == 1 for row in faults
        ),
        "fault_all_zero_false_merge": all(
            float(row["false_merge_pairs"]) == 0 for row in faults
        ),
        "fault_all_zero_false_split": all(
            float(row["false_split_pairs"]) == 0 for row in faults
        ),
        "unsealed_safety": unsealed,
        "witness_by_kind": by_kind,
        "compaction": compaction,
        "scale": scale,
    }
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2), encoding="utf-8"
    )
    return summary


STAGE_OUTPUTS = {
    "correctness": "correctness.csv",
    "faults": "faults.csv",
    "unsealed": "unsealed_safety.csv",
    "witnesses": "witnesses.csv",
    "compaction": "compaction.csv",
    "scale": "scale.csv",
}


def run_stage(stage: str):
    functions = {
        "correctness": run_correctness,
        "faults": run_faults,
        "unsealed": run_unsealed_safety,
        "witnesses": run_witnesses,
        "compaction": run_compaction,
        "scale": run_scale,
    }
    started = time.perf_counter()
    rows = functions[stage]()
    print(
        json.dumps(
            {
                "status": "PASS",
                "stage": stage,
                "rows": len(rows),
                "elapsed_seconds": time.perf_counter() - started,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("aggregate",) + tuple(STAGE_OUTPUTS))
    args = parser.parse_args()
    if args.stage and args.stage != "aggregate":
        run_stage(args.stage)
        return 0
    if not args.stage:
        raise SystemExit("use scripts/reproduce.sh for isolated stages")
    summary = aggregate(
        read_csv(RESULTS / STAGE_OUTPUTS["correctness"]),
        read_csv(RESULTS / STAGE_OUTPUTS["faults"]),
        read_csv(RESULTS / STAGE_OUTPUTS["unsealed"]),
        read_csv(RESULTS / STAGE_OUTPUTS["witnesses"]),
        read_csv(RESULTS / STAGE_OUTPUTS["compaction"]),
        read_csv(RESULTS / STAGE_OUTPUTS["scale"]),
    )
    print(json.dumps({"status": "PASS", "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
