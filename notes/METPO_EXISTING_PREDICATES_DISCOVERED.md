# CRITICAL DISCOVERY: METPO Predicates Already Exist!

**Date:** 2026-04-03  
**Status:** 🚨 URGENT - Major revision needed  
**Impact:** Most proposed predicates ALREADY EXIST in METPO  

---

## Summary

Checked the actual METPO ontology (data/raw/metpo.json) and discovered:

✅ **ALL Phase 2 predicates EXIST** (4/4)  
✅ **ALL Phase 3 predicates EXIST** (3/3)  
✅ **Phase 1 quantitative properties EXIST** (different naming convention)  
✅ **Many Phase 4 genomic/morphological properties EXIST**

**Result:** We should NOT request these terms - just USE the existing METPO IDs!

---

## Phase 2: Core Metabolic Predicates - ALL EXIST ✅

| Our Proposal | Proposed ID | **ACTUAL METPO ID** | **ACTUAL Label** | Status |
|--------------|-------------|---------------------|------------------|--------|
| assimilates | METPO:2000021 | **METPO:2000002** | **assimilates** | ✅ EXISTS |
| uses as energy source | METPO:2000022 | **METPO:2000010** | **uses as energy source** | ✅ EXISTS |
| uses as nitrogen source | METPO:2000023 | **METPO:2000014** | **uses as nitrogen source** | ✅ EXISTS |
| uses as electron donor | METPO:2000024 | **METPO:2000009** | **uses as electron donor** | ✅ EXISTS |

**Action:** Use existing METPO IDs (2000002, 2000010, 2000014, 2000009) in transforms

---

## Phase 3: Production Predicates - ALL EXIST ✅

| Our Proposal | Proposed ID | **ACTUAL METPO ID** | **ACTUAL Label** | Status |
|--------------|-------------|---------------------|------------------|--------|
| produces acid from | METPO:2000025 | **METPO:2000003** | **builds acid from** | ✅ EXISTS |
| produces gas from | METPO:2000026 | **METPO:2000005** | **builds gas from** | ✅ EXISTS |
| produces base from | METPO:2000027 | **METPO:2000004** | **builds base from** | ✅ EXISTS |

**Action:** Use existing METPO IDs (2000003, 2000005, 2000004) in transforms

**Note:** METPO uses "builds" instead of "produces from" - semantically equivalent

---

## Phase 1: Quantitative Properties - EXIST with Different Naming ✅

### Our Proposal (data property style)

| Our Proposal | Proposed ID | Type |
|--------------|-------------|------|
| has_growth_temperature_optimum | METPO:has_growth_temperature_optimum | DatatypeProperty |
| has_growth_temperature_minimum | METPO:has_growth_temperature_minimum | DatatypeProperty |
| has_growth_temperature_maximum | METPO:has_growth_temperature_maximum | DatatypeProperty |

### METPO Actual (observation/value style)

| **ACTUAL METPO ID** | **ACTUAL Label** | Type | Status |
|---------------------|------------------|------|--------|
| **METPO:2000701** | **has growth temperature value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000702** | **has minimum temperature value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000703** | **has maximum temperature value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000704** | **has growth pH value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000705** | **has minimum pH value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000706** | **has maximum pH value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000707** | **has growth salinity value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000708** | **has minimum salinity value** | DatatypeProperty | ✅ EXISTS |
| **METPO:2000709** | **has maximum salinity value** | DatatypeProperty | ✅ EXISTS |

**Difference:** METPO uses "value" suffix instead of "optimum/minimum/maximum" in property name, but semantically equivalent.

**Action:** Use existing METPO IDs (2000701-2000709) in transforms

---

## BONUS: Phase 4 Genomic/Morphological Properties - MANY EXIST ✅

| **ACTUAL METPO ID** | **ACTUAL Label** | Our Phase 4 Proposal | Status |
|---------------------|------------------|----------------------|--------|
| **METPO:2000711** | **has genome size value** | genome size | ✅ EXISTS |
| **METPO:2000712** | **has estimated genome size value** | estimated genome size | ✅ EXISTS |
| **METPO:2000713** | **has gene count value** | gene count | ✅ EXISTS |
| **METPO:2000714** | **has estimated gene count value** | estimated gene count | ✅ EXISTS |
| **METPO:2000715** | **has GC percentage value** | GC content percentage | ✅ EXISTS |
| **METPO:2000716** | **has coding density value** | coding density | ✅ EXISTS |
| **METPO:2000721** | **has cell length value** | cell length | ✅ EXISTS |
| **METPO:2000722** | **has cell width value** | cell width | ✅ EXISTS |
| **METPO:2000723** | **has minimum cell length value** | cell length minimum | ✅ EXISTS |
| **METPO:2000724** | **has maximum cell length value** | cell length maximum | ✅ EXISTS |
| **METPO:2000725** | **has minimum cell width value** | cell width minimum | ✅ EXISTS |
| **METPO:2000726** | **has maximum cell width value** | cell width maximum | ✅ EXISTS |

**Action:** Use existing METPO IDs for these genomic/morphological properties

---

## Complete METPO 2000xxx Predicate Landscape

### Chemical Interaction Predicates (Positive)

| ID | Label | Coverage in Our Data |
|----|-------|---------------------|
| 2000001 | organism interacts with chemical | Generic |
| **2000002** | **assimilates** | **266 traits** ← WE NEED THIS |
| **2000003** | **builds acid from** | **28 traits** ← WE NEED THIS |
| **2000004** | **builds base from** | **7 traits** ← WE NEED THIS |
| **2000005** | **builds gas from** | **16 traits** ← WE NEED THIS |
| 2000006 | uses as carbon source | Already using |
| 2000007 | degrades | Already using |
| 2000008 | uses as electron acceptor | Already using |
| **2000009** | **uses as electron donor** | **53 traits** ← WE NEED THIS |
| **2000010** | **uses as energy source** | **97 traits** ← WE NEED THIS |
| 2000011 | ferments | Already using |
| 2000012 | uses for growth | Available |
| 2000013 | hydrolyzes | Already using |
| **2000014** | **uses as nitrogen source** | **57 traits** ← WE NEED THIS |
| 2000015 | uses in other way | Available |
| 2000016 | oxidizes | Already using |
| 2000017 | reduces | Already using |
| 2000018 | requires for growth | Available |
| 2000019 | uses for respiration | Available |
| 2000020 | uses as sulfur source | Available |

### Chemical Interaction Predicates (Negative)

| ID | Label |
|----|-------|
| 2000027 | does not assimilate |
| 2000028 | does not build acid from |
| 2000029 | does not build base from |
| 2000030 | does not build gas from |
| 2000031 | does not use as carbon source |
| 2000034 | does not use as electron acceptor |
| 2000035 | does not use as electron donor |
| 2000036 | does not use as energy source |
| 2000037 | does not ferment |
| 2000040 | does not use as nitrogen source |
| (etc.) | ... |

### Additional Growth/Catabolization Predicates

| ID | Label |
|----|-------|
| 2000032 | uses for aerobic catabolization |
| 2000043 | uses for aerobic growth |
| 2000048 | uses for anaerobic catabolization |
| 2000049 | uses for anaerobic growth |
| 2000601 | denitrifies |
| 2000603 | ammonifies |
| 2000605 | oxidizes in darkness |

### Production/Transport Predicates

| ID | Label |
|----|-------|
| 2000200 | disproportionates |
| 2000202 | produces |
| 2000207 | transports |
| 2000208 | imports |
| 2000209 | exports |
| 2000210 | accumulates |
| 2000211 | sequesters |
| 2000212 | compartmentalizes |

### Quantitative Data Properties (2000700-2000799 range)

| ID | Label | Use For |
|----|-------|---------|
| **2000701** | **has growth temperature value** | **Optimum temperature** |
| **2000702** | **has minimum temperature value** | **Min temperature** |
| **2000703** | **has maximum temperature value** | **Max temperature** |
| **2000704** | **has growth pH value** | **Optimum pH** |
| **2000705** | **has minimum pH value** | **Min pH** |
| **2000706** | **has maximum pH value** | **Max pH** |
| **2000707** | **has growth salinity value** | **Optimum NaCl** |
| **2000708** | **has minimum salinity value** | **Min NaCl** |
| **2000709** | **has maximum salinity value** | **Max NaCl** |
| **2000711** | **has genome size value** | **Genome size** |
| **2000712** | **has estimated genome size value** | **Estimated genome size** |
| **2000713** | **has gene count value** | **Gene count** |
| **2000714** | **has estimated gene count value** | **Estimated gene count** |
| **2000715** | **has GC percentage value** | **GC%** |
| **2000716** | **has coding density value** | **Coding density** |
| **2000721** | **has cell length value** | **Cell length** |
| **2000722** | **has cell width value** | **Cell width** |
| **2000723** | **has minimum cell length value** | **Min cell length** |
| **2000724** | **has maximum cell length value** | **Max cell length** |
| **2000725** | **has minimum cell width value** | **Min cell width** |
| **2000726** | **has maximum cell width value** | **Max cell width** |
| 2000730-2000734 | ecology metrics | Various |

---

## Impact on Our Proposals

### What We DON'T Need to Request from METPO

❌ **Phase 2 predicates** - ALL EXIST (use 2000002, 2000009, 2000010, 2000014)  
❌ **Phase 3 predicates** - ALL EXIST (use 2000003, 2000004, 2000005)  
❌ **Phase 1 quantitative properties** - ALL EXIST (use 2000701-2000709)  
❌ **Many Phase 4 genomic/morphological** - MOST EXIST (use 2000711-2000726)  

### What We MIGHT Still Need to Request

✅ **Phase 4 classes** - Phenotypic quality classes (oxygen requirement, flagellar arrangement, etc.)  
✅ **Biochemical test classes** - indole, methyl red, hemolysis  
✅ **Some growth characteristic classes** - selective media growth, bile resistance, biosafety level  

**But even these might exist!** Need to check METPO classes (1000xxx range).

---

## Revised Coverage Estimate

### Before (Our Proposal)
- Request 47 new METPO terms
- Achieve 85% coverage

### After (Using Existing Terms)
- Request **~0-15 new METPO terms** (only if specific classes missing)
- Achieve **same 85% coverage** using EXISTING predicates
- **Immediate implementation** - no waiting for METPO approval!

---

## Immediate Action Items

1. **CANCEL new predicate requests** for Phases 1-3 (all exist)
2. **Update transform code** to use existing METPO IDs:
   - Use METPO:2000002 instead of proposed 2000021 (assimilates)
   - Use METPO:2000010 instead of proposed 2000022 (energy source)
   - Use METPO:2000014 instead of proposed 2000023 (nitrogen source)
   - Use METPO:2000009 instead of proposed 2000024 (electron donor)
   - Use METPO:2000003 instead of proposed 2000025 (builds acid from)
   - Use METPO:2000005 instead of proposed 2000026 (builds gas from)
   - Use METPO:2000004 instead of proposed 2000027 (builds base from)
   - Use METPO:2000701-2000709 for quantitative properties
3. **Check METPO classes** (1000xxx range) to see what Phase 4 terms exist
4. **Update all proposal documents** to reflect existing terms
5. **Implement immediately** - no need to wait for METPO maintainer approval!

---

## Why Didn't We Know This Before?

**Reasons:**
1. METPO documentation (docs/METPO_PREDICATES.md) was incomplete
2. Only listed ~30 predicates, but METPO has 100+ predicates
3. Recent METPO additions (2000700+ range) not documented
4. Assumed missing terms without checking actual ontology

**Lesson:** Always check the actual ontology file, not just documentation!

---

## Next Steps

1. ✅ Search METPO for remaining Phase 4 classes
2. ✅ Create corrected mapping table (proposed → existing)
3. ✅ Update transform code to use existing METPO IDs
4. ✅ Test with sample data
5. ✅ Run full transforms
6. ✅ Update documentation with correct METPO IDs

**Timeline:** Can implement IMMEDIATELY instead of waiting weeks for METPO approval!

---

**This is excellent news!** We can achieve 85% coverage using existing METPO terms without requesting any new predicates.
