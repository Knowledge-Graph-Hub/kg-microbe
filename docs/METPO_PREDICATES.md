# METPO Predicates Documentation

This document describes the Microbial Ecophysiological Trait and Phenotype Ontology (METPO) predicates used in KG-Microbe.

**Source**: https://github.com/berkeleybop/metpo

**Priority**: When modeling microbial traits and interactions, METPO predicates should be prioritized over generic biolink predicates when a more specific METPO predicate is available.

## Categories of METPO Predicates

### 1. Chemical Interaction Predicates (Positive)
Range: METPO:2000001-2000020

These predicates describe positive interactions between organisms and chemical entities.

| Predicate ID | Label | Description | Use Case |
|--------------|-------|-------------|----------|
| METPO:2000001 | organism interacts with chemical | Generic organism-chemical interaction | Use when specific interaction type unknown |
| METPO:2000002 | assimilates | Organism assimilates chemical | Nutrient uptake |
| METPO:2000003 | builds acid from | Organism produces acid from chemical | Acid production from substrate |
| METPO:2000004 | builds base from | Organism produces base from chemical | Base production from substrate |
| METPO:2000005 | builds gas from | Organism produces gas from chemical | Gas production from substrate |
| METPO:2000006 | uses as carbon source | Organism uses chemical as carbon source | Carbon metabolism |
| METPO:2000007 | degrades | Organism degrades chemical | Degradation pathways |
| METPO:2000008 | uses as electron acceptor | Chemical serves as electron acceptor | Respiration |
| METPO:2000009 | uses as electron donor | Chemical serves as electron donor | Energy metabolism |
| METPO:2000010 | uses as energy source | Chemical used for energy | Energy metabolism |
| METPO:2000011 | ferments | Organism ferments chemical | Fermentation |
| METPO:2000012 | uses for growth | Chemical supports growth | Growth requirements |
| METPO:2000013 | hydrolyzes | Organism hydrolyzes chemical | Hydrolysis reactions |
| METPO:2000014 | uses as nitrogen source | Chemical provides nitrogen | Nitrogen metabolism |
| METPO:2000015 | uses in other way | Other chemical utilization | Catch-all for other uses |
| METPO:2000016 | oxidizes | Organism oxidizes chemical | Oxidation reactions |
| METPO:2000017 | reduces | Organism reduces chemical | Reduction reactions |
| METPO:2000018 | requires for growth | Chemical required for growth | Essential growth factors |
| METPO:2000019 | uses for respiration | Chemical used in respiration | Respiratory processes |
| METPO:2000020 | uses as sulfur source | Chemical provides sulfur | Sulfur metabolism |

### 2. Chemical Interaction Predicates (Negative)
Range: METPO:2000021-2000051

These predicates describe negative or absent interactions.

| Predicate ID | Label | Description | Use Case |
|--------------|-------|-------------|----------|
| METPO:2000027 | does not assimilate | Organism does not assimilate chemical | Negative assimilation result |
| METPO:2000028 | does not build acid from | No acid production from chemical | Negative acid test |
| METPO:2000031 | does not use as carbon source | Chemical not used as carbon source | Negative carbon utilization |
| METPO:2000037 | does not ferment | Organism does not ferment chemical | Negative fermentation test |
| METPO:2000038 | does not use for growth | Chemical not used for growth | Growth inhibition or lack of use |
| METPO:2000039 | does not hydrolyze | No hydrolysis of chemical | Negative hydrolysis test |
| METPO:2000044 | does not reduce | Chemical not reduced | Negative reduction test |
| METPO:2000046 | does not use for respiration | Not used in respiration | Negative respiration test |

### 3. Capability and Phenotype Predicates
Range: METPO:2000101-2000103

| Predicate ID | Label | Description | Biolink Equivalent | Priority |
|--------------|-------|-------------|-------------------|----------|
| METPO:2000101 | has quality | Organism has a quality | biolink:has_attribute | Use METPO for microbial traits |
| METPO:2000102 | has phenotype | Organism has a phenotype | biolink:has_phenotype | **PREFER METPO over biolink** |
| METPO:2000103 | capable of | Organism capable of process/activity | biolink:capable_of | **PREFER METPO over biolink** |

**Important**: For microbial phenotypes and capabilities, use METPO:2000102 (has phenotype) and METPO:2000103 (capable of) instead of their biolink equivalents.

### 4. Production Predicates
Range: METPO:2000202, METPO:2000222

| Predicate ID | Label | Description | Use Case |
|--------------|-------|-------------|----------|
| METPO:2000202 | produces | Organism produces chemical/substance | Chemical production |
| METPO:2000222 | does not produce | Organism does not produce chemical | Negative production test |

### 5. Enzyme Activity Predicates
Range: METPO:2000302-2000303

| Predicate ID | Label | Description | Use Case |
|--------------|-------|-------------|----------|
| METPO:2000302 | shows activity of | Organism shows enzyme activity | Positive enzyme activity test |
| METPO:2000303 | does not show activity of | No enzyme activity detected | Negative enzyme activity test |

### 6. Growth Medium Predicates
Range: METPO:2000517-2000518

| Predicate ID | Label | Description | Use Case |
|--------------|-------|-------------|----------|
| METPO:2000517 | grows in | Organism grows in medium | Growth medium compatibility |
| METPO:2000518 | does not grow in | Organism does not grow in medium | Growth inhibition/incompatibility |

## Usage Guidelines

### When to Use METPO vs Biolink Predicates

1. **Organism-Chemical Interactions**: Always use specific METPO predicates (METPO:2000001-2000051) instead of generic biolink predicates
   - ❌ `biolink:interacts_with`
   - ✅ `METPO:2000001` (organism interacts with chemical) or more specific METPO predicate

2. **Phenotypes and Capabilities**: Use METPO predicates for microbial traits
   - ❌ `biolink:has_phenotype`
   - ✅ `METPO:2000102` (has phenotype)
   - ❌ `biolink:capable_of`
   - ✅ `METPO:2000103` (capable of)

3. **Production**: Use METPO production predicates
   - ❌ `biolink:produces` or other generic predicates
   - ✅ `METPO:2000202` (produces)

4. **Enzyme-Substrate Relationships**: Currently use biolink (no METPO equivalent)
   - ✅ `biolink:has_input` (enzyme -> substrate)
   - Note: This may change if METPO adds equivalent predicates

### Constants in Code

All METPO predicates are defined in `kg_microbe/transform_utils/constants.py`:

```python
# Chemical interactions (positive)
METPO_ORGANISM_INTERACTS_WITH_CHEMICAL = "METPO:2000001"
METPO_USES_AS_CARBON_SOURCE = "METPO:2000006"
METPO_FERMENTS = "METPO:2000011"
# ... etc

# Capability/phenotype
METPO_HAS_QUALITY = "METPO:2000101"
METPO_HAS_PHENOTYPE = "METPO:2000102"
METPO_CAPABLE_OF = "METPO:2000103"

# Production
METPO_PRODUCES = "METPO:2000202"
METPO_DOES_NOT_PRODUCE = "METPO:2000222"

# Enzyme activity
METPO_SHOWS_ACTIVITY_OF = "METPO:2000302"
METPO_DOES_NOT_SHOW_ACTIVITY_OF = "METPO:2000303"

# Growth medium
METPO_GROWS_IN = "METPO:2000517"
METPO_DOES_NOT_GROW_IN = "METPO:2000518"
```

### Transform Implementation

When implementing transforms, follow these patterns:

#### 1. Organism-Chemical Interactions
```python
from kg_microbe.transform_utils.constants import METPO_USES_AS_CARBON_SOURCE

edge = {
    "subject": organism_id,
    "predicate": METPO_USES_AS_CARBON_SOURCE,  # Not biolink:interacts_with
    "object": chemical_id,
    "relation": METPO_USES_AS_CARBON_SOURCE,
    "primary_knowledge_source": source
}
```

#### 2. Phenotypes
```python
from kg_microbe.transform_utils.constants import METPO_HAS_PHENOTYPE

edge = {
    "subject": organism_id,
    "predicate": METPO_HAS_PHENOTYPE,  # Not biolink:has_phenotype
    "object": phenotype_id,
    "relation": METPO_HAS_PHENOTYPE,
    "primary_knowledge_source": source
}
```

#### 3. Capabilities
```python
from kg_microbe.transform_utils.constants import METPO_CAPABLE_OF

edge = {
    "subject": organism_id,
    "predicate": METPO_CAPABLE_OF,  # Not biolink:capable_of
    "object": process_id,
    "relation": METPO_CAPABLE_OF,
    "primary_knowledge_source": source
}
```

## Current Transform Usage

### Transforms using METPO predicates:

1. **bacdive**: Uses METPO for organism-chemical interactions, phenotypes, enzyme activities, and growth media
2. **mediadive**: Uses METPO for growth medium relationships
3. **bactotraits**: Uses METPO:2000103 for capabilities
4. **madin_etal**: Uses METPO:2000103 and METPO:2000006 as fallbacks

### Areas for Improvement

The following transforms still use biolink predicates where METPO predicates would be more appropriate:

1. **madin_etal.py**: Uses `biolink:has_phenotype` as fallback (lines 258-262, 499-503, 547-551, 585-589, 622-626, 656-660, 694-698)
   - Should use `METPO:2000102` instead

2. **bactotraits.py**: Uses `biolink:has_phenotype` as fallback (lines 240, 376)
   - Should use `METPO:2000102` instead

3. **bacdive.py**: Uses `biolink:has_phenotype` in several places (lines 387, 436-440, 484, 500)
   - Should use `METPO:2000102` instead

4. **bacdive.py**: Uses `biolink:interacts_with` (line 1897)
   - Should use `METPO:2000001` or more specific METPO predicate

## Statistics

From merged graph (merged_graph_stats.yaml):
- Total METPO predicates: 168
- METPO edges: 143
- METPO nodes: 25

## References

- METPO GitHub: https://github.com/berkeleybop/metpo
- Biolink Model: https://biolink.github.io/biolink-model/
- Constants definition: `kg_microbe/transform_utils/constants.py`
