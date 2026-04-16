# Phase 1: Key Patterns Resolved with METPO Predicates

**Total:** 30 patterns, 9.6M observations

---

## High-Frequency Patterns (Top 10)

| Pattern | Observations | METPO Predicate | Resolution | Predicate Meaning |
|---------|--------------|-----------------|------------|-------------------|
| **electron acceptor: sulfur compounds** | 1.2M | **METPO:2000008** | CHEBI:26833 | uses as electron acceptor |
| **oxidation in darkness: sulfur compounds** | 1.2M | **METPO:2000605** | CHEBI:26833 | oxidizes in darkness |
| **degradation: plastic** | 1.2M | **METPO:2000007** | ENVO:01000970 | degrades |
| **degradation: aromatic compound** | 1.0M | **METPO:2000007** | CHEBI:33655 | degrades |
| **degradation: aromatic hydrocarbon** | 800K | **METPO:2000007** | CHEBI:33848 | degrades |
| **degradation: hydrocarbon** | 600K | **METPO:2000007** | CHEBI:24632 | degrades |
| **electron acceptor: amorphous iron(iii) oxide** | 500K | **METPO:2000008** | CHEBI:82594 | uses as electron acceptor |
| **produces: methane from formate** | 400K | **METPO:2000202** | CHEBI:16183 | produces |
| **reduction: arsenate detoxification** | 300K | **METPO:2000017** | CHEBI:29242 | reduces |
| **aerobic catabolization: dihydrogen** | 200K | **METPO:2000032** | CHEBI:29356 | uses for aerobic catabolization |

**Subtotal:** 7.2M observations

---

## All 30 Patterns by METPO Predicate Category

### 1. Electron Acceptor (METPO:2000008) - 4 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| electron acceptor: sulfur compounds | CHEBI:26833 | ChemicalEntity |
| electron acceptor: amorphous iron (iii) oxide | CHEBI:82594 | ChemicalEntity |
| electron acceptor: ethylenediaminetetraacetatoferrate | CHEBI:42191 | ChemicalEntity |
| electron acceptor: amorphous fe(iii) oxyhydroxid | CHEBI:82594 | ChemicalEntity |

### 2. Degradation (METPO:2000007) - 6 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| degradation: plastic | ENVO:01000970 | EnvironmentalMaterial |
| degradation: aromatic compound | CHEBI:33655 | ChemicalEntity |
| degradation: hydrocarbon | CHEBI:24632 | ChemicalEntity |
| degradation: aromatic hydrocarbon | CHEBI:33848 | ChemicalEntity |
| degradation: elastin | CHEBI:53248 | ChemicalEntity |
| degradation: egg yolk | FOODON:00001274 | Food |
| degradation: 4-nitrophenyl beta-D-galactopyranoside | CHEBI:52701 | ChemicalEntity |

### 3. Hydrolysis (METPO:2000013) - 5 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| hydrolysis: 4-nitrophenyl beta-D-galactopyranoside | CHEBI:52701 | ChemicalEntity |
| hydrolysis: casein hydrolysate | CHEBI:17895 | ChemicalEntity |
| hydrolysis: cationic chitosan | CHEBI:16261 | ChemicalEntity |
| hydrolysis: crab shell chitin | CHEBI:17029 | ChemicalEntity |
| hydrolysis: milk | FOODON:03301422 | Food |
| hydrolysis: 4-nitrophenyl-alpha-D-maltopyranoside | CHEBI:87626 | ChemicalEntity |

### 4. Reduction (METPO:2000017) - 4 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| reduction: arsenate detoxification | CHEBI:29242 | ChemicalEntity |
| reduction: amorphous iron (iii) oxide | CHEBI:82594 | ChemicalEntity |
| reduction: amorphous fe(iii) oxyhydroxid | CHEBI:82594 | ChemicalEntity |
| reduction: glutathione oxidized | CHEBI:17858 | ChemicalEntity |
| reduction: 3-O-methylgallate | CHEBI:68499 | ChemicalEntity |

### 5. Production (METPO:2000202) - 2 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| produces: methane from formate | CHEBI:16183 | ChemicalEntity |
| produces: DL-lactate | CHEBI:422 | ChemicalEntity |

### 6. Aerobic Catabolization (METPO:2000032) - 2 patterns ⭐ NEW USAGE
| Pattern | Resolution | Category |
|---------|------------|----------|
| aerobic catabolization: dihydrogen | CHEBI:29356 | ChemicalEntity |
| aerobic catabolization: acetate | CHEBI:30089 | ChemicalEntity |

### 7. Anaerobic Catabolization (METPO:2000048) - 1 pattern ⭐ NEW USAGE
| Pattern | Resolution | Category |
|---------|------------|----------|
| anaerobic catabolization: acetate | CHEBI:30089 | ChemicalEntity |

### 8. Oxidation in Darkness (METPO:2000605) - 1 pattern ✅ CORRECTED
| Pattern | Resolution | Category |
|---------|------------|----------|
| oxidation in darkness: sulfur compounds | CHEBI:26833 | ChemicalEntity |

### 9. General Utilization (METPO:2000001) - 2 patterns
| Pattern | Resolution | Category |
|---------|------------|----------|
| utilizes: 4-nitrophenyl beta-D-galactopyranoside | CHEBI:52701 | ChemicalEntity |
| utilizes: 1,2-propandiol | CHEBI:16240 | ChemicalEntity |

---

## METPO Predicate Definitions

| METPO ID | Predicate Name | Biolink Mapping | Definition |
|----------|----------------|-----------------|------------|
| METPO:2000001 | organism interacts with chemical | biolink:interacts_with | Generic interaction |
| METPO:2000007 | degrades | biolink:capable_of | Can break down substance |
| METPO:2000008 | uses as electron acceptor | biolink:capable_of | Terminal electron acceptor in respiration |
| METPO:2000013 | hydrolyzes | biolink:capable_of | Enzymatic cleavage using water |
| METPO:2000017 | reduces | biolink:capable_of | Reduction reaction |
| METPO:2000032 | uses for aerobic catabolization | biolink:capable_of | Aerobic breakdown for energy |
| METPO:2000048 | uses for anaerobic catabolization | biolink:capable_of | Anaerobic breakdown for energy |
| METPO:2000202 | produces | biolink:produces | Metabolic product |
| METPO:2000605 | oxidizes in darkness | biolink:capable_of | Chemolithotrophic oxidation |

---

## Ontologies Used

### ChEBI (Chemical Entities) - 23 patterns
- Parent classes: CHEBI:26833 (sulfur), CHEBI:33655 (aromatic), CHEBI:24632 (hydrocarbon)
- Specific compounds: CHEBI:82594 (iron oxide), CHEBI:16183 (methane), CHEBI:29242 (arsenate)
- Proteins: CHEBI:53248 (elastin), CHEBI:17895 (casein)
- Assay substrates: CHEBI:52701, CHEBI:87626 (nitrophenyl compounds)

### ENVO (Environment Ontology) - 1 pattern
- ENVO:01000970 (plastic material)

### FOODON (Food Ontology) - 2 patterns
- FOODON:00001274 (egg yolk)
- FOODON:03301422 (milk)

---

## Impact by Predicate Type

| METPO Predicate | Patterns | Estimated Observations | % of Phase 1 |
|-----------------|----------|------------------------|--------------|
| METPO:2000007 (degrades) | 6 | 3.5M | 36.5% |
| METPO:2000008 (electron acceptor) | 4 | 2.2M | 22.9% |
| METPO:2000605 (oxidizes in darkness) | 1 | 1.2M | 12.5% |
| METPO:2000013 (hydrolyzes) | 5 | 1.0M | 10.4% |
| METPO:2000017 (reduces) | 4 | 800K | 8.3% |
| METPO:2000202 (produces) | 2 | 450K | 4.7% |
| METPO:2000032 (aerobic catab.) | 2 | 250K | 2.6% |
| METPO:2000048 (anaerobic catab.) | 1 | 150K | 1.6% |
| METPO:2000001 (utilizes) | 2 | 100K | 1.0% |
| **TOTAL** | **30** | **9.6M** | **100%** |

---

## Key Insights

### 1. Degradation Dominates (36.5%)
- Plastic biodegradation: 1.2M observations
- Aromatic compound degradation: 2.3M observations
- Most use ChEBI parent classes (aromatic compound, hydrocarbon)

### 2. Electron Acceptor Patterns (35.4%)
- Sulfur compounds: 1.2M (parent class mapping)
- Iron compounds: 1.0M (specific forms)
- Critical for anaerobic respiration modeling

### 3. New Predicate Usage
- **METPO:2000032** (aerobic catabolization) - first usage
- **METPO:2000048** (anaerobic catabolization) - first usage
- Enables modeling of catabolic vs anabolic processes

### 4. Predicate Correction
- **METPO:2000605** (oxidizes in darkness) - fixed from 2000016
- Distinguishes chemolithotrophy from general oxidation

### 5. Cross-Ontology Integration
- **ChEBI** (77%) - chemical entities
- **ENVO** (3%) - environmental materials
- **FOODON** (7%) - food substances
- Appropriate category assignment for each

---

## Edge Structure

Each mapped pattern creates edges like:

```
subject: NCBITaxon:XXXXXX (organism)
predicate: METPO:2000008 (uses as electron acceptor)
object: CHEBI:26833 (sulfur molecular entity)
relation: biolink:capable_of
category: biolink:ChemicalEntity
primary_knowledge_source: infores:metatraits
```

**Total new edges:** 9.6M (one edge per observation)

---

## Validation

All 30 patterns tested and validated:
- ✅ Correct CURIE resolution
- ✅ Correct METPO predicate assignment
- ✅ Correct Biolink category
- ✅ Appropriate ontology selection (ChEBI vs ENVO vs FOODON)
