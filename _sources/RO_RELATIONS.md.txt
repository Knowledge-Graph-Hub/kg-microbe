# RO (Relations Ontology) Usage in kg-microbe

**Last Updated**: January 10, 2026

This document lists all Relations Ontology (RO) terms used in kg-microbe transforms.

---

## Overview

The Relations Ontology (RO) provides standardized relation terms for biological and biomedical relationships. kg-microbe uses RO terms extensively to express semantic relationships between entities in the knowledge graph.

**RO Ontology**:
- **Source**: http://purl.obolibrary.org/obo/ro.owl
- **Download**: Included in `download.yaml`
- **Transform**: Processed by ontologies transform
- **Documentation**: https://www.obofoundry.org/ontology/ro.html

---

## RO Relations by Category

### Organism Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002215 | capable of / biological process | Organism capability predicates |
| RO:0002438 | trophically interacts with | Organism to carbon substrate interaction |
| RO:0001015 | location of | Organism to isolation source |
| RO:0002200 | has phenotype | Organism phenotype relationships |
| RO:0002551 | has gene | Organism to gene relationship |

### Molecular Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002327 | enables | Protein/gene enables molecular function |
| RO:0002436 | molecularly interacts with | Chemical-protein interactions |
| RO:0002233 | has input | Reaction/process has chemical input |
| RO:0002234 | has output | Reaction/process has chemical output |
| RO:0002333 | enabled by | Process enabled by enzyme |

### Process Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0000056 | participates in | Entity participates in process/assay |
| RO:0000057 | has participant | Process has entity as participant |
| RO:0002331 | involved in | Gene/protein involved in biological process |

### Structural Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0001025 | located in | Protein/component located in cellular location |
| RO:0001000 | derives from | Protein derives from organism |
| RO:0000052 | related to | General relatedness |

### Functional Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0000087 | has role | Chemical entity has functional role |
| RO:0002205 | has gene product | Gene has protein product |
| RO:0002326 | contributes to | Protein contributes to disease |
| RO:0002350 | member of | Gene is member of ortholog group/COG |

### Disease-Microbe Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002610 | correlated with | Disease-microbe abundance correlations (Disbiome, Wallen et al) |

### Homology Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:HOM0000017 | orthologous to | Gene orthology relationships (KEGG KO) |

---

## Transform Usage

### BacDive Transform
**File**: `kg_microbe/transform_utils/bacdive/bacdive.py`

**Relations used**:
- **RO:0002233** (has input) - Enzyme to substrate relationships
  - Example: `EC:3.5.1.5 → has_input → CHEBI:16199 (urea)`

---

### Bakta Transform
**File**: `kg_microbe/transform_utils/bakta/bakta.py`

**Relations used**:
- **RO:0002551** (has gene) - Organism to gene relationships
  - Example: `NCBITaxon:12345 → has_gene → gene:SAMN123_00001`

- **RO:0002205** (has gene product) - Gene to protein relationships
  - Example: `gene:SAMN123_00001 → has_gene_product → UniProtKB:P12345`

- **RO:0002327** (enables) - Protein enables molecular function
  - Example: `UniProtKB:P12345 → enables → GO:0005524 (ATP binding)`

- **RO:0002350** (member of) - Gene membership in ortholog groups
  - Example: `gene:SAMN123_00001 → member_of → COG:COG0001`

- **RO:0002331** (involved in) - Gene/protein involved in biological process
  - Example: `gene:SAMN123_00001 → involved_in → GO:0006412 (translation)`

- **RO:HOM0000017** (orthologous to) - Gene orthology to KEGG KO
  - Example: `gene:SAMN123_00001 → orthologous_to → KEGG:K00001`

---

### MediaDive Transform
**File**: `kg_microbe/transform_utils/mediadive/mediadive.py`

**Relations used**:
- **RO:0000087** (has role) - Chemical entity to functional role
  - Example: `CHEBI:16199 → has_role → CHEBI:78295 (nitrogen source role)`

---

### Madin et al Transform
**File**: `kg_microbe/transform_utils/madin_etal/madin_etal.py`

**Relations used**:
- **RO:0000087** (has role) - Chemical entity to functional role
  - Example: `CHEBI:17234 → has_role → CHEBI:78297 (carbon source role)`

- **RO:0001015** (location of) - Organism to isolation source
  - Example: `NCBITaxon:12345 → location_of → ENVO:00002030 (aquatic environment)`

---

### BactoTraits Transform
**File**: `kg_microbe/transform_utils/bactotraits/bactotraits.py`

**Relations used**:
- **RO:0002215** (capable of / biological process) - Organism capability predicates
  - Example: `NCBITaxon:12345 → capable_of → GO:0015976 (carbon fixation)`

- **RO:0002200** (has phenotype) - Organism phenotype relationships
  - Example: `NCBITaxon:12345 → has_phenotype → PATO:0001396 (motile)`

---

### UniProt Transform
**File**: `kg_microbe/utils/uniprot_utils.py`

**Relations used**:
- **RO:0001000** (derives from) - Protein to organism
  - Example: `UniProtKB:P12345 → derives_from → NCBITaxon:12345`

- **RO:0002327** (enables) - Protein to EC enzyme
  - Example: `UniProtKB:P12345 → enables → EC:3.5.1.5`

- **RO:0002436** (molecularly interacts with) - Chemical to protein
  - Example: `CHEBI:16199 → molecularly_interacts_with → UniProtKB:P12345`

- **RO:0000056** (participates in) - Protein participates in process
  - Example: `UniProtKB:P12345 → participates_in → GO:0006412`

- **RO:0001025** (located in) - Protein cellular location
  - Example: `UniProtKB:P12345 → located_in → GO:0005737 (cytoplasm)`

- **RO:0002326** (contributes to) - Protein to disease
  - Example: `UniProtKB:P12345 → contributes_to → MONDO:0005148`

- **RO:0002205** (has gene product) - Gene to protein
  - Example: `gene:SAMN123_00001 → has_gene_product → UniProtKB:P12345`

---

### Rhea Mappings Transform
**File**: `kg_microbe/transform_utils/rhea_mappings/rhea_mappings.py`

**Relations used**:
- **RO:0002233** (has input) - Reaction to substrate
  - Example: `RHEA:10000 → has_input → CHEBI:16199`

- **RO:0002234** (has output) - Reaction to product
  - Example: `RHEA:10000 → has_output → CHEBI:16234`

- **RO:0002333** (enabled by) - Reaction enabled by enzyme
  - Example: `RHEA:10000 → enabled_by → EC:3.5.1.5`

---

### Disbiome Transform
**File**: `kg_microbe/transform_utils/disbiome/disbiome.py`

**Edge Direction**: Disease → Microbe (flipped from previous implementation)

**Rationale**: Represents observational correlation between disease state and microbial abundance. The direction Disease→Microbe better captures the clinical observation perspective: "Disease X is correlated with increased/decreased abundance of Microbe Y"

**Relations used**:
- **RO:0002610** (correlated with) - Disease-microbe abundance correlations
  - Elevated cases use `biolink:positively_correlated_with`
  - Reduced cases use `biolink:negatively_correlated_with`
  - Example: `MONDO:0005180 → positively_correlated_with → NCBITaxon:1678`
  - Example: `MONDO:0005066 → negatively_correlated_with → NCBITaxon:853`

---

### Wallen et al Transform
**File**: `kg_microbe/transform_utils/wallen_etal/wallen_etal.py`

**Edge Direction**: Disease → Microbe (same as Disbiome for consistency)

**Relations used**:
- **RO:0002610** (correlated with) - Parkinson's disease to microbe abundance correlations
  - Higher PD abundance: `biolink:positively_correlated_with`
  - Higher control abundance: `biolink:negatively_correlated_with`
  - Example: `MONDO:0005180 → positively_correlated_with → NCBITaxon:239935`

---

## Constants Reference

All RO relations are defined as constants in `kg_microbe/transform_utils/constants.py`:

```python
# Core RO relations
TROPHICALLY_INTERACTS_WITH = "RO:0002438"
LOCATION_OF = "RO:0001015"
BIOLOGICAL_PROCESS = "RO:0002215"
HAS_ROLE = "RO:0000087"
HAS_PARTICIPANT = "RO:0000057"
PARTICIPATES_IN = "RO:0000056"
HAS_PHENOTYPE = "RO:0002200"
CAPABLE_OF = "RO:0002215"

# Molecular relations
DERIVES_FROM = "RO:0001000"
ENABLES = "RO:0002327"
MOLECULARLY_INTERACTS_WITH = "RO:0002436"
LOCATED_IN = "RO:0001025"
CONTRIBUTES_TO = "RO:0002326"
HAS_GENE_PRODUCT = "RO:0002205"
HAS_INPUT_RELATION = "RO:0002233"
HAS_OUTPUT_RELATION = "RO:0002234"
ENABLED_BY_RELATION = "RO:0002333"
RELATED_TO_RELATION = "RO:0000052"

# Bakta-specific relations
HAS_GENE = "RO:0002551"
MEMBER_OF = "RO:0002350"
INVOLVED_IN = "RO:0002331"
ORTHOLOGOUS_TO = "RO:HOM0000017"

# Disease-microbe relations
CORRELATED_WITH = "RO:0002610"
POSITIVELY_CORRELATED_WITH = CORRELATED_WITH
NEGATIVELY_CORRELATED_WITH = CORRELATED_WITH
```

---

## Non-RO Relations

kg-microbe also uses relations from other ontologies:

| Ontology | Relations Used |
|----------|---------------|
| **BFO** (Basic Formal Ontology) | BFO:0000050 (part of), BFO:0000051 (has part) |
| **NCIT** (NCI Thesaurus) | NCIT:C153110 (assessed activity) |
| **PATO** (Phenotype Ontology) | PATO:0001668 (associated with) |
| **SKOS** | skos:closeMatch, skos:exactMatch |
| **RDFS** | rdfs:subClassOf |
| **UPA** (UniPathways) | OBO:upa#has_alternate_enzymatic_reaction |

---

## Validation

To validate all RO relations against the downloaded ontology, use:

```bash
python scripts/validate_ro_relations.py
```

This script:
1. Extracts all valid RO terms from `data/raw/ro.owl`
2. Checks all relation values in transformed edge files
3. Reports numeric-only relations (missing `RO:` prefix)
4. Reports invalid RO term IDs

---

## Best Practices

1. **Always use constants**: Never hardcode RO values like `"RO:0002327"`
   - ✅ Good: `ENABLES`
   - ❌ Bad: `"RO:0002327"`

2. **Verify term validity**: Check new RO terms against the ontology
   - Use OLS Browser: https://www.ebi.ac.uk/ols/ontologies/ro
   - Or download and search local ro.owl

3. **Document new constants**: When adding new RO constants:
   - Add to `constants.py` with descriptive name and comment
   - Update this document with usage examples
   - Run validation script

4. **Prefer specific over general**: Use most specific applicable relation
   - ✅ Good: `enables` for protein→function
   - ❌ Bad: `related_to` for protein→function

---

## References

- **RO OBO Foundry**: https://www.obofoundry.org/ontology/ro.html
- **RO GitHub**: https://github.com/oborel/obo-relations
- **RO Documentation**: https://github.com/oborel/obo-relations/wiki
- **OLS Browser**: https://www.ebi.ac.uk/ols/ontologies/ro
- **Biolink Model**: https://biolink.github.io/biolink-model/

---

**Maintained by**: kg-microbe team
**Repository**: https://github.com/KG-Hub/KG-Microbe
