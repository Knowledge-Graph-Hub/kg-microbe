# Biolink Model Predicate Changes - assesses / is_assessed_by

**Date**: January 10, 2026
**Update**: Biolink Model v3.6.0 → v4.3.6
**Status**: DEPRECATED in v4.3.3

---

## Executive Summary

⚠️ **DEPRECATED**: The predicates `biolink:assesses` and `biolink:is_assessed_by` were deprecated in Biolink Model v4.3.3 (Nov 5, 2024) via [PR #1622](https://github.com/biolink/biolink-model/pull/1622).

**Recommendation**: Use `biolink:affects` predicate to represent actual experimental outcomes instead of merely recording that an experiment was conducted.

---

## What Changed

### v3.6.0 (Previous Version)

**Available predicates:**
- ✅ `biolink:assesses` - Active predicate
- ✅ `biolink:is_assessed_by` - Active predicate (inverse of assesses)
- ✅ `biolink:was_tested_for_effect_on` - Active predicate (parent of assesses)

**Association class:**
- ✅ `ChemicalEntityAssessesNamedThingAssociation` - Active

### v4.3.6 (Current Version)

**Deprecated predicates:**
- ⚠️ `biolink:assesses` - **REMOVED** from predicates
- ⚠️ `biolink:is_assessed_by` - **REMOVED** from predicates
- ⚠️ `biolink:was_tested_for_effect_on` - **DEPRECATED** (marked with `deprecated: true`)

**Association class:**
- ⚠️ `ChemicalEntityAssessesNamedThingAssociation` - **DEPRECATED** (marked with `deprecated: true`)

---

## Why Were They Deprecated?

From [PR #1622 discussion](https://github.com/biolink/biolink-model/pull/1622):

> "The fact that an experiment was done to test if X affects Y is not particularly useful. What is useful is outcomes of such assays."

**Key points:**
1. These predicates only recorded that testing occurred, not the results
2. Limited applicability - originally created for ChEMBL experimental assay data
3. Not broadly useful across knowledge graphs
4. Replaced by more meaningful predicates that capture actual experimental findings

---

## Recommended Replacement

### Instead of: `assesses` / `is_assessed_by`

**Use**: `biolink:affects` and its subpredicates

```yaml
# OLD (deprecated):
subject: CHEBI:12345
predicate: biolink:assesses
object: NCBIGene:67890

# NEW (recommended):
subject: CHEBI:12345
predicate: biolink:affects
object: NCBIGene:67890
```

### Better Practice: Capture Actual Outcomes

Use specific subpredicates of `affects` that describe the actual experimental result:

- `biolink:increases_activity_of`
- `biolink:decreases_activity_of`
- `biolink:regulates`
- `biolink:positively_regulates`
- `biolink:negatively_regulates`

**Example:**
```yaml
# Instead of just recording that testing happened:
subject: CHEBI:16737
predicate: biolink:assesses
object: NCBIGene:1234

# Record what the experiment showed:
subject: CHEBI:16737
predicate: biolink:increases_activity_of
object: NCBIGene:1234
```

---

## Available Predicates in v4.3.6

### For Chemical-Gene/Protein Interactions

| Predicate | Description | Status |
|-----------|-------------|--------|
| `affects` | General causal relationship | ✅ Active |
| `increases_activity_of` | Positive effect on activity | ✅ Active |
| `decreases_activity_of` | Negative effect on activity | ✅ Active |
| `regulates` | Regulatory relationship | ✅ Active |
| `interacts_with` | General interaction (symmetric) | ✅ Active |
| `physically_interacts_with` | Physical contact interaction | ✅ Active |

### Deprecated Predicates (Do Not Use)

| Predicate | Status | Replacement |
|-----------|--------|-------------|
| `assesses` | ⚠️ REMOVED | Use `affects` or subpredicates |
| `is_assessed_by` | ⚠️ REMOVED | Use inverse of `affects` |
| `was_tested_for_effect_on` | ⚠️ DEPRECATED | Use `affects` |

---

## Migration Guide for kg-microbe

### Step 1: Search for Usage

Check if kg-microbe uses deprecated predicates:

```bash
grep -r "assesses\|is_assessed_by\|was_tested_for_effect_on" kg_microbe/
grep "assesses\|is_assessed_by\|was_tested_for_effect_on" data/transformed/*/edges.tsv
```

### Step 2: Replace with Appropriate Predicates

Based on the context of your data:

1. **If recording experimental results**: Use `affects` subpredicates
   - Chemical increases enzyme activity → `increases_activity_of`
   - Chemical decreases protein function → `decreases_activity_of`

2. **If recording general relationships**: Use `affects` or `interacts_with`
   - Unknown mechanism → `affects`
   - Known physical interaction → `physically_interacts_with`

3. **If using StudyResult objects**: Link to experimental evidence
   - Create StudyResult nodes with detailed outcomes
   - Use `has_evidence` to link to supporting studies

### Step 3: Update Validation

Ensure your transforms validate against Biolink Model v4.3.6:

```bash
# Update biolink-model package
poetry add biolink-model@latest

# Download latest model YAML
poetry run kg download
```

---

## Impact on kg-microbe

### Data Sources to Check

1. **Rhea Mappings** (`rhea_mappings/`)
   - May use assesses for reaction-enzyme relationships
   - Replace with `enables` or `catalyzes`

2. **BacDive** (`bacdive/`)
   - May use assesses for substrate-organism relationships
   - Replace with `metabolizes` or appropriate trait predicates

3. **MediaDive** (`mediadive/`)
   - May use assesses for chemical-organism growth relationships
   - Replace with `affects` or `enables_growth_of`

4. **Custom transforms**
   - Review any hardcoded predicate mappings
   - Update to use v4.3.6 compliant predicates

---

## Reference Links

- [Biolink Model v4.3.6 Release](https://github.com/biolink/biolink-model/releases/tag/v4.3.6)
- [PR #1622: Deprecate assesses predicates](https://github.com/biolink/biolink-model/pull/1622)
- [Biolink Model Documentation](https://biolink.github.io/biolink-model/)
- [KGX Format Specification](https://kgx.readthedocs.io/en/latest/kgx_format.html)

---

## Updated download.yaml Configuration

```yaml
#
# Biolink Model
# The standard schema for biological knowledge graphs
# Version 4.3.6 (latest as of Dec 2024)
# NOTE: is_assessed_by predicate was removed after v3.6.0
#
-
  url: https://raw.githubusercontent.com/biolink/biolink-model/v4.3.6/biolink-model.yaml
  local_name: biolink-model.yaml

#
# KGX Format Specification
# Specification for Knowledge Graph Exchange format (TSV/CSV/JSON serialization)
#
-
  url: https://raw.githubusercontent.com/biolink/kgx/master/docs/kgx_format.md
  local_name: kgx-format.md
```

---

## Dependency Conflict Notice

⚠️ **Cannot upgrade biolink-model Python package to v4.3.6 due to dependency conflict:**

```
biolink-model 4.3.6 requires: curies >=0.9.0, <0.10.0
pyobo 0.12.4 requires:        curies >=0.10.17
kg-microbe requires:          pyobo >=0.12.0
```

**Current solution:**
- Python package: biolink-model 3.6.0 (installed via Poetry)
- YAML reference: biolink-model.yaml 4.3.6 (downloaded to data/raw/)

**Impact:**
- Python validation uses v3.6.0 rules (accepts is_assessed_by)
- YAML documentation shows v4.3.6 deprecations (is_assessed_by removed)
- Use YAML file as authoritative reference for schema compliance

**Tracking issue:** https://github.com/biolink/biolink-model/issues/[to be filed]

---

## Migration Completed: bacdive_mappings.tsv Enzyme-Assay Edges

**Date**: January 10, 2026

**Change**: Replaced `biolink:is_assessed_by` with `biolink:related_to_at_instance_level`

**Affected Edges**: 112 methodological reference edges
- Pattern: EC enzyme → related_to_at_instance_level → assay:API_[kit]_[test]
- Relation: NCIT:C153110 (assessed_activity)
- Purpose: Reference metadata showing which API kit tests detect which enzymes

**Example edges:**
```
EC:4.1.99.1 → biolink:related_to_at_instance_level → assay:API_20A_IND
EC:3.5.1.5  → biolink:related_to_at_instance_level → assay:API_20A_URE
```

**Not Affected**: Organism-specific enzyme activity outcomes
- Pattern: NCBITaxon → METPO:2000302/2000303 → EC enzyme
- Already using correct METPO predicates (shows_activity_of / does_not_show_activity_of)

**Rationale**:
- METPO predicates apply to organism→enzyme outcomes, not enzyme→assay methodology
- `biolink:related_to_at_instance_level` is semantically appropriate for factual instance relationships
- Preserves current direction (enzyme→assay) to avoid breaking changes
- More specific than generic `biolink:related_to`

**Code Changes**:
- File: `kg_microbe/transform_utils/constants.py` (line 215)
- Constant: `ENZYME_TO_ASSAY_EDGE`
- Old value: `"biolink:is_assessed_by"`
- New value: `"biolink:related_to_at_instance_level"`

**Deprecated Constants** (commented out in constants.py lines 212-214):
- `ASSAY_TO_NCBI_EDGE = "biolink:assesses"` - UNUSED
- `MEDIUM_TO_METABOLITE_EDGE = "biolink:assesses"` - UNUSED
- `NCBI_TO_ASSAY_EDGE = "biolink:is_assessed_by"` - UNUSED

**API Kit Context**:
API (Analytical Profile Index) kits are standardized bacterial identification test strips containing 20+ miniaturized biochemical tests. Each test well (e.g., API_20A_IND, API_20A_URE) detects specific enzyme activities. The 112 reference edges document which enzymes each assay can detect, separate from organism-specific test outcomes.

---

**Generated**: January 10, 2026
**Author**: Claude Code
**Repository**: kg-microbe
**Biolink Model Version**: v4.3.6
