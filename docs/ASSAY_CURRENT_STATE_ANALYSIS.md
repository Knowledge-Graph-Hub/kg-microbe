# Current State Analysis: Assay Nodes and Deprecated Predicates

**Date**: 2026-01-12
**Analyzed Release**: `data/merged/20251217/`
**Status**: FINDINGS

---

## Executive Summary

The current KG-Microbe release (20251217) contains:
- ✅ **349 assay nodes** already exist (as `biolink:NamedThing`)
- ⚠️ **112 edges** using deprecated `biolink:is_assessed_by` predicate
- ❌ **0 organism→assay edges** (organisms link directly to GO/EC/ChEBI)
- ⚠️ **237 orphaned assay nodes** (not connected to any edges)
- ❌ **0 edges** using `biolink:assesses` predicate

**Conclusion**: Assay nodes exist but are incomplete, outdated, and only used for EC→assay methodological references. Organisms are NOT currently linked through assay nodes.

---

## Detailed Findings

### 1. Existing Assay Nodes

**Count**: 349 nodes with `assay:` prefix

**Structure**:
```tsv
id: assay:API_zym_Trypsin
category: biolink:NamedThing
name: (empty)
description: (empty)
provided_by: Graph
```

**Issues**:
- ❌ Categorized as `biolink:NamedThing` (not `biolink:Procedure`)
- ❌ No name or description
- ❌ No metadata (kit_name, well_name, test_type)
- ❌ Incomplete coverage (349 vs. 503 wells in new metadata)
- ❌ Missing entire kits (e.g., API biotype100 with 99 growth tests)

**Distribution by Kit**:
```
API 50CHas:    49 nodes
API ID32E:     31 nodes
API rID32STR:  29 nodes
API rID32A:    27 nodes
API ID32STA:   26 nodes
API 20E:       24 nodes
API 20NE:      21 nodes
API 20A:       21 nodes
API coryne:    20 nodes
API STA:       20 nodes
API CAM:       20 nodes
API 20STR:     20 nodes
API zym:       19 nodes  ⚠️ (Missing 1 well - should be 20)
API NH:        13 nodes
API LIST:       9 nodes
---
Total:        349 nodes

MISSING KITS:
- API 50CHac (49 wells) - Fermentation tests
- API biotype100 (99 wells) - GROWTH TESTS ⚠️
- API rID32A (additional wells?)
```

**Discrepancy**: Current release has "50CHas" but new metadata has "50CHac" (likely different versions)

### 2. Deprecated Predicate Usage

#### `biolink:is_assessed_by` (DEPRECATED in Biolink v4.3.3)

**Count**: 112 edges
**Pattern**: EC enzyme → assay node
**Source**: `bacdive_mappings.tsv`

**Example Edges**:
```tsv
subject: EC:4.1.99.1
predicate: biolink:is_assessed_by
object: assay:API_20A_IND
relation: NCIT:C153110 (assessed_activity)
knowledge_source: bacdive_mappings.tsv
```

**Purpose**: Methodological reference showing which API kit tests can detect which enzymes

**Connected Assay Nodes**: Only 112 out of 349 assay nodes are used in these edges

**Orphaned Nodes**: 237 assay nodes exist but have no incoming or outgoing edges

#### `biolink:assesses` (DEPRECATED in Biolink v4.3.3)

**Count**: 0 edges
**Status**: Never used in this release

### 3. Current Organism Relationships

**Pattern**: Organisms link DIRECTLY to GO/EC/ChEBI entities (NOT through assay nodes)

**Example Edges**:
```tsv
# Organism → ChEBI (chemical metabolism)
subject: NCBITaxon:693023
predicate: METPO:2000006
object: CHEBI:17992
relation: RO:0002215 (capable of)

# Organism → GO (enzyme activity)
subject: NCBITaxon:28448
predicate: METPO:2000103
object: GO:0030245
relation: RO:0002215 (capable of)
```

**Top METPO Predicates Used**:
```
METPO:2000006  -  36,817 edges  (unknown label - likely metabolizes)
METPO:2000517  -  30,031 edges  (unknown label)
METPO:2000103  -   7,495 edges  (capable of - enzyme activity)
```

**Note**: These are the predicates currently in use. Need to check if these include the API kit-specific predicates we identified:
- METPO:2000302 (shows activity of)
- METPO:2000303 (does not show activity of)
- METPO:2000011 (ferments)
- METPO:2000037 (does not ferment)
- METPO:2000008 (assimilates)
- METPO:2000034 (does not assimilate)
- METPO:2000012 (uses for growth)
- METPO:2000038 (does not use for growth)

### 4. Graph Statistics

**File**: `data/merged/20251217/merged-kg_edges.tsv`
- Size: 666 MB
- Total edges: ~10-15 million (estimated)

**File**: `data/merged/20251217/merged-kg_nodes.tsv`
- Size: 258 MB
- Total nodes: ~2-3 million (estimated)

**Organism Edges**:
```
biolink:subclass_of:    882,486 edges  (taxonomy hierarchy)
biolink:has_phenotype:  193,603 edges  (phenotypic traits)
METPO:2000006:           36,817 edges  (metabolic traits)
METPO:2000517:           30,031 edges  (trait type TBD)
METPO:2000103:            7,495 edges  (enzyme capabilities)
biolink:location_of:        624 edges  (isolation sources)
```

---

## Comparison: Current vs. Proposed

| Aspect | Current State (20251217) | Proposed State |
|--------|-------------------------|----------------|
| **Assay Nodes** | 349 nodes | 503 nodes |
| **Node Category** | `biolink:NamedThing` | `biolink:Procedure` |
| **Node Metadata** | None (empty name/description) | Rich (name, description, kit_name, well_name, test_type) |
| **Organism→Assay** | 0 edges | ~50,000-100,000 edges (per organism) |
| **Assay→Entity** | 0 edges | ~600-800 edges (methodological) |
| **EC→Assay** | 112 edges (`is_assessed_by`) | 0 edges (removed deprecated predicate) |
| **Organism→Entity** | Direct edges (~74,343 METPO edges) | Indirect via assay (2-hop path) |
| **Deprecated Predicates** | ⚠️ `is_assessed_by` used (112 edges) | ✅ None (replaced with `related_to_at_instance_level`) |
| **Kit Coverage** | 15 kits (missing biotype100, 50CHac) | 17 kits (complete) |
| **Growth Tests** | ❌ Missing | ✅ Included (API biotype100) |

---

## Impact Analysis

### What Needs to Change

1. **Replace 349 outdated assay nodes with 503 new nodes**
   - Add missing kits (biotype100, updated 50CHac)
   - Change category from `NamedThing` to `Procedure`
   - Add rich metadata (name, description, kit_name, well_name, test_type)

2. **Remove 112 EC→assay edges using deprecated `is_assessed_by`**
   - Already documented as replaced with `related_to_at_instance_level`
   - See: `BIOLINK_PREDICATE_CHANGES.md` (line 240-280)

3. **Add ~50,000-100,000 organism→assay edges**
   - NEW: Organisms will link to assay nodes (not directly to GO/EC/ChEBI)
   - Use METPO predicates from assay metadata
   - Creates 2-hop path: Organism → Assay → Entity

4. **Add ~600-800 assay→entity edges**
   - NEW: Methodological reference edges
   - Enzyme assays → GO/EC (`has_output`)
   - Chemical assays → ChEBI (`has_input`)

5. **Preserve ~74,343 existing direct organism→entity edges?**
   - ✅ **DECISION: KEEP** - Use dual-edge pattern (direct + 2-hop)
   - Direct edges: Capture biological facts for simple queries
   - 2-hop via assay: Capture methodology and experimental provenance
   - Benefits: Users can choose query complexity based on needs

---

## Current Data Source: bacdive_mappings.tsv

The 349 existing assay nodes and 112 EC→assay edges come from:
- **File**: `bacdive_mappings.tsv`
- **Location**: Referenced in edge metadata as knowledge source
- **Status**: Appears to be outdated/incomplete compared to new assay metadata
- **Coverage**: Only enzyme tests (EC→assay), no chemical/growth tests

**New Data Source**: `assay_kits_simple.json`
- **URL**: https://raw.githubusercontent.com/CultureBotAI/assay-metadata/refs/heads/main/data/assay_kits_simple.json
- **Coverage**: Complete 503 wells across 17 kits
- **Metadata**: Rich information (descriptions, GO terms, EC numbers, ChEBI IDs, METPO predicates)

---

## Backward Compatibility Considerations

### Breaking Changes

1. **Assay node IDs may change**
   - Old: `assay:API_zym_Trypsin`
   - New: `assay:API_zym_trypsin` (normalized?)
   - Impact: External references to old IDs will break

2. **Assay node category changes**
   - Old: `biolink:NamedThing`
   - New: `biolink:Procedure`
   - Impact: Queries filtering by category will need updates

3. **Removal of `is_assessed_by` edges**
   - Old: 112 EC→assay edges with `is_assessed_by`
   - New: 0 edges (deprecated predicate removed)
   - Impact: Any queries using this predicate will return no results

### Non-Breaking Additions

1. **New organism→assay edges**
   - No existing edges to replace
   - Pure addition (~50,000-100,000 new edges)

2. **New assay→entity edges**
   - No existing edges to replace
   - Pure addition (~600-800 new edges)

3. **New assay nodes for missing kits**
   - Adding biotype100 (99 nodes), 50CHac updates
   - Pure addition (154 new nodes)

---

## Migration Strategy

### Option A: Clean Break (Recommended)

1. Remove all 349 old assay nodes
2. Remove all 112 `is_assessed_by` edges
3. Add 503 new assay nodes with rich metadata
4. Add organism→assay edges (new)
5. Add assay→entity edges (new)
6. **Decision**: Remove or keep direct organism→entity edges?

**Pros**: Clean, compliant with Biolink v4.3.6, no deprecated predicates
**Cons**: Breaking change for any external tools using old assay nodes

### Option B: Gradual Migration

1. Keep old 349 assay nodes
2. Add 503 new assay nodes (with different IDs?)
3. Mark old nodes as deprecated
4. Add new edges alongside old edges
5. Deprecation period (1-2 releases)
6. Remove old nodes in future release

**Pros**: Backward compatible, gives users time to migrate
**Cons**: Redundant data, confusion about which nodes to use

---

## Recommendations

1. **Use Clean Break for Assay Nodes**
   - Biolink v4.3.6 deprecation is already 1+ year old
   - Current assay nodes are incomplete/orphaned anyway
   - Better to fix comprehensively now

2. **✅ APPROVED: Keep Direct Organism→Entity Edges (Dual-Edge Pattern)**
   - Maintain all direct organism→entity edges
   - Add organism→assay edges (NEW)
   - Add assay→entity edges (NEW)
   - Result: Both direct paths AND 2-hop paths via assay nodes
   - **Benefits**:
     - Direct edges: Simple queries for biological facts
     - Assay paths: Rich methodology and provenance information
     - Users choose query complexity based on needs
     - Backward compatible with existing queries

3. **Document migration in release notes**
   - List breaking changes
   - Provide migration guide for common queries
   - Include examples of old vs. new query patterns

4. **Add assay node validation tests**
   - Ensure all 503 nodes created
   - Ensure no deprecated predicates used
   - Ensure category is `Procedure`
   - Ensure metadata is complete

---

## Example Migration: Query Patterns

### Old Query (Direct Edges)
```sparql
# Find organisms that can perform alkaline phosphatase activity
SELECT ?organism ?name
WHERE {
  ?organism METPO:2000103 GO:0004035 .
  ?organism rdfs:label ?name .
}
```

### New Query (2-Hop via Assay)
```sparql
# Find organisms that show alkaline phosphatase activity via assay
SELECT ?organism ?name ?assay
WHERE {
  ?organism METPO:2000302 ?assay .  # shows activity of (via assay)
  ?assay biolink:has_output GO:0004035 .  # assay detects this enzyme
  ?organism rdfs:label ?name .
}
```

### Alternative: If Keeping Direct Edges
```sparql
# Find organisms with alkaline phosphatase (either direct or via assay)
SELECT ?organism ?name
WHERE {
  ?organism rdfs:label ?name .
  {
    # Direct edge (old pattern)
    ?organism METPO:2000103 GO:0004035 .
  } UNION {
    # Via assay (new pattern)
    ?organism METPO:2000302 ?assay .
    ?assay biolink:has_output GO:0004035 .
  }
}
```

---

## Next Steps

1. ✅ **APPROVED: Dual-edge pattern** (direct + 2-hop via assay)
2. ✅ **APPROVED: Keep direct organism→entity edges**
3. **Implement assay node generation** (as per implementation plan)
4. **Update BacDive transform** to ADD organism→assay edges (keep existing direct edges)
5. **Add validation tests**
6. **Run test transform** on subset of data
7. **Review sample output** before full transform
8. **Document migration** for users
9. **Run full transform**
10. **Validate against Biolink v4.3.6 schema**

---

## Files to Reference

- Current release: `data/merged/20251217/merged-kg_*.tsv`
- Proposal: `docs/ASSAY_NODE_MODELING.md`
- Implementation: `docs/ASSAY_IMPLEMENTATION_SUMMARY.md`
- Biolink changes: `BIOLINK_PREDICATE_CHANGES.md`
- Code: `kg_microbe/transform_utils/bacdive/bacdive.py` (lines 2315-2435)

---

**Analysis Date**: 2026-01-12
**Analyst**: Claude Code
