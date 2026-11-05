# Plan for release-wide KG-Microbe edge curation

This is the historical architecture review. Subsequent implementation is tracked
in the [implementation plan](edge-curation-implementation-20261103.md).

Prepared 2026-11-03 Pacific / 2026-11-04 UTC. This is a local architecture review
and implementation plan, not a new scientific review of the graph. No curation
batch, repository creation, deployment, or remote session change was performed.

**Recommendation: one new federating Mech, provisionally `EdgeMech`, with
scientific curation delegated to the existing specialist Mechs.** Its job is to
account for every edge in a pinned KG-Microbe build, connect it to evidence and
review decisions, route unresolved work, and produce reproducible curation
overlays. Keep bulk graph data and the complete row ledger outside Git. Keep
reviewable policies, compact scientific review bundles, schemas, code, manifests,
and exception decisions in Git. Do not create one YAML file, test case, issue,
agent invocation, or HTML file per edge.

The first deliverable should be an evidence and coverage inventory plus one
complete source-to-Mech-to-KG curation round trip. It should establish how much
existing reviewed material actually applies before commissioning new literature
review at scale.

## Evidence baseline and scale

The requested intermediate snapshot is
`kg-microbe/data/merged/20260929`. A streaming scan verified its exact edge and
node hashes, row counts, and byte sizes against `manifest.json`; both TSVs had
zero row-width errors. This verifies file integrity and the inventory, not the
truth or freshness of their assertions.

| Measurement | Result |
|---|---:|
| Edges | 17,637,435 |
| Nodes | 3,354,500 |
| Edge TSV bytes | 2,787,420,483 |
| Node TSV bytes | 479,594,588 |
| Distinct raw predicate values | 114 |
| Distinct primary-knowledge-source field values | 31 |
| METPO-predicated edges | 9,167,205 (51.976%) |
| Nonempty `publications` | 4,381,907 (24.844%) |
| Nonempty `source_record` | 551,030 (3.124%) |
| Nonempty `source_assertion_id` | 39,879 (0.226%) |

Missing publication fields do not establish missing evidence: ontology releases,
database records, and source-specific columns can provide other provenance.
Conversely, a populated publication field does not establish that the cited work
supports this particular assertion. Existing `manual_agent` and
`manual_validation_of_automated_agent` values are upstream metadata, not evidence
that a Mech or a human has reviewed these released rows.

| Largest source labels | Rows | Share |
|---|---:|---:|
| BacDive | 4,518,786 | 25.620% |
| MetaTraits | 4,365,897 | 24.754% |
| GTDB–MetaTraits | 3,417,267 | 19.375% |
| GTDB | 1,471,034 | 8.340% |
| NCBITaxon | 925,267 | 5.246% |
| GOLD | 705,750 | 4.001% |

The first three source labels account for 69.749% of rows. This is a useful
engineering priority, not a reason to grant those sources blanket scientific
approval. `biolink:subclass_of` alone accounts for 3,409,292 edges, illustrating
why ontology/taxonomy validation and experimental-claim review need different
workflows. The snapshot also contains 706,765 `METPO:2000511` edges covered by
the existing obsolete-assay-predicate issue [KG-Microbe #909](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/909).
One modeling decision can therefore matter more than hundreds of thousands of
separate record edits.

The snapshot manifest identifies its producer as `1408e7099-dirty`, generated
2026-09-30T03:47:12Z. Preserve it as an explicitly identified historical pilot;
do not relabel it as a clean current build. As checked during this review,
[GitHub's latest published KG-Microbe release](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/tag/2025-03-07)
is still `2025-03-07`. The supported-release documentation still identifies
[publication issue #887](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/887)
as open. Before production curation, choose and pin the intended new build and
its actual admitted source receipts; “latest” must resolve to an immutable
manifest, not a moving directory or branch.

Code review used KG-Microbe published master
`ba19536867b1d1e93fe14745dac6b232bffcd4d3`. Fleet scope used published CLAW
`3022b8738dcc9e01c7464a8d5c95aa9be2eef141`, whose manifest hash is
`ffc1d462cdeac0f699fd24273ce66857856aa2f0ce07a25e93ec4a70e4c043fb`.
Its 14 Mechs define the scope; CLAW itself is the control plane. This was a
targeted capability and dependency review, not an exhaustive audit of every
fleet issue, record, or live website. Reviewed-claim overlap with this graph
has not yet been counted.

## Curation model and scientific boundaries

Separate six objects rather than treating an edge row as the whole scientific
record:

| Object | Identity and purpose |
|---|---|
| Release occurrence | Manifest hash, member, row position and complete row hash; accounts for every occurrence, including duplicates. |
| Source observation | Versioned source record/assertion and complete normalized payload; preserves relation, provider, methods, conditions, values, units, polarity and evidence. |
| Scoped claim | A scientific proposition that can group compatible observations without discarding their identity or disagreements. |
| Evidence item | Pinned source, passage/table/figure or database field, retrieval/version/license metadata, and the experiment or analysis it reports. |
| Review decision | Exact claim/observation scope, evidence hashes, reasoning, actor type, model/tool versions where applicable, review status and supersession history. |
| Coverage membership | Explicit, hash-bound list of release occurrences covered by a particular decision or validation policy. |

KG-Microbe already hashes the **entire normalized observation**, not merely
subject/predicate/object/relation, in
[`kgx_source.py`](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/ba19536867b1d1e93fe14745dac6b232bffcd4d3/kg_microbe/merge_utils/kgx_source.py).
Reuse that behavior. A separate occurrence identity remains necessary for exact
release accounting; a grouped claim must not collapse independent observations.
Bind observation and claim IDs to a named, versioned canonicalization contract
and pinned schema/prefix interpretation. Identical payload bytes interpreted
under different contexts must not silently acquire the same scientific identity.
Canonicalizer changes require explicit migration/alias mappings and review
invalidation rules; coordinate this with the context-dependent identity work in
PR #1585.

Every released edge receives exactly one current accounting disposition from a
mutually exclusive lifecycle such as unprocessed, pending review, admitted,
withheld or superseded. Retain multiple historical decisions and disagreements;
an explicit versioned current-state view supplies the unique counting row.
Validation outcome, review depth, review origin and conflict flags are separate
attributes. Thus an admitted row can be structurally validated and matched to a
Mech decision without being counted twice. Distinguish upstream-import assurance,
scoped Mech review and independently rechecked evidence; publish both their
disjoint reporting buckets and detailed attributes. Track agent-assisted review
separately from human signoff. Missing or inaccessible evidence is distinct from
negative experimental evidence. A withheld mapping is not a globally false
biological assertion.

“All edges covered” means no rows fall out of the ledger. It must never be used
as a synonym for “all edges independently supported by literature.” Publish
separate coverage metrics by predicate, source, review depth, and unresolved
reason, with both edge-weighted and distinct-claim/experiment counts.

Use the following review paths:

1. **Ontology and taxonomy imports:** verify the pinned source statement,
   relation semantics, identifiers, taxon/strain scope and transformation.
   Route scientific or modeling disputes to their owning source. Import
   validation is an explicit level of assurance, not a fresh literature review
   of every ontology axiom.
2. **Existing reviewed Mech claims:** match exact scientific scope and evidence
   lineage, import the pinned decision, and retain its limits. Matching names,
   endpoints, or a passing schema check is insufficient.
3. **New or conflicting biological claims:** assemble one coherent evidence
   packet, ask an agent for a structured decision, run deterministic checks,
   then perform an independent adversarial review before publishing a supported
   claim. Escalate ambiguous/high-impact decisions for domain review and allow
   an unresolved result.
4. **Predictions and text mining:** preserve their computational origin and
   uncertainty. Agreement or a PREGO score is not experimental confirmation.

A packet can cover multiple edges only when it retains a frozen selector,
explicit membership, and a reason the same decision applies to each member.
Changes to evidence, source version, mapping policy, or claim scope invalidate
the affected review. Do not simply carry “reviewed” forward across releases.

Store provenance links across Mechs to detect shared publications, experiments,
and copied assertions. KG-derived content subsequently curated in a Mech must
not return as independent corroboration of its own ancestor. Evidence graphs,
ontological relationships, statistical associations, and biological causal
graphs remain different products. Causal interpretation requires the native
Mech's mechanistic evidence and scope rules.

## Storage, website and CI design

At a hypothetical 1,000 bytes per edge record, 17.6 million records require
17.64 GB before Git history and filesystem overhead. At 5,000 bytes per HTML
page, edge pages require 88.19 GB. These are sizing scenarios, not measured
serialization sizes. Both make a per-edge Git/Pages design unsuitable.

GitHub Pages limits published sites to 1 GB and deployments to 10 minutes; the
100 GB/month bandwidth limit is soft. Custom Actions builds are exempt from
the soft ten-builds/hour limit, not from the site-size limit.
[GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

Use this division:

| Location | Contents |
|---|---|
| EdgeMech Git repository | Schema/contracts, routing rules, small fixtures, reviewed policy changes, bounded review bundles/selected adjudications, release manifests and checksums. |
| Specialist Mech repositories | Native scientific records, evidence-linked decisions and histories; exporters of explicitly supported scoped assertions. |
| Versioned artifact storage | Original KGX snapshots; partitioned Parquet observation, membership and decision tables; authoritative complete decision/review histories; evidence snapshots where licensing permits; immutable machine-readable exports. |
| Local analysis | DuckDB over those versioned files; repeatable full reconciliation and analytical queries. |
| GitHub Pages | Small release dashboard, aggregate counts, bounded search/index shards, and a reusable record viewer that fetches only the selected packet/detail shard. |
| Optional read-only query service | Bounded cross-partition filtering and graph queries when precomputed indexes are insufficient; introduced after measuring real reader needs. |

Partition the bulk tables by release and stable ID ranges/hash buckets, with
source/predicate-aware indexes and columnar row groups. Set partition sizes from
a benchmark; avoid an uncontrolled source × predicate × taxon directory fanout.
Publish atomically by replacing a small manifest only after every referenced
object is verified. Keep all historical manifests addressable.

Bound Git growth as well as page growth: replacing per-edge files with millions
of per-packet files would recreate the problem. Full review histories are durable
versioned artifacts. Git retains selected authored adjudications, policies and
manifests. Large proposed decision changes need deterministic semantic diffs,
readable summaries and access to every changed decision for review; approving a
hash alone does not approve its scientific contents. Establish tracked-byte,
authored-file and Git-object growth budgets, then compact derived indexes without
discarding the immutable review history.

Release assets are a suitable initial distribution channel for downloads:
GitHub allows up to 1,000 assets per release, each under 2 GiB. The 178 MiB
compressed September archive fits, but its uncompressed edge TSV does not fit
as one asset. Pack or partition as necessary. These limits do not establish
that release hosting is suitable for browser range queries; test CORS, byte
ranges and caching, or use object storage/CDN for the interactive data layer.
[GitHub release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

Reuse the published ProteinTraitsMech browser pattern:
[`scripts/build_docs_index.py`](https://github.com/CultureBotAI/proteintraitsmech/blob/490bbfd5284a45cb0aeca181b706045a149a08e0/scripts/build_docs_index.py)
uses lean search shards, bounded detail buckets and exact-ID routing rather
than generating a file for every record. Its constants are useful starting
points, not evidence that the implementation already scales to this graph.
Its authoritative per-record YAML storage and in-memory builder must be adapted
to bulk-table inputs; copying the browser pattern alone does not solve ingestion.
TaxonMech's shared viewer is another useful example, but its whole compressed
search index should not be copied into a 17.6-million-edge browser.

The viewer should expose the original row, grouped claim, evidence, decision,
review depth, unresolved reason, and owning Mech link. Arbitrary edge links
should resolve through a release-and-ID URL; they do not need a dedicated HTML
file. Show failed data loads distinctly from “no matching records.” Retain
offline bulk downloads as a complete access path.

**CI validates changes; it does not run literature curation.** During iteration,
check changed review bundles, their dependency closure, the schema, exporter
contracts, and small immutable fixtures. Changes to shared schemas, identifiers,
mapping rules or validators trigger broader checks. Run the required code suite
once on the final candidate, following KG-Microbe's now-merged
[single-suite policy](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/ba19536867b1d1e93fe14745dac6b232bffcd4d3/docs/TESTING.md).
Validate all rows with streaming data checks, not millions of parametrized tests.
ProteinTraitsMech's published
[`validation_scope.py`](https://github.com/CultureBotAI/proteintraitsmech/blob/490bbfd5284a45cb0aeca181b706045a149a08e0/scripts/validation_scope.py)
provides a concrete changed-data/dependency-invalidation starting point. DUFMech's
published Pages workflow provides exact-validated-commit deployment and explicit
artifact budgets. CultureMech's current full-corpus PR job is not the incremental
validation pattern proposed here.

Run full corpus reconciliation at release boundaries and after changes that can
invalidate broad coverage. Cache by complete dependency fingerprints, including
validator/schema versions. Never reuse an old “pass” against changed evidence.
Long-running agent tasks belong in resumable leased queues with idempotent writes,
bounded concurrency, retry and cost limits; use fleet workers or dedicated batch
compute. Do not create an Actions matrix job per edge. GitHub-hosted jobs have a
six-hour limit and matrices a 256-job limit.
[Actions limits](https://docs.github.com/en/actions/reference/limits)

## Existing assets and dependent work

The most concrete precedent is MediaIngredientMech. KG-Microbe's
[`mim_reviewed_release.py`](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/ba19536867b1d1e93fe14745dac6b232bffcd4d3/scripts/mim_reviewed_release.py)
validates supported/withheld exports, complete-row hashes and exactly one
disposition per source position. Generalize this accounting contract.
[`review_claims.py`](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/ba19536867b1d1e93fe14745dac6b232bffcd4d3/kg_microbe/utils/review_claims.py)
binds scientific decisions to exact owning-record/evidence bytes and explicitly
distinguishes such decisions from integrity receipts.

The basic four-file MIM bundle contains publisher claims about original
source/review hashes. KG-Microbe's schema-v2 pinned-archive consumption can also
verify those original bytes. Neither step independently redoes the scientific
review. Preserve these distinct assurance levels. The scoped integration issue
[#1123](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1123) is closed;
do not schedule it again as wholly unfinished. Its accepted scope does not imply
general CultureMech ingestion or approval to replace production mappings.

Proposed scientific routing follows below. A native review capability or record
count is not evidence that all records are reviewed or exportable.

| Owning repository | Suitable edge/claim scope | Required work or condition |
|---|---|---|
| CultureBotAI/TraitMech | Microbial phenotype, physiology, growth and assay claims | Export qualified observations and reviewed claims; preserve organism/strain, condition, measurement, polarity and source lineage. Prioritize BacDive/MetaTraits compatibility. |
| CultureBotAI/CultureMech | Medium composition, recipes, organism growth in a specified medium | Distinguish a listed target organism from experimentally demonstrated growth; preserve recipe versions and culture conditions. |
| CultureBotAI/MediaIngredientMech | Ingredient identity, hydration/material scope and supported mappings | Reuse the reviewed export/disposition contract; reconcile native exporter capabilities with CLAW manifest declarations. |
| CultureBotAI/TaxonMech | Taxonomic identity, strain/species placement and GTDB/NCBI mappings | Versioned crosswalk and scope policies; no broad/close match promoted to exact identity. |
| CultureBotAI/HabitatMech | Habitat, isolation source, host/environment claims | Preserve isolation provenance, nesting and sampling context; distinguish occurrence from ecological preference or function. |
| CultureBotAI/CommunityMech | Microbe–microbe interactions and community context | Separate co-occurrence from experimentally supported interaction and mechanism. |
| CultureBotAI/AntibioticMech | Resistance/sensitivity and drug-response evidence | Preserve assay, concentration, medium and strain; distinguish molecular mechanism from observed phenotype. |
| CultureBotAI/CellStructureMech | Morphology and cellular structures | Match native claim scope and experimental versus inferred evidence before reuse. |
| CultureBotAI/PathwayMech | Processes, reactions, pathways and organism-level capacity | Retain reaction direction and organism/protein evidence; inferred capacity is not demonstrated flux. |
| CultureBotAI/DUFMech; CultureBotAI/proteintraitsmech | Protein/domain function and measured protein traits | Reuse only exact sequence/version/coordinate/construct scope. DUF coordinate-reasoning work is a dependency for relevant claims, not a prerequisite for all edge curation. |
| CultureBotAI/NaturalProductMech; CultureBotAI/CMMMech | Specialized natural-product or material claims when their native scopes match | Adopt explicit adapters after inspecting eligible native review exports; do not infer general coverage from repository identity. |
| CultureBotAI/AIMech | Only explicitly matching claims under its native scientific scope | No initial scientific routing assumed; determine applicability from actual records. |
| CultureBotAI/culturebotai-claw | Shared contracts, scheduling, provenance/evidence validation, fleet registration and publication budgets | Publish one canonical versioned contract and consumer conformance fixtures before parallel adapter rollout. It is not the scientific authority for every claim. |

Only create another domain Mech if the coverage inventory reveals a substantial
unowned claim class. Most new infrastructure belongs in EdgeMech and the shared
contract; scientific fixes belong in existing owners.

The following native capabilities were checked at published revisions. Routing
for the remaining specialist repositories above is provisional: their full
scientific export contracts were not inspected during this review.

| Published source | Verified asset | Remaining adoption work |
|---|---|---|
| [MediaIngredientMech `0ee56c11`](https://github.com/CultureBotAI/MediaIngredientMech/blob/0ee56c11a2894ed50a476b331d56297be0a3ee12/src/mediaingredientmech/export/supported_kgx.py) | Native approved-assertion KGX exporter and supported/withheld SSSOM export; exact source-position decisions and record/evidence hashes. | The CLAW manifest still declares KGX disabled while native code has advanced. Reconcile the declaration with verified consumer acceptance; do not flip it solely because an exporter exists. |
| [TraitMech `6c40bd0f`](https://github.com/CultureBotAI/TraitMech/blob/6c40bd0fdd324c2dfa3c79061be085988c8de004/src/traitmech/schema/traitmech.yaml) | Trait records, evidence-bearing causal graphs and protein examples; taxon-agnostic mechanisms distinct from organism examples. | Add a downstream scoped-assertion exporter. Generic mechanism review does not establish a particular organism's trait. [#1982](https://github.com/CultureBotAI/TraitMech/issues/1982) records source-limited/nonmechanistic cases. |
| [HabitatMech `95a1eb1b`](https://github.com/CultureBotAI/HabitatMech/blob/95a1eb1b6a5b18b8a5c3b135222b1118f7506ef0/src/habitatmech/schema/habitatmech.yaml) | GOLD/BacDive/PREGO source attestations and habitat grounding; observed association distinguished from characteristic taxon. | Add a downstream assertion exporter; preserve shared source lineage. [#2284](https://github.com/CultureBotAI/HabitatMech/issues/2284) records quote-check exceptions in one audit, not graph-wide error rates. |
| [CommunityMech `898c839a`](https://github.com/CultureBotAI/CommunityMech/blob/898c839a50e08b75609d6ac6fa0659fcdb001f80/src/communitymech/export/kgx_export.py) | KGX transport with deterministic edge IDs, publications, supporting text and source attribution. | Add an approved-only partition; retain richer KG-Microbe observation identity. [#765](https://github.com/CultureBotAI/CommunityMech/issues/765) identifies claims needing renewed evidence. |
| [CLAW `3022b873`](https://github.com/CultureBotAI/culturebotai-claw/blob/3022b8738dcc9e01c7464a8d5c95aa9be2eef141/src/kg_microbe_governance/artifacts/schema/record_review.yaml) | Canonical review envelope, selectors, semantic digests, input provenance, independence and coverage; quote-checking machinery. | Extend the envelope for release occurrences/export accounting. Quote checks and valid review documents do not establish scientific truth. The research package supplies policy/result schemas, not provider execution; choose a supported native worker path for the canary. |

Additional site/CI baselines: CultureMech `a74dd489720c9df96cc073ffd11568d407d3c06c`,
DUFMech `aa7d08bcf3a9a03879d06cffd075bc083d29788f`, TaxonMech
`b04590a7a416eb934f67e7c04416e37924f10ec8`, and proteintraitsmech
`490bbfd5284a45cb0aeca181b706045a149a08e0`. These were source reviews, not rendered
browser checks or scale benchmarks.

Several KG-Microbe dependencies already have records:

| Dependency | Existing work | Plan treatment |
|---|---|---|
| Reproducible current publication | [#887](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/887), open | Fix and verify the publication source before calling a production corpus the latest release. Historical pilot can proceed independently. |
| Item-level BacDive attribution | [#770](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/770), open | Extend beyond currently supported metabolite-utilization evidence; never attach every record citation to every edge. |
| Agreeing observations and grouped claims | [#794](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/794), open | Preserve individual observations and add a derived claim layer; do not overwrite raw evidence to aggregate it. |
| Contradictions and unmapped values | [#737](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/737), open | Use as a pilot, after distinguishing real contradictions from different specificity/conditions. Historical issue counts are not current measurements. |
| Obsolete assay predicate | [#909](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/909), open; berkeleybop/metpo as ontology owner | Resolve the scientific modeling upstream; no invented successor. Can be accounted as unresolved without blocking unrelated cohorts. |
| Evaluation without copied evidence | [#698](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/698), open | Require provenance-disjoint evaluation and uncertainty. Current PREGO quality code retracts older discrimination claims; do not reuse those figures. |
| Lossless evidence serialization | [PR #1585](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1585), draft/open | Coordinate with this work; it is not yet a shipped contract. |
| Isolation and reaction-direction evidence | [PR #1587](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1587), [PR #1589](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1589), open | Inspect current scope before assigning overlapping adapters. |

Additional gaps in this plan are proposed work packages, not newly filed issues.
Refresh issue/PR states before implementation. For governed shared artifacts,
change and release the canonical CLAW source before updating consumer pins.

## Dependency-ordered implementation

**Wave 0 — establish the denominator and reuse opportunity.** Owner: KG-Microbe
integration lead, with one fleet-contract reviewer. Preserve the September pilot,
select the intended production build, and inventory every row by source,
predicate, evidence availability and routing outcome. Join against pinned,
eligible reviewed Mech exports; report exact matches, incompatible scope,
shared evidence, unmapped IDs and unavailable exports separately. Deliver a
machine-readable eligibility/coverage matrix and source-lineage report. Do not
promise a reuse percentage until this join is measured. This work can proceed
alongside the publication repair.

**Wave 1 — shared contract and thin registry.** Owner: CLAW contract maintainer
and EdgeMech lead. Agree the six identities, review envelope, dispositions,
evidence lineage and invalidation rules; version the contract and supply offline
positive/adversarial fixtures. Implement an EdgeMech registry over bulk tables,
an immutable manifest and a complete pending ledger. Use the MIM exhaustive
partition model and KG-Microbe observation/manifest invariants. Deliver one
coverage count query and one edge-to-owning-review lookup. Shared schema changes
must precede consumer rollout.

**Wave 2 — exactly one real end-to-end canary.** Owner: one specialist maintainer
plus the KG-Microbe adapter owner. Start with a tightly scoped MediaIngredientMech
mapping because the reviewed export and consumer already exist. Carry one
evidence packet through acquisition/cache, native review, supported/withheld
export, EdgeMech membership, KG candidate ingestion, serialized archive and
viewer. Verify the persisted artifacts and hashes, a scope mismatch/withhold,
and invalidation after a relevant input changes. Use the actual launcher,
environment, storage and worker path intended for subsequent jobs. Repair and
repeat this canary before any fanout.

**Wave 3 — stratified pilot and independent adapters.** Once the contract and
canary pass, run a bounded pilot of roughly 500–1,000 rows grouped into coherent
packets across BacDive/MetaTraits traits, taxonomy, habitat, media and a
conflicting/negative-evidence cohort. Preserve source proportions for coverage
reporting but oversample difficult cases for error discovery. Evaluate against
independently adjudicated evidence, with shared experiments/sources kept out of
both sides of a claimed independent evaluation. Estimate time and cost per
new packet, reuse rate, abstention/conflict rates and corrected-source impact.
This is a proposed sample size, not a powered estimate of graph-wide accuracy.

Parallel work after the shared contract can split into TraitMech provenance,
HabitatMech context, TaxonMech mapping, and the browser/storage implementation.
Give each native schema/exporter one owner; serialize overlapping CLAW contract
changes. Coordinate with existing PRs rather than creating competing writers.

**Wave 4 — bounded production queue.** Prioritize source/predicate cohorts by
downstream use, known defect impact, available evidence and reuse opportunity.
Start with systematic provenance/mapping corrections affecting many rows, then
unresolved high-value claims. Record leases/checkpoints and deduplicate evidence
retrieval; cache only when licenses and source versions allow it. Set budget and
concurrency from the pilot. Do not estimate LLM cost as one call per graph row.
Forecast total cost as ingestion + unique new packet review + re-review after
invalidation + storage/publication, using measured pilot rates and uncertainty.

**Wave 5 — reviewed release and continuing updates.** Produce an immutable
curation overlay and separately named candidate graph. KG-Microbe's merge is
transport of finalized inputs, so semantic corrections must enter the owning
transform/mapping and regenerate affected products; do not patch the canonical
merge to rewrite meaning. Verify the producer→finalizer→archive round trip and
all row dispositions. Publish only after review and the user's merge/release
decision. On the next release, compare observations and evidence dependencies,
carry forward only still-valid decisions, and queue additions/changes/removals.

## Acceptance and unresolved choices

Acceptance for the first implementation:

- Every input occurrence appears exactly once in the current accounting ledger;
  all totals reconcile to the pinned manifest. Every supported outcome resolves
  to a scoped decision and its evidence or an explicitly named import policy.
- Independent source observations and contradictions survive aggregation and
  export. Wrong strain, wrong hydration, changed evidence, copied evidence,
  missing source and incompatible function scope all produce explicit failures
  or withheld decisions in adversarial fixtures.
- One end-to-end canary leaves nonempty, hash-verified artifacts using the
  production execution path. It proves that path, not rate-limit behavior or
  accuracy across other source types.
- Changed-data checks do not scan unrelated scientific records during ordinary
  iteration. The final code suite and full release data reconciliation still
  run where required; duplicate full-suite execution is not reintroduced.
- Proposed initial performance targets: changed-bundle CI below 10 minutes,
  Pages payload below 250 MB, typical detail data fetch below 2 MB, and a bounded
  first search response. Initial EdgeMech repository budgets: 250 MB of tracked
  files, 10,000 authored files and a 1 GB Git-object growth alert. Adjust only
  from measured workload needs while keeping bulk history outside Git. Benchmark
  on documented hardware/network; these are targets, not measured performance or
  platform guarantees.
- Users can retrieve any edge by ID/release, see what was actually reviewed,
  follow its owning Mech/evidence, and download the full bulk data.

Before production rollout, settle the repository name, intended production
release, durable storage/egress budget, source redistribution permissions,
human-review escalation rules and worker budget. None blocks the local inventory
or the proposed contract/canary work. No domain-wide evidence review, exact Mech
overlap rate, compression benchmark, throughput benchmark or paid-provider cost
measurement was performed in this planning review.

## Reproduction and retained evidence

The original checkout and its modified statistics file were preserved. Local
planning work is isolated on `plan/edge-curation-architecture-20261103` in
`kg-microbe-curation-plan-20261103`. At the end of that planning turn no commit or
PR had been created and no implementation had been installed. The subsequent
implementation worktree retains this report and its helper scripts.

Scripts retained with this report:

- [`profile_edge_curation_snapshot.py`](../../scripts/adhoc/profile_edge_curation_snapshot.py): streams both TSVs, hashes exact bytes, checks manifest counts and profiles raw fields.
- [`summarize_edge_curation_profile.py`](../../scripts/adhoc/summarize_edge_curation_profile.py): derives percentages and explicitly hypothetical sizing scenarios from the verified scan.

The 10,000-row-per-file canary used the same profiling command and output area;
its nonempty JSON explicitly marks the scans partial. The full scan took about
107 seconds for edges and 11 seconds for nodes in this run. The saved outputs
are [`profile.json`](../../data/edge-curation-plan/profile.json),
[`summary.json`](../../data/edge-curation-plan/summary.json), and
[`canary.json`](../../data/edge-curation-plan/canary.json). Raw release metadata,
the manifest and fleet manifest are in
[`data/edge-curation-plan/evidence/`](../../data/edge-curation-plan/evidence/).
These generated data files are local, untracked evidence, not committed Git data.
Both helper scripts pass the repository's Ruff checks. The final formatted
profiler was rechecked with a 10,000-row-per-file canary under Python 3.10;
[`canary-final.json`](../../data/edge-curation-plan/canary-final.json) retains that
result. Run these helpers with the repository's supported Python 3.10–3.12.
