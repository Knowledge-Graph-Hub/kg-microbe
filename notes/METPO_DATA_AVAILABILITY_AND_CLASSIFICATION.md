# METPO Data Availability and Classification Strategy

**Date:** 2026-04-05  
**Status:** ✅ Data Available - Need Classification Strategy  

---

## Data Available in MetaTraits

### Confirmed Fields Present

From `ncbi_species_summary.jsonl.gz` and `gtdb_species_summary.jsonl.gz`:

**Temperature:**
- ✅ `temperature minimum` - Median: 14.8 Celsius
- ✅ `temperature maximum` - Median: 37.8 Celsius
- ✅ `temperature growth` - Median: 31.2 Celsius (optimal)

**Salinity:**
- ✅ `salinity minimum` - Median: 1.6 % NaCl (w/v)
- ✅ `salinity maximum` - Median: 3.1 % NaCl (w/v)
- ✅ `salinity growth` - Median: 1.4 % NaCl (w/v) (optimal)

**pH:**
- ✅ `pH minimum` - Median: 4.7 pH
- ✅ `pH maximum` - Median: 8.6 pH
- ✅ `pH growth` - Median: 6.6 pH (optimal)

---

## Classification Strategy Using Min/Max Values

### Temperature Phenotypes (METPO:1000614-1000617)

**Use maximum temperature to classify:**

| Max Temp | METPO Class | ID | Rationale |
|----------|-------------|-----|-----------|
| ≥ 80°C | hyperthermophilic | METPO:1000617 | Can survive extreme heat |
| ≥ 60°C | thermophilic | METPO:1000616 | Can grow at high temps |
| ≥ 45°C and < 60°C | mesophilic | METPO:1000615 | Upper limit is moderate |
| < 45°C and max ≥ 20°C | mesophilic | METPO:1000615 | Typical mesophile range |
| max < 20°C | psychrophilic | METPO:1000614 | Cannot tolerate warmth |

**Additional classification using minimum temperature:**
| Min Temp | Additional Class | ID |
|----------|------------------|-----|
| min < 15°C | facultative psychrophilic | METPO:1000720 | Can grow in cold |

**Example:**
```
temperature minimum: 14.8°C
temperature maximum: 37.8°C
temperature growth: 31.2°C

→ Max temp 37.8°C < 45°C → mesophilic (METPO:1000615)
→ Min temp 14.8°C < 15°C → facultative psychrophilic (METPO:1000720)
→ Both phenotypes assigned!
```

### Salinity Phenotypes (METPO:1000623-1000628)

**Use maximum salinity to classify:**

| Max NaCl % | METPO Class | ID | Rationale |
|------------|-------------|-----|-----------|
| ≥ 15% | extremely halophilic | METPO:1000628 | Requires very high salt |
| ≥ 3% and < 15% | moderately halophilic | METPO:1000623 | Tolerates moderate salt |
| ≥ 1% and < 3% | slightly halophilic | METPO:1000625 | Slight salt tolerance |
| < 1% | non halophilic | METPO:1000624 | No salt requirement |

**Example:**
```
salinity minimum: 1.6% NaCl
salinity maximum: 3.1% NaCl
salinity growth: 1.4% NaCl

→ Max salinity 3.1% → moderately halophilic (METPO:1000623)
→ Min salinity 1.6% > 1% → requires some salt (supports classification)
```

### pH Phenotypes (METPO:1003001, 1003003, 1003XXX)

**Use minimum and maximum pH to classify:**

| pH Range | METPO Class | ID | Rationale |
|----------|-------------|-----|-----------|
| max < 6.0 | acidophilic | METPO:1003003 | Only grows in acidic |
| min > 8.5 | alkaliphilic | METPO:1003XXX* | Only grows in alkaline |
| min ≥ 5.5 and max ≤ 8.5 | neutrophilic | METPO:1003001 | Grows in neutral range |
| min < 5.5 and max > 8.5 | broad pH tolerance | - | Skip or add custom |

*Needs METPO term

**Additional classification using pH range:**
| pH Range | Additional Class | ID |
|----------|------------------|-----|
| min < 4.0 | obligately acidophilic | METPO:1003006 | Requires acid |
| min ≥ 4.0 and max ≤ 6.0 | facultatively acidophilic | METPO:1003007 | Acid-tolerant |

**Example:**
```
pH minimum: 4.7
pH maximum: 8.6
pH growth: 6.6

→ Range spans 4.7-8.6 (neutral + some acid/alkaline tolerance)
→ Optimal 6.6 is neutral
→ neutrophilic (METPO:1003001)
```

---

## Implementation Plan

### Phase 2 (Current - REVISED)

**Change approach from single growth tests to min/max classification:**

#### OLD (incorrect):
```python
# growth: 42 degrees Celsius = true
→ If 42°C → mesophilic
```

#### NEW (correct):
```python
# temperature minimum: 14.8 Celsius
# temperature maximum: 37.8 Celsius
→ Max 37.8°C < 45°C → mesophilic (METPO:1000615)
→ Min 14.8°C < 15°C → facultative psychrophilic (METPO:1000720)
```

### Resolver Updates Needed

**1. Parse quantitative trait names:**
```python
"temperature minimum" → extract value, store as min_temp
"temperature maximum" → extract value, store as max_temp
"salinity minimum" → extract value, store as min_salinity
"salinity maximum" → extract value, store as max_salinity
"pH minimum" → extract value, store as min_ph
"pH maximum" → extract value, store as max_ph
```

**2. Aggregate per taxon:**
```python
# Collect all min/max values for each taxon
tax_data = {
    "NCBITaxon:562": {
        "temp_min": 14.8,
        "temp_max": 37.8,
        "temp_growth": 31.2,
        "salinity_min": 1.6,
        "salinity_max": 3.1,
        "pH_min": 4.7,
        "pH_max": 8.6
    }
}
```

**3. Classify using thresholds:**
```python
def classify_temperature_phenotype(min_temp, max_temp):
    phenotypes = []
    
    # Primary classification based on max temp
    if max_temp >= 80:
        phenotypes.append(("METPO:1000617", "hyperthermophilic"))
    elif max_temp >= 60:
        phenotypes.append(("METPO:1000616", "thermophilic"))
    elif max_temp < 20:
        phenotypes.append(("METPO:1000614", "psychrophilic"))
    else:
        phenotypes.append(("METPO:1000615", "mesophilic"))
    
    # Additional classification based on min temp
    if min_temp < 15:
        phenotypes.append(("METPO:1000720", "facultative psychrophilic"))
    
    return phenotypes
```

### Data Flow Change

**Current (Phase 2 - incorrect):**
```
Single growth test → Phenotype class
"growth: 42 degrees Celsius" → mesophilic
```

**New (Phase 2 - corrected):**
```
Min/max values → Classification → Phenotype classes
temp_min=14.8, temp_max=37.8 → mesophilic + facultative psychrophilic
```

---

## METPO Predicates to Use

### For Quantitative Values (Additional Edges)

**Also create edges with actual min/max values:**

```python
# Temperature
subject: NCBITaxon:562
predicate: METPO:2000702  # has minimum temperature value
object: "14.8"^^xsd:float
qualifier: {unit: "Cel"}

subject: NCBITaxon:562
predicate: METPO:2000703  # has maximum temperature value
object: "37.8"^^xsd:float
qualifier: {unit: "Cel"}

subject: NCBITaxon:562
predicate: METPO:2000701  # has growth temperature value
object: "31.2"^^xsd:float
qualifier: {unit: "Cel"}

# Salinity
subject: NCBITaxon:562
predicate: METPO:2000708  # has minimum salinity value
object: "1.6"^^xsd:float
qualifier: {unit: "%"}

subject: NCBITaxon:562
predicate: METPO:2000709  # has maximum salinity value
object: "3.1"^^xsd:float
qualifier: {unit: "%"}

subject: NCBITaxon:562
predicate: METPO:2000707  # has growth salinity value
object: "1.4"^^xsd:float
qualifier: {unit: "%"}

# pH
subject: NCBITaxon:562
predicate: METPO:2000705  # has minimum pH value
object: "4.7"^^xsd:float

subject: NCBITaxon:562
predicate: METPO:2000706  # has maximum pH value
object: "8.6"^^xsd:float

subject: NCBITaxon:562
predicate: METPO:2000704  # has growth pH value
object: "6.6"^^xsd:float
```

### For Phenotype Classes (Primary Edges)

```python
# Temperature phenotypes (derived from min/max)
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1000615  # mesophilic

subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1000720  # facultative psychrophilic

# Salinity phenotypes (derived from min/max)
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1000623  # moderately halophilic

# pH phenotypes (derived from min/max)
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1003001  # neutrophilic
```

---

## Updated Gap: Alkaliphilic Still Needed

**METPO has:**
- ✅ METPO:1003001 - neutrophilic
- ✅ METPO:1003003 - acidophilic
- ✅ METPO:1003006 - obligately acidophilic
- ✅ METPO:1003007 - facultatively acidophilic

**METPO missing:**
- ❌ Plain alkaliphilic (only has METPO:1000621 haloalkaliphilic)

**Need to propose:**
- METPO:1003XXX - alkaliphilic
- METPO:1003XXY - obligately alkaliphilic (min pH > 8.5)
- METPO:1003XXZ - facultatively alkaliphilic (can grow at pH > 8.5)

---

## Implementation Checklist

### Phase 2 Corrections

- [ ] Remove single growth test resolvers ("growth: 42 degrees Celsius")
- [ ] Add quantitative value parsers ("temperature minimum", "temperature maximum")
- [ ] Implement classification logic using thresholds
- [ ] Create edges for both:
  - [ ] Quantitative values (METPO:2000702/2000703/etc.)
  - [ ] Phenotype classes (METPO:1000614-1000617/etc.)
- [ ] Handle organisms with multiple phenotypes (e.g., mesophilic + facultative psychrophilic)
- [ ] Update METPO gap proposals to remove pigmentation, keep alkaliphilic

### Data Extraction

- [ ] Parse "Median: 14.8 Celsius" format
- [ ] Extract numeric value (14.8)
- [ ] Extract unit (Celsius, % NaCl, pH)
- [ ] Handle "Median:" prefix
- [ ] Handle multiple measurements per taxon

---

## Expected Impact (Revised)

### Current Phase 2 (Incorrect Implementation)
- ❌ Using single growth tests → phenotypes
- Missing actual min/max data
- Losing quantitative information

### Corrected Phase 2 (Proper Implementation)
- ✅ Using min/max values → phenotypes
- ✅ Creating quantitative value edges
- ✅ Better phenotype classification
- ✅ Supporting multiple phenotypes per organism

### Edge Count Impact
**Before:** ~8.9M new edges expected  
**After (corrected):**
- Min/max/optimal quantitative edges: ~1.6M (3 per param per taxon × 3 params × ~180K taxa)
- Phenotype classification edges: ~400K (1-2 phenotypes per taxon × ~180K taxa)
- **Total:** ~2.0M new edges from temperature/pH/salinity alone

---

## Example: Complete Organism Profile

```python
# Organism: Escherichia coli (NCBITaxon:562)

# Quantitative data (from metatraits):
temperature_min = 14.8  # Celsius
temperature_max = 37.8  # Celsius
temperature_growth = 31.2  # Celsius
salinity_min = 1.6  # % NaCl
salinity_max = 3.1  # % NaCl
pH_min = 4.7
pH_max = 8.6
pH_growth = 6.6

# Classification:
# - temp_max 37.8 < 45 → mesophilic
# - temp_min 14.8 < 15 → facultative psychrophilic
# - salinity_max 3.1 ≈ 3% → moderately halophilic
# - pH range 4.7-8.6 with optimal 6.6 → neutrophilic

# Edges created:

# 1. Quantitative values (6 edges)
NCBITaxon:562 METPO:2000702 "14.8"^^xsd:float {unit: Cel}
NCBITaxon:562 METPO:2000703 "37.8"^^xsd:float {unit: Cel}
NCBITaxon:562 METPO:2000708 "1.6"^^xsd:float {unit: %}
NCBITaxon:562 METPO:2000709 "3.1"^^xsd:float {unit: %}
NCBITaxon:562 METPO:2000705 "4.7"^^xsd:float
NCBITaxon:562 METPO:2000706 "8.6"^^xsd:float

# 2. Phenotype classes (4 edges)
NCBITaxon:562 biolink:has_phenotype METPO:1000615  # mesophilic
NCBITaxon:562 biolink:has_phenotype METPO:1000720  # facultative psychrophilic
NCBITaxon:562 biolink:has_phenotype METPO:1000623  # moderately halophilic
NCBITaxon:562 biolink:has_phenotype METPO:1003001  # neutrophilic

# Total: 10 edges per organism (for temp/pH/salinity)
```

---

**Status:** Data confirmed available | Classification strategy defined | Implementation needed  
**Next:** Update resolvers to use min/max classification instead of single growth tests  
**Date:** 2026-04-05
