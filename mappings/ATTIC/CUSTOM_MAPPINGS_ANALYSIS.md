# Custom Metatraits Mappings Analysis

## Overview

This document analyzes all custom metatraits mappings (manual + pattern-based) against the METPO ontology to identify which mappings are already in METPO and which are unique custom extensions.

## Summary Statistics

- **Total custom mappings**: 57
- **Mappings using METPO terms**: 40 (70.2%)
- **Mappings NOT in METPO**: 17 (29.8%)

### Tier 1 Manual Mappings

- **Total Tier 1 mappings**: 25
- **Using METPO terms**: 8 (32.0%)
- **NOT in METPO**: 17 (68.0%)

#### Tier 1 Mappings by Object Source

| Source | Total | In METPO | Not in METPO | % External |
|--------|-------|----------|--------------|------------|
| CHEBI | 7 | 0 | 7 | 100.0% |
| EC | 4 | 0 | 4 | 100.0% |
| GO | 5 | 0 | 5 | 100.0% |
| METPO | 9 | 8 | 1 | 11.1% |

### Pattern-Based Mappings (Tier 1.5-2.0)

- **Tier 1.5 (chemical)**: 8 patterns, 8 use METPO predicates
- **Tier 1.6 (metabolic)**: 9 patterns, 9 use METPO predicates
- **Tier 1.7 (growth)**: 2 patterns, 2 use METPO predicates
- **Tier 1.8 (trophic)**: 8 patterns, 8 use METPO predicates
- **Tier 1.9 (enzyme)**: 1 patterns, 1 use METPO predicates
- **Tier 2.0 (phenotype)**: 4 patterns, 4 use METPO predicates

## Key Findings

### 1. METPO Predicate Usage

All pattern-based resolvers (Tier 1.5-2.0) use METPO predicates correctly:

- `METPO:2000001` - organism interacts with chemical
- `METPO:2000002-2000020` - specific chemical interactions (produces, ferments, etc.)
- `METPO:2000103` - capable of (for biological processes)
- `METPO:2000102` - has phenotype
- `METPO:2000302` - shows activity of (for enzymes)

### 2. External Ontology References

Custom mappings correctly delegate to external ontologies when appropriate:

- **ChEBI**: Chemical substances (carbon source, electron acceptor patterns)
- **GO**: Biological processes (trophic modes, pathways)
- **EC**: Enzyme classification (enzyme activity with EC numbers)

### 3. Tier 1 Manual Mappings Analysis

**CRITICAL FINDING: Incorrect METPO CURIEs in phenotype_mappings.tsv**

The manual phenotype mapping file contains **INCORRECT METPO CURIEs**. Analysis shows:

**Incorrect mappings (wrong CURIE → actual METPO label):**
- `gram positive` → `METPO:1000606` (actually: "obligately aerobic", should be: METPO:1000698)
- `gram negative` → `METPO:1000607` (actually: "obligately anaerobic", should be: METPO:1000699)
- `sporulation` → `METPO:1000614` (actually: "psychrophilic", should be: METPO:1000870) ✓ correct CURIE
- `obligate aerobic` → `METPO:1000616` (actually: "thermophilic", should be: METPO:1000606)
- `obligate anaerobic` → `METPO:1000870` (actually: "sporulation", should be: METPO:1000607)
- `presence of motility` → `METPO:1002005` (actually: "Fermentation", should be: METPO:1000702)
- `psychrophilic` → `METPO:1000660` (actually: "phototrophic", should be: METPO:1000614)
- `thermophilic` → `METPO:1000656` (actually: "photoautotrophic", should be: METPO:1000616)
- `voges-proskauer test` → `METPO:1005017` (NOT FOUND in METPO)

**Impact**: These incorrect CURIEs mean the current manual mappings are creating WRONG edges in the knowledge graph! For example, a "gram positive" organism is being incorrectly mapped to "obligately aerobic" phenotype.

**Recommendation**:
1. **URGENT**: Fix all incorrect METPO CURIEs in phenotype_mappings.tsv
2. After fixing CURIEs, these mappings can be removed when METPO-first resolution is implemented
3. Terms not in METPO (voges-proskauer) need custom handling

**17 Tier 1 mappings use external ontologies:**


**CHEBI (7 mappings):**

- `produces: ethanol` → `CHEBI:16236`
- `produces: hydrogen sulfide` → `CHEBI:16136`
- `produces: indole` → `CHEBI:16881`
- `produces: methane from acetate` → `CHEBI:16183`
- `produces: siderophore` → `CHEBI:26672`
- `carbon source: acetate` → `CHEBI:30089`
- `carbon source: ethanol` → `CHEBI:16236`

**EC (4 mappings):**

- `enzyme activity: catalase (EC1.11.1.6)` → `EC:1.11.1.6`
- `enzyme activity: beta-galactosidase (EC3.2.1.23)` → `EC:3.2.1.23`
- `enzyme activity: urease (EC3.5.1.5)` → `EC:3.5.1.5`
- `enzyme activity: lipase` → `EC:3.1.1.3`

**GO (5 mappings):**

- `enzyme activity: oxidase` → `GO:0016491`
- `fermentation` → `GO:0006113`
- `nitrogen fixation` → `GO:0009399`
- `denitrification pathway` → `GO:0019333`
- `nitrification` → `GO:0019329`

**METPO (1 mappings):**

- `voges-proskauer test` → `METPO:1005017`

**Recommendation**: These should remain as Tier 1 mappings as they provide specific chemical/pathway/enzyme mappings not in METPO.

## Impact of METPO Priority Change

### Current Resolution Order

1. Tier 1: Manual mappings (4 TSV files)
2. Tier 1.5-2.0: Pattern-based resolvers
3. Tier 3: METPO synonym matching
4. Tier 4: OAK adapter search

### Proposed Resolution Order

1. Tier 1: METPO synonym matching (classes + properties)
2. Tier 2: Manual mappings (external ontologies only)
3. Tier 3: Pattern-based resolvers
4. Tier 4: OAK adapter search

### Expected Benefits

1. **Reduced manual mapping maintenance**: 8 Tier 1 METPO mappings can be removed, reducing manual TSV file maintenance.

2. **Improved consistency**: All METPO terms will use official METPO labels and predicates from the ontology.

3. **Automatic updates**: New METPO terms and synonyms will be available immediately without code changes.

4. **Clearer separation**: Tier 1 manual mappings will focus exclusively on external ontology bridges (ChEBI, GO, EC).

### Migration Steps

1. Test METPO-first resolution with current test suite
2. Remove Tier 1 mappings that duplicate METPO synonyms
3. Keep Tier 1 mappings for external ontologies (ChEBI, GO, EC)
4. Update documentation to reflect new priority order
5. Monitor edge counts to ensure no regressions

## Corrected METPO CURIEs for phenotype_mappings.tsv

| Trait | Current (WRONG) | Correct CURIE | METPO Label | Status |
|-------|----------------|---------------|-------------|--------|
| gram positive | METPO:1000606 | METPO:1000698 | gram positive | Fix required |
| gram negative | METPO:1000607 | METPO:1000699 | gram negative | Fix required |
| sporulation | METPO:1000614 | METPO:1000870 | sporulation | Fix required (wrong in TSV label) |
| obligate aerobic | METPO:1000616 | METPO:1000606 | obligately aerobic | Fix required |
| obligate anaerobic | METPO:1000870 | METPO:1000607 | obligately anaerobic | Fix required |
| presence of motility | METPO:1002005 | METPO:1000702 | motile | Fix required |
| voges-proskauer test | METPO:1005017 | N/A | NOT IN METPO | Keep custom or remove |
| psychrophilic | METPO:1000660 | METPO:1000614 | psychrophilic | Fix required |
| thermophilic | METPO:1000656 | METPO:1000616 | thermophilic | Fix required |

## Recommendations

### URGENT (Priority 0)

1. **Fix incorrect METPO CURIEs in phenotype_mappings.tsv** before any other changes
2. Validate that other manual mapping files (chemical_mappings.tsv, enzyme_mappings.tsv, pathway_mappings.tsv) have correct CURIEs
3. Run test suite to confirm fix doesn't break existing tests (tests may expect wrong CURIEs)

### Short-term

1. Implement METPO-first resolution order
2. Keep all current mappings during transition
3. Add logging to track which tier resolves each trait

### Medium-term

1. Remove redundant Tier 1 METPO mappings after validation
2. Propose missing terms to METPO ontology:
   - Pattern-based mappings that should be METPO classes
   - Common chemical/pathway mappings from Tier 1

### Long-term

1. Contribute back to METPO ontology development
2. Align KG-Microbe trait patterns with METPO structure
3. Develop METPO-based validation for data quality

