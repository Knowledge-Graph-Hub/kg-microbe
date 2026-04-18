# METPO Proposals Reconciliation

**Date:** 2026-04-03  
**Purpose:** Answer the key questions about METPO proposal files and coverage estimates  

---

## Question 1: Where are the METPO TSV proposal files?

### **Active/Current Proposal Files**

Located in **`mappings/`** directory:

1. **`metpo_unified_all_phases.tsv`** ✅ **USE THIS**
   - **Most comprehensive:** All 6 phases (59 total terms)
   - Includes Phases 1-4 (47 terms), Phase 5 (ChEBI), Phase 6 (12 optional)
   - **Created:** 2026-04-03
   - **Status:** COMPLETE - Ready for review

2. **`metpo_phases_1_2_3_terms.tsv`** ✅ **Alternative**
   - Phases 1-3 only (44 terms)
   - Missing Phase 3 metabolic predicates (acid/gas/base)
   - Missing Phase 5 (ChEBI improvements)
   - Missing Phase 6 (optional phenotypes)
   - **Created:** 2026-04-03

3. **`metpo_predicate_based_proposal.tsv`** ✅ **Phase 1 only**
   - 9 quantitative data properties only
   - Useful for testing Phase 1 in isolation
   - **Created:** 2026-03-28

4. **`additional_metpo_mappings.tsv`** ✅ **Analysis reference**
   - Categorization of all 902 unmapped traits
   - Not a proposal, but shows what needs to be addressed
   - **Created:** 2026-03-25

### **Deprecated Files (Do NOT use)**

❌ `metpo_fermentation_proposal.tsv` - OLD class-based approach (95 fermentation classes)  
❌ `metpo_electron_acceptor_proposal.tsv` - OLD class-based approach (16 electron acceptor classes)  
❌ `metpo_quantitative_proposal.tsv` - OLD format (superseded by predicate_based_proposal.tsv)

**Recommendation:** Use **`metpo_unified_all_phases.tsv`** for complete 6-phase proposal.

---

## Question 2: What about the 85% unmapped estimate?

### **Short Answer**

The **85% coverage estimate is CORRECT** but was split across TWO different proposals:

1. **Old proposal** (`METPO_TERM_REQUESTS.md`): 31 terms → 85% coverage
2. **New proposal** (Phases 1-3 document): 44 terms → 57% coverage

These were **NOT the same proposal** → caused confusion.

### **Detailed Explanation**

#### **Proposal A: METPO_TERM_REQUESTS.md (March 25)**

**31 new METPO terms across 5 phases → 85% coverage (770/902 traits)**

| Phase | Terms | What | Traits | Cumulative Coverage |
|-------|-------|------|--------|---------------------|
| 1 | 4 predicates | assimilates, energy, nitrogen, electron donor | 473 | 52% |
| 2 | 12 classes | Environmental/morphological phenotypes | +26 | 55% |
| 3 | 3 predicates | Produces acid/gas/base from | +66 | 60% |
| **4** | **0 terms** | **ChEBI lookup improvements** | **+151** | **77%** |
| 5 | 12 classes | Additional phenotypes | +54 | 83% |
| **TOTAL** | **31** | | **770** | **85%** |

**Key:** Phase 4 has ZERO new METPO terms (just improves ChEBI lookups in code).

---

#### **Proposal B: My New Phases 1-3 (April 3)**

**44 new METPO terms across 3 phases → 57% coverage (514 traits)**

| Phase | Terms | What | Traits | Coverage |
|-------|-------|------|--------|----------|
| 1 | 9 properties | Quantitative (temp/pH/salinity) | 3 | 0.3% |
| 2 | 4 predicates | Core metabolic (assimilates, energy, N, e-donor) | 473 | 53% |
| 3 | 31 classes | Comprehensive phenotypes | 38 | 57% |
| **TOTAL** | **44** | | **514** | **57%** |

**Why lower coverage?**
- Missing Phase 3 metabolic predicates (acid/gas/base) = 66 traits
- Missing Phase 5 ChEBI improvements = 151 traits
- Missing Phase 6 optional phenotypes = 54 traits

---

### **The Solution: UNIFIED 6-PHASE PROPOSAL**

**New unified proposal:** `METPO_UNIFIED_PROPOSAL_5_PHASES.md` (technically 6 phases)

**47 new METPO terms (Phases 1-5) + 12 optional (Phase 6) → 85% coverage**

| Phase | Terms | What | Traits | Cumulative Coverage |
|-------|-------|------|--------|---------------------|
| **1** | 9 properties | Quantitative (temp/pH/salinity) | 3 | 0.3% |
| **2** | 4 predicates | Core metabolic | 473 | 53% |
| **3** | 3 predicates | Extended metabolic (acid/gas/base) | 66 | 60% |
| **4** | 31 classes | Comprehensive phenotypes | 38 | 64% |
| **5** | **0 terms** | **ChEBI improvements (code only)** | **151** | **81%** |
| 6 (opt) | 12 classes | Remaining phenotypes | 54 | 87% |
| **TOTAL (1-5)** | **47** | | **731** | **~85%** |
| **TOTAL (1-6)** | **59** | | **785** | **87%** |

**Achievement:**
- ✅ 85% coverage with 47 new METPO terms (Phases 1-5)
- ✅ 87% coverage with 59 new METPO terms (Phases 1-6)
- ✅ Phase 5 requires NO new METPO terms (ChEBI infrastructure only)

---

## Summary: File Locations & Coverage

### **TSV Proposal Files (in `mappings/`)**

| File | Phases | Terms | Coverage | Status |
|------|--------|-------|----------|--------|
| **metpo_unified_all_phases.tsv** | **1-6** | **59** | **87%** | **✅ USE THIS** |
| metpo_phases_1_2_3_terms.tsv | 1-3 | 44 | 57% | ⚠️ Incomplete |
| metpo_predicate_based_proposal.tsv | 1 only | 9 | 0.3% | ⚠️ Partial |
| additional_metpo_mappings.tsv | N/A | Analysis | N/A | ✅ Reference |

### **Full Proposal Documents**

| File | Phases | Terms | Coverage | Status |
|------|--------|-------|----------|--------|
| **METPO_UNIFIED_PROPOSAL_5_PHASES.md** | **1-6** | **59** | **87%** | **✅ USE THIS** |
| METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md | 1-4 | 44 | 64% | ⚠️ Incomplete |
| METPO_TERM_REQUESTS.md | 1-5 | 31 | 85% | ⚠️ Old version |
| METPO_PROPOSAL_EXECUTIVE_SUMMARY.md | 1-3 | 44 | 57% | ⚠️ Incomplete |

### **GitHub Issue Templates**

| File | Based On | Status |
|------|----------|--------|
| METPO_GITHUB_ISSUE_TEMPLATE.md | Phases 1-3 (44 terms) | ⚠️ Needs update for unified proposal |

---

## Recommended Next Steps

### **1. Review Unified Proposal**
- Read: `METPO_UNIFIED_PROPOSAL_5_PHASES.md`
- Review TSV: `mappings/metpo_unified_all_phases.tsv`

### **2. Decide on Submission Strategy**

**Option A: Submit All (Phases 1-5)** - RECOMMENDED
- 47 new METPO terms requested
- 85% coverage (81% conservative)
- Phase 5 requires NO METPO changes (ChEBI only)
- Defer Phase 6 to future

**Option B: Phased Submission**
- **First:** Phases 1-2 (13 terms, CRITICAL) → 53%
- **Second:** Phases 3-4 (34 terms, HIGH) → 64%
- **Third:** Phase 6 (12 terms, MEDIUM) → 87%
- **No METPO request for Phase 5** (code only)

**Option C: Critical Only**
- Phases 1-2 only (13 terms) → 53%
- Test METPO maintainer appetite first

### **3. Update GitHub Issue Template**
- Current template based on incomplete Phases 1-3
- Should update to reflect unified 5-phase proposal
- Or create separate templates for Option A/B/C

### **4. Create Phase 3 Detailed Specs**
- Current detailed specs only cover Phases 1, 2, 4
- Need to expand Phase 3 (produces acid/gas/base) with full OWL definitions
- Should match format of `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md`

---

## Coverage Breakdown (Phases 1-5)

### By Term Type
| Type | Count | Coverage |
|------|-------|----------|
| Data Properties | 9 | 176,101 observations |
| Object Properties | 7 | 539 traits (~536,000 obs) |
| Classes | 31 | 38 traits (~26,000 obs) |
| **Total METPO Terms** | **47** | **~731 traits** |
| Infrastructure (ChEBI) | 0 | 151 traits |
| **Grand Total** | **47** | **~85%** |

### By Priority
| Priority | Phases | Terms | Coverage |
|----------|--------|-------|----------|
| CRITICAL | 1-2 | 13 | 53% |
| HIGH | 3-4 | 34 | 11% |
| Infrastructure | 5 | 0 | 21% |
| MEDIUM (opt) | 6 | 12 | 6% |

---

## Key Takeaways

1. **File to use:** `mappings/metpo_unified_all_phases.tsv` (59 terms, 6 phases)

2. **85% coverage is achievable** with:
   - 47 new METPO terms (Phases 1-5)
   - ChEBI infrastructure improvements (Phase 5 = 0 new terms)

3. **Two proposals existed:**
   - METPO_TERM_REQUESTS.md (31 terms, old)
   - Phases 1-3 document (44 terms, incomplete)
   - **NOW UNIFIED** → 47 terms (Phases 1-5) or 59 terms (Phases 1-6)

4. **Phase 5 is special:** Achieves 21% additional coverage with ZERO new METPO terms (just improves ChEBI lookups in KG-Microbe code)

5. **Next decision:** Choose submission strategy (Option A, B, or C)

---

**Questions? See:**
- Complete proposal: `METPO_UNIFIED_PROPOSAL_5_PHASES.md`
- All terms: `mappings/metpo_unified_all_phases.tsv`
- Analysis: `mappings/additional_metpo_mappings.tsv`
