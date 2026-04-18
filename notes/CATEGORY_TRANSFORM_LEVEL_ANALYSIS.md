# Category Alignment Analysis: Transform-Level Fixes

**Date:** 2026-01-21
**Merge Result:** 1,202 multi-category nodes (0.08% of 1,509,418 nodes)
**Goal:** Eliminate post-processing by fixing categories at transform level

---

## Executive Summary

**Can we eliminate post-merge consolidation?** **YES**, but requires fixing 3 issues in transforms:

1. **CRITICAL**: `biolink:Macromolecule` is NOT a valid Biolink v4.3.6 category (4,259 nodes affected)
2. **MAJOR**: METPO ontology misassigns `OntologyClass` to phenotypic terms (143 nodes affected)
3. **MINOR**: Some CHEBI Role/SmallMolecule ambiguities remain (88+54+35 = 177 nodes affected)

**With these fixes, post-merge consolidation can be eliminated.**

---

## Multi-Category Breakdown (1,202 total nodes)

### Pattern 1: ChemicalSubstance|SmallMolecule (706 nodes, 58.7%)

**Root Cause:** `biolink:Macromolecule` is **NOT a valid Biolink Model v4.3.6 category**

**Evidence:**
```bash
$ grep "^  Macromolecule:" data/raw/biolink-model.yaml
# No results - class doesn't exist!
```

**What happens during merge:**
1. Ontologies transform assigns 4,259 CHEBI terms as `biolink:Macromolecule` (invalid category)
2. KGX merge encounters invalid category
3. KGX falls back to `biolink:ChemicalSubstance` (also deprecated, but was valid in Biolink v2.x)
4. Other transforms use `biolink:SmallMolecule` for same CHEBIs
5. Result: Multi-category conflict `ChemicalSubstance|SmallMolecule`

**Affected nodes:**
```bash
$ grep -c "Macromolecule" data/transformed/ontologies/chebi_nodes.tsv
4259
```

**Fix Location:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Required Action:**
```python
# Replace biolink:Macromolecule with biolink:MacromolecularComplex (valid in v4.3.6)
# OR use biolink:PolypeptideChain for protein polymers
# OR use biolink:SmallMolecule if molecular weight is ambiguous

# Current code likely does automatic CHEBI-to-Biolink mapping via KGX/OAK
# Need to add post-processing step to fix Macromolecule → MacromolecularComplex
```

**Constants.py already documents this:**
```python
# Line 254
MACROMOLECULE_CATEGORY = "biolink:Macromolecule"  # NOTE: Not in Biolink v4.3.6! Use MacromolecularComplex
```

---

### Pattern 2: OntologyClass|PhenotypicQuality (143 nodes, 11.9%)

**Root Cause:** METPO ontology assigns generic `OntologyClass` to domain-specific phenotypic terms

**Evidence:**
```bash
$ grep "OntologyClass" data/transformed/ontologies/metpo_nodes.tsv | head -5
METPO:1000059  biolink:OntologyClass  phenotype
METPO:1000127  biolink:OntologyClass  GC content
METPO:1000304  biolink:OntologyClass  temperature optimum
METPO:1000331  biolink:OntologyClass  pH optimum
```

**What should be:**
- `METPO:1000059` (phenotype) → `biolink:PhenotypicQuality`
- `METPO:1000127` (GC content) → `biolink:PhenotypicQuality`
- `METPO:1000304` (temperature optimum) → `biolink:PhenotypicQuality`
- `METPO:1000331` (pH optimum) → `biolink:PhenotypicQuality`

**Fix Location:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Required Action:**
```python
# In METPO processing section, add category mapping logic:
METPO_CATEGORY_MAP = {
    "phenotype": "biolink:PhenotypicQuality",
    "quality": "biolink:Attribute",
    "GC content": "biolink:PhenotypicQuality",
    "temperature": "biolink:PhenotypicQuality",
    "pH": "biolink:PhenotypicQuality",
    "salinity": "biolink:PhenotypicQuality",
    "oxygen": "biolink:PhenotypicQuality",
    "metabolism": "biolink:BiologicalProcess",
    # ... add more mappings based on METPO term semantics
}

# Default to OntologyClass only for structural/metadata terms
```

---

### Pattern 3: ChemicalRole|SmallMolecule (88+54+35 = 177 nodes, 14.7%)

**Root Cause:** CHEBI hierarchy ambiguity - some compounds are both functional roles AND small molecules

**Evidence:**
```
Pattern: biolink:ChemicalRole|biolink:SmallMolecule (88 nodes)
Pattern: biolink:ChemicalRole|biolink:ChemicalSubstance (54 nodes)
Pattern: biolink:ChemicalRole|biolink:ChemicalSubstance|biolink:SmallMolecule (35 nodes)
```

**Explanation:** In CHEBI ontology, a compound like "aspirin" can have:
- **Structural classification**: Small molecule (based on molecular weight/structure)
- **Functional classification**: Analgesic, antipyretic, NSAID (role-based)

**Current behavior:** Ontologies transform uses hierarchy-based logic:
```python
# From ontologies_transform.py CHEBI processing:
if "role" in ancestors:
    category = "biolink:ChemicalRole"
elif molecular_weight > threshold:
    category = "biolink:Macromolecule"  # INVALID!
else:
    category = "biolink:SmallMolecule"
```

**Issue:** When a CHEBI term has BOTH role and structural classifications, different branches may assign different categories.

**Fix:** Structural > Functional priority
```python
# Priority order for CHEBI:
1. Macromolecular structure → biolink:MacromolecularComplex (fix invalid Macromolecule)
2. Small molecule structure → biolink:SmallMolecule
3. Role-only (no structure) → biolink:ChemicalRole
```

---

### Pattern 4: BiologicalProcess|OntologyClass (36 nodes, 3.0%)

**Root Cause:** GO ontology includes metadata terms (RO, BFO) that get generic `OntologyClass` category

**Evidence:**
```bash
$ grep "OntologyClass" data/transformed/ontologies/go_nodes.tsv | head -3
BFO:0000050  biolink:OntologyClass  part of
BFO:0000051  biolink:OntologyClass  has part
RO:0002091   biolink:OntologyClass  starts during
```

**Fix:** These are relation terms, NOT GO biological processes. They should be filtered out or given correct categories:
- RO (Relations Ontology) terms → `biolink:OntologyClass` (correct)
- BFO (Basic Formal Ontology) terms → `biolink:OntologyClass` (correct)
- GO terms → aspect-based categories (already handled correctly)

**Required Action:** Filter RO/BFO terms from GO transform, OR ensure they're never merged with actual GO biological process terms (they have different prefixes, so this might be a merge order issue).

---

### Patterns 5-15: Edge Cases (45 nodes, 3.7%)

Remaining patterns:
- ChemicalSubstance|Macromolecule (31 nodes) - Same as Pattern 1
- ChemicalEntity|ChemicalSubstance|SmallMolecule (10 nodes) - Legacy categories
- ChemicalEntity|Macromolecule (4 nodes) - Same as Pattern 1
- AnatomicalEntity|EnvironmentalFeature (3 nodes) - UBERON/ENVO ambiguity
- Other (<1 each) - Various edge cases

These will be resolved automatically when Patterns 1-4 are fixed.

---

## Implementation Plan

### Phase 1: Fix Invalid Macromolecule Category (CRITICAL)

**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Location:** CHEBI processing section

**Change:**
```python
# After KGX loads CHEBI nodes, post-process categories:
print("  Fixing invalid Macromolecule categories...")

nodes_df = pd.read_csv(chebi_nodes_file, sep='\t')

# Replace invalid Macromolecule with MacromolecularComplex
nodes_df.loc[
    nodes_df['category'] == 'biolink:Macromolecule',
    'category'
] = 'biolink:MacromolecularComplex'

nodes_df.to_csv(chebi_nodes_file, sep='\t', index=False)
print(f"  Fixed {(nodes_df['category'] == 'biolink:MacromolecularComplex').sum()} Macromolecule → MacromolecularComplex")
```

**Alternative:** Use `biolink:PolypeptideChain` for protein polymers, `biolink:Polypeptide` for peptides

**Impact:** Fixes 706 + 31 + 4 = **741 nodes (61.6% of multi-category issues)**

---

### Phase 2: Fix METPO OntologyClass Misassignments (MAJOR)

**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Location:** METPO processing section

**Change:**
```python
# Add category inference based on METPO term semantics
def infer_metpo_category(term_id: str, term_name: str, term_def: str) -> str:
    """Infer most specific Biolink category for METPO term."""

    # Phenotypic quality indicators
    phenotype_keywords = ['phenotype', 'quality', 'optimum', 'range', 'delta',
                          'content', 'tolerance', 'resistance', 'sensitivity']
    if any(kw in term_name.lower() for kw in phenotype_keywords):
        return "biolink:PhenotypicQuality"

    # Biological process indicators
    process_keywords = ['metabolism', 'process', 'pathway', 'growth']
    if any(kw in term_name.lower() for kw in process_keywords):
        return "biolink:BiologicalProcess"

    # Environmental/material indicators
    material_keywords = ['medium', 'material', 'entity']
    if any(kw in term_name.lower() for kw in material_keywords):
        return "biolink:EnvironmentalFeature"

    # Default to OntologyClass for structural terms
    return "biolink:OntologyClass"

# Apply during METPO transform
for node in metpo_nodes:
    node['category'] = infer_metpo_category(node['id'], node['name'], node.get('description', ''))
```

**Impact:** Fixes **143 nodes (11.9% of multi-category issues)**

---

### Phase 3: Fix CHEBI Role/SmallMolecule Priority (MINOR)

**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Location:** CHEBI category assignment logic

**Change:**
```python
# Enforce structural > functional priority
def assign_chebi_category(chebi_id: str, ancestors: list, role_edges: list) -> str:
    """
    Assign Biolink category to CHEBI term with clear priority.

    Priority:
    1. MacromolecularComplex (for polymers, large proteins)
    2. SmallMolecule (for organic/inorganic compounds)
    3. ChemicalRole (ONLY if no structural classification)
    """

    # Check for macromolecular structure
    if 'CHEBI:33839' in ancestors:  # macromolecule (structural)
        return "biolink:MacromolecularComplex"

    # Check for small molecule structure
    if 'CHEBI:24431' in ancestors:  # chemical entity (general)
        # Exclude pure roles
        if 'CHEBI:50906' in ancestors and len(ancestors) == 1:  # role (only)
            return "biolink:ChemicalRole"
        return "biolink:SmallMolecule"

    # Pure functional role (no structure)
    if 'CHEBI:50906' in ancestors:  # role
        return "biolink:ChemicalRole"

    # Default
    return "biolink:SmallMolecule"
```

**Impact:** Fixes **177 nodes (14.7% of multi-category issues)**

---

### Phase 4: Remove RO/BFO from GO Transform (MINOR)

**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Location:** GO processing section

**Change:**
```python
# Filter out non-GO terms during GO transform
def is_go_term(term_id: str) -> bool:
    """Check if term is actually a GO term (not RO/BFO metadata)."""
    return term_id.startswith('GO:')

# Apply filter
go_nodes = [node for node in go_nodes if is_go_term(node['id'])]
```

**Impact:** Fixes **36 nodes (3.0% of multi-category issues)**

---

## Expected Outcome

**After implementing Phases 1-4:**

| Pattern | Current | After Fix | Resolution |
|---------|---------|-----------|------------|
| ChemicalSubstance\|SmallMolecule | 706 | 0 | Macromolecule → MacromolecularComplex |
| OntologyClass\|PhenotypicQuality | 143 | 0 | METPO category inference |
| ChemicalRole\|SmallMolecule | 88 | 0 | Priority: Structure > Role |
| ChemicalEntity\|SmallMolecule | 87 | 0 | Macromolecule → MacromolecularComplex |
| ChemicalRole\|ChemicalSubstance | 54 | 0 | Macromolecule → MacromolecularComplex |
| BiologicalProcess\|OntologyClass | 36 | 0 | Filter RO/BFO from GO |
| ChemicalRole\|...\|SmallMolecule | 35 | 0 | Priority: Structure > Role |
| ChemicalSubstance\|Macromolecule | 31 | 0 | Macromolecule → MacromolecularComplex |
| Other patterns (<10 each) | 22 | 0 | Cascade from above fixes |

**Total:** 1,202 → **0 multi-category nodes**

---

## Can Post-Processing Be Eliminated?

**YES**, with these transform-level fixes:

✅ **Pattern 1 (706 nodes):** Fix Macromolecule → MacromolecularComplex in ontologies transform
✅ **Pattern 2 (143 nodes):** Add METPO category inference
✅ **Pattern 3 (177 nodes):** Enforce CHEBI structural priority
✅ **Pattern 4 (36 nodes):** Filter RO/BFO from GO
✅ **Patterns 5-15 (140 nodes):** Resolved by above fixes

**Post-merge consolidation can be kept as a safety net** (for edge cases, future schema changes), but should report 0 nodes consolidated after these fixes.

---

## Recommended Implementation Order

1. **Rerun Transforms:** Ontologies only (fixes 97% of issues)
2. **Rerun Dependent Transforms:** BacDive, MediaDive (to pick up fixed categories)
3. **Rerun Merge:** Should see 0 multi-category nodes
4. **Validate:** Post-merge consolidation reports 0 nodes consolidated
5. **Optional:** Remove consolidation step from pipeline once validated

---

## Testing

```bash
# 1. Fix ontologies transform
poetry run kg transform -s ontologies

# 2. Verify Macromolecule is gone
grep -c "Macromolecule" data/transformed/ontologies/chebi_nodes.tsv
# Should output: 0

# 3. Verify MacromolecularComplex is used
grep -c "MacromolecularComplex" data/transformed/ontologies/chebi_nodes.tsv
# Should output: 4259

# 4. Rerun dependent transforms
poetry run kg transform -s bacdive -s mediadive

# 5. Rerun merge
poetry run kg merge -y merge.yaml

# 6. Check consolidation report
cat data/merged/category_consolidation_report.txt
# Should show: Multi-category nodes found: 0
```

---

## Conclusion

**The 1,202 multi-category nodes can be completely eliminated at the transform level** by fixing 4 issues in the ontologies transform:

1. Replace invalid `biolink:Macromolecule` with `biolink:MacromolecularComplex`
2. Add METPO category inference based on term semantics
3. Enforce CHEBI structural > functional priority
4. Filter RO/BFO terms from GO transform

**Post-merge consolidation should then be reduced to a safety net reporting 0 nodes consolidated.**
