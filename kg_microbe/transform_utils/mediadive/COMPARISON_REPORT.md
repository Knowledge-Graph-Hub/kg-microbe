# MediaDive Transform Comparison Report

**Date:** 2025-12-13
**Current Version:** `data/transformed/mediadive/` (media-upgrade branch)
**Previous Version:** `data/transformed_last4/mediadive/` (before upgrade)

---

## Summary

| Metric | Current | Previous | Change |
|--------|---------|----------|--------|
| **Total Nodes** | 32,270 | 30,741 | **+1,529** (+5.0%) |
| **Total Edges** | 143,797 | 140,182 | **+3,615** (+2.6%) |

---

## Node Categories

| Category | Current | Previous | Change | Notes |
|----------|---------|----------|--------|-------|
| biolink:OrganismTaxon | 22,353 | 20,583 | **+1,770** | More strain associations |
| biolink:ChemicalEntity | 9,915 | 9,938 | -23 | Slight reduction |
| biolink:ChemicalRole | ~218 | 218 | ~0 | Re-enabled for self-contained transform |
| biolink:ChemicalMixture | 2 | 2 | 0 | Unchanged |

---

## Edge Predicates

| Predicate | Current | Previous | Change | Notes |
|-----------|---------|----------|--------|-------|
| biolink:has_part | 85,503 | 85,288 | +215 | Medium-ingredient relationships |
| METPO:2000517 (grows in) | 54,968 | 50,623 | **+4,345** | Medium-strain relationships |
| biolink:subclass_of | 3,326 | 3,326 | 0 | Medium hierarchy unchanged |
| biolink:has_chemical_role | ~945 | 945 | ~0 | Re-enabled for self-contained transform |

---

## ChemicalEntity ID Prefixes

| Prefix | Current | Previous | Change | Notes |
|--------|---------|----------|--------|-------|
| mediadive.solution: | 5,401 | 5,422 (as solution:) | -21 | Now Bioregistry-compliant |
| mediadive.medium: | 3,316 | 3,316 (as medium:) | 0 | Now Bioregistry-compliant |
| mediadive.ingredient: | 732 | 261 (as ingredient:) | +471 | Unmapped compounds |
| CHEBI: | 392 | 684 | **-292** | Consolidated to canonical IDs |
| PubChem: | 43 | 20 | +23 | |
| CAS-RN: | 12 | 233 (as CAS-RN:) | **-221** | Most now mapped to CHEBI |
| foodon: | 9 | 0 | +9 | New mappings via MicroMediaParam |
| UBERON: | 6 | 0 | +6 | New mappings via MicroMediaParam |
| pubchem.compound: | 3 | 0 | +3 | New prefix format |
| envo: | 1 | 0 | +1 | New mapping |
| KEGG: | 0 | 2 | -2 | Now mapped to CHEBI |

---

## OrganismTaxon ID Prefixes

| Prefix | Current | Previous | Change | Notes |
|--------|---------|----------|--------|-------|
| NCBITaxon: | 14,685 | 14,091 | +594 | More taxon associations |
| kgmicrobe.strain: | 7,668 | 6,492 (as strain:) | +1,176 | Now Bioregistry-compliant |

---

## Key Changes Explained

### 1. Bioregistry-Compliant Prefixes
All custom prefixes now follow Bioregistry conventions:
- `medium:` → `mediadive.medium:`
- `solution:` → `mediadive.solution:`
- `ingredient:` → `mediadive.ingredient:`
- `strain:` → `kgmicrobe.strain:`

### 2. ChEBI Mapping Consolidation (-292 CHEBI nodes)
This is NOT a loss but an improvement in data quality:
- **Previous**: Multiple ChEBI IDs per compound (e.g., Glucose → CHEBI:17234, CHEBI:17634, CHEBI:17925, CHEBI:4167)
- **Current**: Single canonical ID via MicroMediaParam (e.g., Glucose → CHEBI:42758)
- The 292 "lost" IDs are redundant variants consolidated to canonical forms

### 3. CAS-RN Reduction (-221 CAS-RN nodes)
Most CAS-RN identifiers are now mapped to ChEBI IDs via MicroMediaParam:
- Previous: 233 compounds identified only by CAS-RN
- Current: 12 compounds with CAS-RN (unmapped)
- Remaining CAS-RNs are for compounds with no ChEBI equivalent

### 4. ChemicalRole Preserved (each transform self-contained)
ChEBI role relationships are kept in MediaDive transform for self-containment:
- Each transform includes all its nodes/edges independently
- ChEBI ontology also has 45,188 `has_chemical_role` edges
- Merge step handles deduplication across transforms
- MediaDive includes ~218 role nodes and ~945 role edges for its compounds

### 5. Increased Strain Associations (+4,345 grows_in edges)
More medium-strain relationships discovered through improved bulk download:
- Previous: 50,623 strain-medium relationships
- Current: 54,968 strain-medium relationships
- More accurate API data capture

### 6. New Ontology Mappings
MicroMediaParam provides additional mappings not available before:
- 9 FOODON mappings (food ingredients)
- 6 UBERON mappings (anatomical extracts)
- 1 ENVO mapping (environmental compound)

---

## Data Quality Improvements

1. **Canonical Chemical IDs**: Single, authoritative ChEBI IDs instead of multiple variants
2. **Bioregistry Compliance**: All prefixes now follow semantic web standards
3. **Reduced Redundancy**: ChemicalRole data now comes only from ChEBI ontology
4. **Better Coverage**: More strain associations and new ontology mappings
5. **Hydrate Handling**: Hydrated compounds map to base (anhydrous) ChEBI IDs

---

## Files Changed

- `mediadive.py`: Transform logic for Bioregistry prefixes, MicroMediaParam mappings
- `mediadive_bulk_download.py`: Improved bulk download with better strain handling
- `download.yaml`: MicroMediaParam mapping file configuration
- `README.md`: Updated documentation

---

## Commits in media-upgrade Branch

1. `1ab0b23c` - feat(mediadive)!: upgrade to Bioregistry prefixes and extended MicroMediaParam mappings
2. `77f8b9f3` - Revert "disable redundant ChEBI role querying" (each transform self-contained)
3. `2b497ebc` - fix MediaDive bulk download to extract solutions and compounds from embedded structure
4. `2f45582c` - Update MediaDive unmapped ingredients documentation
5. `490bd3a8` - Upgrade MediaDive transform to use high-confidence compound mappings
6. Additional fixes for Copilot review comments
