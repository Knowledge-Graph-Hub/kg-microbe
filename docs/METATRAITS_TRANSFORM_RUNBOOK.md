# Metatraits Transform: Runbook for New Dataset

This document describes how to run the metatraits transform on new metatraits summary data.

## Overview

The metatraits transform reads JSONL summary files (species, genus, family level), resolves taxon names to NCBITaxon IDs, maps trait names to ontology terms (CHEBI, EC, GO, METPO), and outputs KGX-format `nodes.tsv` and `edges.tsv`.

**Edge predicate resolution:** The transform emits distinct Biolink predicates based on trait type—no longer collapsing all traits to `has_phenotype`. For example, `produces: ethanol` → `biolink:produces` with CHEBI object; `carbon source: acetate` → `biolink:capable_of`; `gram positive` → `biolink:has_phenotype`.

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

With `ncbitaxon_nodes.tsv` in place, the transform uses only the cache for taxon resolution—no OAK adapter is created and no download occurs. The OAK adapter (and potential ~2GB download) is created only when a taxon is not found in the cache (first cache miss).

## Running the Transform

```bash
poetry run kg transform -s metatraits
```

Default paths:
- **Input:** `data/raw/`
- **Output:** `data/transformed/metatraits/`

## Trait Mapping Lookup

Trait names are resolved in this order:

1. **Curated microbial-trait-mappings** (`mappings/metatraits/*.tsv`) — authoritative lookup from [turbomam/microbial-trait-mappings](https://github.com/turbomam/microbial-trait-mappings). TSVs by entity type:
   - `chemical_mappings.tsv` — produces compounds (CHEBI)
   - `enzyme_mappings.tsv` — enzyme activities (EC, GO)
   - `pathway_mappings.tsv` — pathways (GO)
   - `phenotype_mappings.tsv` — phenotypes (METPO)

2. **METPO + custom_curies** — fallback for traits not in the curated TSVs.

| Trait pattern | Example | Biolink predicate | Object ontology |
|--------------|---------|-------------------|-----------------|
| Produces compound | produces: ethanol | biolink:produces | CHEBI |
| Carbon/nitrogen source | carbon source: acetate | biolink:capable_of | CHEBI, GO |
| Enzyme activity | enzyme activity: catalase (EC1.11.1.6) | biolink:capable_of | EC, GO |
| Pathway | fermentation, nitrogen fixation | biolink:capable_of | GO |
| Phenotype | gram positive, thermophilic | biolink:has_phenotype | METPO |

## Output Files

| File | Description |
|------|--------------|
| `nodes.tsv` | Taxon and trait nodes in KGX format |
| `edges.tsv` | Taxon–trait edges with Biolink predicates (`biolink:produces`, `biolink:capable_of`, `biolink:has_phenotype`) |
| `unmapped_traits.tsv` | Traits that could not be mapped to ontology terms |
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

## Adding New Trait Mappings

To map a new trait that appears in `unmapped_traits.tsv`:

1. **Preferred:** Contribute to [turbomam/microbial-trait-mappings](https://github.com/turbomam/microbial-trait-mappings) (PR with new rows in the appropriate TSV). Once merged, copy the updated TSV into `mappings/metatraits/`.

2. **Local override:** Add a row to the appropriate TSV in `mappings/metatraits/`. Required columns:
   - `subject_label` — trait name (e.g. `produces: ethanol`)
   - `subject_label_normalized` — lowercase variant for case-insensitive lookup
   - `object_id` — CURIE (e.g. `CHEBI:16236`, `EC:1.11.1.6`, `GO:0008150`)
   - `object_label` — human-readable label
   - `object_source` — CHEBI, EC, GO, or METPO
   - `notes` — include `biolink:produces`, `biolink:capable_of`, or `biolink:has_phenotype` to specify the predicate

3. **Fallback:** Add to `custom_curies.yaml` or METPO synonym mappings (used when trait is not in curated TSVs).

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

**Recent updates (predicate resolution):**

- Curated mappings from `mappings/metatraits/` (turbomam/microbial-trait-mappings) are the primary lookup.
- Edges now emit distinct predicates: `biolink:produces`, `biolink:capable_of`, `biolink:has_phenotype` instead of collapsing to `has_phenotype`.
- Loader: `kg_microbe/utils/microbial_trait_mappings.py`.
