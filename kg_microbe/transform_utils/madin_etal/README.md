# Madin et al. Transform

This module transforms the **Madin et al. bacterial and archaeal traits dataset** into a knowledge graph compatible with the KG-Microbe project.

## Table of Contents
- [Overview](#overview)
- [Data Source](#data-source)
- [Transformation Pipeline](#transformation-pipeline)
- [Data Flow](#data-flow)
- [Ontology Mappings](#ontology-mappings)
- [Output Files](#output-files)
- [Usage](#usage)
- [Architecture](#architecture)

---

## Overview

The Madin et al. dataset contains phenotypic and ecological traits for thousands of bacterial and archaeal species. This transformer:

1. **Extracts** organism trait data from CSV files
2. **Standardizes** trait terms using ontology mappings (METPO, ChEBI, GO, ENVO)
3. **Annotates** text using Named Entity Recognition (NER)
4. **Generates** a knowledge graph with nodes (organisms, traits) and edges (relationships)

### Key Features
- ✅ Standardized ontology mappings (METPO, ChEBI, GO, ENVO)
- ✅ Intelligent NER with caching for performance
- ✅ Multi-level fallback strategy (METPO → NER → Custom)
- ✅ Support for complex traits (comma-separated values)
- ✅ Duplicate detection and removal

---

## Data Source

**Primary Dataset:**
- Source: [bacteria-archaea-traits GitHub Repository](https://github.com/bacteria-archaea-traits/bacteria-archaea-traits)
- File: `condensed_traits_NCBI.csv`
- Contains: ~10,000+ bacterial and archaeal species with trait annotations

**Extracted Columns:**
| Column | Description | Example Values |
|--------|-------------|----------------|
| `tax_id` | NCBI Taxonomy ID | `562` (E. coli) |
| `org_name` | Organism name | `Escherichia coli` |
| `metabolism` | Metabolic type | `aerobe`, `anaerobe`, `facultative` |
| `pathways` | Biological pathways | `glycolysis`, `photosynthesis` |
| `carbon_substrates` | Carbon sources used | `glucose`, `acetate`, `citrate` |
| `cell_shape` | Morphology | `rod`, `cocci`, `spiral` |
| `isolation_source` | Environment | `soil`, `marine`, `human gut` |

---

## Transformation Pipeline

```
┌─────────────────┐
│  Input CSV      │
│  (Madin et al)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  1. Load & Parse Data               │
│     - Extract trait columns         │
│     - Handle NA values              │
│     - Split comma-separated values  │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  2. NER (Named Entity Recognition)  │
│     - ChEBI for carbon substrates   │
│     - GO for pathways               │
│     - Cache results for performance │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  3. Ontology Mapping (3-tier)       │
│     Tier 1: METPO (preferred)       │
│     Tier 2: NER (ChEBI/GO)          │
│     Tier 3: Custom IDs (fallback)   │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  4. Generate Knowledge Graph        │
│     - Create nodes (organisms,      │
│       traits, chemicals, etc.)      │
│     - Create edges (relationships)  │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  5. Post-processing                 │
│     - Remove duplicates             │
│     - Add chemical roles (ChEBI)    │
│     - Validate output               │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Output Files   │
│  - nodes.tsv    │
│  - edges.tsv    │
└─────────────────┘
```

---

## Data Flow

### Processing Each Organism

For each organism in the dataset, the transformer:

```python
# 1. Create organism node
organism_node = [
    "NCBITaxon:562",           # ID
    "biolink:OrganismTaxon",   # Category
    "Escherichia coli"         # Name
]

# 2. Process each trait type
for trait_type in [metabolism, pathways, carbon_substrates, cell_shape, isolation_source]:
    
    # Try METPO mapping (most reliable)
    if trait_value in METPO_mappings:
        node, edge = create_from_METPO(trait_value)
    
    # Fallback to NER results (ChEBI/GO)
    elif trait_value in NER_results:
        node, edge = create_from_NER(trait_value)
    
    # Last resort: custom ID
    else:
        node, edge = create_custom(trait_value)
    
    write_to_graph(node, edge)
```

### Example: Processing "glucose" as a carbon substrate

```
Input: "glucose" (from carbon_substrates column)
    │
    ├─ Step 1: Check METPO mapping
    │  └─ Not found in METPO
    │
    ├─ Step 2: Check ChEBI NER results
    │  └─ Found: "glucose" → CHEBI:17234 (D-glucose)
    │
    └─ Step 3: Create nodes and edges
       ├─ Node: [CHEBI:17234, biolink:ChemicalEntity, "D-glucose"]
       └─ Edge: [NCBITaxon:562, biolink:consumes, CHEBI:17234, RO:0002470]
```

---

## Ontology Mappings

### 1. METPO (Microbial Ecology Traits and Phenotypes Ontology)
**Purpose:** Standardize microbial trait terminology

**Applied to:**
- Metabolism types (aerobe, anaerobe, facultative)
- Cell shapes (rod, cocci, spiral)
- Some pathways and substrates

**Example:**
```python
"aerobe" → METPO:0000001 (aerobic organism)
"rod" → METPO:0000123 (rod-shaped cell)
```

### 2. ChEBI (Chemical Entities of Biological Interest)
**Purpose:** Identify and standardize chemical compounds

**Applied to:**
- Carbon substrates (glucose, acetate, etc.)
- Metabolites

**Method:** NER using OAK (Ontology Access Kit)

**Example:**
```python
"glucose" → CHEBI:17234 (D-glucose)
"acetate" → CHEBI:30089 (acetate)
```

**Chemical Roles:**
The transformer also extracts chemical roles from ChEBI:
```python
CHEBI:17234 (glucose) 
  ├─ has_role → CHEBI:33284 (nutrient)
  └─ has_role → CHEBI:35358 (carbon source)
```

### 3. GO (Gene Ontology)
**Purpose:** Standardize biological processes and pathways

**Applied to:**
- Metabolic pathways
- Biological processes

**Method:** NER using OAK

**Example:**
```python
"glycolysis" → GO:0006096 (glycolytic process)
"photosynthesis" → GO:0015979 (photosynthesis)
```

### 4. ENVO (Environment Ontology)
**Purpose:** Standardize environmental terms

**Applied to:**
- Isolation sources (where organism was found)

**Example:**
```python
"soil" → ENVO:00001998 (soil)
"marine" → ENVO:00000569 (marine water body)
```

### Mapping Priority (Fallback Strategy)

```
┌──────────────────────────────────────────┐
│ Tier 1: METPO Mapping                   │
│ - Most reliable for microbial traits    │
│ - Includes Biolink predicates            │
│ - Manually curated                       │
└─────────────┬────────────────────────────┘
              │ Not found
              ▼
┌──────────────────────────────────────────┐
│ Tier 2: NER (ChEBI/GO)                   │
│ - Automatic text mining                  │
│ - Good for chemicals & pathways          │
│ - Prefers exact matches                  │
└─────────────┬────────────────────────────┘
              │ Not found
              ▼
┌──────────────────────────────────────────┐
│ Tier 3: Custom ID                        │
│ - Fallback for unmapped terms            │
│ - Format: PREFIX:original_term           │
│ - Example: pathway:nitrogen_fixation     │
└──────────────────────────────────────────┘
```

---

## Output Files

### 1. `nodes.tsv`
Tab-separated file containing all entities in the knowledge graph.

**Format:**
```tsv
id                      category                    name
NCBITaxon:562          biolink:OrganismTaxon       Escherichia coli
CHEBI:17234            biolink:ChemicalEntity      D-glucose
GO:0006096             biolink:BiologicalProcess   glycolytic process
METPO:0000001          biolink:Phenotype           aerobic organism
ENVO:00001998          biolink:Environment         soil
```

**Node Types:**
- **Organisms:** NCBITaxon IDs
- **Chemicals:** ChEBI IDs
- **Pathways:** GO IDs
- **Traits:** METPO IDs or custom IDs
- **Environments:** ENVO IDs

### 2. `edges.tsv`
Tab-separated file containing relationships between entities.

**Format:**
```tsv
subject             predicate               object              relation
NCBITaxon:562       biolink:consumes        CHEBI:17234        RO:0002470
NCBITaxon:562       biolink:capable_of      GO:0006096         RO:0002215
NCBITaxon:562       biolink:has_phenotype   METPO:0000001      RO:0002200
ENVO:00001998       biolink:location_of     NCBITaxon:562      RO:0001025
CHEBI:17234         biolink:has_role        CHEBI:33284        RO:0000087
```

**Edge Types:**

| Predicate | Meaning | Example |
|-----------|---------|---------|
| `biolink:consumes` | Organism uses chemical | E. coli → consumes → glucose |
| `biolink:capable_of` | Organism performs process | E. coli → capable_of → glycolysis |
| `biolink:has_phenotype` | Organism has trait | E. coli → has_phenotype → rod shape |
| `biolink:location_of` | Environment contains organism | Soil → location_of → E. coli |
| `biolink:has_role` | Chemical has function | Glucose → has_role → nutrient |

### 3. NER Results (intermediate files)
Cached NER results stored in output directory:

- `chebi_ner.tsv` - ChEBI annotations for carbon substrates
- `go_ner.tsv` - GO annotations for pathways

**Format:**
```tsv
carbon_substrates    object_id       object_label    subject_label
glucose              CHEBI:17234     D-glucose       glucose
acetate              CHEBI:30089     acetate         acetate
```

---

## Usage

### Basic Usage

```python
from kg_microbe.transform_utils.madin_etal import MadinEtAlTransform

# Initialize transformer
transformer = MadinEtAlTransform(
    input_dir="data/raw/madin_etal",
    output_dir="data/transformed/madin_etal",
    nlp=True  # Enable NER
)

# Run transformation
transformer.run(
    data_file="condensed_traits_NCBI.csv",
    show_status=True  # Show progress bars
)
```

### Without NLP (faster, but less accurate)

```python
# Skip NER step (uses only METPO mappings)
transformer = MadinEtAlTransform(
    input_dir="data/raw/madin_etal",
    output_dir="data/transformed/madin_etal",
    nlp=False
)
transformer.run()
```

### Required Input Files

Place these in your `input_dir`:

1. **condensed_traits_NCBI.csv** - Main data file from Madin et al.
2. **environments.csv** - ENVO mappings for isolation sources
3. **stopwords.txt** - Words to exclude from NER (optional)

### Expected Directory Structure

```
kg-microbe/
├── data/
│   ├── raw/
│   │   └── madin_etal/
│   │       ├── condensed_traits_NCBI.csv
│   │       └── environments.csv
│   └── transformed/
│       └── madin_etal/
│           ├── nodes.tsv          # Generated
│           ├── edges.tsv          # Generated
│           ├── chebi_ner.tsv      # Generated (if nlp=True)
│           └── go_ner.tsv         # Generated (if nlp=True)
```

---

## Architecture

### Class Structure

```python
class MadinEtAlTransform(Transform):
    """Main transformation class"""
    
    # Public methods
    def run()                              # Main entry point
    def pass_through()                     # Simple pass-through mode
    
    # Private helper methods (refactored for reusability)
    def _get_metpo_node_and_edge()         # METPO mapping logic
    def _perform_ner_if_needed()           # NER with caching
    def _process_ner_fallback()            # NER fallback processing
    def _process_isolation_source()        # ENVO mapping
    def _parse_comma_separated_values()    # CSV parsing utility
    def _filter_ner_results_exact_match()  # Prefer exact matches
```

### Helper Methods

#### `_get_metpo_node_and_edge()`
Unified method for METPO mapping across all trait types.

**Parameters:**
- `trait_value`: The trait value to map (e.g., "aerobe")
- `tax_id`: Organism taxonomy ID
- `default_category`: Fallback category if no METPO mapping
- `default_predicate`: Fallback predicate (e.g., "biolink:has_phenotype")
- `default_relation`: Relation type for edge

**Returns:** `(node, edge)` tuple or `(None, None)` if no mapping found

**Used by:** Metabolism, pathways, carbon substrates, cell shape

#### `_perform_ner_if_needed()`
Performs NER with intelligent caching. If results already exist, loads from cache.

**Parameters:**
- `data_df`: DataFrame with text to annotate
- `prefix`: Ontology prefix (e.g., "CHEBI:", "GO:")
- `output_filename`: Output filename for cached results
- `exclusion_list`: Words to exclude from NER
- `manual_annotation_path`: Optional manual annotations for better accuracy

**Returns:** DataFrame with NER results

**Used by:** ChEBI annotation (carbon substrates), GO annotation (pathways)

#### `_process_ner_fallback()`
Standardized fallback when METPO mapping not available. Filters NER results and creates nodes/edges.

**Parameters:**
- `items_to_process`: List of items needing NER mapping
- `ner_results`: DataFrame with NER results
- `tax_id`: Organism taxonomy ID
- `column_name`: Column being processed (for filtering)
- `category`: Node category
- `prefix`: Prefix for custom IDs
- `edge_type`: Edge predicate
- `relation`: Relation type for edge

**Returns:** `(nodes, edges)` tuple of lists

**Used by:** Pathways (→GO), Carbon substrates (→ChEBI)

#### `_process_isolation_source()`
Maps isolation sources to ENVO terms. Handles both single and comma-separated multiple environments.

**Parameters:**
- `isolation_source_value`: The isolation source text
- `tax_id`: Organism taxonomy ID
- `envo_mapping`: Dictionary of ENVO mappings

**Returns:** `(nodes, edges)` tuple of lists

**Special handling:** Comma-separated ENVO terms are split into multiple nodes/edges

#### `_parse_comma_separated_values()`
Parses comma-separated trait values and handles NA values consistently.

**Parameters:**
- `value`: The cell value to parse
- `na_value`: String representing NA/missing values (default: "NA")

**Returns:** List of parsed values or `None` if all NA

**Used by:** Pathways, carbon substrates (supports "glucose, acetate, citrate")

#### `_filter_ner_results_exact_match()`
Filters NER results to prefer exact matches between input text and ontology term labels.

**Parameters:**
- `ner_results`: DataFrame with NER results

**Returns:** Filtered DataFrame (exact matches if available, otherwise all results)

**Improves quality:** Reduces false positives from fuzzy NER matching

---

## Design Decisions

### Why Three-Tier Mapping?

1. **METPO (Tier 1)**: Most reliable for microbial traits, includes domain expertise
2. **NER (Tier 2)**: Good for chemicals and pathways, automated but accurate
3. **Custom (Tier 3)**: Preserves all data, even unmapped terms

### Why Cache NER Results?

NER is computationally expensive (~10 seconds per column). Caching:
- ✅ Speeds up repeated runs (seconds vs minutes)
- ✅ Allows manual review and correction
- ✅ Enables reproducibility

### Why Extract Chemical Roles?

Chemical roles (e.g., "glucose has_role nutrient") provide:
- ✅ Richer semantics for downstream analysis
- ✅ Functional classification of chemicals
- ✅ Better integration with other knowledge graphs

---

## Performance

**Typical runtime** (on ~10,000 organisms):
- With NLP (first run): ~10-15 minutes
- With NLP (cached): ~2-3 minutes
- Without NLP: ~1 minute

**Memory usage:** ~500 MB - 1 GB (depends on NER cache size)

**Output size:**
- ~50,000 nodes
- ~200,000 edges

---

## Troubleshooting

### Issue: NER taking too long
**Solution:** NER results are cached. First run is slow, subsequent runs are fast.

### Issue: Missing ChEBI/GO mappings
**Solution:** Check internet connection. OAK downloads ontologies on first use.

### Issue: "NA" values in output
**Solution:** These are unmapped terms. Either:
1. Add to METPO mappings
2. Add to manual ChEBI annotations
3. Keep as custom IDs for manual review

### Issue: Duplicate nodes/edges
**Solution:** Duplicates are automatically removed at end of processing. If persisting, check input data.

---

## References

- **Madin et al. Dataset**: [bacteria-archaea-traits GitHub](https://github.com/bacteria-archaea-traits/bacteria-archaea-traits)
- **ChEBI**: [Chemical Entities of Biological Interest](https://www.ebi.ac.uk/chebi/)
- **GO**: [Gene Ontology](http://geneontology.org/)
- **ENVO**: [Environment Ontology](http://environmentontology.org/)
- **Biolink Model**: [Biolink Model](https://biolink.github.io/biolink-model/)
- **OAK**: [Ontology Access Kit](https://github.com/INCATools/ontology-access-kit)

---

## Contributing

To add new trait types or improve mappings:

1. Add trait column to `traits_columns_of_interest`
2. Implement processing logic (reuse helper methods)
3. Add to METPO mappings if needed
4. Update this README

For questions or issues, contact the KG-Microbe team.
