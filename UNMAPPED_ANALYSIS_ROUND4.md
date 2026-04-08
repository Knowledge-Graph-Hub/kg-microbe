# Unmapped Traits Analysis - Round 4 (Post Quick Wins)

**Date:** 2026-04-08  
**Branch:** `fix_metatraits`  
**Status:** After Quick Wins implementation

---

## Summary

**Total Unmapped:** 73,749 observations across 288 unique patterns

**Breakdown:**
- Yellow pigment: 73,423 observations (99.6%) - **Intentionally skipped**
- Actionable unmapped: ~358 observations (0.4%) across 287 patterns
  - metatraits: 226 observations, 180 unique patterns
  - metatraits_gtdb: 132 observations, 107 unique patterns

**Quick Wins Impact:**
- Before: 73,812 unmapped
- After: 73,749 unmapped
- **Reduction:** 63 observations (0.08%)
- Note: Lower than expected 100+ reduction, but significant progress on pattern coverage

---

## Pattern Category Analysis

### Category 1: Rare Antibiotics (Long Tail) ⏸️

**Count:** 127 unique "produces" patterns  
**Total observations:** ~254  
**Status:** Diminishing returns - skip for now

**Top patterns (1-2 obs each):**
- setamycin (2)
- halomicin (2)
- primocarcin (2)
- monazomycin (2)
- gardimycin (2)
- aburamycin A (2)
- mycobacidin (3)
- ... and 120+ more rare compounds

**Recommendation:** Not cost-effective for <3 observations each

---

### Category 2: Catabolization Patterns (NEW!) 🎯

**Count:** 11 patterns (aerobic: 8, anaerobic: 3)  
**Total observations:** ~22  
**Status:** **New pattern type not currently handled**

**Aerobic catabolization:**
- (-)-quinic acid
- 2-oxoglutarate
- 4-hydroxybutyrate
- alpha-D-glucose
- D-fructose
- D-galactose
- cellobiose
- cis-aconitate

**Anaerobic catabolization:**
- cellobiose
- D-arabinose
- D-fructose

**METPO Analysis:**
- No "catabolization" predicate in METPO pattern mappings
- These are metabolic processes on chemical substrates
- Should map to GO terms for catabolism or use METPO metabolic predicates

**Implementation Options:**

**Option 1: Add catabolization pattern handler**
```python
# In _resolve_metabolic_trait() or new method
pattern_keywords = [
    ...,
    "aerobic catabolization",
    "anaerobic catabolization"
]
```

**Option 2: Skip as too specific**
- Only 11 patterns, ~22 observations
- May be BacDive-specific annotation
- Could be out of scope for general trait modeling

**Recommendation:** Option 2 - Skip for now (low observation count)

---

### Category 3: Concentration Prefix Issues (FIXABLE!) 🔧

**Count:** 5 patterns  
**Total observations:** ~24  
**Status:** Bug in implementation - concentration stripping not applied to all methods

**Affected patterns:**
- growth: 1 % sodium lactate (16 obs)
- builds acid from: 1 % sodium lactate (1 obs)
- respiration: 1 % sodium lactate (4 obs)
- oxidation: 1 % sodium lactate (4 obs)
- growth: yeast extract (0.01 %, w/v) (4 obs)
- growth: glycine 1% (unknown count)

**Root Cause:**
Quick Win 1 added concentration prefix stripping to `_resolve_chemical_trait()` (line 986-989), but NOT to:
- `_resolve_growth_substrate()` (line 1119-1152) - handles "growth:", "builds acid from:"
- `_resolve_metabolic_trait()` (line 1041-1091) - handles "respiration:", "oxidation:"

**Fix:**
Add same concentration stripping logic to both methods:
```python
# After extracting substrate_name, before ChEBI lookup:
# Strip concentration prefixes
substrate_name = re.sub(r'^\d+(\.\d+)?\s*(%|mM|µM|μM|mg/ml|g/l|M)\s+', '', substrate_name)
# Remove parenthetical concentrations
substrate_name = re.sub(r'\s*\([^)]*(%|w/v|v/v)[^)]*\)\s*', ' ', substrate_name).strip()
```

**Expected Impact:** 24+ observations

---

### Category 4: Disodium Salts 🔬

**Count:** 4 patterns (disodium fumarate, disodium malate)  
**Total observations:** ~8  
**Status:** ChEBI lookup failing for sodium salts

**Patterns:**
- carbon source: disodium fumarate (2 obs)
- carbon source: disodium malate (2 obs)
- assimilation: disodium fumarate (2 obs)
- assimilation: disodium malate (2 obs)

**ChEBI Investigation:**
```bash
# Check if these exist in ChEBI/unified file
gunzip -c mappings/unified_chemical_mappings.tsv.gz | grep -i "disodium fumarate"
gunzip -c mappings/unified_chemical_mappings.tsv.gz | grep -i "disodium malate"
```

**Options:**
1. Add to special_chemical_mappings if ChEBI IDs exist
2. Map to parent compound (fumarate, malate) and ignore sodium salt detail
3. Enable fuzzy matching that strips "disodium" prefix

**Recommendation:** Investigate ChEBI first, then decide approach

---

### Category 5: Stereochemistry Variants 🔧

**Count:** 17 patterns with stereochemistry notations  
**Total observations:** ~34  
**Status:** Fuzzy stereochemistry may not be working correctly

**Patterns:**
- aerobic catabolization: (-)-quinic acid
- aerobic catabolization: alpha-D-glucose
- aerobic catabolization: D-fructose
- aerobic catabolization: D-galactose
- anaerobic catabolization: D-arabinose
- anaerobic catabolization: D-fructose
- carbon source: (2)-D-lactose

**Analysis:**
Quick Win 3 enabled `fuzzy_stereochemistry=True` for `_resolve_chemical_trait()`, but:
1. Many of these are "catabolization" patterns (not handled by any resolver)
2. Need to verify fuzzy matching actually works for these notations

**Test:**
```python
# Check if fuzzy matching strips these prefixes:
# "(-)-quinic acid" → "quinic acid"
# "alpha-D-glucose" → "glucose" or "D-glucose"
# "(2)-D-lactose" → "lactose" or "D-lactose"
```

**Recommendation:** 
- If catabolization is skipped, most of these go away
- For remaining patterns, verify fuzzy matching works correctly

---

### Category 6: Chromogenic Substrates 🔬

**Count:** 6 unique compounds  
**Total observations:** ~12  
**Status:** Specialized enzymatic assay substrates

**Patterns:**
- 2-naphthyl dihydrogen phosphate (3 contexts: hydrolysis, assimilation, builds acid)
- L-alanine 4-nitroanilide (2 contexts: nitrogen source, assimilation)
- O-nitrophenyl-beta-D-galactopyranosid (1 context: hydrolysis)
- bis-4-nitrophenyl-phosphorylcholine (1 context: hydrolysis)
- bis-4-nitrophenyl-phenyl phosphonate (1 context: hydrolysis)
- 5-bromo-3-indolyl nonanoate (1 context: builds acid)

**Recommendation:** Add to unified file with ChEBI lookups (if available)

---

### Category 7: Complex Substrates (Food/Media) ⏸️

**Count:** 8 patterns  
**Total observations:** ~16  
**Status:** Undefined mixtures - low priority

**Patterns:**
- milk (3 contexts: assimilation, degradation, utilizes)
- skimmed milk (2 contexts: degradation, hydrolysis)
- casitone (growth)
- yeast extract (0.01 %, w/v) (growth) - also concentration issue
- serum (required for growth)
- proteose (growth)
- soyton (growth)

**Recommendation:** Skip or use FOODON for food items (low ROI)

---

### Category 8: Other Chemical Patterns 🔬

**Miscellaneous unmapped:**
- pyrite (oxidation, electron donor) - mineral, not ChEBI
- goethite (growth) - mineral (iron oxide)
- butamine (assimilation) - typo or rare compound?
- altrarate (builds acid from) - unknown compound
- esculin hydrolysate (reduction) - complex mixture

**Recommendation:** Manual investigation for each, likely skip

---

## Priority Recommendations

### Priority 1: Fix Concentration Prefix Stripping 🎯

**Effort:** 15 minutes  
**Impact:** 24+ observations  
**ROI:** High

**Files to modify:**
1. `kg_microbe/transform_utils/metatraits/metatraits.py`
   - `_resolve_growth_substrate()` (line ~1128, after substrate_name extraction)
   - `_resolve_metabolic_trait()` (line ~1059, after substrate_name extraction)

**Implementation:**
```python
# In _resolve_growth_substrate(), after line 1128:
substrate_name = match.group(1).strip()

# ADD:
# Strip concentration prefixes (e.g., "1 %", "0.01 %", "10 mM")
substrate_name = re.sub(r'^\d+(\.\d+)?\s*(%|mM|µM|μM|mg/ml|g/l|M)\s+', '', substrate_name)
# Remove parenthetical concentrations
substrate_name = re.sub(r'\s*\([^)]*(%|w/v|v/v)[^)]*\)\s*', ' ', substrate_name).strip()

# Then continue with non_chemical_patterns check...
```

**Repeat same for `_resolve_metabolic_trait()` around line 1059**

---

### Priority 2: Investigate Disodium Salts 🔬

**Effort:** 30 minutes  
**Impact:** 8 observations  
**ROI:** Medium

**Tasks:**
1. Check ChEBI for "disodium fumarate" and "disodium malate"
2. If ChEBI IDs exist, add to unified file with provenance
3. If not, add synonym mappings to fumarate/malate parent compounds
4. Test resolution

---

### Priority 3: Chromogenic Substrates Curation 🔬

**Effort:** 1 hour  
**Impact:** 12 observations  
**ROI:** Medium

**Tasks:**
1. ChEBI search for each compound
2. Add to unified file with provenance (manual curation source)
3. Test resolution

---

### Priority 4: Catabolization Patterns (OPTIONAL) ⏸️

**Effort:** 1 hour  
**Impact:** 22 observations  
**ROI:** Low-Medium

**Decision:** Skip for now unless these patterns are scientifically important
- Only 11 unique patterns
- May be too specific (BacDive annotation artifact)
- Could model later if needed

---

## Expected Results After Priority 1-3

### Before
- Total unmapped: 73,749
- Actionable (non-yellow): 358

### After Priority 1-3
- Expected unmapped: ~73,700
- Reduction: ~50 observations
- Remaining actionable: ~310

### Breakdown
- Concentration prefix fix: 24 obs
- Disodium salts: 8 obs
- Chromogenic substrates: 12 obs
- **Total reduction:** 44 observations

---

## Long-Term Low Priority

- Catabolization patterns: 22 obs (new pattern type)
- Rare antibiotics: 254 obs, 127 patterns (long tail)
- Complex substrates: 16 obs (food/media mixtures)
- Miscellaneous chemicals: 10 obs (minerals, unknowns)

**Total long-tail unmapped:** ~300 observations

---

## Success Metrics

### Current State
- Total unmapped: 73,749
- Yellow pigment (intentional): 73,423 (99.6%)
- Actionable: 358 (0.4%)

### After All Priority Work (1-3)
- Expected unmapped: ~73,700
- Yellow pigment: 73,423 (same)
- Actionable: ~310
- **Total reduction from baseline (244,534):** 170,834 (69.9%)

---

## Files to Modify

**Priority 1:**
- `kg_microbe/transform_utils/metatraits/metatraits.py`
  - `_resolve_growth_substrate()` - add concentration stripping
  - `_resolve_metabolic_trait()` - add concentration stripping

**Priority 2:**
- `mappings/unified_chemical_mappings.tsv.gz` - add disodium salts
- OR `kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv` - add synonym mappings

**Priority 3:**
- `mappings/unified_chemical_mappings.tsv.gz` - add chromogenic substrates with provenance

---

## Next Steps

1. **Implement Priority 1** (15 min) - Fix concentration prefix stripping
2. **Test transforms** - Verify ~24 observation reduction
3. **Commit changes** - "Fix: Add concentration prefix stripping to growth/metabolic resolvers"
4. **Investigate Priority 2** (30 min) - Disodium salts ChEBI lookup
5. **Optional: Priority 3** (1 hour) - Chromogenic substrates if high value

---

**End of Analysis**
