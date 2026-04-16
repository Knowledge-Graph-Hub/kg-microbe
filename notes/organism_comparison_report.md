# KG-Microbe Organism Comparison Report
**Release:** 20250222
**Date:** 2026-02-28

## Organisms Compared

1. **Akkermansia muciniphila** (NCBITaxon:239935)
2. **Alicyclobacillus montanus** (NCBITaxon:1830138)

---

## Executive Summary

- **Total edges for Akkermansia muciniphila:** 14
- **Total edges for Alicyclobacillus montanus:** 25
- **Common edges (identical predicate-object pairs):** 0
- **Unique to Akkermansia:** Growth media associations (`biolink:occurs_in`), biosafety level
- **Unique to Alicyclobacillus:** Gram stain phenotype, no growth media data

---

## Edge Type Distribution

| Predicate | Akkermansia | Alicyclobacillus |
|-----------|-------------|------------------|
| `biolink:associated_with` | 1 | 0 |
| `biolink:capable_of` | 2 | 13 |
| `biolink:consumes` | 1 | 10 |
| `biolink:has_phenotype` | 3 | 1 |
| `biolink:occurs_in` | 6 | 0 |
| `biolink:subclass_of` | 1 | 1 |

---

## Detailed Comparisons

### Metabolic Capabilities (`biolink:capable_of`)

**Akkermansia muciniphila:**
- beta-D-galactosidase (EC:3.2.1.23)
- 2-nitrophenyl beta-D-galactopyranoside (EC:3.2.1.52)

**Alicyclobacillus montanus:**
- catalase (EC:1.11.1.6)
- cytochrome-c oxidase (EC:1.9.3.1)
- acid phosphatase (EC:3.1.3.2)
- alpha-glucosidase (EC:3.2.1.20)
- beta-glucosidase (EC:3.2.1.21)
- alpha-galactosidase (EC:3.2.1.22)
- leucine arylamidase (EC:3.4.11.1)
- trypsin (EC:3.4.21.4)
- motile
- spore forming
- autotrophy
- heterotrophy
- mixotrophy

**Analysis:** Alicyclobacillus has much broader metabolic capabilities, including respiratory enzymes, various hydrolases, and multiple trophic modes. Akkermansia is limited to beta-galactosidase activities.

---

### Substrate Utilization (`biolink:consumes`)

**Akkermansia muciniphila:**
- (-)-D-glucose (CHEBI:17634)

**Alicyclobacillus montanus:**
- D-fructose (CHEBI:15824)
- D-galactose (CHEBI:12936)
- L-arabinose (CHEBI:30849)
- cellobiose (CHEBI:17057)
- trehalose (CHEBI:27082)
- melibiose (CHEBI:28053)
- Various other compounds (some with abbreviated names: g, l, r - likely data quality issues)

**Analysis:** Alicyclobacillus shows diverse sugar utilization, while Akkermansia is documented with only glucose consumption in this dataset.

---

### Phenotypic Traits (`biolink:has_phenotype`)

**Akkermansia muciniphila:**
- GC content 42.65% - 57.0% (gc:mid1)
- anaerobe (oxygen:anaerobe)
- mesophilic (temperature:mesophilic)

**Alicyclobacillus montanus:**
- gram positive (gram_stain:positive)

**Analysis:** Akkermansia has GC content and oxygen/temperature growth requirements documented, while Alicyclobacillus only has Gram stain information in this dataset.

---

### Growth Media (`biolink:occurs_in`)

**Akkermansia muciniphila:**
- PYG MEDIUM MODIFIED DSMZ Medium 104 (medium:104)
- CHOPPED MEAT MEDIUM WITH CARBOHYDRATES DSMZ Medium 110 (medium:110)
- FASTIDIOUS ANAEROBE AGAR DSMZ Medium 1203 (medium:1203)
- SCHAEDLER BROTH ROTH 5772 DSMZ Medium 1669 (medium:1669)
- COLUMBIA BLOOD MEDIUM DSMZ Medium 693 (medium:693)
- COLUMBIA BLOOD AGAR WITH 5% HORSE BLOOD (medium:J282)

**Alicyclobacillus montanus:**
- (No growth media data)

**Analysis:** Akkermansia has detailed growth media information from BacDive/MediaDive sources, while Alicyclobacillus lacks this data in the current release.

---

### Other Associations

**Akkermansia muciniphila:**
- biosafety level 1 (BSL:1)

**Alicyclobacillus montanus:**
- (No biosafety level data)

---

### Taxonomic Classification (`biolink:subclass_of`)

**Akkermansia muciniphila:**
- Parent: Akkermansia (NCBITaxon:239934)

**Alicyclobacillus montanus:**
- Parent: Alicyclobacillus (NCBITaxon:29330)

---

## Key Findings

1. **No overlap in specific traits:** Despite sharing predicate types, these organisms have no identical predicate-object combinations, reflecting their distinct phylogenetic positions and ecological niches.

2. **Data completeness varies:** Akkermansia has richer growth media data, while Alicyclobacillus has more enzymatic and metabolic trait data.

3. **Biological differences:**
   - **Akkermansia** is an anaerobic, mesophilic bacterium specialized in mucin degradation
   - **Alicyclobacillus** is a Gram-positive, spore-forming bacterium with diverse metabolic capabilities including autotrophy and motility

4. **Data source bias:** The differences may partly reflect which data sources have better coverage for each organism, rather than complete biological profiles.

---

## Recommendations

1. Consider enriching Alicyclobacillus with growth media data from BacDive if available
2. Investigate the abbreviated chemical names (g, l, r) in Alicyclobacillus substrate data
3. Add biosafety level and oxygen requirement data for Alicyclobacillus if available
4. Consider adding more enzymatic capability data for Akkermansia if available in source databases
