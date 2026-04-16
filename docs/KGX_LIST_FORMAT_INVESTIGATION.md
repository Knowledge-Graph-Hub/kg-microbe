# KGX List Format Investigation and Fix

**Date**: 2026-01-25
**Status**: RESOLVED
**Issue**: Python list representations in merged graph instead of pipe-delimited strings

---

## Problem Summary

After merging, some edges had `primary_knowledge_source` values like:
```python
['infores:madin_etal', 'infores:bactotraits']
```

Instead of the correct pipe-delimited format:
```
infores:madin_etal|infores:bactotraits
```

---

## Investigation Process

### Step 1: Check Individual Transforms

Ran diagnostic tool on all transformed data:
```bash
poetry run python kg_microbe/utils/diagnose_duplicates.py --check-all-transforms
```

**Result**: ✅ All transforms are clean
- Only 2 rows in `ncbitaxon_nodes.tsv` had duplicate synonyms (from source data)
- No transforms were creating Python list representations
- No transforms were creating duplicate values

### Step 2: Check Merged Output

Analyzed merged graph:
```bash
awk -F'\t' '$11 {print $11}' data/merged/merged-kg_default_edges.tsv | head -50
```

**Result**: ⚠️ Found 10,810 rows with Python list format
- Pattern: `['infores:chebi', 'infores:chebi']`
- Pattern: `['infores:madin_etal', 'infores:bactotraits']`

### Step 3: Identify Root Cause

**Breakdown by predicate**:
```
9,093 rows: biolink:has_phenotype
1,559 rows: biolink:category
  158 rows: biolink:has_chemical_role
```

**Example edge**:
```
Subject: NCBITaxon:1000562
Predicate: biolink:has_phenotype
Object: METPO:1000604
primary_knowledge_source: ['infores:madin_etal', 'infores:bactotraits']
```

**Analysis**:
- Same phenotype assertion exists in both `madin_etal` and `bactotraits` transforms
- KGX merges these duplicate edges (same subject-predicate-object)
- KGX should output: `infores:madin_etal|infores:bactotraits`
- KGX actually outputs: `['infores:madin_etal', 'infores:bactotraits']`

**Root Cause**: KGX output format bug when merging duplicate edges
- KGX version: ^2.4.0
- The `preserve: - primary_knowledge_source` setting in `merge.yaml` doesn't prevent this
- KGX writes Python list string representations instead of proper TSV format

---

## Solution

### Implementation

Created `kg_microbe/utils/fix_list_representations.py` to:
1. Parse Python list representations using `ast.literal_eval()`
2. Deduplicate values while preserving order
3. Convert to pipe-delimited format
4. Handle malformed TSV files with embedded `\r` characters

**Key Features**:
- Uses binary mode to preserve embedded `\r` in headers
- Handles duplicate column names (e.g., `agent_type` appears twice)
- Deduplicates values (e.g., `['infores:chebi', 'infores:chebi']` → `infores:chebi`)

### Integration

Added to post-merge processing in `kg_microbe/merge_utils/merge_kg.py`:
1. KGX merge runs
2. Preserve default output as `merged-kg_default.tar.gz`
3. **Fix Python list representations** (NEW)
4. Consolidate multi-category nodes
5. Create final output as `merged-kg.tar.gz`

---

## Results

**Before Fix**:
```bash
awk -F'\t' '$11 {print $11}' data/merged/merged-kg_default_edges.tsv | grep "^\[" | wc -l
# Output: 10,810 rows
```

**After Fix**:
```bash
poetry run python kg_microbe/utils/fix_list_representations.py \
    --input data/merged/merged-kg_default_edges.tsv \
    --output /tmp/test_fixed_edges.tsv

# Output:
# ✓ Processed 6,369,983 rows
# ✓ Found 10,810 rows with Python list format
# ✓ Fixed 10,810 fields across 10,810 rows
```

**Verification**:
```bash
awk -F'\t' '$11 {print $11}' /tmp/test_fixed_edges.tsv | grep "^\[" | wc -l
# Output: 0 (no list representations remain)

awk -F'\t' '$11 ~ /\|/ {print $11}' /tmp/test_fixed_edges.tsv | head -5
# Output:
# infores:madin_etal|infores:bactotraits
# infores:madin_etal|infores:bactotraits
# infores:madin_etal|infores:bactotraits
# infores:madin_etal|infores:bactotraits
# infores:madin_etal|infores:bactotraits
```

---

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `kg_microbe/utils/diagnose_duplicates.py` | Created | Diagnostic tool to find duplicate list values |
| `kg_microbe/utils/fix_list_representations.py` | Created | Fix Python list representations to pipe-delimited |
| `kg_microbe/merge_utils/merge_kg.py` | Modified | Integrate fix into post-merge processing |

---

## Technical Details

### Python List Representation Format

**Input** (from KGX):
```python
"['infores:madin_etal', 'infores:bactotraits']"
```

**Parsing**:
```python
import ast
parsed = ast.literal_eval("['infores:madin_etal', 'infores:bactotraits']")
# Result: ['infores:madin_etal', 'infores:bactotraits']
```

**Output** (proper TSV format):
```
infores:madin_etal|infores:bactotraits
```

### Deduplication

**Input**:
```python
"['infores:chebi', 'infores:chebi']"
```

**Output**:
```
infores:chebi
```

### Edge Cases Handled

1. **Duplicate column headers**: File has `agent_type` twice
2. **Embedded carriage returns**: Header contains `agent_type\r\tknowledge_level`
3. **Mixed line endings**: File uses `\r\n` line endings with embedded `\r`
4. **Empty/missing values**: Handles fields that are empty or don't exist

---

## Upstream Issue

This is a **KGX library bug**. Consider:
1. Reporting to KGX maintainers: https://github.com/biolink/kgx
2. Checking if newer KGX versions fix this issue
3. Adding test case to KGX for proper TSV output format

---

## Usage

### Manual Fix

```bash
# Fix edges
poetry run python kg_microbe/utils/fix_list_representations.py \
    --input data/merged/merged-kg_edges.tsv \
    --output data/merged/merged-kg_edges_fixed.tsv

# Fix nodes
poetry run python kg_microbe/utils/fix_list_representations.py \
    --input data/merged/merged-kg_nodes.tsv \
    --output data/merged/merged-kg_nodes_fixed.tsv
```

### Automatic Fix (Integrated)

The fix now runs automatically during merge:

```bash
poetry run kg merge -y merge.yaml
```

**Output**:
```
Running KGX merge...
✓ KGX merge complete

================================================================================
Post-Merge Category Consolidation
================================================================================

Preserving default KGX output as merged-kg_default.tar.gz...
✓ Created merged-kg_default.tar.gz

Copying _default files for post-processing...
✓ Created working copies

Fixing Python list representations to pipe-delimited format...
✓ Processed 6,369,983 rows
✓ Found 10,810 rows with Python list format
✓ Fixed 10,810 fields across 10,810 rows
✓ Processed 1,482,945 rows
✓ Found 0 rows with Python list format
✓ Fixed 0 fields across 0 rows

Consolidating multi-category nodes using Biolink Model hierarchy...
✓ Consolidated 1,117 multi-category nodes
...
```

---

## Related Documentation

- Category consolidation: `docs/KGX_CATEGORY_INVESTIGATION.md`
- Transform fixes: `notes/CATEGORY_FIXES_IMPLEMENTATION.md`
- Merge configuration: `merge.yaml` (line 32: `preserve: - primary_knowledge_source`)
