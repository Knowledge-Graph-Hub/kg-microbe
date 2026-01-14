# Schema Compliance Analysis - Node and Edge Properties

**Date**: January 6, 2026
**Purpose**: Identify misuse of node properties in edges and edge properties in nodes

---

## Executive Summary

✅ **EXCELLENT COMPLIANCE**: Zero schema violations found!

- **Edge properties in nodes**: Present as headers but NEVER populated (0/8 sources)
- **Node properties in edges**: Not present at all
- **Overall assessment**: Production-ready schema compliance

---

## Findings

### Part 1: Edge Properties in Nodes Files

**Result**: ✅ **NO VIOLATIONS**

While nodes.tsv files have edge property columns in their headers (`subject`, `predicate`, `object`, `relation`), these columns are **NEVER populated with data** across all 8 sources analyzed.

**Analysis**:
- Edge columns present in node headers: 4 (`subject`, `predicate`, `object`, `relation`)
- Sources with data in edge columns: **0 out of 8** ✅
- This is due to the base `Transform` class including all columns in `node_header` for compatibility
- No actual schema violation since columns are empty

### Part 2: Node Properties in Edges Files

**Result**: ✅ **NO VIOLATIONS**

Edges.tsv files contain only the 5 required edge properties and nothing else.

**Analysis**:
- Node-specific columns found in edge files: **0**
- All edge files use exactly 5 standard columns
- Perfect schema compliance

---

## Detailed Column Usage Analysis

### Nodes Files (nodes.tsv)

**Standard Node Schema**:
```
Required: id, category, name
Optional: description, xref, provided_by, synonym, iri, same_as, subsets
```

#### Column Usage Summary (8 sources analyzed)

| Column | Present | Populated | Usage | Status |
|--------|---------|-----------|-------|--------|
| **id** | 8/8 | 8/8 | 100% | ✅ Required |
| **category** | 8/8 | 8/8 | 100% | ✅ Required |
| **name** | 8/8 | 8/8 | 100% | ✅ Required |
| **description** | 8/8 | 2/8 | 25% | ⚪ Optional, underutilized |
| **xref** | 8/8 | 2/8 | 25% | ⚪ Optional, underutilized |
| **provided_by** | 8/8 | 3/8 | 38% | ⚪ Optional |
| **synonym** | 8/8 | 0/8 | 0% | ⚠️ Unused |
| **iri** | 8/8 | 0/8 | 0% | ⚠️ Unused |
| **same_as** | 8/8 | 0/8 | 0% | ⚠️ Unused |
| **subsets** | 8/8 | 0/8 | 0% | ⚠️ Unused |
| **subject** | 8/8 | 0/8 | 0% | ✅ Edge property, correctly unused |
| **predicate** | 8/8 | 0/8 | 0% | ✅ Edge property, correctly unused |
| **object** | 8/8 | 0/8 | 0% | ✅ Edge property, correctly unused |
| **relation** | 8/8 | 0/8 | 0% | ✅ Edge property, correctly unused |

#### Sources Using Description
- bakta_cmm
- cog

#### Sources Using Xref
- bakta_cmm
- cmm-ai

#### Sources Using Provided_by
- bakta_cmm
- cmm-ai
- cog

### Edges Files (edges.tsv)

**Standard Edge Schema**:
```
Required: subject, predicate, object, relation, primary_knowledge_source
```

#### Column Usage Summary (8 sources analyzed)

| Column | Present | Populated | Usage | Status |
|--------|---------|-----------|-------|--------|
| **subject** | 8/8 | 8/8 | 100% | ✅ Required |
| **predicate** | 8/8 | 8/8 | 100% | ✅ Required |
| **object** | 8/8 | 8/8 | 100% | ✅ Required |
| **relation** | 8/8 | 8/8 | 100% | ✅ Required |
| **primary_knowledge_source** | 8/8 | 8/8 | 100% | ✅ Required |

**Perfect compliance**: All edge files use exactly the 5 required columns with 100% population.

---

## Sources Analyzed

### Data Sources (8 total)

1. **bacdive**
   - Nodes: data/transformed/bacdive/nodes.tsv
   - Edges: data/transformed/bacdive/edges.tsv

2. **bactotraits**
   - Nodes: data/transformed/bactotraits/nodes.tsv
   - Edges: data/transformed/bactotraits/edges.tsv

3. **bakta_cmm**
   - Nodes: data/transformed/bakta/cmm_bakta/nodes.tsv
   - Edges: data/transformed/bakta/cmm_bakta/edges.tsv

4. **cmm-ai**
   - Nodes: data/transformed/cmm-ai/cmm-ai_nodes.tsv
   - Edges: data/transformed/cmm-ai/cmm-ai_edges.tsv

5. **cog**
   - Nodes: data/transformed/cog/nodes.tsv
   - Edges: data/transformed/cog/edges.tsv

6. **madin_etal**
   - Nodes: data/transformed/madin_etal/nodes.tsv
   - Edges: data/transformed/madin_etal/edges.tsv

7. **mediadive**
   - Nodes: data/transformed/mediadive/nodes.tsv
   - Edges: data/transformed/mediadive/edges.tsv

8. **rhea_mappings**
   - Nodes: data/transformed/rhea_mappings/nodes.tsv
   - Edges: data/transformed/rhea_mappings/edges.tsv

**Note**: Ontology files (chebi, ec, envo, foodon, go, hp, metpo, ncbitaxon, uberon, upa) follow the same schema patterns and were verified separately.

---

## Issues and Recommendations

### 🟡 Minor Issues (Non-Violations)

#### 1. Unused Node Columns

**Columns**: `synonym`, `iri`, `same_as`, `subsets`

**Status**: Present in all node files but never populated (0/8 sources)

**Impact**: Low - adds ~4 empty columns to every nodes.tsv file

**Recommendation**:
- **Option A**: Remove from `node_header` in base `Transform` class to reduce file size
- **Option B**: Keep for future use if these properties will be added later
- **Current**: No action needed - doesn't affect functionality

#### 2. Underutilized Node Columns

**Columns**: `description` (25% usage), `xref` (25% usage), `provided_by` (38% usage)

**Status**: Useful metadata that some transforms use, others don't

**Recommendation**:
- Encourage more transforms to populate `description` for better node understanding
- Add `xref` cross-references where available (especially for chemical and biological entities)
- Use `provided_by` to track provenance

---

## Best Practices Observed

### ✅ Edges Schema Compliance

All edge files demonstrate perfect schema compliance:
- Exactly 5 columns (no more, no less)
- All columns always populated
- Consistent across all 8 sources
- **Recommendation**: Use as template for future transforms

### ✅ Nodes Schema Compliance

All node files correctly:
- Always populate required fields (id, category, name)
- Never populate edge property columns (subject, predicate, object, relation)
- Use optional fields appropriately (description, xref, provided_by)

---

## Technical Details

### Base Transform Class Schema

From `kg_microbe/transform_utils/transform.py`:

```python
self.node_header = [
    ID_COLUMN,              # ✅ Always used
    CATEGORY_COLUMN,        # ✅ Always used
    NAME_COLUMN,            # ✅ Always used
    DESCRIPTION_COLUMN,     # ⚪ Sometimes used (2/8)
    XREF_COLUMN,            # ⚪ Sometimes used (2/8)
    PROVIDED_BY_COLUMN,     # ⚪ Sometimes used (3/8)
    SYNONYM_COLUMN,         # ⚠️ Never used (0/8)
    IRI_COLUMN,             # ⚠️ Never used (0/8)
    OBJECT_COLUMN,          # ✅ Correctly unused (edge property)
    PREDICATE_COLUMN,       # ✅ Correctly unused (edge property)
    RELATION_COLUMN,        # ✅ Correctly unused (edge property)
    SAME_AS_COLUMN,         # ⚠️ Never used (0/8)
    SUBJECT_COLUMN,         # ✅ Correctly unused (edge property)
    SUBSETS_COLUMN,         # ⚠️ Never used (0/8)
]

self.edge_header = [
    SUBJECT_COLUMN,                    # ✅ Always used
    PREDICATE_COLUMN,                  # ✅ Always used
    OBJECT_COLUMN,                     # ✅ Always used
    RELATION_COLUMN,                   # ✅ Always used
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,   # ✅ Always used
]
```

### Why Edge Columns Are in Node Header

The base `Transform` class includes edge columns in `node_header` for compatibility and future extensibility. However:
- ✅ **Good**: Allows framework flexibility
- ✅ **Good**: Transforms never actually populate these columns
- ⚪ **Neutral**: Adds ~4 empty columns to nodes files
- ✅ **Good**: KGX merge process ignores empty columns

---

## Validation Methodology

### Step 1: Schema Definition
- Defined standard node-only properties: id, category, name, description, xref, provided_by, synonym, iri, same_as, subsets
- Defined standard edge-only properties: subject, predicate, object, relation, primary_knowledge_source

### Step 2: Violation Detection
- Checked all nodes.tsv files for populated edge properties
- Checked all edges.tsv files for node properties (excluding 'id' which can be edge_id)

### Step 3: Usage Analysis
- Analyzed column presence across all files
- Analyzed column population (empty vs populated)
- Identified usage patterns and best practices

---

## Conclusion

**Overall Assessment**: ✅ **EXCELLENT SCHEMA COMPLIANCE**

KG-Microbe demonstrates excellent schema compliance with:
- ✅ Zero violations of node/edge property separation
- ✅ Perfect edge file schema (5 columns, all required)
- ✅ Consistent node file schema across all sources
- ⚪ Minor optimization opportunity: remove unused columns from node_header

**No action required** - the current implementation is production-ready and follows best practices.

### Compliance Score: 10/10

| Criteria | Score | Notes |
|----------|-------|-------|
| Edge properties not in nodes | 10/10 | Perfect - 0 violations |
| Node properties not in edges | 10/10 | Perfect - not present |
| Required fields populated | 10/10 | id, category, name always populated |
| Schema consistency | 10/10 | All files follow same pattern |
| KGX compatibility | 10/10 | Fully compatible with KGX merge |

---

## Appendix: Column Definitions

### Node Columns (KGX Standard)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| id | string | ✅ Yes | Unique CURIE identifier |
| category | string | ✅ Yes | Biolink category (e.g., biolink:Gene) |
| name | string | ✅ Yes | Human-readable label |
| description | string | ⚪ Optional | Detailed description of entity |
| xref | string | ⚪ Optional | Cross-references (pipe-separated) |
| provided_by | string | ⚪ Optional | Source/provenance information |
| synonym | string | ⚪ Optional | Alternative names (pipe-separated) |
| iri | string | ⚪ Optional | IRI/URL for the entity |
| same_as | string | ⚪ Optional | Equivalent entity identifiers |
| subsets | string | ⚪ Optional | Ontology subsets/slims |

### Edge Columns (KGX Standard)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| subject | string | ✅ Yes | Subject node CURIE |
| predicate | string | ✅ Yes | Biolink predicate (e.g., biolink:related_to) |
| object | string | ✅ Yes | Object node CURIE |
| relation | string | ✅ Yes | RO or other ontology relation |
| primary_knowledge_source | string | ✅ Yes | Source provenance (e.g., infores:bacdive) |

---

**Generated**: January 6, 2026
**Tool**: Claude Code
**Repository**: kg-microbe
