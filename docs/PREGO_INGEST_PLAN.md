# PREGO ingest plan

**Tracking issue:** [#182 — ingest PREGO knowledgebase](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/182)
**Status:** planning — **unblocked** (data URLs discovered 2026-08-05 via deep-research task `wg3yk78jd`)
**Owner:** unassigned
**Estimated scale:** ~10⁵–10⁶ nodes, ~10⁸ edges (see [Data volumes](#data-volumes) — larger than the original estimate now that the raw table sizes are known)
**Category:** environmental
**Ranking:** #5 in the current novel-transform recommendations (see [`NOVEL_TRANSFORMS.md`](./NOVEL_TRANSFORMS.md))

## Why ingest PREGO

BacDive and `madin_etal` cover organism↔habitat associations partially and inconsistently — BacDive from strain-level isolation-source curation, `madin_etal` from a small compositional-habitat table. PREGO systematically closes that gap by text-mining the entire PubMed corpus for co-mentions of taxa with environments (ENVO), processes (GO), and diseases (DOID/BTO), and by consuming JGI IMG isolate metadata for direct experimental annotations. For the flagship taxa-media link-prediction use case, "grows in similar habitats" is a strong prior for "grows in similar media" — PREGO gives that signal at ~10⁸-edge scale across three channels (literature, environmental samples, JGI IMG isolates), uniformly across the tree of life rather than only for the ~50 K strains BacDive has curated.

## Correction to earlier assessment (2026-08-05)

The first draft of this plan (2026-08-04) claimed the PREGO associations table was not publicly downloadable, based on the `prego.hcmr.gr/Downloads` UI tab reading "we will provide" in future tense. **That was wrong.** The paper's Appendix D (Zafeiropoulos et al. 2022, PMC8879827, Table A2) documents three live download URLs on the same host, unlinked from the Downloads tab:

| URL | Compressed | Channel |
|---|---:|---|
| [`https://prego.hcmr.gr/download/literature.tar.gz`](https://prego.hcmr.gr/download/literature.tar.gz) | 5.4 GB | Text-mined literature co-mentions |
| [`https://prego.hcmr.gr/download/environmental_samples.tar.gz`](https://prego.hcmr.gr/download/environmental_samples.tar.gz) | 702 MB | Environmental samples channel |
| [`https://prego.hcmr.gr/download/annotated_genomes_isolates.tar.gz`](https://prego.hcmr.gr/download/annotated_genomes_isolates.tar.gz) | 269 MB | JGI IMG isolates channel |

All three verified 2026-08-05 with HTTP 200, real `application/x-gzip` payloads, `Accept-Ranges: bytes`, `Access-Control-Allow-Origin: *`. The Downloads UI page is stale documentation, not a data-availability gap. Each archive unpacks to a single `database_pairs.tsv` with a nine-column schema (see [Phase 3](#phase-3--entity-model)); the literature file is ~19.6 GB uncompressed.

**Consequence:** the "email the authors" recommendation in the original plan is unnecessary. The data is live and CC-BY-licensed; the transform can proceed on the normal timeline.

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

**What PREGO uniquely adds:**
1. **Systematic taxon→ENVO edges** across the entire literature — not just BacDive-curated strains. Expands from ~50 K covered organisms toward the full ~2 M in the dictionary.
2. **Taxon→GO process edges** with confidence scores from co-mention statistics — quantitative, not just presence/absence.
3. **Taxon→DOID edges** — organism↔disease from text-mining. Complementary to `disbiome` and any human-microbiome data.
4. **Direct experimental annotations** from the JGI IMG isolates channel (`annotated_genomes_isolates.tar.gz`) — carries a `direct-flag=TRUE` on each row plus a JGI IMG evidence URL, distinguishing curator-verified rows from text-mined ones.
5. **Score-attributed edges** so downstream users can threshold on confidence.

**Merge policy for overlap:** every PREGO edge carries `primary_knowledge_source: infores:prego` so it stays distinguishable from bacdive/madin edges to the same target. No dedup at the transform stage; merge-time dedup by `(subject, predicate, object, primary_knowledge_source)` is fine.

**If we ingest this, "why do we need it when we have BacDive?" answer in one line:** BacDive covers ~50 K strains from strain-level isolation-source curation; PREGO covers ~2 M taxa from text-mining and adds confidence-scored process/disease edges that BacDive doesn't emit at all.

## Phase 3 — Entity model

Each archive unpacks to a single `database_pairs.tsv` with a **nine-column schema** (verified via partial extraction of `annotated_genomes_isolates.tar.gz`):

```
entity1_type    entity1_id    entity1_extra    entity2_id    source    channel    score    direct_flag    evidence_url
```

Example row: `-2 → 100 → (extra) → GO:0000034 → "JGI IMG" → "Isolates" → 4 → TRUE → <JGI deep link>`.

The `entity1_type` column uses JensenLab tagger integer codes (`-2` = NCBITaxon, `-21` = GO biological_process, `-27` = ENVO, `-26` = DOID, `-25` = BTO). The `entity2_id` field is already a full CURIE for ontology entities; NCBITaxon rows carry a bare integer that needs the `NCBITaxon:` prefix prepended.

| Row shape from source | Emitted edge | Predicate | Notes |
|---|---|---|---|
| taxon `-2` → ENVO `-27` | `NCBITaxon:X` → `ENVO:Y` | `biolink:located_in` | Novel content; carry `score`, `channel`, `direct_flag` as edge attributes |
| taxon `-2` → GO process `-21` | `NCBITaxon:X` → `GO:Y` | `biolink:capable_of` | Novel content |
| taxon `-2` → DOID `-26` | `NCBITaxon:X` → `MONDO:Y` | `biolink:associated_with` | Route DOID→MONDO through `ontologies` output; skip if no xref |
| taxon `-2` → BTO `-25` | *(defer to v2)* | — | BTO not in KGM; not worth the ontology import for v1 |
| non-taxon subject (either side is ontology-ontology) | *(skip)* | — | PREGO's cross-ontology pairs (e.g. GO↔ENVO) are out of scope for the taxa-focused link-prediction use case |

**Predicates:** all existing biolink; no METPO extensions needed.
**Prefixes:** all existing (`NCBITaxon`, `ENVO`, `GO`, `MONDO`).
**No new placeholder prefixes.**
**No stub nodes** — every PREGO edge subject/object already resolves in an existing KGM transform.

**Edge attributes** (per JensenLab convention, discovered schema):
- `score` — PREGO scoring column (semantics per-channel; the literature file uses a two-score co-mention output that needs on-the-ground validation during Phase 6)
- `channel` — one of `Literature` / `Environmental` / `Isolates` — kept so consumers can filter by evidence type
- `direct_flag` — `TRUE` if the row is a direct curator/database annotation rather than text-mined
- `evidence_url` — deep link into the underlying evidence source (JGI IMG, PubMed abstract, etc.)
- `primary_knowledge_source: infores:prego`

**Threshold policy for v1:** emit all associations from all three channels. Downstream consumers can filter by `score`, `channel`, or `direct_flag`. If the total edge count exceeds ~10⁸ (see [Data volumes](#data-volumes)) and pushes merge-time cost past acceptable, add a `--min-score` flag or channel-select flag rather than dropping content silently.

## Phase 4 — Cross-references

PREGO is *itself* a cross-referencing resource — every emitted edge is between existing KGM entities. No native identifier crosswalks of its own.

## Phase 5 — Scaffold (parallel to CLAUDE.md checklist)

```
[ ] kg_microbe/transform_utils/prego/__init__.py
[ ] kg_microbe/transform_utils/prego/prego.py              (PregoTransform class)
[ ] kg_microbe/transform_utils/prego/utils.py              (JensenLab-format parsers, type-code table, DOID→MONDO xref helper)
[ ] kg_microbe/transform_utils/constants.py                (PREGO, PREGO_DIR, PREGO_KNOWLEDGE_SOURCE = "infores:prego")
[ ] kg_microbe/transform.py                                (register PREGO: PregoTransform)
[ ] download.yaml                                          (3 archives: literature / environmental_samples / annotated_genomes_isolates)
[ ] merge.yaml                                             (prego nodes + edges)
[ ] tests/test_prego_transform.py                          (fixture with ~10 associations across all 3 channels and 3 target categories)
[ ] tests/resources/prego/                                 (fixture database_pairs.tsv snippets, one per channel)
```

No new prefix registration in `custom_curies.yaml` — every target CURIE prefix is already registered.

**download.yaml entries** (concrete):

```yaml
- url: https://prego.hcmr.gr/download/literature.tar.gz
  local_name: prego_literature.tar.gz
  tag: prego
  # NOTE: 5.4 GB compressed (~19.6 GB uncompressed database_pairs.tsv). Text-mined
  # co-mention scores. Unlinked from the /Downloads UI page but documented in the
  # paper's Appendix D. CC-BY. Server (Mamba/nginx) occasionally returns HTTP 500
  # on HEAD but 200 on GET — retry-on-GET always succeeds.

- url: https://prego.hcmr.gr/download/environmental_samples.tar.gz
  local_name: prego_environmental_samples.tar.gz
  tag: prego

- url: https://prego.hcmr.gr/download/annotated_genomes_isolates.tar.gz
  local_name: prego_annotated_genomes_isolates.tar.gz
  tag: prego

- url: https://download.jensenlab.org/prego_dictionary.tar.gz
  local_name: prego_dictionary.tar.gz
  tag: prego
  # NOTE: 278 MB. Entity vocabulary — needed only if we resolve preferred labels
  # from serials, which we do NOT for v1 (association tables carry CURIEs directly
  # for ontology entities, and NCBI taxon integers we prefix as NCBITaxon:).
  # Kept in download.yaml for completeness / future use.
```

## Phase 6 — Implement

Reference transforms (based on similarity):
- **`rhea_mappings`** — closest analog: a mapping file emitting many edges, thin on rich nodes. Read this first.
- **`bacdive`** — for score-attribute handling and large-per-record source data if we ever ingest the dictionary.

**Implementation notes:**
- Reuse `get_ontology_adapter("go" / "ncbitaxon")` for label lookups on emitted subject/object nodes (we still emit rich nodes for any subject/object not already carried by the merged graph, but that will be a small residual — most already exist).
- **Stream the archives, don't materialise.** `literature.tar.gz` unpacks to ~19.6 GB. Read row-by-row with `gzip.open()` + `tarfile.open(mode="r|gz")` in streaming mode; do NOT load into a DataFrame.
- **Canary before the full literature run.** Start with the smallest archive (`annotated_genomes_isolates.tar.gz`, 269 MB) end-to-end — smoke it through Phase 7 gates first. Once that's clean, extrapolate row-count and disk-cost predictions before touching the 5.4 GB file. This is the standing global rule (see `~/.claude-work/CLAUDE.md` → "Canary first").
- **DOID→MONDO xref.** Not every DOID has a MONDO equivalent. Route through `ontologies/mondo_nodes.tsv` and skip rows with no xref rather than emitting an orphan DOID CURIE.
- **Cardinality risk.** 2.4 M taxa × N GO processes could produce 10⁸+ edges. Watch `NCBITaxon → capable_of` fan-out in Phase 7 for spike outliers (would indicate a runaway text-mining match on a single popular taxon).
- **Server quirk.** The Mamba/nginx server on `prego.hcmr.gr` occasionally returns HTTP 500 on HEAD requests but 200 on GET. `kghub-downloader` should already handle this via GET-based verification, but note this in the download.yaml comment.

## Phase 7-8 — Verify + test

Gates:
- `poetry run kg transform -s prego` produces non-zero rows.
- `kg-model-review --transform prego` reports **0 ERRORs**.
- `kg-path-review --transform prego` — sweep for self-loops, family-mismatch, orphan-edges.
- Post-merge cardinality check: `NCBITaxon → capable_of` fan-out should have a plausible distribution (long tail, not spike-outliers).
- Unit tests (target ~20):
  - Fixture-in → known node/edge count.
  - Every emitted edge carries `score`, `channel`, `direct_flag`, `primary_knowledge_source`.
  - DOID→MONDO xref path exercises the mapping; DOID with no MONDO xref is silently skipped.
  - Absent optional columns handled without raising.
  - JensenLab type-code table covers `-2 / -21 / -27 / -26 / -25`; unknown codes log-and-skip rather than raise.

## Phase 9 — Ship

Branch: `feat/prego-transform` · PR: `Add PREGO transform: taxon↔environment/process associations from text-mining`
Body: link this doc + fixture description + smoke-run counts.
Follow the `branch-triage-ship` playbook: adversarial review → file findings → address in-scope → admin-merge → delete branch.

## Phase 10 — Post-merge

- Close #182 with a link to the merge commit.
- Update `docs/NOVEL_TRANSFORMS.md` (regenerate via the `novel-transforms` skill — #182 drops off automatically once closed).
- Bump merged KG if this is release-adjacent; run `kg-release`.

---

## Data acquisition

**Resolved.** All three association archives are live on `prego.hcmr.gr`, discovered via deep-research task `wg3yk78jd` (see the [correction section](#correction-to-earlier-assessment-2026-08-05) at the top of this doc). Add them to `download.yaml` per Phase 5 and the transform can proceed immediately — no author contact needed.

### Data volumes

| Archive | Compressed | Uncompressed (est.) | Rows (est.) |
|---|---:|---:|---:|
| `annotated_genomes_isolates.tar.gz` | 269 MB | ~8.7 GB | ~48 M (JGI IMG isolates channel; verified partial-extract) |
| `environmental_samples.tar.gz` | 702 MB | ~22 GB | ~120 M |
| `literature.tar.gz` | 5.4 GB | 19.6 GB (confirmed via tar header) | ~110 M (assuming ~180 B/row typical of tagger output) |

Combined raw: **~280 M association rows**. After filtering to just taxon→(ENVO/GO/DOID/MONDO) shapes and applying merge-time dedup, expect **~10⁸ emitted edges** — an order of magnitude larger than the original `~10⁶` estimate in [`NOVEL_TRANSFORMS.md`](./NOVEL_TRANSFORMS.md); update that dict in the next `novel-transforms` skill refresh.

### Where the "not downloadable" misread came from

The `prego.hcmr.gr/Downloads` UI page still shows only a placeholder ("we will provide"), unchanged since the paper's publication in early 2022. The paper's Appendix D lists the actual URLs but they're unlinked from the UI. A first-pass check of the site's Downloads tab (which is what the original plan draft did) plausibly reads as "data not yet released" — but the paper is the authoritative reference and the endpoints have been live since ~2021-12-21. Documentation bug, not a data-availability bug.

## Effort estimate

- Full-association path: **~4-5 days** once code starts.
  - Day 1: canary on `annotated_genomes_isolates.tar.gz` (269 MB) end-to-end through Phase 7 gates.
  - Day 2-3: implement streaming parser + DOID→MONDO xref path + tests against fixture derived from the canary output.
  - Day 4: run the two larger archives end-to-end; verify cardinality + path review.
  - Day 5: ship PR + adversarial review.
- **Blocking risk: none.** Data is live and CC-BY. The prior estimate's "author-response latency (0-6 weeks)" no longer applies.

## Explicitly out-of-scope for v1

- Re-running the text-mining pipeline (weeks of compute + PubMed corpus). Ingesting the pre-computed pair scores is the whole point.
- **BTO tissue nodes** — defer until an issue asks; BTO isn't in KGM's current ontology set.
- **Cross-ontology pairs** (rows where both entities are ontology terms, e.g. GO↔ENVO). PREGO includes some of these; skip for v1 in favor of the taxa-centric edges that match the flagship use case.
- **Sequence-search endpoint** (`prego.hcmr.gr/SequenceSearch`) — separate concern.
- **Score-based edge filtering.** Emit all associations from all three channels; let downstream consumers threshold.
- **Taxon-taxon similarity edges** — orthogonal to the taxa↔environment focus.
