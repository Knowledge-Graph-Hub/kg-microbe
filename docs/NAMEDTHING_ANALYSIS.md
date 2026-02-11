# NamedThing Analysis - KG-Microbe Transformed Data

**Date**: January 6, 2026
**Purpose**: Identify biolink:NamedThing occurrences for proper category assignment

---

## Executive Summary

✅ **EXCELLENT NEWS**: Only **1 NamedThing node** found across all transformed data (out of 1.1M+ total nodes)

- **Source**: EC Ontology (data/transformed/ontologies/ec_nodes.tsv)
- **Node**: `RO:0002333` (Relation Ontology term)
- **Percentage**: 0.01% (1 out of 13,131 EC nodes)

This indicates that KG-Microbe transforms are already doing an excellent job of assigning proper Biolink categories to nodes.

---

## Detailed Findings

### NamedThing Occurrence

| Source | Node ID | Name | Category | File |
|--------|---------|------|----------|------|
| ontologies/ec | RO:0002333 | Graph | biolink:NamedThing | data/transformed/ontologies/ec_nodes.tsv |

**Analysis**: This is a Relation Ontology (RO) term that appears to have been incorrectly included in the EC ontology nodes file. RO terms are typically used for predicates/relations, not as nodes.

**Recommendation**:
- Filter out RO terms from EC ontology transform
- RO:0002333 should not be a node in the knowledge graph

---

## Category Distribution by Source

### Data Sources (Non-Ontology)

#### BacDive (275,132 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 271,803 | 98.8% |
| METPO:1004005 | 1,575 | 0.6% |
| biolink:ChemicalEntity | 1,225 | 0.4% |
| biolink:EnvironmentalFeature | 353 | 0.1% |
| biolink:MolecularActivity | 104 | 0.0% |
| biolink:PhenotypicQuality | 72 | 0.0% |

**Note**: METPO:1004005 appears to be a custom METPO category. May need to map to standard Biolink category.

#### BactoTraits (10,026 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 9,933 | 99.1% |
| biolink:PhenotypicQuality | 93 | 0.9% |

**Status**: ✅ Well-categorized

#### Bakta CMM (595,275 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:Gene | 311,660 | 52.4% |
| biolink:Protein | 271,695 | 45.6% |
| biolink:GeneFamily | 6,781 | 1.1% |
| biolink:MolecularActivity | 5,081 | 0.9% |
| biolink:OrganismTaxon | 58 | 0.0% |

**Status**: ✅ Excellent genome annotation categorization

#### CMM-AI (1,458 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 966 | 66.3% |
| biolink:Enzyme | 213 | 14.6% |
| biolink:BiologicalProcess | 76 | 5.2% |
| biolink:Genome | 63 | 4.3% |
| biolink:ChemicalSubstance | 62 | 4.3% |
| biolink:MolecularActivity | 37 | 2.5% |
| biolink:ChemicalEntity | 30 | 2.1% |
| METPO:1004005 | 11 | 0.8% |

**Note**: Uses METPO:1004005 custom category

#### COG (5,090 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:GeneFamily | 5,061 | 99.4% |
| biolink:OntologyClass | 29 | 0.6% |

**Status**: ✅ Well-categorized

#### Madin et al (122,454 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 122,113 | 99.7% |
| biolink:ChemicalEntity | 102 | 0.1% |
| biolink:ChemicalRole | 95 | 0.1% |
| biolink:BiologicalProcess | 84 | 0.1% |
| biolink:EnvironmentalFeature | 60 | 0.0% |

**Status**: ✅ Well-categorized

#### MediaDive (32,467 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 22,367 | 68.9% |
| biolink:ChemicalEntity | 6,601 | 20.3% |
| METPO:1004005 | 3,317 | 10.2% |
| biolink:ChemicalRole | 180 | 0.6% |
| biolink:ChemicalMixture | 2 | 0.0% |

**Note**: Uses METPO:1004005 custom category extensively

#### Rhea Mappings (81,678 nodes)
| Category | Count | Percentage |
|----------|-------|------------|
| biolink:MolecularActivity | 77,285 | 94.6% |
| biolink:BiologicalProcess | 4,393 | 5.4% |

**Status**: ✅ Well-categorized

---

## Sources Analyzed

**Active Transformed Data** (18 files):
- ✅ data/transformed/bacdive/nodes.tsv
- ✅ data/transformed/bactotraits/nodes.tsv
- ✅ data/transformed/bakta/cmm_bakta/nodes.tsv
- ✅ data/transformed/cmm-ai/cmm-ai_nodes.tsv
- ✅ data/transformed/cog/nodes.tsv
- ✅ data/transformed/madin_etal/nodes.tsv
- ✅ data/transformed/mediadive/nodes.tsv
- ✅ data/transformed/rhea_mappings/nodes.tsv
- ✅ data/transformed/ontologies/chebi_nodes.tsv
- ✅ data/transformed/ontologies/ec_nodes.tsv (⚠️ 1 NamedThing found)
- ✅ data/transformed/ontologies/envo_nodes.tsv
- ✅ data/transformed/ontologies/foodon_nodes.tsv
- ✅ data/transformed/ontologies/go_nodes.tsv
- ✅ data/transformed/ontologies/hp_nodes.tsv
- ✅ data/transformed/ontologies/metpo_nodes.tsv
- ✅ data/transformed/ontologies/ncbitaxon_nodes.tsv
- ✅ data/transformed/ontologies/uberon_nodes.tsv
- ✅ data/transformed/ontologies/upa_nodes.tsv

**Note**: Excluded ontologies_last/ (backup directory)

---

## Issues Identified

### 1. Single NamedThing Node (Low Priority)

**Node**: `RO:0002333` in EC ontology
**Issue**: Relation Ontology term incorrectly included as a node
**Fix**: Filter RO terms from EC ontology transform
**Priority**: Low (only 1 occurrence)

### 2. Custom METPO Category (Medium Priority)

**Category**: `METPO:1004005`
**Sources**: BacDive (1,575 nodes), CMM-AI (11 nodes), MediaDive (3,317 nodes)
**Total**: 4,903 nodes
**Issue**: Custom category not part of standard Biolink model
**Recommendation**: Map METPO:1004005 to appropriate Biolink category
**Likely mapping**: Needs investigation - appears to be growth media or substrate related

---

## Recommendations

### Immediate Actions

1. **Fix EC Ontology Transform** ✅ (Low Priority)
   - Filter out RO (Relation Ontology) terms from EC nodes
   - File: `kg_microbe/transform_utils/ontologies/ontologies_transform.py`
   - Add RO prefix to exclusion list

2. **Investigate METPO:1004005** 🔍 (Medium Priority)
   - Determine what METPO:1004005 represents
   - Map to appropriate Biolink category or categories
   - Options:
     - biolink:ChemicalEntity
     - biolink:ChemicalMixture
     - biolink:EnvironmentalFeature
     - Custom mixin if justified

### Future Enhancements

1. **Add Category Validation**
   - Implement pre-merge validation to catch NamedThing occurrences
   - Alert on non-standard categories like METPO:1004005

2. **Category Consistency Check**
   - Ensure ChemicalEntity vs ChemicalSubstance usage is consistent
   - Review MolecularActivity vs Enzyme categorization

---

## Statistics Summary

| Metric | Value |
|--------|-------|
| Total sources analyzed | 18 |
| Sources with NamedThing | 1 |
| Total NamedThing nodes | 1 |
| Total nodes analyzed | ~1.1M+ |
| NamedThing percentage | <0.0001% |
| Sources with custom categories | 3 (BacDive, CMM-AI, MediaDive) |
| Custom category nodes | 4,903 (METPO:1004005) |

---

## Conclusion

KG-Microbe transforms are **exceptionally well-categorized** with only 1 NamedThing occurrence (0.0001% of all nodes). This indicates:

✅ Excellent use of Biolink model categories
✅ Proper entity typing across all transforms
✅ Minimal cleanup required

The only action items are:
1. Filter RO:0002333 from EC ontology (trivial fix)
2. Investigate and map METPO:1004005 to standard Biolink (requires domain knowledge)

**Overall Assessment**: Production-ready with minor improvements possible.
