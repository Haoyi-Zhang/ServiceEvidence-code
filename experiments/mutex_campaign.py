#!/usr/bin/env python3
"""Bounded passive graph comparisons; standard library, no sockets or fetches."""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from cie.metrics import partition_metrics
from cie.model import EvidenceCell, Replica, Vote
from cie.mutex_baseline import (SignedEdge, controlled_materialize, mutex_watershed,
                                priority_preserving_mws, violated_negatives)
from cie.workload import generate_workload
from materializer_campaign import FAMILIES, SIZES, SEEDS, instance

ROOT = Path(__file__).resolve().parents[1]
REPETITIONS = 5


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def factorial_rows(r, family, seed, truth=None):
    baseline = r.materialize()
    require(baseline == priority_preserving_mws(r), 'MWS same-priority view mismatch')
    rows = []
    for relation_veto, component_veto in itertools.product((True, False), repeat=2):
        view = controlled_materialize(r, relation_veto=relation_veto, component_veto=component_veto)
        if relation_veto and component_veto:
            require(view == baseline, 'explicit-block reference mismatch')
        if relation_veto:
            require(view.decisions == baseline.decisions, 'component ablation changed decisions')
        row = dict(family=family, seed=seed, relation_veto=relation_veto,
                   component_veto=component_veto, handles=len(r.handles),
                   selected_positive=sum(d.vote == Vote.SAME for d in view.decisions.values()),
                   selected_negative=len(view.different_edges),
                   components=len(view.components), rejected=len(view.rejected_same_edges),
                   original_negative_violations=violated_negatives(view, baseline.different_edges),
                   view_equal_to_cie=view == baseline)
        if truth is not None:
            m = partition_metrics(view, truth)
            row.update(false_merge_pairs=m.false_merge_pairs, false_split_pairs=m.false_split_pairs,
                       false_merge_rate=m.false_merge_rate, false_split_rate=m.false_split_rate)
        rows.append(row)
    return rows


def run(out):
    start = time.monotonic()
    def bounded():
        require(time.monotonic() - start < 180, '180-second campaign cap exceeded')
    out.mkdir(parents=True, exist_ok=True)
    # Do not reuse the retained Linux timing environment for this execution.
    environment = dict(python=sys.version, executable=sys.executable, os=platform.platform(),
                       processor=platform.processor(), timing_clock='perf_counter_ns',
                       scope='in-memory pure graphs; no persistent-service or network timing',
                       allocation='not pinned; external CPU/memory allocation unknown')
    (out/'environment.json').write_text(json.dumps(environment, indent=2)+'\n', encoding='utf-8')
    exhaustive = dict(graphs=0, full_view_equal=0, component_off_changes=0,
                      component_off_negative_violations=0)
    pairs = list(itertools.combinations('abcd',2))
    for labels in itertools.product(tuple(Vote), repeat=6):
        r = Replica('finite',['s'],1,'abcd')
        for p, v in zip(pairs,labels):
            r.add(EvidenceCell(*p,0,'s',v,'finite signed graph'))
        cie = r.materialize()
        require(cie == r.materialize_reference() == priority_preserving_mws(r) == controlled_materialize(r),
                'exhaustive full-view mismatch')
        off = controlled_materialize(r, component_veto=False)
        exhaustive['graphs'] += 1
        exhaustive['full_view_equal'] += 1
        exhaustive['component_off_changes'] += int(off.components != cie.components)
        exhaustive['component_off_negative_violations'] += violated_negatives(off, cie.different_edges)
        bounded()

    triangle = Replica('triangle',['s0','s1','s2'],2,'abc')
    for p, vs in ((('a','b'),(Vote.SAME,Vote.SAME,Vote.UNKNOWN)),
                  (('b','c'),(Vote.SAME,Vote.SAME,Vote.UNKNOWN)),
                  (('a','c'),(Vote.UNKNOWN,Vote.UNKNOWN,Vote.DIFFERENT))):
        for s,v in zip(triangle.sources,vs):
            triangle.add(EvidenceCell(*p,0,s,v,'constructed conflicting triangle'))
    triangle_rows = factorial_rows(triangle,'conflicting_triangle',0)
    write_csv(out/'reachable_veto.csv',triangle_rows)
    views = {}
    for rv,cv in itertools.product((True,False),repeat=2):
        v = controlled_materialize(triangle,relation_veto=rv,component_veto=cv)
        views[f'relation={rv};component={cv}'] = dict(components=v.components,
            accepted=v.accepted_same_edges, rejected=v.rejected_same_edges,
            selected_negative=v.different_edges)
    (out/'reachable_veto_state.json').write_text(json.dumps(dict(state=triangle.export_state(),views=views,
        assumption_scope='A1/A2 admissible; conflicting positives need not satisfy A4 separability'),indent=2)+'\n',encoding='utf-8')
    strong_positive = [SignedEdge(('a','b'),Vote.SAME,3),SignedEdge(('b','c'),Vote.SAME,2),
                       SignedEdge(('a','c'),Vote.DIFFERENT,1)]
    weighted = mutex_watershed('abc',strong_positive)
    priority = mutex_watershed('abc',[SignedEdge(e.pair,e.vote,
        2 if e.vote == Vote.DIFFERENT else 1) for e in strong_positive])
    require(weighted.components == (('a','b','c'),) and weighted.ignored_negative == (('a','c'),),
            'weighted priority witness mismatch')
    require(priority.components == (('a','b'),('c',)), 'negative-first witness mismatch')
    (out/'priority_witness.json').write_text(json.dumps(dict(
        weighted_edges=[dict(pair=e.pair,vote=e.vote.value,weight=e.weight) for e in strong_positive],
        weighted_result=weighted.__dict__, negative_first_result=priority.__dict__),indent=2)+'\n',encoding='utf-8')

    generated = []
    for sparse,seed in itertools.product((0.0,0.08,0.20),(7,19,43,71,97)):
        workload = generate_workload(600,sparse_fraction=sparse,collision_fraction=0.30,seed=seed)
        r = Replica('generated',workload.sources,2,workload.handles)
        for cell in workload.cells:
            r.add(cell)
        generated.extend(factorial_rows(r,f'sparse={sparse:.2f}',seed,workload.truth))
        bounded()
    write_csv(out/'generated_ablations.csv',generated)

    raw,cases,summary = [],[],[]
    for family,n in itertools.product(FAMILIES,SIZES):
        family_cases = []
        for seed in SEEDS:
            r = instance(family,n,seed)
            functions = dict(scanning=r.materialize_reference, indexed=r.materialize,
                             mws_edge_ids=lambda: priority_preserving_mws(r))
            reference = r.materialize()
            require(len(r.cells) <= 20000, 'stress graph cell cap')
            for fn in functions.values():
                require(fn() == reference, 'stress warm-up view mismatch')
            timings = {name:[] for name in functions}
            orders = list(itertools.permutations(functions))
            for rep in range(REPETITIONS):
                for position,name in enumerate(orders[(rep+seed) % len(orders)]):
                    t = time.perf_counter_ns()
                    observed = functions[name]()
                    seconds = (time.perf_counter_ns()-t)/1e9
                    require(observed == reference, 'timed full-view mismatch')
                    raw.append(dict(family=family,handles=n,seed=seed,repetition=rep,
                                    position=position,implementation=name,seconds=seconds,full_view_equal=True))
                    timings[name].append(seconds)
                bounded()
            row = dict(family=family,handles=n,seed=seed,cells=len(r.cells),
                       negatives=len(reference.different_edges),rejected=len(reference.rejected_same_edges),
                       components=len(reference.components),full_view_equal=True)
            row.update({name+'_median_ms':1000*statistics.median(ts) for name,ts in timings.items()})
            row['scanning_over_indexed'] = row['scanning_median_ms']/row['indexed_median_ms']
            row['mws_over_indexed'] = row['mws_edge_ids_median_ms']/row['indexed_median_ms']
            cases.append(row); family_cases.append(row)
        row = dict(family=family,handles=n,seeds=len(SEEDS),repetitions=REPETITIONS)
        for name in ('scanning_median_ms','indexed_median_ms','mws_edge_ids_median_ms',
                     'scanning_over_indexed','mws_over_indexed'):
            row[name] = statistics.median(c[name] for c in family_cases)
        summary.append(row)
        print(json.dumps(row),flush=True)
    write_csv(out/'stress_raw.csv',raw)
    write_csv(out/'stress_cases.csv',cases)
    write_csv(out/'stress_summary.csv',summary)
    checks = dict(exhaustive=exhaustive,generated_cases=len(generated)//4,
        generated_factorial_rows=len(generated),
        generated_component_guard_rejections=sum(x['rejected'] for x in generated
            if x['relation_veto'] and x['component_veto']),
        generated_component_only_changed_partitions=sum(not x['view_equal_to_cie'] for x in generated
            if x['relation_veto'] and not x['component_veto']),
        stress_cases=len(cases),stress_raw_calls=len(raw),
        full_view_equal=all(c['full_view_equal'] for c in cases),
        max_stress_cells=max(c['cells'] for c in cases),
        reachable_component_only_negative_violations=triangle_rows[1]['original_negative_violations'],
        elapsed_seconds=time.monotonic()-start,
        inference_scope='synthetic bounded graphs; no image-code, Web-population or deployment ranking')
    (out/'checks.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'results'/'mutex')
    run(parser.parse_args().out)
