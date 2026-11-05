# Release-wide edge curation: implementation plan

This plan implements the [architecture and evidence baseline](edge-curation-architecture-20261103.md).
Tracking: [CLAW #756](https://github.com/CultureBotAI/culturebotai-claw/issues/756)
and [KG-Microbe #1717](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1717).
The architecture report records the earlier planning state; the staged work below
is the subsequent implementation. No milestone is marked complete here. Final
candidate checks, independent PR review, issue disposition and status updates
remain pending. **Merges remain the user's decision.**

The historical engineering input is `data/merged/20260929`: 17,637,435 edge
occurrences under source manifest SHA-256
`f585e55a616d3771f382c91c78713cb8d74812c7ba177576090ccd5f9e6654b2`.
Preserve its recorded dirty producer identity. Choose an immutable production
build separately; do not rename this snapshot “latest.” Reviewed Mech overlap
with the full edge population has not been measured.

## 1. Shared foundation — staged, in progress

**Owners:** KG-Microbe producer and CLAW contract/ledger maintainers. Work is
isolated on `feat/edge-curation-snapshot-20261103` and
`feat/edge-curation-ledger-20261103`, respectively.

| Staged deliverable | Maintained write paths | Acceptance before closing the milestone |
|---|---|---|
| Standard-library snapshot exporter | KG: `kg_microbe/edge_snapshot.py`, `tests/resources/edge_snapshot/`, `tests/test_edge_snapshot.py`, `docs/EDGE_SNAPSHOT_EXPORT.md` | Verify every manifest member, including unselected tails; preserve exact row text, extensions and duplicate occurrences; publish only complete, bounded, hash-verified shards into a new directory. |
| Versioned identities and bounded review bundles | CLAW: `src/kg_microbe_curation/{identity,contract}.py`, `schema/bundle.json`, contract tests and package metadata | Cross-producer occurrence vectors agree. Exact membership, context fingerprints, current review/input bindings and packaged schema validate. Native observation identity remains distinct from occurrence identity. |
| External SQLite ledger and CLI | CLAW: `src/kg_microbe_curation/{ledger,__main__}.py`, ledger/CLI tests | Import persists one current accounting row per selected occurrence. Lookup works; transactional counters make status independent of population size. Explicit audit reconciles membership and counters. Apply rejects stale inputs/revisions and rolls back atomically; prior bundles remain accessible. |
| Offline persisted canaries | CLAW: retained `scripts/adhoc/` launchers, tests and guides; receipts under external/local artifact storage | Reproduce the actual 1,000-row export/import/lookup/apply path and pinned MIM import; inspect saved artifacts, hashes, counters and negative controls using the final candidate. |

SQLite is the **initial local backend**, not the final partitioned Parquet
architecture. Raw snapshots, shards, databases and full receipts stay outside
Git; Git retains code, small fixtures, contracts and concise run evidence.

The recorded 1,000-row canary retains all selected rows as withheld, exercises a
deferred decision and stale-revision rejection, and reports zero scientific
approvals. The separate MIM canary uses pinned commit
`1848b0fe521bc2462f165912fcf92d09ad9a8cec`: it verifies the complete native
supported/withheld partition and tests one reusable identity mapping plus two
withholds. Payload, evidence-dependency and biological-scope changes refuse reuse.
It does not establish actual KG edge membership or automatically convert native
MIM decisions to `RecordReview`. No EdgeMech repository, browser or live
scientific-review worker is part of this milestone.

Finish with affected/downstream tests, packaging checks, independent review and
filed findings. Run final repository gates on the concrete candidate: KG uses
its single-full-suite runner; do not add a second full pytest run. Re-run a
canary when changes affect its recorded path or interpretation. Attach final
evidence to the tracking PRs before updating this milestone's state.

## 2. Review and pin contracts; scaffold EdgeMech — planned

**Owners:** CLAW contract maintainer and EdgeMech integration maintainer.
**Dependency:** milestone 1 contract review; other teams may prepare fixtures in
parallel, but must not independently redefine identities or review semantics.

Review overlap with [CLAW PR #448](https://github.com/CultureBotAI/culturebotai-claw/pull/448)
(claim support versus study type), [CLAW PR #543](https://github.com/CultureBotAI/culturebotai-claw/pull/543)
(causal-graph KGX transport, stacked on #537), and
[KG PR #1585](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1585)
(context-dependent RDF identities). Refresh their states and pin reviewed code;
do not duplicate their contracts or treat open PRs as published capabilities.
Transport validation, quote matching and scientific approval remain separate.

After contract review, scaffold the proposed EdgeMech repository with
`src/edgemech/`, `conf/routing.yaml`, small `tests/resources/`, documentation and
pinned CLAW dependencies. Register its actual capabilities in CLAW's
`src/kg_microbe_fleet/fleet.yaml`; retain canonical schemas in CLAW. Define owner
routing, artifact manifests, assurance levels and invalidation/migration rules.
Accept when a clean installation can read the milestone 1 artifacts, locate any
selected occurrence and explain its state without inventing reviewed coverage.

## 3. Storage and native adapters — planned, parallel after contract pinning

| Lane / owner | Deliverables and proposed write paths | Acceptance |
|---|---|---|
| Durable storage / EdgeMech, shared interfaces in CLAW | EdgeMech `src/edgemech/storage/`; versioned external `releases/<manifest>/generations/<id>/` artifacts containing Parquet occurrence, observation, claim, evidence, membership and decision/history tables; DuckDB query layer | SQLite-to-artifact migration preserves exact IDs, memberships, current decisions and history. Hash-verified manifest publication is atomic. Benchmark partition size, reconciliation, lookup, storage and memory on documented inputs before choosing production layout. |
| Trait / TraitMech | Native `src/traitmech/export/` adapter and conformance fixtures; scientific corrections remain in maintained `data/traits/` owners | Export scoped reviewed assertions for prioritized BacDive/MetaTraits-compatible cases. Preserve strain, conditions, measurement, units, polarity and evidence. A generic trait mechanism does not approve an organism-level observation. |
| Habitat / HabitatMech | Native `src/habitatmech/export/` adapter and fixtures; maintained corrections under `data/habitats/` or their source/overlay owners | Preserve GOLD/BacDive/PREGO attestations and lineage. Isolation, observed association, characteristic habitat and causal mechanism remain distinguishable; copied upstream evidence is not independent corroboration. |
| Ingredient reuse / MediaIngredientMech and KG consumer | Extend native `src/mediaingredientmech/export/` contracts and KG consumer conformance fixtures, reusing the existing reviewed partition | Exact predicate, substance/form scope, source position, evidence and owner hashes survive import. Produce an explicit, reviewed adapter to canonical review packets; endpoint matches never approve organism-growth claims. |
| Taxonomic context / TaxonMech and KG | Versioned crosswalk/scope policy and adapter fixtures in their maintained mapping/export paths | Preserve strain/species/rank and source versions; broad/close mappings cannot become exact identity. Coordinate with the three scientific adapters rather than block unrelated cohorts. |

Give each native schema/exporter one writer. Storage/query work and separate
Mech adapters may proceed concurrently; serialize shared CLAW contract changes
and roll out consumer pins only after their canonical change is reviewed.
Remaining specialist routes follow the architecture's ownership table after
their actual native export eligibility is checked.

## 4. Eligible-overlap inventory and bounded browser — planned

**Owners:** EdgeMech integration/analysis maintainer, native adapter owners and
browser maintainer. **Dependencies:** pinned adapters; verified query artifacts
for full-population joins. A small conformance join can precede the full run.

Implement joins under `src/edgemech/` with retained profiling scripts in
`scripts/adhoc/`; keep bulk eligibility tables outside Git. Report exact eligible
matches, incompatible scope, ambiguous mappings, unavailable evidence/exports,
shared evidence ancestry and unmatched occurrences separately. Include all
occurrences and counts of distinct observations, claims and experiments.
Acceptance is complete membership reconciliation with reproducible hashes and
explicit assurance levels, not a target reuse percentage.

Build a small dashboard and generic detail viewer under EdgeMech's maintained
site generator/templates, backed by bounded search/detail shards. Reuse fleet
browser and payload-budget patterns. Accept when users can retrieve an edge by
release/ID, inspect the actual decision/evidence/owner and download the bulk
artifact. Enforce measured site, shard and request budgets; no per-edge HTML or
YAML corpus in Git. UI work may run alongside adapters once interfaces are pinned.

## 5. Independent review-worker canary, then stratified pilot — planned

**Owners:** one native Mech curator, a separate reviewer and the CLAW execution
maintainer. **Dependencies:** eligible scope, evidence packet and persistence
contracts. Use the supported native execution path and its provider/budget
policy; a declared agent configuration is not an implemented worker.

First run **one real packet end to end** through the same launcher, environment,
provider, caches, output location and concurrency path intended for the batch.
Persist its native review, independent assessment, explicit membership,
supported/withheld export and candidate-consumer receipt. Check mismatch and
changed-evidence invalidation; verify nonempty persisted artifacts and counters.
Fix and repeat this canary before fanout. Existing offline canaries do not
substitute for this worker/evidence-review canary.

Then pilot **500–1,000 release rows grouped into coherent packets**, stratified
across traits, taxonomy, habitat, media and conflicting/negative evidence.
Oversample difficult cases for error discovery while reporting population
weights separately. Keep evaluation evidence provenance-disjoint. Measure
reviewer disagreement, false support, abstention, reuse, corrected-source impact,
elapsed work and cost per new packet. Agree expansion thresholds from these
observations; this sample is not a powered graph-wide accuracy estimate.

## 6. Production queues and candidate publication — planned

**Owners:** EdgeMech operations, specialist maintainers and KG-Microbe release
maintainer. **Dependencies:** accepted pilot and durable storage/recovery checks.

Add bounded leases, checkpoints, idempotent retry and evidence-dependency
invalidation in the maintained worker/queue paths. Select cohorts by downstream
use, defect impact and evidence availability; set concurrency and resource
budgets from measurements. Preserve explicit unresolved outcomes. Coordinate
item-level citations, aggregation and contradictions with existing KG issues
[#770](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/770),
[#794](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/794) and
[#737](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/737).

Generate an immutable curation overlay and separately named candidate graph.
Scientific corrections enter owning transforms/mappings and native Mech records;
the canonical merge transports finalized inputs. Acceptance requires complete
row/disposition reconciliation, reviewable semantic diffs, producer-to-archive
round-trip checks and reversible manifest-based publication. Carry decisions to
a later release only when their observation, scope and evidence bindings remain
valid.

KG's reproducible publication work in
[#887](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/887) is a separate
dependency for declaring a production release. It can progress in parallel with
the historical pilot. Release/publication and every PR merge remain explicit
user decisions; staged implementation and complete accounting alone confer no
scientific approval.
