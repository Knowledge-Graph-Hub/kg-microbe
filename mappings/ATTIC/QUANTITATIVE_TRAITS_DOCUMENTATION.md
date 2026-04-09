# Quantitative Traits Documentation

**Date**: 2026-03-26
**Transform**: metatraits, metatraits_gtdb

---

## Purpose

This document explains why certain trait patterns appear in `unmapped_traits.tsv` and why this is **expected and correct behavior**.

---

## Quantitative Measurements vs Categorical Traits

### Categorical Traits (Should Map to Ontology Terms)

Categorical traits describe **qualitative properties** that can be represented by ontology terms:

| Trait Example | Maps To | Ontology Term |
|---------------|---------|---------------|
| "gram positive" | METPO:1000698 | gram positive |
| "obligate aerobic" | METPO:1000606 | obligately aerobic |
| "produces: ethanol" | CHEBI:16236 | ethanol |
| "growth: glucose" | CHEBI:17634 | glucose |

These traits represent **discrete states** or **substance identities** that have formal ontology definitions.

---

### Quantitative Measurements (Should NOT Map to Ontology Terms)

Quantitative measurements are **numerical values with units** that describe continuous ranges:

| Trait Pattern | Example Values | Why Not Mapped |
|---------------|----------------|----------------|
| `temperature growth` | "Median: 31.2 Celsius" | Numeric value, not a term |
| `temperature minimum` | "Median: 14.8 Celsius" | Numeric value, not a term |
| `temperature maximum` | "Median: 37.8 Celsius" | Numeric value, not a term |
| `pH minimum` | "Median: 5.2" | Numeric value, not a term |
| `pH maximum` | "Median: 8.7" | Numeric value, not a term |
| `salinity minimum` | "Median: 0.5 % NaCl (w/v)" | Numeric value with units |
| `salinity maximum` | "Median: 3.1 % NaCl (w/v)" | Numeric value with units |
| `salinity growth` | "Median: 1.4 % NaCl (w/v)" | Numeric value with units |
| `genome size` | "Median: 3.2 Mbp" | Numeric value with units |
| `estimated genome size` | "Median: 2.8 Mbp" | Numeric value with units |
| `gene count` | "Median: 3200" | Count, not a term |
| `estimated gene count` | "Median: 2900" | Count, not a term |
| `coding density` | "Median: 0.87" | Ratio/percentage |

These measurements represent **data values**, not categorical properties that can be mapped to ontology concepts.

---

## Expected Unmapped Counts

Based on the current metatraits transform output (March 26, 2026):

| Quantitative Pattern | Unmapped Occurrences | Notes |
|---------------------|---------------------|--------|
| `temperature growth` | 56,954 | Growth temperature measurements |
| `temperature maximum` | 54,981 | Maximum growth temperature |
| `temperature minimum` | 54,977 | Minimum growth temperature |
| `pH minimum` | 54,703 | Minimum pH for growth |
| `pH maximum` | 54,703 | Maximum pH for growth |
| `salinity maximum` | 54,406 | Maximum salinity tolerance |
| `salinity minimum` | 54,298 | Minimum salinity requirement |
| `salinity growth` | 53,843 | Optimal salinity for growth |
| `genome size` | 53,165 | Genome size in base pairs |
| `estimated genome size` | 53,165 | Estimated genome size |
| `gene count` | 53,165 | Number of genes |
| `estimated gene count` | 53,165 | Estimated gene count |
| `coding density` | 52,770 | Proportion of genome that codes for proteins |
| **Total** | **~700K** | **16.6% of all unmapped occurrences** |

---

## Why This Is Correct Behavior

### 1. Ontologies Represent Concepts, Not Values

Ontology terms like METPO, ChEBI, and GO represent:
- **Classes of entities** (e.g., "glucose", "gram positive bacterium")
- **Relationships** (e.g., "capable of", "has phenotype")
- **Categorical properties** (e.g., "motile", "thermophilic")

They do **NOT** represent:
- Specific numerical measurements
- Value ranges
- Statistical summaries (median, mean, min, max)

### 2. Measurements Require Different Representation

Quantitative data should be represented using:
- **Data properties** with typed values (e.g., `temperature_growth: 37.0 ^^xsd:float`)
- **Units ontology** (UO) for unit annotations (e.g., `degree Celsius`)
- **Statistical qualifiers** (median, mean, range)

Mapping "temperature growth: 37.0 Celsius" to a single ontology term would lose:
- The actual measurement value (37.0)
- The unit (Celsius)
- The statistical context (median vs mean)

### 3. Data Structure in unmapped_traits.tsv

Quantitative traits in `unmapped_traits.tsv` preserve the full context:

```
trait_name              tax_name                    majority_label              num_observations
temperature growth      Escherichia coli            Median: 37.0 Celsius       150
pH minimum              Lactobacillus acidophilus   Median: 4.2                89
genome size             Bacillus subtilis           Median: 4.2 Mbp            45
```

This representation maintains:
- ✅ The measurement type (trait_name)
- ✅ The organism context (tax_name)
- ✅ The actual value and statistical summary (majority_label)
- ✅ Sample size (num_observations)

---

## How to Use Quantitative Traits

### For Data Analysis

Quantitative traits in `unmapped_traits.tsv` can be:
1. **Extracted** and converted to numeric values
2. **Joined** with mapped trait edges using `tax_name` (NCBITaxon ID)
3. **Used in statistical analyses** (correlations, distributions, ranges)
4. **Visualized** as continuous variables (histograms, scatter plots)

### Example Use Case

Query: "Find bacteria that grow at high temperatures and produce ethanol"

1. **Categorical trait** (from edges.tsv):
   ```
   NCBITaxon:X -- biolink:produces --> CHEBI:16236 (ethanol)
   ```

2. **Quantitative trait** (from unmapped_traits.tsv):
   ```
   temperature_growth: Median: 55.0 Celsius for NCBITaxon:X
   ```

3. **Combined query**:
   - Filter edges where object = CHEBI:16236
   - Join with unmapped_traits on tax_name
   - Filter where temperature_growth > 50°C

---

## Alternative Approaches (Future Consideration)

While quantitative measurements should not be mapped to ontology terms, they could potentially be:

### Option 1: Add as Edge Qualifiers

```turtle
NCBITaxon:X biolink:has_attribute [
  a biolink:Attribute ;
  biolink:has_qualitative_value METPO:temperature_trait ;
  biolink:has_quantitative_value 37.0 ;
  biolink:has_unit UO:0000027 ;  # degree Celsius
]
```

### Option 2: Create Measurement Nodes

```turtle
NCBITaxon:X biolink:has_measurement <measurement_1> .

<measurement_1> a biolink:Measurement ;
  biolink:has_attribute METPO:temperature_growth ;
  biolink:has_numeric_value 37.0 ;
  biolink:has_unit UO:0000027 ;
  biolink:statistical_qualifier "median" .
```

### Option 3: Range Binning (Not Recommended)

Create categorical bins for continuous values:
- "mesophilic" (20-45°C)
- "thermophilic" (45-80°C)
- "hyperthermophilic" (>80°C)

**Problem**: Loses precision and introduces arbitrary boundaries.

---

## Conclusion

The presence of **~700K quantitative trait occurrences in unmapped_traits.tsv is expected and correct**. These measurements:

- ✅ **Should NOT** be mapped to ontology terms
- ✅ **Are preserved** in unmapped_traits.tsv with full context
- ✅ **Can be used** for quantitative analyses and filtering
- ✅ **Represent 16.6%** of unmapped occurrences (not a mapping failure)

The remaining **~3.5M unmapped occurrences** are candidates for improved mapping through:
- Enhanced ChEBI lookup (Phase 2: stereochemistry handling)
- Additional pattern resolvers (Phase 3: already implemented)
- Expanded ontology coverage (submitting term requests to METPO)

---

## References

- **METPO Ontology**: https://github.com/berkeleybop/metpo
- **Units Ontology (UO)**: http://www.ontobee.org/ontology/UO
- **Biolink Model Attributes**: https://biolink.github.io/biolink-model/Attribute/
