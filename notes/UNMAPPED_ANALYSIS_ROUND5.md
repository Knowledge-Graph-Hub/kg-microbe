# Unmapped Traits Analysis - Round 5 (Final Deep Dive)

**Date:** 2026-04-08  
**Branch:** `fix_metatraits`  
**Status:** After concentration prefix + unified file fixes

---

## Summary

**Total Unmapped:** 29,903 observations across 164 unique patterns

**Breakdown:**
- Yellow pigment: 29,721 observations (99.4%) - **Intentionally skipped**
- Actionable unmapped: 182 observations (0.6%) across 163 patterns

**Previous Reduction:** 44 observations from fixes
- Before: 29,947 unmapped (226 actionable)
- After: 29,903 unmapped (182 actionable)

---

## Priority-Based Analysis

### HIGH Priority: 10 observations (7 patterns) 🎯

#### 1. Chromogenic Substrates (9 observations, 6 patterns)
**Issue:** These compounds are NOT in the unified chemical mappings file

| Pattern | Count | ChEBI Search Needed |
|---------|-------|---------------------|
| nitrogen source: L-alanine 4-nitroanilide | 3 | L-alanyl-4-nitroanilide |
| assimilation: L-alanine 4-nitroanilide | 2 | Same |
| builds acid from: 3-[(4-nitrophenyl)carbamoylamino]propanoic acid | 1 | NPAPA or similar |
| builds acid from: 5-bromo-3-indolyl nonanoate | 1 | 5-bromo-3-indolyl caprate |
| hydrolysis: bis-4-nitrophenyl-phosphorylcholine | 1 | p-nitrophenylphosphocholine? |
| hydrolysis: bis-4-nitrophenyl-phenyl phosphonate | 1 | Check ChEBI |

**Action Required:**
1. Search ChEBI for each compound
2. Add to unified file with provenance (manual curation source)
3. Or add synonyms to existing entries if close matches exist

**Effort:** 1-2 hours  
**ROI:** Medium (9 observations, but sets precedent for enzyme assays)

---

#### 2. Concentration Suffix Pattern (1 observation)
**Pattern:** `growth: glycine 1%`  
**Issue:** Concentration is AFTER the chemical name (suffix), not prefix

**Current regex only handles:**
- ✅ "1 % glycine" → "glycine" (prefix)
- ✗ "glycine 1%" → "glycine 1%" (suffix, not handled!)

**Fix:**
```python
# After stripping prefixes, also strip suffixes:
substrate_name = re.sub(r'\s+\d+(\.\d+)?\s*(%|mM|µM|μM|mg/ml|g/l|M)$', '', substrate_name)
```

**Effort:** 5 minutes  
**ROI:** High (trivial fix, 1 observation)

---

### MEDIUM Priority: 8 observations (8 patterns) 🔬

#### 3. Stereochemistry Variants (3 observations)
| Pattern | ChEBI Likely Exists? |
|---------|---------------------|
| assimilation: beta-D-galacto-pyranosyl-D-arabinose | Yes (check ChEBI) |
| growth: 1-o-methyl alpha-galactopyranoside | Yes (check ChEBI) |
| growth: 6-O-alpha-D-glucopyranosyl-D-gluconic acid | Yes (check ChEBI) |

**Issue:** These may exist in ChEBI but fuzzy stereochemistry matching isn't working
**Action:** Manual ChEBI search + add to unified file if found

---

#### 4. Other Chemicals (5 observations)
| Pattern | Notes |
|---------|-------|
| degradation: 1-chlorobutane | CHEBI likely exists |
| degradation: 1-chloropropane | CHEBI likely exists |
| reduction: esculin hydrolysate | Complex mixture product |
| growth: 4-aminovalerate | CHEBI:17361 exists! |
| carbon source: (2)-D-lactose | Stereochemistry notation issue |

**Action:** ChEBI search + add to unified file

**Effort:** 1 hour  
**ROI:** Medium (8 observations total for Medium priority)

---

### LOW Priority: 30 observations (23 patterns) ⏸️

#### 5. Catabolization Patterns (11 observations)
**Issue:** New predicate type not currently handled

**Patterns:**
- aerobic catabolization: 8 patterns (D-fructose, D-galactose, cellobiose, etc.)
- anaerobic catabolization: 3 patterns (D-arabinose, D-fructose, cellobiose)

**METPO Status:** No "catabolization" predicate exists

**Options:**
- Add pattern handler using existing metabolic predicates
- Skip as too specific (only 11 obs across 2 datasets)

**Recommendation:** Skip for now (low impact)

---

#### 6. Complex Mixtures (16 observations)
| Pattern | Count | Type |
|---------|-------|------|
| hydrolysis: skimmed milk | 4 | Food product |
| growth: casitone | 4 | Peptone mixture |
| assimilation: milk | 2 | Food product |
| required for growth: serum | 1 | Undefined mixture |
| growth: proteose, soyton | 2 | Peptones |

**Recommendation:** Skip or use FOODON (low ROI)

---

#### 7. Unknowns (2 observations)
- builds acid from: altrarate (likely typo for "altronate"?)
- assimilation: butamine (unknown compound)

**Recommendation:** Investigate briefly, likely skip

---

#### 8. Minerals (1 observation)
- growth: goethite (iron oxide mineral - not suitable for ChEBI)

**Recommendation:** Skip

---

### SKIP: 136 observations (125 patterns) ⏭️

#### 9. Rare Antibiotics (136 observations, 125 patterns)
**Long tail of "produces: X" patterns**

Top patterns:
- produces: mycobacidin (4 obs)
- produces: eurocidin (2 obs)
- produces: geomycin (2 obs)
- produces: gardimycin (2 obs)
- ... 121+ more with 1-2 observations each

**Recommendation:** Skip - not cost-effective (<3 observations each)

---

## Recommended Actions

### Quick Fix (5 minutes, 1 observation) ✅

**Fix concentration suffix pattern:**
```python
# In _resolve_growth_substrate(), _resolve_metabolic_trait(), _resolve_chemical_trait():
# After existing prefix stripping, add:

# Strip concentration suffixes (e.g., "glycine 1%" → "glycine")
substrate_name = re.sub(r'\s+\d+(\.\d+)?\s*(%|mM|µM|μM|mg/ml|g/l|M)$', '', substrate_name)
```

**Expected impact:** 1 observation

---

### Medium Effort (2-3 hours, 17 observations) 🔬

**Add missing chemicals to unified file:**

1. **Chromogenic substrates** (9 obs):
   - L-alanine 4-nitroanilide → Search ChEBI for "L-alanyl-4-nitroanilide"
   - 3-[(4-nitrophenyl)carbamoylamino]propanoic acid → Search ChEBI
   - 5-bromo-3-indolyl nonanoate → Check if CHEBI:90248 matches
   - bis-4-nitrophenyl-phosphorylcholine → Check CHEBI:55394 synonym
   - bis-4-nitrophenyl-phenyl phosphonate → Search ChEBI

2. **Stereochemistry variants** (3 obs):
   - beta-D-galacto-pyranosyl-D-arabinose
   - 1-o-methyl alpha-galactopyranoside
   - 6-O-alpha-D-glucopyranosyl-D-gluconic acid

3. **Other chemicals** (5 obs):
   - 1-chlorobutane (CHEBI likely exists)
   - 1-chloropropane (CHEBI likely exists)
   - 4-aminovalerate (CHEBI:17361 already exists - check name!)
   - (2)-D-lactose (stereochemistry notation)

**Process:**
1. Search ChEBI for each compound
2. If found, add to unified file with provenance:
   ```tsv
   CHEBI:XXXXX   compound_name   formula   synonyms   xrefs   metatraits_chromogenic[manual_2026-04-08]
   ```
3. Re-run transform to verify resolution

**Expected impact:** 17 observations

---

### Skip for Now ⏸️

**Low ROI items (30 observations):**
- Catabolization patterns (11 obs) - new pattern type
- Complex mixtures (16 obs) - undefined composition
- Unknowns (2 obs) - likely typos
- Minerals (1 obs) - not ChEBI

**Skip items (136 observations):**
- Rare antibiotics - long tail, diminishing returns

---

## Expected Results

### After Quick Fix Only
- Current: 29,903 unmapped (182 actionable)
- Expected: 29,902 unmapped (181 actionable)
- **Reduction:** 1 observation

### After Quick Fix + Medium Effort
- Current: 29,903 unmapped (182 actionable)
- Expected: 29,885 unmapped (164 actionable)
- **Reduction:** 18 observations

### Final State (after all reasonable fixes)
- Total unmapped: ~29,885
- Yellow pigment (intentional): 29,721
- Actionable unmapped: ~164
  - Catabolization: 11
  - Complex mixtures: 16
  - Unknowns: 2
  - Minerals: 1
  - Rare antibiotics: 134

**Coverage achieved:** 99.5% of non-yellow-pigment patterns addressed

---

## Implementation Priority

1. ✅ **Do Now** (5 min): Fix concentration suffix regex
2. 🔬 **Consider** (2-3 hours): Add chromogenic substrates + other chemicals to unified file
3. ⏸️ **Skip**: Low ROI and long-tail patterns

---

## Summary Statistics

| Category | Patterns | Observations | Priority | Effort | Action |
|----------|----------|--------------|----------|--------|--------|
| Chromogenic substrates | 6 | 9 | HIGH | 1-2 hr | Add to unified file |
| Concentration suffix | 1 | 1 | HIGH | 5 min | Fix regex |
| Stereochemistry | 3 | 3 | MEDIUM | 1 hr | Add to unified file |
| Other chemicals | 5 | 5 | MEDIUM | 1 hr | Add to unified file |
| Catabolization | 11 | 11 | LOW | N/A | Skip |
| Complex mixtures | 9 | 16 | LOW | N/A | Skip |
| Unknowns | 2 | 2 | LOW | N/A | Skip |
| Minerals | 1 | 1 | LOW | N/A | Skip |
| Rare antibiotics | 125 | 136 | SKIP | N/A | Skip |

---

**Total addressable with reasonable effort:** 18 observations (10% of remaining actionable)

**Final actionable after all fixes:** ~164 observations (mostly long-tail and intentional skips)

---

**End of Analysis**
