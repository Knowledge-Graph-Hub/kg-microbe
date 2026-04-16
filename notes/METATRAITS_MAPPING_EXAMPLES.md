# MetaTraits Mapping Examples

**Purpose:** Document what `trait_mapping` and `microbial_mappings` contain  
**Date:** 2026-04-05

---

## Overview

The metatraits transform uses two main mapping dictionaries to convert trait names from MetaTraits database to ontology terms:

1. **`trait_mapping`** - Maps exact trait names to METPO phenotype classes
2. **`microbial_mappings`** - Maps trait patterns to chemical/enzyme/pathway terms

---

## 1. trait_mapping

**Source:** Built from METPO ontology "metatraits synonym" column + custom_curies.yaml

**Size:** 115 entries (after case-insensitive duplicates)

**Structure:**
```python
{
  "trait_name": {
    "curie": "METPO:XXXXXXX",
    "category": "biolink:PhenotypicQuality",
    "name": "human readable label",
    "predicate": "biolink:has_phenotype"
  }
}
```

### Examples by Category

#### Temperature Traits
```python
"temperature preference" → {
  "curie": "METPO:1000613",
  "category": "biolink:PhenotypicQuality",
  "name": "temperature preference",
  "predicate": "biolink:has_phenotype"
}

"psychrophilic" → {
  "curie": "METPO:1000614",
  "category": "biolink:PhenotypicQuality",
  "name": "psychrophilic",
  "predicate": "biolink:has_phenotype"
}

"thermophilic" → {
  "curie": "METPO:1000616",
  "category": "biolink:PhenotypicQuality",
  "name": "thermophilic",
  "predicate": "biolink:has_phenotype"
}
```

#### Oxygen Preference Traits
```python
"oxygen preference" → {
  "curie": "METPO:1000601",
  "category": "biolink:PhenotypicQuality",
  "name": "oxygen preference",
  "predicate": "biolink:has_phenotype"
}

"facultative anaerobe" → {
  "curie": "METPO:1000605",
  "category": "biolink:PhenotypicQuality",
  "name": "facultatively anaerobic",
  "predicate": "biolink:has_phenotype"
}

"obligate aerobic" → {
  "curie": "METPO:1000606",
  "category": "biolink:PhenotypicQuality",
  "name": "obligately aerobic",
  "predicate": "biolink:has_phenotype"
}

"aerotolerant" → {
  "curie": "METPO:1000609",
  "category": "biolink:PhenotypicQuality",
  "name": "aerotolerant",
  "predicate": "biolink:has_phenotype"
}

"obligate anaerobic" → {
  "curie": "METPO:1000611",
  "category": "biolink:PhenotypicQuality",
  "name": "strictly anaerobic",
  "predicate": "biolink:has_phenotype"
}
```

#### Cell Properties
```python
"GC percentage" → {
  "curie": "METPO:1000127",
  "category": "biolink:PhenotypicQuality",
  "name": "GC content",
  "predicate": "biolink:has_phenotype"
}

"cell shape" → {
  "curie": "METPO:1000666",
  "category": "biolink:PhenotypicQuality",
  "name": "cell shape",
  "predicate": "biolink:has_phenotype"
}

"presence of motility" → {
  "curie": "METPO:1000701",
  "category": "biolink:PhenotypicQuality",
  "name": "motility",
  "predicate": "biolink:has_phenotype"
}
```

### How trait_mapping is Built

```python
# Step 1: Load from METPO "metatraits synonym" column
for synonym, metpo_data in self.metpo_mappings.items():
    self.trait_mapping[synonym] = {
        "curie": metpo_data["curie"],
        "category": metpo_data["inferred_category"],
        "name": metpo_data["label"],
        "predicate": metpo_data["predicate_biolink_equivalent"]
    }
    # Also add lowercase version
    self.trait_mapping[synonym.lower()] = self.trait_mapping[synonym]

# Step 2: Add custom_curies.yaml entries (if not already present)
# Located at: kg_microbe/transform_utils/custom_curies.yaml
```

---

## 2. microbial_mappings

**Source:** Loaded from TSV files in `mappings/metatraits/` directory

**Size:** 45 entries

**Structure:**
```python
{
  "trait_pattern": {
    "object_id": "CHEBI:XXXXX" or "EC:X.X.X.X" or "GO:XXXXXXX",
    "object_label": "human readable label",
    "object_source": "CHEBI" or "EC" or "GO",
    "biolink_predicate": "biolink:produces" or "biolink:capable_of" or "biolink:has_phenotype",
    "object_category": "biolink:ChemicalSubstance" or "biolink:MolecularActivity" or "biolink:BiologicalProcess"
  }
}
```

### Examples by Category

#### Chemical Production (biolink:produces)
```python
"produces: ethanol" → {
  "object_id": "CHEBI:16236",
  "object_label": "ethanol",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}

"produces: hydrogen sulfide" → {
  "object_id": "CHEBI:16136",
  "object_label": "hydrogen sulfide",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}

"produces: indole" → {
  "object_id": "CHEBI:16881",
  "object_label": "indole",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}

"produces: methane from acetate" → {
  "object_id": "CHEBI:16183",
  "object_label": "methane",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}

"produces: siderophore" → {
  "object_id": "CHEBI:26672",
  "object_label": "siderophore",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}
```

#### Carbon Source (biolink:capable_of)
```python
"carbon source: acetate" → {
  "object_id": "CHEBI:30089",
  "object_label": "acetate",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:capable_of",
  "object_category": "biolink:ChemicalSubstance"
}

"carbon source: ethanol" → {
  "object_id": "CHEBI:16236",
  "object_label": "ethanol",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:capable_of",
  "object_category": "biolink:ChemicalSubstance"
}
```

#### Fermentation (biolink:has_phenotype)
```python
"fermentation: glucose" → {
  "object_id": "CHEBI:17234",
  "object_label": "glucose",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:has_phenotype",
  "object_category": "biolink:ChemicalSubstance"
}

"fermentation" → {
  "object_id": "GO:0006113",
  "object_label": "fermentation",
  "object_source": "GO",
  "biolink_predicate": "biolink:has_phenotype",
  "object_category": "biolink:BiologicalProcess"
}
```

#### Assimilation
```python
"assimilation: citrate" → {
  "object_id": "CHEBI:30769",
  "object_label": "citrate",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:has_phenotype",
  "object_category": "biolink:ChemicalSubstance"
}
```

#### Enzyme Activity (biolink:capable_of)
```python
"enzyme activity: catalase (EC1.11.1.6)" → {
  "object_id": "EC:1.11.1.6",
  "object_label": "catalase",
  "object_source": "EC",
  "biolink_predicate": "biolink:capable_of",
  "object_category": "biolink:MolecularActivity"
}

"enzyme activity: beta-galactosidase (EC3.2.1.23)" → {
  "object_id": "EC:3.2.1.23",
  "object_label": "beta-galactosidase",
  "object_source": "EC",
  "biolink_predicate": "biolink:capable_of",
  "object_category": "biolink:MolecularActivity"
}

"enzyme activity: urease (EC3.5.1.5)" → {
  "object_id": "EC:3.5.1.5",
  "object_label": "urease",
  "object_source": "EC",
  "biolink_predicate": "biolink:capable_of",
  "object_category": "biolink:MolecularActivity"
}
```

### Source TSV Files

Located in: `mappings/metatraits/`

**TSV Format:**
```tsv
subject_label	object_id	object_label	object_source	notes	entity_category
produces: ethanol	CHEBI:16236	ethanol	CHEBI	biolink:produces	chemicals
carbon source: acetate	CHEBI:30089	acetate	CHEBI	biolink:capable_of	chemicals
enzyme activity: catalase (EC1.11.1.6)	EC:1.11.1.6	catalase	EC	biolink:capable_of	enzymes
```

**Files included:**
- `*_chemical_mappings.tsv` - Chemical substances (ChEBI)
- `*_enzyme_mappings.tsv` - Enzyme activities (EC numbers, GO molecular functions)
- `*_pathway_mappings.tsv` - Biological processes (GO)
- `*_phenotype_mappings.tsv` - Phenotypic traits (METPO)

**Negative mappings excluded:**
- Files ending in `_negative_mappings.tsv` are not loaded
- These contain "does not ferment X" type patterns

---

## Usage in Transform

### Lookup Priority (Tier 1)

```python
# 1. Check trait_mapping (METPO synonyms + custom_curies)
mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(trait_name.lower())
if mapping:
    # Direct METPO phenotype class match
    return mapping

# 2. Check microbial_mappings (curated chemical/enzyme/pathway patterns)
mapping = self.microbial_mappings.get(trait_name)
if mapping:
    # Curated chemical/enzyme/pathway mapping
    return {
        "curie": mapping["object_id"],
        "category": mapping["object_category"],
        "name": mapping["object_label"],
        "predicate": mapping["biolink_predicate"]
    }

# 3. Pattern-based resolvers (for dynamic patterns)
# ... (chemical resolver, metabolic resolver, etc.)
```

### Example Edge Creation

**Input trait:** "produces: ethanol" with value "true"

**Lookup:**
```python
mapping = microbial_mappings.get("produces: ethanol")
# Returns:
{
  "object_id": "CHEBI:16236",
  "object_label": "ethanol",
  "object_source": "CHEBI",
  "biolink_predicate": "biolink:produces",
  "object_category": "biolink:ChemicalSubstance"
}
```

**Edge created:**
```tsv
subject	predicate	object	relation	primary_knowledge_source	knowledge_level	agent_type	has_percentage
NCBITaxon:562	biolink:produces	CHEBI:16236	biolink:produces	infores:metatraits	observation	automated_agent	100.0
```

**Node created:**
```tsv
id	category	name
CHEBI:16236	biolink:ChemicalSubstance	ethanol
```

---

## Key Differences

| Aspect | trait_mapping | microbial_mappings |
|--------|---------------|-------------------|
| **Source** | METPO ontology + custom_curies.yaml | Curated TSV files |
| **Size** | 115 entries | 45 entries |
| **Object types** | METPO phenotype classes | CHEBI, EC, GO terms |
| **Predicates** | Mostly `biolink:has_phenotype` | `biolink:produces`, `biolink:capable_of`, `biolink:has_phenotype` |
| **Categories** | Mostly `biolink:PhenotypicQuality` | `biolink:ChemicalSubstance`, `biolink:MolecularActivity`, `biolink:BiologicalProcess` |
| **Pattern type** | Exact trait names | Trait patterns with chemicals/enzymes |
| **Maintenance** | Auto-updated from METPO releases | Manually curated in repo |

---

## Statistics

### trait_mapping Coverage
- **Temperature traits:** 1
- **Oxygen preference traits:** 5
- **Cell property traits:** 3
- **Total:** 115 unique trait names (including case variations)

### microbial_mappings Coverage
- **Chemical production:** 5
- **Carbon sources:** 2
- **Fermentation:** 2
- **Enzyme activities:** 6+ (multiple EC numbers)
- **Total:** 45 curated patterns

### Combined Coverage
- **Direct METPO mappings:** 115 trait names
- **Curated chemical/enzyme patterns:** 45 patterns
- **Total tier-1 coverage:** 160 exact matches before pattern-based resolvers

---

## Multiprocessing

Both mappings are shared across worker processes:

```python
def _get_shared_init_data(self) -> Dict[str, Any]:
    return {
        "trait_mapping": self.trait_mapping,      # 115 entries
        "microbial_mappings": self.microbial_mappings,  # 45 entries
        # ... other shared data
    }

def _init_from_shared_data(self, shared_data: Dict[str, Any]) -> None:
    self.trait_mapping = shared_data["trait_mapping"]
    self.microbial_mappings = shared_data["microbial_mappings"]
```

This ensures all workers have consistent lookups without re-loading files.

---

**Status:** Documentation complete  
**Date:** 2026-04-05
