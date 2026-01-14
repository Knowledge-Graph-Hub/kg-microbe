# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KG-Microbe is a knowledge graph construction project for microbial traits and beyond. It integrates multiple data sources (BacDive, MediaDive, UniProt, CTD, etc.) with ontologies (NCBITaxon, ChEBI, GO, ENVO, etc.) to create a comprehensive knowledge graph of microbial organisms, their traits, growth media, metabolic pathways, and associated chemical compounds.

The project follows a three-stage pipeline: **Download → Transform → Merge**

## Core Commands

### Development Setup
```bash
pip install poetry
poetry install
```

### Main Pipeline Commands
```bash
# Download all data sources (configured in download.yaml)
poetry run kg download

# Transform downloaded data into KG format (TSV: nodes.tsv, edges.tsv)
poetry run kg transform

# Transform specific sources only
poetry run kg transform -s bacdive -s mediadive

# Merge all transformed graphs (configured in merge.yaml or merge.minimal.yaml)
poetry run kg merge -y merge.yaml
```

### Testing and Quality Checks
```bash
# Run all quality checks before committing (REQUIRED before every commit)
poetry run tox

# Run specific test suites
poetry run pytest                    # Run all tests
poetry run pytest tests/test_file.py # Run specific test file

# Individual quality checks
poetry run tox -e format             # Format code (black + ruff --fix)
poetry run tox -e lint               # Check code style
poetry run tox -e codespell-write    # Fix spelling errors
poetry run tox -e docstr-coverage    # Check documentation coverage
```

### Summary Statistics
```bash
make run-summary  # Generate node and edge counts by category
```

### Machine Learning and Queries
```bash
# Generate holdout sets for ML training (splits graph into train/test/validation)
poetry run kg holdouts -n data/merged/nodes.tsv -e data/merged/edges.tsv -o data/holdouts/

# Run SPARQL queries against the knowledge graph
poetry run kg query -y queries/sparql/example_query.yaml -o data/queries/
```

### Neo4j Upload (optional)
```bash
make neo4j-upload  # Upload merged KG to local Neo4j instance
```

## Architecture

### Pipeline Stages

1. **Download** (`kg_microbe/download.py`)
   - Downloads resources defined in `download.yaml`
   - Sources stored in `data/raw/`
   - Uses `kghub-downloader` library

2. **Transform** (`kg_microbe/transform.py`)
   - Each data source has its own transform class in `kg_microbe/transform_utils/[source_name]/`
   - All transform classes inherit from `Transform` base class (`transform_utils/transform.py`)
   - Each transform produces `nodes.tsv` and `edges.tsv` in `data/transformed/[source_name]/`
   - Node/edge headers defined in base `Transform` class using constants from `constants.py`

3. **Merge** (`kg_microbe/merge_utils/merge_kg.py`)
   - Uses KGX library to merge transformed graphs
   - Configuration in `merge.yaml` or `merge.minimal.yaml`
   - Outputs to `data/merged/` as TSV (optionally tar.gz compressed)
   - Generates graph statistics in `merged_graph_stats.yaml`

### Transform Architecture

All transform classes follow this pattern:
- Located in `kg_microbe/transform_utils/[source_name]/`
- Class name: `[SourceName]Transform` (e.g., `BacDiveTransform`, `MediaDiveTransform`)
- Registered in `DATA_SOURCES` dict in `kg_microbe/transform.py`
- Implement `run()` method from base `Transform` class
- Output standard KGX TSV format (nodes.tsv, edges.tsv)

Key transform sources (currently active in DATA_SOURCES):
- **bacdive**: Bacterial diversity data (taxon traits, growth media, metabolic properties)
- **mediadive**: Growth media composition data
- **madin_etal**: Condensed bacterial/archaeal traits from literature
- **bactotraits**: Bacterial trait data
- **ontologies**: OBO ontologies (ENVO, ChEBI, GO, NCBITaxon, MONDO, HP, EC)
- **rhea_mappings**: Rhea reaction mappings to GO and EC

Additional available transforms (commented out in DATA_SOURCES):
- **uniprot_functional_microbes**: Protein data for functional microbes
- **ctd**: Comparative Toxicogenomics Database
- **disbiome**: Microbiome-disease associations
- **wallen_etal**: Additional bacterial trait data
- **uniprot_human**: Human protein data

### Key Files

- `kg_microbe/run.py`: CLI entry point with Click commands
- `kg_microbe/transform_utils/constants.py`: Standard column names (ID_COLUMN, CATEGORY_COLUMN, etc.)
- `kg_microbe/transform_utils/custom_curies.yaml`: Custom CURIE prefix mappings
- `kg_microbe/transform_utils/translation_table.yaml`: Entity type translations
- `pyproject.toml`: Poetry configuration, ruff/black settings

### Data Flow

```
download.yaml → data/raw/[source].json/csv/owl
                      ↓
              Transform Classes
                      ↓
        data/transformed/[source]/nodes.tsv
        data/transformed/[source]/edges.tsv
                      ↓
                merge.yaml
                      ↓
            data/merged/merged-kg.tar.gz
```

## Important Notes

### Memory Requirements
The KG construction process is computationally intensive, particularly:
- Trimming NCBI Taxonomy
- Processing microbial UniProt datasets (for KG-Microbe-Function and KG-Microbe-Biomedical-Function)

Successful execution may require significant memory resources (e.g., >500 GB RAM for certain operations).

### Pre-commit Requirement
**ALWAYS run `poetry run tox` before every commit** to ensure code quality. This runs all quality checks: format, lint, codespell, docstr-coverage, and tests.

### Environment Variables
Copy `.env.example` to `.env` and configure:
- `BACDIVE_USERNAME`: BacDive API email
- `BACDIVE_PASSWORD`: BacDive API password

## Naming Conventions

- Transform classes: `[SourceName]Transform` in `transform_utils/[source_name]/[source_name].py`
- Source name constants: Uppercase in `transform_utils/constants.py` (e.g., `BACDIVE = "bacdive"`)
- Output files: Always `nodes.tsv` and `edges.tsv` per source
- Column names: Use constants from `constants.py` (e.g., `SUBJECT_COLUMN`, `PREDICATE_COLUMN`, `OBJECT_COLUMN`)

## Code Style

- Line length: 120 characters (ruff), 100 characters (black)
- Python: ≥3.10
- Linting: ruff with pydocstyle (D), pycodestyle (E), Pyflakes (F), isort (I), flake8-bandit (S)
- Type hints required for function signatures
- Docstrings required (checked by `docstr-coverage`)

## Testing

Tests in `tests/` directory:
- `test_transform_class.py`: Transform class tests
- `test_transform_utils.py`: Transform utility tests
- `test_run.py`: CLI command tests
- `test_query.py`: SPARQL query tests

Test resources in `tests/resources/`

## Common Patterns

### Adding a New Transform

1. Create directory: `kg_microbe/transform_utils/[new_source]/`
2. Create transform class inheriting from `Transform`
3. Implement `run()` method to generate nodes.tsv and edges.tsv
4. Add constant to `constants.py`: `NEW_SOURCE = "new_source"`
5. Register in `DATA_SOURCES` dict in `kg_microbe/transform.py`
6. Add download entry to `download.yaml`
7. Add merge entry to `merge.yaml`

### Standard Edge Format

Edges must include:
- `subject`: Subject node ID (with CURIE prefix)
- `predicate`: Biolink predicate (e.g., `biolink:related_to`)
- `object`: Object node ID (with CURIE prefix)
- `relation`: RO or other relation ontology term
- `primary_knowledge_source`: Source provenance

### Standard Node Format

Nodes must include:
- `id`: Unique CURIE identifier
- `category`: Biolink category (e.g., `biolink:OrganismTaxon`, `biolink:ChemicalEntity`)
- `name`: Human-readable label
- Other optional fields: `description`, `xref`, `synonym`, `provided_by`