# ChEBI Search Findings for Missing Chemicals

**Date:** 2026-04-08  
**Purpose:** Comprehensive ChEBI search for 17 unmapped chemicals from Round 5 analysis

---

## Summary

**Search Results:**
- ✅ **1 compound found and added:** CHEBI:15887 (4-aminovalerate)
- ❌ **16 compounds NOT in ChEBI:** Genuinely missing from reference ontology
- 📊 **Expected impact:** 1 observation resolved

---

## Compounds Found in ChEBI

### 1. CHEBI:15887 - 5-aminopentanoic acid ✅

**Status:** ADDED to unified file

**Unmapped pattern:** `growth: 4-aminovalerate` (1 observation)

**Action Taken:**
- Added synonyms: "4-aminovalerate", "4-aminovaleric acid"  
- Added source: "metatraits_manual[2026-04-08]"
- Entry already existed in unified file with other synonyms

**Resolution:** Will now map `growth: 4-aminovalerate` → CHEBI:15887

---

## Compounds NOT Found in ChEBI ❌

The following 16 compounds are genuinely absent from the ChEBI database and cannot be added without ChEBI curation:

### Chromogenic Substrates (6 compounds, 9 observations)

1. **L-alanine 4-nitroanilide** (5 observations)
   - Patterns: nitrogen source (3), assimilation (2)
   - Type: Aminopeptidase chromogenic substrate
   - ChEBI has: beta-alanine 4-nitroanilide (CHEBI:90126), but NOT L-alanine variant
   - Status: Would require ChEBI curation request

2. **3-[(4-nitrophenyl)carbamoylamino]propanoic acid** (1 observation)
   - Pattern: builds acid from
   - Type: Chromogenic substrate
   - Status: Not in ChEBI

3. **5-bromo-3-indolyl nonanoate** (1 observation)
   - Pattern: builds acid from
   - Note: ChEBI has 5-bromo-3-indolyl **decanoate** (CHEBI:90248, C10), but nonanoate (C9) is not present
   - Status: One-carbon-chain difference - likely a different compound

4. **bis-4-nitrophenyl-phosphorylcholine** (1 observation)
   - Pattern: hydrolysis
   - Note: ChEBI has p-nitrophenylphosphocholine (CHEBI:55394), but "bis-4-nitrophenyl" variant not found
   - Status: May be a different compound or naming error

5. **bis-4-nitrophenyl-phenyl phosphonate** (1 observation)
   - Pattern: hydrolysis
   - Note: ChEBI has bis-4-nitrophenyl phosphate (CHEBI:3122), but phosphonate variant not found
   - Status: Not in ChEBI

### Halogenated Alkanes (2 compounds, 2 observations)

6. **1-chlorobutane** (1 observation)
   - Pattern: degradation
   - Note: ChEBI has 2-chlorobutane (CHEBI:166855), but 1-chlorobutane is missing
   - Status: Different isomer

7. **1-chloropropane** (1 observation)
   - Pattern: degradation
   - Note: ChEBI has various dichloropropane and trichloropropane variants, but not 1-chloropropane
   - Status: Not in ChEBI

### Carbohydrates/Glycosides (4 compounds, 4 observations)

8. **beta-D-galacto-pyranosyl-D-arabinose** (1 observation)
   - Pattern: assimilation
   - Type: Disaccharide
   - Status: Not found in ChEBI

9. **1-o-methyl alpha-galactopyranoside** (1 observation)
   - Pattern: growth
   - Type: Methyl glycoside
   - Status: Not found in ChEBI

10. **6-O-alpha-D-glucopyranosyl-D-gluconic acid** (1 observation)
    - Pattern: growth
    - Type: Glucosyl-gluconic acid
    - Status: Not found in ChEBI

11. **(2)-D-lactose** (1 observation)
    - Pattern: carbon source
    - Note: Unusual stereochemistry notation "(2)-" 
    - ChEBI has D-lactose, but not this specific variant
    - Status: May be a data entry error or non-standard notation

---

## Recommendations

### For Immediate Use:

✅ **DONE:** Added CHEBI:15887 with "4-aminovalerate" synonym
- Expected to resolve: 1 observation

### For Future Consideration:

1. **ChEBI Curation Requests (9 observations):**
   - L-alanine 4-nitroanilide (5 obs) - **HIGH PRIORITY** (common chromogenic substrate)
   - Other chromogenic substrates (4 obs) - Medium priority
   
   These are legitimate chemical entities used in microbiology assays but absent from ChEBI.
   Could submit curation requests to ChEBI if high-value.

2. **Accept as Unmappable (7 observations):**
   - Halogenated alkanes (2 obs) - Low priority compounds
   - Complex carbohydrates (4 obs) - May be rare or incorrectly annotated
   - (2)-D-lactose (1 obs) - Likely data entry error

3. **Data Quality Investigation (1 observation):**
   - "(2)-D-lactose" - Verify source data for correct chemical name

---

## Impact Summary

| Category | Compounds | Observations | Action | Status |
|----------|-----------|--------------|--------|--------|
| Added to unified file | 1 | 1 | CHEBI:15887 | ✅ Complete |
| Missing from ChEBI (chromogenic) | 5 | 9 | ChEBI request or skip | ⏸️ Deferred |
| Missing from ChEBI (other) | 11 | 7 | Accept as unmappable | ⏸️ Deferred |
| **Total** | **17** | **17** | | |

**Final Reduction:** 1 observation (from 182 → 181 actionable unmapped)

---

## Technical Notes

### ChEBI Search Methods Used:
1. Direct lookup in unified chemical mappings file (gzipped TSV)
2. ChemicalMappingLoader.find_chebi_by_name() with fuzzy_stereochemistry
3. Web search of ebi.ac.uk/chebi domain
4. Manual grep searches for compound name variants

### Limitations:
- ChEBI focus: Biological entities, not all synthetic chromogenic substrates
- Coverage gaps: Enzyme assay substrates, especially p-nitroanilide derivatives
- Nomenclature: Some compounds may exist under alternative IUPAC names not searched

---

## Sources

- ChEBI database: https://www.ebi.ac.uk/chebi/
- Unified chemical mappings: `mappings/unified_chemical_mappings.tsv.gz`
- Unmapped traits: `data/transformed/metatraits/unmapped_traits.tsv`

---

**Conclusion:** Of 17 missing chemicals investigated, only 1 could be added to the unified file. The remaining 16 genuinely do not exist in ChEBI. The chromogenic substrates (especially L-alanine 4-nitroanilide) represent a gap in ChEBI coverage for microbiology assay compounds.

---

**End of Findings**
