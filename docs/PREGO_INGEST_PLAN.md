# PREGO ingest plan

**Tracking issue:** [#182 — ingest PREGO knowledgebase](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/182)
**Status:** Phase 6a shipped (PR #667, 2026-08-04) · Phase 6b shipped (PR TBD, 2026-08-04)
**Owner:** unassigned
**Estimated scale:** ~10⁵–10⁶ nodes, ~10⁸ edges, ~10⁷ synonym enrichments (see [Data volumes](#data-volumes))
**Category:** environmental
**Ranking:** #5 in the current novel-transform recommendations (see [`NOVEL_TRANSFORMS.md`](./NOVEL_TRANSFORMS.md))

## Why ingest PREGO

BacDive and `madin_etal` cover organism↔habitat associations partially and inconsistently — BacDive from strain-level isolation-source curation, `madin_etal` from a small compositional-habitat table. PREGO systematically closes that gap by text-mining the entire PubMed corpus for co-mentions of taxa with environments (ENVO), processes (GO), and diseases (DOID/BTO), and by consuming JGI IMG isolate metadata for direct experimental annotations. For the flagship taxa-media link-prediction use case, "grows in similar habitats" is a strong prior for "grows in similar media" — PREGO gives that signal at ~10⁸-edge scale across three channels (literature, environmental samples, JGI IMG isolates), uniformly across the tree of life rather than only for the ~250 K strains BacDive has curated.

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
1. **Systematic taxon→ENVO edges** across the entire literature — not just BacDive-curated strains. BacDive covers ~250 K strains (verified in `data/transformed/bacdive/nodes.tsv`); PREGO expands coverage toward the full ~2 M NCBITaxon vocabulary — and does so at *species / higher* rank rather than strain rank, so the two sources are complementary rather than redundant (text-mining doesn't hit strain identifiers, which don't appear in literature).
2. **Taxon→GO process edges** with confidence scores from co-mention statistics — quantitative, not just presence/absence.
3. **Taxon→DOID edges** — organism↔disease from text-mining. Complementary to `disbiome` and any human-microbiome data.
4. **Direct experimental annotations** from the JGI IMG isolates channel (`annotated_genomes_isolates.tar.gz`) — carries a `direct_flag` column that is `TRUE` for curator/database rows and something else (empty / `FALSE`) for text-mined rows, so consumers can filter for the high-confidence subset. Each row also carries a JGI IMG evidence URL.
5. **Score-attributed edges** so downstream users can threshold on confidence.
6. **Literature-attested synonym expansion** (from the tagger dictionary, ~13.9 M name variants across ~2.5 M entities, ~5.6 aliases per entity on average). Every NCBITaxon / ENVO / GO node PREGO touches gains the alternate names that actually appear in PubMed abstracts — feeding better NER matching in other transforms and better user-facing search hits ("*Enterococcus faecium*" vs "*Streptococcus faecium*" vs "*E. faecium*" — one entity, many literature forms).

**Merge policy for overlap:** every PREGO edge carries `primary_knowledge_source: infores:prego` so it stays distinguishable from bacdive/madin edges to the same target. No dedup at the transform stage; merge-time dedup by `(subject, predicate, object, primary_knowledge_source)` is fine.

**If we ingest this, "why do we need it when we have BacDive?" answer in one line:** BacDive covers ~250 K strains at strain rank from isolation-source curation; PREGO covers ~2 M NCBITaxa at species / higher rank from text-mining, and adds confidence-scored process/disease edges that BacDive doesn't emit at all.

## Phase 3 — Entity model

Each archive unpacks to a single `database_pairs.tsv` with a **nine-column schema** (verified end-to-end on `annotated_genomes_isolates.tar.gz` — see [Canary findings](#canary-findings-2026-08-04)):

```
entity1_type    entity1_id    entity2_type    entity2_id    source    channel    score    direct_flag    evidence_url
```

Example row: `-2 → 100 → -23 → GO:0000034 → "JGI IMG" → "Isolates" → 4 → TRUE → <JGI deep link>`.

Both `entity1_type` and `entity2_type` use JensenLab tagger integer codes (`-2` = NCBITaxon, `-21` = GO biological_process, `-22` = GO cellular_component, `-23` = GO molecular_function, `-27` = ENVO, `-26` = DOID, `-25` = BTO). Entity IDs are already full CURIEs for ontology entities; NCBITaxon rows carry a bare integer that needs the `NCBITaxon:` prefix prepended. **Each unique association appears twice** in the raw data — as `(X, Y)` and as `(Y, X)` — so the transform must dedup to a canonical direction (see Phase 6a).

| Row shape from source | Emitted edge (subject → object) | Predicate | Notes |
|---|---|---|---|
| taxon `-2` ↔ ENVO `-27` | `ENVO:Y` → `NCBITaxon:X` | `biolink:location_of` | **Direction matches bacdive** (`ENVO → location_of → strain`); use same predicate here so the merged KG carries a single canonical direction for organism–environment edges. Carry `score`, `channel`, `direct_flag` as edge attributes. |
| taxon `-2` ↔ GO `-21` / `-22` / `-23` | `NCBITaxon:X` → `GO:Y` | `biolink:capable_of` | Novel content. Predicate fits **all three GO namespaces**: biological_process (`-21`), cellular_component (`-22`), molecular_function (`-23`). Isolates channel is 99.7% `-23` (molecular_function — see canary); literature channel likely biased toward `-21`. |
| taxon `-2` ↔ DOID `-26` | `NCBITaxon:X` → `MONDO:Y` | `biolink:associated_with` | Route DOID→MONDO through `ontologies` output; skip if no xref |
| taxon `-2` ↔ BTO `-25` | *(defer to v2)* | — | BTO not in KGM; not worth the ontology import for v1 |
| taxon `-2` ↔ taxon `-2` | *(skip)* | — | Host / co-occurrence taxon-taxon rows (e.g. `→ NCBITaxon:9606` = organism-associated-with-human). Small volume (~4K in isolates), out of scope for v1's taxa↔environment/process focus. |
| any pair where subject and object are both ontology terms | *(skip)* | — | PREGO's cross-ontology pairs (e.g. GO↔ENVO) are out of scope for the taxa-focused link-prediction use case |
| dictionary: `(serial, synonym)` × `(serial, CURIE)` join | node `synonym` column enrichment on `NCBITaxon:X` / `ENVO:Y` / `GO:Y` | — | Not an edge — the tagger dictionary's ~13.9 M name variants are joined via `prego_entities.tsv` → CURIE → `prego_names.tsv`, and the resulting alternate names are emitted as pipe-delimited `synonym` values on the node row. Only enriches nodes we already emit from the associations tables (avoids exploding into 2.5 M mostly-unused NCBITaxon stubs). |

**Predicates:** all existing biolink; no METPO extensions needed.
**Prefixes:** all existing (`NCBITaxon`, `ENVO`, `GO`, `MONDO`).
**No new placeholder prefixes.**
**No stub nodes** — every PREGO edge subject/object already resolves in an existing KGM transform.

**Edge attributes** (per JensenLab convention, discovered schema):
- `score` — PREGO scoring column (semantics per-channel; **integer scores 3 / 4 observed in the first 100 K isolates rows** — verify against the full 42 M-row file during implementation; literature and environmental score conventions to verify during their respective canaries).
- `channel` — the sub-channel string from the source archive (isolates has `Isolates`, `Single Amplified Genome`, `Genome annotation`, `Aquatic`, `Oceanic`, `Human`, `Plants`, plus PMID-tagged BioProject rows). Kept as-is so consumers can filter by evidence type.
- `direct_flag` — `TRUE` for direct curator/database rows. **All rows in the isolates archive are TRUE** (this whole channel IS the direct-annotation channel); the flag becomes discriminating only when literature rows (mostly `FALSE` / empty) get mixed in during merge.
- `evidence_url` — deep link into the underlying evidence source (JGI IMG, PubMed abstract, etc.). Often empty for older rows.
- `primary_knowledge_source: infores:prego`

**Node enrichment** (from the tagger dictionary):
- For each `NCBITaxon:` / `ENVO:` / `GO:` node the transform emits, pipe-delimited alternate names from `prego_names.tsv` land in the `synonym` column.
- Uses the `prego_entities.tsv` file as the serial → CURIE lookup, then joins `prego_names.tsv` on serial.
- Only nodes that appear in the associations tables get enriched — the transform does NOT emit 2.5 M standalone NCBITaxon stubs just because they exist in the dictionary.

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
  # NOTE: 278 MB. Tagger vocabulary — Phase 6b joins prego_entities.tsv
  # (serial → CURIE) with prego_names.tsv (serial → synonym) to enrich
  # the `synonym` column on every NCBITaxon / ENVO / GO node the
  # associations tables produce.
```

## Phase 6 — Implement

Split into two sub-phases in the same transform. Sub-phase 6a is the primary value; 6b is a multiplier. Canary 6a first — if 6b turns out messier than expected, ship 6a to master rather than blocking on the enrichment.

Reference transforms (based on similarity):
- **`rhea_mappings`** — closest analog for 6a: a mapping file emitting many edges, thin on rich nodes. Read this first.
- **`bacdive`** — closest analog for score-attribute handling.

### Phase 6a — associations (primary value)

- Reuse `get_ontology_adapter("go" / "ncbitaxon")` for label lookups on emitted subject/object nodes (we still emit rich nodes for any subject/object not already carried by the merged graph, but that will be a small residual — most already exist).
- **Stream the archives, don't materialise.** `literature.tar.gz` unpacks to ~19.6 GB. Read row-by-row with `gzip.open()` + `tarfile.open(mode="r|gz")` in streaming mode; do NOT load into a DataFrame.
- **Deduplicate by canonical-direction filter, not by tracking-set.** Every unique association appears exactly twice as an ordered pair: as `(type_A, id_A, type_B, id_B)` AND as `(type_B, id_B, type_A, id_A)`. Instead of an in-memory / sqlite / LMDB dedup set (all of which have their own problems — memory pressure, complexity, or false positives), just **filter each row by `entity1_type`** to keep the canonical-subject direction per row shape:
  - Taxon↔GO: keep rows where `entity1_type == -2` (drop the `-21/-22/-23 → -2` inverses).
  - Taxon↔ENVO: keep rows where `entity1_type == -27` — this matches the bacdive convention (`ENVO → location_of → strain`) so the merged KG carries one canonical direction.
  - Taxon↔DOID: keep rows where `entity1_type == -2` (biolink domain of `associated_with`).

  O(1) memory per row, single streaming pass, deterministic.
- **Canary before the full literature run.** Isolates archive canary complete 2026-08-04 (see [Canary findings](#canary-findings-2026-08-04)) — schema, row shapes, and scale confirmed. Extrapolate row-count and disk-cost predictions from those measurements before touching the 5.4 GB literature file.
- **DOID→MONDO xref.** Not every DOID has a MONDO equivalent. Route through `ontologies/mondo_nodes.tsv` and skip rows with no xref rather than emitting an orphan DOID CURIE.
- **Cardinality risk.** Isolates: ~21 M unique taxon↔GO_MF edges (post-dedup) confirmed. Literature likely 3-5x larger. Watch `NCBITaxon → capable_of` fan-out in Phase 7 for spike outliers (would indicate a runaway text-mining match on a single popular taxon).
- **Server quirk.** The Mamba/nginx server on `prego.hcmr.gr` occasionally returns HTTP 500 on HEAD requests but 200 on GET. **Verify during actual `kg download`** that `kghub-downloader` tolerates this — if it HEAD-checks and refuses, we'll need a custom fetch wrapper for the PREGO entries.

#### Canary findings (2026-08-04)

`annotated_genomes_isolates.tar.gz` fetched, extracted, and profiled end-to-end. Measured facts:

| Fact | Measured value | Plan estimate before canary | Status |
|---|---|---|---|
| Compressed size | 269 MB (verified) | 269 MB | ✅ |
| Uncompressed `database_pairs.tsv` | 8.1 GB (measured) | ~8.7 GB | ✅ close |
| Row count | **42,038,686** (measured) | ~48 M | ✅ close |
| Column 3 meaning | `entity2_type` (integer type code) | `entity1_extra` (wrong) | ❌ **plan schema fixed** |
| Row-shape dominance | **99.7% NCBITaxon ↔ GO molecular_function** (`-2` ↔ `-23`) | GO biological_process (`-21`) as focus | ❌ **plan predicate table now covers all 3 GO namespaces** |
| Bidirectional emission | Yes — every association appears as `(X,Y)` AND `(Y,X)` | Not called out | ❌ **plan now specifies dedup step** |
| Unique NCBI taxa in file | **38,737** | Was extrapolating ~500 K across all 3 archives | ✅ order-of-magnitude right for aggregate; isolates alone is 4 × 10⁴ |
| ENVO edges | 97 K (asymmetric: 59 K `→` + 38 K `←`) | 60 K estimated | ✅ close |
| DOID edges | 5,172 | small | ✅ |
| BTO edges | 6,725 | small | ✅ deferred per v1 scope |
| taxon-taxon rows | 3,992 (host associations e.g. `→ NCBITaxon:9606`) | Not listed | ❌ **plan now lists these as skip-in-v1** |
| Score values | Integers `3` / `4` observed in first 100 K rows | Floats + z_score assumed | ❌ **plan now clarifies per-channel score conventions; verify full file during impl** |
| `direct_flag` | 100% TRUE in isolates | Assumed mixed within a file | ❌ **plan now clarifies flag is per-channel discriminator, not per-row** |

**Cost:** 21-second download, 3-second extract, 3.5-minute sort of the pair-type distribution, ~5 min of targeted sampling. Total ~10 min of wall-clock; ~8 GB disk in `/tmp/prego_isolates/`.

**Conclusion:** the plan's overall shape holds; the seven items in the "Status ❌" rows above have been folded in as concrete corrections. **No new blocker discovered.** Ready to proceed to full implementation when someone has 5-6 days.

### Phase 6b — dictionary synonym enrichment (multiplier)

- Load `prego_entities.tsv` into a `{serial: CURIE}` dict for the emitted entity types (`-2` NCBITaxon, `-21`/`-22`/`-23` GO all namespaces, `-27` ENVO, `-26` DOID via xref to MONDO — `-25` BTO skipped per v1 scope). Canary measured **~4 × 10⁴ unique taxa in the isolates channel alone**; literature and environmental will add more. Full-aggregate estimate: **10⁵ order-of-magnitude** across all three channels.
- Stream `prego_names.tsv` (13.9 M rows) row-by-row; for each `(serial, name)` where the serial is in the dict, accumulate `{CURIE: [names...]}`.
- After phase 6a has emitted nodes, second-pass update the `synonym` column with pipe-delimited names — OR do the join in-memory and emit synonyms as the node is first written (single pass; preferred). The accumulator is small: ~10⁵ CURIEs × average ~6 names × ~40 B/name ≈ **~200 MB peak**.
- **Only enrich nodes the associations tables produced** — do NOT ingest the full 2.5 M dictionary as standalone stubs. Prevents the transform from ballooning by ~2 M NCBITaxon rows that duplicate the `ontologies` transform.
- **Deduplicate names** case-insensitively within each entity. **Leave the `name` column untouched by 6b** — it's set by 6a from the CURIE lookup or the association row's preferred label, and PREGO's `prego_preferred.tsv` may or may not agree with the ontology's own canonical label. Put every dictionary name (including PREGO's preferred if it isn't identical to the existing `name`) into `synonym`. No clobbering, all the info stays available for matching.
- **`prego_groups.tsv` (42 M hierarchy rows) is NOT ingested** — the NCBI tree and GO is_a hierarchy are already in the `ontologies` transform; duplicating them here would just produce redundant `subclass_of` edges.
- **`prego_texts.tsv` (43 K GO definitions) is NOT ingested** — go.owl already carries these.

## Phase 7-8 — Verify + test

Gates:
- `poetry run kg transform -s prego` produces non-zero rows.
- `kg-model-review --transform prego` reports **0 ERRORs**.
- `kg-path-review --transform prego` — sweep for self-loops, family-mismatch, orphan-edges.
- Post-merge cardinality check: `NCBITaxon → capable_of` fan-out should have a plausible distribution (long tail, not spike-outliers).
- Unit tests (target ~25):
  - Fixture-in → known node/edge count.
  - Every emitted edge carries `score`, `channel`, `direct_flag`, `primary_knowledge_source`.
  - DOID→MONDO xref path exercises the mapping; DOID with no MONDO xref is silently skipped.
  - Absent optional columns handled without raising.
  - JensenLab type-code table covers `-2 / -21 / -27 / -26 / -25`; unknown codes log-and-skip rather than raise.
  - **6b enrichment:** an emitted `NCBITaxon:` node carries pipe-delimited alternate names from the dictionary in `synonym`; names are deduplicated case-insensitively; the `name` column is NOT touched by 6b (set by 6a from the CURIE lookup).
  - **6b scope:** a fixture serial that has names in `prego_names.tsv` but doesn't appear in any association row is NOT emitted as a standalone node.

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

| Archive | Compressed | Uncompressed | Rows |
|---|---:|---:|---:|
| `annotated_genomes_isolates.tar.gz` | 269 MB (verified) | 8.1 GB (**measured 2026-08-04 canary**) | **42,038,686 (measured)** — dominates as taxon↔GO_MF ~21M unique after dedup |
| `environmental_samples.tar.gz` | 702 MB | ~22 GB (est.) | ~120 M (est.; canary pending) |
| `literature.tar.gz` | 5.4 GB | 19.6 GB (tar-header confirmed) | ~110 M (est.; assuming ~180 B/row typical of tagger output) |

Combined raw: **~280 M association rows**. After filtering to just taxon→(ENVO/GO/DOID/MONDO) shapes and applying merge-time dedup, expect **~10⁸ emitted edges** — an order of magnitude larger than the original `~10⁶` estimate in [`NOVEL_TRANSFORMS.md`](./NOVEL_TRANSFORMS.md); update that dict in the next `novel-transforms` skill refresh.

**Dictionary (Phase 6b):** 278 MB compressed. `prego_names.tsv` has 13.9 M `(serial, synonym)` rows; after filtering to the serials that survive Phase 6a (only entities that appear in the associations, order of magnitude ~10⁵), expect **~10⁶–10⁷ synonym enrichments** distributed across those same nodes. The dictionary-wide average is 5.6 aliases per entity, but the enriched subset skews toward well-known organisms which have *more* aliases than obscure ones — so the per-node synonym count in the enriched subset is likely higher than 5.6. Actual counts to be verified during Phase 6a canary.

### Where the "not downloadable" misread came from

The `prego.hcmr.gr/Downloads` UI page still shows only a placeholder ("we will provide"), unchanged since the paper's publication in early 2022. The paper's Appendix D lists the actual URLs but they're unlinked from the UI. A first-pass check of the site's Downloads tab (which is what the original plan draft did) plausibly reads as "data not yet released" — but the paper is the authoritative reference and the endpoints have been live since ~2021-12-21. Documentation bug, not a data-availability bug.

## Effort estimate

- **~5-6 days** once code starts.
  - **Day 1 (6a canary):** Isolates channel (269 MB) end-to-end through Phase 7 gates.
  - **Day 2-3 (6a build-out):** streaming parser + DOID→MONDO xref path + tests against fixture derived from the canary output.
  - **Day 4 (6a scale-out):** run the two larger archives end-to-end; verify cardinality + path review.
  - **Day 5 (6b):** dictionary join + synonym enrichment pass. Ship 6a to master first (as PR-of-record) if 6b turns out messier than expected; 6b then lands as a follow-up PR.
  - **Day 6:** ship PR + adversarial review.
- **Blocking risk: none.** Data is live and CC-BY.

## Explicitly out-of-scope for v1

- Re-running the text-mining pipeline (weeks of compute + PubMed corpus). Ingesting the pre-computed pair scores is the whole point.
- **BTO tissue nodes** — defer until an issue asks; BTO isn't in KGM's current ontology set.
- **Cross-ontology pairs** (rows where both entities are ontology terms, e.g. GO↔ENVO). PREGO includes some of these; skip for v1 in favor of the taxa-centric edges that match the flagship use case.
- **Sequence-search endpoint** (`prego.hcmr.gr/SequenceSearch`) — separate concern.
- **Score-based edge filtering.** Emit all associations from all three channels; let downstream consumers threshold.
- **Taxon-taxon similarity edges** — orthogonal to the taxa↔environment focus.
- **Dictionary `prego_groups.tsv`** (42 M child-parent rows) — redundant with the NCBI tree + GO is_a hierarchy already in `ontologies`. Ingesting would just duplicate `subclass_of` edges.
- **Dictionary `prego_texts.tsv`** (43 K GO definitions) — redundant with go.owl.
- **Standalone dictionary nodes** — the dictionary has 2.5 M entities; the transform only enriches nodes that already appear in an association row. Ingesting the full dictionary would duplicate the entire NCBITaxon transform's output.
