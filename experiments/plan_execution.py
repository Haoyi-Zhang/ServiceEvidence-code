"""Owned bounded execution of hypothetical ambiguity completions.

No measurement sources are contacted, and constructed votes are not claims
about external identity. Fresh epochs exceed ALL retained epochs, including
unsealed ones. All other relation decisions remain unchanged.
"""
import argparse
import gzip
import importlib.util
import itertools
import json
from pathlib import Path

from cie.model import Replica, EvidenceCell, Vote
from cie.mutex_baseline import priority_preserving_mws

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('execution_checker', ROOT/'checker/verify.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def complete(replica, certificate):
    result = Replica.import_state(replica.export_state())
    for step in certificate['steps']:
        edge = tuple(step['pair'])
        epoch = max(result.relation_epochs().get(edge, {-1:{}})) + 1
        for source in result.sources:
            vote = Vote.SAME if source in step['same_sources'] or source in step['gap_sources'] else Vote.UNKNOWN
            result.add(EvidenceCell(*edge, epoch, source, vote, 'hypothetical owned completion'))
    return result


def run(out, source_count=3, allow_absent=False):
    if out.exists():
        raise ValueError('fresh output directory required')
    out.mkdir(parents=True)
    pairs = tuple(itertools.combinations('abcd',2))
    labels_allowed = ('same','different','unknown','absent') if allow_absent else ('same','different','unknown')
    sources = tuple(f's{i}' for i in range(source_count))
    counts = dict(graphs=0,queries=0,executed_plans=0,new_cells=0,mismatches=0,
                  sources=source_count,alphabet=labels_allowed,plan_edge_counts={})
    with gzip.open(out/'plans.jsonl.gz','wt',encoding='utf-8') as stream:
        for labels in itertools.product(labels_allowed,repeat=6):
            replica = Replica('owned',sources,2,'abcd')
            for edge, label in zip(pairs,labels):
                if label == 'absent':
                    continue
                votes = {'same':('same','same')+('unknown',)*(source_count-2),
                         'different':('unknown',)*(source_count-1)+('different',),
                         'unknown':('same',)+('unknown',)*(source_count-1)}[label]
                for source,vote in zip(replica.sources,votes):
                    replica.add(EvidenceCell(*edge,0,source,Vote(vote),'owned ternary fixture'))
            counts['graphs'] += 1
            for query in pairs:
                cert = replica.certificate(*query)
                checker.verify(replica.export_state(),cert)
                counts['queries'] += 1
                if cert['kind'] != 'ambiguous':
                    continue
                after = complete(replica,cert)
                before_view, after_view = replica.materialize(),after.materialize()
                success = (after_view.component_of[query[0]] == after_view.component_of[query[1]]
                           and after_view == after.materialize_reference() == priority_preserving_mws(after)
                           and set(before_view.accepted_same_edges) <= set(after_view.accepted_same_edges)
                           and all(len({after_view.component_of[h] for h in group}) == 1
                                   for group in before_view.components)
                           and before_view.different_edges == after_view.different_edges)
                counts['executed_plans'] += 1
                size = str(cert['edge_count'])
                counts['plan_edge_counts'][size] = counts['plan_edge_counts'].get(size,0)+1
                counts['new_cells'] += len(after)-len(replica)
                counts['mismatches'] += int(not success)
                stream.write(json.dumps(dict(state=replica.export_state(),certificate=cert,
                    after=after.export_state(),components_after=after_view.components,
                    contract_pass=success),sort_keys=True)+'\n')
    (out/'summary.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
    print(json.dumps(counts))
    if counts['mismatches']:
        raise ValueError('plan execution mismatch')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--sources',type=int,choices=(3,5),default=3)
    p.add_argument('--allow-absent',action='store_true')
    args = p.parse_args()
    run(args.out,args.sources,args.allow_absent)
