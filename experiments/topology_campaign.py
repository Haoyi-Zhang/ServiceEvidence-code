#!/usr/bin/env python3
"""Exact responsiveness over an explicitly uniform finite partition universe."""
from __future__ import annotations
import csv
import itertools
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def partitions(n: int):
    if n < 1:
        raise ValueError('n must be positive')
    def extend(i, blocks):
        if i == n:
            yield tuple(tuple(b) for b in blocks)
            return
        for j in range(len(blocks)):
            blocks[j].append(i)
            yield from extend(i+1, blocks)
            blocks[j].pop()
        blocks.append([i]); yield from extend(i+1, blocks); blocks.pop()
    yield from extend(0, [])

def responsiveness(blocks, central, quorum):
    n = sum(map(len, blocks))
    c = next(b for b in blocks if central in b)
    reachable = sum(len(b) for b in blocks if len(set(b) & set(quorum)) >= 2)
    return Fraction(len(c), n), Fraction(reachable, n), Fraction(1)

def run():
    out = ROOT/'results'/'tpds'; out.mkdir(parents=True, exist_ok=True)
    allp = [p for p in partitions(5) if len(p) > 1]
    assert len(allp) == len(set(allp)) == 51
    rows = []
    groups = defaultdict(list)
    for i, blocks in enumerate(allp):
        for central in range(5):
            for quorum in itertools.combinations(range(5), 3):
                c, q, peer = responsiveness(blocks, central, quorum)
                row = dict(partition=i, blocks='|'.join(','.join(map(str,b)) for b in blocks),
                    components=len(blocks), central=central, quorum=','.join(map(str,quorum)),
                    central_responding_sites=int(5*c), quorum_responding_sites=int(5*q),
                    peer_responding_sites=5, query_sites=5)
                rows.append(row); groups[len(blocks)].append((c,q,peer))
    with (out/'topology_cases.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=[]
    for k, vals in sorted(groups.items()):
        summary.append(dict(components=k, placements=len(vals),
            central_mean=str(sum(v[0] for v in vals)/len(vals)),
            quorum_mean=str(sum(v[1] for v in vals)/len(vals)), peer_mean='1'))
    report=dict(sites=5, nonconnected_partitions=len(allp), placement_cases=len(rows),
        query_checks=5*len(rows),
        central_gt_quorum=sum(r['central_responding_sites']>r['quorum_responding_sites'] for r in rows),
        quorum_gt_central=sum(r['central_responding_sites']<r['quorum_responding_sites'] for r in rows),
        equal=sum(r['central_responding_sites']==r['quorum_responding_sites'] for r in rows),
        central_mean=str(sum(Fraction(r['central_responding_sites'],5) for r in rows)/len(rows)),
        quorum_mean=str(sum(Fraction(r['quorum_responding_sites'],5) for r in rows)/len(rows)),
        strata=summary,
        scope='combinatorial response reachability, not network measurements or decisive authorization',
        distribution='uniform over 51 partitions, 5 central placements, 10 quorum placements')
    (out/'topology_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':run()
