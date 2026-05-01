---
name: chemical-mapping
description: Work with KG-Microbe's unified chemical mapping system (`mappings/unified_ingredient_mappings.sssom.tsv.gz` and `kg_microbe/utils/chemical_mapping_utils.py`). Use when adding a new mapping source, regenerating the unified file, debugging a missing ChEBI lookup, validating mappings against OLS, or reasoning about which source wins when sources disagree.
---

# KG-Microbe Chemical Mapping

## What this is

KG-Microbe resolves free-text chemical names from many source transforms
(BacDive metabolites, MediaDive ingredients, metatraits, manual curation,
etc.) to canonical **ChEBI** identifiers via a single consolidated
mapping set. All transforms that need "name → ChEBI" go through
`kg_microbe.utils.chemical_mapping_utils`, which reads
`mappings/unified_ingredient_mappings.sssom.tsv.gz` once per process
and reconstructs the in-memory name/xref/formula/category indices from
the SSSOM rows. The unified SSSOM is the **single source of truth** for
chemical mappings; legacy entity-centric TSV outputs have been retired.

The unified file is built by `scripts/consolidate_chemical_mappings.py`
from multiple source files with a **priority system** — higher-priority
sources override lower-priority ones for `canonical_name`/`formula` and
win tie-breaks during duplicate-name merging.

## Files

| Path | Role |
|---|---|
| `mappings/unified_ingredient_mappings.sssom.tsv.gz` | **Single source of truth.** Standards-compliant SSSOM mapping set covering xrefs (`skos:exactMatch`) + canonical names + free-text synonyms via synthetic `kgm.name:<slug>` subjects (`skos:exactMatch` / `skos:closeMatch`, justification `semapv:LexicalMatching`). Holds CHEBI chemicals **and** non-CHEBI ingredients (FOODON foods, UBERON anatomy, ENVO environments). Validated with the `sssom` Python package on every write. |
| `scripts/dump_unmapped_mediadive_ingredients.py` | Emits a MIM-compatible TSV of MediaDive ingredients still unmapped after the current mappings + `fuzzy_hydrate` retry, for curator review. |
| `mappings/culturebotai_reviewed_ingredients.tsv` | Authoritative reviewed source from CultureBotAI (priority=10). |
| `mappings/ingredient_mappings.sssom.tsv` | **Vendored copy** of the MediaIngredientMech SSSOM (priority=11). Auto-refreshed from the sibling repo on every consolidator run — never edit this file directly; edit upstream in MIM and let `sync_mim_sssom` overwrite it. |
| `../MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv` | **Source of truth** for MIM mappings. The MediaIngredientMech repo (https://github.com/KG-Hub/MediaIngredientMech) is expected to be checked out as a sibling of `kg-microbe`. The consolidator wins-from-sibling on content divergence. |
| `mappings/chemical_mappings.tsv` | Legacy KEGG/BacDive primary mappings (may be absent). |
| `mappings/README.md` | Schema + regeneration instructions. |
| `scripts/consolidate_chemical_mappings.py` | Consolidator (run to rebuild). |
| `scripts/migrate_chemical_mappings.py` | One-time migration helper. |
| `kg_microbe/utils/chemical_mapping_utils.py` | Reader API + in-memory indices. |
| `tests/test_chemical_mapping_utils.py` | Reader unit tests. |
| `mappings/validate_manual_mappings.py` | Validates manual rows against OLS4. |
| `data/raw/compound_mappings_strict.tsv` | MediaDive ingredient source (may be absent). |
| `data/raw/compound_mappings_strict_hydrate.tsv` | Hydrate source (may be absent). |
| `kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv` | ChEBI xrefs from ontology transform (may be absent). |
| `kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv` | Expert annotation source (may be absent). |
| `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` | BacDive metabolite source (may be absent). |

## Schema: SSSOM rows in `unified_ingredient_mappings.sssom.tsv.gz`

Per-entity attributes are reconstructed at read time by grouping rows on
`object_id`. Three row shapes (emitted by `export_unified_sssom`):

| Row shape | `subject_id` | `comment` | Carries |
|---|---|---|---|
| canonical name | `kgm.name:<slug>` | `canonical_name` | the entity's preferred label via `subject_label` / `object_label` |
| synonym | `kgm.name:<slug>` | `synonym` | one synonym per row via `subject_label` |
| xref | plain CURIE (e.g. `cas:7647-14-5`) | _empty_ | an equivalent identifier mapped to the entity |
| attribute carrier | _equal to_ `object_id` | _empty_ | extension columns only (when the entity has no other rows) |

Extension columns ride on every row as per-entity attributes:

| Column | Description |
|---|---|
| `object_id` | Primary key — any supported ontology CURIE: `CHEBI:<int>`, `FOODON:<int>`, `UBERON:<int>`, `ENVO:<int>`, `pubchem.compound:<int>`, `cas:<dash-separated>`, etc. |
| `object_label` | The entity's canonical name. |
| `object_formula` | Molecular formula (chemicals only). Higher-priority source wins. |
| `object_category` | Biolink category (`biolink:ChemicalSubstance`, `biolink:Food`, `biolink:AnatomicalEntity`, `biolink:EnvironmentalFeature`, …). |
| `predicate_id` | `skos:exactMatch` (default) or `skos:closeMatch` / `narrowMatch` / `broadMatch` for asymmetric matches. |
| `mapping_justification` | `semapv:LexicalMatching` for synthetic name rows; `semapv:ManualMappingCuration` for curated xrefs. |
| `source` | Pipe-delimited provenance tags (one per contributing source loader). |

## Priority system

| Priority | Source | Notes |
|---|---|---|
| 11 | `mediaingredientmech_reviewed` | Expert-curated MIM → ontology SSSOM (`mappings/ingredient_mappings.sssom.tsv`). **Authoritative.** MIM is the canonical-naming source: symmetric matches (`skos:exactMatch`, `skos:closeMatch`) overwrite the canonical name with MIM's `subject_label`; asymmetric (`narrowMatch`/`broadMatch`) keep the ontology label canonical and add the MIM term as a synonym. MIM `subject_id` is emitted as xref. |
| 10 | `culturebotai_reviewed` | Evidence-based, manually reviewed media-ingredient mappings from CultureBotAI. **Authoritative.** |
| 5 | `manual_annotation*`, `manual_corrections*`, `metatraits_manual*`, `metatraits_chemical_synonyms*`, `metatraits_special_chemicals*` | Expert in-repo curation. |
| 2 | `chebi_xrefs` | ChEBI ontology's own xref table. Authoritative for xrefs but not preferred for names. |
| 1 | Everything else (BacDive, MediaDive, KEGG, etc.) | Automatic mappings. |

When two sources disagree on `canonical_name` or `formula` for the same
`id`, the higher priority wins outright. Within the same priority band,
the first non-empty value is kept (stable). Synonyms, xrefs, and sources
always accumulate (set union).

When duplicate `canonical_name`s point to different CHEBI IDs, the
merger picks the entry with the highest priority; ties break by lowest
ChEBI ID. Non-CHEBI categories are ontologically disjoint even when
labels collide, so duplicate-name merging is CHEBI-only.

## Reader API

Primary surface in `kg_microbe/utils/chemical_mapping_utils.py`:

```python
from kg_microbe.utils.chemical_mapping_utils import (
    find_chebi_by_name, find_chebi_by_formula, find_chebi_by_xref,
    get_canonical_name, get_category, get_synonyms, get_xrefs, get_formula,
    ChemicalMappingLoader,
)

# find_chebi_by_name returns *any* supported CURIE, not just CHEBI. Name is
# retained for API stability; non-CHEBI matches (FOODON/UBERON/ENVO) come
# from the same unified file.
find_chebi_by_name("NaCl")                       # → "CHEBI:26710"
find_chebi_by_name("Yeast extract")              # → "FOODON:00002441"
find_chebi_by_name("Defibrinated sheep blood")   # → "UBERON:0000178"
find_chebi_by_name("(R)-lactate", fuzzy_stereochemistry=True)
find_chebi_by_name("MgCl2 x 6 H2O", fuzzy_hydrate=True)  # strips trailing hydrate suffix
find_chebi_by_name("glucose", synonyms=False)    # canonical-only index (O(1))
find_chebi_by_formula("H2O")                     # → ["CHEBI:15377", ...]
find_chebi_by_xref("cas:7647-14-5")              # → "CHEBI:26710"

# Read the biolink category straight from the data column. This replaces
# prefix-based category routing in downstream transforms.
get_category("CHEBI:15377")     # → "biolink:ChemicalSubstance"
get_category("FOODON:00002441") # → "biolink:Food"
```

Performance notes:
- First call loads the file and builds 5 in-memory indices: `_NAME_INDEX` (canonical+synonyms), `_CANONICAL_NAME_INDEX`, `_FORMULA_INDEX`, `_XREF_INDEX`, `_CATEGORY_INDEX`.
- A bounded LRU-style `_NEGATIVE_LOOKUP_CACHE` (default max 100k) short-circuits repeated misses and is cleared on reload.
- All name lookups are O(1). `get_canonical_name` / `get_synonyms` / `get_xrefs` / `get_formula` use `.loc` so they are also O(1).

## Common tasks

### Regenerate the unified file

```bash
poetry run python scripts/consolidate_chemical_mappings.py
```

Behaviour:
1. Seeds from the existing `mappings/unified_ingredient_mappings.sssom.tsv.gz` (the single source of truth; priority inferred per row from source labels).
2. Layers in any still-present legacy source files (absent ones are skipped).
3. Always loads `mappings/culturebotai_reviewed_ingredients.tsv` (priority=10).
4. Calls `sync_mim_sssom` to refresh `mappings/ingredient_mappings.sssom.tsv` from the MIM sibling repo at `../MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv` (sibling wins on divergence; vendored is a cache, not a fork), then loads it (priority=11).
5. Enriches from `data/raw/chebi.db` via OAK (labels fill only when no higher-priority name is present; aliases always accumulate).
6. Harvests CHEBI xref labels via OAK into owning-record synonyms.
7. Propagates names across equivalent-CURIE records via xrefs (symmetric snapshot; no record merge).
8. Resolves name-index conflicts by source priority (no cross-CURIE merge pass).
9. Writes `mappings/unified_ingredient_mappings.sssom.tsv.gz` (validated round-trip via the `sssom` package).

### MIM SSSOM source-of-truth contract

The MediaIngredientMech repo is the **authoritative** source for ingredient
mappings (priority=11). Its SSSOM lives at
`../MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv` (sibling of
the kg-microbe repo). The vendored copy at
`mappings/ingredient_mappings.sssom.tsv` is a cache, refreshed on every
consolidator run by `sync_mim_sssom` (see `scripts/consolidate_chemical_mappings.py:182`):

| Sibling | Vendored | Sync action |
|---|---|---|
| present, content matches | present | no-op (`MIM SSSOM up-to-date`) |
| present, content differs | present | overwrite vendored (sibling wins) |
| present | absent | copy sibling → vendored |
| absent | present | warn, continue with stale vendored copy |
| absent | absent | **fatal** — script aborts with clone instructions |

Rules:
- **Never edit the vendored copy directly** — your changes will be silently
  overwritten by the next consolidator run.
- To change a mapping: edit `../MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`,
  open a PR against MediaIngredientMech, and once it merges, re-run the consolidator.
- New contributors must clone MIM as a sibling:
  ```bash
  cd $(dirname $(pwd))   # parent of kg-microbe
  git clone https://github.com/KG-Hub/MediaIngredientMech.git
  ```

### Add a new mapping source

1. Put the source file under `mappings/` (or `data/raw/` if large).
2. Add a `load_<source>(filepath)` method to `ChemicalMappingConsolidator` in `scripts/consolidate_chemical_mappings.py`. Call `self.add_chemical(id=..., canonical_name=..., formula=..., synonyms=[...], xrefs=[...], source="<tag>", priority=<1|2|5|10>)`. The consolidator infers `category` from the CURIE prefix and writes it to the data column.
3. Invoke the loader in `main()`.
4. Document the source + priority in `mappings/README.md` and in the priority table in this skill.
5. Regenerate and commit both the code and the regenerated `.tsv.gz`.
6. If the source should be inferable during baseline seeding, add its tag prefix to `priority_for` in `load_existing_unified`.

### Validate manual mappings against OLS

```bash
poetry run python mappings/validate_manual_mappings.py
```

Checks that every manually-curated ChEBI ID (entries without `chebi_xrefs`, and entries from `metatraits_chemical_synonyms` / `metatraits_special_chemicals`) still matches OLS4's label and that no synonym is spurious. Output: `mappings/manual_mapping_audit_report.tsv`.

### Debug a missing lookup

```python
from kg_microbe.utils.chemical_mapping_utils import (
    find_chebi_by_name, load_unified_mappings, normalize_name,
)
df = load_unified_mappings()                           # 164k+ rows
print(normalize_name("Yeast Extract"))                 # → "yeast extract"
print(df[df["synonyms"].str.contains("yeast extract", case=False, na=False)][["id","canonical_name","synonyms","sources"]].head())
```

If a name should map but doesn't:
1. Normalize it (`normalize_name`) and grep the unified file.
2. If no row matches, check whether the source file contains it — if yes, the source file isn't loaded in `main()`.
3. Consider `fuzzy_stereochemistry=True` for names prefixed with `(R)-`, `(S)-`, `D-`, `L-`, `(+)-`, `(-)-`.
4. If the name is legitimate but absent everywhere, add it to `mappings/culturebotai_reviewed_ingredients.tsv` (or another priority-5+ source) and regenerate.

## Known limitations

- **Not ChEBI-only anymore**: the unified SSSOM and the consolidator support non-ChEBI primary IDs, including FOODON, UBERON, ENVO, NCIT, `pubchem.compound`, `cas`, `mediadive.ingredient`, and `kgmicrobe.compound`. Some downstream helpers and workflows are still ChEBI-oriented (for example `find_chebi_*` utilities), so callers that assume every row resolves to a ChEBI ID should handle non-ChEBI primary IDs explicitly.
- **CAS RN format**: stored as `cas:<dash-separated>` xrefs (e.g. `cas:7647-14-5`). Consumers must include the `cas:` prefix when calling `find_chebi_by_xref`.
- **Priority inference on baseline reseed**: when `load_existing_unified` re-ingests the current `.tsv.gz`, the priority field is reconstructed from the `sources` column via prefix matching. A brand-new priority tier requires updating `priority_for` in that loader as well.
- **ChEBI enrichment cost**: `enrich_with_chebi_synonyms` iterates every entry through an OAK adapter; it is the slowest step (~165k entries × label + aliases). If `data/raw/chebi.db` is absent, the enrichment is silently skipped.

## Tests

`tests/test_chemical_mapping_utils.py` covers: `normalize_name` (including `strip_stereochemistry`), load/caching, `find_chebi_by_name` (canonical, synonyms, case, punctuation, fuzzy), `find_chebi_by_formula`, `find_chebi_by_xref`, `get_canonical_name/synonyms/xrefs/formula`, `ChemicalMappingLoader`, and negative-cache bounded/reload behavior.

Run:
```bash
poetry run pytest tests/test_chemical_mapping_utils.py -v
```
