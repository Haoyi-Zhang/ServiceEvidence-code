# Smaller-table MWS, compatible-plan execution and same-contract workflow

This separate cohort does not replace earlier measurements. It uses owned
synthetic graph inputs, not external observations or production deployments.

`pure-003/` is the complete 60-case, 900-call comparison used in the new table.
It stores 60 actual input states in `inputs/*.json.gz`, raw per-call timings,
case/family summaries, the 729-graph consistency/ablation counts, the sealed
triangle, the weighted-priority witness and 60 factorial rows for the 15
historical generated parameter cases. The corrected MWS comparator merges the
smaller mutex-ID table independently of its union-find root. Source vectors,
threshold, complete-epoch selection, relation rules and lexical order are held
fixed. The component-only factor preserves decisions; the relation-veto-off
column removes selected negatives and makes the component factor inert. The
15 generated cases retain zero component-only effect. Their counts are not
external identity accuracy. `pure-001/` and `pure-002/` retain earlier executions;
the first overlapped another owned campaign and neither captured stress input
states. They are not pooled into the table. Selection of pure-003 is based on
complete input capture, not its timing rank.

`workflow-003/` is the final 36-case native loopback run: three implementations,
three families, two sizes (64/128) and two seeds, with three fixed local owners.
Each raw compressed case contains the input state, all 45 outer RPC events,
all 36 nested peer request/response pairs, final snapshots and measured cost
fields. The paired arms receive byte-identical source input information and the
same update/query/repair/later-epoch/floor schedule. The 1,620 outer events plus
1,296 nested frames account for 2,916 RPCs and 212,032,101 application-wire
bytes, including four-byte frame headers and full state-coupled responses.
There are 432 query/certificate checks. Every arm is **volatile**: no snapshot
write, no fsync and no durable commit occurs in these cases. The recorded
final-state bytes are in-memory serialization sizes, not durable footprint.
The table's workflow elapsed time includes generation, endpoint start, updates,
repair, queries, checker work, floor coordination and endpoint closure; it
excludes raw-log compression/writing. `workflow-phase-costs.csv` retains phase
RPC-plus-checker costs. The entire campaign elapsed time also includes writing
the raw records and is a different measure. Two preliminary cohorts remain
separate; they have no nested-frame log and are not final byte-replay evidence.

`native-persistence-probe.json` records the unchanged persistent Service's
actual Windows result. File-content fsync and snapshot replacement occur, but
parent-directory fsync raises PermissionError (errno 13), preventing an
acknowledgement. No fake directory-sync substitute is installed. The volatile
campaign does not close this durable-platform gap. Power loss, mid-write exit,
independent machines and author-optimized MWS code are not validated.

`execution-001/` contains the original ternary check: 729 graphs, 4,374 queries,
643 executed plans and 1,929 fresh cells. Its plans all have one edge.
`execution-002/` adds absent pair relations, uses five sources and q=2, and
checks 4,096 graphs and 24,576 queries. It executes 7,862 plans: 7,418 one-edge,
432 two-edge and 12 three-edge plans, adding 41,590 fresh cells. Every recorded
completion connects the query, preserves prior components and accepted support,
and leaves selected negatives unchanged; no mismatch occurs. These are actual
state-coupled future-vector replays, distinct from the older abstract quotient
oracle with the same 4,096 domain size. New epochs exceed all retained epochs,
including open ones. Votes are hypothetical owned fixtures, not verified
judgments from actual measurement sources. Candidate admission, source
cooperation, no other decision changes and sufficient capacity are prerequisites.

The prefix proof is in `proofs/model-and-proofs.md` Section 17. The 25-node,
24-edge counted-set regression exposes the comparator's old 16-insertion cost
and repaired zero-insertion transfer while preserving the view. This is a
closest-baseline repair, not an algorithm novelty or a byte lower bound.
MWS's extended Algorithm 2 already supports redundant attractive edges with
connect_all=True. An ordinary evidence log plus complete-vector selection and
MWS remains a same-semantic alternative. No novelty priority is inferred from
these finite counts or local Python timings.

Commands from the artifact directory (PYTHONPATH=src):

```text
python -B -m unittest discover -s tests -p test_mutex_merge_cost.py -v
python -B -m unittest discover -s tests -p test_mutex_baseline.py -v
python -B -m unittest discover -s tests -p test_checker_context.py -v
python -B -m unittest discover -s tests -p test_plan_execution.py -v
python -B experiments/mutex_campaign.py --out <fresh-pure-directory>
python -B scripts/verify_mutex.py --out <pure-directory>
python -B experiments/workflow_mws.py --out <fresh-workflow-directory>
python -B experiments/plan_execution.py --out <fresh-execution-directory> --sources 5 --allow-absent
python -B scripts/verify_workflow_mws.py --root results/primary-mws-20261014
```

The last replay checks the retained named cohorts, reconstructs all emitted
application frames, checks the common input matrix and independently verifies
every recorded query and completed plan. A full 86-test native durable-service
run is not implied by the 18 targeted tests.

Environment: the actual Win32_Processor/OperatingSystem/LogicalDisk inventory
and Python clocks are in `workflow-003/environment.json`. The host reports
i7-12700KF, 12 cores/20 logical processors, Windows 11 Pro 10.0.28000, Python
3.12.14 and NTFS. Timings use QueryPerformanceCounter; process CPU uses
GetProcessTimes. SQLite 3.53.1 is inventoried, not used by this service.
Affinity is unpinned; external load, allocation limits, virtualization and
persistence medium remain unknown. No historical environment is backfilled.

Primary mechanism sources read: Wolf et al., ECCV 2018, complete 17-page ECVA
author paper, especially Algorithm 2 and Section 3.4:
https://www.ecva.net/papers/eccv_2018/papers_ECCV/papers/Steffen_Wolf_The_Mutex_Watershed_ECCV_2018_paper.pdf
and the complete 15-page extended author version, including Section 4 proofs
and Appendix A: https://arxiv.org/abs/1904.12654v2 . This does not certify all
references in the bibliography as full-text read. Legal notices and source
input licenses remain unchanged. Codex assistance for this addition is
disclosed in the manuscript.
