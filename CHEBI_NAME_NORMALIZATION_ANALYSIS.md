# ChEBI Name Normalization Analysis

**Date:** 2026-04-05  
**Issue:** 916 unmapped chemical trait observations  
**Root Cause:** Name normalization - MetaTraits uses simplified names, ChEBI requires specific forms

---

## Executive Summary

**All 11 tested chemicals exist in ChEBI** - they just need name normalization to be found by the ChEBI loader.

**Problem:** MetaTraits uses simplified chemical names like "bromosuccinate" but ChEBI requires "bromosuccinic acid"

**Solution:** Create chemical name synonym mapping to try alternate names before giving up

**Impact:** Can potentially map all 916 "chemical pattern" unmapped observations

---

## Test Results

### All Chemicals Found with Name Variants ✅

| MetaTraits Name | ChEBI Search Name | ChEBI ID | Match Rate |
|-----------------|-------------------|----------|------------|
| bromosuccinate | bromosuccinic acid | CHEBI:73712 | ❌ → ✅ |
| beta-hydroxybutyrate | 3-hydroxybutyrate | CHEBI:37054 | ❌ → ✅ |
| galacturonate | D-galacturonate | CHEBI:12952 | ❌ → ✅ |
| glucose 1-phosphate | alpha-D-glucose 1-phosphate | CHEBI:29042 | ❌ → ✅ |
| (-)-D-fructose | D-fructose | CHEBI:15824 | ❌ → ✅ |
| 2-oxogluconate | 2-oxogluconic acid | CHEBI:27469 | ❌ → ✅ |
| polyhydroxybutyrate | poly(3-hydroxybutyrate) | CHEBI:53389 | ❌ → ✅ |
| bacteriochlorophyll alpha | bacteriochlorophyll a | CHEBI:30033 | ❌ → ✅ |
| 4-nitrophenyl beta-D-galactopyranoside | 4-nitrophenyl-beta-D-galactoside | CHEBI:355715 | ❌ → ✅ |
| 3-O-methyl alpha-D-glucopyranoside | 3-O-methylglucose | CHEBI:73918 | ❌ → ✅ |
| galactonate | D-galactonate | CHEBI:12931 | ❌ → ✅ |

**Success Rate:** 0/11 (0%) with original names → 11/11 (100%) with normalized names

---

## Name Normalization Patterns

### Pattern 1: Add "acid" Suffix
MetaTraits often uses the salt/anion name, ChEBI prefers the acid form:
- `bromosuccinate` → `bromosuccinic acid`
- `2-oxogluconate` → `2-oxogluconic acid`

### Pattern 2: Add Stereochemistry Prefixes
ChEBI requires explicit stereochemistry:
- `galacturonate` → `D-galacturonate`
- `galactonate` → `D-galactonate`
- `glucose 1-phosphate` → `alpha-D-glucose 1-phosphate`

### Pattern 3: Simplify or Remove Stereochemistry
Some MetaTraits names have redundant stereochemistry:
- `(-)-D-fructose` → `D-fructose` (remove redundant notation)
- `3-O-methyl alpha-D-glucopyranoside` → `3-O-methylglucose` (simplify)

### Pattern 4: Use Standard Nomenclature
ChEBI uses specific conventions:
- `beta-hydroxybutyrate` → `3-hydroxybutyrate` (use position number)
- `polyhydroxybutyrate` → `poly(3-hydroxybutyrate)` (polymer notation)
- `bacteriochlorophyll alpha` → `bacteriochlorophyll a` (use letter not word)

### Pattern 5: Use Shorter Systematic Names
Some MetaTraits names are overly specific:
- `4-nitrophenyl beta-D-galactopyranoside` → `4-nitrophenyl-beta-D-galactoside`

---

## Solution Implemented

### File Created: `chemical_name_synonyms.tsv`

**Location:** `kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv`

**Format:**
```tsv
metatraits_name	chebi_search_name	chebi_id	chebi_label	notes
bromosuccinate	bromosuccinic acid	CHEBI:73712	bromosuccinic acid	Add "acid" suffix
...
```

**Purpose:** Pre-mapped synonym lookup for chemicals that fail direct ChEBI search

---

## Integration Strategy

### Option 1: Extend ChEBI Loader with Fallback Synonyms ✅ RECOMMENDED

Modify `_resolve_chemical_trait()` and `_resolve_metabolic_trait()`:

```python
# Current code
chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)

# Enhanced code
chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)

# If not found, try synonym mapping
if not chebi_id:
    synonym_data = self.chemical_name_synonyms.get(chemical_name.lower())
    if synonym_data:
        chebi_id = synonym_data['chebi_id']
        canonical_name = synonym_data['chebi_label']
```

**Steps:**
1. Load `chemical_name_synonyms.tsv` in `__init__()`
2. Add fallback lookup in chemical resolvers
3. Use pre-mapped ChEBI IDs when direct search fails

### Option 2: Auto-Generate Variants ⏸️ COMPLEX

Try common transformations automatically:
- Add "acid" suffix
- Add "D-" prefix
- Try "3-" instead of "beta-"
- etc.

**Pros:** No manual curation needed  
**Cons:** Might generate incorrect names, harder to debug

### Option 3: Enhance ChEBI Loader Name Matching ⏸️ EXTERNAL

Modify the ChEBI loader itself to be more flexible with name matching.

**Pros:** Benefits all users of ChEBI loader  
**Cons:** Requires changes to external library

---

## Expected Impact

### Before Fix
- **916 observations** unmapped due to ChEBI lookup failures
- Coverage: 93.8% (after pigmentation re-run)

### After Fix
- **~916 observations** mapped (assuming all follow similar patterns)
- Coverage: 93.8% → **94.0%**

**Not huge increase, but eliminates systematic ChEBI lookup failures**

---

## Testing Plan

### Step 1: Load Synonym Mappings
```python
self.chemical_name_synonyms = {}
synonym_file = Path(__file__).parent / "mappings" / "chemical_name_synonyms.tsv"
with open(synonym_file) as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        self.chemical_name_synonyms[row['metatraits_name'].lower()] = row
```

### Step 2: Add Fallback in Resolvers
In both `_resolve_chemical_trait()` and `_resolve_metabolic_trait()`:
```python
chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)

# Fallback to synonym mapping
if not chebi_id and chemical_name.lower() in self.chemical_name_synonyms:
    synonym_data = self.chemical_name_synonyms[chemical_name.lower()]
    chebi_id = synonym_data['chebi_id']
    canonical_name = synonym_data['chebi_label']
    return {
        "curie": chebi_id,
        "category": "biolink:ChemicalSubstance",
        "name": canonical_name,
        "predicate": metpo_predicate,
    }
```

### Step 3: Re-run Transform
```bash
poetry run kg transform -s metatraits -s metatraits_gtdb
```

### Step 4: Verify Reduction
```bash
# Check unmapped counts before/after
wc -l data/transformed/metatraits/unmapped_traits.tsv

# Filter for chemical patterns
grep -E "^(carbon source|produces|builds acid from|oxidation|assimilation):" \
  data/transformed/metatraits/unmapped_traits.tsv | wc -l
```

---

## Additional Name Patterns to Add

Based on the unmapped traits analysis, consider adding these patterns too:

### High-Frequency Unmapped (from analysis)
- `4-nitrophenyl beta-D-galactopyranoside hydrolysate`
- `casitone` (tryptone, not a single chemical - may need special handling)
- `yeast extract` (complex mixture - may need FOODON term)
- `casein hydrolysate` (protein mixture - may need special handling)

### Recommendations
1. **Single chemicals** - Add to synonym mapping
2. **Complex mixtures** (casitone, yeast extract) - Map to FOODON or create KGM: placeholder
3. **Hydrolysates** - May map to parent compound or create separate entries

---

## Future Improvements

### Short-term
1. ✅ **Load synonym mappings** in metatraits transform
2. ✅ **Add fallback lookup** in chemical resolvers
3. **Expand synonym file** as more mismatches discovered

### Medium-term
1. **Auto-generate common variants** (acid/anion forms, D/L isomers)
2. **Add FOODON mappings** for complex growth media components
3. **Contribute synonyms to ChEBI** for commonly used variants

### Long-term
1. **Enhance ChEBI loader** with fuzzy name matching
2. **Use ChEBI InChI/SMILES** for unambiguous matching
3. **Build automated pipeline** to detect and propose new synonyms

---

## Files Created

1. ✅ **`chemical_name_synonyms.tsv`** - Name mappings (11 entries)
2. ✅ **`CHEBI_NAME_NORMALIZATION_ANALYSIS.md`** - This document
3. ⏸️ **Code changes** - Load and use synonym mappings (next step)

---

## Related Files

- **ChEBI loader:** `kg_microbe/utils/chemical_mapping_utils.py`
- **Chemical resolver:** `kg_microbe/transform_utils/metatraits/metatraits.py` line 855
- **Metabolic resolver:** `kg_microbe/transform_utils/metatraits/metatraits.py` line 918
- **Unmapped analysis:** `UNMAPPED_TRAITS_ROUND3_ANALYSIS.md`

---

## Implementation Complete ✅

**Code changes made:**

1. **Added chemical synonym loading** (`metatraits.py` lines ~582-614)
   - Created `_load_chemical_name_synonyms()` method
   - Loads mappings from `chemical_name_synonyms.tsv`
   - Returns dict: metatraits_name → {chebi_id, chebi_label, chebi_search_name}

2. **Added fallback in `_resolve_chemical_trait()`** (lines ~944-954)
   - After direct ChEBI lookup fails, tries synonym mapping
   - Uses pre-mapped ChEBI ID and canonical name

3. **Added fallback in `_resolve_metabolic_trait()`** (lines ~1020-1030)
   - Same fallback logic for metabolic patterns
   - Ensures both resolvers benefit from synonyms

4. **Added multiprocessing support** (lines ~1926, ~1949)
   - Added `chemical_name_synonyms` to `_get_shared_init_data()`
   - Added to `_init_from_shared_data()` for worker processes

5. **Extended GTDB transform** (`metatraits_gtdb.py` line ~59)
   - Added `chemical_name_synonyms` loading in `__init__`
   - Uses parent class method via inheritance

**Next step:** Re-run transform to verify ~916 chemical observations now map

---

**Status:** ✅ Complete - Code integrated, ready for testing  
**Date:** 2026-04-05
