# Metatraits Transform: Runbook for New Dataset

This document describes how to run the metatraits transform on new metatraits summary data.

## Overview

The metatraits transform reads JSONL summary files (species, genus, family level), resolves taxon names to NCBITaxon IDs, maps trait names to METPO/ontology terms, and outputs KGX-format `nodes.tsv` and `edges.tsv`.

## Prerequisites

### 1. Environment Setup

```bash
# Use Python 3.11 (Python 3.14 has compatibility issues with some dependencies)
poetry env use python3.11

# Install dependencies
poetry install

# If you see "No module named 'pkg_resources'", downgrade setuptools:
poetry run pip install "setuptools<82"
```

### 2. Input Files

Place one or more metatraits JSONL files in `data/raw/`. Supported filenames:

| Convention | Species | Genus | Family |
|------------|---------|-------|--------|
| `ncbi_*` | `ncbi_species_summary.jsonl` | `ncbi_genus_summary.jsonl` | `ncbi_family_summary.jsonl` |
| `metatraits_*` | `metatraits_species_summary.jsonl` | `metatraits_genus_summary.jsonl` | `metatraits_family_summary.jsonl` |

Files may be gzipped (`.jsonl.gz`) or plain (`.jsonl`).

**Expected JSONL format** (one JSON object per line):

```json
{"tax_name": "Escherichia coli", "summaries": [{"name": "antibiotic_resistance", "is_discrete": true, "num_observations": 15, "majority_label": "true: (100%)", "percentages": {"true": 100.0}}]}
```

### 3. Taxon Resolution (Optional but Recommended)

To avoid slow OAK lookups or a ~2GB NCBITaxon download, provide NCBITaxon labels:

**Option A:** Run ontologies transform first (produces `data/transformed/ontologies/ncbitaxon_nodes.tsv`):

```bash
poetry run kg transform -s ontologies
```

**Option B:** Manually place `ncbitaxon_nodes.tsv` in `data/raw/` (TSV format: `id`, `category`, `name`, ...).

Without this, the transform falls back to OAK's `sqlite:obo:ncbitaxon`, which may download a large database on first use.

## Running the Transform

```bash
poetry run kg transform -s metatraits
```

Default paths:
- **Input:** `data/raw/`
- **Output:** `data/transformed/metatraits/`

## Output Files

| File | Description |
|------|--------------|
| `nodes.tsv` | Taxon and trait nodes in KGX format |
| `edges.tsv` | Taxon–trait edges (e.g. `biolink:has_phenotype`, METPO predicates) |
| `unmapped_traits.tsv` | Traits that could not be mapped to METPO/ontology |
| `unresolved_taxa.tsv` | Taxon names that could not be resolved to NCBITaxon IDs |

## Verification

After a successful run:

```bash
# Check output
head data/transformed/metatraits/nodes.tsv
head data/transformed/metatraits/edges.tsv

# Review unmapped/unresolved (if any)
cat data/transformed/metatraits/unmapped_traits.tsv
cat data/transformed/metatraits/unresolved_taxa.tsv
```

## Quick Test with Fixture

To verify the transform without full production data:

```bash
cp tests/resources/metatraits_fixture.jsonl data/raw/ncbi_species_summary.jsonl
poetry run kg transform -s metatraits
```

This produces a small graph (2 taxa, 2 traits, 3 edges).

## Merge into Full KG

To include metatraits in the merged knowledge graph, ensure `merge.yaml` (or `merge.minimal.yaml`) includes the metatraits source. The default config already references:

```yaml
metatraits:
  name: "metatraits"
  # ...
  - data/transformed/metatraits/nodes.tsv
  - data/transformed/metatraits/edges.tsv
```

Then run:

```bash
poetry run kg merge -y merge.yaml
```

## Troubleshooting

See [METATRAITS_TRANSFORM_ANALYSIS.md](METATRAITS_TRANSFORM_ANALYSIS.md) for:
- Why NCBITaxon may download (~2GB)
- Why the progress bar may appear stuck
- How taxon resolution and caching work

## Summary of Changes (Registration)

The metatraits transform is registered in `kg_microbe/transform.py` under `DATA_SOURCES`. If you cloned before this was added, ensure your `transform.py` includes:

```python
METATRAITS: MetatraitsTransform,
```
