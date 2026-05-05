---
name: audit-mappings
description: Audit code + curation files for hardcoded ontology mappings, dead files, schema heterogeneity, and repeated-callsite "data masquerading as code" patterns
---

# Audit Mappings Skill (v2)

Scans KG-Microbe code + curation files for hardcoded ontology mappings and surfaces "data masquerading as code" patterns. v2 was rewritten 2026-05-03 after v1 reported "100% data-driven" but missed all 11 inline METPO/RO CURIEs in `bacdive.py` (function-call arguments, method-local dicts of <6 entries, single-occurrence semantic literals).

## What v2 detects

### Code-side findings

| Check | What v1 missed | What v2 catches |
|---|---|---|
| **Inline CURIEs** | All function-call argument literals like `_method(value, "METPO:1000601", ...)` | Every `Constant(str)` AST node whose value matches the broadened CURIE regex (covers mixed-case `mesh:`, dotted `pubchem.compound:`, hyphenated `CAS-RN`). Excludes docstrings. |
| **Method-local dicts** | Dicts with <6 entries; dicts not at top level | Dict literals at any AST nesting level with 3+ CURIE values (catches the 3-entry `pathogenicity_mappings` dict pattern). |
| **Repeated callsites** | Wasn't checked | Same callee invoked 3+ times with 3+ distinct CURIE first-args — strong "this should be table-driven" signal (catches the 7-call `_process_phenotype_by_metpo_parent` pattern in bacdive.py). |

### Curation-file findings

| Check | What v1 missed | What v2 catches |
|---|---|---|
| **Repo-root inventory** | Only scanned `transform_utils/<name>/mappings/` | Also walks repo-root `mappings/` (incl. `canonical/`, proposals, queues, audit reports) and reports per-file entry counts + schema fingerprints. |
| **Schema heterogeneity** | Not checked | Groups files by directory; warns when sibling files claim the same purpose but have different headers. Catches the 3-schema split in `mappings/canonical/` (12-col SSSOM-shape vs `special_chemical` extension vs `enzyme_name_to_go` extension). |
| **Dead-file detection** | Not checked | Greps each mapping file's basename across `kg_microbe/`, `scripts/`, `tests/`, `mappings/`, `.github/`. Files with zero textual references are flagged (would have caught `translation_table.yaml` with its 504 lines and zero consumers). |

## Usage

```bash
# Full repo audit
python3 .claude/skills/audit-mappings/audit_mappings.py

# Single transform
python3 .claude/skills/audit-mappings/audit_mappings.py --transform bacdive

# Verbose output (per-line CURIE list, full schema headers)
python3 .claude/skills/audit-mappings/audit_mappings.py --verbose

# Markdown / JSON output
python3 .claude/skills/audit-mappings/audit_mappings.py --format md > report.md
python3 .claude/skills/audit-mappings/audit_mappings.py --format json > report.json
```

## Tunable thresholds (top of `audit_mappings.py`)

```python
_REPEATED_CALLSITE_MIN = 3   # call count + distinct CURIE count threshold
_DICT_CURIE_MIN        = 3   # min CURIE values in a dict to flag (was 5 in v1)
_KNOWN_CURIE_PREFIXES  = {…} # which prefixes count as "data CURIE"
```

If the scanner is too noisy, tightening these is the right knob; adding to `_ACCEPTABLE_DICT_NAME_FRAGMENTS` is the way to suppress known-good config dicts (URLs, column maps, etc.).

## Lessons baked into v2 from the 2026-05-03 cleanup pass

1. **"0 hardcoded mappings" + "100% data-driven" is misleading** when the scanner only knows about top-level dict assigns. v2 reports specific finding *counts* (inline CURIE literals, dicts, repeated callsites) so a green run actually means something.
2. **Top-level dict scan misses the most common pattern in this codebase** — repeated method calls each passing a different CURIE literal as one argument (e.g. the 7 `_process_phenotype_by_metpo_parent(value, "METPO:1000601", ...)` calls). The repeated-callsite detector is the highest-signal v2 addition.
3. **Two curation directories ≠ two systems** — both `kg_microbe/transform_utils/<x>/mappings/` and repo-root `mappings/` need scanning. When mappings move (as in the phase-4 cleanup), the scanner has to follow.
4. **Dead-file detection earns its keep** — `translation_table.yaml` was 504 lines of unused PATO/SEPIO/GENO mappings. A grep-based "is anything importing/loading this?" pass catches that class of stale curation file fast.
5. **Schema fingerprints are an early-warning signal**, not a hard error. The `canonical/` dir has 3 known-accepted variants (12-col baseline + extension columns). Heterogeneity warnings are useful as "did anyone notice?" prompts at PR review.

## Output format (text, default)

```
=== KG-Microbe Mapping Audit (v2) ===
Date: 2026-05-03

Transform: bacdive
  ⚠ findings: 11 inline CURIEs

Transform: ontologies
  ⚠ findings: 21 inline CURIEs, 1 dict(s)
    [dict] ontologies_transform.py:98-115 ONTOLOGY_KNOWLEDGE_SOURCES (16 CURIE values)

----------------------------------------------------------------
Repo-root canonical curation hub (mappings/):
  - mappings/canonical/chemical_mappings.tsv          9 entries
  - mappings/canonical/enzyme_mappings.tsv           14 entries
  - …

----------------------------------------------------------------
⚠ Schema heterogeneity within sibling curation files:
  mappings/canonical: 3 distinct headers across 7 file(s)
    schema #896: chemical_mappings.tsv, enzyme_mappings.tsv, metpo_alias_mappings.tsv, …
    schema #823: special_chemical_mappings.tsv
    schema #661: enzyme_name_to_go.tsv

----------------------------------------------------------------
Summary:
  Transforms scanned:              23
  Inline CURIE literals:           149
  Repeated-callsite clusters:       1
  Total mapping files:             23
  Total mapping entries:           602,570
  Schema heterogeneity warnings:    2
  Dead files:                       0
```

## When to use

- **Before a release**: confirm no new hardcoded mappings have crept in.
- **During a cleanup pass**: identify migration candidates (high inline-CURIE count + repeated callsites = strong table-driven candidate).
- **After moving curation files**: confirm the move didn't leave dead files behind.
- **During a curation-schema audit**: spot heterogeneous headers in what should be a uniform directory.

## Triage rubric

| Finding | Action |
|---|---|
| **Repeated-callsite cluster** (≥3 calls, ≥3 distinct CURIEs) | Strong "this should be a TSV"; lift the (varying-arg) data into a routing/mapping file. |
| **Method-local dict** (≥3 CURIE values) | If the dict is the body of a single business-logic decision, lift it. If it's an architectural constant (predicate aliases, category aliases), name it and move to `constants.py`. |
| **Inline CURIE** (single occurrence) | Usually a constant candidate (`HAS_PHENOTYPE = "biolink:has_phenotype"`). Move to `constants.py` if it's predicate/category/relation; lift to a TSV if it's data. |
| **Dead file** | If a curation TSV/YAML has zero consumers, delete it (after confirming the listed consumer paths still exist). |
| **Schema heterogeneity** | Unify if the variants don't carry semantic content. Document the variants in the directory's README if they do. |

## See also

- `mappings/validate_mapping_schema.py` — per-row schema enforcer (CI gate)
- `docs/MAPPING_AUDIT.md` — running record of cleanup decisions
- `kg-model-review` skill — surface-level KGX/Biolink/METPO conformance (different layer)
