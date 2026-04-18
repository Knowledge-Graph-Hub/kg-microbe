# Biolink Model and METPO Predicate Review

## Overview

This document reviews the usage of Biolink Model predicates and categories across all KG-Microbe transforms, checking for domain/range compliance and identifying potential discrepancies.

**Generated**: 2025-12-17

---

## 1. Summary Statistics

### Node Categories Used

| Transform | Categories |
|-----------|-----------|
| **BacDive** | OrganismTaxon (271,805), ChemicalEntity (2,800), EnvironmentalFeature (353), Enzyme (104), PhenotypicQuality (72), ChemicalSubstance (8) |
| **MediaDive** | OrganismTaxon (22,367), ChemicalEntity (9,918), ChemicalRole (180), ChemicalMixture (2) |
| **madin_etal** | OrganismTaxon, ChemicalEntity, PhenotypicQuality, BiologicalProcess |
| **bactotraits** | OrganismTaxon, PhenotypicQuality |

### Predicate Usage by Transform

| Transform | Top Predicates |
|-----------|---------------|
| **BacDive** | METPO:2000303 (542,740), METPO:2000028 (321,601), METPO:2000302 (287,208), METPO:2000037 (284,331), biolink:subclass_of (252,218), biolink:location_of (231,468) |
| **MediaDive** | biolink:has_part (85,510), METPO:2000517 (54,989), biolink:subclass_of (3,327), biolink:has_chemical_role (648) |
| **madin_etal** | biolink:has_phenotype (111,928), METPO:2000006 (36,817), biolink:location_of (26,649), biolink:capable_of (7,493) |
| **bactotraits** | biolink:has_phenotype (90,768) |

---

## 2. Biolink Predicate Domain/Range Analysis

### Predicates Currently in Use

| Predicate | Biolink Domain | Biolink Range | KG-Microbe Usage | Status |
|-----------|---------------|---------------|------------------|--------|
| `biolink:has_phenotype` | biological entity | phenotypic quality | OrganismTaxon → PhenotypicQuality | ✓ Valid |
| `biolink:capable_of` | physical entity | biological process or activity | OrganismTaxon → BiologicalProcess | ✓ Valid |
| `biolink:has_input` | named thing | named thing | Enzyme → ChemicalEntity | ✓ Valid |
| `biolink:location_of` | named thing | named thing | EnvironmentalFeature → OrganismTaxon | ✓ Valid |
| `biolink:subclass_of` | named thing | named thing | OrganismTaxon → OrganismTaxon | ✓ Valid |
| `biolink:has_part` | named thing | named thing | ChemicalMixture → ChemicalEntity | ✓ Valid |
| `biolink:has_chemical_role` | chemical entity | chemical role | ChemicalEntity → ChemicalRole | ✓ Valid |
| `biolink:associated_with_resistance_to` | named thing | named thing | OrganismTaxon → ChemicalEntity | ✓ Valid |
| `biolink:associated_with_sensitivity_to` | named thing | named thing | OrganismTaxon → ChemicalEntity | ✓ Valid |
| `biolink:is_assessed_by` | named thing | named thing | Enzyme → assay:* | ✓ Valid |
| `biolink:occurs_in` | named thing | named thing | ChemicalEntity → assay:* | ✓ Valid |

---

## 3. METPO Predicate Analysis

### Key METPO Predicates and Their Semantics

| METPO ID | Label/Meaning | Edge Count | Subject → Object |
|----------|--------------|------------|------------------|
| `METPO:2000517` | grows in (organism → medium) | 91,840 | OrganismTaxon → ChemicalEntity |
| `METPO:2000006` | uses as carbon source | 93,823 | OrganismTaxon → ChemicalEntity |
| `METPO:2000202` | produces | 9,466 | OrganismTaxon → ChemicalEntity |
| `METPO:2000302` | shows activity of (positive) | 287,208 | OrganismTaxon → Enzyme/GO |
| `METPO:2000303` | does not show activity of (negative) | 542,740 | OrganismTaxon → Enzyme/GO |
| `METPO:2000028` | does not build acid from | 321,601 | OrganismTaxon → ChemicalEntity |
| `METPO:2000037` | does not ferment | 284,331 | OrganismTaxon → ChemicalEntity |
| `METPO:2000038` | does not use for growth | 157,869 | OrganismTaxon → ChemicalEntity |
| `METPO:2000027` | does not assimilate | 163,711 | OrganismTaxon → ChemicalEntity |

### METPO Phenotype Parent Classes

| METPO ID | Label | Usage |
|----------|-------|-------|
| `METPO:1000601` | oxygen preference | BacDive phenotype grouping |
| `METPO:1000870` | sporulation | BacDive phenotype grouping |
| `METPO:1000631` | trophic type | BacDive phenotype grouping |
| `METPO:1000666` | cell shape | BacDive phenotype grouping |
| `METPO:1000697` | gram stain | BacDive phenotype grouping |
| `METPO:1000701` | motility | BacDive phenotype grouping |
| `METPO:1000629` | halophily preference | BacDive phenotype grouping |
| `METPO:1001101` | biosafety level | BacDive phenotype grouping |
| `METPO:1004002` | animal pathogen | BacDive pathogenicity |
| `METPO:1004003` | plant pathogen | BacDive pathogenicity |
| `METPO:1004004` | human pathogen | BacDive pathogenicity |

---

## 4. Discrepancies and Issues

### 4.1 Category Issues

| Issue | Transform | Details | Severity | Recommendation |
|-------|-----------|---------|----------|----------------|
| Enzyme vs MolecularActivity | BacDive | EC numbers categorized as `biolink:Enzyme` (104 nodes) | Medium | Use `biolink:MolecularActivity` per Biolink spec |
| ChemicalSubstance usage | BacDive | 8 nodes as ChemicalSubstance vs ChemicalEntity | Low | Standardize to `biolink:ChemicalEntity` |
| Missing category for media | MediaDive | Media nodes use ChemicalEntity but should be ChemicalMixture | Medium | Consider `biolink:ChemicalMixture` for growth media |

### 4.2 Predicate Issues

| Issue | Transform | Current | Expected | Severity | Recommendation |
|-------|-----------|---------|----------|----------|----------------|
| Missing object nodes | BacDive | Some CHEBI:* objects not in nodes.tsv | - | Low | Ensure all ChEBI IDs have node entries |
| GO nodes as Enzyme | BacDive | GO:* objects with Enzyme category | - | Medium | GO terms should be BiologicalProcess or MolecularActivity |

**Note**: `biolink:capable_of` in madin_etal was initially flagged but upon investigation, the objects are `pathways:*` and `GO:*` nodes categorized as `biolink:BiologicalProcess`, which correctly matches the predicate's range specification.

### 4.3 Unmapped/Missing METPO Documentation

The following METPO predicates are heavily used but lack clear documentation in the codebase:

| METPO ID | Edge Count | Inferred Meaning |
|----------|------------|------------------|
| METPO:2000002 | 89,156 | Metabolite test result (unknown type) |
| METPO:2000003 | 104,968 | Metabolite test result (unknown type) |
| METPO:2000011 | 86,697 | Metabolite utilization (specific type) |
| METPO:2000012 | 69,004 | Metabolite utilization (specific type) |
| METPO:2000013 | 23,097 | Metabolite utilization (specific type) |
| METPO:2000039 | 51,581 | Metabolite test result (unknown type) |
| METPO:2000222 | 27,197 | Compound production (specific type) |

---

## 5. Recommendations

### High Priority

1. **Document METPO predicates**: Create a mapping table in constants.py or a separate file documenting all METPO predicates used and their semantics

2. **Standardize EC node category**: Ensure all EC numbers use `biolink:MolecularActivity` (already fixed in recent commit)

### Medium Priority

3. **Review METPO:2000302/2000303**: These represent positive/negative enzyme activity and connect to both EC: and GO: nodes. Consider whether GO terms should have different categories than EC numbers

4. **Add node entries for missing ChEBI**: Some edges reference CHEBI: IDs that don't have corresponding node entries

5. **Consider ChemicalMixture for media**: Growth media might be better categorized as `biolink:ChemicalMixture` than `biolink:ChemicalEntity`

### Low Priority

6. **Consolidate ChemicalSubstance/ChemicalEntity**: Standardize on `biolink:ChemicalEntity` across all transforms

7. **Add METPO ontology file**: Consider including METPO.owl or METPO.yaml in the repo for reference

---

## 6. Edge Patterns Summary

### BacDive Transform (3,266,437 total edges)

```
OrganismTaxon → ChemicalEntity:      ~1,900,000 edges (METPO metabolite predicates)
OrganismTaxon → Enzyme/GO:           ~830,000 edges (METPO:2000302/2000303)
OrganismTaxon → OrganismTaxon:       ~252,000 edges (subclass_of)
EnvironmentalFeature → OrganismTaxon: ~231,000 edges (location_of)
OrganismTaxon → PhenotypicQuality:   ~114,000 edges (has_phenotype)
OrganismTaxon → Medium:              ~37,000 edges (METPO:2000517)
```

### MediaDive Transform (144,475 total edges)

```
ChemicalMixture → ChemicalEntity:    ~85,500 edges (has_part)
NCBITaxon → Medium:                  ~55,000 edges (METPO:2000517)
Medium → MediumType:                 ~3,300 edges (subclass_of)
ChemicalEntity → ChemicalRole:       ~650 edges (has_chemical_role)
```

### madin_etal Transform (183,245 total edges)

```
OrganismTaxon → PhenotypicQuality:   ~112,000 edges (has_phenotype)
OrganismTaxon → ChemicalEntity:      ~37,000 edges (METPO:2000006)
EnvironmentalFeature → OrganismTaxon: ~27,000 edges (location_of)
OrganismTaxon → BiologicalProcess:   ~7,500 edges (capable_of)
```

### bactotraits Transform (90,769 total edges)

```
OrganismTaxon → PhenotypicQuality:   ~91,000 edges (has_phenotype)
```

---

## Appendix: Biolink Category Hierarchy

```
entity
└── named thing
    ├── biological entity
    │   ├── organism taxon
    │   └── biological process or activity
    │       ├── biological process
    │       └── molecular activity
    ├── chemical entity
    │   └── chemical mixture
    ├── attribute
    │   ├── organism attribute
    │   │   └── phenotypic quality
    │   └── chemical role
    └── planetary entity
        └── environmental feature
```
