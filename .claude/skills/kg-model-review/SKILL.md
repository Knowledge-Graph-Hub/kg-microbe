---
name: kg-model-review
description: Knowledge modeling review of KG-Microbe transforms and merged KG for alignment with METPO, Biolink Model, and KGX specification. Use when auditing transform output quality, validating categories/predicates, checking CURIE prefix registration, or preparing a release.
---

# KG-Microbe Knowledge Modeling Review

## Purpose

Perform a systematic review of KG-Microbe transform outputs and/or the merged KG to assess alignment with:

1. **KGX specification** — required columns, data types, CURIE format
2. **Biolink Model** — valid `category` values, valid `predicate` values, subject/object category constraints per predicate
3. **METPO** — correct use of METPO predicates and class CURIEs, consistency with METPO ontology semantics
4. **Prefix registration** — all CURIE prefixes present in `kg_microbe/transform_utils/custom_curies.yaml` or a standard prefix map

## Instructions

When this skill is invoked, run `kg_model_review.py` with the specified scope and report findings. Always summarize violations by severity (ERROR / WARNING / INFO) and by transform source.

### Steps

1. **Identify scope** from user args (default: all transforms + merged)
2. **Run the review script**: `poetry run python .claude/skills/kg-model-review/kg_model_review.py [args]`
3. **Report findings** grouped by:
   - Transform name
   - Check category (KGX / Biolink / METPO / Prefix)
   - Severity (ERROR / WARNING / INFO)
4. **Highlight** any systematic issues that suggest a transform-level fix is needed

### What Is Checked

#### KGX Format (nodes.tsv)
- Required columns present: `id`, `category`, `name`
- `id` is a valid CURIE (`prefix:local`)
- `category` is not empty
- No duplicate `id` values within a single transform

#### KGX Format (edges.tsv)
- Required columns present: `subject`, `predicate`, `object`, `relation`
- `subject`, `object` are valid CURIEs
- `predicate` starts with `biolink:` or is a known METPO predicate mapped to biolink
- `relation` is a RO or METPO term CURIE

#### Biolink Model Alignment

**Reference data source**: `bmt` (Biolink Model Toolkit) loads the authoritative
published biolink-model YAML at runtime. The skill prints the loaded version
(e.g. `Biolink Model 4.2.2 loaded (154 categories, 469 predicates)`) so you can
see what reference data you validated against.

On top of `bmt`, the skill layers a small `KGMICROBE_EXTENSION_CATEGORIES` /
`KGMICROBE_EXTENSION_PREDICATES` whitelist for:
- KG-Microbe native extensions (e.g. `biolink:GrowthMedium`)
- Deprecated upstream classes we still emit intentionally (e.g.
  `biolink:ChemicalSubstance` as the CHEBI normalization target,
  `biolink:Macromolecule` from OAK output)

If `bmt` is unavailable, the skill falls back to a minimal curated set.

Partial list of recognized categories (full list comes from `bmt`):
```
biolink:OrganismTaxon
biolink:ChemicalEntity
biolink:ChemicalSubstance
biolink:SmallMolecule
biolink:MolecularMixture
biolink:ComplexMolecularMixture
biolink:Food
biolink:MacromolecularMachineMixin
biolink:Protein
biolink:Gene
biolink:MolecularActivity
biolink:BiologicalProcess
biolink:CellularComponent
biolink:PhenotypicQuality
biolink:Attribute
biolink:NamedThing
biolink:GrossAnatomicalStructure
biolink:AnatomicalEntity
biolink:EnvironmentalProcess
biolink:PathologicalProcess
biolink:Disease
biolink:GrowthMedium  (KG-Microbe extension)
```

Valid predicates (flag anything not in this list):
```
biolink:has_phenotype
biolink:capable_of
biolink:produces
biolink:consumes
biolink:located_in
biolink:location_of
biolink:has_part
biolink:subclass_of
biolink:related_to
biolink:associated_with
biolink:enabled_by
biolink:enables
biolink:has_chemical_role
biolink:has_input
biolink:has_output
biolink:occurs_in
biolink:associated_with_resistance_to
biolink:associated_with_sensitivity_to
biolink:related_to_at_instance_level
biolink:contains_process
```

#### METPO Alignment
- METPO class CURIEs used as `object` must exist in `data/transformed/ontologies/nodes.tsv` (prefix `METPO:`)
- METPO predicate CURIEs (METPO:20xxxxx) must be in the known predicate map (`METPO_TO_BIOLINK_PREDICATE` in `metatraits.py`)
- `relation` column for METPO-predicated edges must use an RO term, not repeat the biolink predicate

#### CURIE Prefix Registration
- Extract all unique prefixes from `id`, `subject`, `object`, `relation` columns
- Cross-reference against:
  - `kg_microbe/transform_utils/custom_curies.yaml`
  - Standard known prefixes: `NCBITaxon`, `CHEBI`, `GO`, `EC`, `RO`, `METPO`, `biolink`, `FOODON`, `UBERON`, `HP`, `MONDO`, `ENVO`, `infores`, `semapv`, `KGM`
- Flag any prefix not registered

#### Mapping files (curation TSVs)

Run with `--mappings` (in addition to a transform/merged scope) or
`--mappings-only` (just the curation TSVs) to validate every curation artifact
KG-Microbe ships and consumes. Four file groups are checked:

| Group | Example files | Schema |
|---|---|---|
| A — canonical | `kg_microbe/transform_utils/metatraits/mappings/{chemical,enzyme,metpo_alias,pathway,phenotype}_mappings.tsv` | 12-column canonical (`subject_label`, `object_id`, `predicate_id`, `mapping_justification`, `confidence`, …) |
| B — bespoke | `enzyme_name_to_go.tsv`, `special_chemical_mappings.tsv` | per-file expected columns |
| C — queues / audit / proposals | `mappings/mediadive_unmapped_ingredients_to_curate.tsv`, `mappings/culturebotai_reviewed_ingredients.tsv`, METPO proposal TSVs | status counts + sanity |
| D — SSSOM | `mappings/ingredient_mappings.sssom.tsv` | YAML metadata block + SSSOM required columns |

Per-row checks include: CURIE format on every `_id` column; `predicate_id`
restricted to the `skos:` namespace; `mapping_justification` restricted to
`semapv:`; `confidence` ∈ {high, medium, low}; deprecated biolink target
detection; METPO refs that don't exist in the ontology output; ontology IDs
(CHEBI/GO/EC/UBERON/ENVO/HP/MONDO/PATO/PR/CL/FOODON/NCBITaxon/OMP) that don't
resolve in `data/transformed/ontologies/*_nodes.tsv`.

Cross-file checks:
- Same `subject_label` mapped to conflicting `object_id` across canonical files

**Curation upgrade report.** When `--mappings` (or `--mappings-only`) is
specified, a markdown "Curation upgrade report" is appended to the artifact.
It summarises:
1. Top unmapped MediaDive ingredients by occurrence (drives MIM/CultureBotAI
   curation priority).
2. Cross-file mapping conflicts.
3. Object IDs that don't resolve in the ontologies output.
4. Low-confidence canonical rows.
5. Prefix normalization candidates (e.g. `PUBCHEM.COMPOUND` → `pubchem.compound`).
6. CultureBotAI ingredient review queue status counts.

This section is what you hand to the upstream curation repos
(`CultureBotAI`, `MIM`, `CultureBotHT`) to drive new mappings.

## Usage

### Review all transforms
```
/kg-model-review
```

### Review specific transform
```
/kg-model-review --transform metatraits
```

### Review merged KG only
```
/kg-model-review --merged
```

### Review mapping files only (no transforms)
```
/kg-model-review --mappings-only --format md
```

### Combined: merged KG plus mapping files
```
/kg-model-review --merged --mappings --format md
```

### Verbose output with example violations
```
/kg-model-review --transform bacdive --verbose
```

### Output as markdown report
```
/kg-model-review --format md
```

## Options

- `--transform NAME` — review specific transform output in `data/transformed/NAME/`
- `--merged` — review `data/merged/` instead of individual transforms
- `--mappings` — additionally review curation TSVs (canonical, bespoke, queues, SSSOM) and append a curation upgrade report
- `--mappings-only` — review ONLY the curation TSVs (skip transforms/merged)
- `--format {text,md,json}` — output format (default: text)
- `--verbose` — show up to 5 example violating rows per check
- `--max-rows N` — limit rows sampled per file (default: 100000; use 0 for all)
- `--strict-kgx` — additionally run `kgx.validator.Validator` for authoritative
  KGX-spec checking (row-level property types, edge `id` requirement, biolink
  JSON-LD CURIE context). Off by default because it surfaces deviations we
  accept by design (e.g. KG-Microbe prefixes not in biolink's JSON-LD context,
  edges without `id` column). Use before a release to see the full gap list.

## Output Format

```
=== KG-Microbe Knowledge Modeling Review ===
Date: 2026-04-14
Scope: all transforms

Transform: metatraits
  nodes.tsv  (4,905,811 rows sampled: 100,000)
    [KGX]     ✅ Required columns present
    [KGX]     ✅ No duplicate IDs in sample
    [Biolink] ⚠️  WARNING: 3 unknown categories: biolink:ChemicalSubstance (deprecated → use biolink:SmallMolecule)
    [Prefix]  ✅ All prefixes registered
  edges.tsv  (544,482,259 rows sampled: 100,000)
    [KGX]     ✅ Required columns present
    [Biolink] ✅ All predicates valid
    [METPO]   ⚠️  WARNING: 12 edges use biolink predicate in relation column
    [Prefix]  ✅ All prefixes registered

Transform: bacdive
  ...

---
Summary
  Transforms reviewed: 12
  Total ERRORs:   0
  Total WARNINGs: 47
  Total INFOs:    12
```

## Severity Definitions

| Severity | Meaning |
|----------|---------|
| ERROR | Violates KGX or Biolink spec; will cause merge/load failures |
| WARNING | Deviation from best practice; should be fixed before release |
| INFO | Informational observation; no action required |

## Implementation

See `kg_model_review.py` for the review logic.
