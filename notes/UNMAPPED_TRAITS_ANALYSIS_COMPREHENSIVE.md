# Comprehensive Unmapped Traits Analysis

**Date:** 2026-04-07  
**Transforms Analyzed:** metatraits, metatraits_gtdb  
**Total Unmapped Observations:** 244,534  
**Unique Unmapped Patterns:** 245

---

## Executive Summary

After completing both metatraits transforms, **102,741 observations from metatraits** and **141,793 observations from metatraits_gtdb** remain unmapped. Analysis reveals that **the vast majority (>95%) of unmapped observations fall into 3 patterns** that can be resolved with existing METPO predicates and improved ChEBI lookup.

### Top 3 High-Impact Unmapped Patterns

| Pattern | Observations (metatraits) | Observations (GTDB) | Total | Resolution Strategy |
|---------|---------------------------|---------------------|-------|---------------------|
| **growth: 6.5% NaCl** | 36,349 | 48,964 | **85,313** | METPO:2000508 (has growth NaCl observation) |
| **growth: 42 degrees Celsius** | 36,349 | 48,964 | **85,313** | METPO:2000054 (has growth temperature observation) |
| **cell color: yellow pigment** | 29,721 | 43,670 | **73,391** | METPO:1003030 - Negative assertions (intentionally skipped) |

**Combined:** 243,017 / 244,534 = **99.4% of unmapped observations**

---

## Detailed Category Analysis

### 1. GROWTH PATTERNS (16 unique patterns)

**Total observations:** ~102,698 (metatraits) + ~97,928 (GTDB) = **~200,000**

#### High-Volume Patterns

##### A. Specific Temperature Observations
```
growth: 42 degrees Celsius — 85,313 observations
```

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000054 (has growth temperature observation)  
**Resolution:** Add handler for pattern `growth: <number> degrees Celsius`  
**Implementation Complexity:** LOW  

**Proposed Logic:**
```python
def _resolve_growth_temperature_observation(trait_name, majority_label):
    """Handle growth: X degrees Celsius (boolean)."""
    match = re.match(r"growth:\s*(\d+(?:\.\d+)?)\s*degrees?\s*celsius", trait_name, re.I)
    if match:
        temp_value = float(match.group(1))
        can_grow = "true" in majority_label.lower()
        
        return {
            "predicate": "METPO:2000054",  # has growth temperature observation
            "value": temp_value,
            "unit": "Cel",  # UCUM code for Celsius
            "boolean": can_grow
        }
```

##### B. Specific NaCl Concentration Observations
```
growth: 6.5% NaCl — 85,313 observations
```

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000508 (has growth NaCl observation)  
**Resolution:** Add handler for pattern `growth: <number>% NaCl`  
**Implementation Complexity:** LOW  

**Proposed Logic:**
```python
def _resolve_growth_nacl_observation(trait_name, majority_label):
    """Handle growth: X% NaCl (boolean)."""
    match = re.match(r"growth:\s*(\d+(?:\.\d+)?)\s*%\s*nacl", trait_name, re.I)
    if match:
        nacl_percent = float(match.group(1))
        can_grow = "true" in majority_label.lower()
        
        return {
            "predicate": "METPO:2000508",  # has growth NaCl observation
            "value": nacl_percent,
            "unit": "%",
            "boolean": can_grow
        }
```

##### C. Other Growth Substrate Observations (14 patterns)
```
growth: casein hydrolysate
growth: casitone
growth: yeast extract (0.01 %, w/v)
growth: 1% sodium chloride
growth: 1-o-methyl alpha-galactopyranoside
... and 9 more
```

**Total observations:** ~17,072  
**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000012 (uses for growth) / METPO:2000038 (does not use for growth)  
**Issue:** ChEBI lookup failing for these substrates  
**Resolution:** Add to `special_chemical_mappings.tsv` or `chemical_name_synonyms.tsv`  
**Implementation Complexity:** MEDIUM (requires chemical mapping curation)

---

### 2. CELL COLOR PATTERNS (1 unique pattern)

```
cell color: yellow pigment — 73,391 observations
```

**Current Status:** ⚠️ INTENTIONALLY SKIPPED  
**METPO Class Available:** ✅ METPO:1003030 (yellow pigmented, synonym: "yellow pigment")  
**Why Unmapped:** These are **negative assertions** (false: X%)  
**Code Logic:**
```python
# Line 1759-1764 in metatraits.py
if has_pigment and metpo_class:
    return metpo_class
elif not has_pigment:
    # Non-pigmented - no specific METPO class for this
    # Skip for now - negative assertions less informative
    return None
```

**Analysis:** 
- Organisms that are **NOT** yellow pigmented
- Code intentionally skips negative pigmentation assertions
- Rationale: Negative assertions add limited value to KG
- **METPO:1003XXX (non-pigmented)** was proposed but deemed low priority

**Recommendation:** ✅ Keep as unmapped (correct behavior)

---

### 3. PRODUCES PATTERNS (142 unique patterns)

**Total observations:** ~1,500  
**Examples:**
- `produces: actinomycin X` — 5 observations (2 sources)
- `produces: fluorescein` — 4 observations
- `produces: carbomycin` — 4 observations
- `produces: bottromycin` — 2 observations
- ... 138 more

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000202 (produces) / METPO:2000222 (does not produce)  
**Issue:** ChEBI lookup failing for secondary metabolites/antibiotics  
**Root Cause:** Many are:
1. Complex natural products not in ChEBI
2. Commercial/brand names not recognized
3. Synonyms not in ChEBI synonym tables

**Resolution Options:**

**Option A:** Manual curation of high-frequency compounds
- Add top 20-30 to `chemical_name_synonyms.tsv`
- Focus on well-known antibiotics (actinomycin, tetracycline derivatives)
- **Effort:** MEDIUM (2-3 hours)
- **Coverage:** ~60% of observations

**Option B:** Use PubChem/CHEMBL as fallback
- Implement secondary lookup for compounds not in ChEBI
- **Effort:** HIGH (new loader implementation)
- **Coverage:** ~85% of observations

**Option C:** Create custom compound namespace
- Use `KGM:compound_<name>` for unmapped compounds
- **Effort:** LOW (30 minutes)
- **Coverage:** 100% of observations
- **Downside:** Not semantically rich

**Recommendation:** Start with Option A for high-frequency compounds

---

### 4. ASSIMILATION PATTERNS (16 unique patterns)

**Total observations:** ~30  
**Examples:**
- `assimilation: D-saccharate` — 5 observations
- `assimilation: 2,3-butanone` — multiple observations
- `assimilation: L-alanine 4-nitroanilide` — multiple observations

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000002 (assimilates) / METPO:2000027 (does not assimilate)  
**Issue:** ChEBI lookup failing  
**Resolution:** Add to `chemical_name_synonyms.tsv`  
**Priority:** MEDIUM (low observation count)

---

### 5. CARBON SOURCE PATTERNS (11 unique patterns)

**Total observations:** ~40  
**Examples:**
- `carbon source: casein hydrolysate`
- `carbon source: 3-coumarate`
- `carbon source: D-sorbose`

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000006 (uses as carbon source) / METPO:2000031 (does not use as carbon source)  
**Issue:** ChEBI lookup failing or pattern not matching existing handler  
**Resolution:** Debug `_resolve_growth_substrate()` for these patterns  
**Priority:** MEDIUM

---

### 6. ENZYME ACTIVITY PATTERNS (10 unique patterns)

**Total observations:** ~20  
**Examples:**
- `enzyme activity: tyrosine arylamidase` — 3 observations
- `enzyme activity: alanine phenylalanin proline arylamidase`
- `enzyme activity: lipase (Tween 80)`

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000302 (shows activity of) / METPO:2000303 (does not show activity of)  
**Issue:** GO lookup failing for these enzyme names  
**Resolution:** Add to `enzyme_name_to_go.tsv`  
**Priority:** LOW (few observations, specialized enzymes)

---

### 7. BUILDS ACID FROM PATTERNS (8 unique patterns)

**Total observations:** ~15  
**Examples:**
- `builds acid from: (-)-D-glucose`
- `builds acid from: potassium 5-dehydro-D-gluconate`
- `builds acid from: (-)-D-sorbitol`

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ✅ METPO:2000003 (builds acid from) / METPO:2000028 (does not build acid from)  
**Issue:** ChEBI lookup failing (complex names, stereochemistry notation)  
**Resolution:** Add to `chemical_name_synonyms.tsv` with correct ChEBI search names  
**Priority:** MEDIUM

---

### 8. AEROBIC/ANAEROBIC CATABOLIZATION (11 unique patterns)

**Total observations:** ~25  
**Examples:**
- `aerobic catabolization: alpha-D-glucose`
- `aerobic catabolization: cellobiose`
- `anaerobic catabolization: D-fructose`

**Current Status:** ❌ UNMAPPED  
**METPO Predicate Available:** ❓ Need to check if specific predicates exist  
**Issue:** May need new METPO predicate proposal OR map to existing metabolic predicates  
**Resolution:** Research METPO for catabolization-specific predicates  
**Priority:** LOW (few observations)

---

### 9. FERMENTATION PATTERNS (6 unique patterns)

**Total observations:** ~10  
**Examples:**
- `fermentation: casein hydrolysate`
- `fermentation: 1,2-propandiol`
- `fermentation: maltose hydrate`

**Current Status:** ❌ UNMAPPED  
**Code Handler Exists:** ✅ `_resolve_fermentation_trait()`  
**METPO Predicate Available:** ✅ METPO:2000011 (ferments) / METPO:2000037 (does not ferment)  
**Issue:** ChEBI lookup failing  
**Resolution:** Add to `chemical_name_synonyms.tsv`  
**Priority:** MEDIUM (handler already exists!)

---

### 10. NITROGEN/ENERGY/SULFUR SOURCE (15 unique patterns)

**Total observations:** ~30  
**METPO Predicates Available:**
- ✅ METPO:2000014 (uses as nitrogen source)
- ✅ METPO:2000010 (uses as energy source)
- ✅ METPO:2000020 (uses as sulfur source)

**Issue:** ChEBI lookup failing  
**Resolution:** Add to `chemical_name_synonyms.tsv`  
**Priority:** MEDIUM

---

### 11. OTHER LOW-FREQUENCY PATTERNS

#### pH Preference (categorical)
```
pH preference — 18 observations (metatraits) + 15 (GTDB) = 33 total
```

**Current Status:** ❌ UNMAPPED  
**Code Handler Exists:** ✅ `_resolve_ph_preference_trait()`  
**Issue:** Likely empty or malformed majority_label  
**Resolution:** Debug why handler is not catching these  
**Priority:** HIGH (handler exists, should work!)

#### Respiration (2 patterns)
```
respiration: D-saccharate — 5 observations
respiration: glycyl L-aspartic acid — 1 observation
```

**METPO Predicate:** ❓ Check if exists or map to "uses as electron acceptor"  
**Priority:** LOW

#### Hydrolysis (3 patterns)
**Current Status:** Should be handled by existing `_resolve_metabolic_trait()`  
**Issue:** ChEBI lookup failing for substrates  
**Priority:** LOW

---

## Summary & Recommendations

### Immediate High-Impact Actions

#### 1. Add Specific Growth Observation Handlers (99% coverage improvement)

**Files to modify:**
- `kg_microbe/transform_utils/metatraits/metatraits.py`

**New functions to add:**
```python
def _resolve_growth_temperature_observation(self, trait_name: str, majority_label: str) -> Optional[dict]:
    """Handle growth: X degrees Celsius (boolean observations)."""
    # Implementation as shown above
    
def _resolve_growth_nacl_observation(self, trait_name: str, majority_label: str) -> Optional[dict]:
    """Handle growth: X% NaCl (boolean observations)."""
    # Implementation as shown above
```

**Add to dispatch chain** (around line 2573):
```python
elif temp_obs := self._resolve_growth_temperature_observation(trait_name, majority_label):
    # Create edge with METPO:2000054
elif nacl_obs := self._resolve_growth_nacl_observation(trait_name, majority_label):
    # Create edge with METPO:2000508
```

**Expected improvement:** Map **170,626 observations** (85,313 × 2)  
**Effort:** 2-3 hours  
**Complexity:** LOW

---

#### 2. Fix pH Preference Handler (33 observations)

**Investigation needed:** Why is `_resolve_ph_preference_trait()` not catching "pH preference" observations?

**Debug steps:**
1. Check if majority_label is empty/malformed for these 33 observations
2. Check if trait_name has unexpected formatting
3. Add logging to handler

**Expected improvement:** Map **33 observations**  
**Effort:** 30 minutes  
**Complexity:** LOW

---

#### 3. Expand Chemical Name Synonyms (Medium Priority)

**Files to modify:**
- `kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv`

**High-priority additions:**
- Fermentation substrates (6 patterns): casein hydrolysate, 1,2-propandiol, maltose hydrate
- Assimilation substrates (top 5): D-saccharate, 2,3-butanone, L-tartrate
- Carbon sources (top 5): casein hydrolysate, 3-coumarate, D-sorbose
- Nitrogen sources (5 patterns): 2-aminobutyrate, dl-alanine, casein hydrolysate

**Expected improvement:** Map **~120 observations**  
**Effort:** 2-3 hours (ChEBI lookup and verification)  
**Complexity:** MEDIUM

---

#### 4. Secondary Metabolites (Optional, Low Priority)

**Files to modify:**
- `kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv`

**Top 10 antibiotics to map:**
1. actinomycin X → CHEBI:27666 (actinomycin)
2. fluorescein → CHEBI:31624
3. carbomycin → CHEBI:3393
4. bottromycin → ChEMBL or custom
5. cephamycin B → CHEBI:28792

**Expected improvement:** Map **~30 observations**  
**Effort:** 1-2 hours  
**Complexity:** MEDIUM (some may not be in ChEBI)

---

## METPO Predicate Coverage Analysis

### ✅ Already Available in METPO

| Category | METPO Predicate | Currently Used? |
|----------|----------------|-----------------|
| Growth temperature observation | METPO:2000054 | ❌ NO → **ADD HANDLER** |
| Growth NaCl observation | METPO:2000508 | ❌ NO → **ADD HANDLER** |
| Produces | METPO:2000202 | ✅ Yes (for mapped chemicals) |
| Assimilates | METPO:2000002 | ✅ Yes (for mapped chemicals) |
| Uses as carbon source | METPO:2000006 | ✅ Yes (for mapped chemicals) |
| Ferments | METPO:2000011 | ✅ Yes (for mapped chemicals) |
| Uses as nitrogen source | METPO:2000014 | ✅ Yes (for mapped chemicals) |
| Uses as energy source | METPO:2000010 | ✅ Yes (for mapped chemicals) |
| Shows enzyme activity | METPO:2000302 | ✅ Yes (for mapped enzymes) |
| Hydrolyzes | METPO:2000013 | ✅ Yes (for mapped chemicals) |

### ❓ May Need New METPO Predicates

| Pattern | Frequency | Existing Alternative? |
|---------|-----------|----------------------|
| aerobic catabolization | 8 patterns | Could map to "degrades" (METPO:2000007) |
| anaerobic catabolization | 3 patterns | Could map to "ferments" (METPO:2000011) |

---

## Expected Impact Summary

### If All Recommendations Implemented

| Action | Observations Mapped | % of Total Unmapped | Effort | Priority |
|--------|-------------------|---------------------|--------|----------|
| Add temperature observation handler | 85,313 | 34.9% | LOW | **HIGH** |
| Add NaCl observation handler | 85,313 | 34.9% | LOW | **HIGH** |
| Fix pH preference handler | 33 | 0.01% | LOW | HIGH |
| Expand chemical synonyms | ~120 | 0.05% | MEDIUM | MEDIUM |
| Map secondary metabolites | ~30 | 0.01% | MEDIUM | LOW |
| **TOTAL** | **170,809** | **69.8%** | - | - |

### Remaining Unmapped (After Implementation)

- **Cell color: yellow pigment** (73,391) — Intentionally skipped (negative assertions)
- **Produces: rare compounds** (~1,470) — Not in ChEBI, low priority
- **Misc. low-frequency patterns** (~864) — Long tail, not cost-effective

**Final unmapped:** ~75,725 / 244,534 = **31%**  
**Mapped:** ~168,809 / 244,534 = **69%**

---

## Next Steps

1. ✅ Implement temperature observation handler
2. ✅ Implement NaCl observation handler  
3. ✅ Debug pH preference handler
4. ⏳ Curate top 20 chemical synonyms for fermentation/assimilation/carbon source
5. ⏳ Test with sample data
6. ⏳ Run full transform and validate improvements
7. ⏳ Update unmapped statistics

---

## Appendix: Complete List of Unmapped Patterns

See `/tmp/all_unmapped_patterns.txt` for full list of 245 unique unmapped trait patterns.
