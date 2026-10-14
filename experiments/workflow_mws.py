"""Same-contract native volatile loopback comparison; no remote targets.

Persistence is deliberately NOT a service guarantee of this experiment. The
unchanged POSIX file-and-directory-fsync Service is probed separately. Every
implementation receives identical source batches, epoch changes and floor
protocol, and every query is checked against its coupled state.
"""
from __future__ import annotations
import argparse
import asyncio
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time

from cie.model import EvidenceCell, Replica, Vote
from cie.mutex_baseline import priority_preserving_mws
from cie.service import Service, WireStats, rpc, common_floor_reports
from cie import service as service_module
from materializer_campaign import instance

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workflow_checker', ROOT/'checker/verify.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def require(value, message):
    if not value:
        raise ValueError(message)


def clock_record():
    return {name: vars(time.get_clock_info(name)) for name in
            ('time', 'monotonic', 'perf_counter', 'process_time')}


def environment():
    host = None
    if sys.platform == 'win32':
        command = ("[pscustomobject]@{cpu=Get-CimInstance Win32_Processor | "
                   "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors; "
                   "os=Get-CimInstance Win32_OperatingSystem | "
                   "Select-Object Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize; "
                   "volume=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='D:'\" | "
                   "Select-Object FileSystem,DriveType} | ConvertTo-Json -Depth 5")
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                                capture_output=True, timeout=20)
        require(result.returncode == 0, 'host inventory failed')
        host = json.loads(result.stdout.decode('utf-8-sig'))
    return dict(python=sys.version, python_executable=sys.executable,
                platform=platform.platform(), sqlite=sqlite3.sqlite_version,
                sqlite_role='runtime inventory only; this service does not use SQLite',
                clocks=clock_record(), host=host, affinity='not pinned',
                allocation_limit='unknown', virtualization='unknown',
                persistence_medium='unknown',
                scope='this execution only; no historical environment attribution')


class VolatileService(Service):
    """Explicit memory-only experimental owner; not a durability substitution."""
    def __init__(self, *args, implementation, **kwargs):
        self.implementation = implementation
        self.volatile_commits = 0
        super().__init__(*args, **kwargs)

    def _commit(self, proposed):
        self._admit(proposed)
        if self.implementation == 'scanning':
            proposed.materialize = proposed.materialize_reference
        elif self.implementation == 'mws_small_table':
            proposed.materialize = lambda: priority_preserving_mws(proposed)
        self.replica = proposed
        self.volatile_commits += 1


async def native_persistence_probe(out):
    service = Service('probe', ['s'], 1, ['a','b'], ['probe'], out/'probe'/'state.json')
    error = None
    try:
        await service.dispatch({'op':'ingest', 'cells':[
            EvidenceCell('a','b',0,'s',Vote.SAME,'owned native boundary').to_dict()]})
    except OSError as exc:
        error = dict(type=type(exc).__name__, errno=exc.errno, winerror=getattr(exc,'winerror',None))
    return dict(acknowledged=error is None, error=error,
                replaced_snapshot_exists=service.snapshot.exists(),
                cells_in_memory=len(service.replica),
                contract='unchanged Service: content fsync + replace + parent directory fsync',
                substitute_used=False, power_loss_test=False)


async def case(out, family, n, seed, implementation):
    start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    r = instance(family, n, seed)
    # All names are synthetic handles; no URLs, scanners or acquired payloads.
    members = ['n0','n1','n2']
    wire = WireStats()
    owners = [VolatileService(node, list(r.sources), r.threshold, list(r.handles), members,
              out/'unused-volatile-paths'/f'{family}-{n}-{seed}-{implementation}-{node}.json',
              wire, implementation=implementation) for node in members]
    events, peer_frames = [], []
    query = (r.handles[0], r.handles[-1]) if family == 'low_conflict' else (r.handles[0],r.handles[1])
    ports = []
    original_peer_rpc = service_module.rpc

    async def recorded_peer_rpc(port, request, stats=None):
        # Instrumentation delegates to the real loopback RPC. No transport,
        # persistence or decision mechanism is replaced by this recorder.
        answer = await original_peer_rpc(port, request, stats)
        peer_frames.append(dict(port=port,request=request,response=answer))
        return answer
    async def call(node, request, phase):
        t = time.perf_counter_ns()
        answer = await rpc(ports[node], request, wire)
        events.append(dict(phase=phase,node=node,request=request,response=answer,
                           rpc_ns=time.perf_counter_ns()-t))
        if request['op'] == 'query':
            t = time.perf_counter_ns()
            checker.verify(answer['state'], answer['certificate'])
            events[-1]['checker_ns'] = time.perf_counter_ns()-t
        require(time.perf_counter_ns()-start < 120_000_000_000, '120-second case cap')
        return answer

    async def heal(phase):
        for a in range(3):
            for b in range(3):
                if a != b:
                    await call(a, {'op':'pull','peer_port':ports[b]}, phase)

    service_module.rpc = recorded_peer_rpc
    try:
        for owner in owners:
            ports.append(await owner.start())
        for i, source in enumerate(r.sources):
            await call(i, {'op':'ingest','cells':[c.to_dict() for c in r.cells if c.source == source]}, 'initial_update')
        partial = [await call(i, {'op':'query','left':query[0],'right':query[1]}, 'partition_query') for i in range(3)]
        require(all(x['certificate']['kind'] == 'ambiguous' for x in partial), 'partial closure')
        await heal('initial_repair')
        initial = [await call(i, {'op':'query','left':query[0],'right':query[1]}, 'complete_query') for i in range(3)]
        expected = r.certificate(*query)
        require(all(x['certificate'] == expected for x in initial), 'same-semantic complete query')
        # Actual later sealed epoch; it may split the earlier low-conflict view.
        delta = []
        for i, source in enumerate(r.sources):
            c = EvidenceCell(*query, 1, source, Vote.DIFFERENT if i == 0 else Vote.UNKNOWN,
                             'owned later negative epoch')
            delta.append(c)
            await call(i, {'op':'ingest','cells':[c.to_dict()]}, 'later_update')
        await heal('later_repair')
        for c in delta:
            r.add(c)
        later = [await call(i, {'op':'query','left':query[0],'right':query[1]}, 'later_query') for i in range(3)]
        require(all(x['certificate'] == r.certificate(*query) for x in later), 'later semantics')
        reports = [await call(i, {'op':'report'}, 'floor_reports') for i in range(3)]
        floors = common_floor_reports([x['sealed'] for x in reports])
        acks = [await call(i, {'op':'ack','floors':floors}, 'floor_acks') for i in range(3)]
        for i in range(3):
            await call(i, {'op':'compact','floors':floors,'acks':acks,'pending':0}, 'compaction')
        r.compact({(a,b):e for a,b,e in floors},0)
        await heal('floor_repair')
        finals = [await call(i, {'op':'query','left':query[0],'right':query[1]}, 'final_query') for i in range(3)]
        expected_state = r.export_state()
        for answer in finals:
            state = dict(answer['state'],node_id=expected_state['node_id'])
            require(state == expected_state and answer['certificate'] == r.certificate(*query), 'final state/certificate')
    finally:
        for owner in owners:
            await owner.close()
        service_module.rpc = original_peer_rpc
    elapsed = time.perf_counter_ns()-start
    phase_ns = {phase:sum(e['rpc_ns']+e.get('checker_ns',0) for e in events if e['phase']==phase)
                for phase in sorted({e['phase'] for e in events})}
    row = dict(family=family,handles=n,seed=seed,implementation=implementation,
               workflow_ns=elapsed,process_cpu_ns=time.process_time_ns()-cpu_start,
               phases_including_checker_ns=phase_ns,top_level_events=len(events),
               wire_requests=wire.requests,wire_bytes=wire.total_bytes,
               certificate_generations=wire.certificate_generations,
               certificate_ms=wire.certificate_generation_ms,
               volatile_commits=sum(x.volatile_commits for x in owners),
               snapshot_bytes=wire.snapshot_bytes,fsyncs=wire.fsyncs,durable_commits=wire.commits,
               final_state_bytes=sum(len(json.dumps(x.replica.export_state(),sort_keys=True,separators=(',',':')).encode()) for x in owners),
               all_predicates_pass=True,persistence='none: volatile local owners',
               scope='elapsed includes generation/start/update/repair/query/checker/floors/close; excludes raw serialization')
    path = out/f'{family}-{n}-{seed}-{implementation}.json.gz'
    with gzip.open(path,'wt',encoding='utf-8') as stream:
        json.dump(dict(input_parameters=dict(family=family,handles=n,seed=seed),
                       input_state=instance(family,n,seed).export_state(),
                       events=events,peer_frames=peer_frames,finals=finals,row=row),stream,sort_keys=True)
    return row


async def run(out):
    require(not out.exists(), 'fresh output directory required')
    out.mkdir(parents=True)
    (out/'environment.json').write_text(json.dumps(environment(),indent=2),encoding='utf-8')
    probe = await native_persistence_probe(out)
    (out/'native-persistence-probe.json').write_text(json.dumps(probe,indent=2),encoding='utf-8')
    rows = []
    names = ('indexed','mws_small_table','scanning')
    start = time.monotonic()
    for family in ('sparse_cut','dense_cut','low_conflict'):
        for n in (64,128):
            for seed in (1,2):
                order = names[seed%3:]+names[:seed%3]
                for implementation in order:
                    rows.append(await case(out,family,n,seed,implementation))
                    require(time.monotonic()-start < 180, '180-second campaign cap')
    summary = dict(cases=rows,case_count=len(rows),input_graphs=12,
                   raw_event_count=sum(r['top_level_events'] for r in rows),
                   total_wire_requests=sum(r['wire_requests'] for r in rows),
                   total_wire_bytes=sum(r['wire_bytes'] for r in rows),
                   certificate_checks=sum(r['certificate_generations'] for r in rows),
                   total_elapsed_seconds=time.monotonic()-start,
                   comparable_semantics=True,same_persistence_policy='explicitly volatile for all arms',
                   durable_service_costs_measured=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    asyncio.run(run(parser.parse_args().out))
