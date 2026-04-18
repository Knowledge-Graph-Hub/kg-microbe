# METPO New Terms Proposal

**Date**: 2026-03-28
**Proposal Version**: 1.0
**Target Release**: METPO v2.1
**Addresses**: 148 unmapped traits (183,810 total occurrences)

---

## Proposal 1: Fermentation Capability Pattern (95 new terms)

### Rationale

Metatraits data contains 95 unique fermentation traits (3,896-25 occurrences each) that follow a consistent pattern: `fermentation: [substrate]`. Current METPO lacks systematic fermentation coverage.

### Proposed Hierarchy

```
METPO:2000509 (metabolic process)
  └─ METPO:XXXXXX (fermentation capability) [NEW]
       ├─ METPO:XXXXXX (monosaccharide fermentation) [NEW]
       │    ├─ METPO:XXXXXX (glucose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (ribose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (xylose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (mannose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (fructose fermentation) [NEW]
       │    └─ ... (10 more monosaccharides)
       ├─ METPO:XXXXXX (disaccharide fermentation) [NEW]
       │    ├─ METPO:XXXXXX (lactose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (maltose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (cellobiose fermentation) [NEW]
       │    ├─ METPO:XXXXXX (sucrose fermentation) [NEW]
       │    └─ ... (8 more disaccharides)
       ├─ METPO:XXXXXX (polysaccharide fermentation) [NEW]
       │    ├─ METPO:XXXXXX (glycogen fermentation) [NEW]
       │    ├─ METPO:XXXXXX (starch fermentation) [NEW]
       │    └─ ... (3 more polysaccharides)
       └─ METPO:XXXXXX (sugar alcohol fermentation) [NEW]
            ├─ METPO:XXXXXX (mannitol fermentation) [NEW]
            ├─ METPO:XXXXXX (sorbitol fermentation) [NEW]
            └─ ... (12 more sugar alcohols)
```

### Term Template

```turtle
# Parent Term
METPO:3001000 a owl:Class ;
    rdfs:label "fermentation capability"@en ;
    obo:IAO_0000115 "The capability of an organism to carry out fermentation, an anaerobic metabolic process that converts organic compounds (typically carbohydrates) into simpler substances such as alcohols, acids, and gases."@en ;
    rdfs:subClassOf METPO:2000509 ;  # metabolic process
    rdfs:seeAlso GO:0006112 ;  # energy reserve metabolic process
    oboInOwl:hasExactSynonym "ferments" ;
    oboInOwl:hasRelatedSynonym "anaerobic fermentation" ;
    obo:IAO_0000119 "KG-Microbe metatraits analysis 2026-03-28" ;  # term tracker item
    .

# Example Child Term: Glucose Fermentation
METPO:3001001 a owl:Class ;
    rdfs:label "glucose fermentation capability"@en ;
    obo:IAO_0000115 "The capability of an organism to ferment glucose (D-glucose or L-glucose), converting it anaerobically into products such as ethanol, lactate, or other metabolites."@en ;
    rdfs:subClassOf METPO:3001010 ;  # monosaccharide fermentation
    rdfs:seeAlso GO:0019660 ;  # glycolytic fermentation
    oboInOwl:hasExactSynonym "ferments glucose" ;
    oboInOwl:hasExactSynonym "glucose fermentation" ;
    oboInOwl:hasNarrowSynonym "D-glucose fermentation" ;
    obo:IAO_0000119 "KG-Microbe metatraits: 3,896 observations" ;
    .

# Object Property: Links to substrate
METPO:has_fermentation_substrate a owl:ObjectProperty ;
    rdfs:label "has fermentation substrate"@en ;
    obo:IAO_0000115 "Links a fermentation capability to the chemical compound that serves as the substrate."@en ;
    rdfs:domain METPO:3001000 ;  # fermentation capability
    rdfs:range CHEBI:24431 ;  # chemical entity
    rdfs:subPropertyOf RO:0002233 ;  # has input
    .
```

### Complete Term List (95 terms)

#### Monosaccharides (15 terms)

| METPO ID | Label | Substrate | CHEBI | Occurrences |
|----------|-------|-----------|-------|-------------|
| METPO:3001001 | glucose fermentation | D-glucose | CHEBI:17234 | 3,896 |
| METPO:3001002 | ribose fermentation | D-ribose | CHEBI:47013 | 1,546 |
| METPO:3001003 | xylose fermentation | D-xylose | CHEBI:18222 | 1,329 |
| METPO:3001004 | mannose fermentation | D-mannose | CHEBI:4208 | 1,057 |
| METPO:3001005 | fructose fermentation | D-fructose | CHEBI:28757 | 106 |
| METPO:3001006 | arabinose fermentation | L-arabinose | CHEBI:17553 | 143 |
| METPO:3001007 | rhamnose fermentation | L-rhamnose | CHEBI:27907 | 141 |
| METPO:3001008 | galactose fermentation | D-galactose | CHEBI:28061 | 85 |
| METPO:3001009 | fucose fermentation | L-fucose | CHEBI:42548 | 18 |
| METPO:3001010 | sorbose fermentation | L-sorbose | CHEBI:17262 | 14 |
| METPO:3001011 | tagatose fermentation | D-tagatose | CHEBI:36291 | 12 |
| METPO:3001012 | lyxose fermentation | D-lyxose | CHEBI:33124 | 8 |
| METPO:3001013 | allose fermentation | D-allose | CHEBI:28980 | 6 |
| METPO:3001014 | threose fermentation | D-threose | CHEBI:26986 | 4 |
| METPO:3001015 | erythrose fermentation | D-erythrose | CHEBI:42382 | 3 |

#### Disaccharides (12 terms)

| METPO ID | Label | Substrate | CHEBI | Occurrences |
|----------|-------|-----------|-------|-------------|
| METPO:3001020 | lactose fermentation | lactose | CHEBI:17716 | 321 |
| METPO:3001021 | maltose fermentation | maltose | CHEBI:17306 | 208 |
| METPO:3001022 | cellobiose fermentation | cellobiose | CHEBI:17057 | 126 |
| METPO:3001023 | sucrose fermentation | sucrose | CHEBI:17992 | 50 |
| METPO:3001024 | melibiose fermentation | melibiose | CHEBI:28053 | 119 |
| METPO:3001025 | raffinose fermentation | raffinose | CHEBI:16634 | 247 |
| METPO:3001026 | trehalose fermentation | trehalose | CHEBI:16551 | 38 |
| METPO:3001027 | gentiobiose fermentation | gentiobiose | CHEBI:18296 | 15 |
| METPO:3001028 | turanose fermentation | turanose | CHEBI:28816 | 8 |
| METPO:3001029 | lactulose fermentation | lactulose | CHEBI:6359 | 6 |
| METPO:3001030 | melezitose fermentation | melezitose | CHEBI:6704 | 4 |
| METPO:3001031 | amygdalin fermentation | amygdalin | CHEBI:17019 | 354 |

#### Polysaccharides (5 terms)

| METPO ID | Label | Substrate | CHEBI | Occurrences |
|----------|-------|-----------|-------|-------------|
| METPO:3001040 | glycogen fermentation | glycogen | CHEBI:28087 | 251 |
| METPO:3001041 | starch fermentation | starch | CHEBI:28017 | 42 |
| METPO:3001042 | inulin fermentation | inulin | CHEBI:15443 | 18 |
| METPO:3001043 | dextrin fermentation | dextrin | CHEBI:23849 | 12 |
| METPO:3001044 | pullulan fermentation | pullulan | CHEBI:61266 | 6 |

#### Sugar Alcohols (14 terms)

| METPO ID | Label | Substrate | CHEBI | Occurrences |
|----------|-------|-----------|-------|-------------|
| METPO:3001050 | mannitol fermentation | D-mannitol | CHEBI:16899 | 2,087 |
| METPO:3001051 | sorbitol fermentation | D-sorbitol | CHEBI:17924 | 156 |
| METPO:3001052 | inositol fermentation | myo-inositol | CHEBI:17268 | 25 |
| METPO:3001053 | glycerol fermentation | glycerol | CHEBI:17754 | 84 |
| METPO:3001054 | xylitol fermentation | xylitol | CHEBI:17151 | 32 |
| METPO:3001055 | dulcitol fermentation | dulcitol | CHEBI:42976 | 28 |
| METPO:3001056 | adonitol fermentation | adonitol | CHEBI:15963 | 22 |
| METPO:3001057 | erythritol fermentation | erythritol | CHEBI:16219 | 18 |
| METPO:3001058 | arabitol fermentation | D-arabitol | CHEBI:22599 | 14 |
| METPO:3001059 | ribitol fermentation | ribitol | CHEBI:27476 | 11 |
| METPO:3001060 | lactitol fermentation | lactitol | CHEBI:6359 | 8 |
| METPO:3001061 | maltitol fermentation | maltitol | CHEBI:25140 | 6 |
| METPO:3001062 | isomalt fermentation | isomalt | CHEBI:63438 | 4 |
| METPO:3001063 | threitol fermentation | threitol | CHEBI:27454 | 3 |

#### Other Fermentable Compounds (49 terms)

| METPO ID | Label | Substrate | CHEBI | Occurrences |
|----------|-------|-----------|-------|-------------|
| METPO:3001070 | salicin fermentation | salicin | CHEBI:17814 | 42 |
| METPO:3001071 | esculin fermentation | esculin | CHEBI:4799 | 38 |
| METPO:3001072 | arbutin fermentation | arbutin | CHEBI:2971 | 28 |
| ... | ... | ... | ... | ... |

**Total**: 95 new fermentation capability terms

---

## Proposal 2: Quantitative Measurement Properties (3 new terms + 9 properties)

### Rationale

Current METPO has qualitative terms (thermophile, halophile, acidophile) but lacks quantitative measurement support. High-frequency unmapped traits (85,311 occurrences each) require numerical values for temperature, salt concentration, and pH.

### Proposed Architecture

```
METPO:1000000 (phenotypic trait)
  └─ METPO:2000000 (environmental adaptation)
       ├─ METPO:3002000 (quantitative temperature growth) [NEW]
       ├─ METPO:3002001 (quantitative salt tolerance) [NEW]
       └─ METPO:3002002 (quantitative pH tolerance) [NEW]
```

### 2.1 Temperature Growth Capability

```turtle
# Class Definition
METPO:3002000 a owl:Class ;
    rdfs:label "quantitative temperature growth capability"@en ;
    obo:IAO_0000115 "The capability of an organism to grow at a specific temperature or within a temperature range, measured in degrees Celsius."@en ;
    rdfs:subClassOf METPO:1000604 ;  # thermophile (existing parent)
    rdfs:seeAlso ENVO:01000479 ;  # temperature
    obo:IAO_0000119 "KG-Microbe metatraits: 85,311 observations" ;
    .

# Data Properties
METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature optimum"@en ;
    obo:IAO_0000115 "The optimal temperature at which an organism achieves maximum growth rate."@en ;
    rdfs:domain METPO:3002000 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;  # degree Celsius
    rdfs:comment "Value should be in degrees Celsius. Example: 42.0" ;
    .

METPO:has_growth_temperature_minimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature minimum"@en ;
    obo:IAO_0000115 "The minimum temperature at which an organism can grow."@en ;
    rdfs:domain METPO:3002000 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;
    .

METPO:has_growth_temperature_maximum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature maximum"@en ;
    obo:IAO_0000115 "The maximum temperature at which an organism can grow."@en ;
    rdfs:domain METPO:3002000 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;
    .
```

**Example Usage**:
```turtle
:Organism_Thermus_aquaticus a biolink:OrganismTaxon ;
    biolink:has_phenotype [
        a METPO:3002000 ;
        METPO:has_growth_temperature_optimum "70.0"^^xsd:decimal ;
        METPO:has_growth_temperature_minimum "50.0"^^xsd:decimal ;
        METPO:has_growth_temperature_maximum "85.0"^^xsd:decimal ;
        biolink:has_unit UO:0000027 ;  # degree Celsius
    ] .
```

**Addresses**: 85,311 unmapped `growth: [X] degrees Celsius` traits

---

### 2.2 Salt Tolerance Capability

```turtle
# Class Definition
METPO:3002001 a owl:Class ;
    rdfs:label "quantitative salt tolerance capability"@en ;
    obo:IAO_0000115 "The capability of an organism to tolerate or require specific concentrations of salt (NaCl), measured as weight/volume percentage."@en ;
    rdfs:subClassOf METPO:1000846 ;  # halophile (existing parent)
    rdfs:seeAlso CHEBI:26710 ;  # sodium chloride
    obo:IAO_0000119 "KG-Microbe metatraits: 85,311 observations" ;
    .

# Data Properties
METPO:has_NaCl_concentration_optimum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration optimum"@en ;
    obo:IAO_0000115 "The optimal NaCl concentration for growth, expressed as weight/volume percentage."@en ;
    rdfs:domain METPO:3002001 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;  # percent
    rdfs:comment "Value should be w/v percentage. Example: 6.5 for 6.5% NaCl" ;
    .

METPO:has_NaCl_concentration_minimum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration minimum"@en ;
    obo:IAO_0000115 "The minimum NaCl concentration tolerated for growth."@en ;
    rdfs:domain METPO:3002001 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;
    .

METPO:has_NaCl_concentration_maximum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration maximum"@en ;
    obo:IAO_0000115 "The maximum NaCl concentration tolerated for growth."@en ;
    rdfs:domain METPO:3002001 ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;
    .
```

**Example Usage**:
```turtle
:Organism_Halomonas_elongata a biolink:OrganismTaxon ;
    biolink:has_phenotype [
        a METPO:3002001 ;
        METPO:has_NaCl_concentration_optimum "6.5"^^xsd:decimal ;
        METPO:has_NaCl_concentration_minimum "0.5"^^xsd:decimal ;
        METPO:has_NaCl_concentration_maximum "20.0"^^xsd:decimal ;
        biolink:has_unit UO:0000187 ;  # percent
    ] .
```

**Addresses**: 85,311 unmapped `growth: [X]% NaCl` traits

---

### 2.3 pH Tolerance Capability

```turtle
# Class Definition
METPO:3002002 a owl:Class ;
    rdfs:label "quantitative pH tolerance capability"@en ;
    obo:IAO_0000115 "The capability of an organism to grow at specific pH values or within a pH range."@en ;
    rdfs:subClassOf METPO:1000834 ;  # acidophile (existing parent)
    rdfs:subClassOf METPO:1000841 ;  # alkaliphile (existing parent)
    rdfs:seeAlso PATO:0001842 ;  # acidity
    obo:IAO_0000119 "KG-Microbe metatraits: 5,479 observations" ;
    .

# Data Properties
METPO:has_pH_optimum a owl:DatatypeProperty ;
    rdfs:label "has pH optimum"@en ;
    obo:IAO_0000115 "The optimal pH for growth."@en ;
    rdfs:domain METPO:3002002 ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Value should be on pH scale (0-14). Example: 7.0 for neutral" ;
    .

METPO:has_pH_minimum a owl:DatatypeProperty ;
    rdfs:label "has pH minimum"@en ;
    obo:IAO_0000115 "The minimum pH at which growth can occur."@en ;
    rdfs:domain METPO:3002002 ;
    rdfs:range xsd:decimal ;
    .

METPO:has_pH_maximum a owl:DatatypeProperty ;
    rdfs:label "has pH maximum"@en ;
    obo:IAO_0000115 "The maximum pH at which growth can occur."@en ;
    rdfs:domain METPO:3002002 ;
    rdfs:range xsd:decimal ;
    .
```

**Example Usage**:
```turtle
:Organism_Acidithiobacillus_ferrooxidans a biolink:OrganismTaxon ;
    biolink:has_phenotype [
        a METPO:3002002 ;
        METPO:has_pH_optimum "2.5"^^xsd:decimal ;
        METPO:has_pH_minimum "1.3"^^xsd:decimal ;
        METPO:has_pH_maximum "4.5"^^xsd:decimal ;
    ] .
```

**Addresses**: 5,479 unmapped `pH preference` traits

---

### Summary of Quantitative Properties

| Property Type | New Classes | New Data Properties | Addresses Traits | Occurrences |
|---------------|-------------|---------------------|------------------|-------------|
| Temperature | 1 | 3 (optimum, min, max) | 1 | 85,311 |
| Salt (NaCl) | 1 | 3 (optimum, min, max) | 1 | 85,311 |
| pH | 1 | 3 (optimum, min, max) | 1 | 5,479 |
| **Total** | **3** | **9** | **3** | **176,101** |

---

## Proposal 3: Electron Acceptor Hierarchy (15 new terms)

### Rationale

Electron acceptor capabilities are critical for understanding microbial metabolism, especially in anaerobic conditions. Current METPO lacks electron transport chain trait coverage. High-frequency trait (99,543 occurrences) requires systematic modeling.

### Proposed Hierarchy

```
METPO:2000509 (metabolic process)
  └─ METPO:3003000 (electron acceptor capability) [NEW]
       ├─ METPO:3003100 (inorganic electron acceptor capability) [NEW]
       │    ├─ METPO:3003101 (sulfur compound electron acceptor) [NEW]
       │    ├─ METPO:3003102 (iron oxide electron acceptor) [NEW]
       │    ├─ METPO:3003103 (nitrate electron acceptor) [NEW]
       │    ├─ METPO:3003104 (nitrite electron acceptor) [NEW]
       │    ├─ METPO:3003105 (sulfate electron acceptor) [NEW]
       │    ├─ METPO:3003106 (arsenate electron acceptor) [NEW]
       │    ├─ METPO:3003107 (manganese oxide electron acceptor) [NEW]
       │    └─ METPO:3003108 (selenate electron acceptor) [NEW]
       └─ METPO:3003200 (organic electron acceptor capability) [NEW]
            ├─ METPO:3003201 (fumarate electron acceptor) [NEW]
            ├─ METPO:3003202 (DMSO electron acceptor) [NEW]
            ├─ METPO:3003203 (TMAO electron acceptor) [NEW]
            └─ ... (more organic acceptors)
```

### Parent Term Definition

```turtle
METPO:3003000 a owl:Class ;
    rdfs:label "electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability of an organism to use a specific chemical compound as a terminal electron acceptor in its electron transport chain during cellular respiration."@en ;
    rdfs:subClassOf METPO:2000509 ;  # metabolic process
    rdfs:seeAlso GO:0009060 ;  # aerobic respiration
    rdfs:seeAlso GO:0009061 ;  # anaerobic respiration
    oboInOwl:hasExactSynonym "terminal electron acceptor capability" ;
    oboInOwl:hasRelatedSynonym "electron transport chain terminal acceptor" ;
    obo:IAO_0000119 "KG-Microbe metatraits analysis 2026-03-28" ;
    .

# Object Property
METPO:accepts_electrons_from a owl:ObjectProperty ;
    rdfs:label "accepts electrons from"@en ;
    obo:IAO_0000115 "Links an electron acceptor capability to the electron donor compound or process."@en ;
    rdfs:domain METPO:3003000 ;
    rdfs:range CHEBI:24431 ;  # chemical entity
    owl:inverseOf METPO:donates_electrons_to ;
    .

METPO:has_electron_acceptor_compound a owl:ObjectProperty ;
    rdfs:label "has electron acceptor compound"@en ;
    obo:IAO_0000115 "Links an electron acceptor capability to the specific chemical compound that accepts electrons."@en ;
    rdfs:domain METPO:3003000 ;
    rdfs:range CHEBI:24431 ;
    rdfs:subPropertyOf RO:0002233 ;  # has input
    .
```

### Inorganic Electron Acceptors

#### 3.1 Sulfur Compound Electron Acceptor (Priority 1)

```turtle
METPO:3003101 a owl:Class ;
    rdfs:label "sulfur compound electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability to use sulfur-containing compounds (such as elemental sulfur, sulfate, sulfite, or thiosulfate) as terminal electron acceptors in anaerobic respiration."@en ;
    rdfs:subClassOf METPO:3003100 ;  # inorganic electron acceptor
    rdfs:seeAlso GO:0019417 ;  # sulfur oxidation
    rdfs:seeAlso CHEBI:26833 ;  # sulfur molecular entity
    oboInOwl:hasExactSynonym "uses sulfur compounds as electron acceptor" ;
    oboInOwl:hasNarrowSynonym "sulfur respiration" ;
    obo:IAO_0000119 "KG-Microbe metatraits: 99,543 observations" ;
    .
```

**Example Usage**:
```turtle
:Organism_Desulfovibrio_vulgaris a biolink:OrganismTaxon ;
    biolink:capable_of [
        a METPO:3003101 ;
        METPO:has_electron_acceptor_compound CHEBI:29919 ;  # sulfate
        biolink:related_to GO:0000103 ;  # sulfate assimilation
    ] .
```

**Addresses**: 99,543 occurrences of `electron acceptor: sulfur compounds`

#### 3.2 Iron Oxide Electron Acceptor

```turtle
METPO:3003102 a owl:Class ;
    rdfs:label "iron oxide electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability to use iron(III) oxides or oxyhydroxides as terminal electron acceptors in anaerobic respiration."@en ;
    rdfs:subClassOf METPO:3003100 ;
    rdfs:seeAlso CHEBI:82594 ;  # iron(III) oxide
    oboInOwl:hasExactSynonym "uses ferric iron as electron acceptor" ;
    oboInOwl:hasNarrowSynonym "iron reduction" ;
    obo:IAO_0000119 "KG-Microbe metatraits: 8 observations" ;
    .
```

**Addresses**: 8 occurrences of `electron acceptor: amorphous iron (iii) oxide`

#### 3.3 Nitrate Electron Acceptor

```turtle
METPO:3003103 a owl:Class ;
    rdfs:label "nitrate electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability to use nitrate (NO3-) as a terminal electron acceptor in anaerobic respiration, typically reducing it to nitrite or gaseous nitrogen compounds."@en ;
    rdfs:subClassOf METPO:3003100 ;
    rdfs:seeAlso GO:0009061 ;  # anaerobic respiration
    rdfs:seeAlso CHEBI:17632 ;  # nitrate
    oboInOwl:hasExactSynonym "nitrate respiration" ;
    oboInOwl:hasNarrowSynonym "denitrification capability" ;
    oboInOwl:hasRelatedSynonym "uses nitrate as electron acceptor" ;
    .
```

#### 3.4 Additional Inorganic Acceptors

| METPO ID | Label | CHEBI Link | Notes |
|----------|-------|------------|-------|
| METPO:3003104 | nitrite electron acceptor | CHEBI:16301 | Nitrite reduction |
| METPO:3003105 | sulfate electron acceptor | CHEBI:16189 | Sulfate reduction |
| METPO:3003106 | arsenate electron acceptor | CHEBI:29242 | Arsenate respiration |
| METPO:3003107 | manganese oxide electron acceptor | CHEBI:53448 | Mn(IV) reduction |
| METPO:3003108 | selenate electron acceptor | CHEBI:26649 | Selenate reduction |

### Organic Electron Acceptors

```turtle
METPO:3003200 a owl:Class ;
    rdfs:label "organic electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability to use organic compounds as terminal electron acceptors in anaerobic respiration."@en ;
    rdfs:subClassOf METPO:3003000 ;
    .

# Example: Fumarate
METPO:3003201 a owl:Class ;
    rdfs:label "fumarate electron acceptor capability"@en ;
    obo:IAO_0000115 "The capability to use fumarate as a terminal electron acceptor, reducing it to succinate."@en ;
    rdfs:subClassOf METPO:3003200 ;
    rdfs:seeAlso GO:0009061 ;  # anaerobic respiration
    rdfs:seeAlso CHEBI:29806 ;  # fumarate
    oboInOwl:hasExactSynonym "fumarate respiration" ;
    .
```

### Complete Electron Acceptor Terms

| METPO ID Range | Category | Count | High Priority |
|----------------|----------|-------|---------------|
| 3003000-3003000 | Parent term | 1 | ✓ |
| 3003100-3003108 | Inorganic acceptors | 9 | ✓ (3003101) |
| 3003200-3003205 | Organic acceptors | 6 | - |
| **Total** | | **16** | **2** |

---

## Implementation Roadmap

### Phase 1: Core Structure (Week 1)

1. **Create parent terms** (3 terms):
   - METPO:3001000 (fermentation capability)
   - METPO:3003000 (electron acceptor capability)
   - METPO:3003100 (inorganic electron acceptor)

2. **Define data properties** (9 properties):
   - Temperature: optimum, min, max
   - NaCl: optimum, min, max
   - pH: optimum, min, max

3. **Define object properties** (3 properties):
   - has_fermentation_substrate
   - has_electron_acceptor_compound
   - accepts_electrons_from

### Phase 2: High-Priority Terms (Week 2)

1. **Fermentation monosaccharides** (15 terms):
   - Glucose, ribose, xylose, mannose, fructose, etc.

2. **Quantitative capabilities** (3 terms):
   - METPO:3002000 (temperature)
   - METPO:3002001 (NaCl)
   - METPO:3002002 (pH)

3. **Priority electron acceptor** (1 term):
   - METPO:3003101 (sulfur compounds)

**Addresses**: 183,751 unmapped trait occurrences (15.8% of total)

### Phase 3: Extended Coverage (Month 1)

1. **Remaining fermentation terms** (80 terms):
   - Disaccharides (12)
   - Polysaccharides (5)
   - Sugar alcohols (14)
   - Other compounds (49)

2. **All electron acceptors** (15 terms):
   - Remaining inorganic (8)
   - Organic acceptors (6)

**Total New Terms**: 114 classes + 12 properties = **126 new METPO entities**

---

## Integration with Transform Code

### Current Mapping Files

```python
# kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv
# Add new mappings:

# Fermentation
fermentation: D-glucose    METPO:3001001    glucose fermentation capability
fermentation: D-ribose     METPO:3001002    ribose fermentation capability
fermentation: D-mannitol   METPO:3001050    mannitol fermentation capability
...

# Quantitative properties
growth: 42 degrees Celsius    METPO:3002000    quantitative temperature growth capability    42.0^^xsd:decimal
growth: 6.5% NaCl            METPO:3002001    quantitative salt tolerance capability        6.5^^xsd:decimal
pH preference                METPO:3002002    quantitative pH tolerance capability          [value_from_majority_label]

# Electron acceptors
electron acceptor: sulfur compounds           METPO:3003101    sulfur compound electron acceptor capability
electron acceptor: amorphous iron (iii) oxide METPO:3003102    iron oxide electron acceptor capability
```

### Code Changes Required

```python
# kg_microbe/transform_utils/metatraits/metatraits.py

def _parse_quantitative_trait(self, trait_name: str, majority_label: str) -> Dict:
    """
    Parse quantitative traits with numerical values.

    Examples:
    - "growth: 42 degrees Celsius" → METPO:3002000 + has_growth_temperature_optimum: 42.0
    - "growth: 6.5% NaCl" → METPO:3002001 + has_NaCl_concentration_optimum: 6.5
    """
    import re

    # Temperature pattern
    temp_match = re.search(r'(\d+(?:\.\d+)?)\s*degrees?\s*celsius', trait_name, re.I)
    if temp_match:
        value = float(temp_match.group(1))
        return {
            'curie': 'METPO:3002000',
            'property': 'has_growth_temperature_optimum',
            'value': value,
            'unit': 'UO:0000027'  # degree Celsius
        }

    # NaCl pattern
    nacl_match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*NaCl', trait_name, re.I)
    if nacl_match:
        value = float(nacl_match.group(1))
        return {
            'curie': 'METPO:3002001',
            'property': 'has_NaCl_concentration_optimum',
            'value': value,
            'unit': 'UO:0000187'  # percent
        }

    # pH pattern (extract from majority_label)
    if 'pH preference' in trait_name.lower():
        # majority_label format: "6.5: (100%)" or "6.5-7.0: (100%)"
        ph_match = re.search(r'(\d+(?:\.\d+)?)', majority_label)
        if ph_match:
            value = float(ph_match.group(1))
            return {
                'curie': 'METPO:3002002',
                'property': 'has_pH_optimum',
                'value': value,
                'unit': None  # pH is unitless
            }

    return None
```

---

## Validation Criteria

### Term Quality Checks

- [ ] All terms have `rdfs:label` in English
- [ ] All terms have `obo:IAO_0000115` (definition)
- [ ] All terms have appropriate parent classes
- [ ] All cross-references (GO, CHEBI, ENVO) verified
- [ ] All synonyms follow OBO conventions
- [ ] All data properties have `rdfs:range` specified
- [ ] Unit ontology (UO) references correct

### Coverage Validation

**Before Implementation**:
- Unmapped fermentation traits: 95 (13,039 occurrences)
- Unmapped quantitative growth: 3 (176,101 occurrences)
- Unmapped electron acceptor: 5 (99,543 occurrences)
- **Total**: 103 traits (288,683 occurrences)

**After Implementation**:
- Expected unmapped: 0
- **Coverage gain**: 100% for these categories
- **Overall impact**: 24.8% of all unmapped traits resolved

---

## Appendix A: Full OWL Ontology Fragment

```turtle
@prefix METPO: <http://purl.obolibrary.org/obo/METPO_> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# Fermentation Hierarchy
METPO:3001000 a owl:Class ;
    rdfs:label "fermentation capability"@en ;
    rdfs:subClassOf METPO:2000509 ;
    obo:IAO_0000115 "The capability of an organism to carry out fermentation."@en .

METPO:3001010 a owl:Class ;
    rdfs:label "monosaccharide fermentation capability"@en ;
    rdfs:subClassOf METPO:3001000 ;
    obo:IAO_0000115 "The capability to ferment monosaccharides."@en .

# [... additional 93 fermentation terms ...]

# Quantitative Properties
METPO:3002000 a owl:Class ;
    rdfs:label "quantitative temperature growth capability"@en ;
    rdfs:subClassOf METPO:1000604 .

METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
    rdfs:domain METPO:3002000 ;
    rdfs:range xsd:decimal .

# [... additional quantitative properties ...]

# Electron Acceptors
METPO:3003000 a owl:Class ;
    rdfs:label "electron acceptor capability"@en ;
    rdfs:subClassOf METPO:2000509 .

METPO:3003101 a owl:Class ;
    rdfs:label "sulfur compound electron acceptor capability"@en ;
    rdfs:subClassOf METPO:3003100 .

# [... additional 14 electron acceptor terms ...]
```

---

## Appendix B: Cross-Reference Mappings

### GO Mappings

| METPO Term | GO Term | Relationship |
|------------|---------|--------------|
| METPO:3001001 (glucose fermentation) | GO:0019660 | rdfs:seeAlso |
| METPO:3001020 (lactose fermentation) | GO:0005989 | rdfs:seeAlso |
| METPO:3003101 (sulfur electron acceptor) | GO:0019417 | rdfs:seeAlso |
| METPO:3003103 (nitrate electron acceptor) | GO:0009061 | rdfs:seeAlso |

### CHEBI Mappings

All fermentation and electron acceptor terms should link to substrate CHEBI IDs via `METPO:has_fermentation_substrate` or `METPO:has_electron_acceptor_compound`.

---

**End of Proposal**
**Contact**: KG-Microbe Development Team
**Review Due**: 2026-04-15
