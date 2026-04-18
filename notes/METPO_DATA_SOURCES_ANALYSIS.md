# METPO Data Sources in kg-microbe

**Date:** 2026-04-04  
**Status:** ✅ Currently using TSV templates from METPO GitHub (correct approach)

---

## Current METPO Data Sources

### 1. METPO TSV Templates (PRIMARY - For Mappings) ✅

**Source:** METPO GitHub repository TSV templates

**Files Used:**
```python
# kg_microbe/utils/mapping_file_utils.py

METPO_CLASSES_ROBOT_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo_sheet.tsv"
)

METPO_PROPERTIES_ROBOT_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo-properties.tsv"
)
```

**Purpose:**
- **metpo_sheet.tsv** - METPO phenotype/quality classes with synonyms
- **metpo-properties.tsv** - METPO predicates (object/data properties)

**When Loaded:** 
- Dynamically fetched when `load_metpo_mappings()` is called
- Used by metatraits, bacdive, bactotraits, madin_etal transforms

**Content Examples:**

**metpo_sheet.tsv:**
```tsv
ID              label           metatraits synonym    bacdive keyword synonym
METPO:1000127   GC content      GC percentage        GC content
METPO:1000602   aerobic         aerobic              aerobe
METPO:1000304   temperature optimum   optimal temperature   optimum temperature
```

**metpo-properties.tsv:**
```tsv
ID              label                        RANGE               biolink equivalent
METPO:2000002   assimilates                 chemical entity     biolink:interacts_with
METPO:2000007   degrades                    chemical entity     biolink:capable_of
METPO:2000008   uses as electron acceptor   chemical entity     biolink:capable_of
```

---

### 2. METPO OWL File (SECONDARY - For Ontology) ✅

**Source:** METPO GitHub main branch OWL file

**Download Configuration:**
```yaml
# download.yaml line 230
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/metpo.owl
  local_name: metpo.owl
```

**Local Location:** `data/raw/metpo.owl`

**Purpose:**
- Used by **ontologies transform** only
- Adds METPO as an ontology in the KG (nodes/edges from ontology itself)
- NOT used for trait mappings

**Usage:**
```python
# kg_microbe/transform_utils/ontologies/ontologies_transform.py:83
"metpo": "metpo.owl",
```

**When Used:**
```bash
poetry run kg transform -s ontologies
```

---

## How METPO Mappings Work

### Data Flow

```
1. Transform initializes (e.g., MetaTraitsTransform)
   ↓
2. Calls load_metpo_mappings("metatraits synonym")
   ↓
3. Fetches metpo_sheet.tsv from GitHub
   ↓
4. Fetches metpo-properties.tsv from GitHub
   ↓
5. Builds tree structure from classes
   ↓
6. Maps synonyms to METPO terms + predicates
   ↓
7. Returns mapping dictionary
```

### Load Function

```python
def load_metpo_mappings(synonym_column: str) -> Dict[str, Dict[str, str]]:
    """
    Load METPO mappings from METPO classes ROBOT template file.
    
    :param synonym_column: Column to use for synonyms
        Examples: 
        - "metatraits synonym"
        - "bacdive keyword synonym"
        - "madin synonym or field"
        - "bactotraits related synonym"
    
    :return: Dictionary mapping synonyms to METPO info
        Format: {
            synonym: {
                'curie': 'METPO:1000602',
                'label': 'aerobic',
                'predicate': 'has phenotype',
                'inferred_category': 'biolink:PhenotypicQuality'
            }
        }
    """
```

### Synonym Columns Available

Each transform uses a different synonym column:

| Transform | Synonym Column | Source Data |
|-----------|----------------|-------------|
| metatraits | "metatraits synonym" | MetaTraits database |
| bacdive | "bacdive keyword synonym" | BacDive API |
| bactotraits | "bactotraits related synonym" | BactoTraits database |
| madin_etal | "madin synonym or field" | Madin et al. dataset |

---

## Relations/Predicates Source

### Question: Are relations obtained from the OWL file?

**Answer: NO** - Relations come from **metpo-properties.tsv**, not the OWL file.

### How Predicates Are Determined

**From metpo-properties.tsv:**

1. Load properties sheet with RANGE and biolink equivalent
2. Build mapping: RANGE class label → predicate

Example from metpo-properties.tsv:
```tsv
ID              label                      RANGE                    biolink equivalent
METPO:2000002   assimilates               chemical entity          biolink:interacts_with
METPO:2000007   degrades                  chemical entity          biolink:capable_of
METPO:2000701   has growth temperature    temperature phenotype    biolink:has_attribute
```

**In code:**
```python
def _load_metpo_properties():
    # Load properties sheet
    # Extract RANGE → predicate mapping
    
    range_to_predicate = {
        "chemical entity": {
            "label": "assimilates",
            "biolink_equivalent": "biolink:interacts_with"
        },
        ...
    }
    
    return range_to_predicate
```

**Predicate resolution logic:**
```python
# For a trait like "aerobic"
# 1. Find in metpo_sheet.tsv → METPO:1000602 (aerobic)
# 2. Find parent with biolink equivalent → METPO:1000601 (oxygen preference)
# 3. Use parent's label to lookup in properties → "has phenotype"
# 4. Return predicate: "has phenotype" (biolink:has_phenotype)
```

---

## Available METPO Files on GitHub

### Currently Downloaded

From `https://github.com/berkeleybop/metpo/tree/main/src/templates`:

| File | Used? | Purpose |
|------|-------|---------|
| **metpo_sheet.tsv** | ✅ YES | Class definitions with synonyms |
| **metpo-properties.tsv** | ✅ YES | Predicate definitions |
| deprecated.tsv | ❌ NO | Deprecated terms |
| stubs.tsv | ❌ NO | Placeholder/stub terms |

### Potentially Useful Additional Files

**1. deprecated.tsv**
- Could warn users about deprecated terms
- Could auto-map to replacement terms
- **Recommendation:** Consider adding as reference

**2. stubs.tsv**
- Placeholder terms for future development
- Probably not needed for production use

---

## Why TSVs Instead of OWL?

### Advantages of TSV Templates

1. **Synonym columns** - Multiple data source mappings in one file
2. **ROBOT template format** - Structured, human-readable
3. **Lightweight** - Faster to parse than OWL
4. **Direct access** - No OWL parsing library needed
5. **Version pinning** - Uses tagged release (2026-03-24)

### OWL File Use Case

**Only needed for:**
- Adding METPO ontology itself to the KG
- Ontology browsing/visualization tools
- Formal reasoning (not currently used)

**Not needed for:**
- Trait mappings (TSVs sufficient)
- Predicate lookups (TSVs sufficient)

---

## Version Control

### Current Version Pinning

```python
# Uses tagged release 2026-03-24
METPO_CLASSES_ROBOT_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/..."
)
```

**Benefits:**
- Stable, reproducible builds
- Won't break if METPO main branch changes
- Explicit version control

**OWL file uses main branch:**
```yaml
url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/metpo.owl
```

**Potential issue:** Could change unexpectedly

**Recommendation:** Consider pinning OWL to same tag:
```yaml
url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/metpo.owl
```

---

## What Could Be Enhanced

### Option 1: Download deprecated.tsv

**Purpose:** Warn about deprecated terms, map to replacements

**Implementation:**
```python
METPO_DEPRECATED_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/deprecated.tsv"
)

def load_deprecated_metpo_terms():
    # Load deprecated terms
    # Return mapping: old_id → new_id
    pass
```

**Use case:**
- Check if any mappings use deprecated terms
- Auto-upgrade to current terms

### Option 2: Cache TSVs Locally

**Current:** Fetch from GitHub on every transform run

**Alternative:** Download and cache locally
```yaml
# download.yaml
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo_sheet.tsv
  local_name: metpo_sheet.tsv
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo-properties.tsv
  local_name: metpo-properties.tsv
```

**Benefits:**
- Faster (no network request)
- Works offline
- Guaranteed version consistency

**Tradeoffs:**
- Need to explicitly update files
- Larger repo size

### Option 3: Add More Synonym Columns

**Current columns used:**
- metatraits synonym
- bacdive keyword synonym
- madin synonym or field
- bactotraits related synonym

**Available but unused:**
- confirmed exact synonym
- literature mining related synonyms

**Could add more transforms or enhance existing ones**

---

## Current Architecture Summary

### ✅ What's Working Well

1. **TSV templates as primary source** - Correct approach
2. **Version pinning** - Stable 2026-03-24 tag
3. **Dynamic fetching** - No manual file updates needed
4. **Multiple synonym sources** - Each transform uses appropriate column
5. **Hierarchical predicate inference** - Smart parent-based lookup

### ⚠️ Potential Improvements

1. **Pin OWL file to tag** - Currently uses main branch
2. **Consider caching TSVs locally** - For offline/faster runs
3. **Add deprecated.tsv** - Track deprecated terms
4. **Document version updates** - When to update METPO version

---

## Files Reference

### In kg-microbe Repository

**Source Code:**
```
kg_microbe/utils/mapping_file_utils.py
  - METPO_CLASSES_ROBOT_TEMPLATE_URL
  - METPO_PROPERTIES_ROBOT_TEMPLATE_URL
  - load_metpo_mappings()
  - _build_metpo_tree()
  - _load_metpo_properties()
```

**Downloaded Data:**
```
data/raw/metpo.owl          (from main branch)
data/raw/metpo.json         (generated by ontologies transform)
```

**Configuration:**
```
download.yaml               (line 230: metpo.owl download)
```

### On METPO GitHub

**Repository:** https://github.com/berkeleybop/metpo

**Template Files (src/templates/):**
```
metpo_sheet.tsv             ← Classes with synonyms (USED)
metpo-properties.tsv        ← Predicates/properties (USED)
deprecated.tsv              ← Deprecated terms (NOT USED)
stubs.tsv                   ← Placeholder terms (NOT USED)
```

**Ontology Files:**
```
metpo.owl                   ← Main ontology (USED for ontologies transform)
metpo.json                  ← JSON-LD format (NOT USED)
metpo.obo                   ← OBO format (NOT USED)
```

---

## Recommendations

### 1. ✅ Current Approach is Correct

**The metatraits mappings are already from the correct location:**
- Using TSV templates from METPO GitHub ✅
- Using appropriate synonym columns ✅
- Using tagged release for stability ✅

### 2. Consider Minor Enhancements

**Pin OWL file to tag:**
```yaml
# download.yaml
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/metpo.owl
  local_name: metpo.owl
```

**Optionally cache TSVs locally:**
```yaml
# download.yaml
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo_sheet.tsv
  local_name: metpo_sheet.tsv
- url: https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo-properties.tsv
  local_name: metpo-properties.tsv
```

Then update mapping_file_utils.py to use local files if available.

### 3. No Need to Download Additional TSVs

**Currently not needed:**
- deprecated.tsv (no deprecated terms in current usage)
- stubs.tsv (placeholder terms, not production-ready)

**Could add later if:**
- METPO deprecates terms we're using
- Need to track term evolution

---

## Conclusion

**Q1: Where is the METPO data with mappings and properties to metatraits in this repo?**

**A:** Fetched dynamically from METPO GitHub TSV templates:
- `metpo_sheet.tsv` - Classes/synonyms
- `metpo-properties.tsv` - Predicates
- Tagged release: 2026-03-24
- Location in code: `kg_microbe/utils/mapping_file_utils.py`

**Q2: Are the relations obtained from the OWL file?**

**A:** NO - Relations come from `metpo-properties.tsv`, not the OWL file.
- OWL file only used for ontologies transform
- Predicates resolved via TSV properties sheet

**Q3: The metatraits mappings already in use in kg-microbe are from the correct location likely**

**A:** YES - ✅ Confirmed correct:
- Using official METPO GitHub TSV templates
- Using tagged release (2026-03-24)
- Using appropriate synonym columns for each transform
- Predicate resolution via properties sheet

**Q4: We could be downloading additional METPO TSVs (mappings, properties) from the METPO github**

**A:** Already downloading the important ones!
- ✅ metpo_sheet.tsv - fetched dynamically
- ✅ metpo-properties.tsv - fetched dynamically
- ❌ deprecated.tsv - not needed currently
- ❌ stubs.tsv - not needed currently

**Current implementation is optimal.** Only minor enhancement would be to pin OWL file to tag instead of main branch.
