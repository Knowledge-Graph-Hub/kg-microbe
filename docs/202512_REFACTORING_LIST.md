# 202512-release-fixes: Refactored Predicates and Categories

## Predicates Changed

### Organism Capabilities
```
BEFORE: biolink:capable_of
AFTER:  METPO:2000103 (capable of)

Applied to:
- NCBI_TO_PATHWAY_EDGE (organism → pathway)
- NCBI_TO_ENZYME_EDGE (organism → enzyme)
```

### Production Relationships
```
BEFORE: biolink:produces
AFTER:  METPO:2000202 (produces)

Applied to:
- Chemical production edges (antibiotic, alcohol, toxin, pigment production)
- 850 edges in Madin et al and BactoTraits via custom_curies.yaml
```

### Enzyme-Substrate Relationships
```
BEFORE: biolink:consumes (RO:0000056 - participates_in)
AFTER:  biolink:has_input (RO:0002233 - has_input)

Applied to:
- ENZYME_TO_SUBSTRATE_EDGE
```

---

## Categories Changed

### EC Nodes (Enzyme Classification)
```
BEFORE: biolink:Enzyme (incorrect - for proteins)
AFTER:  biolink:MolecularActivity (correct - for enzymatic activities)

Applied to:
- All EC ontology nodes
```

### Growth Media
```
BEFORE: biolink:ChemicalEntity (imprecise - single chemical)
AFTER:  METPO:1004005 (domain-specific - growth medium)

Applied to:
- MEDIUM_CATEGORY
- 3,317 media nodes from MediaDive (all with mediadive.medium: prefix)
- Note: BacDive references these media nodes but does not create its own
```

### Generic Chemicals
```
BEFORE: biolink:ChemicalSubstance (deprecated in Biolink 2.x)
AFTER:  biolink:ChemicalEntity (current standard)

Applied to:
- CHEMICAL_CATEGORY
- All generic chemical nodes
```

---

## CURIEs Standardized

### EC Identifiers
```
BEFORE: https://www.ebi.ac.uk/intenz/query?cmd=SearchEC&ec=1.1.1.1
AFTER:  EC:1.1.1.1

IRI field:
BEFORE: https://www.ebi.ac.uk/intenz/query?cmd=SearchEC&ec=1.1.1.1
AFTER:  https://enzyme.expasy.org/EC/1.1.1.1
```

---

## Constants Removed

### Dead Code
```
REMOVED: NCBI_TO_METABOLITE_UTILIZATION_EDGE (unused)
REMOVED: NCBI_TO_METABOLITE_PRODUCTION_EDGE (unused)
```

---

## Ontology Integration

### METPO Ontology
```
ADDED: data/transformed/ontologies/metpo_nodes.tsv (376 nodes)
ADDED: data/transformed/ontologies/metpo_edges.tsv (352 edges)
STATUS: Now included in merge.yaml
```

---

## Summary Table

| Type | Before | After | Count Affected |
|------|--------|-------|----------------|
| **Predicates** | | | |
| Organism→Pathway/Enzyme | `biolink:capable_of` | `METPO:2000103` | All capability edges |
| Production | `biolink:produces` | `METPO:2000202` | 850 edges |
| Enzyme→Substrate | `biolink:consumes` | `biolink:has_input` | All enzyme-substrate edges |
| **Categories** | | | |
| EC nodes | `biolink:Enzyme` | `biolink:MolecularActivity` | All EC nodes |
| Growth media | `biolink:ChemicalEntity` | `METPO:1004005` | 3,317 nodes |
| Generic chemicals | `biolink:ChemicalSubstance` | `biolink:ChemicalEntity` | All generic chemical nodes |
| **CURIEs** | | | |
| EC identifiers | IntEnz URLs | `EC:*` | All EC nodes |
| EC IRIs | IntEnz URLs | ExpaSy URLs | All EC nodes |
| **Ontologies** | | | |
| METPO in merge | ❌ Not included | ✅ Included | 376 nodes, 352 edges |
