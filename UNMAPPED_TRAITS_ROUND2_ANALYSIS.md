# Unmapped Traits - Round 2 Analysis

**Date:** 2026-04-06  
**After:** Enzyme GO mappings, required-for-growth resolver, chemical synonyms expansion  
**Status:** 97-98% reduction in enzyme-no-EC, 98% reduction in required-for-growth

---

## Improvement Summary

### Success Metrics by Category

| Category | Before (NCBI) | After (NCBI) | Reduction | Before (GTDB) | After (GTDB) | Reduction |
|----------|---------------|--------------|-----------|---------------|--------------|-----------|
| Enzyme no EC | 6,670 | 144 | **-97.8%** | 4,747 | 125 | **-97.4%** |
| Required for growth | 44 | 1 | **-97.7%** | 36 | 1 | **-97.2%** |
| Chemical patterns | 456 | 405 | -11.2% | 292 | 267 | -8.6% |

**Key success:** Enzyme GO mappings captured **10.4K observations** with just 23 mapping entries!

---

## High Priority Opportunities

### 1. Enzyme Malformed EC (577 obs) ✅ HIGH PRIORITY

**Pattern:** `enzyme activity: pyrazinamidase (EC3.5.1.B15)`

- 353 NCBI + 224 GTDB = 577 observations
- "B15" is malformed, should be EC:3.5.1.19
- **Solution:** Add to `enzyme_name_to_go.tsv`
- **Impact:** 577 observations

### 2. Remaining Enzymes (269 obs) ✅ MEDIUM PRIORITY

Top unmapped:
- adenyl cyclase hemolysin: 206 obs
- nitrogenase: 8 obs  
- beta-N-acetylgalactosaminidase: 7 obs
- NiFe-hydrogenase: 7 obs

**Solution:** Expand `enzyme_name_to_go.tsv` with 10 entries
**Impact:** ~230 observations

### 3. Chemical Patterns (672 obs) ✅ INVESTIGATION NEEDED

**Mystery:** Some chemicals ARE in synonyms file but still failing:
- `(-)-D-fructose`: 32 obs (already in file!)
- `2-oxogluconate`: 23 obs (already in file!)
- `3-O-methyl alpha-D-glucopyranoside`: 24 obs (already in file!)

**Action:** Debug why existing synonyms not mapping
**Impact:** 79+ observations

### 4. Utilizes Stereochemistry (21 obs) ✅ QUICK WIN

Pattern: `utilizes: (+)-L-ornithine`, etc.
**Solution:** Add stereochemistry variants to synonyms
**Impact:** 21 observations

### 5. Respiration (14 obs) ✅ QUICK WIN

Pattern: `respiration: D-saccharate`
**Action:** Check if resolver handles "respiration" pattern
**Impact:** 14 observations

---

## Recommendation

**Quick wins (2 hours):**
1. Fix pyrazinamidase malformed EC (5 min, 577 obs)
2. Debug synonym failures (30 min, 79+ obs)
3. Add 10 remaining enzymes (1 hour, 230 obs)

**Total impact:** ~886 observations  
**New coverage:** 90.72% → 90.74%

---

**Date:** 2026-04-06  
**Status:** Round 1 successful - ready for Round 2
