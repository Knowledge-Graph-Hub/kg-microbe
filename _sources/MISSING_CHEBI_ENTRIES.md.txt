# Missing ChEBI Node Entries

This document tracks chemicals and ingredients that lack ChEBI mappings in KG-Microbe.

## Overview

KG-Microbe integrates chemical data from multiple sources. While many chemicals are mapped to ChEBI (Chemical Entities of Biological Interest) ontology identifiers, some remain unmapped due to:

1. **Complex mixtures** (e.g., "meat extract", "brain heart infusion") that don't have single ChEBI IDs
2. **Proprietary formulations** (e.g., "trypticase", "bacto soytone")
3. **Chemicals with CAS Registry Numbers but no ChEBI mapping**
4. **Food/biological materials** (e.g., "tomato juice", "horse serum")

## Current Status

### Missing Chemical Entries

Two files track unmapped chemicals:

1. **`missing_chem.txt`** (517 entries)
   - Complex ingredients without ChEBI mappings
   - Primarily growth media components
   - Examples: meat extract, trypticase, beef extract, sea salt

2. **`missing_chem_casrn.txt`** (237 entries)
   - Chemicals identified by CAS Registry Numbers
   - Have chemical identifiers but lack ChEBI equivalents
   - Require manual mapping or ChEBI submission

### ChEBI References in Transforms

| Transform | ChEBI Edges | ChEBI Nodes | Notes |
|-----------|-------------|-------------|-------|
| BacDive | 1,575,321 | 1,176 | ChEBI as subjects in assay edges |
| MediaDive | 39,308 | 572 | Chemical role and composition edges |
| Ontologies (ChEBI) | - | ~200,000+ | Primary ChEBI node source |

## Impact

### Low Impact
- Most edges reference ChEBI IDs that **do** have corresponding nodes from the ChEBI ontology transform
- Missing entries are primarily:
  - Complex mixtures that cannot be represented as single ChEBI entities
  - Proprietary/commercial products without standardized chemical definitions
  - Items that should use alternative namespaces (e.g., `ingredient:*` for unnamed mixtures)

### Where It Matters
- **Growth media composition**: Some media ingredients lack standardized chemical identities
- **BacDive metabolite tests**: A few test substrates may lack ChEBI mappings
- **Cross-database integration**: Cannot link to external databases requiring ChEBI IDs

## Resolution Strategies

### 1. For Complex Mixtures
Use custom CURIE prefixes rather than forcing ChEBI mappings:
```
- ❌ Try to find ChEBI for "meat extract"
- ✅ Use ingredient:2 with biolink:ChemicalMixture category
```

### 2. For Chemicals with CAS-RN
Priority mapping workflow:
1. Query ChEBI API/database for CAS-RN
2. If found, add to mapping table
3. If not found, consider submitting to ChEBI
4. As fallback, use CAS-RN as identifier: `CAS:15548-61-5`

### 3. For Proprietary Products
Document composition when possible:
- Link to manufacturer data sheets
- Create node with descriptive name
- Use `biolink:ChemicalMixture` category
- Add `description` field with composition details

## Files Reference

### Missing Chemicals Files

**`missing_chem.txt`**
Format: `<prefix>:<id>\t<category>\t<name>\t...\t<source>`

Sample entries:
```
ingredient:2	biolink:ChemicalEntity	meat extract	Graph
ingredient:74	biolink:ChemicalEntity	trypticase	Graph
ingredient:85	biolink:ChemicalEntity	beef extract	Graph
```

**`missing_chem_casrn.txt`**
Format: `CAS-RN:<number>`

Sample entries:
```
CAS-RN:15548-61-5
CAS-RN:10025-84-0
CAS-RN:10028-22-5
```

### Transform Code References

- **MediaDive ChEBI loading**: `kg_microbe/transform_utils/mediadive/mediadive.py:126`
  - Method: `_load_chebi_roles()`
  - Silently skips if ChEBI role files missing

## Recommendations

### Immediate Actions
1. **No action required** for complex mixtures - current `ingredient:*` approach is appropriate
2. **Consider ChEBI API lookups** for the 237 CAS-RN entries in `missing_chem_casrn.txt`
3. **Document in user guide** that not all media ingredients have ChEBI mappings by design

### Future Enhancements
1. **Automated CAS-RN to ChEBI mapping script**
   - Query ChEBI API for each CAS-RN
   - Generate mapping table
   - Update transforms to use discovered ChEBI IDs

2. **Alternative ontologies**
   - FooDB for food components (tomato juice, etc.)
   - Consider FOODON (Food Ontology) for biological materials
   - ENVO for environmental samples

3. **Contribution to ChEBI**
   - Submit missing common chemicals to ChEBI
   - Particularly those with established CAS-RNs

## Notes from Code Review

From `notes/biolink-metpo-review.md`:
- **Issue**: Some CHEBI:* objects not in nodes.tsv (BacDive)
- **Severity**: Low
- **Recommendation**: Ensure all ChEBI IDs have node entries

**Status**: Upon investigation, this is not a significant issue because:
- ChEBI nodes come from ontologies transform
- BacDive creates 1,176 specialized ChEBI nodes for metabolites
- Most ChEBI references resolve to nodes from the merged ChEBI ontology
- Unmapped items are predominantly complex mixtures that shouldn't have ChEBI IDs

## Related Documentation

- ChEBI Ontology: https://www.ebi.ac.uk/chebi/
- ChEBI xrefs: `kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv`
- Constants: `kg_microbe/transform_utils/constants.py` (ChEBI-related constants)
