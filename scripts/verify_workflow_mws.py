"""Replay raw same-information workflow and plan outcomes; no sockets."""
import argparse
from collections import Counter
import gzip
import importlib.util
import json
from pathlib import Path

from cie.model import Replica
from cie.mutex_baseline import priority_preserving_mws
from cie.service import pack, bounded_response

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workflow_replay_checker',ROOT/'checker/verify.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def require(value, message):
    if not value:
        raise ValueError(message)


def main(root):
    workflow = root/'workflow-003'
    summary = json.loads((workflow/'summary.json').read_text(encoding='utf-8'))
    expected = {(f,n,s,a) for f in ('sparse_cut','dense_cut','low_conflict')
                for n in (64,128) for s in (1,2)
                for a in ('indexed','mws_small_table','scanning')}
    observed = set()
    common = {}
    events = checks = requests = wire_bytes = 0
    for path in sorted(workflow.glob('*.json.gz')):
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            data = json.load(stream)
        row = data['row']
        key = tuple(row[k] for k in ('family','handles','seed','implementation'))
        require(key not in observed,'duplicate case')
        observed.add(key)
        require(row in summary['cases'],'summary row mismatch')
        cohort = key[:3]
        state = data['input_state']
        if cohort in common:
            require(state == common[cohort], 'unequal baseline input information')
        common[cohort] = state
        require(len(data['events']) == row['top_level_events'] == 45,'event count')
        require((row['snapshot_bytes'],row['fsyncs'],row['durable_commits']) == (0,0,0),'volatile boundary')
        require(row['volatile_commits'] == 27,'update/merge/compact count')
        phases = Counter()
        for event in data['events']:
            phases[event['phase']] += 1
            require(event['rpc_ns'] > 0,'nonpositive timing')
            if event['request']['op'] == 'query':
                answer = event['response']
                checker.verify(answer['state'],answer['certificate'])
                replica = Replica.import_state(answer['state'])
                require(replica.materialize() == replica.materialize_reference() == priority_preserving_mws(replica),
                        'whole-view comparator mismatch')
                checks += 1
        require(phases == Counter(initial_update=3,partition_query=3,initial_repair=6,
                complete_query=3,later_update=3,later_repair=6,later_query=3,
                floor_reports=3,floor_acks=3,compaction=3,floor_repair=6,final_query=3),'phase schedule')
        expected_phases = {phase:sum(e['rpc_ns']+e.get('checker_ns',0) for e in data['events']
                                  if e['phase']==phase) for phase in phases}
        require(row['phases_including_checker_ns'] == expected_phases,'phase cost')
        require(row['wire_requests'] == 81,'nested peer RPC count')
        require(len(data['peer_frames']) == 36,'raw nested frame count')
        frames = data['events']+data['peer_frames']
        rebuilt_bytes = sum(len(pack(e['request'])) + len(bounded_response(e['request'],e['response']))
                            for e in frames)
        require(rebuilt_bytes == row['wire_bytes'],'raw frame byte accounting')
        events += len(data['events'])
        requests += row['wire_requests']
        wire_bytes += row['wire_bytes']
    require(observed == expected and len(common) == 12,'case matrix')
    require((events,checks,requests,wire_bytes) == (summary['raw_event_count'],summary['certificate_checks'],
                summary['total_wire_requests'],summary['total_wire_bytes']),'total accounting')
    plans = root/'execution-002'
    plan_summary = json.loads((plans/'summary.json').read_text(encoding='utf-8'))
    count = new_cells = 0
    with gzip.open(plans/'plans.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:
            data = json.loads(line)
            checker.verify(data['state'],data['certificate'])
            before, after = map(Replica.import_state,(data['state'],data['after']))
            bv,av = before.materialize(),after.materialize()
            query = data['certificate']['query']
            require(av.component_of[query[0]] == av.component_of[query[1]],'execution did not connect')
            require(av == after.materialize_reference() == priority_preserving_mws(after),'completed view mismatch')
            require(all(len({av.component_of[h] for h in block}) == 1 for block in bv.components),'old component split')
            require(set(bv.accepted_same_edges) <= set(av.accepted_same_edges),'lost accepted support')
            require(av.different_edges == bv.different_edges,'changed negative set')
            count += 1
            new_cells += len(after)-len(before)
    require(plan_summary['graphs'] == 4096 and plan_summary['queries'] == 24576,'finite absent-relation domain')
    require(count == plan_summary['executed_plans'] and new_cells == plan_summary['new_cells'],'plan raw totals')
    result = dict(workflow_cases=36,input_graphs=12,raw_events=events,query_checks=checks,
                  nested_requests=requests,wire_bytes=wire_bytes,plans=count,new_cells=new_cells,
                  mismatches=0,fulltext_certification=False,durable_service_validation=False)
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    main(p.parse_args().root)
