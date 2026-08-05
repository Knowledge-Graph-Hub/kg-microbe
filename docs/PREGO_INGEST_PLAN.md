# PREGO ingest plan

**Tracking issue:** [#182 — ingest PREGO knowledgebase](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/182)
**Status:** planning — **blocked on data acquisition** (see [Data acquisition](#data-acquisition-the-blocker))
**Owner:** unassigned
**Estimated scale (if unblocked):** ~10⁵ nodes, ~10⁶ edges
**Category:** environmental
**Ranking:** #5 in the current novel-transform recommendations (see [`NOVEL_TRANSFORMS.md`](./NOVEL_TRANSFORMS.md))

## Why ingest PREGO

BacDive and `madin_etal` cover organism↔habitat associations partially and inconsistently — BacDive from strain-level isolation-source curation, `madin_etal` from a small compositional-habitat table. PREGO systematically closes that gap by text-mining the entire PubMed corpus for co-mentions of taxa with environments (ENVO), processes (GO), and diseases (DOID/BTO). For the flagship taxa-media link-prediction use case, "grows in similar habitats" is a strong prior for "grows in similar media" — PREGO gives that signal at 10⁵–10⁶-edge scale, uniformly across the tree of life rather than only for the ~50 K strains BacDive has curated.

## Critical caveat

**The PREGO associations table is not currently publicly downloadable.** The `prego.hcmr.gr/Downloads` page as of 2026-08-04 reads:

> "On this tab, we will provide a bulk download of all the associations available on the PREGO knowledge-base."

Future tense. Only the **tagger dictionary** — the entity vocabulary — is on `download.jensenlab.org`. The dictionary alone adds ~0 novel edges to KG-Microbe, so ingesting only the dictionary is a low-value ship. Real value depends on obtaining the associations.

See [Data acquisition](#data-acquisition-the-blocker) for the acquisition strategy.

## Phase 1 — What PREGO contains

**Publication:** Zafeiropoulos et al. 2022, *Microorganisms* 10(2):293. DOI `10.3390/microorganisms10020293`. Text-mining pipeline over PubMed that scores co-mentions of taxa with environments (ENVO), processes (GO), and diseases (DOID/BTO), using the [JensenLab tagger](https://github.com/larsjuhljensen/tagger).

**Website / API:** https://prego.hcmr.gr/ (CGI-driven; `/Search`, `/SequenceSearch`, `/About`, `/Downloads`). No documented REST API. Downloads page is empty as noted above.

**License:** CC-BY (both dictionary and paper).

**Downloaded and inspected `prego_dictionary.tar.gz` (292 MB, 2024-09-13):**

| File | Rows | Purpose |
|---|---:|---|
| `prego_entities.tsv` | 2,496,991 | `(serial, type_int, source_id)` — JensenLab tagger triples |
| `prego_names.tsv` | 13,948,977 | `(serial, synonym)` — every mention name |
| `prego_preferred.tsv` | 2,477,875 | `(serial, preferred_label)` — one per entity |
| `prego_groups.tsv` | 42,531,655 | `(child_serial, parent_serial)` — hierarchy (NCBI tree, GO is_a, etc.) |
| `prego_global.tsv` | 68,528 | Stopword vocabulary |
| `prego_texts.tsv` | 43,723 | GO term definitions (bundled copy) |

**Entity type distribution:**

| type | count | maps to | in KGM already? |
|---:|---:|---|---|
| `-2` | 2,429,256 | `NCBITaxon:*` (species) | yes (`ontologies`, `bacdive`, `gtdb`) |
| `-21` | 28,240 | `GO:*` (biological_process) | yes (`ontologies`) |
| `-26` | 26,437 | `DOID:*` (disease) | partial (via `MONDO:*` in `ontologies`; DOID→MONDO xref needed) |
| `-25` | 11,324 | `BTO:*` (tissue) | **no** — BTO not currently in KGM |
| `-27` | 1,734 | `ENVO:*` (environment) | yes (`ontologies`) |

## Phase 2 — Delta vs existing transforms

**Overlaps:**
- NCBITaxon, GO, ENVO, MONDO/DOID vocabularies: all in the `ontologies` transform.
- Organism↔environment edges: partial coverage from `bacdive` (isolation source) and `madin_etal` (compositional habitats).
- Organism↔process edges: partial from `bacdive` (metabolism keywords) and `metatraits`/`microbedecoder` (fermentation profiles).

**What PREGO uniquely adds** (assuming associations are obtained):
1. **Systematic taxon→ENVO edges** across the entire literature — not just BacDive-curated strains. Expands from ~50 K covered organisms to ~2 M.
2. **Taxon→GO process edges** with confidence scores from co-mention statistics — quantitative, not just presence/absence.
3. **Taxon→DOID edges** — organism↔disease from text-mining. Complementary to `disbiome` and any human-microbiome data.
4. **Score-attributed edges** so downstream users can threshold on confidence (`z_score`, `co_mention_count`).

**Merge policy for overlap:** every PREGO edge carries `primary_knowledge_source: infores:prego` so it stays distinguishable from bacdive/madin edges to the same target. No dedup at the transform stage; merge-time dedup by `(subject, predicate, object, primary_knowledge_source)` is fine.

**If we ingest this, "why do we need it when we have BacDive?" answer in one line:** BacDive covers ~50 K strains from strain-level isolation-source curation; PREGO covers ~2 M taxa from text-mining and adds confidence-scored process/disease edges that BacDive doesn't emit at all.

## Phase 3 — Entity model

Assumes the associations table becomes available in the JensenLab-standard 4-column format: `(entity1_type_int, entity1_id, entity2_type_int, entity2_id, score, z_score)` — this is the shape STRING/DISEASES use, so PREGO is expected to mirror it.

| Row shape from source | Emitted edge | Predicate | Notes |
|---|---|---|---|
| (taxon, ENVO, score) | `NCBITaxon:X` → `ENVO:Y` | `biolink:located_in` | Novel content; carry `score` + `z_score` as edge attributes |
| (taxon, GO process, score) | `NCBITaxon:X` → `GO:Y` | `biolink:capable_of` | Novel content |
| (taxon, DOID, score) | `NCBITaxon:X` → `MONDO:Y` | `biolink:associated_with` | Route through DOID→MONDO xref in `ontologies` output |
| (taxon, BTO, score) | *(defer to v2)* | — | BTO not in KGM; not worth the ontology import for v1 |

**Predicates:** all existing biolink; no METPO extensions needed.
**Prefixes:** all existing (`NCBITaxon`, `ENVO`, `GO`, `MONDO`).
**No new placeholder prefixes.**
**No stub nodes** — every PREGO edge subject/object already resolves in an existing KGM transform.

**Edge attributes** (per JensenLab convention):
- `score` — combined co-mention score
- `z_score` — statistical significance
- `primary_knowledge_source: infores:prego`

**Threshold policy for v1:** emit all associations. Consumers can filter by score. Consider a `--min-score` flag in the transform if the raw edge count is unmanageable.

## Phase 4 — Cross-references

PREGO is *itself* a cross-referencing resource — every emitted edge is between existing KGM entities. No native identifier crosswalks of its own.

## Phase 5 — Scaffold (parallel to CLAUDE.md checklist)

```
[ ] kg_microbe/transform_utils/prego/__init__.py
[ ] kg_microbe/transform_utils/prego/prego.py              (PregoTransform class)
[ ] kg_microbe/transform_utils/prego/utils.py              (JensenLab-format parsers)
[ ] kg_microbe/transform_utils/constants.py                (PREGO, PREGO_DIR, PREGO_KNOWLEDGE_SOURCE = "infores:prego")
[ ] kg_microbe/transform.py                                (register PREGO: PregoTransform)
[ ] download.yaml                                          (dictionary tarball + associations file)
[ ] merge.yaml                                             (prego nodes + edges)
[ ] tests/test_prego_transform.py                          (fixture with ~10 associations across all 3 target categories)
[ ] tests/resources/prego/                                 (fixture dictionary + associations)
```

No new prefix registration in `custom_curies.yaml` — every target CURIE prefix is already registered.

## Phase 6 — Implement

Reference transforms (based on similarity):
- **`bacdive`** — for large-per-record source data + score-attribute handling.
- **`rhea_mappings`** — closest analog: a mapping file emitting many edges, thin on rich nodes. Read this first.

**Implementation notes:**
- Reuse `ChemicalMappingLoader` if PREGO exposes chemical entities we want to map (currently not — type `-1` count is 0 in the dictionary).
- Reuse `get_ontology_adapter("go" / "ncbitaxon")` for label lookups on the emitted edges.
- Use `split_multivalue_comma_only` from the shared helpers if any cell is multi-valued (unlikely in JensenLab format, but check).
- **Cardinality risk:** 2.4 M taxa × N GO processes could produce 10⁷+ edges. Add a canary early — run against a 100-taxon sample first and extrapolate before the full run.

## Phase 7-8 — Verify + test

Gates:
- `poetry run kg transform -s prego` produces non-zero rows.
- `kg-model-review --transform prego` reports **0 ERRORs**.
- `kg-path-review --transform prego` — sweep for self-loops, family-mismatch, orphan-edges.
- Post-merge cardinality check: `NCBITaxon → capable_of` fan-out should have a plausible distribution (long tail, not spike-outliers).
- Unit tests (target ~20):
  - Fixture-in → known node/edge count.
  - Every emitted edge carries `score`, `z_score`, `primary_knowledge_source`.
  - DOID→MONDO xref path exercises the mapping.
  - Absent optional score columns handled without raising.

## Phase 9 — Ship

Branch: `feat/prego-transform` · PR: `Add PREGO transform: taxon↔environment/process associations from text-mining`
Body: link this doc + fixture description + smoke-run counts.
Follow the `branch-triage-ship` playbook: adversarial review → file findings → address in-scope → admin-merge → delete branch.

## Phase 10 — Post-merge

- Close #182 with a link to the merge commit.
- Update `docs/NOVEL_TRANSFORMS.md` (regenerate via the `novel-transforms` skill — #182 drops off automatically once closed).
- Bump merged KG if this is release-adjacent; run `kg-release`.

---

## Data acquisition (the blocker)

The [`prego_dictionary.tar.gz`](https://download.jensenlab.org/prego_dictionary.tar.gz) tarball contains ONLY the tagger vocabulary — no association scores. Ingesting it alone would add ~2% synonym coverage over what KGM already has: low value, wrong shape.

Four options for getting the actual associations:

**A. Wait.** The Downloads page says "will provide". No timeline given. Passive; not recommended.

**B. Email the authors.** Zafeiropoulos + Pafilis at IMBBC-HCMR (lab42open) or Jensen at NNF-CPR. Ask for a snapshot of the association table in whatever format they maintain internally. Cite issue #182 and the flagship taxa-media link-prediction use case. Standard route for pre-release academic data; ~50% success rate; faster than waiting. **Recommended primary path.**

**C. Scrape the web interface.** `prego.hcmr.gr/Search` is CGI-driven and accepts entity IDs. With ~2.4 M taxa entries at ~7 requests/sec, that's ~4 days of scraping — feasible but discourteous without permission. **Do not do this without asking authors first** — they'd almost certainly prefer to just send the file.

**D. Dictionary-only v1.** Ingest just the synonym vocabulary; ship "PREGO synonyms" as an incremental value; upgrade to full associations later. Low value; unblocks the shipping schedule if it matters.

### Recommended sequencing

1. **Immediately:** email the authors (option B). Wait 2-3 weeks for reply.
2. **In parallel:** stub the dictionary download path in `download.yaml` and scaffold Phase 5 skeleton, so the moment the associations arrive we can plug into an already-wired transform.
3. **If reply arrives:** implement Phases 6-9 against their format. Since PREGO reuses JensenLab tagger conventions, format is likely the same 4-column tabular shape STRING and DISEASES use.
4. **If no reply after 3 weeks:** revisit — option D (dictionary-only v1) or drop PREGO from the top-5 in favor of a runner-up (thermobase, TogoMedium, or the CultureMech aggregate).

### Deep-research task in flight

A parallel `deep-research` workflow (task `wg3yk78jd`, launched 2026-08-04) is searching for any alternative downloadable copy of the associations table: Zenodo / Figshare deposits, MDPI supplementary materials, alternative JensenLab mirrors, undocumented CGI endpoints on `prego.hcmr.gr`, or downstream papers that mention how they obtained the data. Findings will be folded into this doc when they arrive.

## Effort estimate

- Dictionary-only path: ~2 days once code starts (fixture, wiring, prefix registration, ~10 tests).
- Full-association path (assumes JensenLab-format TSV in hand): ~3-4 days including score-attribute handling, model review, path review.
- Blocking risk: dominated by author-response latency (0-6 weeks, non-negotiable).

## Explicitly out-of-scope for v1

- Re-running the text-mining pipeline (weeks of compute + PubMed corpus).
- BTO tissue nodes — defer until an issue asks; BTO isn't in KGM's current ontology set.
- Sequence-search endpoint (`prego.hcmr.gr/SequenceSearch`) — separate concern.
- Taxon-taxon similarity edges — orthogonal to the taxa↔environment focus.
