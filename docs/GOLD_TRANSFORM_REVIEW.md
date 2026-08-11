# GOLD pre-transformed data — modeling review

**Date:** 2026-08-10 · **Branch:** `feat/gold-transform`
**Input:** `GOLD_nodes.tsv` (121.8 MB, 1,086,930 nodes), `GOLD_edges.tsv` (184.2 MB, 1,314,901 edges)
**Method:** `.claude/skills/kg-model-review` (`--transform gold --max-rows 0`, Biolink Model 4.2.2
via `bmt`), plus the merged-KG integrity checks that skill does not cover — dangling
endpoints, orphan nodes, duplicate edges, self-loops, cross-transform ID collisions and
Biolink domain/range per edge signature.

GOLD arrives already in KGX shape rather than as a source to parse, so this review treats
the TSVs as a transform's *output* and asks the question we would ask of any transform
before it enters a merge.

---

## Summary

| | |
|---|---|
| Blocking errors | **0** — nothing here prevents a merge |
| Schema conformance | **2 issues** — missing KG-Microbe standard columns |
| Modeling | **2 issues** — one Biolink domain/range violation, one vacuous predicate |
| Content | **2 issues** — 26.5% orphan nodes, 10 unnamed nodes |
| Integration | **3 issues** — unregistered prefixes, taxon name conflicts, new taxa |

The data is **structurally sound**. What needs attention is conformance, one real Biolink
violation, and the fact that a quarter of the nodes carry no information.

---

## What is clean

Genuinely better than several shipping transforms, and worth stating so the issues below
are read in proportion:

- **Zero dangling endpoints.** Every one of the 2,629,802 edge endpoints resolves to a row
  in `nodes.tsv`. Most transforms leak some.
- **Zero duplicate node IDs**, **zero duplicate `(subject, predicate, object)` triples**,
  **zero self-loops**.
- **All 5 categories and all 5 predicates are real Biolink 4.2.2 elements.**
- `relation` uses non-biolink CURIEs, as the convention requires.

---

## Issues

### 1. Schema does not match the KG-Microbe standard — *conformance*

| | standard | GOLD | missing |
|---|---|---|---|
| nodes | `id, category, name, description, xref, provided_by, synonym, deprecated, same_as` | `id, category, name, provided_by, xref` | `description`, `synonym`, `deprecated`, `same_as` |
| edges | `subject, predicate, object, relation, primary_knowledge_source, knowledge_level, agent_type` | `id, subject, predicate, object, relation, primary_knowledge_source` | `knowledge_level`, `agent_type` |

`knowledge_level` and `agent_type` matter most: every other transform emits them, and they
are how a consumer distinguishes an assertion from a prediction. GOLD entries are curated
submissions, so `knowledge_assertion` / `manual_agent` is the likely fill.

The extra edge `id` column is harmless — the post-merge cleanup drops it (`dropped=['id',
'knowledge_source']`) — but it should not be emitted.

### 2. `biolink:subclass_of` violates Biolink domain/range — *modeling, real violation*

4,220 edges assert `biolink:EnvironmentalFeature -subclass_of-> biolink:EnvironmentalFeature`.
`subclass_of` requires **`biolink:OntologyClass`** on both domain and range. Checked against
`bmt`:

| signature | n | domain | range | verdict |
|---|---:|---|---|---|
| `IndividualOrganism -in_taxon-> OrganismTaxon` | 605,885 | thing with taxon | organism taxon | OK |
| `IndividualOrganism -related_to-> Study` | 361,673 | named thing | named thing | OK |
| `IndividualOrganism -occurs_in-> EnvironmentalFeature` | 342,880 | unconstrained | unconstrained | OK |
| `EnvironmentalFeature -subclass_of-> EnvironmentalFeature` | 4,220 | ontology class | ontology class | **VIOLATION** |
| `IndividualOrganism -derives_from-> MaterialSample` | 243 | unconstrained | unconstrained | OK |

This is the GOLD ecosystem hierarchy (`gold.ecosystem:*`). Two fixes: add
`biolink:OntologyClass` as a second pipe-delimited category on those 4,226 nodes — which
KG-Microbe already does elsewhere (`METPO:1001000|biolink:Procedure`) — or use a
non-ontological containment predicate. The former is closer to what the data means.

### 3. `biolink:related_to` on 27.5% of edges — *modeling, semantics*

361,673 edges say `IndividualOrganism -related_to-> Study`. It passes validation because
`related_to` is unconstrained, but it asserts nothing a consumer can use, and it is the
second-largest predicate in the file. The real relation is presumably "was sequenced/
reported in", for which `biolink:contributes_to`, or a study-membership predicate, would
carry meaning. Worth resolving before this lands in a merged product, because it is
indistinguishable from a modeling placeholder.

### 4. A quarter of the nodes are orphans — *content, biggest issue by volume*

288,516 nodes (26.5%) have no incident edge:

| category | orphaned | of total | share |
|---|---:|---:|---:|
| `biolink:MaterialSample` | 279,618 | 279,671 | **100.0%** |
| `biolink:Study` | 8,893 | 71,794 | 12.4% |
| `biolink:EnvironmentalFeature` | 5 | 4,226 | 0.1% |

**`MaterialSample` is entirely disconnected.** 279,671 nodes exist and only 243
`derives_from` edges touch any of them — 0.09%. Whatever join was meant to link organisms
or studies to their biosamples did not happen. As shipped, these are 279k nodes of pure
weight: they inflate the node count by 25.7%, and any traversal that expects to reach a
sample will find nothing.

This is the one finding I would treat as blocking for a *standard* merge, not because it
breaks anything, but because shipping 279k unreachable nodes misrepresents coverage.

### 5. Unregistered CURIE prefixes — *integration*

`gold` (957,350 nodes) and `gold.ecosystem` (4,226) appear in no prefix map. They need
entries in `kg_microbe/transform_utils/custom_curies.yaml` with expansion URIs, or every
downstream RDF/SPARQL consumer will fail to expand them. This is the only issue the
built-in review flagged on its own.

### 6. 26 substantive NCBITaxon name differences — *integration*

GOLD carries 125,354 `NCBITaxon:` nodes; 101,659 also exist in
`data/transformed/ontologies/ncbitaxon_nodes.tsv`. Of those, 78 disagree on `name` (0 on
`category`). **KG-Microbe does not curate taxon labels** — ours are the NCBITaxon OBO
labels — so this is an OBO-vs-GOLD comparison, not a conflict with anything we maintain.

- **52 are OBO artifacts only**: homonym suffixes (`Microcystis <cyanobacteria>`) and
  nomenclatural qualifiers (`(nom. inval.)`). Strip those and the names match. No action.
- **26 are substantive**, in two groups: NCBI hybrid markers dropped by GOLD
  (`Saccharomyces x bayanus CBS 424` → `Saccharomyces bayanus CBS 424`, and five more CBS
  strains), and taxonomy version skew (`Jeongeupia sp. HS-3` vs `Jeongeupia sacculi`).

The hybrid-marker loss is the only one that changes meaning — without the `x` the name
denotes a different taxon. KGX merge resolves by write order, so neither side should be
allowed to overwrite the other's `name` on `NCBITaxon:` nodes.

### 7. GOLD would silently undo the NCBITaxon trim — *ours to fix, not GOLD's*

23,695 of GOLD's `NCBITaxon:` nodes are absent from our build. The first reading was that
GOLD used a different NCBI release. **That is wrong**, and the correction matters because
it moves the work to our side.

Checked against NCBI directly: of a random sample of 40, **39 are current taxids**, not
retired. What they are is out of scope for us — a random sample is `Wuhan Mosquito Virus 4`,
`Serratia phage phiMAM1`, `Picea glauca`, `Eudorina sp.`, `Spodiopsar sericeus` (a
starling). KG-Microbe deliberately trims NCBITaxon via `exclusion_branches.tsv`, which
excludes **Viruses (10239), Viridiplantae (33090) and Metazoa (33208)** among others. GOLD
is a genome database covering all of life; the difference is scope, and both sides are
behaving correctly.

The problem is what happens on merge:

| | |
|---|---|
| GOLD taxa in excluded branches | **23,695** |
| GOLD edges touching them | **76,034 (5.8% of the export)** |
| `IndividualOrganism` nodes typed to an excluded taxon | **76,034** |

Ingesting GOLD as-is reintroduces 23,695 viral, plant and animal taxa that the ontologies
transform went to the trouble of removing, plus 76k organism nodes hanging off them.

**Action (on us):** the GOLD transform should drop nodes and edges whose taxon falls outside
the trimmed NCBITaxon set, the same way the ontologies transform applies
`exclusion_branches.tsv`. Not yet implemented — the transform currently passes them through.

An earlier spot check suggested these were *merged* taxids, because sorting by ascending
taxid surfaced the oldest IDs, which are the ones most likely to have been merged
(`NCBITaxon:1172` → 264691 `Trichormus variabilis`). Random sampling corrected that: merges
are ~2% of the gap, not the explanation.

### 8. Ten nodes with an empty `name` — *content, trivial*

Nine of the ten are among the excluded-branch taxa in issue 7, so they never reach our
graph once that is handled. The tenth is cosmetic.

### 9. `xref` populated on 55.7% of nodes — *informational*

605,885 of 1,086,930 — exactly the `IndividualOrganism` count, so xrefs are present for
organisms and absent for everything else. Expected rather than wrong; noted so it is not
mistaken for partial loss.

---

## Status after the transform in this branch

The passthrough transform repairs the mechanical issues; the review above
describes the **upstream payload**, which is what a future refresh will look
like again.

| issue | status |
|---|---|
| 1 — schema columns | **fixed** — standard node/edge headers, `knowledge_assertion` / `manual_agent`, upstream edge `id` dropped |
| 2 — `subclass_of` violation | **fixed** — ecosystem nodes emit `biolink:EnvironmentalFeature\|biolink:OntologyClass` |
| 5 — unregistered prefixes | **fixed** — `gold` / `gold.ecosystem` in `custom_curies.yaml` |
| 8 — 10 unnamed nodes | carried through; upstream data issue |
| 3 — `related_to` | **open** — needs a modelling decision |
| 4 — orphan `MaterialSample` | **open** — warned at transform time, not dropped |
| 6 — taxon name differences | **open** — 26 substantive; hybrid markers raised upstream |
| 7 — excluded-branch taxa | **open, ours** — transform must apply the NCBITaxon trim |

`kg-model-review --transform gold` now reports **0 errors, 0 warnings** on the
conformed output.

## Recommended order

1. Add `gold` / `gold.ecosystem` to `custom_curies.yaml` (issue 5) — mechanical, unblocks RDF.
2. Emit `knowledge_level` / `agent_type`, drop edge `id`, add the missing node columns (1).
3. Decide what `MaterialSample` is for (4) — populate the join, or don't emit the nodes.
4. Fix `subclass_of` by adding `biolink:OntologyClass` to the ecosystem nodes (2).
5. Replace `related_to` with a meaningful predicate (3).
6. Reconcile the 78 taxon name conflicts and sample the 23,695 GOLD-only taxa (6, 7).

Issues 1, 2, 5 and 8 are mechanical. Issues 3, 4 and 7 need a decision about what the data
is meant to assert, which is a modeling question rather than a defect to patch.

---

## Requests to the upstream author

The items needing a decision by whoever produces the export are collected as a
standalone request in [`GOLD_UPSTREAM_REQUESTS.md`](GOLD_UPSTREAM_REQUESTS.md),
written to be sent as-is.

## Reproducing

```bash
mkdir -p data/transformed/gold
cp GOLD_nodes.tsv data/transformed/gold/nodes.tsv
cp GOLD_edges.tsv data/transformed/gold/edges.tsv
poetry run python .claude/skills/kg-model-review/kg_model_review.py \
  --transform gold --verbose --max-rows 0
```

The built-in review alone reports **0 errors, 2 warnings** — the prefix registration. Every
other finding above comes from the merged-KG-level checks layered on top, which is the gap
worth knowing about: a transform can pass the standard review and still ship 279k
unreachable nodes.
