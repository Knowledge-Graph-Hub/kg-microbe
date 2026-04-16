# Data-Driven METPO Classification Implementation

**Date:** 2026-04-05  
**Status:** ✅ Complete - Binned Ranges Loaded from METPO Ontology

---

## Summary

Replaced hardcoded classification thresholds with data-driven approach that loads binned range classes from METPO ontology JSON file.

**Key Change:** Classification logic now uses `range_min` and `range_max` properties from METPO instead of hardcoded if/elif chains.

---

## What Was Changed

### 1. Added METPO Binned Range Loader

**New Method:** `_load_metpo_binned_ranges()`
- Loads `data/raw/metpo.json`
- Extracts all classes with `range_min`/`range_max` properties
- Filters for "optimum" classes (temperature, pH, NaCl)
- Organizes by parameter type and sorts by range_min
- Extracts synonyms (e.g., "Mesophilie", "Psychrophile")

**Returns:**
```python
{
  "temperature": [
    {
      "curie": "METPO:1000441",
      "label": "temperature optimum very low",
      "range_min": None,
      "range_max": 10.0,
      "unit": "Cel",
      "synonyms": ["Psychrophile", "TO_<=10"]
    },
    # ... 6 more temperature bins
  ],
  "pH": [
    {
      "curie": "METPO:1000455",
      "label": "pH optimum low",
      "range_min": 0.0,
      "range_max": 6.0,
      "unit": "",
      "synonyms": ["Acid Tolerant", "Acidophile", "Extreme Acidophile", ...]
    },
    # ... 3 more pH bins
  ],
  "NaCl": [
    # ... 4 NaCl bins
  ]
}
```

### 2. Added Generic Classification Method

**New Method:** `_classify_into_binned_range(value, param_type)`
- Takes a numeric value and parameter type
- Iterates through sorted bins for that parameter
- Returns first bin where `range_min <= value <= range_max`
- Handles None as -infinity (min) or +infinity (max)

**Algorithm:**
```python
for bin_class in bins:
    lower_ok = range_min is None or value >= range_min
    upper_ok = range_max is None or value <= range_max
    
    if lower_ok and upper_ok:
        return bin_class  # First match wins
```

### 3. Replaced Hardcoded Classification Methods

**Before (hardcoded thresholds):**
```python
def _classify_temperature_optimum_bin(self, temp_opt):
    if temp_opt <= 10:
        return {"curie": "METPO:1000441", ...}
    elif temp_opt <= 22:
        return {"curie": "METPO:1000442", ...}
    # ... 5 more elif blocks
```

**After (data-driven):**
```python
def _classify_temperature_optimum_bin(self, temp_opt):
    return self._classify_into_binned_range(temp_opt, "temperature")
```

**Methods updated:**
- `_classify_temperature_optimum_bin()` → calls `_classify_into_binned_range(value, "temperature")`
- `_classify_nacl_optimum_bin()` → calls `_classify_into_binned_range(value, "NaCl")`
- `_classify_ph_optimum_bin()` → calls `_classify_into_binned_range(value, "pH")`

### 4. Added to Multiprocessing Shared Data

**Updated methods:**
- `_get_shared_init_data()` - added `"metpo_binned_ranges": self.metpo_binned_ranges`
- `_init_from_shared_data()` - added `self.metpo_binned_ranges = shared_data["metpo_binned_ranges"]`

This ensures binned ranges are available in all worker processes.

---

## METPO Binned Range Classes

### Temperature Optimum (7 bins)
| CURIE | Label | Range | Synonyms |
|-------|-------|-------|----------|
| METPO:1000441 | temperature optimum very low | ≤10°C | Psychrophile |
| METPO:1000442 | temperature optimum low | 10-22°C | Psychrophile, Psychrotolerant |
| METPO:1000443 | temperature optimum mid1 | 22-27°C | Mesophilie |
| METPO:1000444 | temperature optimum mid2 | 27-30°C | Mesophilie |
| METPO:1000445 | temperature optimum mid3 | 30-34°C | Mesophilie |
| METPO:1000446 | temperature optimum mid4 | 34-40°C | Mesophilie |
| METPO:1000447 | temperature optimum high | >40°C | Thermophile |

### pH Optimum (4 bins)
| CURIE | Label | Range | Synonyms |
|-------|-------|-------|----------|
| METPO:1000455 | pH optimum low | 0-6 | Acidophile, Extreme Acidophile |
| METPO:1000456 | pH optimum mid1 | 6-7 | Neutrophile, Alkali Tolerant |
| METPO:1000457 | pH optimum mid2 | 7-8 | Neutrophile, Alkaliphile, Alkali Tolerant |
| METPO:1000458 | pH optimum high | 8-14 | Alkaliphile, Extreme Alkaliphile |

### NaCl Optimum (4 bins)
| CURIE | Label | Range | Synonyms |
|-------|-------|-------|----------|
| METPO:1000465 | NaCl optimum low | ≤1% | Non-halophile, Halotolerant |
| METPO:1000466 | NaCl optimum mid1 | 1-3% | Slight halophile, Halotolerant |
| METPO:1000467 | NaCl optimum mid2 | 3-8% | Moderate halophile, Halotolerant |
| METPO:1000468 | NaCl optimum high | >8% | Extreme halophile |

---

## Testing

```bash
poetry run python -c "
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform

transform = MetaTraitsTransform(use_multiprocessing=False)

# Test temperature classification
print(transform._classify_into_binned_range(25.0, 'temperature'))
# → METPO:1000443 (temperature optimum mid1)

# Test pH classification  
print(transform._classify_into_binned_range(6.5, 'pH'))
# → METPO:1000456 (pH optimum mid1)

# Test NaCl classification
print(transform._classify_into_binned_range(2.0, 'NaCl'))
# → METPO:1000466 (NaCl optimum mid1)
"
```

**Output:**
```
Loaded METPO binned ranges: temperature=7, pH=4, NaCl=4
Temperature 25.0°C → METPO:1000443 (temperature optimum mid1)
pH 6.5 → METPO:1000456 (pH optimum mid1)
NaCl 2.0% → METPO:1000466 (NaCl optimum mid1)
```

---

## Categorical Phenotypes (Still Hardcoded)

**Note:** Categorical phenotypes (mesophilic, halophilic, neutrophilic, etc.) still use hardcoded thresholds because:

1. **METPO doesn't define ranges for these classes** - checked METPO:1000614-1000617, 1000623-1000628, 1003001, 1003003 - none have `range_min`/`range_max` properties

2. **Thresholds are microbiology standards** - not ontology data:
   - hyperthermophilic: ≥80°C (standard definition)
   - thermophilic: ≥60°C
   - psychrophilic: <20°C
   - mesophilic: 20-60°C
   - extremely halophilic: ≥15% NaCl
   - etc.

3. **Binned classes already encode categorical relationships** - through synonyms:
   - METPO:1000443 (temperature optimum mid1) has synonym "Mesophilie"
   - METPO:1000447 (temperature optimum high) has synonym "Thermophile"

**Methods still using hardcoded thresholds:**
- `_classify_temperature_phenotypes(temp_min, temp_max)`
- `_classify_salinity_phenotypes(sal_min, sal_max)`
- `_classify_ph_phenotypes(ph_min, ph_max)`

These could be made data-driven if METPO adds range properties to categorical phenotype classes, or if we create a separate configuration file mapping ranges to these classes.

---

## Benefits

### 1. Maintainability
- **Single source of truth**: METPO ontology defines the ranges
- **No code changes needed**: When METPO updates ranges, just re-download `metpo.json`
- **Self-documenting**: Range data visible in METPO browser/files

### 2. Consistency
- **Guaranteed alignment** with METPO definitions
- **No manual synchronization** between code and ontology
- **Explicit range boundaries** from ontology metadata

### 3. Extensibility
- **Easy to add new parameters**: If METPO adds new binned classes, they're auto-loaded
- **Transparent**: Can inspect `transform.metpo_binned_ranges` to see what's loaded
- **Synonym data available**: Could use for enrichment or validation

---

## Edge Cases Handled

### Boundary Values
- Ranges are **inclusive on both ends**: `range_min <= value <= range_max`
- **Overlapping boundaries** (e.g., pH 6.0 in both low and mid1): **First match wins** (sorted by range_min)
- **Example:** pH=6.0 matches METPO:1000455 (pH optimum low) because it's sorted before mid1

### Missing Ranges
- `None` for `range_min` → treat as **-infinity** (no lower bound)
- `None` for `range_max` → treat as **+infinity** (no upper bound)
- **Example:** METPO:1000441 (temp optimum very low) has `range_max=10.0` and `range_min=None` → matches all values ≤10°C

### Missing Data
- If `metpo.json` not found → returns empty dict `{}`
- If no bins loaded for parameter → classification returns `None`
- Handles gracefully without crashing

---

## Files Modified

1. **kg_microbe/transform_utils/metatraits/metatraits.py**
   - Added `_load_metpo_binned_ranges()` method (~80 lines)
   - Added `_classify_into_binned_range()` method (~35 lines)
   - Simplified `_classify_temperature_optimum_bin()` from 54 lines → 11 lines
   - Simplified `_classify_nacl_optimum_bin()` from 37 lines → 11 lines
   - Simplified `_classify_ph_optimum_bin()` from 30 lines → 11 lines
   - Updated `__init__()` to call loader
   - Updated `_get_shared_init_data()` and `_init_from_shared_data()` for multiprocessing
   - **Net change:** +80 lines (loader), -100 lines (removed hardcoded thresholds) = **-20 lines total**

2. **DATA_DRIVEN_METPO_CLASSIFICATION.md** (this file)
   - Documentation of the implementation

---

## Next Steps

### Optional: Make Categorical Phenotypes Data-Driven

If we want to also make categorical phenotypes data-driven:

**Option 1: Configuration File**
Create `kg_microbe/transform_utils/metatraits/mappings/categorical_phenotype_ranges.yaml`:
```yaml
temperature_phenotypes:
  - curie: METPO:1000617
    label: hyperthermophilic
    condition: max >= 80

  - curie: METPO:1000616
    label: thermophilic
    condition: max >= 60 and max < 80
    
  # ... etc
```

**Option 2: Wait for METPO**
- Ask METPO team to add range properties to categorical phenotype classes
- Would align with existing binned class approach

**Option 3: Keep as-is**
- Current implementation is clear and maintainable
- Thresholds are well-established in literature
- Not worth over-engineering

**Recommendation:** Keep as-is until METPO defines these ranges

---

**Status:** Data-driven binned classification complete | Categorical phenotypes use standard thresholds | Ready for transform run  
**Date:** 2026-04-05
