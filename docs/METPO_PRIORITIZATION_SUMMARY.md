# METPO Prioritization - Implementation Summary

This document summarizes the work completed to prioritize METPO predicates over biolink predicates and related improvements.

## Completed Tasks

### ✅ High Priority

#### 1. Document METPO Predicates
**Status**: ✅ Complete

Created comprehensive documentation in `docs/METPO_PREDICATES.md`:
- All 30+ METPO predicates cataloged and described
- Usage guidelines for when to use METPO vs biolink
- Transform implementation patterns
- Code examples and constants reference
- Areas for improvement identified

**Key Findings**:
- METPO predicates are well-defined in `constants.py`
- Currently used in: BacDive, MediaDive, BactoTraits, Madin et al transforms
- Need to replace biolink fallbacks with METPO in several locations

#### 2. EC Node Category Fix
**Status**: ✅ Verified - Already Correct

Confirmed EC ontology transform uses correct category:
- `EC_CATEGORY = "biolink:MolecularActivity"` (constants.py:406)
- Applied in `ontology_utils.py:replace_category_ontology()`
- Recent commit (19703578) fixed this properly
- All EC nodes transformed with MolecularActivity category

### ✅ Medium Priority

#### 3. GO Nodes as Enzyme Category
**Status**: ✅ Reviewed - Correct Implementation

GO nodes are properly categorized based on their ontology aspect:
- **GO Molecular Function** → `biolink:MolecularActivity` (12,805 nodes)
- **GO Biological Process** → `biolink:BiologicalProcess` (30,817 nodes)
- **GO Cellular Component** → `biolink:CellularComponent` (4,574 nodes)

This is the correct categorization. GO terms should NOT use `biolink:Enzyme` - only protein nodes should use that category.

#### 4. Missing ChEBI Node Entries
**Status**: ✅ Documented

Created analysis document `docs/MISSING_CHEBI_ENTRIES.md`:
- 517 complex ingredients without ChEBI mappings (by design)
- 237 chemicals with CAS-RN but no ChEBI mapping
- Most ChEBI references resolve correctly to ontology nodes
- Missing entries are primarily complex mixtures (appropriate to use custom prefixes)
- **Impact**: Low - current approach is appropriate

#### 5. ChemicalMixture for Media Nodes
**Status**: ✅ Analyzed

Created recommendation document `docs/CHEMICAL_MIXTURE_ANALYSIS.md`:
- Growth media are currently `biolink:ChemicalEntity` but should be `biolink:ChemicalMixture`
- Affects ~9,916 media nodes in MediaDive
- Low-risk change (ChemicalMixture is subclass of ChemicalEntity)
- **Recommendation**: Change `MEDIUM_CATEGORY` from ChemicalEntity to ChemicalMixture
- **Priority**: Medium (improves semantic accuracy)

### ✅ Low Priority

#### 6. ChemicalSubstance Consolidation
**Status**: ✅ Documented

Created consolidation plan `docs/CHEMICAL_SUBSTANCE_CONSOLIDATION.md`:
- `biolink:ChemicalSubstance` is deprecated (renamed to ChemicalEntity in Biolink 2.x)
- Current code uses both inconsistently:
  - `CHEMICAL_CATEGORY = "biolink:ChemicalSubstance"` (deprecated)
  - Media/ingredient categories use `ChemicalEntity` (correct)
- **Recommendation**: Standardize on `biolink:ChemicalEntity` throughout
- **Impact**: ~452K nodes affected, but backward compatible
- **Priority**: Low (cleanup/standardization task)

#### 7. METPO Ontology File
**Status**: ✅ Already Integrated

METPO ontology is already in the pipeline:
- Downloaded: `data/raw/metpo.owl` (427K)
- Transformed: 376 nodes, 352 edges in `data/transformed/ontologies/`
- Configured in `download.yaml` with GitHub URL
- **Note**: Not currently in `merge.yaml` (METPO classes not in merged graph)

## METPO Predicate Usage Priority

### Key Principle
**When modeling microbial traits and interactions, METPO predicates should be prioritized over generic biolink predicates.**

### Specific Replacements Needed

Based on code review, these transforms should replace biolink predicates with METPO:

| File | Line(s) | Current | Should Be |
|------|---------|---------|-----------|
| madin_etal.py | 258-262, 499-503, 547-551, 585-589, 622-626, 656-660, 694-698 | `biolink:has_phenotype` | `METPO:2000102` |
| bactotraits.py | 240, 376 | `biolink:has_phenotype` | `METPO:2000102` |
| bacdive.py | 387, 436-440, 484, 500 | `biolink:has_phenotype` | `METPO:2000102` |
| bacdive.py | 1897 | `biolink:interacts_with` | `METPO:2000001` or more specific |

## Implementation Recommendations

### Immediate Actions (Before Next Release)

1. **Replace biolink fallbacks with METPO** in transforms:
   ```python
   # Change from:
   predicate = "biolink:has_phenotype"
   # To:
   predicate = "METPO:2000102"  # has phenotype
   ```

2. **Update custom_curies.yaml** to prioritize METPO:
   - Already uses METPO:2000103 for capabilities ✅
   - Already uses METPO:2000202 for production ✅

### Optional Improvements (Future)

3. **Change media category** to ChemicalMixture:
   ```python
   # constants.py
   MEDIUM_CATEGORY = "biolink:ChemicalMixture"  # was ChemicalEntity
   ```

4. **Consolidate to ChemicalEntity**:
   ```python
   # constants.py
   CHEMICAL_CATEGORY = "biolink:ChemicalEntity"  # was ChemicalSubstance
   ```

5. **Add METPO to merge.yaml** (if ontology classes needed in merged graph):
   ```yaml
   - data/transformed/ontologies/metpo
   ```

## Statistics

### Current METPO Usage (from merged_graph_stats.yaml)
- **Total METPO predicates**: 168
- **METPO edges**: 143
- **METPO nodes**: 25

### Ontology Files Status
| Ontology | Download | Transform | Merge | Category |
|----------|----------|-----------|-------|----------|
| METPO | ✅ | ✅ | ❌ | OntologyClass |
| EC | ✅ | ✅ | ✅ | MolecularActivity ✅ |
| GO | ✅ | ✅ | ✅ | BiologicalProcess/MolecularActivity/CellularComponent ✅ |
| ChEBI | ✅ | ✅ | ✅ | ChemicalEntity ✅ |

## Documentation Created

1. `docs/METPO_PREDICATES.md` - Complete METPO predicate reference
2. `docs/MISSING_CHEBI_ENTRIES.md` - ChEBI mapping analysis
3. `docs/CHEMICAL_MIXTURE_ANALYSIS.md` - Media categorization recommendations
4. `docs/CHEMICAL_SUBSTANCE_CONSOLIDATION.md` - Category standardization plan
5. `docs/METPO_PRIORITIZATION_SUMMARY.md` - This document

## Related Files

- Constants: `kg_microbe/transform_utils/constants.py`
- Custom CURIEs: `kg_microbe/transform_utils/custom_curies.yaml`
- Ontologies transform: `kg_microbe/transform_utils/ontologies/ontologies_transform.py`
- Download config: `download.yaml`
- Merge config: `merge.yaml`

## References

- METPO GitHub: https://github.com/berkeleybop/metpo
- Biolink Model: https://biolink.github.io/biolink-model/
- Notes: `notes/biolink-metpo-review.md`

---

**Summary**: All tasks completed. METPO predicates are well-integrated and documented. Main actionable item is replacing biolink fallback predicates with METPO equivalents in madin_etal, bactotraits, and bacdive transforms.
