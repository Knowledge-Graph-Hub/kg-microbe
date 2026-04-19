---
name: chemical-mapping
description: Work with KG-Microbe's unified chemical mapping system (`mappings/unified_chemical_mappings.tsv.gz` and `kg_microbe/utils/chemical_mapping_utils.py`). Use when adding a new mapping source, regenerating the unified file, debugging a missing ChEBI lookup, validating mappings against OLS, or reasoning about which source wins when sources disagree.
---

# KG-Microbe Chemical Mapping

## What this is

KG-Microbe resolves free-text chemical names from many source transforms
(BacDive metabolites, MediaDive ingredients, metatraits, manual curation,
etc.) to canonical **ChEBI** identifiers via a single consolidated
lookup table. All transforms that need "name → ChEBI" go through
`kg_microbe.utils.chemical_mapping_utils`, which reads
`mappings/unified_chemical_mappings.tsv.gz` once per process.

The unified file is built by `scripts/consolidate_chemical_mappings.py`
from multiple source files with a **priority system** — higher-priority
sources override lower-priority ones for `canonical_name`/`formula` and
win tie-breaks during duplicate-name merging.

## Files

| Path | Role |
|---|---|
| `mappings/unified_ingredient_mappings.sssom.tsv.gz` | **Primary mapping product.** Standards-compliant SSSOM mapping set covering xrefs (`skos:exactMatch`) + canonical names + free-text synonyms via synthetic `kgm.name:<slug>` subjects (`skos:exactMatch` / `skos:closeMatch`, justification `semapv:LexicalMatching`). Validated with the `sssom` Python package on every write. |
| `mappings/unified_chemical_mappings.tsv.gz` | **In-process runtime index.** 7-col gzipped TSV consumed by all transforms. Entity-centric (one row per primary CURIE). Needed because plain-string synonyms cannot be represented as SSSOM subjects. Holds CHEBI chemicals **and** non-CHEBI ingredients (FOODON foods, UBERON anatomy, ENVO environments) in a single file. |
| `scripts/dump_unmapped_mediadive_ingredients.py` | Emits a MIM-compatible TSV of MediaDive ingredients still unmapped after the current mappings + `fuzzy_hydrate` retry, for curator review. |
| `mappings/culturebotai_reviewed_ingredients.tsv` | Authoritative reviewed source from CultureBotAI (priority=10). |
| `mappings/ingredient_mappings.sssom.tsv` | Authoritative SSSOM mapping set from the MediaIngredientMech sibling repo (priority=11). |
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

## Schema: `unified_chemical_mappings.tsv.gz`

| Column | Description |
|---|---|
| `id` | Primary key. Any supported ontology CURIE: `CHEBI:<int>` (preferred for chemicals), `FOODON:<int>`, `UBERON:<int>`, `ENVO:<int>`, etc. |
| `category` | Biolink category for the entry (`biolink:ChemicalSubstance`, `biolink:Food`, `biolink:AnatomicalEntity`, `biolink:EnvironmentalFeature`, …). Populated at consolidation time; downstream transforms read it directly instead of deriving category from the CURIE prefix. |
| `canonical_name` | Preferred name. Dominated by the highest-priority source. |
| `formula` | Molecular formula (chemicals only). Higher-priority wins. |
| `synonyms` | Pipe-delimited. Always unioned across all sources. |
| `xrefs` | Pipe-delimited. Union. Includes `cas:*`, `kegg.compound:*`, `pubchem.compound:*`, `MediaIngredientMech:*`, etc. |
| `sources` | Pipe-delimited provenance tags (one per contributing source loader). |

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
1. Seeds from the existing `mappings/unified_chemical_mappings.tsv.gz` (priority inferred per row from source labels).
2. Layers in any still-present legacy source files (absent ones are skipped).
3. Always loads `mappings/culturebotai_reviewed_ingredients.tsv` (priority=10).
4. Enriches from `data/raw/chebi.db` via OAK (labels fill only when no higher-priority name is present; aliases always accumulate).
5. Merges duplicate-name records (highest priority wins).
6. Writes `mappings/unified_chemical_mappings.tsv.gz`.

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

- **Not ChEBI-only anymore**: `unified_chemical_mappings.tsv.gz` and the consolidator now support non-ChEBI primary IDs, including FOODON, UBERON, ENVO, NCIT, `pubchem.compound`, `cas`, `mediadive.ingredient`, and `kgmicrobe.compound`. Some downstream helpers and workflows are still ChEBI-oriented (for example `find_chebi_*` utilities), so callers that assume every row resolves to a ChEBI ID should handle non-ChEBI primary IDs explicitly.
- **CAS RN format**: stored as `cas:<dash-separated>` xrefs (e.g. `cas:7647-14-5`). Consumers must include the `cas:` prefix when calling `find_chebi_by_xref`.
- **Priority inference on baseline reseed**: when `load_existing_unified` re-ingests the current `.tsv.gz`, the priority field is reconstructed from the `sources` column via prefix matching. A brand-new priority tier requires updating `priority_for` in that loader as well.
- **ChEBI enrichment cost**: `enrich_with_chebi_synonyms` iterates every entry through an OAK adapter; it is the slowest step (~165k entries × label + aliases). If `data/raw/chebi.db` is absent, the enrichment is silently skipped.

## Tests

`tests/test_chemical_mapping_utils.py` covers: `normalize_name` (including `strip_stereochemistry`), load/caching, `find_chebi_by_name` (canonical, synonyms, case, punctuation, fuzzy), `find_chebi_by_formula`, `find_chebi_by_xref`, `get_canonical_name/synonyms/xrefs/formula`, `ChemicalMappingLoader`, and negative-cache bounded/reload behavior.

Run:
```bash
poetry run pytest tests/test_chemical_mapping_utils.py -v
```
