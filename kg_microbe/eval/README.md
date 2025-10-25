# KG-Microbe Evaluation Framework

This directory contains scripts for evaluating and comparing transform outputs to detect data quality degradation.

## Overview

The evaluation framework provides three main capabilities:

1. **Sample Taxa Generation** (`sample_taxa.py`) - Create reproducible random samples from source data
2. **Transform Evaluation** (`evaluate_transform.py`) - Analyze transform output for sampled taxa
3. **Transform Comparison** (`compare_transforms.py`) - Compare baseline vs current transform versions

## Quick Start

### 1. Generate Sample Taxa

Generate a random sample of 10 taxa from the source data:

```bash
poetry run python kg_microbe/eval/sample_taxa.py --source bacdive
```

The sample is saved to `kg_microbe/eval/samples/bacdive_sample_taxa.json` and will be reused on subsequent runs.

To regenerate a new random sample:

```bash
poetry run python kg_microbe/eval/sample_taxa.py --source bacdive --regenerate
```

To generate a larger sample:

```bash
poetry run python kg_microbe/eval/sample_taxa.py --source bacdive --sample-size 50 --regenerate
```

### 2. Evaluate Transform Output

Analyze the current transform output for the sampled taxa:

```bash
poetry run python kg_microbe/eval/evaluate_transform.py --source bacdive
```

This generates a report at `kg_microbe/eval/samples/bacdive_evaluation.json` with:
- Node and edge counts
- Category distributions
- Predicate distributions
- Category pair patterns
- Edges per strain statistics

Example output:
```
=== Summary ===
Sample size: 10 taxa
Total nodes: 30
Total edges: 61
Avg edges per strain: 4.0

Top 5 predicates:
  biolink:location_of: 17
  biolink:consumes: 13
  biolink:subclass_of: 10
  biolink:has_phenotype: 6
  biolink:occurs_in: 5
```

### 3. Compare Transform Versions

Compare a baseline version against the current transform output:

```bash
poetry run python kg_microbe/eval/compare_transforms.py \
  --source bacdive \
  --baseline-dir /path/to/baseline/data/transformed/bacdive
```

This will:
- Evaluate both baseline and current transforms
- Identify differences in counts, predicates, and categories
- Categorize differences by severity (critical, warning, info)
- Generate a comparison report
- Exit with error code 1 if critical differences are found

Example output:
```
=== Comparison Summary ===

CRITICAL: 2 differences
------------------------------------------------------------
  ❌ MISSING: edge_statistics.predicate_counts.biolink:interacts_with
     Baseline had: 15
  📉 CHANGED: edge_statistics.total_edges
     75 → 61 (-14, -18.7%)

WARNING: 1 differences
------------------------------------------------------------
  📈 CHANGED: edge_statistics.avg_edges_per_strain
     4.0 → 5.2 (+1.2, +30.0%)

⚠️  CRITICAL differences detected!
```

## Use Cases

### Regression Testing After Code Changes

After modifying transform code, verify no data degradation:

```bash
# 1. Save current transform as baseline
cp -r data/transformed/bacdive /tmp/bacdive_baseline

# 2. Make code changes to transform
# ... edit kg_microbe/transform_utils/bacdive/bacdive.py ...

# 3. Run transform with changes
poetry run kg transform -s bacdive

# 4. Compare baseline vs current
poetry run python kg_microbe/eval/compare_transforms.py \
  --source bacdive \
  --baseline-dir /tmp/bacdive_baseline
```

### CI/CD Integration

Add to GitHub Actions or other CI systems:

```yaml
- name: Run transform evaluation
  run: |
    poetry run python kg_microbe/eval/sample_taxa.py --source bacdive
    poetry run python kg_microbe/eval/evaluate_transform.py --source bacdive
```

### Comparing Different Transform Configurations

```bash
# Compare old vs new prefix format
poetry run python kg_microbe/eval/compare_transforms.py \
  --source bacdive \
  --baseline-dir data/transformed_old/bacdive \
  --current-dir data/transformed_new/bacdive
```

## Output Files

All output files are stored in `kg_microbe/eval/samples/`:

- `{source}_sample_taxa.json` - Random sample of taxa IDs
- `{source}_evaluation.json` - Evaluation report for current transform
- `{source}_comparison.json` - Comparison report between two versions

## Command-Line Reference

### sample_taxa.py

```
--source           Data source name (default: bacdive)
--regenerate       Force regeneration of sample even if one exists
--sample-size      Number of taxa to sample (default: 10)
```

### evaluate_transform.py

```
--source           Data source name (default: bacdive)
--data-dir         Override path to transformed data directory
--output           Path to save evaluation report
```

### compare_transforms.py

```
--source           Data source name (default: bacdive)
--baseline-dir     Path to baseline transformed data directory (required)
--current-dir      Path to current transformed data directory
--output           Path to save comparison report
```

## Extending to Other Data Sources

To add support for a new data source:

1. Update `get_raw_data_path()` in `sample_taxa.py` to handle the new source format
2. Add extraction logic for the source's ID field (like `extract_bacdive_ids()`)
3. Update `get_strain_node_ids()` in `evaluate_transform.py` to generate correct node IDs

## Design Principles

- **Reproducibility**: Samples are saved and reused for consistent testing
- **Modularity**: Each script has a single responsibility
- **Extensibility**: Easy to add new data sources and metrics
- **Automation-friendly**: Exit codes and JSON output for CI/CD integration
- **Backward compatibility**: Supports both old and new CURIE formats
