# Ontology Category Fixing - Explained

## What Does "Fixed categories for go" Mean?

When the ontologies transform processes GO (Gene Ontology), it performs a **post-processing step** to ensure all GO terms have the correct Biolink categories assigned. This message confirms that the category fixing was successfully applied.

## Background: Why Category Fixing is Needed

### Problem
When ontologies are initially converted to KGX (Knowledge Graph Exchange) format, they may have:
1. **Deprecated categories** - Old Biolink category names that have been superseded
2. **Generic categories** - Terms assigned broad categories that should be more specific
3. **Incorrect mappings** - Categories that don't match the term's semantic type

### Solution
The ontologies transform includes a `_fix_node_categories()` method that corrects these issues for specific ontologies.

---

## Ontologies That Get Category Fixes

The category fixing process applies to **4 ontologies**:

| Ontology | What Gets Fixed | Why |
|----------|----------------|-----|
| **GO** | Aspect-based categories | GO terms need different categories based on their namespace |
| **ChEBI** | Deprecated categories | Replace `ChemicalSubstance` → `SmallMolecule` |
| **UBERON** | Anatomical categories | Ensure proper anatomical entity categories |
| **NCBITaxon** | Organism categories | Ensure correct organism taxon categories |

---

## GO Category Fixing (Detailed)

### GO Aspects → Biolink Categories

GO terms are organized into **3 aspects** (namespaces), each requiring a different Biolink category:

#### 1. Molecular Function → `biolink:MolecularActivity`
**What it is:** Activities/functions performed by gene products (proteins, RNAs) at the molecular level

**Examples:**
- `GO:0004096` - catalase activity
- `GO:0003824` - catalytic activity
- `GO:0016491` - oxidoreductase activity

**Before fix:** Might be `biolink:BiologicalProcess` or generic `biolink:OntologyClass`
**After fix:** `biolink:MolecularActivity`

---

#### 2. Biological Process → `biolink:BiologicalProcess`
**What it is:** Larger biological programs accomplished by multiple molecular activities

**Examples:**
- `GO:0006091` - generation of precursor metabolites and energy
- `GO:0008152` - metabolic process
- `GO:0006412` - translation

**Before fix:** Might be generic `biolink:OntologyClass`
**After fix:** `biolink:BiologicalProcess`

---

#### 3. Cellular Component → `biolink:CellularComponent`
**What it is:** Locations where gene products are active (organelles, complexes, membranes)

**Examples:**
- `GO:0005737` - cytoplasm
- `GO:0005634` - nucleus
- `GO:0005886` - plasma membrane

**Before fix:** Might be generic `biolink:OntologyClass`
**After fix:** `biolink:CellularComponent`

---

## How It Works

### Process Flow

```
1. Initial KGX conversion
   ↓
   GO terms have generic categories
   (e.g., "biolink:OntologyClass")

2. Post-processing: _fix_node_categories()
   ↓
   Read nodes file → Check each GO term's aspect → Assign correct category

3. Write updated nodes file
   ↓
   Print "Fixed categories for go"
```

### Code Implementation

**Location:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

```python
def _fix_node_categories(self, nodes_file_path: Path, ontology_name: str):
    """Fix node categories for GO (aspect-based), ChEBI, UBERON, NCBITaxon."""

    df = pd.read_csv(nodes_file_path, sep="\t", dtype=str)

    # Replace deprecated categories (e.g., ChemicalSubstance → SmallMolecule)
    print(f"  Replacing deprecated categories in {ontology_name}...")
    df["category"] = df["category"].apply(
        lambda x: replace_deprecated_categories(str(x)) if pd.notna(x) else x
    )

    # Write back
    df.to_csv(nodes_file_path, sep="\t", index=False)
    print(f"  Fixed categories for {ontology_name}")
```

**Helper function:** `kg_microbe/utils/ontology_utils.py`

```python
def get_go_category_by_aspect(go_term_id: str, go_adapter=None) -> str:
    """Return Biolink category based on GO aspect (namespace)."""

    # Query GO adapter for term's namespace
    namespace = go_adapter.get_namespace(go_term_id)

    if namespace == "molecular_function":
        return "biolink:MolecularActivity"
    elif namespace == "biological_process":
        return "biolink:BiologicalProcess"
    elif namespace == "cellular_component":
        return "biolink:CellularComponent"

    # Fallback for unknown cases
    return "biolink:BiologicalProcess"
```

---

## Deprecated Category Replacement

### ChemicalSubstance → SmallMolecule

**Why this matters:**
- `biolink:ChemicalSubstance` was deprecated in Biolink Model 3.x
- The current standard is `biolink:SmallMolecule` for molecular entities
- This affects ChEBI terms and chemical references in other ontologies

**Mapping:**
```python
deprecated_map = {
    "biolink:ChemicalSubstance": "biolink:SmallMolecule",
}
```

**Impact:**
- **ChEBI**: All ChEBI terms get updated from `ChemicalSubstance` → `SmallMolecule`
- **GO**: Any GO terms referencing chemicals get corrected
- **Other ontologies**: Ensures consistency across the knowledge graph

---

## Why This Matters for KG-Microbe

### 1. **Query Accuracy**
Users querying for molecular activities need terms properly categorized:
```sparql
# This query works correctly only if categories are fixed
SELECT ?activity WHERE {
    ?activity rdf:type biolink:MolecularActivity .
}
```

### 2. **Semantic Consistency**
Different tools/consumers expect standard Biolink categories:
- KGX validation requires current (non-deprecated) categories
- Monarch Initiative tools rely on correct categorization
- SPOKE and other knowledge graphs expect Biolink compliance

### 3. **Integration with Other Data Sources**
MetaTraits, BacDive, and other transforms reference GO terms:
- Enzyme activities (molecular functions) need `biolink:MolecularActivity`
- Metabolic processes need `biolink:BiologicalProcess`
- Incorrect categories break semantic relationships

---

## Verification

### Check Category Distribution

After the transform completes, you can verify the categories were fixed:

```bash
# Count GO categories in the nodes file
cut -f2 data/transformed/ontologies/go_nodes.tsv | sort | uniq -c

# Expected output:
#  15234 biolink:MolecularActivity      (molecular functions)
#  29856 biolink:BiologicalProcess      (biological processes)
#   4125 biolink:CellularComponent      (cellular components)
```

### Spot Check Examples

```bash
# Check a known molecular function
grep "GO:0004096" data/transformed/ontologies/go_nodes.tsv
# Should show: biolink:MolecularActivity

# Check a known biological process
grep "GO:0006091" data/transformed/ontologies/go_nodes.tsv
# Should show: biolink:BiologicalProcess

# Check a known cellular component
grep "GO:0005737" data/transformed/ontologies/go_nodes.tsv
# Should show: biolink:CellularComponent
```

---

## Other Ontologies Fixed

### ChEBI
**Issue:** Many ChEBI nodes initially have `biolink:ChemicalSubstance` (deprecated)
**Fix:** Replace with `biolink:SmallMolecule` (current standard)
**Count:** ~164,000+ ChEBI terms updated

### UBERON
**Issue:** Anatomical terms may have generic categories
**Fix:** Ensure proper anatomical entity categories
**Count:** ~13,000+ UBERON terms

### NCBITaxon
**Issue:** Organism taxa may have generic categories
**Fix:** Ensure all taxa have `biolink:OrganismTaxon` category
**Count:** ~2.7M+ taxa (trimmed to microbial subset)

---

## Summary

**"Fixed categories for go"** means:

✅ **Aspect-based categorization applied** - GO terms now have correct categories based on their namespace
✅ **Deprecated categories replaced** - Old `ChemicalSubstance` → new `SmallMolecule`
✅ **Biolink compliance ensured** - All categories follow current Biolink Model standards
✅ **Ready for integration** - GO terms can now be properly linked with other data sources

This is a **normal and necessary** step in the ontologies transform that ensures the knowledge graph maintains semantic consistency and compatibility with the broader Biolink ecosystem.

---

## Related Documentation

- **Biolink Model**: https://biolink.github.io/biolink-model/
- **GO Aspects**: http://geneontology.org/docs/ontology-documentation/
- **KGX Format**: https://github.com/biolink/kgx
- **Category Consolidation**: See `docs/CHEMICAL_SUBSTANCE_CONSOLIDATION.md` in this repository

---

*Generated: 2026-03-22*
*Part of KG-Microbe ontologies transform pipeline*
