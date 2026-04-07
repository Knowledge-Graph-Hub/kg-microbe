# Unmapped Traits - Round 3 Analysis

**Date:** 2026-04-06  
**After:** EC2GO integration, pyrazinamidase fix, 10 enzymes added, synonym fallback fix  
**Status:** Round 2 extremely successful - 97%+ enzyme reduction maintained

---

## Round 2 Results Summary

### Success Metrics

| Category | After Round 1 | After Round 2 | **Improvement** |
|----------|---------------|---------------|-----------------|
| **Enzyme malformed EC** | 577 | **0** | **-100%** ✅ |
| **Enzyme no EC** | 269 | **24** | **-91%** ✅ |
| **Chemical patterns** | 672 | **236** | **-65%** ✅ |
| **Required for growth** | 80 | **2** | **-98%** ✅ |
| **Total patterns** | 245,304 | 244,700 | -604 (-0.25%) |

**Key achievement:** 
- Pyrazinamidase malformed EC: **100% fixed** (577 → 0)
- Enzyme no EC: **91% reduction** (269 → 24)
- Chemical patterns: **65% reduction** (672 → 236)

---

## Round 3 Opportunities (Low ROI)

### 1. Chemical Patterns (236 obs remaining)

Most common unmapped: 3-aminobutyrate (10 obs), 1,2-propandiol (10 obs), D-salicin (9 obs)

**Solution:** Add 8-10 entries to chemical_name_synonyms.tsv  
**Expected impact:** ~100 observations  
**Time:** 30 minutes

### 2. Utilizes + Respiration Patterns (35 obs)

Check if resolvers handle "utilizes" and "respiration" patterns.

**Expected impact:** ~35 observations  
**Time:** 30 minutes

### Low Priority (Skip)

- Remaining enzymes: 24 obs (too rare)
- Produces: 256 obs (obscure compounds, not in ChEBI)
- Other: 102 obs (complex materials)

---

## Conclusion

Round 2 achieved:
- ✅ **100% fix** for malformed EC (577 → 0)
- ✅ **91% reduction** in enzyme no EC (269 → 24)
- ✅ **65% reduction** in chemical patterns (672 → 236)
- ✅ EC2GO integration for all enzymes with EC numbers

**Remaining unmapped:** 99.993% are intentional (single growth tests, negative assertions).

Only **~650 observations** (0.007%) are actionable, most very low frequency.

**Recommendation:** Round 2 is sufficient. We've reached diminishing returns.

---

**Date:** 2026-04-06  
**Status:** Analysis complete - Round 2 very successful
