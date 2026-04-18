# New Edge Types for API Kit Assay Implementation

**Date**: 2026-01-12
**Status**: SPECIFICATION

---

## Overview

This document specifies all new edge types that will be created in the dual-edge assay implementation. Existing direct organism→entity edges are preserved (not listed here).

---

## New Edge Type 1: Organism → Assay (Test Outcomes)

These edges capture the results of API kit tests performed on organisms.

### Edge Pattern

```
Subject: NCBITaxon:{id} or strain:bacdive_{id}
Predicate: METPO predicate (varies by test type and result)
Object: assay:{kit_name}_{well_name}
Relation: RO or Biolink relation (varies by test type)
```

### Enzyme Test Outcomes

#### 1a. Organism Shows Enzyme Activity (Positive Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000302 | (shows activity of) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | RO:0002215 | (capable of) |

**Predicate Domain**: biolink:BiologicalEntity (OrganismTaxon ✓)
**Predicate Range**: biolink:BiologicalEntity (Procedure ⚠️ - semantic stretch)

**Example**:
```tsv
subject: NCBITaxon:562
predicate: METPO:2000302
object: assay:API_zym_alkaline_phosphatase
relation: RO:0002215
```

#### 1b. Organism Does Not Show Enzyme Activity (Negative Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000303 | (does not show activity of) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | RO:0002215 | (capable of) |

**Predicate Domain**: biolink:BiologicalEntity
**Predicate Range**: biolink:BiologicalEntity

**Example**:
```tsv
subject: NCBITaxon:1234
predicate: METPO:2000303
object: assay:API_zym_esterase
relation: RO:0002215
```

---

### Chemical Test Outcomes - Fermentation

#### 1c. Organism Ferments Substrate (Positive Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000011 | (ferments) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity (Procedure ⚠️ - semantic stretch)

**Example**:
```tsv
subject: NCBITaxon:562
predicate: METPO:2000011
object: assay:API_50CHac_ERY
relation: biolink:interacts_with
```

#### 1d. Organism Does Not Ferment Substrate (Negative Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000037 | (does not ferment) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity

**Example**:
```tsv
subject: NCBITaxon:1234
predicate: METPO:2000037
object: assay:API_50CHac_DARA
relation: biolink:interacts_with
```

---

### Chemical Test Outcomes - Assimilation

#### 1e. Organism Assimilates Substrate (Positive Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000008 | (assimilates) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity

**Example**:
```tsv
subject: NCBITaxon:562
predicate: METPO:2000008
object: assay:API_20NE_GLU
relation: biolink:interacts_with
```

#### 1f. Organism Does Not Assimilate Substrate (Negative Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000034 | (does not assimilate) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity

**Example**:
```tsv
subject: NCBITaxon:1234
predicate: METPO:2000034
object: assay:API_20NE_MAL
relation: biolink:interacts_with
```

---

### Chemical Test Outcomes - Growth

#### 1g. Organism Uses Substrate for Growth (Positive Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000012 | (uses for growth) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity

**Example**:
```tsv
subject: NCBITaxon:562
predicate: METPO:2000012
object: assay:API_biotype100_GLU
relation: biolink:interacts_with
```

#### 1h. Organism Does Not Use Substrate for Growth (Negative Result)

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | NCBITaxon:{id} | biolink:OrganismTaxon |
| **Predicate** | METPO:2000038 | (does not use for growth) |
| **Object** | assay:{kit}_{well} | biolink:Procedure |
| **Relation** | biolink:interacts_with | |

**Predicate Domain**: biolink:OrganismTaxon
**Predicate Range**: biolink:ChemicalEntity

**Example**:
```tsv
subject: NCBITaxon:1234
predicate: METPO:2000038
object: assay:API_biotype100_FRU
relation: biolink:interacts_with
```

---

## New Edge Type 2: Assay → GO/EC (Enzyme Output)

These edges describe what enzyme activities are detected by enzyme assays.

### Edge Pattern

```
Subject: assay:{kit_name}_{well_name}
Predicate: biolink:has_output
Object: GO:{term_id} or EC:{enzyme_class}
Relation: NCIT:C25284 (output)
```

### 2a. Assay Detects GO Molecular Function

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | assay:{kit}_{well} | biolink:Procedure |
| **Predicate** | biolink:has_output | |
| **Object** | GO:{id} | biolink:MolecularActivity |
| **Relation** | NCIT:C25284 | (output) |

**Predicate Domain**: biolink:Occurrent (Procedure ✓)
**Predicate Range**: biolink:NamedThing (MolecularActivity ✓)

**Example**:
```tsv
subject: assay:API_zym_alkaline_phosphatase
predicate: biolink:has_output
object: GO:0004035
relation: NCIT:C25284
knowledge_source: infores:assay-metadata
```

### 2b. Assay Detects EC Enzyme Class

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | assay:{kit}_{well} | biolink:Procedure |
| **Predicate** | biolink:has_output | |
| **Object** | EC:{number} | biolink:MolecularActivity |
| **Relation** | NCIT:C25284 | (output) |

**Predicate Domain**: biolink:Occurrent
**Predicate Range**: biolink:NamedThing

**Example**:
```tsv
subject: assay:API_zym_alkaline_phosphatase
predicate: biolink:has_output
object: EC:3.1.3.1
relation: NCIT:C25284
knowledge_source: infores:assay-metadata
```

---

## New Edge Type 3: Assay → ChEBI (Chemical Input)

These edges describe what chemical substrates are used as inputs in chemical assays.

### Edge Pattern

```
Subject: assay:{kit_name}_{well_name}
Predicate: biolink:has_input
Object: CHEBI:{id}
Relation: RO:0002233 (has input)
```

### 3. Assay Tests Chemical Substrate

| Field | Value | Biolink Type |
|-------|-------|--------------|
| **Subject** | assay:{kit}_{well} | biolink:Procedure |
| **Predicate** | biolink:has_input | |
| **Object** | CHEBI:{id} | biolink:ChemicalEntity |
| **Relation** | RO:0002233 | (has input) |

**Predicate Domain**: biolink:Occurrent (Procedure ✓)
**Predicate Range**: biolink:NamedThing (ChemicalEntity ✓)

**Example**:
```tsv
subject: assay:API_50CHac_ERY
predicate: biolink:has_input
object: CHEBI:17113
relation: RO:0002233
knowledge_source: infores:assay-metadata
```

---

## Summary Table: All New Edge Types

| # | Subject Type | Predicate | Object Type | Count | Created When |
|---|--------------|-----------|-------------|-------|--------------|
| 1a | OrganismTaxon | METPO:2000302 | Procedure | ~30K-50K | Per organism, positive enzyme |
| 1b | OrganismTaxon | METPO:2000303 | Procedure | ~10K-20K | Per organism, negative enzyme |
| 1c | OrganismTaxon | METPO:2000011 | Procedure | ~10K-20K | Per organism, ferments |
| 1d | OrganismTaxon | METPO:2000037 | Procedure | ~5K-10K | Per organism, does not ferment |
| 1e | OrganismTaxon | METPO:2000008 | Procedure | ~5K-10K | Per organism, assimilates |
| 1f | OrganismTaxon | METPO:2000034 | Procedure | ~2K-5K | Per organism, does not assimilate |
| 1g | OrganismTaxon | METPO:2000012 | Procedure | ~5K-10K | Per organism, uses for growth |
| 1h | OrganismTaxon | METPO:2000038 | Procedure | ~2K-5K | Per organism, does not use for growth |
| 2a | Procedure | biolink:has_output | MolecularActivity (GO) | ~200-300 | Once upfront (per GO) |
| 2b | Procedure | biolink:has_output | MolecularActivity (EC) | ~150-200 | Once upfront (per EC) |
| 3 | Procedure | biolink:has_input | ChemicalEntity | ~250-300 | Once upfront (per ChEBI) |

**Total New Edges**: ~69,600 - ~125,300 (approximately ~50K-100K organism→assay + ~600-800 assay→entity)

---

## Predicate Details

### METPO Predicates (Organism → Assay)

These are domain-specific predicates from the METPO (Microbial Environmental Traits and Phenotypes Ontology).

| Predicate | Label | Domain | Range | Used For |
|-----------|-------|--------|-------|----------|
| METPO:2000302 | shows activity of | OrganismTaxon | BiologicalEntity | Positive enzyme test |
| METPO:2000303 | does not show activity of | OrganismTaxon | BiologicalEntity | Negative enzyme test |
| METPO:2000011 | ferments | OrganismTaxon | ChemicalEntity | Positive fermentation test |
| METPO:2000037 | does not ferment | OrganismTaxon | ChemicalEntity | Negative fermentation test |
| METPO:2000008 | assimilates | OrganismTaxon | ChemicalEntity | Positive assimilation test |
| METPO:2000034 | does not assimilate | OrganismTaxon | ChemicalEntity | Negative assimilation test |
| METPO:2000012 | uses for growth | OrganismTaxon | ChemicalEntity | Positive growth test |
| METPO:2000038 | does not use for growth | OrganismTaxon | ChemicalEntity | Negative growth test |

**Note**: When targeting assay nodes (Procedure), these predicates technically violate their intended range (ChemicalEntity or BiologicalEntity, not Procedure). However, this is acceptable because:
1. The assay acts as a proxy for the biological process
2. The dual-edge pattern maintains direct edges with correct ranges
3. The semantic intent is preserved (organism has capability tested by assay)

### Biolink Predicates (Assay → Entity)

These are standard Biolink Model predicates.

| Predicate | Label | Domain | Range | Used For |
|-----------|-------|--------|-------|----------|
| biolink:has_output | has output | Occurrent | NamedThing | Assay produces evidence of enzyme activity |
| biolink:has_input | has input | Occurrent | NamedThing | Assay uses chemical substrate as input |

**Occurrent** includes:
- biolink:Procedure ✓ (our assay nodes)
- biolink:BiologicalProcess
- biolink:Behavior

**NamedThing** includes:
- biolink:MolecularActivity ✓ (GO terms, EC numbers)
- biolink:ChemicalEntity ✓ (ChEBI entities)
- All other Biolink entities

---

## Relation Details

These RO (Relation Ontology) and NCIT (NCI Thesaurus) terms provide semantic meaning in the `relation` field.

| Relation | Label | Description | Used With |
|----------|-------|-------------|-----------|
| RO:0002215 | capable of | An organism is capable of a biological process or molecular function | Enzyme tests (organism→assay) |
| RO:0002233 | has input | A process has a specified input | Chemical tests (assay→ChEBI) |
| NCIT:C25284 | output | Something that is produced as a result | Enzyme tests (assay→GO/EC) |
| biolink:interacts_with | interacts with | Generic interaction relation | Chemical tests (organism→assay) |

---

## Node Categories

All nodes involved in these edges and their Biolink categories:

| Node Type | Example ID | Biolink Category | Description |
|-----------|-----------|------------------|-------------|
| Organism | NCBITaxon:562 | biolink:OrganismTaxon | Taxonomic identifier for organisms |
| Strain | strain:bacdive_12502 | biolink:OrganismTaxon | Specific strain identifier |
| Assay | assay:API_zym_alkaline_phosphatase | biolink:Procedure | API kit test component |
| GO Term | GO:0004035 | biolink:MolecularActivity | Gene Ontology molecular function |
| EC Number | EC:3.1.3.1 | biolink:MolecularActivity | Enzyme Commission classification |
| ChEBI | CHEBI:17113 | biolink:ChemicalEntity | Chemical Entities of Biological Interest |

---

## Edge Provenance

### Organism → Assay Edges

| Field | Value |
|-------|-------|
| knowledge_source | infores:bacdive |
| primary_knowledge_source | bacdive:{record_id} |
| knowledge_level | observation |
| agent_type | manual_agent |

**Source**: BacDive API records with physiology_and_metabolism.test.API fields

### Assay → Entity Edges

| Field | Value |
|-------|-------|
| knowledge_source | infores:assay-metadata |
| primary_knowledge_source | assay-metadata |
| knowledge_level | knowledge_assertion |
| agent_type | manual_agent |

**Source**: assay_kits_simple.json from CultureBotAI/assay-metadata repository

---

## Validation Rules

### For Organism → Assay Edges

1. ✅ Subject must be NCBITaxon:{id} or strain:bacdive_{id}
2. ✅ Predicate must be one of 8 METPO predicates listed above
3. ✅ Object must be assay:{kit}_{well} node that exists
4. ✅ Relation must match test type (RO:0002215 for enzyme, biolink:interacts_with for chemical)
5. ✅ knowledge_source must be infores:bacdive
6. ✅ Edge should only exist if organism has actual test result in BacDive

### For Assay → Entity Edges

1. ✅ Subject must be assay:{kit}_{well} node
2. ✅ Predicate must be biolink:has_output (enzyme) or biolink:has_input (chemical)
3. ✅ Object must be GO:{id}, EC:{number}, or CHEBI:{id}
4. ✅ Relation must be NCIT:C25284 (output) or RO:0002233 (input)
5. ✅ knowledge_source must be infores:assay-metadata
6. ✅ All assay→entity edges created upfront (not dependent on organism data)

---

## Example Complete Paths

### Example 1: Positive Enzyme Test

```
# Organism shows alkaline phosphatase activity

Organism → Assay:
  subject: NCBITaxon:562
  predicate: METPO:2000302
  object: assay:API_zym_alkaline_phosphatase
  relation: RO:0002215
  knowledge_source: infores:bacdive

Assay → GO:
  subject: assay:API_zym_alkaline_phosphatase
  predicate: biolink:has_output
  object: GO:0004035
  relation: NCIT:C25284
  knowledge_source: infores:assay-metadata

Assay → EC:
  subject: assay:API_zym_alkaline_phosphatase
  predicate: biolink:has_output
  object: EC:3.1.3.1
  relation: NCIT:C25284
  knowledge_source: infores:assay-metadata
```

**Result**: User can trace from organism to enzyme activity via assay, understanding both the biological fact and the experimental method used.

### Example 2: Negative Fermentation Test

```
# Organism does not ferment D-arabinose

Organism → Assay:
  subject: NCBITaxon:1234
  predicate: METPO:2000037
  object: assay:API_50CHac_DARA
  relation: biolink:interacts_with
  knowledge_source: infores:bacdive

Assay → ChEBI:
  subject: assay:API_50CHac_DARA
  predicate: biolink:has_input
  object: CHEBI:16731
  relation: RO:0002233
  knowledge_source: infores:assay-metadata
```

**Result**: User can see organism tested negative for D-arabinose fermentation using API 50CHac kit.

### Example 3: Positive Growth Test

```
# Organism uses glucose for growth

Organism → Assay:
  subject: NCBITaxon:562
  predicate: METPO:2000012
  object: assay:API_biotype100_GLU
  relation: biolink:interacts_with
  knowledge_source: infores:bacdive

Assay → ChEBI:
  subject: assay:API_biotype100_GLU
  predicate: biolink:has_input
  object: CHEBI:17234
  relation: RO:0002233
  knowledge_source: infores:assay-metadata
```

**Result**: User can see organism can grow using glucose as sole carbon source, tested via API biotype100 kit.

---

## Implementation Checklist

- [ ] All 8 METPO predicates handled in code
- [ ] Organism→assay edges created for each test result
- [ ] Assay→GO edges created for all GO terms in metadata
- [ ] Assay→EC edges created for all EC numbers in metadata
- [ ] Assay→ChEBI edges created for all ChEBI IDs in metadata
- [ ] Correct relation field populated for each edge type
- [ ] Correct knowledge_source populated for each edge type
- [ ] Edge counts match estimates (~50K-100K organism→assay, ~600-800 assay→entity)
- [ ] No predicate domain/range violations cause validation errors
- [ ] Sample queries work for all edge types

---

**Created**: 2026-01-12
**Status**: Specification for implementation
**Related**:
- `docs/ASSAY_DUAL_EDGE_DESIGN.md` (design rationale)
- `docs/ASSAY_IMPLEMENTATION_SUMMARY.md` (implementation guide)
