#!/usr/bin/env python3
"""Reaggregate passive Mutex Watershed comparisons and check controls."""
import csv
import itertools
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results'/'mutex'


def read(name):
    with (OUT/name).open(newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def near(a,b):
    return math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-12)


def main():
    checks = json.loads((OUT/'checks.json').read_text(encoding='utf-8'))
    require(checks['exhaustive'] == dict(graphs=729,full_view_equal=729,
        component_off_changes=259,component_off_negative_violations=354),'finite graph counts')
    require(checks['generated_cases'] == 15 and checks['generated_factorial_rows'] == 60,'factorial count')
    require(checks['generated_component_guard_rejections'] == 0 and
            checks['generated_component_only_changed_partitions'] == 0,'generated component-only control')
    require(checks['stress_cases'] == 60 and checks['stress_raw_calls'] == 900,'stress counts')
    require(checks['full_view_equal'] and checks['max_stress_cells'] == 13821,'stress checks')
    require(0 < checks['elapsed_seconds'] < 180,'campaign time cap')
    raw,cases,summary = read('stress_raw.csv'),read('stress_cases.csv'),read('stress_summary.csv')
    require((len(raw),len(cases),len(summary)) == (900,60,12),'row counts')
    implementations = ('scanning','indexed','mws_edge_ids')
    keys = set()
    for row in raw:
        key = (row['family'],row['handles'],row['seed'],row['repetition'],row['implementation'])
        require(key not in keys,'duplicate timed call')
        keys.add(key)
        seconds = float(row['seconds'])
        require(math.isfinite(seconds) and seconds > 0 and row['full_view_equal'] == 'True','timed call')
    for row in cases:
        selected = [r for r in raw if all(r[k] == row[k] for k in ('family','handles','seed'))]
        require(len(selected) == 15,'case calls')
        for rep in range(5):
            group = [r for r in selected if int(r['repetition']) == rep]
            require({r['implementation'] for r in group} == set(implementations) and
                    {r['position'] for r in group} == {'0','1','2'},'timing order')
        for name in implementations:
            value = 1000*statistics.median(float(r['seconds']) for r in selected if r['implementation'] == name)
            require(near(value,row[name+'_median_ms']),'case median')
        require(near(float(row['scanning_median_ms'])/float(row['indexed_median_ms']),row['scanning_over_indexed']),
                'scan ratio')
        require(near(float(row['mws_edge_ids_median_ms'])/float(row['indexed_median_ms']),row['mws_over_indexed']),
                'MWS ratio')
    for row in summary:
        selected = [r for r in cases if all(r[k] == row[k] for k in ('family','handles'))]
        require(len(selected) == 5,'summary seeds')
        for key in ('scanning_median_ms','indexed_median_ms','mws_edge_ids_median_ms',
                    'scanning_over_indexed','mws_over_indexed'):
            require(near(statistics.median(float(r[key]) for r in selected),row[key]),'summary median')
    with (ROOT/'results'/'correctness.csv').open(newline='',encoding='utf-8') as f:
        historical = list(csv.DictReader(f))
    factorial = read('generated_ablations.csv')
    require(len(factorial) == 60,'generated rows')
    for family,seed in itertools.product(('sparse=0.00','sparse=0.08','sparse=0.20'),('7','19','43','71','97')):
        group = [r for r in factorial if (r['family'],r['seed']) == (family,seed)]
        require(len(group) == 4 and {(r['relation_veto'],r['component_veto']) for r in group} ==
                set(itertools.product(('True','False'),repeat=2)),'factorial design')
        for row in group:
            method = 'sealed-evidence q=2' if row['relation_veto'] == 'True' else 'no negative veto'
            old = next(r for r in historical if r['trial'] == f'{family};seed={seed}' and r['method'] == method)
            for key in ('false_merge_pairs','false_split_pairs','false_merge_rate','false_split_rate'):
                require(near(row[key],old[key]),'historical metric mismatch')
            if row['relation_veto'] == 'True':
                require(row['view_equal_to_cie'] == 'True' and row['rejected'] == '0','isolated guard control')
    triangle = read('reachable_veto.csv')
    require(len(triangle) == 4,'reachable rows')
    require(triangle[0]['components'] == '2' and triangle[0]['original_negative_violations'] == '0','guarded triangle')
    require(triangle[1]['components'] == '1' and triangle[1]['selected_negative'] == '1' and
            triangle[1]['original_negative_violations'] == '1','component-only triangle')
    require(all(r['selected_negative'] == '0' for r in triangle[2:]),'relation-off interaction')
    witness = json.loads((OUT/'priority_witness.json').read_text(encoding='utf-8'))
    require(witness['weighted_result']['components'] == [['a','b','c']] and
            witness['weighted_result']['ignored_negative'] == [['a','c']],'weighted witness')
    require(witness['negative_first_result']['components'] == [['a','b'],['c']],'special-priority witness')
    print('PASS: 729 full-view graph comparisons; 60 factorial rows match retained correctness metrics; '
          'reachable component-only violation; weighted priority witness; 900 raw calls/60 cases/12 summaries reaggregated')


if __name__ == '__main__':
    main()
