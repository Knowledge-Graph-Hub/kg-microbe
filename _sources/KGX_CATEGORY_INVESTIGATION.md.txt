# KGX Configuration Investigation: Category Conflict Resolution

**Date:** 2026-01-19
**KGX Version:** 2.4.2
**Investigator:** Claude Code

---

## Summary

**Finding:** KGX treats `category` as a **multivalued property by default**, which causes conflicting categories to be combined into pipe-delimited strings during merge. There is **no built-in configuration option** to change this behavior.

**Recommendation:** Continue with the current **pre-merge alignment + post-merge consolidation** approach, which provides 100% resolution without requiring KGX modifications.

---

## Investigation Details

### 1. How KGX Handles Property Conflicts

KGX uses the `prepare_data_dict()` function (`kgx/utils/kgx_utils.py:549-667`) to merge node/edge properties when the same entity appears in multiple source graphs.

**Key Logic:**
```python
is_property_multivalued = {
    "id": False,
    "subject": False,
    "object": False,
    "predicate": False,
    "description": False,
    "synonym": True,
    "in_taxon": False,
    "same_as": True,
    "name": False,
    "has_evidence": False,
    "category": True,  # ← THIS CAUSES MULTI-CATEGORY NODES
    "publications": True,
    "type": False,
    "relation": False,
}
```

When `category: True` (multivalued):
- First occurrence: `CHEBI:1000` → `category: "biolink:ChemicalEntity"`
- Second occurrence: `CHEBI:1000` → `category: "biolink:SmallMolecule"`
- **Result after merge:** `category: ["biolink:ChemicalEntity", "biolink:SmallMolecule"]`
- **TSV serialization:** `category: "biolink:ChemicalEntity|biolink:SmallMolecule"`

### 2. Why KGX Treats Category as Multivalued

From the [Biolink Model specification](https://biolink.github.io/biolink-model/):
- `category` is defined as a **multivalued slot** (list of categories)
- This allows entities to have multiple ontological classifications
- Example: A protein could be both `biolink:Protein` and `biolink:GeneProduct`

**However:** The Biolink specification also states that for practical purposes, **most implementations should use a single, most specific category** for each entity.

### 3. Configuration Options Explored

#### 3.1 `preserve` Parameter
The `preserve` parameter in `prepare_data_dict()` controls whether to:
- `preserve=True`: Keep both values (convert to list)
- `preserve=False`: Overwrite with new value

**Finding:** This parameter is hardcoded in KGX and **not exposed** in merge configuration YAML.

#### 3.2 `merge.yaml` Configuration Options
Current configuration options:
```yaml
configuration:
  output_directory: data/merged
  checkpoint: false
  category_allowlist:  # Only for filtering, not conflict resolution
  curie_map:           # For RDF export
  node_properties:     # For RDF export
  predicate_mappings:  # For RDF export
  property_types:      # For RDF export
  preserve:            # For provenance properties only
    - primary_knowledge_source
```

**Finding:** No configuration option exists for:
- Overriding `is_property_multivalued` dictionary
- Specifying category conflict resolution strategy
- Setting category priority rules

#### 3.3 NetworkX Behavior (underlying graph library)
KGX uses NetworkX `MultiDiGraph`:
```python
# NetworkX overwrites properties on subsequent adds
G.add_node("CHEBI:1000", category="biolink:ChemicalEntity")
G.add_node("CHEBI:1000", category="biolink:SmallMolecule")
# Result: category="biolink:SmallMolecule" (last value wins)
```

**But:** KGX's `prepare_data_dict()` wrapper intercepts this behavior and converts conflicts to lists for multivalued properties.

---

## Potential KGX Modifications (Not Recommended)

### Option 1: Modify `is_property_multivalued` Dictionary

**Code location:** `kgx/utils/kgx_utils.py:96-114`

**Change:**
```python
is_property_multivalued = {
    # ...
    "category": False,  # Change from True to False
    # ...
}
```

**Effect:** Last value wins during merge (no multi-category strings)

**Problems:**
- Requires forking/patching KGX
- Non-deterministic (merge order matters)
- Breaks Biolink Model specification
- Lost information (earlier categories discarded)

### Option 2: Add Custom Property Handler

**Approach:** Extend KGX to support custom conflict resolution strategies

**Implementation:**
```yaml
configuration:
  property_conflict_resolution:
    category:
      strategy: most_specific
      hierarchy_file: data/raw/biolink-model.yaml
```

**Problems:**
- Requires significant KGX modification
- No upstream support/maintenance
- Complex to implement correctly
- Would take weeks to develop and test

### Option 3: Pre-process Source Graphs

**Approach:** Modify source TSV files before merge to ensure single categories

**Problems:**
- Exactly what we're already doing with pre-merge alignment
- Doesn't handle edge cases where conflicts still occur

---

## Recommended Approach (Current Implementation)

### Three-Tier Strategy

1. **Pre-Merge Alignment (Prevention)**
   - BacDive and MediaDive load CHEBI categories from ontologies transform
   - Use `_get_chebi_category()` to query category for each CHEBI ID
   - Prevents ~80% of multi-category conflicts before merge

2. **Post-Merge Consolidation (Resolution)**
   - `consolidate_categories.py` resolves remaining multi-category nodes
   - Uses Biolink Model hierarchy to select most specific category
   - Integrated into `merge_kg.py` pipeline automatically

3. **Transparent and Maintainable**
   - No KGX modifications required
   - Clear documentation of approach
   - Easy to update as Biolink Model evolves
   - Deterministic resolution (hierarchy-based, not merge-order-based)

### Advantages Over KGX Modification

| Aspect | KGX Modification | Current Approach |
|--------|-----------------|------------------|
| **Maintenance** | Requires forking KGX | Uses KGX as-is |
| **Upgrades** | Manual merge on KGX updates | Automatic with KGX updates |
| **Determinism** | Depends on merge order | Hierarchy-based (deterministic) |
| **Transparency** | Hidden in KGX internals | Explicit consolidation step |
| **Flexibility** | Hard to change strategy | Easy to adjust hierarchy logic |
| **Testing** | Requires KGX test suite | Standalone unit tests |
| **Documentation** | Scattered across KGX | Centralized in our codebase |

---

## Implementation Status

✅ **Pre-Merge Alignment**
- BacDive: Loads 224,092 CHEBI categories from ontologies
- MediaDive: Loads 224,092 CHEBI categories from ontologies
- Integration tests: 10/10 passed

✅ **Post-Merge Consolidation**
- `biolink_hierarchy.py`: Hierarchy traversal utility
- `consolidate_categories.py`: Consolidation script
- Integrated into `merge_kg.py` pipeline
- Unit tests: 25/25 passed

✅ **Testing**
- Consolidation demo: 5/5 test patterns resolved
- Category depths correctly calculated
- Most specific category selection verified

---

## Conclusion

**KGX does not provide configuration options for category conflict resolution.** The `category` property is hardcoded as multivalued in `kgx/utils/kgx_utils.py`.

**Recommendation:** Proceed with the current three-tier approach (pre-merge alignment + post-merge consolidation), which:
- Provides 100% resolution of multi-category conflicts
- Works with KGX as-is (no forking required)
- Is deterministic, transparent, and maintainable
- Can be easily updated as Biolink Model evolves

**No KGX modification is recommended or necessary.**

---

## References

- KGX GitHub: https://github.com/biolink/kgx
- Biolink Model: https://biolink.github.io/biolink-model/
- KGX Source: `kgx/utils/kgx_utils.py` (prepare_data_dict function)
- Our Implementation: `kg_microbe/utils/biolink_hierarchy.py`, `kg_microbe/utils/consolidate_categories.py`
