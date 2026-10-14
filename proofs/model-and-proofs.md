# Evidence-Reconciliation Model and Proof Arguments

## 1. State, floors, and decisions

Let `H` be a finite set of service handles, `S` a fixed nonempty finite set of registered discovery sources, `q` an integer with `1 <= q <= |S|`, `R` a finite set of unordered candidate relations over distinct handles, and `E` the non-negative epoch numbers. A cell is

`c = (r, e, s, v, reason)`

where `r` is in `R`, `e` is in `E`, `s` is in `S`, and `v` is one of `same`, `different`, or `unknown`. For each `(r,e,s)`, at most one cell may exist. Conflicting cells from one source for the same key are rejected as source equivocation and are outside the model.

A replica state is `(H, F, C)`. `C` is a finite cell set. `F` maps each relation to either `-1` (no acknowledged floor) or a non-negative stable-floor epoch. An admissible state satisfies:

1. every retained cell for relation `r` has epoch at least `F(r)`; and
2. whenever `F(r) >= 0`, the state retains one floor cell for every source in `S` at `(r,F(r))`.

For admissible states from one globally non-equivocating cell universe, with the same `S` and threshold `q`, define join as:

- `H* = H1 union H2`;
- `F*(r) = max(F1(r), F2(r))`; and
- `C* = { c in C1 union C2 | epoch(c) >= F*(relation(c)) }`.

With every floor at `-1`, this reduces to ordinary cell-set union. The maximum floor dominates obsolete cells, so a cell below an acknowledged floor cannot be resurrected by joining a stale replica.

Epoch `e` is sealed for relation `r` exactly when `C` contains one cell for every source in `S` at `(r,e)`. Let `latest_C(r)` be the greatest sealed retained epoch for `r`, when one exists. With threshold `q`, the relation decision is:

- `different` if any cell at `latest_C(r)` votes `different`;
- otherwise `same` if at least `q` cells vote `same`;
- otherwise `unknown`.

When no epoch is sealed, the decision is `unknown`, even if the latest unsealed prefix already contains `q` positive cells.

## 2. Deterministic negative-safe materialization

Construct a graph on `H`. First collect every relation decided `different`. Process relations decided `same` in lexicographic order. A relation may join two current components only when the union would contain no decided-different pair. Ties in the disjoint-set representation are broken by component size and then lexical root. The resulting partition and accepted/rejected edge sets are functions only of the selected floor-and-cell state, not of message order.

A later sealed epoch can replace the selected decision for a relation. Materialization is recomputed from evidence, so a later negative decision splits any prior component whose justification depended on now-invalid positive relations.

## 3. Assumptions and non-claims

A1. The handle set, source registry, and candidate relation universe are finite; one source registry is fixed for the reconciliation instance and all retained epochs.

A2. Sources do not equivocate for one relation, epoch, and source key.

A3. Every selected `different` cell is sound for the frozen observation and separability vocabulary.

A4. Fix one real-service equivalence relation across the retained evidence under analysis; this is not instantaneous truth during arbitrary service migration. Threshold separability holds: for every candidate relation whose endpoints are different real services, either fewer than `q` sources vote `same` at the selected sealed epoch or at least one source votes `different`.

A5. For convergence, every retained cell and every acknowledged floor is eventually delivered to every non-failed replica.

A6. A floor advances only after every active replica acknowledges the complete sealed vector at that floor. The floor is persisted and merged by maximum. Local compaction validates every relation before mutation, retains the floor and every newer epoch, and succeeds only when the number of newer epochs is at most the configured pending allowance `p`; otherwise it refuses without mutation.

The model does not cover Byzantine content, source collusion, a changing source registry across retained epochs, unbounded offline intervals with no acknowledgement, legal ownership, operator attribution, or completeness for arbitrary Web identity signals.

## 4. Theorem ladder

### Theorem 1: floor-aware state convergence

The state join on `(H,F,C)` is commutative, associative, and idempotent. Therefore replicas that eventually receive the same retained cells and acknowledged floors converge to the same evidence state, independent of delay, reordering, or duplication.

**Argument.** Handle union and pointwise maximum are each commutative, associative, and idempotent. For any finite family of states, the joined floor is the pointwise maximum over all input floors, and the joined cells are exactly the union of all input cells filtered once by that final maximum. This characterization is independent of grouping or order. A cell filtered by an intermediate floor can never become eligible after another join because floors only increase. Loss can delay convergence, but anti-entropy that delivers each retained cell and floor establishes equal states.

### Theorem 2: view convergence

Replicas with equal floor-and-cell states, source registries, thresholds, and handle sets materialize identical decisions, accepted edges, rejected edges, and partitions.

**Argument.** Sealing, greatest-epoch selection, vote aggregation, edge ordering, safety checks, and tie breaking are deterministic functions of the common inputs.

### Theorem 3: explicit-negative consistency

No materialized component contains both endpoints of a relation selected as `different`.

**Argument.** Initially every handle is alone. A union is executed only if no selected negative relation crosses the two candidate components. By induction over the sorted positive relations, the invariant holds after every union.

### Theorem 4: no unsupported merge under threshold separability

Under A3 and A4, every pair of handles in one materialized component belongs to the same real service.

**Argument.** A selected positive relation has at least `q` positive cells and no negative cell. A4 therefore excludes a cross-service selected positive relation. Each accepted edge connects handles from one service. A component is connected by accepted edges, so transitivity keeps every path and component inside one real service. The negative-safe check is not needed for this implication but protects the view when positive evidence and sound negative evidence form an inconsistent cycle.

### Theorem 5: deterministic split handling

If a later selected sealed epoch changes a previously accepted relation to `different`, every replica that has the same later evidence removes that relation from the positive set and materializes a partition satisfying Theorem 3. If the negative relation separates a formerly joined component, the split is identical at every replica.

**Argument.** Identity partitions are derived rather than replicated. The later epoch is selected deterministically, the negative relation is installed before positive processing, and Theorem 2 gives identical recomputation.

### Theorem 6: acknowledged-floor compaction preserves the current view

For a relation with acknowledged sealed floor `f`, deleting only epochs below `f` while retaining the floor and every newer epoch preserves the selected decision and therefore the materialized partition.

**Argument.** Before compaction, the greatest sealed retained epoch is at least `f`. Every epoch at or above `f` is retained, so the same greatest sealed epoch and all of its source cells remain. Removing strictly older epochs cannot create a newer sealed epoch or change the selected vector. Applying this relation by relation preserves the decision map and deterministic partition.

### Theorem 7: successful compaction is bounded, atomic, and stale-safe

After a successful compaction with pending allowance `p`, each relation with an acknowledged floor retains at most `|S|(1+p)` cells. A failed validation changes neither cells nor floors, and a later floor-aware join cannot restore a below-floor cell.

**Argument.** A successful call retains one sealed floor epoch and all newer epochs, whose count was checked to be at most `p`. A2 bounds each epoch by `|S|` cells. The implementation computes and validates the entire target state before committing it. Subsequent joins take the maximum floor and filter cells below it, so stale history remains dominated. No bound is claimed for relations without a floor or when pending growth causes compaction to refuse.

### Theorem 8: `same` and `different` certificates are sound

A checked `same` certificate supplies an accepted-edge path between the query handles and the selected positive cells for each path edge. A checked `different` certificate supplies a selected negative cell crossing the two reconstructed query components.

**Argument.** The independent checker validates the serialized registry, handles, floors, cell keys, votes, and threshold; reconstructs sealing, decisions, and the negative-safe partition without importing the reconciliation implementation; and then checks the path or separator against that reconstruction.

### Theorem 9: globally negative-compatible ambiguity optimality

For a relation currently decided `unknown`, let `P`, `M`, `D`, and `U` be the source positions that are respectively `same`, missing, `different`, and `unknown` in its selected/latest vector. Define

`g(r) = |M| + |D| + max(0, q - |P| - |M| - |D|)`.

This is the minimum source-position intervention count for a future sealed vector with no `different` position and at least `q` `same` positions: every missing position must be supplied, every different position must change, and any remaining positive deficit is met by changing unknown positions. For a wholly unobserved relation, all `|S|` positions are missing.

Contract the current materialized components and let `N` be the selected-negative component pairs. Add every currently unknown relation with cost `g(r)` and an implicit direct query edge of cost `|S|`. An unobserved direct edge is a hypothetical addition to `R`; its plan requires the measurement controller to admit that relation and supply a future complete vector. It is not a guarantee for an immutable candidate graph that excludes the query relation. A simple component path is admissible only when no pair of components anywhere on the path belongs to `N`; checking only adjacent steps is insufficient because the completed path merges all selected components. The certificate minimizes lexicographically (i) summed intervention cost, (ii) edge count, and then (iii) deterministic relation/component order.

**Argument.** The per-relation formula is exact and relation-source slots on distinct path edges are disjoint, so path costs add. The direct fallback supplies a finite incumbent. Every unknown edge has positive cost, hence no path beating or tying that incumbent has more than `|S|` edges. The producer enumerates every simple prefix within that bound and rejects a new component whenever it has a selected negative relation to any component already on the path. Therefore every feasible path that can improve the incumbent is examined, every returned path is globally negative-compatible for the frozen selected-negative set, and the lexicographic optimum is exact. The independent checker reconstructs components, selected negatives, costs, fallback, and the bounded stack search without importing the producer.

The theorem is intentionally scoped. It does not validate source predicates, prove that the real-service partition is unique, or permit mutation of immutable negative evidence in the current epoch; a changed vote belongs to a future epoch. It proves only that the listed future relation vectors can connect the query endpoints without placing a selected negative pair inside the resulting path component under the supplied frozen state.

## 5. Merge-only partition-state limitation

Order partitions by coarsening and suppose a replicated state's only semantic payload is the current partition, with a join that can only move upward in that order. Once `a` and `b` are in one block, every later join keeps them together; the state cannot represent the refinement `{a},{b}` required by a later selected negative epoch. A versioned partition register can overwrite the snapshot using an external total order, but then its split choice comes from that arbitration and it does not retain the evidence basis needed to reconcile concurrent observations or explain the decision. Thus source-indexed provenance, or equivalent auxiliary state, is necessary for the deterministic evidence-driven and reviewable split semantics claimed here. This is not an impossibility result for every partition representation.

## 6. Executable obligations

- `test_join_commutative_associative_idempotent` checks the ordinary no-floor join laws.
- `test_floor_aware_join_commutative_associative_idempotent` checks the compacted-state join laws and below-floor filtering.
- `test_fault_emulator_converges` and `faults.csv` exercise Theorems 1 and 2 under delay, loss, duplication, and a temporary partition.
- `test_negative_safe_partition` exercises Theorem 3; `correctness.csv` checks Theorem 4's generated separability instances and quantifies the conservative false-split cost.
- `test_negative_veto_and_split` and all 720 exhaustive small-history schedules exercise Theorem 5.
- The compaction tests cover view preservation, no-floor retention, atomic refusal for excess pending epochs or floor regression, unsealed-floor rejection, preservation of a newer pending epoch, stale-history suppression, and state export/import. `compaction.csv` supplies the three measured depth cases.
- The certificate tests cover every certificate kind in normal and optimized interpreter modes, closure-aware ambiguity gaps, unobserved fallback cost, unregistered handles, semantic tampering, false ambiguous labels under a negative separator, and malformed duplicate/equivocating state keys. `witnesses.csv` contains 207 independently checked queries.
- The retained 68-test family covers the original model and schedule checks, strict-schema/common-floor boundary regressions, globally compatible ambiguity regressions, public extraction/predicate checks, persistence/restart accounting, atomic replace and directory-sync failure boundaries, concurrent-ingest serialization, read-only acknowledgement, stale-temporary cleanup, cross-process hash-seed determinism, bounded transport encoding, and 11 workload-bound, compaction-domain, executed-sealing-counter, and timing-reaggregation regressions. Six additional pure tests in `tests/test_checker_context.py` use an independent raw-cell/block/permutation oracle, full/key certificates, partial vectors, ties, non-adjacent negatives and mutation/call-count checks for invocation-local checker reconstruction reuse. Discovery therefore contains 74 tests; the retained 68-test Linux receipt is not evidence of a new full run. The exact oracles, public pair evaluation, event-loop campaigns, and independent-process recovery campaign are additional executable evidence.


## 7. Concrete common-floor obstruction

A report of the greatest sealed epoch is not a prefix certificate. Let one
replica retain only a sealed epoch 2 and another only a sealed epoch 3 for the
same relation. The minimum latest report is 2, but the second replica cannot
acknowledge epoch 2. More generally, histories {1,3} and {1,2,4} have greatest
common sealed epoch 1, not the minimum latest report 3. Floor selection must
intersect the actual retained sealed epoch sets, then choose the greatest
member per relation. An empty intersection blocks compaction. Non-equivocation
ensures that nodes acknowledging the same key acknowledge identical cells;
the TCP coordinator nevertheless carries and compares complete vectors.

This correction concerns floor proposal, not a new failure of the floor-aware
join algebra. The compactor already rejected an absent or unsealed floor.

## 8. Admissible peer deltas and convergence

A peer inventory lists retained cell keys, floors, source registry and threshold.
A receiver requests keys not present locally. The responding peer constructs a
fresh snapshot delta containing requested retained cells, its full handle set,
all its floors, and every source cell at every floor. Thus the delta is an
admissible state: no retained cell predates a floor, and every nonnegative floor
has its sealed vector. It is below the responding state in the join order.
Merging such a delta is therefore an ordinary admissible join, not a second
conflict-resolution rule.

**Proposition (fair peer repair).** After evidence and floors stop changing,
assume a finite fixed membership, compatible sources, correct peers, and fair
repeated successful pulls on a strongly connected directed peer graph. Every
surviving cell, handle and maximum floor reaches every node, and all nodes
converge to the join of their states.

**Proof.** A maximum floor is sent with every delta from a node retaining it,
including an empty cell-key difference. Hence it propagates along each finite
peer path. Its complete floor vector travels with it. A cell at or above the
final maximum floor is never removed. If absent at a neighbor, the next
successful inventory/fetch pair after quiescence requests and returns it.
Induction on finite path length propagates each surviving cell. Handles travel
with deltas. There are finitely many surviving objects, so a finite successful
prefix exists after which all are present everywhere. Theorem 1 then gives
equal states, and deterministic materialization gives equal views. An inventory
made obsolete by intervening compaction is safe: the later fetch includes the
new floor vector; fair later pulls supply any newly added surviving keys.
This is eventual convergence after quiescence, not a time bound during an
unbounded partition or unlimited input stream.

The service acknowledges state mutation only after validating the replacement,
fsyncing a temporary snapshot, atomically replacing the saved snapshot, and
fsyncing the parent directory. The event-loop campaign validates an orderly
endpoint restart. A separate four-process campaign kills a service only after
an acknowledged commit, reloads its snapshot, and verifies the recovered state
and certificate before and after healing. Neither campaign injects a crash
inside a write, torn-sector behavior, filesystem failure, or power loss.
Membership and acknowledgements are trusted; this loopback protocol does not
authenticate Byzantine clients or implement crash consensus.

## 9. Adjacency-only ambiguity is unsound, and the repaired rule rejects it

Take singleton handles a,b,c,d and five sources with q=2. The unknown relations ab, bc and cd each have one positive and four unknown cells, so each has local gap one. Relation bd is negative. There is no direct negative between a and d. The former adjacency-only diagnostic selected a-b-c-d at cost three, cheaper than the unobserved ad fallback of cost five, even though merging the entire path violates bd.

The repaired rule checks every new component against every component already selected. It rejects a-b-c-d and returns the safe direct fallback at cost five. The executable regression checks the producer result and the independent verifier. This counterexample remains in the artifact as evidence for why the global constraint is necessary; it is no longer an unimplemented-obligation marker.

## 10. Exact bounded checks

The supplemental graph oracle tests 729 three-valued label assignments over all
six pairs of four handles and all six queries per graph (4,374 certificates).
It represents components as explicit sets and enumerates simple quotient paths,
not union-find or the producer search. Of these queries, 1,402 are same, 2,329
different and 643 ambiguous. A separate source-slot oracle compares the
intervention formula against every complete three-source vector for 64 partial
vectors at each of three thresholds (192 cases). Floor algebra checks 21
compatible admissible states over one pair, two sources and two epochs: 441
pairs and 9,261 triples.

A second diagnostic oracle enumerates 4,096 four-component graphs and 18,432
query cases. The former adjacency-only objective selects a path containing a
non-adjacent selected-negative pair in 144 cases. The globally compatible objective excludes
all 144 such paths: its optimum costs one additional source slot in
108 cases and two in 36, with maximum increase two. These finite families do not
prove behavior on larger graphs, but they independently expose the old rule's
failure and compare the two abstract objectives; they do not call the production
search or checker. Separate state-coupled regressions exercise those implementations.
The floor-hole examples and strict
state-boundary tests remain explicit regressions rather than being hidden in
aggregate counts.


## 11. An identifiability boundary

Fix two handles, one candidate relation, a nonempty fixed source registry and any admissible positive threshold. Every source supplies UNKNOWN in the same epoch; retain no negative or positive cells elsewhere. Consider two possible real-service equivalence relations: one merges both handles, and one separates them. A1--A6 can hold in both worlds: there is no equivocation, no negative claim to falsify, no cross-service threshold-positive relation, and every cell is delivered. Each world gives the reconciliation algorithm exactly the same input. A deterministic algorithm required to output a unique true partition must give the same answer in both worlds and is wrong in one. The same construction prevents a randomized algorithm from being always correct in both. This elementary indistinguishability argument is a boundary, not a new naming impossibility theorem or a claim that identity is never learnable. Additional observations or stronger assumptions can exclude one world. It explains why convergence of the all-unknown HTTP adapter does not validate identity accuracy.


## 12. Public target-equivalence predicate

The public benchmark has a deliberately narrower label than real-service identity. Each source fixture names one normalized input target and records observations from a probe network and a control network. Two observations are labelled `same` exactly when their normalized target labels are equal; all other pairs are labelled `different`. This label says nothing about common ownership, common operator, or whether two distinct URLs should be one service.

The evaluated predicate does not inspect the target label. It selects `same`
only when successful endpoint sets overlap **and** both observations have valid,
equal HTTP status with either an equal nonempty title or at least 0.5 Jaccard
similarity between retained header-name sets. It selects `different` only when
both observations have successful nonempty disjoint endpoint sets, valid HTTP
status, and at least two of: different status classes, different nonempty titles,
or header-name Jaccard similarity at most the frozen threshold. Every other pair
is `unknown`. Retained fields are side-specific factual values from the source
fixtures: missing probe titles are not synthesized from match flags, and DNS or
successful HTTP records are not converted into an unreported TCP success.

This rule is not proved sound for the Web. A selection manifest records 16
inspected upstream candidates, 12 retained unique measurements, and four
exclusions. The 24 observations form 276 pairs over 11 normalized input targets.
At the selected threshold the rule makes 20 assertions (3 `same`, 17
`different`) without contradicting exact target labels and abstains on 256. The
closed-world endpoint control asserts all 276 pairs and makes nine errors: two
false merges and seven false splits. Threshold sensitivity yields 5.1--8.7%
coverage, target-block leave-one-out yields 4.3--9.5%, and case-block
leave-one-out yields 4.3--8.7%, with zero conservative asserted errors
throughout. Independent-pair Wilson intervals are not reported: shared observations and nonprobability fixture selection do not supply an independent binomial sample. Leave-group-out ranges are descriptive sensitivity checks, not unseen holdout or Web-population accuracy estimates.

## 13. Equal-work architecture comparison

The equal-work campaign compares three deployment architectures while holding the reconciliation semantics fixed:

1. **Peer evidence.** Five endpoints each durably ingest one source batch, answer from local retained evidence, and reconcile by inventories and admissible deltas.
2. **Central recomputation.** One durable authority runs the same evidence materializer and certificate generator. Clients durably stage every source batch before delivery, including immediately reachable batches. Disconnected batches remain spooled until healing.
3. **Coordinated quorum.** Three durable authorities, placed at clients 0, 2, and 4, run the same state machine. A client write or query is available only when its partition side contains at least two authorities. Clients durably stage every batch before checking reachability; unaccepted batches remain spooled until healing, after which authority states reconcile.

All three receive the same five source batches, use the same JSON/TCP framing, fsync temporary contents, atomically replace snapshots, fsync the parent directory before server acknowledgement, answer the same query with the same certificate schema, and reload from saved state after an orderly restart. The two layouts are `{0,1}/{2,3,4}` and `{0,2,4}/{1,3}`. This makes the central authority reachable from 40% or 60% of clients; the three-authority quorum is reachable from 60% in either layout; peer evidence is locally reachable from all clients.

Each central and quorum case includes 263,445 staging bytes and ten staging fsyncs; peer clients ingest directly with no client spool. Persisted bytes sum snapshot and client-staging writes. The resource comparison measures complete request workflows, including their different staging policies. In every available partition-time query, incomplete source closure yields `ambiguous`, never stale `same`. After spooled writes and peer evidence arrive, all architectures reconstruct the same complete state and checked `same` answer for the representative query. The measured wire, cumulative snapshot/spool bytes, final durable footprint, request latency, certificate time, and elapsed time are bounded one-machine observations. A separate campaign checks post-ack service-process exits, but neither campaign establishes crash consensus, a mid-write or power-loss guarantee, independent-machine recovery, or wide-area performance.


## 14. Component-level veto index

For each live component A, store B(A), the union of selected-negative neighbors
of handles in A. Entries are original handle identifiers, not component roots.
A proposed union of disjoint components A and D is admissible exactly when
B(A) intersects D trivially (equivalently, B(D) intersects A trivially).
Initially the invariant holds on singleton components. Upon an admitted union,
set B(A union D) = B(A) union B(D), using the same union-by-size parent as the
reference implementation. The invariant is preserved, so both guards reject
exactly the same candidate edge. Induction over the identical sorted positive
edges gives the same components, accepted edges, and conflict records.

Across live components there are at most twice as many index entries as selected
negative edges: charge each stored neighbor to one original incident edge.
With union by component size, each moved endpoint belongs to a component that
at least doubles. Index-merge insertion attempts can therefore be charged to
O(|N| log |H|) moved negative incidences. Intersection costs still depend on
operand sizes; this is neither a constant-time guard nor a universal speedup.

The paired experiment preserves the member-scanning implementation and times
complete calls, including index construction and decision selection. It uses
three structural families, four sizes, five seeds and five alternating-order
paired repetitions (60 cases and 300 pairs). All views are checked, not merely
component counts. No speed threshold is a test pass condition. Dense-cut and
low-conflict regressions remain in the retained outcomes.

## 15. Topology-dependent responsiveness

Let P be a partition of n query sites, c the central authority site, and Q a
three-site authority set. Central responses are possible at |P(c)| sites.
A quorum response is possible exactly in blocks intersecting Q in at least two
sites. Divide those reachable-site counts by n to obtain response fractions.
A peer endpoint can answer locally, but that answer can be ambiguous. Thus
response fraction must not be equated with decisive, fresh authorization.

Enumerating every nonconnected five-site partition (51), five central placements
and ten quorum sets yields 2,550 cases. Central exceeds quorum in 940, quorum
exceeds central in 510, and 1,100 tie. The uniform-case means are 107/255 and
92/255. For two-block partitions they are instead 43/75 and 47/75. The ranking
reversal is an exact finite sensitivity result, not a failure-probability model.

## 16. MWS specialization and controlled veto obligations

The relevant antecedent is Wolf et al., *The Mutex Watershed: Efficient,
Parameter-Free Image Partitioning*, ECCV 2018, Algorithm 2 and Sections
3.1/3.3/3.4, doi:10.1007/978-3-030-01225-0_34. This section derives the
specialization; it does not claim the negative-component constraint as new.

For a fixed selected decision graph, assign every negative strength 2 and every
positive strength 1, with lexical positive ties. MWS activates all negatives
before the first union. Its incidence set M(A) contains IDs of active negative
edges touching component A. For disjoint components A,B,
M(A) intersects M(B) iff an active negative has one endpoint in each. This is
also equivalent to the handle-neighbor guard B(A) intersecting the members of
B. Initially both representations encode exactly the selected negatives. On an
admitted union, both representations inherit their respective sets by union;
no active negative is internalized. Induction over the identical ordered
positives therefore gives equal components and rejections. MWS's connected
test skips redundant positives; CIE records them as accepted support. Adding
only those skipped internal positives to the comparator's support list restores
the complete PartitionView without altering any component or union.

The equivalence is not universal across strengths. With attractive ab of
strength 3, attractive bc of strength 2, and repulsive ac of strength 1,
Algorithm 2 first merges all three. It ignores ac because its endpoints are
already connected. Negative-first selection instead activates ac, accepts ab
and rejects bc. Neither conclusion contradicts MWS: the priorities differ.

Relation-level negative dominance and the component guard are different
obligations. Masking negative votes during aggregation changes relation labels
and removes selected negatives. Disabling only the component guard preserves
those labels and records while allowing unsafe unions. The former operation
corresponds to the retained `no negative veto` baseline; it cannot measure an
isolated component-guard benefit. With relation dominance disabled, there are
no selected negatives left, so the component factor is inert.

In the original generated q=2 family, every selected positive stays within a
truth class and every selected negative crosses classes. Induction makes every
positive component a subset of one class; no selected negative can cross two
components joined by a selected positive. Hence the component guard never
rejects, and removing it alone gives the same partition. Executing the same 15
600-service parameter cases confirms zero guard rejections and zero changed
partitions. All 60 factorial rows match the corresponding retained pairwise
metrics exactly; this is not new accuracy on an external dataset.

The explicit sealed triangle ab,bc positive and ac negative is admissible under
A1/A2. It forces a component-level rejection of bc after ab. Removing only
that guard merges all three and violates ac while keeping decisions identical.
If the negative is sound with truth classes {a,b},{c}, then bc violates A4;
the example establishes reachability of the negative-consistency obligation,
not a failure of the conditional non-conflation theorem. Across all 729
four-handle ternary graphs, guard removal changes 259 partitions and creates
354 internalized selected-negative edge occurrences.

Eight pure tests in `tests/test_mutex_baseline.py` extend the previously
described 74-test discovery to 82, without extending the retained 68-test Linux
receipt to a full new run. A separate explicit-block active-negative oracle
checks 125 three-node weighted graphs and 200 seeded eight-node graphs.
Additional checks cover 80 multi-epoch/floor states, closure, redundant support,
signed parallel edges and invalid strengths. The 60-case, 900-call passive
stress campaign compares complete views and records its own environment and
raw calls; `scripts/verify_mutex.py` reaggregates all medians and per-seed ratios.
Neither finite checks nor Python timing comparisons establish global novelty,
production deployment or an advantage over the authors' optimized image code.

## 17. Executing a compatible diagnostic without changing other decisions

Let P be the current canonical partition, N the selected negative set, and T the
set of blocks on a simple globally compatible diagnostic path. Fix every old
selected relation decision except the listed UNKNOWN relations, which become
SAME in complete future vectors. Each new epoch must exceed every retained
epoch of that relation, not just the selected sealed epoch. An unobserved direct
fallback requires candidate admission. Assume enough capacity to admit these
cells, no concurrent decision changes, and that all source positions repeat or
change exactly as specified. These are hypothetical interventions; source truth
and the willingness or ability of actual sources to make them are not proved.

**Proposition.** Recomputing the same negative-first lexical materializer
connects the query, preserves every old component and accepted positive edge,
and preserves explicit-negative consistency. This does not optimize global
identity accuracy, minimize arbitrary policies, or provide fresh information
during a partition.

**Proof.** Let K consist of the union of T and every other P block separately.
Every K block is N-free: P is negative-safe, and global compatibility excludes
all negative pairs between T blocks. Consider the lexical old positive sequence
with the new path edges interleaved. Maintain two prefix invariants: the new
partition refines K and coarsens the old partition after the same old-edge
prefix. A new edge stays inside one K block, so it can be admitted safely. An
old accepted edge stays inside its original P block, hence inside K, so it
remains accepted. An old rejected edge has a crossing negative witness in the
old prefix; prefix coarsening preserves that witness. Its endpoints cannot
become internally connected because that would internalize the witness in a
negative-free K block. It therefore stays rejected. Both invariants hold for
singletons and after each step. In the final view every old block is preserved,
all new path edges are accepted, and their connected chain joins the query.
The ordinary negative guard preserves N throughout.

The bounded execution experiment uses all 729 four-handle ternary graphs,
three sources and q=2. It checks all 4,374 classifications and actually creates
fresh complete vectors for each of the 643 ambiguity plans. Raw before/plan/
after records preserve the input, supplied or changed positions and observed
partition. This closes execution for this finite family rather than inferring
execution from an optimum value. The prefix argument applies to the stated
frozen-decision extension, not arbitrary future evidence streams.

A second finite family admits absent relations as a fourth pair state, uses
five sources and q=2, and enumerates all 4,096 graphs and 24,576 queries. It
executes 7,862 plans (7,418 one-edge, 432 two-edge and 12 three-edge plans),
adding 41,590 fresh cells with zero contract mismatches. Its raw plan records
are in execution-002; they are not the earlier abstract 4,096 quotient oracle.
Three named tests additionally check a three-edge plan, a selected epoch 0
with an open epoch 9 requiring epoch 10, and old support/floor preservation.

## 18. Closest-comparator cost and workflow boundary

MWS Section 3.4 merges the smaller active-mutex-ID table into the larger table.
The old local comparator selected a union-find parent by component vertex count
and always updated its table from the other root. Vertex count does not order
mutex-table sizes. The owned 25-node, 24-edge fixture first builds an eight-node
component with no incident negatives, then joins a singleton with 16 incident
negatives. The old code attempts 16 input insertions into an empty table. The
corrected comparator swaps table ownership independently of the canonical
union-find root and attempts zero input insertions in this final union. Table
union and therefore the entire view are unchanged. This is a faithful baseline
repair, not a new algorithm. Historical timing rows use the old cost policy and
are not evidence for the corrected comparator's costs.

Wolf et al.'s extended author paper, arXiv:1904.12654v2, Algorithm 2 already
offers connect_all=True to retain redundant internal positives. Its Section 4
derives a dominant-power multicut objective under distinct priorities. Neither
support-edge retention nor the component veto is a contribution distinction.
The plain replicated evidence log, complete-vector selection and read-time MWS
combination is an ordinary same-semantic alternative; the present artifact's
particular source-slot diagnosis and its execution premises are the specific
object of study, not an established novelty claim.

The native loopback comparison uses exactly the same source batches, three
local owners, partial-query schedule, fair pulls, later negative epoch, floor
reports/acknowledgements/compaction and independent certificate checks for
scanning, indexed and corrected MWS read views. Every arm is explicitly
volatile. The unchanged persistent Service is separately probed on Windows:
content fsync and replace execute, then parent-directory fsync raises
PermissionError, so no acknowledgement is issued. The volatile experiment is
not a repair or validation of that durable contract. Its costs include actual
TCP frames, complete updates and queries, checker time and floor protocol;
snapshot bytes, fsyncs and durable commits are zero by definition. Durable
same-semantic workflow cost, power-loss behavior and multi-machine timing
remain unmeasured in this cohort. SQLite is only inventoried as a runtime
version; it is not a persistence engine in this service.
