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

### 6. 78 NCBITaxon name conflicts with the ontologies output — *integration*

GOLD carries 125,354 `NCBITaxon:` nodes; 101,659 also exist in
`data/transformed/ontologies/ncbitaxon_nodes.tsv`. Of those, **78 disagree on `name`** (0 on
`category`). KGX merge resolves by last-writer or first-writer depending on order, so GOLD
could silently override curated NCBITaxon labels. Either drop `name` from GOLD's taxon rows
and let the ontology own them, or reconcile the 78.

### 7. 23,695 GOLD-only taxa — *integration, needs a decision*

23,695 of GOLD's NCBITaxon nodes are **not** in the ontologies output. They may be
legitimate (recent NCBI additions, strains below the trimmed set) or artifacts of a stale
taxonomy dump. They would enter the merged KG as new taxa with GOLD-supplied names and no
ontology parentage — i.e. disconnected from the NCBITaxon hierarchy. Worth sampling before
accepting.

### 8. Ten nodes with an empty `name` — *content, trivial*

Cosmetic, but they will surface as unlabelled nodes.

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
| 6, 7 — taxon conflicts / GOLD-only taxa | **open** — needs a decision |

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
