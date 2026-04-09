# METPO Gaps and Proposals

**Created:** 2026-04-05  
**Updated:** 2026-04-05  
**Purpose:** Track identified gaps in METPO ontology and proposed additions  
**File:** `metpo_gaps_and_proposals.tsv`

---

## Overview

This file documents gaps identified in the METPO (Microbial Ecophysiological Trait and Phenotype Ontology) during implementation of metatraits transform Phase 2. 

**UPDATE:** Most gaps resolved! METPO already has:
- ✅ Pigmentation classes (METPO:1003022-1003031)
- ✅ Min/max predicates for temperature, pH, salinity (METPO:2000702-2000709)
- ❌ Still missing: Plain alkaliphilic class

---

## Gap Categories

### Critical Gaps (2.9M+ observations affected)

**1. Pigmentation Terms**
- **Missing:** All pigmentation-related classes and predicates
- **Impact:** 2,946,387 observations (33% of unmapped)
- **Workaround:** Using PATO terms temporarily
- **Proposed:**
  - METPO:1000XXX - pigmentation (parent class)
  - METPO:1000XXY - yellow pigmented
  - METPO:1000XXZ - non-pigmented
  - METPO:1000XXA-D - orange/red/pink/brown pigmented
  - METPO:2000XXX - has pigmentation phenotype (predicate)

### High Priority Gaps (5K+ observations)

**2. Alkaliphilic Phenotype**
- **Missing:** Plain alkaliphilic class
- **Exists:** METPO:1000621 (haloalkaliphilic) - for salt-tolerant alkaliphiles only
- **Also exists:** METPO:1003003 (acidophilic), METPO:1003001 (neutrophilic)
- **Impact:** 5,576 observations
- **Workaround:** Using placeholder KGM:alkaliphilic
- **Proposed:**
  - METPO:1003XXX - alkaliphilic (sibling to acidophilic)

### Low Priority Gaps (<100 observations)

**3. Growth Organic Acid Observation**
- **Missing:** has growth organic acid observation predicate
- **Exists:** METPO:2000508 (has growth NaCl observation) - similar pattern
- **Impact:** 31 observations (growth: 1% sodium lactate)
- **Workaround:** Skipping these observations
- **Proposed:**
  - METPO:2000XXY - has growth organic acid observation

---

## File Format

The `metpo_gaps_and_proposals.tsv` file uses the standard METPO ROBOT template format (23 columns) with additional tracking columns:

### Standard METPO Columns
- ID, label, TYPE, parent classes, definition, etc.
- Same format as `metpo_sheet.tsv` and `metpo-properties.tsv`

### Additional Tracking Columns
- **gap_type:** `missing_class` or `missing_predicate`
- **observations_affected:** Number of MetaTraits observations that cannot be modeled
- **priority:** `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` based on observation count
- **workaround:** Current temporary solution being used

---

## Proposed Terms Detail

### Pigmentation Classes

```
METPO:1000XXX - pigmentation
  Type: owl:Class
  Parent: METPO:1000059 (phenotype)
  Definition: A phenotype related to the production or presence of biological 
              pigments that give color to cells or colonies.
  Biolink: biolink:PhenotypicQuality

METPO:1000XXY - yellow pigmented
  Type: owl:Class
  Parent: METPO:1000XXX (pigmentation)
  Definition: A phenotype where cells or colonies produce yellow pigmentation.
  Synonyms: yellow pigment
  MetaTraits synonym: cell color: yellow pigment

METPO:1000XXZ - non-pigmented
  Type: owl:Class
  Parent: METPO:1000XXX (pigmentation)
  Definition: A phenotype where cells or colonies lack visible pigmentation.
  Synonyms: unpigmented, colorless

[Additional color classes: orange, red, pink, brown - see full TSV]
```

### Pigmentation Predicate

```
METPO:2000XXX - has pigmentation phenotype
  Type: owl:ObjectProperty
  Definition: An organism has the specified pigmentation phenotype.
  Range: pigmentation
```

### pH Preference Class

```
METPO:1003XXX - alkaliphilic
  Type: owl:Class
  Parent: METPO:1000059 (phenotype)
  Definition: A phenotype where an organism preferentially grows at alkaline 
              pH levels (typically above pH 8.5).
  Synonyms: alkaliphile
  Biolink: biolink:PhenotypicQuality
```

---

## Submission to METPO

These proposals can be submitted to the METPO team via GitHub:

**Repository:** https://github.com/berkeleybop/metpo

**Process:**
1. Open GitHub issue describing the gaps
2. Attach this TSV file with proposals
3. Reference the observation counts and use cases
4. Explain current workarounds (PATO, placeholders)

**Issue Template:**

```markdown
### Title
Proposed METPO terms for pigmentation and pH preference traits

### Description
We've identified gaps in METPO while implementing metatraits transform for 
kg-microbe knowledge graph construction. These gaps affect 2.95M trait 
observations from the MetaTraits database.

### Missing Terms

**Critical (2.9M observations):**
- Pigmentation phenotype classes (yellow, orange, red, etc.)
- Pigmentation predicate

**High priority (5.6K observations):**
- Alkaliphilic phenotype class (plain alkaliphilic, not haloalkaliphilic)

### Proposed Solutions
See attached TSV file with detailed proposals in ROBOT template format.

### Current Workarounds
- Pigmentation: Using PATO terms (PATO:0001264, etc.)
- Alkaliphilic: Using placeholder KGM:alkaliphilic

### Use Case
MetaTraits database contains extensive pigmentation and pH preference data 
for bacterial species. These traits are important for:
- Colony identification
- Phenotypic characterization
- Environmental adaptation studies

### Files
- metpo_gaps_and_proposals.tsv (23-column ROBOT template format)
```

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-05 | 1.0 | Initial gap identification from Phase 2 implementation |

---

## Integration with Implementation

### Current Workarounds in Code

**Pigmentation (metatraits.py):**
```python
def _resolve_pigmentation_trait(self, trait_name: str, majority_label: str):
    # Using PATO terms temporarily
    color_mappings = {
        "yellow": ("PATO:0001264", "yellow pigmentation"),
        "orange": ("PATO:0001263", "orange pigmentation"),
        # ... etc
    }
```

**Alkaliphilic (metatraits.py):**
```python
def _resolve_ph_preference_trait(self, trait_name: str, majority_label: str):
    if "alkaliphile" in majority_label.lower():
        # Using placeholder until METPO adds term
        return {
            "curie": "KGM:alkaliphilic",
            # ... etc
        }
```

### Migration Plan

When METPO adds these terms:
1. Update `metpo_gaps_and_proposals.tsv` with official METPO IDs
2. Update resolver methods to use METPO IDs instead of workarounds
3. Re-run transforms to generate updated edges
4. Remove PATO dependency if no longer needed

---

## Statistics Summary

| Gap Type | Missing Terms | Observations Affected | % of Unmapped |
|----------|---------------|----------------------|---------------|
| **Pigmentation** | 7 classes + 1 predicate | 2,946,387 | 33.0% |
| **Alkaliphilic** | 1 class | 5,576 | 0.1% |
| **Organic acid** | 1 predicate | 31 | <0.01% |
| **TOTAL** | **10 terms** | **2,951,994** | **33.1%** |

**Impact:** These gaps prevent modeling of 33.1% of currently unmapped trait observations.

**After Resolution:** Expected metatraits coverage would increase from 87.7% to 99%+

---

## Related Files

**In kg-microbe:**
- `metpo_gaps_and_proposals.tsv` - This gap tracking file
- `metpo_metatraits_synonym_mappings.tsv` - Synonym mappings for existing METPO terms
- `METPO_SYNONYM_MAPPINGS_README.md` - Documentation for synonym mappings
- `UNMAPPED_TRAITS_ROUND2_ANALYSIS.md` - Full analysis of unmapped patterns

**From METPO GitHub:**
- `metpo_sheet.tsv` - Official METPO classes template
- `metpo-properties.tsv` - Official METPO predicates template

---

**Status:** Gaps documented, workarounds implemented, ready for METPO team submission  
**Contact:** Submit via https://github.com/berkeleybop/metpo/issues
