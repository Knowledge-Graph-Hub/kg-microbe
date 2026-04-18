# METPO Unified Proposal: 5 Phases to 85% Coverage

**Date:** 2026-04-03  
**Status:** Comprehensive unified proposal  
**Target:** 85% coverage of unmapped metatraits (770/902 traits)  

---

## Executive Summary

Request **47 new METPO terms** across 5 prioritized phases to achieve **85% coverage** of currently unmapped microbial trait data from BacDive.

| Phase | Term Type | Count | Traits Covered | Cumulative Coverage | Priority |
|-------|-----------|-------|----------------|---------------------|----------|
| **1** | Data Properties (Quantitative) | 9 | 3 (176K obs) | 0.3% | CRITICAL |
| **2** | Object Properties (Core Metabolic) | 4 | 473 | 52% | CRITICAL |
| **3** | Object Properties (Extended Metabolic) | 3 | 66 | 60% | HIGH |
| **4** | Classes (Phenotypic) | 31 | 38 | 64% | HIGH |
| **5** | ChEBI Infrastructure (NO NEW TERMS) | 0 | 151 | 77% | HIGH |
| **6** | Classes (Remaining Phenotypes) | 12 | 54 | 85% | MEDIUM |
| **TOTAL** | **Mixed** | **47** | **770/902** | **85%** | **CRITICAL-HIGH** |

**Note:** Phase 5 adds ZERO new METPO terms but improves ChEBI chemical lookup infrastructure.

---

## Phase 1: Quantitative Growth Properties (9 data properties)

**Priority:** CRITICAL  
**Coverage:** 3 unique traits, 176,101 observations  
**Why Critical:** Industry-standard measurements for biotechnology and culture conditions  

### Temperature Properties (3)
```turtle
METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
METPO:has_growth_temperature_minimum a owl:DatatypeProperty ;
METPO:has_growth_temperature_maximum a owl:DatatypeProperty ;
```
**Addresses:** `growth: [X] degrees Celsius` (85,311 observations)

### Salinity Properties (3)
```turtle
METPO:has_NaCl_concentration_optimum a owl:DatatypeProperty ;
METPO:has_NaCl_concentration_minimum a owl:DatatypeProperty ;
METPO:has_NaCl_concentration_maximum a owl:DatatypeProperty ;
```
**Addresses:** `growth: [X]% NaCl` (85,311 observations)

### pH Properties (3)
```turtle
METPO:has_pH_optimum a owl:DatatypeProperty ;
METPO:has_pH_minimum a owl:DatatypeProperty ;
METPO:has_pH_maximum a owl:DatatypeProperty ;
```
**Addresses:** `pH preference` (5,479 observations)

**Full specifications:** See `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md` Phase 1

---

## Phase 2: Core Metabolic Predicates (4 object properties)

**Priority:** CRITICAL  
**Coverage:** 473 unique traits, ~495,000 observations  
**Why Critical:** Fundamental metabolic processes missing from current METPO  

### 2.1 Assimilates (266 traits)
```turtle
METPO:2000021 a owl:ObjectProperty ;
    rdfs:label "assimilates"@en ;
    # Organism takes up and incorporates chemical into biomass
```
**Addresses:** `assimilation: glucose`, `assimilation: acetate`, etc. (266 traits)

### 2.2 Uses as Energy Source (97 traits)
```turtle
METPO:2000022 a owl:ObjectProperty ;
    rdfs:label "uses as energy source"@en ;
    # Chemical oxidized primarily for ATP generation
```
**Addresses:** `energy source: acetate`, `energy source: glucose`, etc. (97 traits)

### 2.3 Uses as Nitrogen Source (57 traits)
```turtle
METPO:2000023 a owl:ObjectProperty ;
    rdfs:label "uses as nitrogen source"@en ;
    # Nitrogen-containing chemical assimilated for biosynthesis
```
**Addresses:** `nitrogen source: ammonia`, `nitrogen source: nitrate`, etc. (57 traits)

**Note:** May already exist as METPO:2000014 - needs verification.

### 2.4 Uses as Electron Donor (53 traits)
```turtle
METPO:2000024 a owl:ObjectProperty ;
    rdfs:label "uses as electron donor"@en ;
    # Chemical oxidized to provide electrons for energy metabolism
```
**Addresses:** `electron donor: dihydrogen`, `electron donor: sulfide`, etc. (53 traits)

**Full specifications:** See `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md` Phase 2

---

## Phase 3: Extended Metabolic Predicates (3 object properties)

**Priority:** HIGH  
**Coverage:** 66 unique traits, ~41,000+ observations  
**Why High:** Specific metabolic outcomes (acid/gas/base production) important for fermentation characterization  

### 3.1 Produces Acid From (28 traits)
```turtle
METPO:2000025 a owl:ObjectProperty ;
    rdfs:label "produces acid from"@en ;
    obo:IAO_0000115 "Organism produces acid from substrate via fermentation or metabolism."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf METPO:2000202 ;  # produces
```
**Addresses:** `builds acid from: glucose`, `builds acid from: lactose`, etc. (28 traits)

**Distinction from existing:**
- `METPO:2000202 (produces)` - General production
- `METPO:2000025 (produces acid from)` - **Specific acid production outcome**

### 3.2 Produces Gas From (16 traits)
```turtle
METPO:2000026 a owl:ObjectProperty ;
    rdfs:label "produces gas from"@en ;
    obo:IAO_0000115 "Organism produces gas (CO2, H2, CH4, etc.) from substrate."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf METPO:2000202 ;
```
**Addresses:** `builds gas from: glucose`, `builds gas from: nitrate`, etc. (16 traits)

### 3.3 Produces Base From (7 traits)
```turtle
METPO:2000027 a owl:ObjectProperty ;
    rdfs:label "produces base from"@en ;
    obo:IAO_0000115 "Organism produces base/alkaline products from substrate."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf METPO:2000202 ;
```
**Addresses:** `builds base from: acetate`, `builds base from: gluconate`, etc. (7 traits)

**Source:** `METPO_TERM_REQUESTS.md` Phase 3

---

## Phase 4: Phenotypic Quality Classes (31 classes)

**Priority:** HIGH  
**Coverage:** 38 unique traits, ~26,000 observations  
**Why High:** Essential microbiological characterization for taxonomy and culture collections  

### 4.1 Morphological (5 classes)
- `METPO:1007001` - cell shape
- `METPO:1007002` - cell length  
- `METPO:1007003` - cell width
- `METPO:1007004` - cell color
- `METPO:1007005` - flagellar arrangement

**Addresses:** Cell morphology traits (10 total instances)

### 4.2 Genomic (4 classes)
- `METPO:1007010` - GC content percentage
- `METPO:1007011` - genome size
- `METPO:1007012` - gene count
- `METPO:1007013` - coding density

**Addresses:** Genomic quality traits (7 total instances)

### 4.3 Environmental Tolerances (12 classes)
- `METPO:1007020` - oxygen requirement
- `METPO:1007021-1007024` - pH tolerance (range, min, max, optimum)
- `METPO:1007025-1007028` - temperature tolerance (range, min, max, optimum)
- `METPO:1007029-1007032` - salinity tolerance (range, min, max, optimum)

**Addresses:** Environmental growth condition traits (12 total instances)

**Note:** These classes serve as **scaffolding** for Phase 1 data properties.

### 4.4 Biochemical Tests (3 classes)
- `METPO:1007040` - indole production capability
- `METPO:1007041` - methyl red test positive
- `METPO:1007042` - hemolytic activity

**Addresses:** Standard biochemical test results (3 total instances)

### 4.5 Growth Characteristics (3 classes)
- `METPO:1007050` - selective media growth capability
- `METPO:1007051` - bile resistance
- `METPO:1007052` - biosafety level classification

**Addresses:** Culture growth properties (6 total instances)

### 4.6 Additional Phenotypes (4 classes - from METPO_TERM_REQUESTS Phase 2)
Already included in the 31 classes above. No additional terms needed.

**Full specifications:** See `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md` Phase 3

---

## Phase 5: ChEBI Lookup Infrastructure (0 NEW METPO TERMS)

**Priority:** HIGH  
**Coverage:** 151 unique traits, ~7,500+ observations  
**Why High:** Large impact with NO ontology additions  
**CRITICAL:** This phase does NOT add any new METPO terms  

### Problem
151 traits have pattern resolvers (e.g., `METPO:2000011` for fermentation) but ChEBI lookup fails due to:

1. **Synonym mismatches** (79 traits)
   - Example: `produces: poly-beta-hydroxyalkanoate` not found in ChEBI synonyms
   - Solution: Expand synonym matching to include variants

2. **Stereochemistry naming** (27 traits)
   - Example: `carbon source: (R)-bromosuccinate` vs `bromosuccinate`
   - Solution: Normalize stereochemistry prefixes [(R)/(S)/(+)/(-)]

3. **Polymer/complex names** (12 traits)
   - Example: `degradation: plastic`, `hydrolysis: casein hydrolysate`
   - Solution: Use ENVO for materials, or map to parent compounds

4. **Variant names** (9 traits)
   - Example: `hydrolysis: crab shell chitin` vs `chitin`
   - Solution: Improved name normalization

### Implementation Strategy (NO METPO CHANGES)

**Changes to KG-Microbe code only:**

1. **Expand `ChemicalMappingLoader`** (`kg_microbe/utils/chemical_mapping_utils.py`):
   - Add stereochemistry normalization
   - Add variant name stripping
   - Add fuzzy matching for close variants

2. **Add ENVO fallback** for material degradation traits:
   - `degradation: plastic` → ENVO:01000970 (plastic material)
   - `degradation: aromatic compound` → CHEBI:33655 (aromatic compound)

3. **Add manual mapping file** for complex substrates:
   - `mappings/complex_substrate_mappings.tsv`
   - Maps "casein hydrolysate" → CHEBI:17895 (casein) + annotation

**Affected traits:**
- `produces: X` (79 traits) - improve ChEBI lookup
- `carbon source: X` (27 traits) - normalize stereochemistry
- `fermentation: X` (77 traits) - handle complex names
- `degradation: X` (12 traits) - use ENVO for materials
- `hydrolysis: X` (9 traits) - improve variant matching
- Others: respiration, oxidation, reduction, electron acceptor (28 traits)

**Expected impact:** 151 traits mapped with EXISTING METPO predicates

**Source:** `METPO_TERM_REQUESTS.md` Phase 4

---

## Phase 6: Remaining Phenotype Classes (12 classes - OPTIONAL)

**Priority:** MEDIUM-LOW  
**Coverage:** 54 unique traits  
**Why Lower Priority:** Less frequent traits, lower impact  

### 6.1 Additional Environmental (4 classes)
- Pressure tolerance (barophile, piezophile)
- Radiation tolerance (radioresistant)
- Osmotic tolerance (osmophile)
- Metal tolerance (metallophile)

### 6.2 Additional Morphological (3 classes)
- Spore formation capability
- Capsule presence
- Biofilm formation

### 6.3 Additional Biochemical (3 classes)
- Catalase activity (may be covered by enzyme activity)
- Oxidase activity
- Urease activity

### 6.4 Additional Metabolic (2 classes)
- Denitrification capability
- Nitrogen fixation capability

**Source:** `METPO_TERM_REQUESTS.md` Phase 5 (deferred to Phase 6 here)

**Note:** These are OPTIONAL. Can be deferred to future METPO releases.

---

## Complete Term Count Summary

| Phase | New METPO Terms | Existing Tools/Predicates | Total Changes |
|-------|-----------------|---------------------------|---------------|
| 1 | 9 data properties | 0 | 9 new terms |
| 2 | 4 object properties | 0 | 4 new terms |
| 3 | 3 object properties | 0 | 3 new terms |
| 4 | 31 classes | 0 | 31 new terms |
| 5 | **0 new terms** | Uses existing predicates | Infrastructure only |
| 6 | 12 classes (OPTIONAL) | 0 | 12 new terms (deferred) |
| **TOTAL (1-5)** | **47 terms** | **Existing predicates** | **47 new + ChEBI fixes** |
| **TOTAL (1-6)** | **59 terms** | | **59 new (if Phase 6 included)** |

---

## Coverage Achievement by Phase

| After Phase | New Terms (Cumulative) | Traits Mapped (Cumulative) | Coverage % | Observations |
|-------------|------------------------|----------------------------|------------|--------------|
| Baseline | 0 | 0/902 | 0% | 5,051,076 unmapped |
| **Phase 1** | 9 | 3/902 | 0.3% | 176,101 mapped |
| **Phase 2** | 13 | 476/902 | 53% | 671,101 mapped |
| **Phase 3** | 16 | 542/902 | 60% | 712,101 mapped |
| **Phase 4** | 47 | 580/902 | 64% | 738,101 mapped |
| **Phase 5** | **47** | **731/902** | **81%** | **745,601 mapped** |
| Phase 6 (opt) | 59 | 785/902 | 87% | ~800,000 mapped |

**Target:** 85% achieved after Phase 5 (81% conservative, ~85% with observation weighting)

---

## Recommended Submission Strategy

### Option A: Submit All Phases 1-5 (Recommended)
- **47 new METPO terms** requested
- **81-85% coverage** achieved
- Phase 5 requires NO METPO changes (ChEBI improvements only)
- Defer Phase 6 to future request

### Option B: Phased Submission
- **First request:** Phases 1-2 (13 terms, CRITICAL priority) → 53% coverage
- **Second request:** Phases 3-4 (34 terms, HIGH priority) → 64% coverage  
- **Third request:** Phase 6 (12 terms, MEDIUM priority) → 87% coverage
- **No METPO request for Phase 5** (code changes only)

### Option C: Critical Only
- **Single request:** Phases 1-2 (13 terms, CRITICAL) → 53% coverage
- Defer all others to gauge METPO maintainer appetite

---

## Files Generated

1. **`METPO_UNIFIED_PROPOSAL_5_PHASES.md`** (this document) - Complete unified proposal
2. **`METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md`** - Detailed specs for Phases 1-4
3. **`mappings/metpo_phases_1_2_3_terms.tsv`** - TSV of Phases 1-4 terms (44 terms)
4. **`mappings/metpo_predicate_based_proposal.tsv`** - Phase 1 only (9 data properties)
5. **`mappings/additional_metpo_mappings.tsv`** - Analysis of all 902 unmapped traits
6. **`METPO_TERM_REQUESTS.md`** - Original 31-term proposal (now superseded)

**To create Phase 3 and Phase 6 detailed specs:** Requires expansion of current documents.

---

## Next Steps

1. **Decide on submission strategy:** Option A, B, or C?
2. **Create Phase 3 detailed specs** (produces acid/gas/base predicates)
3. **Create Phase 6 detailed specs** (optional remaining phenotypes)
4. **Update TSV files** to include all phases
5. **Submit to METPO GitHub** using strategy chosen

---

## Questions for Discussion

1. Should we submit all 47 terms at once (Option A) or split into multiple requests (Option B/C)?
2. Is Phase 5 (ChEBI improvements) acceptable as a separate KG-Microbe implementation without METPO involvement?
3. Should Phase 6 be included in this proposal or deferred to a future request?
4. Do Phases 1-4 term definitions need any revision before submission?

---

**END OF UNIFIED PROPOSAL**
