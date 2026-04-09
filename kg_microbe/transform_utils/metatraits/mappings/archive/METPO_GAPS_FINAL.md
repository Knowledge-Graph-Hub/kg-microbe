# METPO Gaps - Final Assessment

**Date:** 2026-04-05  
**Updated:** 2026-04-06 (confirmed alkaliphilic still needed, predicates now 100% data-driven)  
**Status:** ⚠️ 3 Minor Gaps + 1 Major Issue Identified  
**METPO Coverage:** 99.7% of needed terms exist, but synonym quality needs improvement  

---

## Executive Summary

After thorough investigation, **METPO already has 99.7% of what we need**:

- ✅ Temperature min/max predicates (METPO:2000702/2000703)
- ✅ pH min/max predicates (METPO:2000705/2000706)
- ✅ Salinity min/max predicates (METPO:2000708/2000709)
- ✅ Temperature phenotype classes (1000614-1000617, 1000720)
- ✅ Salinity phenotype classes (1000623-1000628)
- ✅ pH phenotype classes (1003001, 1003003, 1003006, 1003007)
- ✅ Pigmentation classes (1003022-1003031) - 10 colors!
- ✅ Fermentation predicates (2000011, 2000037)

**Issues identified:**
1. **Missing terms** (3): alkaliphilic, non-pigmented, organic acid observation
2. **Incorrect synonyms** (1): ~20-30 negative predicates have wrong synonyms

---

## Gap 1: Alkaliphilic ⚠️ HIGH PRIORITY

### Missing
**METPO:1003XXX - alkaliphilic**

### What Exists
- ✅ METPO:1003001 - neutrophilic
- ✅ METPO:1003003 - acidophilic
- ✅ METPO:1003006 - obligately acidophilic
- ✅ METPO:1003007 - facultatively acidophilic
- ✅ METPO:1000621 - haloalkaliphilic (only for salt-tolerant alkaliphiles)

### Why Needed
- MetaTraits has pH preference data with "alkaliphile" values
- Affects 5,576 observations
- Sibling term to existing acidophilic/neutrophilic
- Plain alkaliphilic (not salt-dependent) is missing

### Proposed Addition
```tsv
ID: METPO:1003XXX
label: alkaliphilic
TYPE: owl:Class
parent classes: METPO:1000059 (phenotype)
definition: A phenotype where an organism preferentially grows at alkaline pH levels (typically above pH 8.5).
biolink close match: biolink:PhenotypicQuality
confirmed exact synonym: alkaliphile
metatraits synonym: pH preference: alkaliphile
```

### Current Workaround
Using placeholder: `KGM:alkaliphilic`

**Status as of 2026-04-06:** This is now the **ONLY remaining hardcoded mapping** in the metatraits transform. All other mappings (trophic modes, phenotypes, temperature/pH/salinity phenotypes, growth patterns, material fallbacks, and predicates) are now 100% data-driven from METPO ontology and mapping files.

**Impact:** 2 occurrences in code (pH classification and pH preference traits)

### Usage Pattern
```python
# Organism with pH minimum >8.5
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1003XXX  # alkaliphilic
```

---

## Gap 2: Non-Pigmented ⚠️ LOW PRIORITY

### Missing
**METPO:1003XXX - non-pigmented**

### What Exists
- ✅ METPO:1003022 - black pigmented
- ✅ METPO:1003023 - brown pigmented
- ✅ METPO:1003024 - cream pigmented
- ✅ METPO:1003025 - green pigmented
- ✅ METPO:1003026 - orange pigmented
- ✅ METPO:1003027 - pink pigmented
- ✅ METPO:1003028 - red pigmented
- ✅ METPO:1003029 - white pigmented
- ✅ METPO:1003030 - yellow pigmented
- ✅ METPO:1003031 - carotenoid pigmentation

### Why Needed
- Companion negative term for pigmentation
- Would complete the pigmentation class family
- Allows explicit assertion of no pigmentation

### Proposed Addition
```tsv
ID: METPO:1003XXX
label: non-pigmented
TYPE: owl:Class
parent classes: METPO:1000059 (phenotype)
definition: A phenotype where cells or colonies lack visible pigmentation.
biolink close match: biolink:PhenotypicQuality
confirmed exact synonym: unpigmented|colorless|non-colored
```

### Current Workaround
Skipping negative pigmentation assertions (only creating edges for positive pigmentation)

### Usage Pattern
```python
# Organism with "cell color: yellow pigment" = false
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1003XXX  # non-pigmented
```

---

## Gap 3: Organic Acid Observation ⚠️ LOW PRIORITY

### Missing
**METPO:2000XXY - has growth organic acid observation**

### What Exists
- ✅ METPO:2000508 - has growth NaCl observation
- ✅ METPO:2000054 - has growth temperature observation
- ✅ METPO:2000239 - has pH observation

### Why Needed
- For boolean growth tests with organic acids
- Pattern: "growth: 1 % sodium lactate"
- Similar structure to existing growth observation predicates
- Affects 31 observations

### Proposed Addition
```tsv
ID: METPO:2000XXY
label: has growth organic acid observation
TYPE: owl:DatatypeProperty
definition: An observation about whether an organism can grow in the presence of a specified concentration of an organic acid.
comment: Similar to has growth NaCl observation (2000508). For recording binary growth test results with organic acids like sodium lactate.
```

### Current Workaround
Skipping these observations (too few to matter)

### Usage Pattern
```python
# Organism tested with "growth: 1 % sodium lactate"
subject: NCBITaxon:562
predicate: METPO:2000XXY  # has growth organic acid observation
object: "1.0"^^xsd:float
qualifier: {compound: "sodium lactate", unit: "%", result: "true"}
```

---

## Issue 4: Incorrect Synonyms on Negative Predicates ⚠️ HIGH PRIORITY

### Problem
**Negative predicates have incorrect synonyms that match their positive counterparts**

Many METPO negative predicates (those with "does not" in the label) have synonyms that should only apply to the positive predicate. This creates semantic ambiguity.

### Examples

**METPO:2000011 "ferments"**
- Synonyms: `["fermentation"]` ✅ **CORRECT**

**METPO:2000037 "does not ferment"**
- Synonyms: `["fermentation"]` ❌ **INCORRECT**
- Should have: `[]` (empty) or `["no fermentation", "lacks fermentation"]`

**METPO:2000006 "uses as carbon source"**
- Synonyms: `["carbon source"]` ✅ **CORRECT**

**METPO:2000031 "does not use as carbon source"**
- Synonyms: `["carbon source"]` ❌ **INCORRECT**
- Should have: `[]` (empty)

**METPO:2000016 "oxidizes"**
- Synonyms: `["oxidation"]` ✅ **CORRECT**

**METPO:2000042 "does not oxidize"**
- Synonyms: `["oxidation"]` ❌ **INCORRECT**
- Should have: `[]` (empty) or `["no oxidation"]`

### Why This is Wrong

1. **Semantic confusion**: "fermentation" should not be a synonym for "does not ferment"
2. **Query ambiguity**: Searching for "fermentation" returns both positive and negative predicates
3. **Lookup fragility**: Requires hacky workarounds (checking label for "does not") instead of clean synonym-based lookup
4. **Data quality**: Violates basic ontology principles - synonyms should be semantically equivalent to the label

### Impact

Affects approximately **20-30 negative predicates** in the 2000xxx range:
- METPO:2000027 "does not assimilate" - synonym: `["assimilation"]` ❌
- METPO:2000028 "does not build acid from" - synonym: `["builds acid from"]` ❌  
- METPO:2000031 "does not use as carbon source" - synonym: `["carbon source"]` ❌
- METPO:2000037 "does not ferment" - synonym: `["fermentation"]` ❌
- METPO:2000038 "does not use for growth" - synonym: `["growth"]` ❌
- METPO:2000039 "does not hydrolyze" - synonym: `["hydrolysis"]` ❌
- METPO:2000042 "does not oxidize" - synonym: `["oxidation"]` ❌
- METPO:2000044 "does not reduce" - synonym: `["reduction"]` ❌
- METPO:2000046 "does not use for respiration" - synonym: `["respiration"]` ❌
- METPO:2000222 "does not produce" - synonym: `["produces"]` ❌
- METPO:2000303 "does not show activity of" - synonym: `["enzyme activity"]` ❌
- ... and more

### Recommended Fix

**Remove incorrect synonyms from all negative predicates:**
```
METPO:2000037 "does not ferment"
  synonyms: []  # Remove "fermentation"
  
METPO:2000042 "does not oxidize"
  synonyms: []  # Remove "oxidation"
  
# Apply to all ~20-30 "does not" predicates
```

**Optionally add proper negative synonyms:**
```
METPO:2000037 "does not ferment"
  synonyms: ["no fermentation", "lacks fermentation", "non-fermenter"]
  
METPO:2000042 "does not oxidize"
  synonyms: ["no oxidation", "cannot oxidize"]
```

### Current Workaround

kg-microbe uses a **hacky workaround** that detects "does not" in the label:

```python
# This shouldn't be necessary!
is_negative = label.lower().startswith("does not ")

if is_negative:
    self.metpo_pattern_to_predicate[pattern_key]["negative"] = curie
else:
    self.metpo_pattern_to_predicate[pattern_key]["positive"] = curie
```

This is **fragile** and relies on naming conventions rather than proper semantic annotation.

### Priority: HIGH

This is a **design flaw** affecting many predicates and should be fixed at the ontology level. While we can work around it in code, it creates technical debt and violates ontology best practices.

---

## Summary Table

| Gap/Issue | Type | Priority | Affected | Workaround | Severity |
|-----------|------|----------|----------|------------|----------|
| **alkaliphilic** | Missing class | HIGH | 5,576 obs | Placeholder KGM:alkaliphilic | Minor |
| **non-pigmented** | Missing class | LOW | Unknown | Skip negative assertions | Minimal |
| **organic acid observation** | Missing predicate | LOW | 31 obs | Skip | Negligible |
| **negative predicate synonyms** | Incorrect synonyms | **HIGH** | ~20-30 predicates | Label-based detection hack | **Major** |
| **TOTAL** | 3 missing + 1 issue | - | - | - | - |

**Observations affected by missing terms:** 5,600 out of 48.5M total (0.01%)  
**Predicates affected by synonym issue:** ~20-30 (all negative predicates)  
**METPO coverage:** 99.99% of observations can be modeled, but synonym quality needs improvement  

---

## Non-Gaps (Initially Thought Missing, But Exist!)

### ✅ Pigmentation Classes
**Initially thought:** METPO lacks pigmentation  
**Reality:** METPO has 10 pigmentation classes (1003022-1003031)  
**Impact:** Saved ~2.9M observations from needing PATO workaround  

### ✅ Quantitative Predicates
**Initially thought:** METPO lacks min/max predicates  
**Reality:** METPO has comprehensive min/max for temp/pH/salinity (2000702-2000709)  
**Impact:** Enables proper quantitative data modeling  

### ✅ Halophily Classes
**Initially thought:** Needed to add salinity tolerance classes  
**Reality:** METPO has 4 halophily classes (1000623-1000628)  
**Impact:** Proper salinity phenotype classification  

### ✅ Temperature Classes
**Initially thought:** Basic psychrophilic/mesophilic/thermophilic  
**Reality:** METPO has 5 temperature classes including facultative (1000614-1000617, 1000720)  
**Impact:** Nuanced temperature tolerance modeling  

### ✅ Fermentation Predicates
**Initially thought:** Needed positive + negative predicates  
**Reality:** METPO has both ferments (2000011) AND does not ferment (2000037)  
**Impact:** Explicit negative assertion capability  

---

## METPO Quality Assessment

### Excellent Coverage
- **Temperature:** 5 phenotype classes + 3 quantitative predicates ✅
- **Salinity:** 4 phenotype classes + 3 quantitative predicates ✅
- **pH:** 4 phenotype classes + 3 quantitative predicates ✅ (missing 1)
- **Pigmentation:** 10 color classes ✅ (missing 1 negative)
- **Fermentation:** Positive + negative predicates ✅

### Well-Designed
- Quantitative predicates separate from phenotype classes ✅
- Both positive and negative assertions supported ✅
- Hierarchical (obligate/facultative) classifications ✅
- Consistent naming conventions ✅

### Minor Improvements Needed
- Add alkaliphilic to complete pH phenotype family
- Add non-pigmented to complete pigmentation family
- Add organic acid observation for consistency

---

## Recommendation

### Priority 1: Fix Negative Predicate Synonyms (HIGH)
**This is a design flaw affecting ~20-30 predicates and should be fixed ASAP**

- Remove incorrect synonyms from all "does not X" predicates
- Affects data quality and ontology usability
- Creates technical debt in downstream applications
- Simple fix: delete incorrect synonyms from predicate definitions

**Submit to METPO immediately:**
- GitHub issue: "Incorrect synonyms on negative predicates"
- High priority - affects ontology quality
- Low effort to fix (remove ~20-30 synonym entries)

### Priority 2: Add Missing Terms (LOW)
**Do NOT hold up implementation for these gaps:**
- Only 0.01% of observations affected
- Workarounds are acceptable
- Can migrate when METPO adds terms

**Proceed with:**
1. Using KGM:alkaliphilic placeholder
2. Skipping non-pigmented (negative assertions less important)
3. Skipping organic acid tests (only 31 observations)

**Submit to METPO:**
- Open GitHub issue proposing these 3 terms
- Low priority - not blocking
- Include usage statistics and rationale

---

## Submission Templates

### Issue 1: Negative Predicate Synonyms (HIGH PRIORITY)

**GitHub Issue Title:**
"BUG: Negative predicates have incorrect synonyms"

**GitHub Issue Body:**
```markdown
## Problem

Many METPO negative predicates (those with "does not" in the label) have synonyms that semantically belong only to their positive counterparts. This creates ambiguity and violates basic ontology principles.

## Examples

**METPO:2000011** "ferments"
- Synonyms: `["fermentation"]` ✅ **CORRECT**

**METPO:2000037** "does not ferment"
- Synonyms: `["fermentation"]` ❌ **WRONG** - "fermentation" is not a synonym for "does not ferment"
- Should be: `[]` (empty) or `["no fermentation", "lacks fermentation"]`

**Additional affected predicates (~20-30 total):**
- METPO:2000031 "does not use as carbon source" - has synonym "carbon source" ❌
- METPO:2000042 "does not oxidize" - has synonym "oxidation" ❌
- METPO:2000044 "does not reduce" - has synonym "reduction" ❌
- METPO:2000222 "does not produce" - has synonym "produces" ❌
- ... and many more

## Why This is Wrong

1. **Semantically incorrect**: A concept and its negation are not synonyms
2. **Query ambiguity**: Searching for "fermentation" returns both positive AND negative predicates
3. **Forces workarounds**: Applications must use hacky label-based detection instead of clean synonym lookup
4. **Violates ontology principles**: Synonyms should be semantically equivalent to the primary label

## Recommended Fix

**Remove incorrect synonyms from all negative predicates:**

For each "does not X" predicate, remove any synonyms that describe the positive action:
```
METPO:2000037 "does not ferment"
  synonyms: []  # Remove "fermentation"
  
METPO:2000042 "does not oxidize"
  synonyms: []  # Remove "oxidation"
```

**Optionally add proper negative synonyms:**
```
METPO:2000037 "does not ferment"
  synonyms: ["no fermentation", "lacks fermentation", "non-fermenting"]
```

## Impact

- Affects ~20-30 predicates in the 2000xxx range
- Simple fix (delete incorrect synonym entries)
- Significantly improves ontology quality and usability
- Removes need for downstream workarounds

## Context

Discovered while implementing data-driven mapping system for kg-microbe project. Currently working around this issue by parsing labels for "does not" prefix, but this is fragile and shouldn't be necessary.
```

---

### Issue 2: Missing Terms (LOW PRIORITY)

**GitHub Issue Title:**
"Propose 3 minor additions to complete phenotype coverage"

### GitHub Issue Body
```markdown
## Summary
After implementing metatraits transform for kg-microbe, we identified 3 minor gaps 
in METPO coverage. METPO has excellent coverage (99.99%), but these additions would 
complete certain phenotype families.

## Proposed Additions

### 1. alkaliphilic (HIGH priority)
- **Type:** Class
- **Parent:** METPO:1000059 (phenotype)
- **Sibling to:** acidophilic (1003003), neutrophilic (1003001)
- **Affects:** 5,576 observations
- **Use case:** MetaTraits pH preference data includes "alkaliphile" values
- **Note:** haloalkaliphilic (1000621) exists but is specific to salt-tolerant alkaliphiles

### 2. non-pigmented (LOW priority)
- **Type:** Class
- **Parent:** METPO:1000059 (phenotype)
- **Companion to:** Existing pigmentation classes (1003022-1003031)
- **Use case:** Explicit negative assertion for non-pigmented organisms

### 3. has growth organic acid observation (LOW priority)
- **Type:** DatatypeProperty
- **Similar to:** has growth NaCl observation (2000508)
- **Affects:** 31 observations
- **Use case:** Boolean growth tests with organic acids (e.g., sodium lactate)

## Detailed Proposals
See attached TSV file in ROBOT template format.

## Current Workarounds
- alkaliphilic: Using placeholder KGM:alkaliphilic
- non-pigmented: Skipping negative assertions
- organic acid: Skipping these tests

## Context
These gaps affect 0.01% of observations. METPO's existing coverage is excellent - 
this request is to complete certain phenotype families for comprehensiveness.
```

---

**Status:** Assessment complete | 3 minor gaps + 1 major synonym issue identified  
**Recommendation:** Submit synonym bug immediately (HIGH), gaps as low priority  
**Date:** 2026-04-05 (updated with Issue 4)
