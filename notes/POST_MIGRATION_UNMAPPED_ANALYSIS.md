# Post-Migration Unmapped Traits Analysis

**Date:** 2026-04-08  
**Branch:** `fix_metatraits`  
**Status:** After Phase 2 migration + bugfix

---

## Summary

**Total Unmapped:** 73,812 observations across 186 unique patterns

**Breakdown:**
- Yellow pigment: 73,391 observations (99.4%) - **Intentionally skipped**
- Actionable unmapped: ~421 observations (0.6%) across 185 patterns

---

## Previous vs Current State

### Before All Work (Baseline)
- Total unmapped: 244,534 observations

### After Phase 0-1 (Priority 1-3 implementations)
- Total unmapped: ~73,200 observations
- **Reduction:** 171,334 observations (70.1%)

### After Phase 2 (Migration + bugfix)
- Total unmapped: 73,812 observations
- **Reduction from baseline:** 170,722 observations (69.8%)
- **Status:** Verified working with unified file

---

## Unmapped Patterns Analysis

### Category 1: Yellow Pigment (Intentionally Skipped) ✅

**Pattern:** `cell color: yellow pigment`  
**Count:** 73,391 observations (99.4% of unmapped)  
**Status:** ⚠️ INTENTIONAL - Negative assertion design decision  
**METPO Term:** METPO:1003030 exists but not used for negative phenotypes  
**Rationale:** Represents absence of pigmentation, not a trait to model

---

### Category 2: pH Preference (Mappable!) 🔍

**Pattern:** `pH preference`  
**Count:** 33 observations  
**Issue:** Not matching METPO terms  
**Analysis:**

```bash
# Check if METPO has pH preference terms
grep -i "ph preference" metatraits/mappings/metpo_*
```

**Potential METPO terms:**
- METPO:1003001 - acidophilic
- METPO:1003002 - alkaliphilic
- METPO:1003003 - neutrophilic

**Recommendation:** Add pH preference handler similar to pH binned ranges

---

### Category 3: Concentration Prefix Issues (High Priority) 🔧

**Patterns with "1 % sodium lactate":**

| Pattern | Count | Issue |
|---------|-------|-------|
| growth: 1 % sodium lactate | 31 | Concentration prefix blocks ChEBI lookup |
| carbon source: 1 % sodium lactate | 18 | Same |
| assimilation: 1 % sodium lactate | 8 | Same |
| respiration: 1 % sodium lactate | 6 | Same |
| oxidation: 1 % sodium lactate | 6 | Same |
| **Total** | **69** | |

**Analysis:**
- Chemical "sodium lactate" likely exists in unified file
- Concentration prefix "1 %" prevents direct lookup
- Pattern: `{predicate}: {concentration} {chemical_name}`

**Fix Options:**

**Option 1: Strip concentration prefix in chemical resolver**
```python
# In _resolve_chemical_trait()
# Remove concentration patterns like "1 %", "0.01 %", etc.
chemical_name = re.sub(r'^\d+(\.\d+)?\s*%\s+', '', chemical_name)
```

**Option 2: Add to chemical_name_synonyms (now unified file)**
```tsv
1 % sodium lactate    sodium lactate    CHEBI:86354    sodium L-lactate
```

**Recommendation:** Option 1 - More general, handles all concentration prefixes

---

### Category 4: Chemical Lookup Failures (Medium Priority) 🔬

**Disodium salts:**

| Pattern | Count | ChEBI Search | Status |
|---------|-------|--------------|--------|
| carbon source: disodium malate | 8 | disodium malate? | Check ChEBI |

**Complex mixtures:**

| Pattern | Count | Type | Recommendation |
|---------|-------|------|----------------|
| growth: casitone | 5 | Peptone | FOODON or skip (complex mixture) |
| growth: yeast extract (0.01 %, w/v) | 4 | Extract | FOODON or skip |
| hydrolysis: skimmed milk | 6 | Food | FOODON:03301422 (already in special?) |
| required for growth: serum | 2 | Complex | Skip (undefined composition) |

**Chromogenic substrates:**

| Pattern | Count | ChEBI Search | Notes |
|---------|-------|--------------|-------|
| hydrolysis: 2-naphthyl dihydrogen phosphate | 4 | 2-naphthyl phosphate | Phosphatase substrate |
| assimilation: 2-naphthyl dihydrogen phosphate | 4 | Same | Same |
| nitrogen source: L-alanine 4-nitroanilide | 3 | L-alanyl-4-nitroanilide | Aminopeptidase substrate |
| assimilation: L-alanine 4-nitroanilide | 3 | Same | Same |

**Stereochemistry variants:**

| Pattern | Count | Issue | Fix |
|---------|-------|-------|-----|
| builds acid from: (-)-D-glucose | 4 | Stereochemistry notation | Should match D-glucose |

---

### Category 5: Rare Antibiotics (Long Tail) ⏸️

**Count:** 122 unique "produces" patterns, mostly 1-4 observations each  
**Total observations:** ~244  
**Status:** Same as before - diminishing returns

**Top rare antibiotics (2-4 obs each):**
- setamycin (4)
- halomicin (4)
- mycobacidin (3)
- gardimycin (3)
- aburamycin A (3)
- monazomycin (3)

**Recommendation:** Skip - not cost-effective for <5 observations each

---

## Actionable Opportunities

### Priority 1: pH Preference Handler (33 obs) 🎯

**Effort:** 30 minutes  
**Impact:** 33 observations  
**ROI:** Medium

**Implementation:**
```python
def _resolve_ph_preference_trait(self, value: str) -> Optional[dict]:
    """Handle 'pH preference' pattern."""
    # Map value to METPO acidophilic/alkaliphilic/neutrophilic
    # Similar to existing pH binned range handler
```

---

### Priority 2: Concentration Prefix Stripper (69 obs) 🎯

**Effort:** 15 minutes  
**Impact:** 69 observations (if sodium lactate in unified file)  
**ROI:** High

**Implementation:**
```python
# In _resolve_chemical_trait(), before ChEBI lookup:
import re
# Strip concentration prefixes like "1 %", "0.01 %", etc.
chemical_name_clean = re.sub(r'^\d+(\.\d+)?\s*%\s+', '', chemical_name)
chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name_clean)
```

**Verification needed:**
```bash
# Check if sodium lactate is in unified file
gunzip -c mappings/unified_chemical_mappings.tsv.gz | grep -i "sodium lactate"
```

---

### Priority 3: Chromogenic Substrates (18 obs) 🔬

**Effort:** 1 hour  
**Impact:** 18 observations  
**ROI:** Medium

**Compounds to add:**
1. 2-naphthyl dihydrogen phosphate (8 obs)
2. L-alanine 4-nitroanilide (6 obs)
3. bis-4-nitrophenyl-phosphorylcholine (2 obs)
4. bis-4-nitrophenyl-phenyl phosphonate (2 obs)

**Method:** ChEBI search + add to unified file with provenance

---

### Priority 4: Stereochemistry Fuzzy Matching (4 obs) 🔧

**Effort:** Already implemented!  
**Impact:** 4 observations  
**Status:** Check if `fuzzy_stereochemistry=True` is enabled

**Pattern:** `builds acid from: (-)-D-glucose`  
**Should match:** D-glucose (CHEBI:4167) - already in unified file

**Verification:**
```python
# Check if fuzzy matching is enabled in _resolve_chemical_trait()
chebi_id = self.chemical_loader.find_chebi_by_name(
    chemical_name, 
    fuzzy_stereochemistry=True  # <-- Is this set?
)
```

---

### Priority 5: Complex Mixtures (17 obs) ⏸️

**Recommendation:** Skip or use FOODON for food items

**Rationale:**
- Casitone, yeast extract, serum are undefined mixtures
- No single ChEBI ID appropriate
- Low observation count (2-5 each)
- Could use FOODON for food-derived items if needed

---

## Implementation Recommendations

### Quick Wins (< 1 hour, 102+ observations)

1. ✅ **Concentration prefix stripper** (15 min, 69 obs)
2. ✅ **pH preference handler** (30 min, 33 obs)
3. ✅ **Verify fuzzy stereochemistry enabled** (5 min, 4+ obs)

**Total:** 50 minutes, 106+ observations

---

### Medium Effort (1-2 hours, 18 observations)

4. **Chromogenic substrates curation** (1 hour, 18 obs)

---

### Low Priority (skip for now)

5. Complex mixtures (17 obs) - Low ROI
6. Rare antibiotics (244 obs, 122 patterns) - Long tail, diminishing returns

---

## Success Metrics

### Current State
- Total unmapped: 73,812
- Actionable unmapped: ~421 (0.6%)
- Yellow pigment (intentional): 73,391 (99.4%)

### After Quick Wins
- Expected unmapped: ~73,700
- Reduction: ~112 observations
- Effort: < 1 hour

### After All Priorities 1-4
- Expected unmapped: ~73,680
- Total reduction from baseline: 170,854 (69.9%)
- Effort: ~2 hours

---

## Code Changes Required

### 1. Concentration Prefix Stripper

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Location:** `_resolve_chemical_trait()` method  
**Change:**
```python
# Before ChEBI lookup, add:
import re
chemical_name_clean = re.sub(r'^\d+(\.\d+)?\s*%\s+', '', chemical_name)
chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name_clean)
```

---

### 2. pH Preference Handler

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Add new method:**
```python
def _resolve_ph_preference_trait(self, value: str) -> Optional[dict]:
    """
    Resolve pH preference to METPO acidophilic/alkaliphilic/neutrophilic.
    
    Maps continuous pH values to METPO phenotype classes.
    """
    # Parse pH value and map to METPO class
    # Similar to _resolve_ph_trait() binned ranges
```

**Add to dispatch chain in `_resolve_trait()`**

---

### 3. Enable Fuzzy Stereochemistry

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Check all ChEBI lookups:**
```python
# Verify this flag is set in all chemical lookup calls:
chebi_id = self.chemical_loader.find_chebi_by_name(
    chemical_name,
    fuzzy_stereochemistry=True  # <-- Add if missing
)
```

---

## Testing Plan

### Test 1: Concentration Prefix Stripper
```bash
# After implementation, verify:
grep "growth: 1 % sodium lactate" data/transformed/metatraits/unmapped_traits.tsv
# Should return 0 results if sodium lactate is in unified file
```

### Test 2: pH Preference Handler
```bash
# After implementation:
grep "pH preference" data/transformed/metatraits/unmapped_traits.tsv
# Should return 0 results
```

### Test 3: Fuzzy Stereochemistry
```bash
# After enabling:
grep "(-)-D-glucose" data/transformed/metatraits/unmapped_traits.tsv
# Should return 0 results
```

---

## Conclusion

**Current State:** Migration successful, transforms working ✅

**Remaining Work:** Opportunity to reduce ~112 more observations (< 1 hour effort)

**Diminishing Returns:** After quick wins, remaining unmapped is mostly:
- Yellow pigment (intentional skip)
- Rare antibiotics (long tail)
- Complex mixtures (low ROI)

**Recommendation:** Implement quick wins (Priorities 1-2), then consider work complete.

**Final Stats (after quick wins):**
- Total reduction from baseline: ~170,834 observations (69.9%)
- Remaining unmapped: ~73,700
- Intentional skips: ~73,400 (yellow pigment)
- True unmapped: ~300 (mostly rare antibiotics and complex mixtures)

---

**End of Analysis**
