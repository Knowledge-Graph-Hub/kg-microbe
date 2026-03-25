# METPO Term Requests for KG-Microbe MetaTraits Integration

**Date:** 2026-03-25
**Project:** KG-Microbe
**Data Source:** BacDive metatraits (via GTDB taxonomy)
**Analysis:** 902 unique unmapped traits from metatraits_gtdb transform

## Executive Summary

We request **31 new METPO class terms** and **11 new METPO predicate terms** to improve coverage of microbial traits from BacDive. These additions would enable mapping of 619 additional trait instances (68% of currently unmapped traits).

### Impact Breakdown
- **38 phenotypic traits** → Need 31 new METPO class terms
- **581 chemical metabolic traits** → Need 11 new METPO predicate terms
- **151 chemical traits** → Already have predicates, need better ChEBI lookup
- **53 enzyme activities** → Map to EC/GO (outside METPO scope)

## Priority 1: High-Impact METPO Class Terms (Phenotypes)

### 1.1 Morphological Characteristics (7 terms)
| Proposed Term | Parent Class | Definition | Data Coverage | Priority |
|--------------|-------------|------------|---------------|----------|
| cell shape | phenotype | The shape of a bacterial cell (e.g., rod, coccus, spiral, filamentous) | 1 trait | HIGH |
| cell length | phenotype | The length of a bacterial cell, typically measured in micrometers | 3 traits (length, min, max) | HIGH |
| cell width | phenotype | The width/diameter of a bacterial cell, typically measured in micrometers | 3 traits (width, min, max) | HIGH |
| cell color | phenotype | The color or pigmentation of bacterial cells | 2 traits | MEDIUM |
| flagellum arrangement | phenotype | The arrangement pattern of flagella (peritrichous, monotrichous, amphitrichous, lophotrichous) | 1 trait | MEDIUM |

**Notes:**
- `cell shape` should allow values: rod, coccus, bacillus, spirillum, spirochete, vibrio, filamentous, pleomorphic
- `cell length` and `cell width` should support min/max/average measurement ranges
- `flagellum arrangement` should allow values: monotrichous, amphitrichous, lophotrichous, peritrichous, polar

### 1.2 Genomic Qualities (5 terms)
| Proposed Term | Parent Class | Definition | Data Coverage | Priority |
|--------------|-------------|------------|---------------|----------|
| GC content percentage | genomic quality | The percentage of guanine-cytosine base pairs in the genome | 1 trait | HIGH |
| genome size | genomic quality | The total size of the genome in base pairs | 3 traits (size, estimated) | HIGH |
| gene count | genomic quality | The total number of genes in the genome | 3 traits (count, estimated) | MEDIUM |
| coding density | genomic quality | The percentage of the genome that codes for proteins | 1 trait | LOW |

**Notes:**
- `GC content percentage` is a key taxonomic and phenotypic marker in microbiology
- `genome size` should support both measured and estimated values
- `gene count` should support both annotated and predicted values

### 1.3 Environmental Tolerances (12 terms)
| Proposed Term | Parent Class | Definition | Data Coverage | Priority |
|--------------|-------------|------------|---------------|----------|
| oxygen requirement | phenotype | The oxygen requirement for growth (aerobic, anaerobic, facultative, microaerophilic) | 1 trait | HIGH |
| pH tolerance range | environmental quality | The range of pH values that support growth | 4 traits (growth, min, max, preference) | HIGH |
| pH minimum | environmental quality | The minimum pH value that supports growth | 1 trait | HIGH |
| pH maximum | environmental quality | The maximum pH value that supports growth | 1 trait | HIGH |
| pH optimum | environmental quality | The optimal pH value for growth | 1 trait | HIGH |
| temperature tolerance range | environmental quality | The range of temperatures that support growth | 4 traits (growth, min, max, preference) | HIGH |
| temperature minimum | environmental quality | The minimum temperature that supports growth (°C) | 1 trait | HIGH |
| temperature maximum | environmental quality | The maximum temperature that supports growth (°C) | 1 trait | HIGH |
| temperature optimum | environmental quality | The optimal temperature for growth (°C) | 1 trait | HIGH |
| salinity tolerance range | environmental quality | The range of salt concentrations that support growth | 4 traits (growth, min, max, preference) | MEDIUM |
| salinity minimum | environmental quality | The minimum salinity/NaCl concentration that supports growth | 1 trait | MEDIUM |
| salinity maximum | environmental quality | The maximum salinity/NaCl concentration that supports growth | 1 trait | MEDIUM |
| salinity optimum | environmental quality | The optimal salinity/NaCl concentration for growth | 1 trait | MEDIUM |

**Notes:**
- These are critical for ecological modeling and biotechnology applications
- Min/max/optimum triplets are standard in microbiology

### 1.4 Biochemical Test Results (3 terms)
| Proposed Term | Parent Class | Definition | Data Coverage | Priority |
|--------------|-------------|------------|---------------|----------|
| indole production | phenotype | Production of indole from tryptophan via tryptophanase enzyme | 1 trait | MEDIUM |
| methyl red test positive | phenotype | Positive result in methyl red test (indicates mixed acid fermentation) | 1 trait | MEDIUM |
| hemolytic activity | phenotype | Ability to lyse red blood cells (alpha, beta, or gamma hemolysis) | 1 trait | MEDIUM |

**Notes:**
- These are standard microbiological identification tests
- Should be boolean traits (positive/negative) or categorical (alpha/beta/gamma for hemolysis)
- Note: `voges-proskauer test` already exists as METPO:1005017

### 1.5 Growth Characteristics (3 terms)
| Proposed Term | Parent Class | Definition | Data Coverage | Priority |
|--------------|-------------|------------|---------------|----------|
| growth on selective media | phenotype | Ability to grow on selective or differential media | 3 traits | LOW |
| bile resistance | phenotype | Ability to grow in presence of bile acids/salts | 1 trait | LOW |
| biosafety level | risk assessment | Biosafety level classification (BSL-1 to BSL-4) | 1 trait | LOW |

**Notes:**
- `growth on selective media` examples: MacConkey agar, blood agar, EMB agar
- `bile resistance` is important for gut microbiome organisms
- `biosafety level` may be outside METPO scope (organizational rather than phenotypic)

## Priority 2: High-Impact METPO Predicate Terms (Metabolic Processes)

### 2.1 Nutrient Utilization Predicates (6 terms)
| Proposed Predicate | Biolink Equivalent | Definition | Data Coverage | Priority |
|-------------------|-------------------|------------|---------------|----------|
| METPO:2000XXX assimilates | biolink:metabolizes | Organism assimilates (takes up and incorporates) a chemical substance | 266 traits | CRITICAL |
| METPO:2000XXX uses as energy source | biolink:metabolizes | Organism uses chemical as primary energy source | 97 traits | CRITICAL |
| METPO:2000XXX uses as nitrogen source | biolink:metabolizes | Organism uses chemical as nitrogen source for biosynthesis | 57 traits | HIGH |
| METPO:2000XXX uses as electron donor | biolink:metabolizes | Organism uses chemical as electron donor in respiration/photosynthesis | 53 traits | HIGH |
| METPO:2000XXX uses as sulfur source | biolink:metabolizes | Organism uses chemical as sulfur source for biosynthesis | 2 traits | LOW |
| METPO:2000XXX requires for growth | biolink:affected_by | Organism requires chemical for growth (essential growth factor) | 22 traits | MEDIUM |

**Notes:**
- `assimilates` is distinct from "uses as carbon source" - broader nutrient incorporation
- `uses as energy source` is distinct from carbon/electron sources - specifically for ATP/energy generation
- `uses as electron donor` complements existing `METPO:2000008 uses as electron acceptor`
- `requires for growth` indicates essentiality, not just utilization

### 2.2 Metabolic Product Predicates (3 terms)
| Proposed Predicate | Biolink Equivalent | Definition | Data Coverage | Priority |
|-------------------|-------------------|------------|---------------|----------|
| METPO:2000XXX produces acid from | biolink:produces | Organism produces acid from substrate via fermentation/metabolism | 28 traits | HIGH |
| METPO:2000XXX produces gas from | biolink:produces | Organism produces gas (CO2, H2, etc.) from substrate | 16 traits | MEDIUM |
| METPO:2000XXX produces base from | biolink:produces | Organism produces base/alkaline products from substrate | 7 traits | LOW |

**Notes:**
- These complement existing `METPO:2000202 produces`
- Specify the metabolic outcome (acid/gas/base production)
- Important for fermentation characterization and diagnostic tests

### 2.3 Catabolic Mode Predicates (2 terms)
| Proposed Predicate | Biolink Equivalent | Definition | Data Coverage | Priority |
|-------------------|-------------------|------------|---------------|----------|
| METPO:2000XXX aerobically catabolizes | biolink:metabolizes | Organism breaks down substrate via aerobic catabolism | 9 traits | MEDIUM |
| METPO:2000XXX anaerobically catabolizes | biolink:metabolizes | Organism breaks down substrate via anaerobic catabolism | 4 traits | MEDIUM |

**Notes:**
- These complement existing metabolic predicates but specify aerobic vs anaerobic mode
- Distinct from fermentation (which is already METPO:2000011)

## Priority 3: Improve ChEBI Chemical Lookup (No New METPO Terms Needed)

**151 traits** have pattern resolvers but ChEBI lookup fails:
- 79 produces: traits (e.g., produces: poly-beta-hydroxyalkanoate, produces: fluorescein)
- 27 carbon source: traits (e.g., carbon source: bromosuccinate)
- 12 degradation: traits (e.g., degradation: plastic, degradation: aromatic hydrocarbon)
- 9 hydrolysis: traits (e.g., hydrolysis: casein hydrolysate)
- 6 respiration: traits
- Others: fermentation, oxidation, reduction, utilizes, electron acceptor

**Recommended solutions:**
1. **Expand ChEBI synonym matching** - Many compounds have variant names
2. **Add stereochemistry normalization** - Remove (R)/(S)/(+)/(-) prefixes for broad matching
3. **Handle polymer names** - Map to parent compound or polymer class
4. **Support material terms** - Use ENVO for complex materials (plastic, aromatic compound)
5. **Add name normalization** - Handle "casein hydrolysate" vs "casein" variants

## Priority 4: Enzyme Activity Mapping (Outside METPO Scope)

**53 enzyme activity traits** should map to EC numbers or GO molecular functions:

**Approach:**
1. Extract EC numbers when present in trait name (e.g., "catalase (EC1.11.1.6)")
2. Map enzyme common names to EC database (e.g., "lipase" → EC:3.1.1.3)
3. Fallback to GO molecular function for broad enzyme classes (e.g., "oxidase" → GO:0016491)

**Note:** This is outside METPO scope - enzymes are molecular functions, not organismal traits.

## Implementation Roadmap

### Phase 1: Critical METPO Predicates (Immediate Impact: 619 traits)
1. Add `assimilates` predicate (266 traits)
2. Add `uses as energy source` predicate (97 traits)
3. Add `uses as nitrogen source` predicate (57 traits)
4. Add `uses as electron donor` predicate (53 traits)
5. Implement pattern resolvers in `_resolve_chemical_trait()` for these predicates

### Phase 2: High-Priority METPO Class Terms (Immediate Impact: 20+ traits)
1. Add morphological terms (cell shape, length, width) - 7 traits
2. Add genomic quality terms (GC%, genome size, gene count) - 7 traits
3. Add environmental tolerance terms (pH, temperature ranges) - 12 traits
4. Add to METPO classes sheet with appropriate synonyms
5. Update manual `phenotype_mappings.tsv` as needed

### Phase 3: Medium-Priority METPO Predicates (Impact: 51 traits)
1. Add `produces acid from` predicate (28 traits)
2. Add `requires for growth` predicate (22 traits)
3. Add `produces gas from` predicate (16 traits)
4. Implement pattern resolvers

### Phase 4: ChEBI Lookup Improvements (Impact: 151 traits)
1. Implement synonym expansion
2. Add stereochemistry normalization
3. Support ENVO lookups for materials
4. Handle complex/polymer names

### Phase 5: Lower-Priority Terms (Impact: 30+ traits)
1. Biochemical test terms (indole, methyl red, hemolysis)
2. Salinity tolerance terms
3. Growth characteristic terms
4. Remaining metabolic predicates (catabolization modes, base production, sulfur source)

## Expected Coverage Improvement

| Phase | New Terms | Traits Covered | % of Unmapped |
|-------|-----------|----------------|---------------|
| Current | 0 | 0 | 0% |
| Phase 1 | 4 predicates | 473 | 52% |
| Phase 2 | 12 classes | +26 | 55% |
| Phase 3 | 3 predicates | +66 | 60% |
| Phase 4 | 0 (ChEBI fixes) | +151 | 77% |
| Phase 5 | 12 terms | +54 | 83% |
| **Total** | **31 terms** | **770/902** | **85%** |

Remaining 15% (132 traits) are enzyme activities (map to EC/GO, outside METPO scope).

## Files Generated

1. **`additional_metpo_mappings.tsv`** - Detailed categorization of all 902 unmapped traits
2. **`METATRAITS_UNMAPPED_ANALYSIS.md`** - Comprehensive analysis of unmapped traits
3. **`METPO_TERM_REQUESTS.md`** - This document with specific term requests

## Contact

For questions or discussion about these term requests:
- KG-Microbe team
- METPO ontology team (berkeleybop/metpo GitHub repository)
