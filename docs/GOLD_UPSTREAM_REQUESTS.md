# Requests to the author of the GOLD KGX export

**Re:** `GOLD_nodes.tsv` (1,086,930 nodes) and `GOLD_edges.tsv` (1,314,901 edges)
**From:** KG-Microbe · **Date:** 2026-08-10
**Full review:** [`GOLD_TRANSFORM_REVIEW.md`](GOLD_TRANSFORM_REVIEW.md)

Thank you for the export — it is in better shape than most of what we ingest. Before
listing requests, the things that are genuinely right, because they are not common:

- **Zero dangling endpoints.** All 2,629,802 edge endpoints resolve to a row in
  `nodes.tsv`. Most sources we take leak some.
- **Zero duplicate node IDs, zero duplicate `(subject, predicate, object)` triples, zero
  self-loops.**
- Every category and predicate is a real Biolink 4.2.2 element, and `relation` correctly
  uses non-biolink CURIEs.

We have written a transform that conforms the export to our internal conventions, so
nothing below blocks us. But several items are things only you can fix properly, and
fixing them at source is better than us patching them on every refresh.

---

## 1. `MaterialSample` nodes are entirely disconnected — our biggest ask

`biolink:MaterialSample` accounts for **279,671 nodes, of which 279,618 (100.0%) have no
incident edge.** Only 243 `derives_from` edges touch the category at all — 0.09%.

As shipped these are a quarter of the node count carrying no information, and any
traversal that expects to reach a biosample finds nothing.

**We think a join was intended and did not happen.** GOLD has organism↔biosample and
study↔biosample relationships in its own schema, so our guess is that the export builds
sample nodes but not the edges to them.

**Request:** either emit the edges linking biosamples to their organisms and/or studies, or
omit the sample nodes from the export. Either is fine; the current state is the one that
misleads, because node counts imply coverage that the edges do not deliver.

## 2. What does `IndividualOrganism -related_to-> Study` mean?

361,673 edges — **27.5% of the whole export**, the second-largest predicate — use
`biolink:related_to`. It validates, because `related_to` is unconstrained, but it asserts
nothing a consumer can act on, and at this volume it shapes how the export reads.

**Request:** replace it with the specific relation you mean. If the claim is "this organism
was sequenced/reported in this study", candidates include `biolink:contributes_to`, or a
study-membership predicate. If you tell us the intended semantics we are happy to propose
the Biolink mapping.

## 3. Please version the hosted files

The TSVs are currently a Drive folder. A Drive file can be replaced in place, so there is
no version for us to pin, and a silent upstream change would reach our graph with nothing
to detect it. We have been bitten by exactly this recently with another source, which
thinned by 48% between refreshes and went unnoticed for ~20 months.

**Request:** a versioned URL, a dated filename, or a published checksum — any of the three
is enough. If GOLD has a release cadence we can follow, better still.

## 4. NCBI hybrid markers are being stripped

Six `Saccharomyces` entries lose NCBI's interspecific-hybrid marker:

| NCBITaxon | NCBI | your export |
|---|---|---|
| 1387703 | `Saccharomyces x bayanus CBS 424` | `Saccharomyces bayanus CBS 424` |
| 1387704–1387708 | same pattern | CBS 1502, 1542, 2946, 3008, 5184 |

The `x` marks a hybrid; without it the name denotes a different taxon. This looks like a
normalisation step rather than a data entry choice.

**Request:** confirm whether something in the export pipeline strips `x`, and restore it if
so. This is the only taxon-name difference we found that changes meaning — we compared all
101,659 taxa we share with you, and the other 72 differences are either OBO formatting on
our side (homonym suffixes like `Microcystis <cyanobacteria>`, which are ours, not a
problem with yours) or NCBI merges you can pick up with a taxonomy refresh
(`Jeongeupia sp. HS-3` is now `Jeongeupia sacculi`).

---

## Two things we checked that need nothing from you

Recording these so they do not come back as questions later.

**23,695 of your taxa are absent from our NCBITaxon build.** This is our scope, not your
error: KG-Microbe deliberately trims NCBITaxon to microbes, excluding Viruses,
Viridiplantae and Metazoa among others. Your export covers all of life, so the difference
is expected — a random sample of the 23,695 is phages, marine viruses, `Picea glauca` and a
starling. We will drop those on our side.

**Nine nodes with an empty `name`.** All are in the branches above, so they never reach our
graph. Not worth your time.

---

## Smaller conveniences, entirely optional

These we already fill in ourselves; mentioning them only in case they are free at source.

| field | note |
|---|---|
| `knowledge_level`, `agent_type` on edges | We default these to `knowledge_assertion` / `manual_agent` on the assumption GOLD entries are curated submissions. **Please correct us if any subset is predicted or computed** — that assumption is the kind that is invisible once it is wrong. |
| `description`, `synonym` on nodes | Absent; we emit empty columns. Useful if GOLD holds them. |
| edge `id` column | We drop it; our merge does not use it. No action needed. |
| `xref` | Populated on 55.7% of nodes — precisely the `IndividualOrganism` rows. We read this as by-design rather than partial loss, but confirmation is welcome. |

## One modelling change we made, for your awareness

The 4,220 `EnvironmentalFeature -subclass_of-> EnvironmentalFeature` edges are a Biolink
domain/range violation: `subclass_of` requires `biolink:OntologyClass` on both ends. Since
the GOLD ecosystem hierarchy *is* a class hierarchy, we now emit those nodes as
`biolink:EnvironmentalFeature|biolink:OntologyClass`, which satisfies the constraint
without changing meaning.

**If you would rather express this differently upstream, we will follow your lead** — we
would prefer to match your intent than to carry a local divergence.

---

## Priority, if you only have time for some

1. **§1 — the `MaterialSample` edges.** By far the largest effect on usability.
2. **§3 — versioned hosting.** Cheapest to do, and it protects every future refresh.
3. **§2 — the `related_to` semantics.** Affects 27.5% of the export.
4. **§4 — the hybrid marker.** Six rows, but a name that means the wrong taxon.

Happy to jump on a call, or to send the exact queries behind any number here. Everything
in this document is reproducible from
[`GOLD_TRANSFORM_REVIEW.md`](GOLD_TRANSFORM_REVIEW.md), which includes the commands.
