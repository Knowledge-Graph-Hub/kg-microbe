# Unmapped Traits Ontology Analysis

**Date**: 2026-03-28
**Total Unmapped Traits**: 551 unique traits (1,164,765 occurrences)
**Sources**: metatraits (470,352) + metatraits_gtdb (694,415)

## Executive Summary

Analysis reveals **8 major categories** of unmapped traits that could be modeled using METPO, GO, ENVO, CHEBI, and other ontologies. High-frequency traits (60K-99K occurrences each) represent systematic gaps requiring immediate attention.

---

## Priority 1: High-Impact Metabolic Traits (99,543 occurrences each)

### 1.1 Metabolic Degradation Pathways

**Current Gap**: 8 degradation traits unmapped despite clear biological processes

| Trait | Occurrences | Proposed Ontology Term | Parent Class |
|-------|-------------|------------------------|--------------|
| `degradation: hydrocarbon` | 99,543 | GO:0042537 (hydrocarbon catabolic process) | GO:0044712 (catabolic process) |
| `degradation: aromatic hydrocarbon` | 99,543 | GO:0018894 (aromatic hydrocarbon catabolic process) | GO:0042537 |
| `degradation: aromatic compound` | 99,543 | GO:0019439 (aromatic compound catabolic process) | GO:0044712 |
| `degradation: plastic` | 99,543 | **NEW METPO TERM** | METPO:2000509 (metabolic process) |
| `oxidation in darkness: sulfur compounds` | 99,543 | GO:0019417 (sulfur oxidation) | GO:0044281 (oxidation-reduction process) |
| `reduction: arsenate detoxification` | 99,543 | GO:0046685 (arsenate reductase activity) + GO:0050896 (detoxification) | Combined term |

**Recommendation**:
- Map to existing GO terms where available
- Create new METPO term for plastic degradation: `METPO:XXXXXX plastic degradation capability`
- Use compound predicates for detoxification processes

### 1.2 Electron Transfer Processes

| Trait | Occurrences | Proposed Ontology Term | Notes |
|-------|-------------|------------------------|-------|
| `electron acceptor: sulfur compounds` | 99,543 | **NEW METPO TERM** | Create hierarchical electron acceptor terms |
| `electron acceptor: amorphous iron (iii) oxide` | 8 | CHEBI:82594 (iron(III) oxide) | Link to chemical via biolink:capable_of |

**Recommendation**:
- Create METPO electron acceptor hierarchy:
  - `METPO:XXXXXX electron acceptor capability`
    - `METPO:XXXXXX sulfur compound electron acceptor`
    - `METPO:XXXXXX iron oxide electron acceptor`
- Link to CHEBI terms for specific chemicals

### 1.3 Metabolite Production

| Trait | Occurrences | Proposed Ontology Term | Parent Class |
|-------|-------------|------------------------|--------------|
| `produces: methane from formate` | 99,543 | GO:0015948 (methanogenesis) + CHEBI:15741 (formate) | Compound relationship |
| `builds gas from: sodium thiosulfate` | 188 | GO:0015976 (carbon utilization) | General gas production |
| `builds gas from: nitrate` | 115 | GO:0042128 (nitrate assimilation) | Nitrogen metabolism |

**Recommendation**:
- Use compound edges: `organism --capable_of--> GO:0015948 --has_input--> CHEBI:15741`
- Create METPO terms for complex metabolic transformations

---

## Priority 2: Growth Condition Traits (85,311 occurrences each)

### 2.1 Salt Tolerance

| Trait | Occurrences | Proposed Ontology Term | Notes |
|-------|-------------|------------------------|-------|
| `growth: 6.5% NaCl` | 85,311 | METPO:1000846 (halophile) + data property | Use PATO for concentration |

**Recommendation**:
- Create METPO salt tolerance terms with PATO qualifiers:
  - `METPO:XXXXXX halotolerant growth`
    - `has_measurement` → 6.5% NaCl (PATO:0000033 concentration)
- Use UO:0000187 (percent) for units

### 2.2 Temperature Tolerance

| Trait | Occurrences | Proposed Ontology Term | Notes |
|-------|-------------|------------------------|-------|
| `growth: 42 degrees Celsius` | 85,311 | METPO:1000604 (thermophile) + data property | Use UO for temperature |

**Recommendation**:
- Create temperature growth range terms:
  - `METPO:XXXXXX growth at temperature`
    - `has_measurement` → 42°C (UO:0000027 degree Celsius)

### 2.3 Biochemical Hydrolysis

| Trait | Occurrences | Proposed Ontology Term | Notes |
|-------|-------------|------------------------|-------|
| `hydrolysis: 4-nitrophenyl beta-D-galactopyranoside` | 85,321 | GO:0004565 (beta-galactosidase activity) | Enzyme activity |

**Recommendation**:
- Map to GO enzyme activity terms
- Link substrate via `has_substrate` → CHEBI:XXXXX

---

## Priority 3: Fermentation Capabilities (95 traits, 3,896-2,087 occurrences)

### 3.1 Sugar Fermentation

**Pattern**: `fermentation: [sugar_name]`

| Trait | Occurrences | Proposed Ontology Term | Chemical |
|-------|-------------|------------------------|----------|
| `fermentation: D-glucose` | 3,896 | GO:0019660 (glycolytic fermentation) | CHEBI:17234 (D-glucose) |
| `fermentation: D-mannitol` | 2,087 | GO:0019400 (mannitol metabolic process) | CHEBI:16899 (D-mannitol) |
| `fermentation: D-ribose` | 1,546 | GO:0046390 (ribose phosphate metabolic process) | CHEBI:47013 (D-ribose) |
| `fermentation: D-xylose` | 1,329 | GO:0042732 (D-xylose metabolic process) | CHEBI:18222 (D-xylose) |

**Recommendation**:
- Create generalized METPO fermentation pattern:
  - `METPO:XXXXXX fermentation capability`
    - Subclasses: `METPO:XXXXXX [sugar] fermentation`
- Link to GO metabolic processes via `rdfs:seeAlso`
- Link to CHEBI substrates via `has_substrate`

### 3.2 Complex Carbohydrate Fermentation

| Trait | Occurrences | Proposed | Chemical |
|-------|-------------|----------|----------|
| `fermentation: glycogen` | 251 | GO:0005977 (glycogen metabolic process) | CHEBI:28087 (glycogen) |
| `fermentation: cellobiose` | 126 | GO:0019583 (cellobiose catabolic process) | CHEBI:17057 (cellobiose) |

---

## Priority 4: Enzyme Activities (44 traits, 843-304 occurrences)

### 4.1 Diagnostic Enzyme Tests

| Trait | Occurrences | Proposed Ontology Term | EC Number |
|-------|-------------|------------------------|-----------|
| `enzyme activity: beta-Galactosidase 6-phosphate` | 843 | GO:0004565 (beta-galactosidase activity) | EC 3.2.1.23 |
| `enzyme activity: esterase (C 4)` | 451 | GO:0016788 (hydrolase activity, ester bonds) | EC 3.1.1.- |
| `enzyme activity: alpha-maltosidase` | 304 | GO:0032450 (maltose alpha-glucosidase activity) | EC 3.2.1.20 |

**Recommendation**:
- Map to GO molecular function terms
- Add EC numbers as xrefs
- Create METPO "has_enzyme_activity" relation

### 4.2 Arylamidase Activities

Pattern: `enzyme activity: [amino acid] arylamidase`

| Trait | Occurrences | GO Term | EC Number |
|-------|-------------|---------|-----------|
| `glycyl tryptophan arylamidase` | 347 | GO:0070006 (metalloaminopeptidase activity) | EC 3.4.11.- |
| `L-arginine arylamidase` | 94 | GO:0004177 (aminopeptidase activity) | EC 3.4.11.6 |
| `valine arylamidase` | 41 | GO:0004177 (aminopeptidase activity) | EC 3.4.11.- |

---

## Priority 5: Carbon Source Utilization (32 traits)

### 5.1 Organic Acid Utilization

| Trait | Occurrences | Proposed Ontology Term | Chemical |
|-------|-------------|------------------------|----------|
| `carbon source: bromosuccinate` | 79 | GO:0015976 (carbon utilization) | CHEBI:XXXXX |
| `carbon source: beta-hydroxybutyrate` | 69 | GO:0019752 (carboxylic acid metabolic process) | CHEBI:20067 |
| `carbon source: galacturonate` | 61 | GO:0046392 (galacturonate catabolic process) | CHEBI:33198 |

**Recommendation**:
- Create METPO carbon source pattern:
  - `METPO:XXXXXX carbon source utilization`
    - Link to specific CHEBI compounds
    - Link to GO metabolic processes

---

## Priority 6: Cell Properties (1 trait, 85,311 occurrences)

### 6.1 Pigmentation

| Trait | Occurrences | Proposed Ontology Term | Notes |
|-------|-------------|------------------------|-------|
| `cell color: yellow pigment` | 85,311 | METPO:1000698 (pigmentation) + PATO:0000324 (yellow) | Use PATO for color |

**Recommendation**:
- Extend METPO pigmentation terms:
  - `METPO:XXXXXX pigmented cell`
    - `has_quality` → PATO:0000324 (yellow)
- Consider linking to specific pigment compounds (carotenoids, etc.)

---

## Priority 7: pH Preference (5,479 occurrences)

### 7.1 Growth pH

| Trait | Occurrences | Current METPO | Recommendation |
|-------|-------------|---------------|----------------|
| `pH preference` | 5,479 | METPO:1000834 (acidophile), METPO:1000841 (alkaliphile) | Add pH range data properties |

**Recommendation**:
- Enhance existing METPO pH terms with quantitative measurements:
  - `has_pH_optimum` → xsd:decimal
  - `has_pH_range` → xsd:string ("4.5-6.5")
- Use PATO:0001842 (acidity)

---

## Priority 8: Other Assimilation Patterns (123 traits)

### 8.1 Metabolite Assimilation

Pattern: `assimilation: [compound]`

| Trait | Occurrences | Proposed Approach |
|-------|-------------|-------------------|
| `assimilation: bromosuccinate` | 50 | GO:0015976 (carbon utilization) + CHEBI |
| `assimilation: beta-hydroxybutyrate` | 42 | GO:0006635 (fatty acid beta-oxidation) + CHEBI |

**Recommendation**:
- Treat similar to carbon source utilization
- Create `METPO:XXXXXX assimilation capability` parent term

---

## Implementation Recommendations

### Phase 1: Map to Existing Ontologies (Quick Wins)

**GO Terms** (can map immediately):
- 26 degradation/oxidation/reduction traits → GO metabolic processes
- 44 enzyme activity traits → GO molecular functions
- 95 fermentation traits → GO fermentation/metabolic processes

**Estimated Coverage**: ~40% of unmapped traits resolved

### Phase 2: Create METPO Extensions (Medium-term)

**New METPO Terms Needed**:
1. **Electron acceptor hierarchy** (5 terms)
   - Parent: `METPO:XXXXXX electron acceptor capability`
   - Children for specific acceptor types

2. **Degradation capabilities** (8 terms)
   - `METPO:XXXXXX plastic degradation capability`
   - `METPO:XXXXXX hydrocarbon degradation capability`

3. **Fermentation pattern** (95+ terms)
   - Parent: `METPO:XXXXXX fermentation capability`
   - Specific sugar fermentation subclasses

4. **Carbon source pattern** (32 terms)
   - Parent: `METPO:XXXXXX carbon source utilization`
   - Specific compound utilization subclasses

5. **Quantitative growth parameters** (3 terms)
   - `METPO:XXXXXX growth at temperature` (with UO)
   - `METPO:XXXXXX growth at salt concentration` (with PATO)
   - `METPO:XXXXXX growth at pH` (with PATO)

**Estimated Coverage**: +50% resolved (90% total)

### Phase 3: Hybrid Modeling (Long-term)

**Compound Relationships**:
- Organism → `capable_of` → GO process → `has_substrate` → CHEBI compound
- Organism → `has_phenotype` → METPO trait → `has_measurement` → PATO quality

**Example**:
```turtle
:Organism_123 biolink:capable_of GO:0019660 .
GO:0019660 rdfs:label "glycolytic fermentation" .
GO:0019660 biolink:has_substrate CHEBI:17234 .
CHEBI:17234 rdfs:label "D-glucose" .
```

**Estimated Coverage**: Remaining 10% edge cases

---

## Prioritization Matrix

| Category | Unique Traits | Total Occurrences | Ontology Complexity | Priority |
|----------|---------------|-------------------|---------------------|----------|
| Metabolic Degradation | 8 | 99,543 each | Medium (GO exists) | **P1** |
| Electron Processes | 5 | 99,543 each | High (new METPO) | **P1** |
| Growth Conditions | 49 | 85,311 each | Medium (METPO + PATO) | **P1** |
| Fermentation | 95 | 3,896-1,057 | Low (GO exists) | **P2** |
| Enzyme Activity | 44 | 843-304 | Low (GO + EC) | **P2** |
| Carbon Source | 32 | 79-61 | Medium (GO + CHEBI) | **P3** |
| Cell Properties | 1 | 85,311 | Low (METPO + PATO) | **P3** |
| pH Preference | 1 | 5,479 | Low (enhance METPO) | **P3** |

---

## Next Steps

1. **Immediate** (Week 1):
   - Map 165 traits to existing GO/ENVO/CHEBI terms
   - Test hybrid modeling approach with top 10 traits
   - Submit GO term requests for missing processes

2. **Short-term** (Month 1):
   - Create 50-100 new METPO terms for fermentation pattern
   - Add quantitative data properties to METPO
   - Implement compound relationship modeling

3. **Medium-term** (Quarter 1):
   - Complete METPO extension with all 200+ new terms
   - Validate ontology mappings with domain experts
   - Re-run transforms to measure improvement

4. **Success Metrics**:
   - **Target**: Reduce unmapped traits from 551 to <50 (90% coverage)
   - **Current**: 551 unmapped (1.16M occurrences)
   - **Phase 1 Goal**: 350 unmapped (40% resolved)
   - **Phase 2 Goal**: 55 unmapped (90% resolved)

---

## Appendix: Sample METPO Term Definitions

### Example 1: Plastic Degradation

```turtle
METPO:XXXXXX a owl:Class ;
    rdfs:label "plastic degradation capability" ;
    rdfs:subClassOf METPO:2000509 ;  # metabolic process
    obo:IAO_0000115 "The ability of an organism to degrade plastic polymers" ;
    rdfs:seeAlso GO:0042537 ;  # hydrocarbon catabolic process
    .
```

### Example 2: Sulfur Compound Electron Acceptor

```turtle
METPO:XXXXXX a owl:Class ;
    rdfs:label "sulfur compound electron acceptor capability" ;
    rdfs:subClassOf METPO:XXXXXX ;  # electron acceptor capability (new parent)
    obo:IAO_0000115 "The ability to use sulfur compounds as terminal electron acceptors" ;
    rdfs:seeAlso GO:0019417 ;  # sulfur oxidation
    .
```

### Example 3: Quantitative Temperature Growth

```turtle
METPO:XXXXXX a owl:Class ;
    rdfs:label "growth at temperature" ;
    rdfs:subClassOf METPO:1000604 ;  # thermophile
    obo:IAO_0000115 "Growth at a specific temperature" ;
    .

# Data property for measurements
METPO:has_temperature_optimum a owl:DatatypeProperty ;
    rdfs:domain METPO:XXXXXX ;
    rdfs:range xsd:decimal ;
    obo:IAO_0000116 "Temperature in degrees Celsius" ;
    .
```

---

**Report Generated**: 2026-03-28
**Analysis Tool**: Python 3.10 + custom trait categorization
**Data Sources**: metatraits + metatraits_gtdb transforms
