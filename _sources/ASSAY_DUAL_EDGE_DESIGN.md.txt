# Dual-Edge Design for API Kit Assays

**Date**: 2026-01-12
**Status**: ✅ APPROVED
**Decision**: Keep both direct organism→entity edges AND add 2-hop paths via assay nodes

---

## Design Decision

We will implement a **dual-edge pattern** that maintains both:

1. **Direct edges**: Organism → GO/EC/ChEBI (biological facts)
2. **Two-hop paths**: Organism → Assay → GO/EC/ChEBI (methodology + provenance)

This is the original design from the 20250222 release, which we are now modernizing with:
- ✅ Proper assay nodes (503 nodes with rich metadata)
- ✅ Correct categories (`biolink:Procedure`)
- ✅ No deprecated predicates
- ✅ Full API kit-specific METPO predicates (8 types)

---

## Graph Structure

### Complete Pattern

```
# Direct edge (biological fact)
NCBITaxon:562 --METPO:2000302 (shows activity of)--> GO:0004035 (alkaline phosphatase activity)

# Two-hop path (methodology + provenance)
NCBITaxon:562 --METPO:2000302 (shows activity of)--> assay:API_zym_alkaline_phosphatase
assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035 (alkaline phosphatase activity)
```

### Visual Representation

```
                    ┌─────────────────────────────────────────────┐
                    │                                             │
                    │        Direct Edge (biological fact)        │
                    │                                             │
    NCBITaxon:562 ──┼────────── METPO:2000302 ──────────────────►│──► GO:0004035
         │          │                                             │       │
         │          └─────────────────────────────────────────────┘       │
         │                                                                 │
         │                                                                 │
         └────── METPO:2000302 ─────► assay:API_zym_alkaline_phosphatase │
                                               │                          │
                                               │                          │
                                               └───── biolink:has_output ─┘

                                      Two-hop path (with methodology)
```

---

## Rationale

### Why Keep Both Patterns?

1. **Query Simplicity vs. Detail**
   - Simple queries: Use direct edges
   - Detailed queries: Use 2-hop paths to see methodology

2. **Different Use Cases**
   - **Biologists**: "Which organisms have this enzyme?" → Direct edges
   - **Data curators**: "Which assay detected this?" → 2-hop paths
   - **Tool developers**: "What's the experimental basis?" → 2-hop paths

3. **Backward Compatibility**
   - Existing queries continue to work
   - No breaking changes to API
   - Users can migrate gradually

4. **Original Design Intent**
   - This was the pattern in 20250222 (though with wrong predicates)
   - We're modernizing, not redesigning from scratch
   - Captures both biological facts AND experimental methodology

---

## Benefits of Dual-Edge Pattern

### For Direct Edges

✅ **Fast queries**: Single hop to answer "what enzymes does this organism have?"
✅ **Simple SPARQL**: No joins needed for basic biological questions
✅ **Backward compatible**: Existing queries continue working
✅ **Semantic clarity**: Direct statement of biological capability

**Example query**:
```sparql
# Simple: Find all organisms with alkaline phosphatase activity
SELECT ?organism ?name
WHERE {
  ?organism METPO:2000302 GO:0004035 .
  ?organism rdfs:label ?name .
}
```

### For Two-Hop Paths

✅ **Methodology capture**: Know which specific assay was used
✅ **Provenance tracking**: Trace back to experimental method
✅ **Data quality**: Assess reliability based on assay type
✅ **Granular queries**: Filter by specific API kit tests

**Example query**:
```sparql
# Detailed: Find organisms tested with API zym kit
SELECT ?organism ?assay ?enzyme
WHERE {
  ?organism METPO:2000302 ?assay .
  ?assay kit_name "API zym" .
  ?assay biolink:has_output ?enzyme .
}
```

### For Combined Analysis

✅ **Cross-validation**: Compare results across different assays
✅ **Method comparison**: See if different assays give same results
✅ **Data reconciliation**: Identify discrepancies between direct and assay-based assertions

**Example query**:
```sparql
# Advanced: Find cases where organism has enzyme but no assay evidence
SELECT ?organism ?enzyme
WHERE {
  # Has direct assertion
  ?organism METPO:2000302 ?enzyme .

  # But no assay path
  FILTER NOT EXISTS {
    ?organism METPO:2000302 ?assay .
    ?assay biolink:has_output ?enzyme .
  }
}
```

---

## Edge Counts

| Edge Type | Pattern | Count | Purpose |
|-----------|---------|-------|---------|
| **Direct** | Organism → GO/EC/ChEBI | ~74,000 | Biological facts |
| **Organism→Assay** | Organism → Assay | ~50,000-100,000 | Test outcomes |
| **Assay→Entity** | Assay → GO/EC/ChEBI | ~600-800 | Methodology |

**Total edges**: ~124,600 - 174,800 (existing + new)

**Storage impact**:
- Direct edges: Already exist (~74K)
- New edges: ~50K-100K organism→assay + ~600-800 assay→entity
- Net addition: ~50K-101K edges (minimal compared to ~10M total graph edges)

---

## Implementation Details

### For Enzyme Tests

```python
# Process GO terms
for go_term in go_terms:
    # EXISTING: Direct organism → GO edge (KEEP THIS)
    edge_writer.writerow([
        organism_id,
        metpo_predicate,  # e.g., METPO:2000302
        go_term,          # e.g., GO:0004035
        CAPABLE_OF,       # RO:0002215
        knowledge_source,
        ...
    ])

# NEW: Add organism → assay edge
edge_writer.writerow([
    organism_id,
    metpo_predicate,      # Same METPO predicate
    assay_id,             # e.g., assay:API_zym_alkaline_phosphatase
    CAPABLE_OF,
    knowledge_source,
    ...
])

# UPFRONT: Assay → GO edge (created once at start)
edge_writer.writerow([
    assay_id,             # e.g., assay:API_zym_alkaline_phosphatase
    "biolink:has_output",
    go_term,              # e.g., GO:0004035
    "NCIT:C25284",        # output relation
    "infores:assay-metadata",
    ...
])
```

### For Chemical Tests

```python
# Process ChEBI entities
for chebi_id in chebi_ids:
    # EXISTING: Direct organism → ChEBI edge (KEEP THIS)
    edge_writer.writerow([
        organism_id,
        metpo_predicate,  # e.g., METPO:2000011 (ferments)
        chebi_id,         # e.g., CHEBI:17113
        "biolink:interacts_with",
        knowledge_source,
        ...
    ])

# NEW: Add organism → assay edge
edge_writer.writerow([
    organism_id,
    metpo_predicate,      # Same METPO predicate
    assay_id,             # e.g., assay:API_50CHac_ERY
    "biolink:interacts_with",
    knowledge_source,
    ...
])

# UPFRONT: Assay → ChEBI edge (created once at start)
edge_writer.writerow([
    assay_id,             # e.g., assay:API_50CHac_ERY
    "biolink:has_input",
    chebi_id,             # e.g., CHEBI:17113
    "RO:0002233",         # has input relation
    "infores:assay-metadata",
    ...
])
```

---

## Query Examples by Use Case

### Use Case 1: Simple Biological Question

**Question**: "Which organisms can ferment erythritol?"

**Simple query (direct edges)**:
```sparql
SELECT ?organism ?name
WHERE {
  ?organism METPO:2000011 CHEBI:17113 .  # ferments erythritol
  ?organism rdfs:label ?name .
}
```

**Detailed query (via assay)**:
```sparql
SELECT ?organism ?name ?assay ?kit
WHERE {
  ?organism METPO:2000011 ?assay .
  ?assay biolink:has_input CHEBI:17113 .
  ?assay kit_name ?kit .
  ?organism rdfs:label ?name .
}
```

### Use Case 2: Methodology Question

**Question**: "Which assays test for alkaline phosphatase activity?"

**Query (requires assay nodes)**:
```sparql
SELECT ?assay ?kit ?description
WHERE {
  ?assay biolink:has_output GO:0004035 .
  ?assay kit_name ?kit .
  ?assay description ?description .
}
```

### Use Case 3: Data Quality Check

**Question**: "Which organisms have enzyme activity assertions without assay evidence?"

**Query (combines both patterns)**:
```sparql
SELECT ?organism ?enzyme ?name
WHERE {
  # Has direct assertion
  ?organism METPO:2000302 ?enzyme .
  FILTER(STRSTARTS(STR(?enzyme), "GO:") || STRSTARTS(STR(?enzyme), "EC:"))

  # But no assay support
  FILTER NOT EXISTS {
    ?organism METPO:2000302 ?assay .
    ?assay biolink:has_output ?enzyme .
  }

  ?organism rdfs:label ?name .
}
```

### Use Case 4: Cross-Assay Validation

**Question**: "Show me all assays that detected the same enzyme in this organism"

**Query (requires assay paths)**:
```sparql
SELECT ?organism ?enzyme ?assay1 ?assay2
WHERE {
  ?organism METPO:2000302 ?assay1 .
  ?assay1 biolink:has_output ?enzyme .

  ?organism METPO:2000302 ?assay2 .
  ?assay2 biolink:has_output ?enzyme .

  FILTER(?assay1 != ?assay2)  # Different assays, same enzyme
}
```

---

## Comparison with Previous Releases

### 20250222 (February 2025) - Original Dual Pattern

```
# Had both patterns but with issues:
assay:API_rID32A_alpha_GAL --biolink:assesses--> NCBITaxon:1262  ❌ Backwards!
NCBITaxon:296 --biolink:consumes--> CHEBI:27689                  ⚠️ Generic predicate
```

**Issues**:
- ❌ Wrong edge direction (assay→organism instead of organism→assay)
- ❌ Deprecated `assesses` predicate (119K edges)
- ⚠️ Generic Biolink predicates (not domain-specific)
- ⚠️ Assays as `PhenotypicQuality` (wrong category)

### 20251217 (December 2025) - Direct Only

```
# Lost the dual pattern:
NCBITaxon:693023 --METPO:2000006--> CHEBI:17992  ✅ METPO predicates
# (No assay connections for organisms)
```

**Issues**:
- ✅ Uses METPO predicates (improvement!)
- ❌ Lost organism→assay edges
- ❌ Orphaned assay nodes
- ❌ No methodology capture

### Proposed (2026+) - Modern Dual Pattern

```
# Both patterns, correctly implemented:
NCBITaxon:562 --METPO:2000302--> GO:0004035                                    ✅ Direct
NCBITaxon:562 --METPO:2000302--> assay:API_zym_alkaline_phosphatase           ✅ Via assay
assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035          ✅ Methodology
```

**Improvements**:
- ✅ Correct edge direction (organism→assay)
- ✅ No deprecated predicates
- ✅ Rich METPO predicates (8 types: shows_activity_of, ferments, assimilates, uses_for_growth, etc.)
- ✅ Proper assay node category (`biolink:Procedure`)
- ✅ Rich metadata (names, descriptions, kit info)
- ✅ Both direct edges AND assay paths

---

## Migration Notes

### Non-Breaking Changes

✅ **All direct organism→entity edges preserved**
- Existing queries continue to work
- No changes to current edge structure
- Same METPO predicates used

✅ **Additive only**
- New assay nodes (503)
- New organism→assay edges (~50K-100K)
- New assay→entity edges (~600-800)
- Nothing removed (except deprecated EC→assay edges)

### Breaking Changes

⚠️ **Only one breaking change**: Removal of 112 EC→assay edges using deprecated `biolink:is_assessed_by`
- These were never used by organism queries
- Only affected methodological metadata
- Already documented as replaced with `related_to_at_instance_level`

### User Impact

| User Type | Impact | Action Needed |
|-----------|--------|---------------|
| **Biologists** (simple queries) | None | No changes needed |
| **Tool developers** (use assays) | Positive | Can now query methodology |
| **Data curators** | Positive | Better provenance tracking |
| **API consumers** | None | Direct edges unchanged |

---

## Validation Checklist

Implementation must verify:

- [ ] All 503 assay nodes created with proper metadata
- [ ] All assay nodes have category `biolink:Procedure`
- [ ] ~600-800 assay→entity edges created (methodological reference)
- [ ] ~50K-100K organism→assay edges created (per organism results)
- [ ] ~74K direct organism→entity edges preserved (no changes)
- [ ] Same METPO predicates used for both direct and assay edges
- [ ] No deprecated predicates used
- [ ] No orphaned assay nodes
- [ ] Sample queries work for both direct and 2-hop patterns
- [ ] Graph validates against Biolink v4.3.6

---

## Conclusion

The dual-edge pattern is the optimal design because it:

1. **Preserves existing functionality** (direct edges)
2. **Adds new capabilities** (methodology capture via assays)
3. **Maintains backward compatibility** (no breaking changes to organism queries)
4. **Follows original design intent** (modernizes 20250222 pattern)
5. **Supports multiple use cases** (simple queries + detailed analysis)

This is not redundancy—it's providing users with **choice of query complexity** based on their needs.

---

**Approved**: 2026-01-12
**Implementation**: See `docs/ASSAY_IMPLEMENTATION_SUMMARY.md`
**Related**:
- `docs/ASSAY_NODE_MODELING.md` (full proposal)
- `docs/ASSAY_CURRENT_STATE_ANALYSIS.md` (current state)
- `docs/ASSAY_RELEASES_COMPARISON.md` (historical comparison)
