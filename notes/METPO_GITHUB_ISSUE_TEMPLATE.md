---
name: Term Request - KG-Microbe MetaTraits Integration
about: Request 44 new METPO terms for microbial trait data integration
title: '[TERM REQUEST] 44 terms for BacDive MetaTraits integration'
labels: term request, enhancement
assignees: ''
---

## Summary

Request for **44 new METPO terms** (9 data properties, 4 object properties, 31 classes) to enable comprehensive representation of microbial trait data from BacDive metatraits in the KG-Microbe knowledge graph.

**Impact:** Enable mapping of 1,092+ unique traits representing ~700,000 observations currently unmapped.

## Requestor Information

- **Project:** KG-Microbe (Knowledge Graph Hub)
- **Repository:** https://github.com/Knowledge-Graph-Hub/kg-microbe
- **Contact:** [Your name/email]
- **Data Source:** BacDive (Bacterial Diversity Metadatabase) - 85,000+ taxa
- **Use Case:** Microbial phenotype knowledge graph construction

## Proposal Overview

This request is organized in 3 phases by priority:

### Phase 1: Quantitative Growth Properties (9 data properties) - **CRITICAL PRIORITY**
**Coverage:** 176,101 observations

- 3 temperature properties (optimum, minimum, maximum)
- 3 salinity/NaCl properties (optimum, minimum, maximum)
- 3 pH properties (optimum, minimum, maximum)

**Rationale:** Enable quantitative modeling of growth conditions for biotechnology and ecological applications.

### Phase 2: Metabolic Process Predicates (4 object properties) - **CRITICAL PRIORITY**
**Coverage:** 473 traits, 495,000+ observations

- `assimilates` - nutrient uptake/incorporation (266 traits)
- `uses as energy source` - ATP generation (97 traits)
- `uses as nitrogen source` - nitrogen assimilation (57 traits)
- `uses as electron donor` - electron transport (53 traits)

**Rationale:** Fill gaps in metabolic process representation distinct from existing terms (carbon source, fermentation, etc.).

### Phase 3: Phenotypic Quality Classes (31 classes) - **HIGH PRIORITY**
**Coverage:** 38 traits, 26,000+ observations

- 5 morphological (cell shape, length, width, color, flagella)
- 4 genomic (GC%, genome size, gene count, coding density)
- 12 environmental tolerances (oxygen, pH, temperature, salinity ranges)
- 3 biochemical tests (indole, methyl red, hemolysis)
- 3 growth characteristics (selective media, bile resistance, biosafety level)

**Rationale:** Basic microbiological characterization traits essential for taxonomic identification and strain selection.

## Detailed Proposal

**Full specification:** See attached [`METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md`](../METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md)

**Term summary table:** See [`mappings/metpo_phases_1_2_3_terms.tsv`](../mappings/metpo_phases_1_2_3_terms.tsv)

## Example Term Definitions

### Phase 1 Example: Temperature Optimum (Data Property)

```turtle
METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature optimum"@en ;
    obo:IAO_0000115 "The optimal temperature at which an organism achieves maximum growth rate, measured in degrees Celsius."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;  # degree Celsius
    obo:IAO_0000119 "KG-Microbe metatraits: 85,311 observations from BacDive"@en ;
    .
```

**Example usage:**
```turtle
NCBITaxon:83332 a biolink:OrganismTaxon ;
    rdfs:label "Mycobacterium tuberculosis H37Rv" ;
    METPO:has_growth_temperature_optimum "37.0"^^xsd:decimal ;
    .
```

### Phase 2 Example: Assimilates (Object Property)

```turtle
METPO:2000021 a owl:ObjectProperty ;
    rdfs:label "assimilates"@en ;
    obo:IAO_0000115 "A relation between an organism and a chemical entity, where the organism takes up and incorporates the chemical into its biomass or metabolic intermediates."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range CHEBI:24431 ;  # chemical entity
    rdfs:subPropertyOf METPO:2000001 ;  # organism interacts with chemical
    obo:IAO_0000119 "KG-Microbe metatraits: 266 traits, 41,000+ observations from BacDive"@en ;
    .
```

**Example usage:**
```turtle
NCBITaxon:562 METPO:2000021 CHEBI:17234 .  # E. coli assimilates glucose
```

### Phase 3 Example: GC Content Percentage (Class)

```turtle
METPO:1007010 a owl:Class ;
    rdfs:label "GC content percentage"@en ;
    obo:IAO_0000115 "A genomic quality that describes the percentage of guanine-cytosine base pairs in the genome, a key taxonomic and phenotypic marker in microbiology."@en ;
    rdfs:subClassOf METPO:1000000 ;  # phenotypic trait
    oboInOwl:hasExactSynonym "GC%"@en ;
    obo:IAO_0000119 "KG-Microbe metatraits: 1 trait type from BacDive"@en ;
    .
```

## Use Cases

### 1. Biotechnology Strain Selection
Find thermophilic bacteria that ferment glucose:
```sparql
SELECT ?organism ?temp_opt WHERE {
  ?organism METPO:has_growth_temperature_optimum ?temp_opt .
  FILTER (?temp_opt > 60.0)
  ?organism METPO:2000011 CHEBI:17234 .  # ferments glucose
}
```

### 2. Metabolic Network Reconstruction
Find organisms with complete electron transport data:
```sparql
SELECT ?organism ?donor ?acceptor WHERE {
  ?organism METPO:2000024 ?donor .      # electron donor
  ?organism METPO:2000008 ?acceptor .  # electron acceptor
}
```

### 3. Environmental Niche Modeling
Find halophiles with known salinity ranges:
```sparql
SELECT ?organism ?nacl_opt WHERE {
  ?organism METPO:has_NaCl_concentration_optimum ?nacl_opt .
  FILTER (?nacl_opt > 3.0)
}
```

## Coverage Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Unique unmapped traits | 902 | ~388 | 514 resolved (57%) |
| Unmapped observations | 5,051,076 | ~4,350,000 | ~700,000 mapped (14%) |
| Total METPO terms | ~168 | ~212 | +44 terms (26% increase) |

## Questions for METPO Team

1. **ID assignments:** Are suggested ID ranges (1007001-1007052, 2000021-2000024) acceptable, or should we use different ranges?

2. **Existing term overlap:** Does `METPO:2000014` already represent "uses as nitrogen source"? If so, we can drop that from Phase 2.

3. **Hierarchy placement:** Phase 3 classes assume `METPO:1000000` as phenotypic trait parent. Should any terms have different parents?

4. **Environmental tolerance classes:** Phase 3 includes 12 "scaffolding" classes (pH/temp/salinity min/max/optimum) that primarily exist to organize Phase 1 data properties. Are these necessary or should we use data properties alone?

5. **Biosafety level:** Is `METPO:1007052 (biosafety level classification)` within METPO scope, or is this too regulatory/organizational?

6. **Phased implementation:** Can we prioritize Phase 1 and 2 (critical) and defer Phase 3 (high) if review bandwidth is limited?

## Timeline

We propose a phased implementation:

- **Weeks 1-2:** METPO maintainer review and feedback
- **Weeks 3-4:** ID assignment and finalization
- **Weeks 5-6:** KG-Microbe transform implementation
- **Weeks 7-8:** Testing and validation
- **Week 9:** Documentation and release

## Supporting Documentation

- **Full proposal:** [`METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md`](link-to-file)
- **Term summary:** [`metpo_phases_1_2_3_terms.tsv`](link-to-file)
- **Unmapped traits analysis:** [`additional_metpo_mappings.tsv`](link-to-file)
- **Existing METPO predicates:** [`docs/METPO_PREDICATES.md`](link-to-file)

## Additional Context

This request follows analysis of 902 unique unmapped trait types from BacDive metatraits data integrated via GTDB taxonomy. The proposed terms cover **essential microbiology characterization** not currently represented in METPO:

- Quantitative growth parameters (industry standard measurements)
- Fundamental metabolic distinctions (assimilation vs fermentation vs respiration)
- Morphological and genomic properties (taxonomic gold standards)

These additions would make METPO more comprehensive for:
- Culture collection catalogs (DSMZ, ATCC, JGI)
- Industrial strain datasheets
- Taxonomic species descriptions
- Systems biology models

We're happy to provide additional context, adjust definitions, or split this into multiple issues if preferred.

---

**Thank you for considering this request!** We're excited to contribute to METPO's growth and improve microbial phenotype representation.
