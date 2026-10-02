#!/usr/bin/env python3
"""Paired full-materialization benchmark; no external packages or downloads."""
from __future__ import annotations
import argparse
import csv
import itertools
import json
import random
import statistics
import time
from pathlib import Path
from cie.model import EvidenceCell, Replica, Vote

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('sparse_cut', 'dense_cut', 'low_conflict')
SIZES = (64, 128, 256, 512)
SEEDS = (1, 2, 3, 4, 5)
REPETITIONS = 5

def instance(family: str, n: int, seed: int) -> Replica:
    rng = random.Random(seed)
    names = [f'h{i:05}' for i in range(n)]
    labels: dict[tuple[int, int], Vote] = {}
    def put(a: int, b: int, vote: Vote) -> None:
        labels[min(a, b), max(a, b)] = vote
    if family == 'low_conflict':
        for i in range(1, n):
            put(i - 1, i, Vote.SAME)
        for a, b in rng.sample(list(itertools.combinations(range(n), 2)), n):
            put(a, b, Vote.SAME)
    else:
        # Early lexicographic stars make two large components; late cross edges
        # exercise a negative-safe union veto. A sparse or dense cut separates them.
        for i in range(2, n):
            put(i % 2, i, Vote.SAME)
        put(0, 1, Vote.DIFFERENT)
        cross = [(a, b) for a in range(2, n, 2) for b in range(3, n, 2)]
        rng.shuffle(cross)
        for a, b in cross[:4 * n]:
            put(a, b, Vote.SAME)
        if family == 'dense_cut':
            for a, b in cross[4*n:8*n]:
                put(a, b, Vote.DIFFERENT)
    r = Replica('benchmark', ('s0', 's1', 's2'), 2, names)
    for (a, b), vote in sorted(labels.items()):
        for source in r.sources:
            r.add(EvidenceCell(names[a], names[b], 0, source, vote, 'generated'))
    return r

def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

def run(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    raw, cases, summary = [], [], []
    for family in FAMILIES:
        for n in SIZES:
            ratios = []
            ref_times, idx_times = [], []
            for seed in SEEDS:
                r = instance(family, n, seed)
                reference = r.materialize_reference()
                assert reference == r.materialize()
                timings = {'reference': [], 'indexed': []}
                for rep in range(REPETITIONS):
                    order = ('reference', 'indexed') if (rep + seed) % 2 else ('indexed', 'reference')
                    for name in order:
                        fn = r.materialize if name == 'indexed' else r.materialize_reference
                        start = time.perf_counter_ns()
                        observed = fn()
                        seconds = (time.perf_counter_ns() - start) / 1e9
                        assert observed == reference
                        timings[name].append(seconds)
                        raw.append(dict(family=family, handles=n, seed=seed,
                                        repetition=rep, implementation=name,
                                        order=order.index(name), seconds=seconds,
                                        view_equal=True))
                ref = statistics.median(timings['reference'])
                idx = statistics.median(timings['indexed'])
                ratio = ref / idx
                ratios.append(ratio); ref_times.append(ref); idx_times.append(idx)
                cases.append(dict(family=family, handles=n, seed=seed,
                    relations=len(reference.decisions),
                    cells=len(r.cells), negative_edges=len(reference.different_edges),
                    accepted=len(reference.accepted_same_edges),
                    rejected=len(reference.rejected_same_edges),
                    components=len(reference.components), reference_seconds=ref,
                    indexed_seconds=idx, reference_over_indexed=ratio,
                    repetitions=REPETITIONS, view_equal=True))
            summary.append(dict(family=family, handles=n, cases=len(SEEDS),
                reference_median_ms=1000*statistics.median(ref_times),
                indexed_median_ms=1000*statistics.median(idx_times),
                paired_speedup_median=statistics.median(ratios),
                paired_speedup_min=min(ratios), paired_speedup_max=max(ratios)))
    write_csv(out/'materializer_raw.csv', raw)
    write_csv(out/'materializer_cases.csv', cases)
    write_csv(out/'materializer_summary.csv', summary)
    (out/'materializer_checks.json').write_text(json.dumps(dict(
        families=FAMILIES, sizes=SIZES, seeds=SEEDS, repetitions=REPETITIONS,
        cases=len(cases), paired_repetitions=len(raw)//2,
        max_cells=max(c['cells'] for c in cases),
        all_views_equal=all(c['view_equal'] for c in cases),
        timing_scope='complete materialization including decisions and index construction',
        inference_scope='synthetic structural stress cases; not deployment distribution'), indent=2)+'\n')
    for row in summary:
        print(row, flush=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=ROOT/'results'/'tpds')
    run(p.parse_args().out)
