# Convergent Identity Evidence

This artifact implements source-indexed evidence reconciliation, not an Internet identity classifier. Immutable evidence cells join by set union; acknowledged per-relation floors join by maximum and suppress obsolete history. Reads select the greatest sealed source vector, apply a negative veto and positive threshold, and derive a deterministic negative-safe partition. Each query returns its serialized state together with a `same`, `different`, or `ambiguous` certificate.

An ambiguity certificate is an exact bounded authorization plan for the supplied state. The service contracts current components, assigns each unknown relation its source-slot intervention cost, and enumerates simple quotient paths whose complete component set contains no selected negative pair. It minimizes intervention count, then edge count, then deterministic order. The independent checker repeats the search without importing the producer. Source-slot cost is a logical edit metric relative to an existing vector, not the number of network requests needed for a fresh epoch. This guarantee applies only to the frozen source registry, threshold, candidate graph, and selected negatives; it does not validate source truth or identify a unique real-world partition.

## Execution paths and architecture comparison

The in-process simulator holds five replica objects and delivers cells directly. Its final repair uses a global retained-cell list. The 79,990-cell scale point and 25 fault trials therefore measure simulated delivery semantics, not network-service throughput.

The peer service exposes five loopback TCP endpoints in one event loop. Each owns an independent replica state. Repair exchanges peer inventories, missing cells, handles, floors, and complete floor vectors; no workload oracle participates. Before acknowledging a mutation, the service validates the replacement state, fsyncs a temporary snapshot, atomically replaces the saved snapshot, and fsyncs the parent directory. A failure before replacement preserves the prior state. A failure after replacement but before acknowledgement is an unacknowledged outcome even though the immutable update may be present; retry is idempotent. The event-loop campaign closes and reopens endpoints orderly.

A query normally returns one state-coupled certificate with the complete serialized state. If repeating the same evidence bodies in both surfaces would exceed the 4~MiB frame bound, the transport replaces certificate cells with immutable `(left, right, epoch, source)` keys into that same returned snapshot; the independent checker resolves and verifies those keys. If the key-reference response still cannot fit, the service returns a framed atomic error rather than beginning a partial frame or silently closing the connection. A static boundary regression covers this serialization case; it is not reported as a performance experiment.

A separate recovery campaign starts four independent Python service processes, distributes five evidence sources across them, and uses two process groups during the partition. Each of three 2,200-cell cases sends `SIGKILL` only after an acknowledged commit, restarts that process from its snapshot, heals through peer pulls, then repeats a post-convergence abrupt restart. This establishes recovery of acknowledged snapshots after process exit on one host. It does not inject a crash inside a write, torn-sector behavior, filesystem failure, power loss, independent-machine failure, or crash consensus.

The equal-work campaign adds two reference architectures using the same evidence decisions, JSON/TCP framing, file-and-directory durable snapshot replacement, restart check, and state-coupled certificate:

- `central-recompute`: one persistent authority; unreachable client batches are durably spooled and replayed after healing;
- `coordinated-quorum`: three persistent authorities at clients 0, 2, and 4; a reachable majority is required; and
- `peer-evidence`: five locally writable/queryable replicas that reconcile retained evidence after healing.

Five seeds and two fixed client partitions produce 30 paired cases. The comparison reports partition-time write/query availability, wire bytes, cumulative snapshot/spool bytes, final durable bytes, request latency, certificate cost, elapsed time, final correctness, and orderly restart recovery. It isolates an architecture tradeoff on one machine; it is not a production consensus or wide-area benchmark. The reported query availability means responsiveness, not a decisive or globally fresh identity authorization.

## Public evidence and label boundary

`external_inputs/public_http_calibration.csv` contains six factual navigation rows from three released *Web Performance Pitfalls* sample HAR files. Its conservative adapter emits only UNKNOWN evidence. This input calibrates redirects, authorities, and endpoint changes and exercises the service input path; it has no identity labels.

`external_inputs/ooni_fixture_selection.csv` records 16 inspected public OONI Web Connectivity fixture candidates, 12 retained unique measurements, and four exclusions with explicit reasons. All upstream fixture and archived-input URLs are recorded as public repository paths in `external_inputs/NOTICE.md`, with access dates in `external_resources.csv`; reproduction uses the retained factual extraction and performs no live fetch. `external_inputs/ooni_dual_vantage_targets.csv` is the minimized side-specific factual extraction; each retained measurement contributes one probe observation and one control observation. `external_inputs/ooni_field_mapping.csv` identifies the source paths and records where fields are absent. Missing probe titles are not synthesized from match flags, DNS or HTTP records are not converted into unreported TCP successes, and negative/zero status values remain missing to the predicate. The 24 observations span 10 countries and 10 probe ASNs and yield 276 pairs over 11 normalized input targets: 16 exact-target matches and 260 cross-target pairs.

The evaluated two-signal predicate never reads the target label. It returns SAME only when successful endpoint overlap **and** a matching successful HTTP signature both hold; it returns DIFFERENT only for disjoint successful endpoints plus two independent HTTP conflicts; otherwise it returns UNKNOWN. The retained finite-family result is 3 SAME, 17 DIFFERENT, 256 UNKNOWN, and zero asserted-label errors. A deliberately closed-world endpoint control asserts every pair and makes nine errors: two false merges and seven false splits. Three threshold settings, 11 leave-one-target-out folds, and 12 leave-one-measurement-out folds are retained. The labels identify exact normalized input targets only, not ownership, common operator, or equivalence across different URLs.

## Reproduction

The artifact uses Python's standard library and Bash. From this directory:

```sh
./scripts/check_all.sh
./scripts/reproduce.sh
./scripts/reproduce_extended.sh
```

`check_all.sh` runs 57 unit and boundary tests, including all 720 orders of the six-cell split history, strict parsing/common-floor regressions, globally compatible ambiguity regressions, public-extraction/predicate checks, atomic persistence failures, concurrent-ingest serialization, read-only acknowledgement, stale-temporary cleanup, and cross-process hash-seed determinism. It also runs the public-input and 68-reference audits (including per-paper supported points, project deltas, and named source anchors), checks representative certificates in normal and optimized Python modes, verifies every retained result surface, evaluates 276 public target pairs, and checks the 30 equal-work rows, independent-process recovery summaries, 60 materializer cases, and 2,550 exact topology placements.

`reproduce.sh` recreates and independently verifies the retained core simulation families, 207 certificate measurements, compaction, five scale cases, the six-row navigation calibration, and the public target benchmark. It is self-contained in an empty `results/` directory; its final verifier intentionally does not require extended-campaign files.

`reproduce_extended.sh` additionally runs the independent finite oracles, the full 30-case equal-work campaign, three independent-process recovery cases, the peer loopback pilot and five 2,200-cell cases, and the public adapter replay. Final verification covers seven peer-service cases, 70 peer-service state-coupled certificates, 135 equal-work certificates, 30 process-campaign certificate checks, availability and persistence predicates, event counts, and case limits.

Scientific runs are capped at 180 seconds. Service cases additionally enforce 120 seconds, 5,000 requests, 100 MiB application wire bytes, a 4 MiB frame limit, and admission limits of 10,000 cells and 30,000 handles. The simulator alone has the larger 80,000-cell and 500,000-delivery caps. Faults are deterministic application-message omissions, duplication, peer-order changes, temporary partitions, and post-acknowledgement process exits—not raw TCP packet manipulation or power-loss injection.

The finite checks comprise:

- 729 four-handle three-valued relation graphs and 4,374 reconstructed query certificates;
- 192 three-source closure-aware intervention-cost cases;
- 21 admissible floor states and 9,261 associativity triples; and
- 4,096 four-component diagnostic graphs with 18,432 queries.

The last family finds 144 queries where an adjacency-only ambiguity path would contain a non-adjacent selected-negative pair. The repaired search rejects all 144; the globally compatible optimum costs one additional slot in 108 cases and two in 36. These are exact bounded comparisons, not whole-program verification.

Check one certificate with:

```sh
python checker/verify.py results/example_state.json results/example_same_certificate.json
```

Regenerate the paper's data-derived tables with:

```sh
python scripts/render_socket_table.py
python scripts/render_socket_table.py --numbers
python scripts/render_evidence_tables.py public
python scripts/render_evidence_tables.py equal
python scripts/render_tpds_assets.py --output /path/to/paper/tables
```

## Indexed materialization and topology sensitivity

The default materializer maintains, for each live component, the union of its
members' selected-negative neighbor identifiers. Entries are original handles,
not mutable disjoint-set roots. `materialize_reference` preserves the scanning
implementation. Both have identical semantics; the index uses at most twice the
number of selected negative edges in live membership entries. Four differential
tests cover exhaustive four-handle graphs, multi-epoch partial states, compaction,
and empty/extended handle sets.

`experiments/materializer_campaign.py` generates sparse-cut, dense-cut, and
low-conflict families at 64/128/256/512 handles and five seeds, with five paired
full-call repetitions and alternating timing order. No timing-based pass threshold
is used. All raw measurements, including regressions, remain in `results/tpds/`.
`experiments/topology_campaign.py` enumerates 51 nonconnected five-site partitions,
five authority locations and ten quorum placements. It analyzes response
reachability, not network latency or the availability of decisive answers.

`./scripts/reproduce_extended.sh` executes these campaigns and their verifier.
No large unseen OONI holdout or 150-window crash experiment is included or claimed.

## Retained results

All seven event-loop peer-service cases converge in one fair repair round after three faulted rounds. Representative generated queries change from ambiguous during the partition to same after healing. Missing acknowledgements and malformed batches are rejected; floor propagation, stale-state suppression, compaction, and orderly restart preserve the checked state. The five 2,200-cell cases use 191–200 request/response exchanges.

The independent-process campaign contains three cases, four processes per case, five evidence sources, 2,200 cells, and two post-ack abrupt exits per case. All 12 partition-time queries remain ambiguous; all six restarts recover their acknowledged state; all cases converge in one heal round; and 30 generated certificates verify. Elapsed times are retained per case in the result files.

In the equal-work campaign, peer evidence keeps 100% of partitioned clients available, central recomputation averages 50%, and coordinated quorum reaches 60%. Every available partition-time answer is ambiguous; no architecture authorizes SAME from a partial source vector. After healing, all 30 cases contain all 2,200 cells, return the same independently checked SAME certificate, have zero generated false merge/split pairs, and recover after orderly restart. Median wire/persisted/final-durable volumes are 5.27/6.37/1.27 MiB for peer evidence, 2.93/3.78/0.76 MiB for quorum, and 1.10/1.02/0.25 MiB for central recomputation. One-machine elapsed times are retained per case rather than treated as stable reproduction fields.

The selected threshold-two rule has zero false merges in the frozen generated correctness families and a mean 12% false-split cost. This is model evidence, not a Web identity accuracy estimate. The largest in-process case retains 79,990 cells and 419,348 delivered events, including oracle repair; it is not relabelled as TCP performance.

`results/reproduction.json` records the final clean-copy commands and stable-field comparison. Timing, latency, and resident-memory fields are explicitly excluded from deterministic equality; wire bytes, event counts, decisions, states, and certificates are not. Use the comparison utility on two independent result directories:

```sh
python scripts/compare_results.py /path/to/reference/results /path/to/recomputed/results
```

## Boundaries

The model requires a finite candidate graph, fixed source registry, non-equivocation, sound negative predicates, and threshold separability for one fixed equivalence relation. Sealing is a completeness condition, not current-time freshness. Compaction is conditional on a successfully acknowledged floor and pending-count check. The prototype does not provide Byzantine robustness, dynamic membership, authenticated clients, process-crash consensus, mid-write crash consistency, power-loss durability, or a Web-wide service-identity predicate.

The public fixture check is intentionally narrower: it evaluates exact normalized input-target equality on a frozen, nonprobability upstream fixture family whose pairs share observations. It does not support ownership, operator, cross-URL service-equivalence, or Web-population accuracy claims. Event-loop, equal-work, and process results are one-host measurements and do not predict wide-area latency or production throughput. The durability tests distinguish pre-replace failure from an unacknowledged post-replace outcome; they do not establish exactly-once requests, torn-write recovery, or power-loss durability.

## Layout

`src/cie/` contains the model, service, public predicate, conservative navigation adapter, workload generators, metrics, and simulator. `checker/` is a separate verifier importing none of the model implementation. `tests/`, `experiments/`, and `scripts/` contain deterministic checks, the public-input selection audit, the bibliography audit, and reproduction commands. `literature/` contains the bibliography and cited-key evidence needed to run that audit without a sibling manuscript directory. `proofs/model-and-proofs.md` states assumptions, proofs, counterexamples, the target-predicate boundary, and architecture limits. `external_inputs/` retains the legally redistributable factual inputs, selection manifest, field mapping, notices, and licenses. `results/` contains claim-linked raw surfaces; the claim and resource ledgers map them to the manuscript.


### Journal evidence and statistical scope
The main article is a replicated-evidence study, not a trained identity classifier.
The public fixture pairs are dependent and selected upstream; independent-pair
confidence intervals are not reported. Their leave-group-out ranges are finite
sensitivity summaries, not an unseen large holdout. For the materializer, two 512-handle executions retain all 600 per-call timing records: the clean run in `results/reproduction.json` and the final current run in `results/tpds/`. Both are independently reaggregated and preserve identical complete views; their sparse-cut medians are 2.32 and 2.72, while the two controls remain near one. An earlier 3.03 sparse-cut value survives only as an aggregate summary. Its per-call timings are unavailable, so it is retained for transparency but is not counted as a complete or independently reproducible execution. `results/tpds/materializer_replications.csv` and `materializer_provenance.json` record that distinction. Neither runtime nor speedup is a correctness gate.

All cited historical timing runs predate environment capture. CPU model and core allocation, memory constraint, OS and Python version, container or virtualization limits, persistence medium, and filesystem are therefore listed as unknown in `results/timing_environment_inventory.csv`. The reproduction entry points invoke `scripts/capture_environment.py` so new executions record those fields automatically without retroactively attributing them to historical measurements.

The main and supplemental numeric assets can be reproduced by
`python scripts/render_tpds_assets.py --output /path/to/table-directory`.
The path is explicit so this repository does not depend on a manuscript tree.
