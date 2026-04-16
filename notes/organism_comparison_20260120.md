# KG-Microbe Organism Comparison Report
**Release:** 20260120
**Date:** 2026-02-28

## Organisms Compared

1. **Akkermansia muciniphila** (NCBITaxon:239935)
2. **Alicyclobacillus montanus** (NCBITaxon:1830138)

---

## Executive Summary

- **Total edges for Akkermansia muciniphila:** 7
- **Total edges for Alicyclobacillus montanus:** 1
- **Common edges (identical predicate-object pairs):** 0
- **Common objects (any predicate):** 0

### Comparison with Previous Release (20250222)

| Metric | Akkermansia (old) | Akkermansia (new) | Alicyclobacillus (old) | Alicyclobacillus (new) |
|--------|-------------------|-------------------|------------------------|------------------------|
| Total edges | 14 | 7 | 25 | 1 |
| Change | - | -50% | - | -96% |

**Dramatic data reduction:** The newer release has significantly fewer edges for both organisms, particularly for Alicyclobacillus which lost nearly all its trait data.

---

## Detailed Edge Analysis

### Akkermansia muciniphila (7 edges)

| Predicate | Object | Object Name | Category |
|-----------|--------|-------------|----------|
| METPO:2000517 | mediadive.medium:110 | CHOPPED MEAT MEDIUM WITH CARBOHYDRATES DSMZ Medium 110 | METPO:1004005 |
| METPO:2000517 | mediadive.medium:693 | COLUMBIA BLOOD MEDIUM DSMZ Medium 693 | METPO:1004005 |
| biolink:has_phenotype | METPO:1000429 | GC low | biolink:PhenotypicQuality |
| biolink:has_phenotype | METPO:1000603 | anaerobic | biolink:PhenotypicQuality |
| biolink:has_phenotype | METPO:1000699 | gram negative | biolink:PhenotypicQuality |
| biolink:has_phenotype | METPO:1000872 | non-spore forming | biolink:PhenotypicQuality |
| biolink:subclass_of | NCBITaxon:239934 | Akkermansia | biolink:OrganismTaxon |

**Key changes from 20250222:**
- Growth media predicates changed from `biolink:occurs_in` to `METPO:2000517`
- Lost 4 growth media associations (now only 2 vs 6)
- Lost all enzyme capabilities (EC codes)
- Lost substrate consumption data (glucose)
- Lost biosafety level annotation
- **Lost temperature phenotype** (mesophilic) - critical for hypothesis testing
- Gained new phenotypes: gram negative, non-spore forming, GC low

### Alicyclobacillus montanus (1 edge)

| Predicate | Object | Object Name | Category |
|-----------|--------|-------------|----------|
| biolink:subclass_of | NCBITaxon:29330 | Alicyclobacillus | biolink:OrganismTaxon |

**Key changes from 20250222:**
- **Lost ALL metabolic and phenotypic trait data**
- Lost all 13 enzyme capabilities
- Lost all 10 substrate utilization records
- Lost gram stain information
- **Lost motility and sporulation traits**
- **Lost trophic mode information** (autotrophy/heterotrophy/mixotrophy)
- Only taxonomic classification remains

---

## Vector Analogy Hypothesis Testing

**Hypothesis:** These organisms were identified as similar via vector analogy reasoning, with the expectation that they share:
1. Higher temperature preference
2. Acidic pH preference

### Results from KG Analysis (20260120 release):

#### Temperature-related traits:
- **Akkermansia muciniphila:** ❌ No temperature phenotype in this release (previous release had "mesophilic")
- **Alicyclobacillus montanus:** ❌ No temperature phenotype

#### pH/Acid-related traits:
- **Akkermansia muciniphila:** ❌ No pH or acidity phenotype
- **Alicyclobacillus montanus:** ❌ No pH or acidity phenotype

### Conclusion:

**The vector analogy hypothesis CANNOT be validated from the explicit edges in the 20260120 KG release.**

The knowledge graph lacks:
- Temperature preference data for both organisms
- pH preference data for both organisms
- Acid tolerance/preference data for both organisms

---

## Biological Reality vs KG Data

### Known Biological Characteristics (from literature):

**Akkermansia muciniphila:**
- Temperature: Mesophilic (37°C optimal, human gut)
- pH: Neutral to slightly alkaline (gut environment)
- Oxygen: Strictly anaerobic
- Habitat: Human intestinal mucus layer

**Alicyclobacillus montanus:**
- Temperature: **Thermophilic** (55-60°C optimal)
- pH: **Acidophilic** (pH 3.0-6.0 optimal)
- Oxygen: Aerobic
- Habitat: Acidic hot springs, soil

### Gap Analysis:

The **vector analogy reasoning likely captured semantic relationships** from:
1. Text embeddings from scientific literature
2. Co-occurrence patterns in papers
3. Functional relationships not explicitly modeled as edges

The KG edges show **explicit, structured trait annotations** but are missing:
- Temperature preferences for Alicyclobacillus
- pH preferences for both organisms
- Many other environmental factors

**The organisms are actually quite different** in their environmental preferences:
- **NOT similar in temperature:** Akkermansia is mesophilic (~37°C), Alicyclobacillus is thermophilic (~55-60°C)
- **NOT similar in pH:** Akkermansia prefers neutral pH (~7), Alicyclobacillus is acidophilic (pH 3-6)

---

## Shared Edges Analysis

### Shared Predicate-Object Pairs: 0

### Shared Objects (any predicate): 0

### Shared Predicates:
- `biolink:subclass_of` (but different parent genera)
- `biolink:has_phenotype` (but different phenotypes)

No actual trait overlap is evident in the KG data.

---

## Key Findings

1. **Massive data loss in newer release:**
   - Akkermansia lost 50% of edges (14 → 7)
   - Alicyclobacillus lost 96% of edges (25 → 1)

2. **Hypothesis cannot be tested:**
   - No temperature or pH trait data in current KG
   - Vector analogy may have captured latent semantic relationships not represented as explicit edges

3. **Biological reality mismatch:**
   - Literature shows these organisms have **different** temperature and pH preferences
   - Vector analogy may have identified similarity based on other factors (e.g., both extremophiles, both studied in environmental contexts, both metabolically versatile)

4. **Data quality concerns:**
   - Significant loss of trait data between releases
   - Missing critical environmental phenotypes
   - Inconsistent data coverage between organisms

---

## Recommendations

1. **Investigate data loss:** Why did trait data decrease so dramatically between releases?
2. **Add environmental phenotypes:** Temperature range, pH range, salinity tolerance
3. **Examine vector embeddings:** What features actually drove the similarity in vector space?
4. **Cross-validate with literature:** Add missing phenotypic data from BacDive, DSMZ, or literature
5. **Consider implicit relationships:** The vector analogy may be capturing relationships beyond explicit trait sharing

---

## Data Provenance Note

This analysis is based solely on explicit edges in the knowledge graph. Vector embeddings may capture:
- Implicit relationships from text
- Co-occurrence patterns
- Functional similarities not modeled as traits
- Pathway-level similarities
- Ecological niche similarities

The absence of shared explicit traits does not invalidate the vector analogy - it may be identifying higher-order patterns.
