# METPO Existing Quantitative Predicates

**Date:** 2026-04-05  
**Status:** ✅ METPO Already Has Min/Max/Range Predicates  

---

## Summary

METPO **already has comprehensive min/max/range predicates** for:
- ✅ Temperature
- ✅ pH
- ✅ Salinity (NaCl)
- ✅ Cell dimensions (length, width)
- ✅ Generic min/max observed values

**No new predicates needed** - we just need to use them correctly!

---

## Temperature Predicates

### Quantitative Values (Data Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000701** | has growth temperature value | Optimal/typical growth temperature |
| **METPO:2000702** | has minimum temperature value | Minimum temperature for growth |
| **METPO:2000703** | has maximum temperature value | Maximum temperature for growth |

### Range Observations (Object Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000054** | has growth temperature observation | Boolean growth test at specific temp |
| **METPO:2000055** | has range temperature observation | Temperature range category |

### Range Classes

| METPO ID | Label | Range |
|----------|-------|-------|
| METPO:1000448 | temperature range very low | - |
| METPO:1000449 | temperature range low | - |
| METPO:1000450 | temperature range mid1 | - |
| METPO:1000451 | temperature range mid2 | - |
| METPO:1000452 | temperature range mid3 | - |
| METPO:1000453 | temperature range mid4 | - |
| METPO:1000454 | temperature range high | - |

---

## pH Predicates

### Quantitative Values (Data Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000704** | has growth pH value | Optimal/typical growth pH |
| **METPO:2000705** | has minimum pH value | Minimum pH for growth |
| **METPO:2000706** | has maximum pH value | Maximum pH for growth |

### Range Observations (Object Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000239** | has pH observation | Boolean growth test at specific pH |
| **METPO:2000503** | has range pH observation | pH range category |

### Range Classes

| METPO ID | Label | Range |
|----------|-------|-------|
| METPO:1000459 | pH range very low | - |
| METPO:1000460 | pH range low | - |
| METPO:1000461 | pH range mid1 | - |
| METPO:1000462 | pH range mid2 | - |
| METPO:1000463 | pH range mid3 | - |
| METPO:1000464 | pH range high | - |

---

## Salinity/NaCl Predicates

### Quantitative Values (Data Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000707** | has growth salinity value | Optimal/typical growth salinity |
| **METPO:2000708** | has minimum salinity value | Minimum salinity for growth |
| **METPO:2000709** | has maximum salinity value | Maximum salinity for growth |

### Range Observations (Object Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000508** | has growth NaCl observation | Boolean growth test at specific NaCl% |
| **METPO:2000509** | has range NaCl observation | NaCl range category |

### Range Classes

| METPO ID | Label | Range |
|----------|-------|-------|
| METPO:1000469 | NaCl range low | - |
| METPO:1000470 | NaCl range mid1 | - |
| METPO:1000471 | NaCl range mid2 | - |
| METPO:1000472 | NaCl range high | - |

---

## Cell Dimension Predicates

### Quantitative Values (Data Properties)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000723** | has minimum cell length value | Minimum cell length |
| **METPO:2000724** | has maximum cell length value | Maximum cell length |
| **METPO:2000725** | has minimum cell width value | Minimum cell width |
| **METPO:2000726** | has maximum cell width value | Maximum cell width |

---

## Generic Min/Max Predicates

### Universal Predicates (Any Measurement)

| METPO ID | Label | Use Case |
|----------|-------|----------|
| **METPO:2000059** | has minimum observed value | Generic minimum for any parameter |
| **METPO:2000060** | has maximum observed value | Generic maximum for any parameter |

---

## Usage Patterns

### Pattern 1: Min/Max Values for Known Parameters

For parameters with dedicated predicates (temperature, pH, salinity):

```python
# Temperature min/max
subject: NCBITaxon:562
predicate: METPO:2000702  # has minimum temperature value
object: "10"^^xsd:float
qualifier: {unit: "Cel"}

subject: NCBITaxon:562
predicate: METPO:2000703  # has maximum temperature value
object: "45"^^xsd:float
qualifier: {unit: "Cel"}

# pH min/max
subject: NCBITaxon:562
predicate: METPO:2000705  # has minimum pH value
object: "5.0"^^xsd:float

subject: NCBITaxon:562
predicate: METPO:2000706  # has maximum pH value
object: "9.0"^^xsd:float

# Salinity min/max
subject: NCBITaxon:562
predicate: METPO:2000708  # has minimum salinity value
object: "0.5"^^xsd:float
qualifier: {unit: "%"}

subject: NCBITaxon:562
predicate: METPO:2000709  # has maximum salinity value
object: "5.0"^^xsd:float
qualifier: {unit: "%"}
```

### Pattern 2: Generic Min/Max for Other Parameters

For parameters without dedicated predicates:

```python
# Generic min/max (e.g., cell length)
subject: NCBITaxon:562
predicate: METPO:2000059  # has minimum observed value
object: "2.5"^^xsd:float
qualifier: {
    parameter: "cell_length",
    unit: "um"
}

subject: NCBITaxon:562
predicate: METPO:2000060  # has maximum observed value
object: "5.0"^^xsd:float
qualifier: {
    parameter: "cell_length",
    unit: "um"
}
```

### Pattern 3: Range Observations (Categorical)

For categorical range classifications:

```python
# Temperature range category
subject: NCBITaxon:562
predicate: METPO:2000055  # has range temperature observation
object: METPO:1000451  # temperature range mid2

# pH range category
subject: NCBITaxon:562
predicate: METPO:2000503  # has range pH observation
object: METPO:1000462  # pH range mid2

# NaCl range category
subject: NCBITaxon:562
predicate: METPO:2000509  # has range NaCl observation
object: METPO:1000470  # NaCl range mid1
```

---

## Implementation for MetaTraits

### We Have This Data

MetaTraits database contains:
- ✅ Min/max temperature values
- ✅ Min/max pH values
- ✅ Min/max salinity values
- ✅ Optimal/growth values

### Current Implementation

**Currently using:** Phenotype classes based on single growth test values
```python
# growth: 42 degrees Celsius → mesophilic
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1000615  # mesophilic
```

### Enhanced Implementation (Phase 3?)

**Could also add:** Actual min/max/optimal quantitative values
```python
# From metatraits metadata
subject: NCBITaxon:562
predicate: METPO:2000702  # has minimum temperature value
object: "20"^^xsd:float
qualifier: {unit: "Cel"}

subject: NCBITaxon:562
predicate: METPO:2000701  # has growth temperature value
object: "37"^^xsd:float
qualifier: {unit: "Cel"}

subject: NCBITaxon:562
predicate: METPO:2000703  # has maximum temperature value
object: "45"^^xsd:float
qualifier: {unit: "Cel"}
```

---

## Data Availability in MetaTraits

### Check What We Have

Need to verify if MetaTraits summary data includes:
- [ ] Min temperature values
- [ ] Max temperature values
- [ ] Optimal temperature values
- [ ] Min pH values
- [ ] Max pH values
- [ ] Optimal pH values
- [ ] Min salinity values
- [ ] Max salinity values
- [ ] Optimal salinity values

### Where to Look

1. **MetaTraits JSONL files:**
   - `data/raw/ncbi_species_summary.jsonl.gz`
   - `data/raw/gtdb_species_summary.jsonl.gz`

2. **Check summary structure:**
   ```python
   {
       "tax_name": "Escherichia coli",
       "summaries": [
           {
               "name": "temperature min",
               "majority_label": "15.0",
               ...
           },
           {
               "name": "temperature max",
               "majority_label": "45.0",
               ...
           }
       ]
   }
   ```

3. **If we have these:**
   - Add resolver for quantitative properties
   - Use METPO:2000702/2000703/2000705/2000706/2000708/2000709
   - Create edges with numeric values + units

---

## Recommendation

### Immediate (Phase 2)
- ✅ Use phenotype classes for qualitative growth tests
- ✅ Use existing pigmentation classes (1003022-1003031)

### Next (Phase 3)
1. **Check MetaTraits data** for min/max/optimal values
2. **If present:** Implement quantitative property resolvers
3. **Use existing METPO predicates:**
   - 2000702/2000703 (temp min/max)
   - 2000705/2000706 (pH min/max)
   - 2000708/2000709 (salinity min/max)
   - 2000701/2000704/2000707 (optimal values)

### No New METPO Terms Needed

**All predicates already exist!** Just need to:
1. Verify we have the data
2. Implement resolvers to use the predicates
3. Add numeric value + unit qualifiers

---

## Example: Complete Temperature Profile

```python
# From single growth test: 42°C = can grow
# Current Phase 2:
subject: NCBITaxon:562
predicate: biolink:has_phenotype
object: METPO:1000615  # mesophilic

# Future Phase 3 (if we have the data):
subject: NCBITaxon:562
predicate: METPO:2000702  # has minimum temperature value
object: "20"^^xsd:float
qualifier: {unit: "Cel", source: "metatraits"}

subject: NCBITaxon:562
predicate: METPO:2000701  # has growth temperature value
object: "37"^^xsd:float
qualifier: {unit: "Cel", source: "metatraits"}

subject: NCBITaxon:562
predicate: METPO:2000703  # has maximum temperature value
object: "45"^^xsd:float
qualifier: {unit: "Cel", source: "metatraits"}

# Both phenotype AND quantitative data!
```

---

## Conclusion

**METPO is well-designed** for quantitative trait modeling:
- ✅ Has all needed min/max predicates
- ✅ Has categorical range classes
- ✅ Has generic predicates for new parameters

**Next step:** Check if MetaTraits data contains min/max values, then implement Phase 3 to use them.

---

**Status:** METPO predicates documented | Ready to check data availability  
**Date:** 2026-04-05
