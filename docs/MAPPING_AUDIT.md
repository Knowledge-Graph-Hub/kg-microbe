# KG-Microbe mapping audit + curation plan

Date: 2026-05-03

## TL;DR

The repo has 19 curation TSV/SSSOM files split across two directories with
five distinct schema shapes, plus 11 inline hardcoded METPO/RO CURIEs in
`bacdive.py` and a 504-line dead YAML (`translation_table.yaml`). The
auto-audit script reports "100% data-driven" but misses everything that
isn't a top-level dict literal.

A consolidation pass would:

1. Move 11 inline `bacdive.py` mappings into a new `bacdive_field_to_metpo.tsv`.
2. Delete `translation_table.yaml` and the 4 stray/archive files.
3. Standardise non-canonical-schema curation files onto the 12-column SSSOM-shape header.
4. Promote `mappings/` (repo root) as the only canonical curation hub; deprecate the per-transform `metatraits/mappings/` location.

## Current inventory

### Repo-root `mappings/` (the canonical curation hub)

| File | Schema | Entries | Role |
|---|---|---|---|
| `kgmicrobe_unified_entity_mappings.sssom.tsv.gz` | true SSSOM (13-col + extensions) | **595,043** | Single source of truth for chemicals/foods/anatomy/environments — built by `scripts/consolidate_chemical_mappings.py` from MIM + CultureBotAI + per-transform sources |
| `ingredient_mappings.sssom.tsv` | true SSSOM (13-col) | 2,052 | Vendored cache of MIM (`MediaIngredientMech`) sibling repo. Auto-refreshed on every consolidator run; never edit directly |
| `culturebotai_reviewed_ingredients.tsv` | bespoke 9-col | 3,853 | Authoritative reviewed-ingredient mappings from CultureBotAI |
| `isolation_source_to_ontology.tsv` | canonical 12-col SSSOM-shape | 358 | BacDive isolation-source label → ontology CURIE; consumed by `isolation_source_mapping_utils.load_isolation_source_mappings()` |
| `manual_mapping_audit_report.tsv` | bespoke 8-col | 299 | **Generated artifact** by `validate_manual_mappings.py` — should not be edited |
| `mediadive_unmapped_ingredients_to_curate.tsv` | bespoke 4-col | 308 | **Curation queue** for MediaDive ingredients still unmapped after consolidator run |
| `kgmicrobe_proposal_placeholders.tsv` | bespoke 5-col | 27 | Registry of `kgmicrobe.*:*` placeholders for proposed-but-unminted METPO terms |
| `metpo_proposal_categorical.tsv` | bespoke 8-col | 37 | New METPO term proposals (categorical) — written by `scripts/extract_metpo_proposals.py`, submitted upstream |
| `metpo_proposal_quantitative.tsv` | bespoke 8-col | 9 | Same, quantitative properties |
| `metpo_proposal_classes_robot.tsv` | ROBOT 2-row template | 44 | ROBOT-shaped class proposal for upstream submission |
| `metpo_proposal_properties_robot.tsv` | ROBOT 2-row template | 4 | ROBOT-shaped property proposal |
| `metpo_existing_aliases.tsv` | bespoke 7-col | 45 | Audit table: proposed labels that already exist in METPO (use the existing ID) |
| `complex_ingredients.tsv.gz` | bespoke 4-col | 9 | Complex-ingredient → component-list (peptone composition, etc.) |
| `validate_*.py` | python | — | 3 schema/content validators (not data) |

### Per-transform `kg_microbe/transform_utils/metatraits/mappings/` (legacy split)

| File | Schema | Entries | Role |
|---|---|---|---|
| `metpo_alias_mappings.tsv` | canonical 12-col SSSOM-shape | 66 | Tier-2 alias overrides for `load_metpo_mappings` (consumed via the new overlay layer added in commit `b7a099bc`) |
| `chemical_mappings.tsv` | canonical 12-col SSSOM-shape | 9 | Chemical name → ChEBI overrides (priority-5 in consolidator) |
| `phenotype_mappings.tsv` | canonical 12-col SSSOM-shape | 12 | Phenotype synonym → METPO |
| `enzyme_mappings.tsv` | canonical 12-col SSSOM-shape | 14 | Enzyme name → EC + GO |
| `pathway_mappings.tsv` | canonical 12-col SSSOM-shape | 4 | Pathway name → GO/UPA |
| `enzyme_name_to_go.tsv` | bespoke 2-col | 44 | Enzyme name → GO id (legacy format) |
| `special_chemical_mappings.tsv` | bespoke 7-col | 194 | Trait-pattern + chemical-name → ontology id (different shape — used by `metatraits.py` for trait-pattern routing) |

### Per-transform JSON / archive (housekeeping candidates)

| Path | Status |
|---|---|
| `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` | 193 entries — consumed by consolidator (priority-1) |
| `kg_microbe/transform_utils/bacdive/archive/metabolite_mapping.json` | duplicate — should be deleted |
| `kg_microbe/transform_utils/bacdive/tmp/bacdive_mappings.tsv*` | build artifacts — `.gitignore` candidates |
| `kg_microbe/transform_utils/bactotraits/tmp/BactoTraits_mapping.tsv` | build artifact |
| `kg_microbe/transform_utils/rhea_mappings/tmp/rhea_id_label_mapping.tsv` | build artifact |
| `kg_microbe/transform_utils/translation_table.yaml` | **DEAD** — 504 lines, no consumer in codebase |
| `kg_microbe/transform_utils/custom_curies.yaml` | 214 entries — actively consumed; defines `kgmicrobe.*` placeholders |

### Schemas dir (separate)

| Path | Status |
|---|---|
| `schemas/chemicals.sssom.tsv` | Last touched 2023-10-30 — predates the unified SSSOM. Likely superseded |
| `schemas/pathways.sssom.tsv` | Same |

### Stray / scratchpad files at repo root

| Path | Status |
|---|---|
| `new_chemical_mappings.tsv` | 341 bytes, March 21 — looks like working notes, never integrated |
| `new_METPO_mapping.tsv` | 1,686 bytes, March 21 — same |

## Real hardcoded mappings (audit script missed these)

### `kg_microbe/transform_utils/bacdive/bacdive.py`

11 inline METPO/RO CURIE references that should be in a TSV:

| Line | Code | Should be |
|---|---|---|
| 1336–1338 | `{"pathogenicity human": ("METPO:1004004", "human pathogen"), ...}` (3 entries) | `bacdive_pathogenicity_to_metpo.tsv` |
| 2283 | `value, "METPO:1001101", organism_id, key, ...` (BacDive risk assessment) | `bacdive_field_to_metpo.tsv` |
| 2320 | `"METPO:1004005"` (object: growth medium ontology class) | constant, OK |
| 2688 | `value, "METPO:1000601", ...` (oxygen tolerance parent) | `bacdive_field_to_metpo.tsv` |
| 2695 | `value, "METPO:1000870", ...` (motility parent) | `bacdive_field_to_metpo.tsv` |
| 2702 | `value, "METPO:1000631", ...` (cell shape parent) | `bacdive_field_to_metpo.tsv` |
| 2709 | `value, "METPO:1000666", ...` (gram stain parent) | `bacdive_field_to_metpo.tsv` |
| 2716 | `value, "METPO:1000697", ...` (spore-forming parent) | `bacdive_field_to_metpo.tsv` |
| 2723 | `value, "METPO:1000701", ...` (cell shape, again?) | `bacdive_field_to_metpo.tsv` |
| 2730 | `value, "METPO:1000629", ...` (other parent) | `bacdive_field_to_metpo.tsv` |
| 2890 | `assay_predicate = "METPO:2000511"` | constant, OK (already in `constants.py:NCBI_TO_ASSAY_EDGE`-style) |

Pattern: 7 `value, "METPO:..."` calls all pass a different METPO parent CURIE to the same helper that processes a BacDive field. This is a classic "data masquerading as code" pattern — should become a `(bacdive_field_name, parent_metpo_id, parent_label)` table.

### `kg_microbe/transform_utils/constants.py`

50 CURIE-bearing constants. Most are architectural (predicate routing, category constants) and OK as constants, but a few are pure data:

- `ASSOCIATED_WITH = "PATO:0001668"` — used once, could be inline
- `ASSAY_OUTPUT_RELATION = "NCIT:C25284"` — semantic, OK
- The `MEDIUM_*_CATEGORY`, `NCBI_TO_*_EDGE` etc. constants are routing decisions — leave them in code

## Dead / stale files to delete

1. `kg_microbe/transform_utils/translation_table.yaml` — 504 lines, NO consumer (verified by `grep -rn`)
2. `kg_microbe/transform_utils/bacdive/archive/metabolite_mapping.json` — duplicate of the live file
3. `new_chemical_mappings.tsv` and `new_METPO_mapping.tsv` at repo root — March-21 scratchpad never integrated
4. `mappings/CONSOLIDATION_SUMMARY.md` — historical doc, replace with `mappings/README.md` (already up-to-date)
5. `schemas/*.sssom.tsv` — pre-unified-SSSOM artifacts; verify no consumer, then delete
6. `tmp/` build artifacts — add to `.gitignore` if not already

## Schema fragmentation

The "canonical 12-col SSSOM-shape" header is shared by 6 files (good) but
there are 5 other one-off shapes:

| Schema | Files | Cols |
|---|---|---|
| **Canonical 12-col** | chemical_mappings, phenotype_mappings, enzyme_mappings, pathway_mappings, metpo_alias_mappings, isolation_source_to_ontology | `subject_label, subject_label_normalized, object_id, object_label, object_source, predicate_id, confidence, mapping_justification, curator, source_dataset, notes, verified_date` |
| **True SSSOM** | ingredient_mappings, kgmicrobe_unified_entity_mappings | 13-col SSSOM standard |
| **Bespoke special_chemical** | special_chemical_mappings | `trait_pattern, chemical_name, ontology_id, ontology_name, predicate, category, notes` |
| **Bespoke CultureBotAI** | culturebotai_reviewed_ingredients | `ingredient_name, occurrence_count, chebi_id, cas_rn, kg_microbe_node_id, mim_id, culturemech_term_id, mapping_status, example_media` |
| **Bespoke 2-col** | enzyme_name_to_go | `enzyme_name, go_id` |
| **ROBOT template** | metpo_proposal_classes_robot, metpo_proposal_properties_robot | 2 header rows (column name + ROBOT directive) |

The 12-column canonical schema is well-designed and widely adopted.
`special_chemical_mappings.tsv` and `enzyme_name_to_go.tsv` could be
migrated to it without losing information.

## Proposed organization

**Single curation hub at `mappings/` with topical subdirectories:**

```
mappings/
├── README.md                                 # current — stays
│
├── canonical/                                # 12-col SSSOM-shape, hand-curated
│   ├── chemical_mappings.tsv                 # moved from metatraits/mappings/
│   ├── phenotype_mappings.tsv                # moved
│   ├── enzyme_mappings.tsv                   # moved
│   ├── pathway_mappings.tsv                  # moved
│   ├── metpo_alias_mappings.tsv              # moved
│   ├── isolation_source_to_ontology.tsv      # already here
│   ├── bacdive_field_to_metpo.tsv            # NEW — extracted from bacdive.py
│   └── special_chemical_mappings.tsv         # migrated to 12-col schema
│
├── consolidated/                             # generated by scripts, not hand-edited
│   ├── kgmicrobe_unified_entity_mappings.sssom.tsv.gz   # consolidator output
│   ├── ingredient_mappings.sssom.tsv         # vendored MIM cache
│   └── complex_ingredients.tsv.gz            # complex ingredient composition
│
├── upstream-curation/                        # external authoritative inputs
│   └── culturebotai_reviewed_ingredients.tsv
│
├── proposals/                                # METPO term proposals (upstream submissions)
│   ├── metpo_proposal_categorical.tsv
│   ├── metpo_proposal_quantitative.tsv
│   ├── metpo_proposal_classes_robot.tsv
│   ├── metpo_proposal_properties_robot.tsv
│   ├── metpo_existing_aliases.tsv
│   └── kgmicrobe_proposal_placeholders.tsv
│
├── queues/                                   # curation backlogs (auto-generated, edited by curators)
│   └── mediadive_unmapped_ingredients_to_curate.tsv
│
├── audit/                                    # generated audit artifacts (.gitignore?)
│   └── manual_mapping_audit_report.tsv
│
└── validators/
    ├── validate_isolation_source_mappings.py
    ├── validate_manual_mappings.py
    └── validate_mapping_schema.py
```

**Per-transform `metatraits/mappings/` becomes empty** (or removed entirely)
once its contents move to `mappings/canonical/`. Loaders updated to read
from the new path.

## Concrete action items (prioritised)

| # | Action | Risk | Effort |
|---|---|---|---|
| 1 | Delete `translation_table.yaml` (verified zero consumers) | None | 1 min |
| 2 | Delete `bacdive/archive/metabolite_mapping.json` and `new_*.tsv` at root | None | 1 min |
| 3 | Add `tmp/` to `.gitignore` (or move existing tmp/ files outside the source tree) | None | 2 min |
| 4 | Extract `bacdive.py` lines 2688–2730 into `bacdive_field_to_metpo.tsv` (8 rows) + loader | Low — must rerun bacdive transform after | 30 min |
| 5 | Extract `bacdive.py` lines 1336–1338 into the same TSV (3 rows: pathogenicity human/animal/plant) | Low — same | 5 min |
| 6 | Migrate `special_chemical_mappings.tsv` (194 rows) to the 12-column canonical schema | Medium — rewrite the metatraits Tier-3 reader | 1 h |
| 7 | Migrate `enzyme_name_to_go.tsv` (44 rows) to the canonical schema | Low — rewrite reader | 30 min |
| 8 | Move all canonical-schema files from `metatraits/mappings/` to `mappings/canonical/`; update loaders | Low — single import-path change per file | 30 min |
| 9 | Add `mappings/canonical/` schema enforcer to CI: `validate_mapping_schema.py --strict` runs on every PR | Low — already exists | 10 min |
| 10 | Verify `schemas/*.sssom.tsv` has no consumer; delete if so | Low | 5 min |

**Total**: ~3–4 hours of work for a clean, single-hub layout that's
trivially curatable and CI-validatable.

## What stays as-is

- `custom_curies.yaml` (214 entries) — actively consumed, defines placeholder CURIEs. Don't touch.
- `constants.py` predicate/category constants — these are architectural routing decisions, not data. Don't touch.
- `kgmicrobe_unified_entity_mappings.sssom.tsv.gz` — already canonical and authoritative.

## CI / curator UX wins after consolidation

1. **Single grep target**: `grep -rn "<label>" mappings/canonical/` finds every curation row in seconds.
2. **Schema validator**: `validate_mapping_schema.py --strict mappings/canonical/` enforces the 12-column shape on every PR.
3. **Cross-file conflict detector**: extend the same validator with a label↔object_id conflict pass (currently 0 conflicts among the 6 canonical files — keep it that way).
4. **Curation queue tracker**: `mappings/queues/` becomes the canonical place for "labels still needing curator attention" — surfaced in the model-review skill's curation upgrade report.

## Inline-CURIE triage from audit-mappings v2 (2026-05-03)

Running `audit-mappings` v2 against the post-cleanup repo surfaced **149 inline CURIE literals across 13 transforms** plus **1 repeated-callsite cluster**. Triaged here so the cleanup doesn't drag on indefinitely.

| Status | Count | Notes |
|---|---|---|
| ✅ Lifted | 5 inline literals + 1 cluster | bakta `add_edge()` callsite cluster: 6 calls each passing a different `(biolink_predicate, ro_relation)` pair. Promoted both halves to named constants in `constants.py` (`BIOLINK_HAS_GENE`, `BIOLINK_HAS_GENE_PRODUCT`, `BIOLINK_ENABLES`, `BIOLINK_MEMBER_OF`, `BIOLINK_ORTHOLOGOUS_TO`) and updated bakta to use them. The cluster is now gone; bakta inline-literal count dropped 32 → 24. |
| 📋 Future incremental | ~140 inline literals | Mostly `infores:*` knowledge-source strings, repeated `biolink:*` category literals at node-creation sites, and one-off `RO:*` relations in single call sites. Each transform owner can lift its own as a small follow-up — they're not data masquerading as code, just constants candidates. The audit doc's `mappings/canonical/` work was higher leverage. |
| 🟢 Leave as-is | 4 dicts | `bakta/utils.py:217-221 aspect_map` (3 entries), `bakta/utils.py:233-237 predicate_map` (3 entries), `ontologies_transform.py:98-115 ONTOLOGY_KNOWLEDGE_SOURCES` (16 entries), and one ontologies dict are all cohesive routing tables that benefit from being inline (close to the function that consumes them). Lifting them would scatter the routing logic without simplifying anything. |

The repeated-callsite detector was the highest-signal v2 addition; it caught the bakta pattern that the v1 scanner couldn't see. The remaining 140 inline literals are visible in `audit-mappings --verbose` whenever a curator wants to nibble at them; not blocking.
