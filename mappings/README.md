# Chemical Mappings

This directory contains unified chemical mapping resources for KG-Microbe.

## Unified Chemical Mappings

The consolidator now writes two complementary artifacts from the same run:

| File | Role |
|---|---|
| `unified_ingredient_mappings.sssom.tsv.gz` | **Primary, standards-compliant mapping product.** Row types: (1) xref-CURIE → primary-CURIE (`skos:exactMatch`); (2) canonical-name → primary-CURIE via `kgm.name:<slug>` (`skos:exactMatch`, `semapv:LexicalMatching`); (3) free-text synonym → primary-CURIE via `kgm.name:<slug>` (`skos:closeMatch`, `semapv:LexicalMatching`). Validated with the `sssom` Python package on every write (LinkML JSON-schema + `check_all_prefixes_in_curie_map`). |
| `unified_chemical_mappings.tsv.gz` | **In-process runtime index** used by transforms via `kg_microbe.utils.chemical_mapping_utils`. Entity-centric: one row per primary CURIE with accumulated canonical name, formula, synonyms, and xrefs. Retains the per-entity attributes (formula, biolink category) that SSSOM cannot express (SSSOM covers mappings, not attributes). |

The synonym rows use a synthetic `kgm.name:<slug>` subject namespace so that free-text names have a CURIE subject (SSSOM requires this). Slugs are deterministic via `normalize_name` with spaces → `_`. Both files are rebuilt by the same `scripts/consolidate_chemical_mappings.py` run and cover CHEBI chemicals plus non-CHEBI ingredients (FOODON foods, UBERON anatomy, ENVO environments).

### File Structure

| Column | Description |
|--------|-------------|
| `id` | Primary key — any supported ontology CURIE. `CHEBI:*` is preferred for chemicals; `FOODON:*`, `UBERON:*`, `ENVO:*` are used for foods, anatomy, and environmental substrates. |
| `category` | Biolink category stored as a data column so downstream transforms read it instead of deriving it from the CURIE prefix. Values: `biolink:ChemicalSubstance`, `biolink:Food`, `biolink:AnatomicalEntity`, `biolink:EnvironmentalFeature`, etc. |
| `canonical_name` | Preferred name; wins are decided by the **priority system** below |
| `formula` | Chemical formula when available (chemicals only); priority-gated |
| `synonyms` | Pipe-delimited union across all sources |
| `xrefs` | Pipe-delimited union — `cas:*`, `kegg.compound:*`, `pubchem.compound:*`, `MediaIngredientMech:*`, etc. |
| `sources` | Pipe-delimited provenance tags (one per contributing loader) |

### Priority System

Multiple sources may assert a name or formula for the same `id`. Higher priority wins outright; within the same priority band, the first-loaded non-empty value is retained. Synonyms, xrefs, and sources **always** accumulate (set union).

| Priority | Source tag(s) | Meaning |
|---|---|---|
| 11 | `mediaingredientmech_reviewed` | Expert-curated MIM → ontology SSSOM from the MediaIngredientMech sibling repo. MIM is the authoritative canonical-naming source: for symmetric matches (`skos:exactMatch`, `skos:closeMatch`) the MIM `subject_label` becomes the canonical name; for `skos:narrowMatch`/`broadMatch` the ontology label stays canonical and the MIM term becomes a synonym. MIM `subject_id` emitted as xref. |
| 10 | `culturebotai_reviewed` | Evidence-based, manually reviewed media-ingredient mappings from the CultureBotAI project. |
| 5 | `manual_annotation*`, `manual_corrections*`, `metatraits_manual*`, `metatraits_chemical_synonyms*`, `metatraits_special_chemicals*` | Expert in-repo curation. |
| 2 | `chebi_xrefs` | ChEBI ontology's own xref table. Authoritative for xrefs but not preferred for names. |
| 1 | Everything else (BacDive, MediaDive, KEGG, etc.) | Automatic mappings. |

Duplicate-name resolution (when two different ChEBI IDs carry the same normalized name): highest priority wins; ties break by lowest ChEBI ID. Non-CHEBI categories are ontologically disjoint from CHEBI and from each other, so duplicate-name merging is skipped for them — a FOODON food and a CHEBI chemical with the same label remain distinct rows.

### Source Files Consolidated

| # | Source | Priority | Present on disk? | Notes |
|---|---|---|---|---|
| 1 | `mappings/chemical_mappings.tsv` | 1 | removed (seeded from unified baseline) | Legacy KEGG/BacDive primary mappings. |
| 2 | `data/raw/compound_mappings_strict.tsv` | 1 | present | MediaDive ingredient compound table. |
| 3 | `data/raw/compound_mappings_strict_hydrate.tsv` | 1 | present | Hydrate/anhydrous cross-links. |
| 4 | `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` | 1 | present | BacDive antibiotic/metabolite mappings (~197). |
| 5 | `kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv` | 2 | removed (seeded from unified baseline) | ChEBI xref table (CAS, KEGG, PubChem, …). |
| 6 | `kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv` | 5 | present | Trait-dataset expert corrections. |
| 7 | `mappings/culturebotai_reviewed_ingredients.tsv` | 10 | present | **Authoritative.** CultureBotAI reviewed ingredients. |
| 8 | `mappings/ingredient_mappings.sssom.tsv` | 11 | present | **Authoritative.** MediaIngredientMech SSSOM mapping set (sibling repo export of `MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`). Contains 1,090 MIM→ontology rows with predicate-typed matches (exactMatch / closeMatch / narrowMatch). |

Missing-legacy handling: when a priority-1/2/5 source file is absent (items 1 & 5 above), the consolidator silently skips its loader because the corresponding rows are already present in the existing `unified_chemical_mappings.tsv.gz`. The `load_existing_unified()` step re-ingests that baseline with priority inferred from the `sources` column.

### Regenerating

```bash
poetry run python scripts/consolidate_chemical_mappings.py
```

Pipeline order:
1. Seed from the existing `mappings/unified_chemical_mappings.tsv.gz` (priority reconstructed per row from source labels).
2. Layer in any still-present legacy inputs (absent ones are skipped).
3. Load `mappings/culturebotai_reviewed_ingredients.tsv` (priority=10).
4. Load `mappings/ingredient_mappings.sssom.tsv` (priority=11) — parsed and validated with the `sssom` Python package before any row is ingested.
5. Enrich from `data/raw/chebi.db` via OAK (labels only fill when no higher-priority name already exists; aliases always accumulate).
6. Merge duplicate-name records (highest priority wins).
7. Write `unified_chemical_mappings.tsv.gz` (runtime index).
8. Write `unified_ingredient_mappings.sssom.tsv.gz` and round-trip-validate it with the `sssom` package.

### Usage Examples

```bash
# Find an ingredient by name
gunzip -c mappings/unified_chemical_mappings.tsv.gz | grep -i "glucose"

# All synonyms for an id
gunzip -c mappings/unified_chemical_mappings.tsv.gz | awk -F'\t' '$1=="CHEBI:42758" {print $5}'

# Ingredients carrying the MediaIngredientMech tag
gunzip -c mappings/unified_chemical_mappings.tsv.gz | grep mediaingredientmech_reviewed | head

# All FOODON foods
gunzip -c mappings/unified_chemical_mappings.tsv.gz | awk -F'\t' '$1 ~ /^FOODON:/'
```

Prefer the Python reader API (`kg_microbe.utils.chemical_mapping_utils.find_chebi_by_name`, `find_chebi_by_xref`, `find_chebi_by_formula`, `get_canonical_name`, `get_category`) inside transforms — it loads the file once per process and serves O(1) lookups. `find_chebi_by_name` is a legacy name; it returns any supported CURIE, including FOODON / UBERON / ENVO.

### Known Limitations

- **CAS format.** Stored as `cas:<dash-separated>` xrefs (e.g. `cas:7647-14-5`). Consumers must include the `cas:` prefix.
- **MIM schema** carries no CAS RN column, so CAS coverage for MIM-only ChEBI IDs comes from the ChEBI xref table (priority=2), not MIM itself.
- **Priority inference on baseline reseed**: when `load_existing_unified` re-ingests the current `.tsv.gz`, the priority field is reconstructed from source-label prefixes. A brand-new priority tier also requires updating `priority_for` inside that loader.

### Validation

```bash
poetry run python mappings/validate_manual_mappings.py
```

Checks every manually curated ChEBI ID (priority-5 and priority-10 rows that are not `chebi_xrefs`) against OLS4 labels. Output: `mappings/manual_mapping_audit_report.tsv`.

### Skill

A Claude Code skill (`.claude/skills/chemical-mapping/SKILL.md`) documents the full process — sources, priority system, reader API, common debugging tasks, and regeneration — and is invoked automatically when the relevant files are touched.

## Maintenance

Last updated: 2026-04-18

Maintainer: KG-Microbe team

For mapping errors or questions, open an issue on the KG-Microbe GitHub repository.
