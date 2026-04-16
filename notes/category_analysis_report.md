# KG-Microbe Node Category Analysis Report

**Date:** 2026-01-11
**Merged Graph:** data/merged/20251217/merged-kg_nodes.tsv

---

## Executive Summary

**Total nodes:** 1,509,463
**Single-category nodes:** 1,502,892 (99.56%)
**Multi-category nodes:** 6,571 (0.44%)

**Unique single categories:** 14
**Unique category combinations:** 22

### Distribution by Number of Categories
- **1 category:** 1,502,892 nodes (99.56%)
- **2 categories:** 6,570 nodes (0.44%)
- **3 categories:** 1 node (0.0001%)

### Key Finding
**99.56% of nodes have single categories** - the multi-category issue affects only a small fraction of the knowledge graph.

---

## Category Distribution

### Top Single Categories

| Category | Count | Percentage |
|----------|-------|------------|
| biolink:OrganismTaxon | 1,135,246 | 75.21% |
| biolink:ChemicalSubstance | 222,620 | 14.75% |
| biolink:MolecularActivity | 87,725 | 5.81% |
| biolink:BiologicalProcess | 31,906 | 2.11% |
| biolink:OntologyClass | 9,657 | 0.64% |
| biolink:ChemicalEntity | 6,256 | 0.41% |
| biolink:CellularComponent | 4,574 | 0.30% |
| METPO:1004005 | 3,333 | 0.22% |
| biolink:AnatomicalEntity | 591 | 0.04% |
| biolink:NamedThing | 432 | 0.03% |
| biolink:EnvironmentalFeature | 406 | 0.03% |
| biolink:PhenotypicQuality | 144 | 0.01% |
| biolink:ChemicalMixture | 2 | 0.0001% |

---

## Multi-Category Node Analysis

### 1. biolink:BiologicalProcess|biolink:MolecularActivity
**Affected nodes:** 5,057 (77% of all multi-category nodes)

- **ID prefix:** GO (Gene Ontology)
- **Sample IDs:** GO:0004096, GO:0004566, GO:0004664, GO:0004565, GO:0009039
- **Sample names:**
  - GO:0004096: catalase activity
  - GO:0004566: beta-glucuronidase activity
  - GO:0009039: urease activity

**Semantic Analysis:**
These are **GO molecular function (MF) terms** that should be categorized as `biolink:MolecularActivity`, not `biolink:BiologicalProcess`. The GO ontology has three aspects:
- Molecular Function (MF) → should be `biolink:MolecularActivity`
- Biological Process (BP) → should be `biolink:BiologicalProcess`
- Cellular Component (CC) → should be `biolink:CellularComponent`

**Root Cause:**
Different transforms assign different categories to the same GO terms. The ontology transform assigns `biolink:MolecularActivity` (correct), but BacDive or other transforms may reference these GO terms with `biolink:BiologicalProcess` (incorrect).

**Recommendation:** **MEDIUM PRIORITY**
Implement GO aspect-based categorization to ensure MF terms are categorized as MolecularActivity and BP terms as BiologicalProcess.

---

### 2. biolink:ChemicalEntity|biolink:ChemicalSubstance
**Affected nodes:** 1,263 (19% of multi-category nodes)

- **ID prefix:** CHEBI (Chemical Entities of Biological Interest)
- **Sample IDs:** CHEBI:16828, CHEBI:16199, CHEBI:17634, CHEBI:16899, CHEBI:17716
- **Sample names:**
  - CHEBI:16828: L-tryptophan
  - CHEBI:16199: Urea
  - CHEBI:17634: D-fructose
  - CHEBI:16899: D-mannitol
  - CHEBI:17716: lactose

**Semantic Analysis:**
`biolink:ChemicalSubstance` is **DEPRECATED** in recent Biolink Model versions. The current Biolink Model recommends using `biolink:SmallMolecule` or `biolink:ChemicalEntity` instead.

These are all chemical compounds from ChEBI that inherit both category assignments from different transforms. ChemicalEntity is a parent class of the deprecated ChemicalSubstance.

**Root Cause:**
The ChEBI ontology transform assigns deprecated `biolink:ChemicalSubstance`, while MediaDive or BacDive transforms assign `biolink:ChemicalEntity` when referencing these chemicals.

**Recommendation:** **HIGH PRIORITY**
Consolidate to `biolink:SmallMolecule` (the current Biolink Model standard for chemical compounds). Update the ChEBI ontology transform to replace deprecated ChemicalSubstance with SmallMolecule.

---

### 3. biolink:ChemicalRole|biolink:ChemicalSubstance
**Affected nodes:** 207 (3% of multi-category nodes)

- **ID prefix:** CHEBI
- **Sample IDs:** CHEBI:131604, CHEBI:131699, CHEBI:132717, CHEBI:138880, CHEBI:139492
- **Sample names:**
  - CHEBI:131604: Mycoplasma genitalium metabolite
  - CHEBI:131699: EC 2.7.7.7 (DNA-directed DNA polymerase) inhibitor
  - CHEBI:23354: coenzyme
  - CHEBI:23357: cofactor
  - CHEBI:22586: antioxidant

**Semantic Analysis:**
These are **ChEBI role terms** that describe the function or role of chemicals (e.g., "antioxidant", "cofactor", "inhibitor"). ChemicalRole is a mixin class that describes function, while ChemicalSubstance (deprecated) describes the entity itself.

**Root Cause:**
ChEBI assigns both ChemicalRole and deprecated ChemicalSubstance to role terms, creating semantic confusion.

**Recommendation:** **HIGH PRIORITY**
Use `biolink:ChemicalRole` only (more specific and semantically correct). Remove deprecated ChemicalSubstance from role terms.

---

### 4. biolink:BiologicalProcess|biolink:OntologyClass
**Affected nodes:** 36 (0.5% of multi-category nodes)

- **ID prefix:** GO
- **Sample IDs:** GO:0003008, GO:0006091, GO:0007588, GO:0007610, GO:0007631
- **Sample names:**
  - GO:0003008: system process
  - GO:0006091: generation of precursor metabolites and energy
  - GO:0007588: excretion

**Semantic Analysis:**
These are GO biological process terms. `biolink:OntologyClass` is too general and should not be used as a category for specific GO terms.

**Recommendation:** **LOW PRIORITY**
Keep `biolink:BiologicalProcess` only. Remove `biolink:OntologyClass` from GO term categorization.

---

### 5. Edge Cases (Small Counts)

#### biolink:AnatomicalEntity|biolink:EnvironmentalFeature (3 nodes)
- **IDs:** UBERON:0000468, UBERON:0001913, UBERON:0002049
- **Names:** multicellular organism, milk, vasculature
- **Analysis:** UBERON anatomical terms that can also be environmental features
- **Recommendation:** Keep AnatomicalEntity (more specific)

#### biolink:ChemicalSubstance|biolink:EnvironmentalFeature (2 nodes)
- **IDs:** CHEBI:24632, CHEBI:33290
- **Names:** hydrocarbon, food
- **Analysis:** Chemicals that are also environmental features
- **Recommendation:** Keep ChemicalSubstance (or update to SmallMolecule), remove EnvironmentalFeature

#### biolink:EnvironmentalFeature|biolink:OrganismTaxon (1 node)
- **ID:** NCBITaxon:1
- **Name:** root
- **Analysis:** The root node of NCBITaxon with questionable dual categorization
- **Recommendation:** Keep OrganismTaxon only

#### biolink:AnatomicalEntity|biolink:ChemicalEntity (1 node)
- **ID:** UBERON:0001970
- **Name:** bile
- **Analysis:** Bile is both an anatomical entity (produced by liver) and a chemical entity
- **Recommendation:** Manual review - may be justified

#### biolink:AnatomicalEntity|biolink:ChemicalEntity|biolink:EnvironmentalFeature (1 node)
- **ID:** UBERON:0000178
- **Name:** blood
- **Analysis:** Blood can be:
  - AnatomicalEntity (part of organism)
  - ChemicalEntity (complex mixture)
  - EnvironmentalFeature (found in environment)
- **Recommendation:** Use AnatomicalEntity as primary category

---

## Root Cause Analysis

### Why Multi-Category Nodes Occur

Multi-category nodes are created during the **KGX merge process** when:

1. **Different transforms assign different categories to the same entity**
   - Ontology transforms assign canonical categories from OBO ontologies
   - Data transforms (BacDive, MediaDive) reference the same entities with different categories

2. **KGX merge combines category assignments**
   - When merging nodes with the same ID but different categories, KGX creates pipe-delimited category combinations
   - This preserves both category assignments but creates semantic redundancy

3. **No category conflict resolution configured**
   - The merge configuration (merge.yaml) doesn't specify category prioritization rules
   - KGX defaults to combining all categories with pipes

### Example Flow

**Transform stage:**
- `ontologies/go` creates: `GO:0004096` with category `biolink:MolecularActivity`
- `bacdive` references: `GO:0004096` with category `biolink:BiologicalProcess`

**Merge stage:**
- KGX finds two nodes with ID `GO:0004096` but different categories
- KGX creates merged node with category: `biolink:BiologicalProcess|biolink:MolecularActivity`

---

## Implementation Roadmap

### High-Priority Actions (Immediate)

#### 1. Update ChEBI Categories (1,263 nodes)
**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Change:**
```python
def _fix_deprecated_categories(self, nodes_file_path: Path):
    """Replace deprecated ChemicalSubstance with SmallMolecule."""
    df = pd.read_csv(nodes_file_path, sep='\t')

    # Replace deprecated ChemicalSubstance
    df['category'] = df['category'].str.replace(
        'biolink:ChemicalSubstance',
        'biolink:SmallMolecule',
        regex=False
    )

    df.to_csv(nodes_file_path, sep='\t', index=False)
```

**Impact:** Fixes 1,470 nodes (1,263 ChemicalEntity|ChemicalSubstance + 207 ChemicalRole|ChemicalSubstance)

---

#### 2. Fix ChEBI Role Categories (207 nodes)
**File:** `kg_microbe/transform_utils/ontologies/ontologies_transform.py`

**Change:** Ensure ChEBI role terms are categorized only as `biolink:ChemicalRole`, removing deprecated ChemicalSubstance.

**Implementation:** Add role detection logic to category assignment:
```python
# Check if ChEBI term is a role
if 'role' in chebi_name.lower() or chebi_id in CHEBI_ROLE_IDS:
    category = 'biolink:ChemicalRole'
```

**Impact:** Fixes 207 nodes

---

### Medium-Priority Actions

#### 3. Implement GO Aspect-Based Categorization (5,057 nodes)
**File:** `kg_microbe/utils/ontology_utils.py` (create new file)

**Create utility function:**
```python
from oaklib import get_adapter

def get_go_category_by_aspect(go_term_id: str) -> str:
    """Return Biolink category based on GO aspect (namespace)."""
    go_adapter = get_adapter("sqlite:data/raw/go.db")
    term = go_adapter.entity(go_term_id)

    if term:
        namespace = term.get('namespace', '')

        if namespace == 'molecular_function':
            return 'biolink:MolecularActivity'
        elif namespace == 'biological_process':
            return 'biolink:BiologicalProcess'
        elif namespace == 'cellular_component':
            return 'biolink:CellularComponent'

    return 'biolink:BiologicalEntity'  # fallback
```

**Update ontologies transform:** Apply this function when processing GO terms.

**Impact:** Fixes 5,057 nodes

---

#### 4. Update Category Constants
**File:** `kg_microbe/transform_utils/constants.py`

**Changes:**
- Replace `CHEMICAL_SUBSTANCE_CATEGORY` with `SMALL_MOLECULE_CATEGORY`
- Add `CHEMICAL_ROLE_CATEGORY = "biolink:ChemicalRole"`
- Update all usages across transforms

---

#### 5. Configure KGX Merge Conflict Resolution
**File:** `merge.yaml`

**Add category priority rules:**
```yaml
# Merge configuration
transform:
  output_format: tsv

  # Category conflict resolution
  category_priority:
    - biolink:SmallMolecule  # prefer over ChemicalEntity
    - biolink:MolecularActivity  # prefer over BiologicalProcess for GO MF
    - biolink:ChemicalRole  # prefer for role terms
    - biolink:BiologicalProcess  # prefer over OntologyClass
```

**Note:** Verify if KGX supports this configuration; may need custom post-processing script instead.

---

### Low-Priority Actions

#### 6. Review BiologicalProcess|OntologyClass (36 nodes)
**Action:** Update ontology transform to remove OntologyClass from GO biological process terms.

#### 7. Manual Review Edge Cases (8 nodes)
**Action:** Review each edge case individually:
- UBERON:0000178 (blood) - likely keep AnatomicalEntity
- NCBITaxon:1 (root) - keep OrganismTaxon only
- Others as documented above

---

### Long-Term Improvements

1. **Migrate to Latest Biolink Model**
   - Ensure all category assignments use current (non-deprecated) categories
   - Review Biolink Model changelog for category changes

2. **Add Category Validation to CI/CD**
   - Create test that checks for multi-category nodes
   - Fail pipeline if multi-category percentage exceeds threshold (e.g., 0.5%)

3. **Implement Category Consistency Checks**
   - Add validation script to check category assignments match ontology types
   - Verify GO MF terms use MolecularActivity, BP terms use BiologicalProcess, etc.

4. **Document Category Assignment Logic**
   - Add docstrings to transform classes explaining category selection
   - Create CATEGORY_MAPPING.md documenting category assignment rules

---

## Validation Plan

After implementing fixes:

1. **Re-run transforms:**
   ```bash
   poetry run kg transform -s ontologies
   poetry run kg transform -s bacdive
   poetry run kg transform -s mediadive
   ```

2. **Re-run merge:**
   ```bash
   poetry run kg merge -y merge.yaml
   ```

3. **Verify results:**
   ```bash
   # Count multi-category nodes
   awk -F'\t' 'NR > 1 && $2 ~ /\|/ {print}' data/merged/[date]/merged-kg_nodes.tsv | wc -l

   # Should be significantly reduced (target: < 50 nodes)
   ```

4. **Run analysis script again:**
   ```bash
   poetry run python analyze_categories.py
   ```

---

## Summary

### What We Have
- 1.5M nodes with **0.44% (6,571 nodes) having multiple categories**
- Primarily affects GO and CHEBI terms

### Why It Happens
- KGX merge combines nodes from different transforms with different category assignments
- No category conflict resolution configured
- Use of deprecated Biolink categories (ChemicalSubstance)

### What's Wrong
1. **ChemicalSubstance is deprecated** (should use SmallMolecule)
2. **GO terms need aspect-based categorization** (MF vs BP distinction)
3. **Semantic redundancy** (parent-child category pairs)

### How to Fix It
1. **HIGH:** Update ChEBI to use SmallMolecule (fixes 1,470 nodes)
2. **MEDIUM:** Implement GO aspect-based categorization (fixes 5,057 nodes)
3. **LOW:** Clean up edge cases and remove OntologyClass (fixes 44 nodes)

### Expected Impact
- Reduce multi-category nodes from **6,571 to < 50** (99%+ reduction)
- Improve Biolink Model compliance
- Enhance data quality and query consistency
- Enable more accurate downstream analysis

---

## Files Generated

- `category_stats.txt` - Complete category distribution
- `multi_category_nodes.tsv` - All 6,571 multi-category nodes with full metadata
- `multi_category_combinations.txt` - Counts by category combination
- `source_attribution.json` - Source transform mapping (sample)
- `category_analysis_report.md` - This report

---

**Report Generated:** 2026-01-11
**Analysis Tool:** `analyze_categories.py`
**Data Source:** `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/merged/20251217/merged-kg_nodes.tsv`
