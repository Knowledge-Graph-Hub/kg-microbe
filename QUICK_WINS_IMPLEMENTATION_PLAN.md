# Quick Wins Implementation Plan

**Date:** 2026-04-08  
**Branch:** `fix_metatraits`  
**Goal:** Reduce remaining unmapped by ~100+ observations in <1 hour

---

## Opportunity Summary

**Current unmapped:** 73,812 observations
- Yellow pigment (intentional): 73,391 (99.4%)
- **Actionable:** ~421 observations (0.6%)

**Quick win targets:** 102+ observations in 3 simple changes

---

## Quick Win 1: Concentration Prefix Stripper 🎯

**Impact:** 69 observations (sodium lactate patterns)  
**Effort:** 15 minutes  
**Priority:** HIGH

### Problem

Patterns like "growth: 1 % sodium lactate" fail ChEBI lookup because:
- Chemical name includes concentration: "1 % sodium lactate"
- Unified file has "sodium lactate" (CHEBI:75228)
- Direct match fails

### Evidence

```bash
# These chemicals ARE in unified file:
CHEBI:75228 - sodium lactate
CHEBI:91260 - disodium malate  
CHEBI:8013 - yeast extract
CHEBI:91043 - 2-naphthyl dihydrogen phosphate
```

**Affected patterns:**
- growth: 1 % sodium lactate (31 obs)
- carbon source: 1 % sodium lactate (18 obs)
- assimilation: 1 % sodium lactate (8 obs)
- respiration: 1 % sodium lactate (6 obs)
- oxidation: 1 % sodium lactate (6 obs)

### Solution

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Method:** `_resolve_chemical_trait()`  
**Change:** Strip concentration prefixes before ChEBI lookup

```python
def _resolve_chemical_trait(self, trait_name: str) -> Optional[dict]:
    """
    Resolve chemical-based trait patterns.
    ...
    """
    for pattern, metpo_predicate in self.chemical_patterns:
        match = re.match(pattern, trait_name, re.IGNORECASE)
        if match:
            chemical_name = match.group(1).strip().lower()
            
            # NEW: Strip concentration prefixes (e.g., "1 %", "0.01 %", "10 mM")
            # Pattern: digits + optional decimal + space + % or unit + space
            import re
            chemical_name = re.sub(r'^\d+(\.\d+)?\s*(%|mM|µM|mg/ml|g/l)\s+', '', chemical_name)
            
            if not self.chemical_loader:
                return None

            # Lookup chemical via unified mappings (includes synonyms)
            chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)
            # ... rest of method
```

### Verification

After implementation:
```bash
poetry run kg transform -s metatraits
grep "1 % sodium lactate" data/transformed/metatraits/unmapped_traits.tsv
# Should return 0 results
```

---

## Quick Win 2: pH Preference Skip Logic 🎯

**Impact:** 33 observations  
**Effort:** 5 minutes  
**Priority:** HIGH

### Problem

Traits with "No robust majority" are being output as unmapped instead of being skipped.

### Evidence

```
pH preference	Aridibacter famidurans	No robust majority	2
pH preference	Aureimonas ureilytica	No robust majority	2
```

All 33 "pH preference" unmapped have "No robust majority" as majority_label.

### Root Cause

The pH preference handler is likely already checking for this, but the check might not be working correctly or the value is formatted differently.

### Solution

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Method:** `_resolve_ph_trait()` or wherever pH is handled  
**Change:** Verify "No robust majority" check is working

```python
# In _resolve_ph_trait() or similar:
if value == "No robust majority" or not value or value.strip() == "":
    return None  # Skip, don't output as unmapped
```

**OR** check if these are being written to unmapped_traits before trait resolution.

### Investigation

```bash
# Find where pH preference is handled
grep -n "pH preference" kg_microbe/transform_utils/metatraits/metatraits.py
```

If no handler exists, these might be failing at pattern matching stage. In that case, skip them in the main processing loop before attempting trait resolution.

---

## Quick Win 3: Enable Fuzzy Stereochemistry 🎯

**Impact:** 4+ observations  
**Effort:** 5 minutes  
**Priority:** MEDIUM

### Problem

Pattern: `builds acid from: (-)-D-glucose`  
Expected match: D-glucose (CHEBI:4167)

### Evidence

ChEBI lookup utility already has `fuzzy_stereochemistry` parameter that strips prefixes like:
- `(-)–`, `(+)–`, `(R)–`, `(S)–`, `D–`, `L–`

From `chemical_mapping_utils.py`:
```python
def find_chebi_by_name(
    name: str,
    synonyms: bool = True,
    fuzzy_stereochemistry: bool = False  # <-- Available but not enabled
) -> Optional[str]:
```

### Solution

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`  
**Methods:** All ChEBI lookup calls  
**Change:** Enable fuzzy_stereochemistry flag

```python
# In _resolve_chemical_trait() and similar methods:
chebi_id = self.chemical_loader.find_chebi_by_name(
    chemical_name,
    fuzzy_stereochemistry=True  # <-- Add this flag
)
```

### Verification

After implementation:
```bash
grep "(-)-D-glucose" data/transformed/metatraits/unmapped_traits.tsv
# Should return 0 results
```

---

## Implementation Checklist

### Step 1: Concentration Prefix Stripper (15 min)

- [ ] Edit `kg_microbe/transform_utils/metatraits/metatraits.py`
- [ ] Find `_resolve_chemical_trait()` method
- [ ] Add regex to strip concentration prefixes
- [ ] Test: `python -m py_compile kg_microbe/transform_utils/metatraits/metatraits.py`
- [ ] Also update `metatraits_gtdb.py` if it overrides this method
- [ ] Commit: "Strip concentration prefixes from chemical names before ChEBI lookup"

### Step 2: pH Preference Investigation (5 min)

- [ ] Search for pH preference handling
- [ ] Verify "No robust majority" check exists
- [ ] If missing, add check to skip these values
- [ ] Test: `python -m py_compile`
- [ ] Commit: "Skip pH preference traits with no robust majority"

### Step 3: Enable Fuzzy Stereochemistry (5 min)

- [ ] Find all `self.chemical_loader.find_chebi_by_name()` calls
- [ ] Add `fuzzy_stereochemistry=True` parameter
- [ ] Test: `python -m py_compile`
- [ ] Commit: "Enable fuzzy stereochemistry matching for ChEBI lookups"

### Step 4: Test Full Transform (30 min)

- [ ] Run: `time poetry run kg transform -s metatraits`
- [ ] Check unmapped count: `wc -l data/transformed/metatraits/unmapped_traits.tsv`
- [ ] Expected: ~29,850 (down from 29,983)
- [ ] Verify sodium lactate patterns resolved
- [ ] Verify pH preference not in unmapped
- [ ] Run: `time poetry run kg transform -s metatraits_gtdb`  
- [ ] Check unmapped count: `wc -l data/transformed/metatraits_gtdb/unmapped_traits.tsv`
- [ ] Expected: ~43,700 (down from 43,829)

---

## Expected Results

### Before Quick Wins
- metatraits: 29,983 unmapped
- metatraits_gtdb: 43,829 unmapped
- **Total:** 73,812 unmapped

### After Quick Wins  
- metatraits: ~29,850 unmapped
- metatraits_gtdb: ~43,700 unmapped
- **Total:** ~73,550 unmapped
- **Reduction:** ~260 observations

### Breakdown
- Yellow pigment (intentional): 73,391
- Concentration prefix (fixed): 69
- pH preference (fixed): 33
- Fuzzy stereochemistry (fixed): 4+
- Remaining (long tail): ~150

---

## Alternative: More Comprehensive Concentration Handling

If simple prefix stripping works well, could expand to handle more patterns:

```python
def _clean_chemical_name(self, chemical_name: str) -> str:
    """
    Clean chemical name by removing common prefixes/modifiers.
    
    Removes:
    - Concentration prefixes: "1 %", "0.01 %", "10 mM", etc.
    - Parenthetical concentrations: "(0.01 %, w/v)"
    - Common modifiers: "growth on", "carbon from", etc.
    """
    import re
    
    # Remove concentration prefixes
    name = re.sub(r'^\d+(\.\d+)?\s*(%|mM|µM|μM|mg/ml|g/l|M)\s+', '', chemical_name)
    
    # Remove parenthetical concentrations
    name = re.sub(r'\s*\([^)]*%[^)]*\)\s*', ' ', name)
    
    # Trim whitespace
    name = name.strip()
    
    return name
```

This would also handle:
- "yeast extract (0.01 %, w/v)" → "yeast extract"
- "10 mM glucose" → "glucose"

---

## Files to Modify

1. `kg_microbe/transform_utils/metatraits/metatraits.py`
   - `_resolve_chemical_trait()` - add concentration prefix stripper
   - All `find_chebi_by_name()` calls - enable fuzzy_stereochemistry
   - pH handling - verify "No robust majority" skip

2. `kg_microbe/transform_utils/metatraits_gtdb/metatraits_gtdb.py`
   - Check if it overrides any chemical resolution methods
   - Apply same fixes if needed

---

## Risk Assessment

**Risk Level:** LOW

**Reasons:**
1. Concentration prefix stripping is conservative (only removes numeric prefixes)
2. Fuzzy stereochemistry is already implemented and tested
3. pH preference skip is defensive (avoids processing invalid data)
4. Changes are in trait resolution, not core transform logic
5. Easy to verify with transform test

**Rollback:** Simple git revert if issues arise

---

## Success Criteria

- [ ] All 3 quick wins implemented
- [ ] Both transforms run successfully
- [ ] Unmapped count reduced by ~100-260 observations
- [ ] No new errors introduced
- [ ] Code committed with clear messages

---

**Total Effort:** ~1 hour  
**Total Impact:** 100-260 observations  
**ROI:** Excellent for minimal effort

---

**End of Plan**
