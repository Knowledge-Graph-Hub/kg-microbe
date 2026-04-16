# Hardcoded Mappings Audit - MetaTraits Transform

**Date:** 2026-04-05  
**Status:** Audit of all hardcoded mappings that should be replaced with METPO-based lookups

---

## Executive Summary

The metatraits transform contains **16 categories of hardcoded mappings** totaling **~80 individual mappings**. These should be replaced with lookups from METPO labels and synonyms to ensure maintainability and alignment with the ontology.

**Categories:**
1. ✅ **METPO predicate → Biolink mappings** (51 entries) - **KEEP** (lookup table, not trait mappings)
2. ❌ **Chemical pattern predicates** (9 entries) - Should use METPO synonyms
3. ❌ **Metabolic pattern predicates** (10 entries) - Should use METPO synonyms
4. ❌ **Hardcoded chemical lookups** (3 entries) - Should use ChEBI loader
5. ❌ **Growth pattern predicates** (4 entries) - Should use METPO synonyms
6. ❌ **Trophic mode mappings** (6 entries) - Should use METPO/GO synonyms
7. ❌ **Aerobic/anaerobic growth** (2 entries) - Should use METPO synonyms
8. ❌ **Phenotype trait mappings** (4 entries) - Should use METPO synonyms
9. ❌ **Temperature phenotype classification** (5 entries) - Should use METPO synonyms/ranges
10. ❌ **Salinity phenotype classification** (4 entries) - Should use METPO synonyms/ranges
11. ❌ **pH phenotype classification** (4 entries) - Should use METPO synonyms/ranges
12. ❌ **Pigmentation color mappings** (9 entries) - Should use METPO synonyms
13. ❌ **Fermentation predicates** (2 entries) - Should use METPO synonyms
14. ❌ **pH preference categorical** (3 entries) - Should use METPO synonyms
15. ❌ **Energy source predicate** (1 entry) - Should use METPO synonyms
16. ❌ **Nitrogen source predicate** (1 entry) - Should use METPO synonyms

**Total to replace:** ~67 hardcoded mappings

---

## Category 1: METPO Predicate → Biolink Mappings ✅ KEEP

**Location:** Lines 55-95  
**Purpose:** Translate METPO predicates to Biolink predicates  
**Status:** This is a legitimate lookup table, not a trait mapping

```python
METPO_PREDICATE_TO_BIOLINK = {
    "METPO:2000101": "biolink:has_attribute",
    "METPO:2000102": "biolink:has_phenotype",
    "METPO:2000103": "biolink:capable_of",
    "METPO:2000001": "biolink:interacts_with",
    "METPO:2000002": "biolink:interacts_with",  # assimilates
    "METPO:2000003": "biolink:produces",  # builds acid from
    # ... 45 more entries
}
```

**Recommendation:** **KEEP** - This is not a trait name mapping, it's a predicate translation table.

---

## Category 2: Chemical Pattern Predicates ❌ REPLACE

**Location:** `_resolve_chemical_trait()` lines 787-795  
**Count:** 9 hardcoded METPO predicates

```python
patterns = [
    (r"^carbon source:\s*(.+)$", "METPO:2000006"),  # uses as carbon source
    (r"^assimilation:\s*(.+)$", "METPO:2000002"),  # assimilates
    (r"^produces:\s*(.+)$", "METPO:2000202"),  # produces
    (r"^ferments:\s*(.+)$", "METPO:2000011"),  # ferments
    (r"^hydrolyzes:\s*(.+)$", "METPO:2000013"),  # hydrolyzes
    (r"^oxidizes:\s*(.+)$", "METPO:2000016"),  # oxidizes
    (r"^reduces:\s*(.+)$", "METPO:2000017"),  # reduces
    (r"^degrades:\s*(.+)$", "METPO:2000007"),  # degrades
    (r"^utilizes:\s*(.+)$", "METPO:2000001"),  # organism interacts with chemical
]
```

**Should be replaced with:** METPO synonym lookup
- Pattern: "carbon source: glucose" 
- METPO should have synonym: "carbon source" → METPO:2000006
- Extract chemical name, look up in METPO synonyms for predicate

---

## Category 3: Metabolic Pattern Predicates ❌ REPLACE

**Location:** `_resolve_metabolic_trait()` lines 844-861  
**Count:** 10 hardcoded METPO predicates + lookup types

```python
patterns = [
    (r"^electron acceptor:\s*(.+)$", "METPO:2000008", "chemical"),
    (r"^electron donor:\s*(.+)$", "METPO:2000009", "chemical"),
    (r"^respiration:\s*(.+)$", "METPO:2000008", "chemical"),
    (r"^reduction:\s*(.+)$", "METPO:2000017", "chemical"),
    (r"^oxidation:\s*(.+)$", "METPO:2000016", "chemical"),
    (r"^oxidation in darkness:\s*(.+)$", "METPO:2000605", "chemical"),
    (r"^denitrification:\s*(.+)$", "METPO:2000017", "chemical"),
    (r"^ammonification:\s*(.+)$", "METPO:2000014", "chemical"),
    (r"^degradation:\s*(.+)$", "METPO:2000007", "material"),
    (r"^hydrolysis:\s*(.+)$", "METPO:2000013", "material"),
]
```

**Should be replaced with:** METPO synonym lookup

---

## Category 4: Hardcoded Chemical Lookups ❌ REPLACE

**Location:** `_resolve_metabolic_trait()` lines 885-889  
**Count:** 3 hardcoded ChEBI IDs

```python
special_compounds = {
    "urea": ("CHEBI:16199", "urea"),
    "esculin": ("CHEBI:4806", "esculin"),
    "starch": ("CHEBI:28017", "starch"),
}
```

**Should be replaced with:** ChEBI loader lookup (already available via `self.chemical_loader`)

**Reason for current hardcoding:** Comments suggest these are missing from unified mappings, but should check if ChEBI loader can find them.

---

## Category 5: Growth Pattern Predicates ❌ REPLACE

**Location:** `_resolve_growth_trait()` lines 927-930  
**Count:** 4 hardcoded METPO predicates

```python
patterns = [
    (r"^growth:\s*(.+)$", "METPO:2000012"),  # uses for growth
    (r"^builds acid from:\s*(.+)$", "METPO:2000003"),  # builds acid from
    (r"^builds gas from:\s*(.+)$", "METPO:2000005"),  # builds gas from
    (r"^builds base from:\s*(.+)$", "METPO:2000004"),  # builds base from
]
```

**Should be replaced with:** METPO synonym lookup

---

## Category 6: Trophic Mode Mappings ❌ REPLACE

**Location:** `_resolve_trophic_trait()` lines 979-1006  
**Count:** 6 hardcoded GO terms

```python
trophic_mappings = {
    "phototrophy": ("GO:0009579", "phototrophic process", "biolink:BiologicalProcess"),
    "chemoheterotrophy": ("GO:0044281", "small molecule metabolic process", "biolink:BiologicalProcess"),
    "photoautotrophy": ("GO:0009541", "photoautotrophic process", "biolink:BiologicalProcess"),
    "photoheterotrophy": ("GO:0009581", "photoheterotrophic process", "biolink:BiologicalProcess"),
    "anoxygenic photoautotrophy": ("GO:0019685", "photosynthesis, anoxygenic", "biolink:BiologicalProcess"),
    "anoxygenic phototrophy": ("GO:0019685", "photosynthesis, anoxygenic", "biolink:BiologicalProcess"),
}
```

**Should be replaced with:** METPO/GO synonym lookup from trait_mapping

**Note:** These may already be in `microbial_mappings` or `trait_mapping` - check before replacing

---

## Category 7: Aerobic/Anaerobic Growth ❌ REPLACE

**Location:** `_resolve_trophic_trait()` lines 1022-1035  
**Count:** 2 hardcoded METPO classes

```python
if trait_name.lower().startswith("aerobic growth"):
    return {
        "curie": "METPO:1001003",  # aerobe phenotype
        "category": "biolink:PhenotypicQuality",
        "name": "aerobe",
        "predicate": "METPO:2000102",  # has phenotype
    }
elif trait_name.lower().startswith("anaerobic growth"):
    return {
        "curie": "METPO:1001004",  # anaerobe phenotype
        "category": "biolink:PhenotypicQuality",
        "name": "anaerobe",
        "predicate": "METPO:2000102",  # has phenotype
    }
```

**Should be replaced with:** METPO synonym lookup for "aerobic growth" and "anaerobic growth"

---

## Category 8: Phenotype Trait Mappings ❌ REPLACE

**Location:** `_resolve_phenotype_trait()` lines 1084-1088  
**Count:** 4 hardcoded METPO classes

```python
phenotype_mappings = {
    "aerotolerant": ("METPO:1001025", "aerotolerant"),
    "facultative anaerobe": ("METPO:1001026", "facultative anaerobe"),
    "acidophilic": ("METPO:1001015", "acidophile"),
    "capnophilic": ("KGM:capnophilic", "capnophilic"),  # No METPO ID
}
```

**Should be replaced with:** METPO synonym lookup (likely already in `trait_mapping`)

---

## Category 9: Temperature Phenotype Classification ❌ REPLACE

**Location:** `_classify_temperature_phenotypes()` lines 1198-1236  
**Count:** 5 hardcoded METPO classes

```python
if temp_max >= 80:
    return {"curie": "METPO:1000617", ...}  # hyperthermophilic
elif temp_max >= 60:
    return {"curie": "METPO:1000616", ...}  # thermophilic
elif temp_max < 20:
    return {"curie": "METPO:1000614", ...}  # psychrophilic
else:
    return {"curie": "METPO:1000615", ...}  # mesophilic

if temp_min < 15:
    return {"curie": "METPO:1000720", ...}  # facultative psychrophilic
```

**Should be replaced with:** 
1. Check if METPO has range properties for these classes
2. If not, create configuration file with thresholds
3. Load from METPO synonyms to link binned ranges to categorical phenotypes

**Note:** Binned optimum classes already have synonyms linking them:
- METPO:1000447 (temperature optimum high) has synonym "Thermophile"
- METPO:1000441 (temperature optimum very low) has synonym "Psychrophile"
- METPO:1000443-1000446 have synonym "Mesophilie"

---

## Category 10: Salinity Phenotype Classification ❌ REPLACE

**Location:** `_classify_salinity_phenotypes()` lines 1275-1302  
**Count:** 4 hardcoded METPO classes

```python
if sal_max >= 15:
    return {"curie": "METPO:1000628", ...}  # extremely halophilic
elif sal_max >= 3:
    return {"curie": "METPO:1000623", ...}  # moderately halophilic
elif sal_max >= 1:
    return {"curie": "METPO:1000625", ...}  # slightly halophilic
else:
    return {"curie": "METPO:1000624", ...}  # non halophilic
```

**Should be replaced with:** METPO synonym-based lookup from binned NaCl classes

**Note:** Binned NaCl classes have synonyms:
- METPO:1000468 (NaCl optimum high) → "Extreme halophile"
- METPO:1000467 (NaCl optimum mid2) → "Moderate halophile"
- METPO:1000466 (NaCl optimum mid1) → "Slight halophile"
- METPO:1000465 (NaCl optimum low) → "Non-halophile"

---

## Category 11: pH Phenotype Classification ❌ REPLACE

**Location:** `_classify_ph_phenotypes()` lines 1342-1374  
**Count:** 4 hardcoded METPO classes

```python
if ph_max < 6.0:
    return {"curie": "METPO:1003003", ...}  # acidophilic
elif ph_min > 8.5:
    return {"curie": "KGM:alkaliphilic", ...}  # METPO gap
elif 5.5 <= ph_min <= 8.5:
    return {"curie": "METPO:1003001", ...}  # neutrophilic
if ph_min < 4.0:
    return {"curie": "METPO:1003006", ...}  # obligately acidophilic
```

**Should be replaced with:** METPO synonym-based lookup from binned pH classes

**Note:** Binned pH classes have synonyms:
- METPO:1000455 (pH optimum low) → "Acidophile", "Extreme Acidophile"
- METPO:1000456-1000457 (pH optimum mid1/mid2) → "Neutrophile"
- METPO:1000458 (pH optimum high) → "Alkaliphile", "Extreme Alkaliphile"

---

## Category 12: Pigmentation Color Mappings ❌ REPLACE

**Location:** `_resolve_pigmentation_trait()` lines 1412-1422  
**Count:** 9 hardcoded METPO classes

```python
color_mappings = {
    "yellow": ("METPO:1003030", "yellow pigmented"),
    "orange": ("METPO:1003026", "orange pigmented"),
    "red": ("METPO:1003028", "red pigmented"),
    "pink": ("METPO:1003027", "pink pigmented"),
    "brown": ("METPO:1003023", "brown pigmented"),
    "white": ("METPO:1003029", "white pigmented"),
    "black": ("METPO:1003022", "black pigmented"),
    "cream": ("METPO:1003024", "cream pigmented"),
    "green": ("METPO:1003025", "green pigmented"),
}
```

**Should be replaced with:** METPO synonym lookup
- METPO classes have labels like "yellow pigmented"
- Pattern: "cell color: yellow pigment" → extract "yellow" → lookup METPO class with label containing "yellow pigmented"

---

## Category 13: Fermentation Predicates ❌ REPLACE

**Location:** `_resolve_fermentation_trait()` line 1467  
**Count:** 2 hardcoded METPO predicates

```python
can_ferment = "true" in majority_label.lower()
predicate = "METPO:2000011" if can_ferment else "METPO:2000037"
```

**Should be replaced with:** METPO synonym lookup for "ferments" and "does not ferment"

---

## Category 14: pH Preference Categorical ❌ REPLACE

**Location:** `_resolve_ph_preference_trait()` lines 1501-1523  
**Count:** 3 hardcoded METPO classes

```python
if "alkaliphile" in majority_label.lower():
    return {"curie": "KGM:alkaliphilic", ...}  # Placeholder
elif "acidophile" in majority_label.lower():
    return {"curie": "METPO:1003003", ...}  # acidophilic
elif "neutrophile" in majority_label.lower():
    return {"curie": "METPO:1003001", ...}  # neutrophilic
```

**Should be replaced with:** METPO synonym lookup
- Trait name: "pH preference"
- Value: "alkaliphile: (100%)" → extract "alkaliphile" → lookup in METPO

---

## Category 15: Energy Source Predicate ❌ REPLACE

**Location:** `_resolve_energy_source()` line 1552  
**Count:** 1 hardcoded METPO predicate

```python
"predicate": "METPO:2000010",  # uses as energy source
```

**Should be replaced with:** METPO synonym lookup for "energy source"

---

## Category 16: Nitrogen Source Predicate ❌ REPLACE

**Location:** `_resolve_nitrogen_source()` line 1581  
**Count:** 1 hardcoded METPO predicate

```python
"predicate": "METPO:2000014",  # uses as nitrogen source
```

**Should be replaced with:** METPO synonym lookup for "nitrogen source"

---

## Replacement Strategy

### Phase 1: Predicate Lookups (Categories 2-5, 13, 15-16)
**Affected:** 30 hardcoded predicates

**Approach:**
1. Check if METPO has metatraits synonyms for these patterns
2. If yes: Use existing METPO mappings from `self.metpo_mappings`
3. If no: Add to `metpo_metatraits_synonym_mappings.tsv`

**Example:**
```python
# OLD (hardcoded):
if trait_name.startswith("carbon source:"):
    predicate = "METPO:2000006"

# NEW (from METPO synonyms):
mapping = self.metpo_mappings.get("carbon source")
if mapping:
    predicate = mapping["curie"]
```

### Phase 2: Categorical Phenotypes (Categories 7-11, 14)
**Affected:** 18 hardcoded phenotype classes

**Approach:**
1. Use binned range class synonyms to infer categorical phenotypes
2. Create reverse lookup: synonym → METPO class
3. Map "Thermophile" → METPO:1000616, etc.

**Example:**
```python
# Load synonym mappings from METPO binned classes
for param_type, bins in self.metpo_binned_ranges.items():
    for bin_class in bins:
        for synonym in bin_class["synonyms"]:
            if "Thermophile" in synonym:
                # Link to thermophilic class
```

### Phase 3: Pigmentation (Category 12)
**Affected:** 9 hardcoded pigmentation classes

**Approach:**
1. Load METPO pigmentation classes from ontology
2. Create lookup by color keyword in label
3. "yellow" in label "yellow pigmented" → METPO:1003030

### Phase 4: Trophic Modes (Category 6)
**Affected:** 6 hardcoded GO terms

**Approach:**
1. Check if already in `trait_mapping` or `microbial_mappings`
2. If not, add to `custom_curies.yaml` or METPO synonym mappings

### Phase 5: Hardcoded Chemicals (Category 4)
**Affected:** 3 hardcoded ChEBI IDs

**Approach:**
1. Test if `self.chemical_loader.find_chebi_by_name()` can find them
2. If yes: Remove hardcoding
3. If no: Keep as fallback, but document why

---

## Implementation Priority

### High Priority (DO FIRST)
1. **Categories 2-3:** Chemical/Metabolic predicates (19 entries)
2. **Category 12:** Pigmentation colors (9 entries)
3. **Categories 9-11:** Temperature/Salinity/pH phenotypes (13 entries)

**Total High Priority:** 41 mappings

### Medium Priority
4. **Categories 5, 13, 15-16:** Growth/Fermentation/Energy/Nitrogen predicates (8 entries)
5. **Categories 7-8:** Aerobic/Anaerobic + simple phenotypes (6 entries)
6. **Category 14:** pH preference categorical (3 entries)

**Total Medium Priority:** 17 mappings

### Low Priority (OPTIONAL)
7. **Category 6:** Trophic modes (6 entries) - May already be in mappings
8. **Category 4:** Special chemicals (3 entries) - Keep as fallback if ChEBI loader fails

**Total Low Priority:** 9 mappings

---

## Verification Checklist

After replacement:
- [ ] No hardcoded `"METPO:XXXXX"` strings in resolver methods
- [ ] No hardcoded `"GO:XXXXX"` strings in resolver methods
- [ ] No hardcoded `"CHEBI:XXXXX"` strings in resolver methods
- [ ] All mappings load from METPO synonyms or configuration files
- [ ] `METPO_PREDICATE_TO_BIOLINK` lookup table retained (legitimate use)
- [ ] Transform produces same edges (regression test)

---

**Status:** Audit complete | 67 hardcoded mappings identified | Replacement strategy defined  
**Date:** 2026-04-05
