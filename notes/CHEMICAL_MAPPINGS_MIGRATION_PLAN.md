# Chemical Mappings Migration Plan

**Date:** 2026-04-07  
**Purpose:** Consolidate manually curated chemical mappings into unified chemical mappings file  
**Goal:** Transform hard-coded mappings into data-driven mappings with provenance

---

## Current State

### Source Files (Hard-Coded Mappings)

| File | Location | Entries | Format | Target |
|------|----------|---------|--------|--------|
| chemical_name_synonyms.tsv | metatraits/mappings/ | 81 | TSV | unified_chemical_mappings.tsv.gz |
| special_chemical_mappings.tsv | metatraits/mappings/ | 35 | TSV | unified_chemical_mappings.tsv.gz |
| metabolite_mapping.json | bacdive/ | 193 | JSON | unified_chemical_mappings.tsv.gz |
| **TOTAL** | | **309** | | |

### Target File (Data-Driven Repository)

**File:** `mappings/unified_chemical_mappings.tsv.gz`  
**Format:** TSV (gzipped)  
**Columns:** `chebi_id`, `canonical_name`, `formula`, `synonyms`, `xrefs`, `sources`

**Existing Sources:**
- `mediadive_compounds` - MediaDive media composition data
- `chebi_xrefs` - ChEBI cross-references
- `primary_mappings[kegg_compound]` - KEGG compound mappings

---

## Migration Strategy

### Phase 1: Convert Format ✅

**chemical_name_synonyms.tsv → unified format**

```
Current format:
metatraits_name | chebi_search_name | chebi_id | chebi_label | notes

Target format:
chebi_id | canonical_name | formula | synonyms | xrefs | sources
```

**Conversion logic:**
- `chebi_id` → `chebi_id` (direct copy)
- `chebi_label` → `canonical_name` (ChEBI primary name)
- `formula` → empty (not in source file; can be fetched from ChEBI later)
- `metatraits_name` → `synonyms` (MetaTraits-specific synonym)
- `xrefs` → empty (no cross-references in source)
- `sources` → `metatraits_chemical_synonyms`

---

**special_chemical_mappings.tsv → unified format**

```
Current format:
trait_pattern | chemical_name | ontology_id | ontology_name | predicate | category | notes

Target format:
chebi_id | canonical_name | formula | synonyms | xrefs | sources
```

**Conversion logic:**
- `ontology_id` → `chebi_id` (only if CHEBI:*, skip ENVO/FOODON)
- `ontology_name` → `canonical_name`
- `formula` → empty
- `chemical_name` → `synonyms`
- `xrefs` → empty
- `sources` → `metatraits_special_chemicals`

**Note:** Entries with ENVO or FOODON IDs should remain in special_chemical_mappings.tsv (not chemical mappings)

---

**metabolite_mapping.json → unified format**

```
Current format:
{
  "CHEBI:86455": "optochin",
  "CHEBI:28971": "ampicillin",
  ...
}

Target format:
chebi_id | canonical_name | formula | synonyms | xrefs | sources
```

**Conversion logic:**
- JSON key → `chebi_id`
- JSON value → add to `synonyms` column
- `canonical_name` → fetch from ChEBI (or use JSON value if unavailable)
- `formula` → empty (fetch from ChEBI later if needed)
- `xrefs` → empty
- `sources` → `bacdive_antibiotics`

---

### Phase 2: Add Provenance Tracking ✅

**New column in unified file: `provenance`**

Options:
1. **Embed in sources column:** `metatraits_chemical_synonyms[manual_curated_2026-04-07]`
2. **Separate provenance field:** Add new column for curator/date/justification
3. **Link to provenance files:** `sources` references provenance TSV/MD files

**Recommended:** Option 1 (embed in sources) for simplicity

Example:
```
CHEBI:16659 | D-saccharate | | D-saccharate|potassium 5-dehydro-D-gluconate | | metatraits_chemical_synonyms[Priority2_2026-04-07]
```

---

### Phase 3: Deduplicate and Merge ✅

**Deduplication strategy:**

1. Check if ChEBI ID already exists in unified file
2. If exists:
   - Append new synonym to `synonyms` column (pipe-separated)
   - Append new source to `sources` column (pipe-separated)
3. If not exists:
   - Add new row with all fields

**Merge order:**
1. Load existing unified_chemical_mappings.tsv.gz
2. Process chemical_name_synonyms.tsv (81 entries)
3. Process special_chemical_mappings.tsv (only ChEBI entries, ~28 entries)
4. Process metabolite_mapping.json (193 entries)
5. Remove duplicates (same ChEBI ID)
6. Sort by ChEBI ID
7. Write to unified_chemical_mappings.tsv.gz

---

### Phase 4: Update Transform Code 🔲

**Files to modify:**

1. **metatraits/metatraits.py**
   - Replace `chemical_name_synonyms.tsv` loader with unified file loader
   - Replace `special_chemical_mappings.tsv` loader with unified file loader
   - Add filtering logic for `sources` column (metatraits_* sources only)

2. **bacdive/bacdive.py**
   - Replace `metabolite_mapping.json` loader with unified file loader
   - Add filtering logic for `sources` column (bacdive_antibiotics source only)

**Benefits:**
- Centralized chemical mapping repository
- Consistent lookup API across transforms
- Provenance tracking built-in
- Easier maintenance and updates

---

### Phase 5: Validate and Test 🔲

**Validation steps:**

1. **Count check:**
   ```bash
   # Before: 81 + 28 + 193 = 302 chemical mappings
   # After: ~302 unique ChEBI IDs in unified file (may be fewer due to deduplication)
   ```

2. **Transform test:**
   ```bash
   poetry run kg transform -s metatraits --show-status
   poetry run kg transform -s bacdive --show-status
   ```
   - Verify no unmapped chemicals that were previously mapped
   - Check edge counts remain consistent

3. **Edge case testing:**
   - Duplicate ChEBI IDs (e.g., CHEBI:2652 and CHEBI:2682 for amphotericin b)
   - Multi-word synonyms with special characters
   - Synonyms with stereochemistry notation

---

## Implementation Steps

### Step 1: Create Migration Script

**File:** `scripts/migrate_chemical_mappings.py`

```python
#!/usr/bin/env python3
"""
Migrate manually curated chemical mappings to unified chemical mappings file.
"""

import json
import gzip
from pathlib import Path
from collections import defaultdict

# Paths
UNIFIED_FILE = Path("mappings/unified_chemical_mappings.tsv.gz")
CHEM_SYNONYMS = Path("kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv")
SPECIAL_CHEM = Path("kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv")
BACDIVE_JSON = Path("kg_microbe/transform_utils/bacdive/metabolite_mapping.json")
OUTPUT_FILE = Path("mappings/unified_chemical_mappings_v2.tsv.gz")

# Load existing unified mappings
# Convert TSV files to unified format
# Deduplicate by ChEBI ID
# Write to new file
```

---

### Step 2: Run Migration

```bash
python scripts/migrate_chemical_mappings.py
```

**Expected output:**
```
Loaded 15,234 existing mappings from unified file
Processing chemical_name_synonyms.tsv... +81 mappings
Processing special_chemical_mappings.tsv... +28 chemical mappings (7 ENVO/FOODON skipped)
Processing metabolite_mapping.json... +193 mappings
Deduplication: 302 total → 298 unique ChEBI IDs (4 duplicates merged)
Writing unified_chemical_mappings_v2.tsv.gz... 15,532 total mappings
Done!
```

---

### Step 3: Backup and Replace

```bash
# Backup original
cp mappings/unified_chemical_mappings.tsv.gz mappings/unified_chemical_mappings_backup_2026-04-07.tsv.gz

# Replace with migrated version
mv mappings/unified_chemical_mappings_v2.tsv.gz mappings/unified_chemical_mappings.tsv.gz
```

---

### Step 4: Update Transform Loaders

**Before (hard-coded):**
```python
# metatraits.py
self.chem_synonyms = self._load_tsv_mapping("chemical_name_synonyms.tsv")
```

**After (data-driven):**
```python
# metatraits.py
from kg_microbe.transform_utils.unified_chemical_loader import UnifiedChemicalLoader

self.chem_loader = UnifiedChemicalLoader(
    sources=["metatraits_chemical_synonyms", "metatraits_special_chemicals"]
)
```

---

### Step 5: Archive Old Files

Move deprecated files to archive:

```bash
mkdir -p kg_microbe/transform_utils/metatraits/mappings/archive/
mv kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv \
   kg_microbe/transform_utils/metatraits/mappings/archive/
mv kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv \
   kg_microbe/transform_utils/metatraits/mappings/archive/

mkdir -p kg_microbe/transform_utils/bacdive/archive/
mv kg_microbe/transform_utils/bacdive/metabolite_mapping.json \
   kg_microbe/transform_utils/bacdive/archive/
```

**Retain provenance files:**
- Keep all `*_provenance.tsv` and `*_provenance.md` files for historical reference
- Add README.md in archive/ explaining migration

---

## Benefits of Migration

### Before (Hard-Coded)

❌ **Scattered:** 3 separate files across 2 transforms  
❌ **No provenance:** Source authority not tracked  
❌ **Inconsistent:** Different formats (TSV, JSON)  
❌ **Duplicate effort:** Same ChEBI ID in multiple files  
❌ **Hard to maintain:** Updates require editing multiple files

### After (Data-Driven)

✅ **Centralized:** Single unified repository  
✅ **Provenance tracked:** `sources` column documents origin  
✅ **Consistent format:** Standard TSV with defined schema  
✅ **Deduplicated:** Each ChEBI ID appears once with all synonyms  
✅ **Easy to maintain:** One file to update, all transforms benefit  
✅ **Interoperable:** Can be used by any transform or external tool

---

## Next Steps

1. ✅ Create provenance files (COMPLETED)
2. 🔲 Write migration script (`scripts/migrate_chemical_mappings.py`)
3. 🔲 Run migration and validate output
4. 🔲 Update transform code to use unified loader
5. 🔲 Test all transforms with new unified file
6. 🔲 Archive deprecated mapping files
7. 🔲 Update documentation (CLAUDE.md, README.md)
8. 🔲 Commit changes with comprehensive message

**Estimated time:** 2-3 hours

---

## Success Criteria

- [ ] All 309 chemical mappings migrated to unified file
- [ ] Deduplication reduces to ~300 unique ChEBI IDs
- [ ] Provenance tracked via `sources` column
- [ ] All provenance files preserved
- [ ] metatraits and bacdive transforms produce identical output
- [ ] No new unmapped chemicals
- [ ] Tests pass (`poetry run tox`)
- [ ] Documentation updated

---

**Status:** READY FOR IMPLEMENTATION  
**Blocker:** None  
**Risk:** Low (transforms can be rolled back if migration fails)
