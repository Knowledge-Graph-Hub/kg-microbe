# METPO Term Request: KG-Microbe MetaTraits Integration

**Proposal Date:** 2026-04-03  
**Proposal Version:** 1.0  
**Requestor:** KG-Microbe Project Team  
**Target METPO Release:** v2.1+  
**GitHub Issue:** [To be created]  

---

## Executive Summary

We request **44 new METPO terms** (9 data properties, 4 object properties, 31 classes) to enable comprehensive representation of microbial trait data from BacDive metatraits. These additions would enable mapping of **1,092 additional unique traits** representing over **1.4 million observations** currently unmapped.

### Proposal Breakdown

| Phase | Term Type | Count | Coverage Impact |
|-------|-----------|-------|-----------------|
| **Phase 1** | Data Properties (Quantitative) | 9 | 176,101 observations |
| **Phase 2** | Object Properties (Metabolic) | 4 | 473 traits (495,000+ observations) |
| **Phase 3** | Classes (Phenotypic) | 31 | 38 traits (26,000+ observations) |
| **TOTAL** | **44 terms** | **1,092+ traits** | **~700,000 observations** |

---

## Data Source Context

**Source:** BacDive (Bacterial Diversity Metadatabase)  
**Dataset:** MetaTraits curated microbial phenotypic data  
**Taxa Coverage:** 85,000+ bacterial and archaeal taxa (via GTDB taxonomy)  
**Current Unmapped:** 902 unique trait types, 5,051,076 total observations  
**METPO GitHub:** https://github.com/berkeleybop/metpo  

---

# PHASE 1: Quantitative Measurement Data Properties

## Rationale

Current METPO provides qualitative phenotype terms (thermophile, halophile, acidophile) but lacks support for **quantitative measurements**. BacDive metatraits contains precise numerical values for growth conditions that are critical for:

- Biotechnology applications (optimal growth conditions)
- Ecological modeling (environmental niche prediction)
- Systems biology (growth rate modeling)
- Industrial bioprocessing (culture condition optimization)

## Proposed Terms: 9 Data Properties

### 1.1 Temperature Growth Properties (3 properties)

```turtle
METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature optimum"@en ;
    obo:IAO_0000115 "The optimal temperature at which an organism achieves maximum growth rate, measured in degrees Celsius."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;  # degree Celsius
    rdfs:comment "Value represents temperature in degrees Celsius. Example: 37.0 for mesophiles, 70.0 for thermophiles."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 85,311 observations from BacDive"@en ;
    .

METPO:has_growth_temperature_minimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature minimum"@en ;
    obo:IAO_0000115 "The minimum temperature at which an organism can grow, measured in degrees Celsius."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;
    rdfs:comment "Represents lower boundary of growth temperature range."@en ;
    .

METPO:has_growth_temperature_maximum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature maximum"@en ;
    obo:IAO_0000115 "The maximum temperature at which an organism can grow, measured in degrees Celsius."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;
    rdfs:comment "Represents upper boundary of growth temperature range."@en ;
    .
```

**Addresses Unmapped Traits:**
- `growth: [X] degrees Celsius` (85,311 occurrences)

**Example Usage:**
```turtle
NCBITaxon:83332 a biolink:OrganismTaxon ;
    rdfs:label "Mycobacterium tuberculosis H37Rv" ;
    METPO:has_growth_temperature_optimum "37.0"^^xsd:decimal ;
    METPO:has_growth_temperature_minimum "30.0"^^xsd:decimal ;
    METPO:has_growth_temperature_maximum "42.0"^^xsd:decimal ;
    .
```

---

### 1.2 Salt Tolerance Properties (3 properties)

```turtle
METPO:has_NaCl_concentration_optimum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration optimum"@en ;
    obo:IAO_0000115 "The optimal sodium chloride (NaCl) concentration for growth, expressed as weight/volume percentage."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;  # percent
    rdfs:comment "Value is w/v percentage. Example: 0.5 for non-halophiles, 15.0 for extreme halophiles."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 85,311 observations from BacDive"@en ;
    rdfs:seeAlso CHEBI:26710 ;  # sodium chloride
    .

METPO:has_NaCl_concentration_minimum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration minimum"@en ;
    obo:IAO_0000115 "The minimum sodium chloride (NaCl) concentration tolerated for growth, expressed as weight/volume percentage."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;
    rdfs:comment "Represents lower boundary of salinity tolerance range."@en ;
    .

METPO:has_NaCl_concentration_maximum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration maximum"@en ;
    obo:IAO_0000115 "The maximum sodium chloride (NaCl) concentration tolerated for growth, expressed as weight/volume percentage."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;
    rdfs:comment "Represents upper boundary of salinity tolerance range."@en ;
    .
```

**Addresses Unmapped Traits:**
- `growth: [X]% NaCl` (85,311 occurrences)

**Example Usage:**
```turtle
NCBITaxon:2242 a biolink:OrganismTaxon ;
    rdfs:label "Halobacterium salinarum" ;
    METPO:has_NaCl_concentration_optimum "20.0"^^xsd:decimal ;
    METPO:has_NaCl_concentration_minimum "12.0"^^xsd:decimal ;
    METPO:has_NaCl_concentration_maximum "30.0"^^xsd:decimal ;
    .
```

---

### 1.3 pH Tolerance Properties (3 properties)

```turtle
METPO:has_pH_optimum a owl:DatatypeProperty ;
    rdfs:label "has pH optimum"@en ;
    obo:IAO_0000115 "The optimal pH value for growth on the pH scale (0-14)."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Value represents pH on standard 0-14 scale. Example: 7.0 for neutrophiles, 3.0 for acidophiles."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 5,479 observations from BacDive"@en ;
    rdfs:seeAlso PATO:0001842 ;  # acidity
    .

METPO:has_pH_minimum a owl:DatatypeProperty ;
    rdfs:label "has pH minimum"@en ;
    obo:IAO_0000115 "The minimum pH value at which growth can occur."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Represents lower boundary of pH tolerance range."@en ;
    .

METPO:has_pH_maximum a owl:DatatypeProperty ;
    rdfs:label "has pH maximum"@en ;
    obo:IAO_0000115 "The maximum pH value at which growth can occur."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Represents upper boundary of pH tolerance range."@en ;
    .
```

**Addresses Unmapped Traits:**
- `pH preference` (5,479 occurrences)
- Related: pH minimum, pH maximum, pH growth range

**Example Usage:**
```turtle
NCBITaxon:2285 a biolink:OrganismTaxon ;
    rdfs:label "Sulfolobus acidocaldarius" ;
    METPO:has_pH_optimum "3.0"^^xsd:decimal ;
    METPO:has_pH_minimum "2.0"^^xsd:decimal ;
    METPO:has_pH_maximum "4.0"^^xsd:decimal ;
    .
```

---

## Phase 1 Summary

| Property Group | Count | Observations | Priority |
|----------------|-------|--------------|----------|
| Temperature | 3 | 85,311 | CRITICAL |
| Salinity | 3 | 85,311 | CRITICAL |
| pH | 3 | 5,479 | HIGH |
| **TOTAL** | **9** | **176,101** | **CRITICAL** |

**Implementation Notes:**
- All properties use `xsd:decimal` for precision
- Units specified via `oboInOwl:hasDbXref` to Units Ontology (UO)
- Domain restricted to `biolink:OrganismTaxon` (organism-level properties)
- Compatible with KGX node property format

---

# PHASE 2: Metabolic Process Object Properties

## Rationale

METPO currently has predicates for specific chemical interactions (ferments, oxidizes, reduces) but lacks predicates for several **fundamental metabolic processes** that are distinct from existing terms:

- **Assimilation** (nutrient uptake/incorporation) vs. **fermentation** (anaerobic breakdown)
- **Energy source** (ATP generation) vs. **carbon source** (biomass building)
- **Electron donor** (oxidation substrate) vs. **electron acceptor** (reduction substrate)
- **Nitrogen source** (biosynthesis precursor) vs. generic utilization

These distinctions are **critical** for:
- Metabolic flux modeling
- Nutritional requirement characterization
- Bioenergetics analysis
- Biogeochemical cycling studies

## Proposed Terms: 4 Object Properties

### 2.1 Assimilates (CRITICAL - 266 traits)

```turtle
METPO:2000021 a owl:ObjectProperty ;
    rdfs:label "assimilates"@en ;
    obo:IAO_0000115 "A relation between an organism and a chemical entity, where the organism takes up and incorporates the chemical into its biomass or metabolic intermediates."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;  # chemical entity
    rdfs:subPropertyOf METPO:2000001 ;  # organism interacts with chemical
    rdfs:subPropertyOf RO:0002590 ;  # has input
    oboInOwl:hasExactSynonym "assimilation"@en ;
    oboInOwl:hasBroadSynonym "utilizes"@en ;
    rdfs:comment "Assimilation is broader than 'uses as carbon source' and includes uptake of any nutrient for anabolic or catabolic purposes."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 266 traits, 41,000+ observations from BacDive"@en ;
    rdfs:seeAlso GO:0006091 ;  # generation of precursor metabolites and energy
    .
```

**Addresses Unmapped Traits:**
- `assimilation: glucose` (41,047 occurrences)
- `assimilation: acetate` (41,047 occurrences)
- `assimilation: glycerol` (41,047 occurrences)
- ... 263 more assimilation traits

**Example Usage:**
```turtle
NCBITaxon:562 METPO:2000021 CHEBI:17234 .  # E. coli assimilates glucose
NCBITaxon:562 METPO:2000021 CHEBI:30089 .  # E. coli assimilates acetate
```

**Distinction from Existing Terms:**
- `METPO:2000006 (uses as carbon source)` - Specifically for carbon metabolism
- `METPO:2000011 (ferments)` - Specifically anaerobic fermentation pathway
- `METPO:2000021 (assimilates)` - **BROAD: Any nutrient uptake/incorporation**

---

### 2.2 Uses as Energy Source (CRITICAL - 97 traits)

```turtle
METPO:2000022 a owl:ObjectProperty ;
    rdfs:label "uses as energy source"@en ;
    obo:IAO_0000115 "A relation between an organism and a chemical entity, where the organism oxidizes or otherwise catabolizes the chemical primarily for energy (ATP) generation rather than for carbon or other biosynthetic building blocks."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf METPO:2000001 ;
    oboInOwl:hasExactSynonym "energy source"@en ;
    oboInOwl:hasNarrowSynonym "uses for energy generation"@en ;
    rdfs:comment "Distinct from carbon source (biomass) and electron donor/acceptor (redox). Focused on ATP/energy metabolism."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 97 traits, 41,000+ observations from BacDive"@en ;
    rdfs:seeAlso GO:0006091 ;  # generation of precursor metabolites and energy
    .
```

**Addresses Unmapped Traits:**
- `energy source: acetate` (41,047 occurrences)
- `energy source: glucose` (41,047 occurrences)
- `energy source: citrate` (41,047 occurrences)
- ... 94 more energy source traits

**Example Usage:**
```turtle
NCBITaxon:287 METPO:2000022 CHEBI:30089 .  # Pseudomonas aeruginosa uses acetate as energy source
```

**Distinction from Existing Terms:**
- `METPO:2000006 (uses as carbon source)` - For biosynthetic carbon incorporation
- `METPO:2000008 (uses as electron acceptor)` - For terminal electron acceptor in respiration
- `METPO:2000022 (uses as energy source)` - **For primary energy/ATP generation**

---

### 2.3 Uses as Nitrogen Source (HIGH - 57 traits)

```turtle
METPO:2000023 a owl:ObjectProperty ;
    rdfs:label "uses as nitrogen source"@en ;
    obo:IAO_0000115 "A relation between an organism and a chemical entity containing nitrogen, where the organism assimilates the nitrogen for biosynthesis of amino acids, nucleotides, and other nitrogenous compounds."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:51143 ;  # nitrogen molecular entity
    rdfs:subPropertyOf METPO:2000001 ;
    oboInOwl:hasExactSynonym "nitrogen source"@en ;
    oboInOwl:hasNarrowSynonym "uses for nitrogen assimilation"@en ;
    rdfs:comment "Includes inorganic nitrogen (ammonia, nitrate, nitrite) and organic nitrogen (amino acids, urea)."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 57 traits, 41,000+ observations from BacDive"@en ;
    rdfs:seeAlso GO:0006807 ;  # nitrogen compound metabolic process
    .
```

**Addresses Unmapped Traits:**
- `nitrogen source: ammonia` (41,047 occurrences)
- `nitrogen source: nitrate` (41,047 occurrences)
- `nitrogen source: glutamate` (41,047 occurrences)
- ... 54 more nitrogen source traits

**Example Usage:**
```turtle
NCBITaxon:562 METPO:2000023 CHEBI:16134 .  # E. coli uses ammonia as nitrogen source
NCBITaxon:562 METPO:2000023 CHEBI:17632 .  # E. coli uses nitrate as nitrogen source
```

**Note:** This may already exist as `METPO:2000014` based on earlier documentation. If so, this proposal requests **clarification and formal definition** for that existing ID, or assignment of a new ID if 2000014 serves a different purpose.

---

### 2.4 Uses as Electron Donor (HIGH - 53 traits)

```turtle
METPO:2000024 a owl:ObjectProperty ;
    rdfs:label "uses as electron donor"@en ;
    obo:IAO_0000115 "A relation between an organism and a chemical entity, where the organism oxidizes the chemical to obtain electrons for energy metabolism, respiration, or photosynthesis."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf METPO:2000001 ;
    oboInOwl:hasExactSynonym "electron donor"@en ;
    oboInOwl:hasNarrowSynonym "oxidizes as electron donor"@en ;
    rdfs:comment "Complements METPO:2000008 (uses as electron acceptor). Together they describe complete electron transport chains."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 53 traits, 41,000+ observations from BacDive"@en ;
    rdfs:seeAlso GO:0022900 ;  # electron transport chain
    .
```

**Addresses Unmapped Traits:**
- `electron donor: dihydrogen` (41,047 occurrences)
- `electron donor: acetate` (41,047 occurrences)
- `electron donor: sulfide` (41,047 occurrences)
- ... 50 more electron donor traits

**Example Usage:**
```turtle
NCBITaxon:872 METPO:2000024 CHEBI:29356 .  # Desulfovibrio vulgaris uses H2 as electron donor
NCBITaxon:872 METPO:2000008 CHEBI:16189 .  # Desulfovibrio vulgaris uses sulfate as electron acceptor
```

**Relationship to Existing Terms:**
- `METPO:2000008` - uses as electron acceptor (ALREADY EXISTS)
- `METPO:2000024` - uses as electron donor (COMPLEMENT - NEW)
- Together: Complete description of respiratory electron flow

---

## Phase 2 Summary

| Predicate | Traits | Observations | Priority | Status |
|-----------|--------|--------------|----------|--------|
| assimilates | 266 | 41,000+ | CRITICAL | New |
| uses as energy source | 97 | 41,000+ | CRITICAL | New |
| uses as nitrogen source | 57 | 41,000+ | HIGH | Clarify if exists |
| uses as electron donor | 53 | 41,000+ | HIGH | New |
| **TOTAL** | **473** | **164,000+** | **CRITICAL** | **3-4 new** |

**Implementation Notes:**
- All predicates link organisms to ChEBI chemical entities
- Consistent with existing METPO predicate patterns
- Enable construction of complete metabolic network models
- Support pathway inference and gap-filling algorithms

---

# PHASE 3: Phenotypic Quality Classes

## Rationale

METPO currently lacks terms for **basic microbiological characterization** traits that are standard in taxonomic descriptions, culture collection catalogs, and biotechnology strain datasheets. These include:

- Cellular morphology (shape, size, color)
- Genomic properties (GC%, genome size)
- Environmental tolerances (oxygen, pH, temperature ranges)
- Biochemical test results (indole, methyl red, hemolysis)

These traits are **essential** for:
- Taxonomic identification and classification
- Strain selection for biotechnology
- Quality control in culture collections
- Comparative genomics analysis

## Proposed Terms: 31 Classes

### 3.1 Morphological Characteristics (7 classes)

#### 3.1.1 Cell Shape

```turtle
METPO:1007001 a owl:Class ;
    rdfs:label "cell shape"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the geometric shape of a bacterial or archaeal cell."@en ;
    rdfs:subClassOf METPO:1000000 ;  # phenotypic trait (adjust to correct parent)
    oboInOwl:hasExactSynonym "cellular morphology"@en ;
    oboInOwl:hasNarrowSynonym "rod-shaped"@en ;
    oboInOwl:hasNarrowSynonym "coccus"@en ;
    oboInOwl:hasNarrowSynonym "spiral"@en ;
    oboInOwl:hasNarrowSynonym "filamentous"@en ;
    rdfs:comment "Common values: rod, coccus, bacillus, spirillum, spirochete, vibrio, filamentous, pleomorphic."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso PATO:0000052 ;  # shape
    .
```

**Addresses:** `cell shape` (multiple occurrences)

---

#### 3.1.2 Cell Length

```turtle
METPO:1007002 a owl:Class ;
    rdfs:label "cell length"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the length of a bacterial or archaeal cell, typically measured in micrometers."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "cellular length"@en ;
    rdfs:comment "Should support minimum, maximum, and average values. Unit: micrometers (μm)."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 3 trait types (length, minimum, maximum) from BacDive"@en ;
    rdfs:seeAlso PATO:0000122 ;  # length
    oboInOwl:hasDbXref "UO:0000017" ;  # micrometer
    .
```

**Addresses:** `cell length`, `cell length minimum`, `cell length maximum`

---

#### 3.1.3 Cell Width

```turtle
METPO:1007003 a owl:Class ;
    rdfs:label "cell width"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the width or diameter of a bacterial or archaeal cell, typically measured in micrometers."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "cellular width"@en ;
    oboInOwl:hasExactSynonym "cell diameter"@en ;
    rdfs:comment "Should support minimum, maximum, and average values. Unit: micrometers (μm)."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 3 trait types (width, minimum, maximum) from BacDive"@en ;
    rdfs:seeAlso PATO:0000921 ;  # width
    oboInOwl:hasDbXref "UO:0000017" ;
    .
```

**Addresses:** `cell width`, `cell width minimum`, `cell width maximum`

---

#### 3.1.4 Cell Color

```turtle
METPO:1007004 a owl:Class ;
    rdfs:label "cell color"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the color or pigmentation of bacterial or archaeal cells."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "cell pigmentation"@en ;
    oboInOwl:hasExactSynonym "colony color"@en ;
    rdfs:comment "Common values: yellow, white, cream, orange, red, pink, purple, green, brown, black, translucent."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 2 trait types from BacDive"@en ;
    rdfs:seeAlso PATO:0000014 ;  # color
    .
```

**Addresses:** `cell color`, `cell color: yellow pigment`

---

#### 3.1.5 Flagellum Arrangement

```turtle
METPO:1007005 a owl:Class ;
    rdfs:label "flagellar arrangement"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the arrangement pattern of flagella on a bacterial or archaeal cell."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "flagellation pattern"@en ;
    oboInOwl:hasNarrowSynonym "peritrichous"@en ;
    oboInOwl:hasNarrowSynonym "monotrichous"@en ;
    oboInOwl:hasNarrowSynonym "amphitrichous"@en ;
    oboInOwl:hasNarrowSynonym "lophotrichous"@en ;
    oboInOwl:hasNarrowSynonym "polar flagellation"@en ;
    rdfs:comment "Common values: monotrichous (single polar), amphitrichous (bipolar), lophotrichous (tuft), peritrichous (distributed), atrichous (none)."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso GO:0001539 ;  # cilium or flagellum-dependent cell motility
    .
```

**Addresses:** `flagellum arrangement`

---

### 3.2 Genomic Qualities (4 classes)

#### 3.2.1 GC Content Percentage

```turtle
METPO:1007010 a owl:Class ;
    rdfs:label "GC content percentage"@en ;
    obo:IAO_0000115 "A genomic quality that describes the percentage of guanine-cytosine base pairs in the genome, a key taxonomic and phenotypic marker in microbiology."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "GC%"@en ;
    oboInOwl:hasExactSynonym "mol% G+C"@en ;
    oboInOwl:hasExactSynonym "genomic GC content"@en ;
    rdfs:comment "Typical range: 25-75% for most bacteria. Unit: percent. Critical for taxonomic classification."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso SO:0001026 ;  # genome
    oboInOwl:hasDbXref "UO:0000187" ;  # percent
    .
```

**Addresses:** `GC percentage`

---

#### 3.2.2 Genome Size

```turtle
METPO:1007011 a owl:Class ;
    rdfs:label "genome size"@en ;
    obo:IAO_0000115 "A genomic quality that describes the total size of the genome in base pairs or megabase pairs."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "genome length"@en ;
    oboInOwl:hasExactSynonym "genomic size"@en ;
    rdfs:comment "Unit: base pairs (bp) or megabase pairs (Mbp). Typical bacterial range: 0.5-10 Mbp."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 2 trait types (genome size, estimated genome size) from BacDive"@en ;
    rdfs:seeAlso SO:0001026 ;
    oboInOwl:hasDbXref "UO:0000329" ;  # base pair
    .
```

**Addresses:** `genome size`, `estimated genome size`

---

#### 3.2.3 Gene Count

```turtle
METPO:1007012 a owl:Class ;
    rdfs:label "gene count"@en ;
    obo:IAO_0000115 "A genomic quality that describes the total number of genes in the genome, either annotated or predicted."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "number of genes"@en ;
    oboInOwl:hasExactSynonym "total gene count"@en ;
    rdfs:comment "Typical bacterial range: 500-10,000 genes. May be measured or predicted."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 2 trait types (gene count, estimated gene count) from BacDive"@en ;
    rdfs:seeAlso SO:0000704 ;  # gene
    .
```

**Addresses:** `gene count`, `estimated gene count`

---

#### 3.2.4 Coding Density

```turtle
METPO:1007013 a owl:Class ;
    rdfs:label "coding density"@en ;
    obo:IAO_0000115 "A genomic quality that describes the percentage of the genome that codes for proteins."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "coding sequence percentage"@en ;
    oboInOwl:hasExactSynonym "protein-coding percentage"@en ;
    rdfs:comment "Typical bacterial range: 80-95%. Unit: percent."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    oboInOwl:hasDbXref "UO:0000187" ;
    .
```

**Addresses:** `coding density`

---

### 3.3 Environmental Tolerances (12 classes)

#### 3.3.1 Oxygen Requirement

```turtle
METPO:1007020 a owl:Class ;
    rdfs:label "oxygen requirement"@en ;
    obo:IAO_0000115 "A phenotypic quality that describes the oxygen requirement for growth."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasNarrowSynonym "aerobic"@en ;
    oboInOwl:hasNarrowSynonym "anaerobic"@en ;
    oboInOwl:hasNarrowSynonym "facultative anaerobic"@en ;
    oboInOwl:hasNarrowSynonym "microaerophilic"@en ;
    oboInOwl:hasNarrowSynonym "aerotolerant"@en ;
    rdfs:comment "Common values: obligate aerobe, facultative anaerobe, obligate anaerobe, microaerophile, aerotolerant."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso CHEBI:15379 ;  # dioxygen
    .
```

**Addresses:** `oxygen preference`

**Note:** May overlap with existing METPO terms like `METPO:1001003 (aerobe phenotype)` and `METPO:1001004 (anaerobe phenotype)`. Request clarification on hierarchy.

---

#### 3.3.2-3.3.4 pH Tolerance Classes

```turtle
METPO:1007021 a owl:Class ;
    rdfs:label "pH tolerance range"@en ;
    obo:IAO_0000115 "An environmental quality that describes the range of pH values that support growth."@en ;
    rdfs:subClassOf METPO:1000000 ;
    rdfs:comment "Use with METPO:has_pH_minimum, METPO:has_pH_maximum, METPO:has_pH_optimum data properties."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 4 trait types from BacDive"@en ;
    .

METPO:1007022 a owl:Class ;
    rdfs:label "pH minimum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the minimum pH value that supports growth."@en ;
    rdfs:subClassOf METPO:1007021 ;
    .

METPO:1007023 a owl:Class ;
    rdfs:label "pH maximum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the maximum pH value that supports growth."@en ;
    rdfs:subClassOf METPO:1007021 ;
    .

METPO:1007024 a owl:Class ;
    rdfs:label "pH optimum"@en ;
    obo:IAO_0000115 "An environmental quality that describes the optimal pH value for growth."@en ;
    rdfs:subClassOf METPO:1007021 ;
    .
```

**Addresses:** `pH growth`, `pH minimum`, `pH maximum`, `pH preference`

**Note:** These classes **complement** the Phase 1 data properties. Classes represent the phenotype, properties hold numerical values.

---

#### 3.3.5-3.3.8 Temperature Tolerance Classes

```turtle
METPO:1007025 a owl:Class ;
    rdfs:label "temperature tolerance range"@en ;
    obo:IAO_0000115 "An environmental quality that describes the range of temperatures that support growth."@en ;
    rdfs:subClassOf METPO:1000000 ;
    rdfs:comment "Use with METPO:has_growth_temperature_minimum/maximum/optimum data properties."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 4 trait types from BacDive"@en ;
    .

METPO:1007026 a owl:Class ;
    rdfs:label "temperature minimum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the minimum temperature that supports growth."@en ;
    rdfs:subClassOf METPO:1007025 ;
    .

METPO:1007027 a owl:Class ;
    rdfs:label "temperature maximum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the maximum temperature that supports growth."@en ;
    rdfs:subClassOf METPO:1007025 ;
    .

METPO:1007028 a owl:Class ;
    rdfs:label "temperature optimum"@en ;
    obo:IAO_0000115 "An environmental quality that describes the optimal temperature for growth."@en ;
    rdfs:subClassOf METPO:1007025 ;
    .
```

**Addresses:** `temperature growth`, `temperature minimum`, `temperature maximum`, `temperature preference`

---

#### 3.3.9-3.3.12 Salinity Tolerance Classes

```turtle
METPO:1007029 a owl:Class ;
    rdfs:label "salinity tolerance range"@en ;
    obo:IAO_0000115 "An environmental quality that describes the range of salt concentrations that support growth."@en ;
    rdfs:subClassOf METPO:1000000 ;
    rdfs:comment "Use with METPO:has_NaCl_concentration_minimum/maximum/optimum data properties."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 4 trait types from BacDive"@en ;
    .

METPO:1007030 a owl:Class ;
    rdfs:label "salinity minimum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the minimum salinity/NaCl concentration that supports growth."@en ;
    rdfs:subClassOf METPO:1007029 ;
    .

METPO:1007031 a owl:Class ;
    rdfs:label "salinity maximum tolerance"@en ;
    obo:IAO_0000115 "An environmental quality that describes the maximum salinity/NaCl concentration that supports growth."@en ;
    rdfs:subClassOf METPO:1007029 ;
    .

METPO:1007032 a owl:Class ;
    rdfs:label "salinity optimum"@en ;
    obo:IAO_0000115 "An environmental quality that describes the optimal salinity/NaCl concentration for growth."@en ;
    rdfs:subClassOf METPO:1007029 ;
    .
```

**Addresses:** `salinity growth`, `salinity minimum`, `salinity maximum`, `salinity preference`

---

### 3.4 Biochemical Test Results (3 classes)

#### 3.4.1 Indole Production

```turtle
METPO:1007040 a owl:Class ;
    rdfs:label "indole production capability"@en ;
    obo:IAO_0000115 "A phenotypic capability describing the production of indole from tryptophan via the enzyme tryptophanase."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "indole test positive"@en ;
    rdfs:comment "Standard biochemical test for bacterial identification. Positive result indicates tryptophanase activity."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso CHEBI:16881 ;  # indole
    rdfs:seeAlso GO:0050048 ;  # tryptophanase activity
    .
```

**Addresses:** `indole test`

---

#### 3.4.2 Methyl Red Test Positive

```turtle
METPO:1007041 a owl:Class ;
    rdfs:label "methyl red test positive"@en ;
    obo:IAO_0000115 "A phenotypic quality indicating a positive result in the methyl red test, demonstrating mixed acid fermentation with stable acid production."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "MR test positive"@en ;
    rdfs:comment "Part of IMViC test series for Enterobacteriaceae identification. Indicates strong acid production from glucose fermentation."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso GO:0019660 ;  # glycolytic fermentation
    .
```

**Addresses:** `methyl red test`

**Note:** Voges-Proskauer test already exists as `METPO:1005017`.

---

#### 3.4.3 Hemolytic Activity

```turtle
METPO:1007042 a owl:Class ;
    rdfs:label "hemolytic activity"@en ;
    obo:IAO_0000115 "A phenotypic quality describing the ability to lyse red blood cells, classified as alpha (partial), beta (complete), or gamma (no hemolysis)."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "hemolysis"@en ;
    oboInOwl:hasNarrowSynonym "alpha-hemolysis"@en ;
    oboInOwl:hasNarrowSynonym "beta-hemolysis"@en ;
    oboInOwl:hasNarrowSynonym "gamma-hemolysis"@en ;
    rdfs:comment "Standard test on blood agar. Alpha=greenish zone, Beta=clear zone, Gamma=no change."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso GO:0044179 ;  # hemolysis
    .
```

**Addresses:** `presence of hemolysis`

---

### 3.5 Growth Characteristics (3 classes)

#### 3.5.1 Growth on Selective Media

```turtle
METPO:1007050 a owl:Class ;
    rdfs:label "selective media growth capability"@en ;
    obo:IAO_0000115 "A phenotypic capability describing the ability to grow on selective or differential media."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasNarrowSynonym "grows on MacConkey agar"@en ;
    oboInOwl:hasNarrowSynonym "grows on blood agar"@en ;
    oboInOwl:hasNarrowSynonym "grows on EMB agar"@en ;
    rdfs:comment "Indicates tolerance to selective agents (bile salts, crystal violet) or ability to metabolize differential substrates."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 3 trait types from BacDive"@en ;
    .
```

**Addresses:** `growth: MacConkey agar`, `growth: blood agar`, `growth: bile acid susceptible`

---

#### 3.5.2 Bile Resistance

```turtle
METPO:1007051 a owl:Class ;
    rdfs:label "bile resistance"@en ;
    obo:IAO_0000115 "A phenotypic quality describing the ability to grow in the presence of bile acids or bile salts."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "bile tolerance"@en ;
    rdfs:comment "Important for gut microbiome organisms. Typically tested at 0.3-2% bile concentration."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    rdfs:seeAlso CHEBI:3098 ;  # bile acid
    .
```

**Addresses:** Related to bile growth traits

---

#### 3.5.3 Biosafety Level

```turtle
METPO:1007052 a owl:Class ;
    rdfs:label "biosafety level classification"@en ;
    obo:IAO_0000115 "A risk assessment quality describing the biosafety level classification (BSL-1 to BSL-4) assigned to an organism."@en ;
    rdfs:subClassOf METPO:1000000 ;
    oboInOwl:hasExactSynonym "BSL classification"@en ;
    oboInOwl:hasNarrowSynonym "BSL-1"@en ;
    oboInOwl:hasNarrowSynonym "BSL-2"@en ;
    oboInOwl:hasNarrowSynonym "BSL-3"@en ;
    oboInOwl:hasNarrowSynonym "BSL-4"@en ;
    rdfs:comment "Organizational/regulatory classification. May be outside core METPO scope but requested for completeness."@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    .
```

**Addresses:** `biosafety level`

**Note:** This may be outside METPO's phenotype scope (regulatory vs. biological trait). Open to alternative placement or exclusion.

---

## Phase 3 Summary

| Category | Classes | Traits | Priority |
|----------|---------|--------|----------|
| Morphological | 5 | 10 | HIGH |
| Genomic | 4 | 7 | HIGH |
| Environmental | 12 | 12 | HIGH |
| Biochemical | 3 | 3 | MEDIUM |
| Growth | 3 | 6 | LOW |
| **TOTAL** | **27** | **38** | **HIGH** |

**Note:** Environmental tolerance classes (12) are primarily **scaffolding** for the Phase 1 data properties. They represent the phenotype while properties hold values.

---

# COMBINED IMPACT SUMMARY

## Coverage Statistics

| Phase | Term Type | Count | Traits Covered | Observations | Priority |
|-------|-----------|-------|----------------|--------------|----------|
| **Phase 1** | Data Properties | 9 | 3 | 176,101 | CRITICAL |
| **Phase 2** | Object Properties | 4 | 473 | 495,000+ | CRITICAL |
| **Phase 3** | Classes | 31 | 38 | 26,000+ | HIGH |
| **TOTAL** | **Mixed** | **44** | **514+** | **~700,000** | **CRITICAL** |

## Unmapped Trait Reduction

| Current State | After Implementation | Reduction |
|---------------|---------------------|-----------|
| 902 unique unmapped traits | ~388 unmapped | 514 resolved (57%) |
| 5,051,076 unmapped observations | ~4,350,000 unmapped | ~700,000 mapped (14%) |

**Note:** Observation reduction appears lower than trait reduction because many unmapped traits have low observation counts, while the resolved traits have high frequencies.

---

## Implementation Roadmap

### Week 1-2: METPO Maintainer Review
1. Submit this proposal as GitHub issue to berkeleybop/metpo
2. Engage in discussion on term definitions and IDs
3. Revise based on feedback

### Week 3-4: ID Assignment
4. Receive assigned METPO IDs for approved terms
5. Update local METPO OWL file for testing
6. Create mapping tables for KG-Microbe transforms

### Week 5-6: Transform Implementation
7. Update metatraits and metatraits_gtdb transforms
8. Integrate Phase 1 data properties as node attributes
9. Integrate Phase 2 predicates for chemical relationships
10. Integrate Phase 3 classes for phenotype annotations

### Week 7-8: Testing and Validation
11. Run transforms on sample data
12. Verify edge/node counts match expectations
13. Quality check: spot-check mappings for accuracy
14. Run full transforms on complete dataset

### Week 9: Documentation and Release
15. Update KG-Microbe documentation
16. Generate merged graph statistics
17. Create visualization examples
18. Prepare manuscript/poster highlighting new coverage

---

## Technical Notes

### KGX TSV Format Compatibility

**Phase 1 Data Properties** (nodes.tsv):
```tsv
id	category	name	has_growth_temperature_optimum	has_pH_optimum	has_NaCl_concentration_optimum
NCBITaxon:562	biolink:OrganismTaxon	Escherichia coli	37.0	7.0	0.5
```

**Phase 2 Object Properties** (edges.tsv):
```tsv
subject	predicate	object	relation	primary_knowledge_source
NCBITaxon:562	METPO:2000021	CHEBI:17234	METPO:2000021	infores:bacdive
NCBITaxon:562	METPO:2000022	CHEBI:30089	METPO:2000022	infores:bacdive
```

**Phase 3 Classes** (edges.tsv):
```tsv
subject	predicate	object	relation	primary_knowledge_source
NCBITaxon:562	METPO:2000102	METPO:1007001	METPO:2000102	infores:bacdive
```

### Ontology Alignment

All proposed terms align with:
- **GO (Gene Ontology)** - Molecular functions and biological processes
- **ChEBI** - Chemical entities and metabolites
- **PATO** - Phenotypic qualities
- **SO (Sequence Ontology)** - Genomic features
- **UO (Units Ontology)** - Measurement units
- **RO (Relations Ontology)** - Relationships

---

## Supporting Materials

### Files Included with Proposal
1. `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md` (this document)
2. `mappings/metpo_predicate_based_proposal.tsv` (Phase 1 data properties)
3. `mappings/additional_metpo_mappings.tsv` (categorized unmapped traits)
4. `docs/METPO_PREDICATES.md` (existing METPO predicate reference)

### Data Sources
- BacDive API: https://bacdive.dsmz.de/
- GTDB Taxonomy: https://gtdb.ecogenomic.org/
- KG-Microbe GitHub: https://github.com/Knowledge-Graph-Hub/kg-microbe

---

## Contact Information

**Project:** KG-Microbe (Knowledge Graph Hub)  
**Repository:** https://github.com/Knowledge-Graph-Hub/kg-microbe  
**METPO Repository:** https://github.com/berkeleybop/metpo  

For questions or discussion about this proposal, please comment on the GitHub issue or contact the KG-Microbe team.

---

## Appendix A: Term ID Suggestions

**Phase 1 Data Properties:** METPO:has_* (use existing pattern)

**Phase 2 Object Properties:**
- METPO:2000021 - assimilates
- METPO:2000022 - uses as energy source
- METPO:2000023 - uses as nitrogen source (verify if 2000014 exists)
- METPO:2000024 - uses as electron donor

**Phase 3 Classes:**
- METPO:1007001-1007005 - Morphological (5 terms)
- METPO:1007010-1007013 - Genomic (4 terms)
- METPO:1007020-1007032 - Environmental (13 terms)
- METPO:1007040-1007042 - Biochemical (3 terms)
- METPO:1007050-1007052 - Growth (3 terms)

**Note:** ID ranges are suggestions. METPO maintainers will assign official IDs.

---

## Appendix B: Example Use Cases

### Use Case 1: Biotechnology Strain Selection
**Query:** "Find thermophilic bacteria that ferment glucose and produce ethanol"
```sparql
SELECT ?organism ?temp_opt ?product
WHERE {
  ?organism METPO:has_growth_temperature_optimum ?temp_opt .
  FILTER (?temp_opt > 60.0)
  ?organism METPO:2000011 CHEBI:17234 .  # ferments glucose
  ?organism METPO:2000202 CHEBI:16236 .  # produces ethanol
}
```

### Use Case 2: Environmental Niche Prediction
**Query:** "Find halophiles with known salinity ranges"
```sparql
SELECT ?organism ?nacl_min ?nacl_opt ?nacl_max
WHERE {
  ?organism METPO:has_NaCl_concentration_optimum ?nacl_opt .
  ?organism METPO:has_NaCl_concentration_minimum ?nacl_min .
  ?organism METPO:has_NaCl_concentration_maximum ?nacl_max .
  FILTER (?nacl_opt > 3.0)
}
```

### Use Case 3: Metabolic Pathway Reconstruction
**Query:** "Find organisms that use nitrate as electron acceptor and H2 as electron donor"
```sparql
SELECT ?organism
WHERE {
  ?organism METPO:2000008 CHEBI:17632 .  # uses nitrate as e- acceptor
  ?organism METPO:2000024 CHEBI:29356 .  # uses H2 as e- donor
}
```

---

**END OF PROPOSAL**
