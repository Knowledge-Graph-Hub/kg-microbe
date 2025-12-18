# Knowledge Graph Visualization Examples

This directory contains example scripts for creating network visualizations from the KG-Microbe knowledge graph.

## Example Data Files

Subgraph data extracted from the merged knowledge graph for **Corynebacterium glutamicum** (NCBITaxon:1718):

- `corynebacterium_glutamicum_1hop_subgraph_nodes.csv` - 1-hop neighbor nodes
- `corynebacterium_glutamicum_1hop_subgraph_edges.csv` - 1-hop edges
- `corynebacterium_glutamicum_2hop_subgraph_nodes.csv` - 2-hop neighbor nodes
- `corynebacterium_glutamicum_2hop_subgraph_edges.csv` - 2-hop edges

## Visualization Scripts

### Simple Visualizations with Full Labels

**create_1hop_full_labels.py** - Create 1-hop subgraph visualization with full node labels

```bash
cd scripts/examples/visualization
python create_1hop_full_labels.py
```

Output: `corynebacterium_glutamicum_1hop_subgraph_full_labels.png`

**create_2hop_full_labels.py** - Create 2-hop subgraph visualization with full labels for 1-hop neighbors

```bash
python create_2hop_full_labels.py
```

Output: `corynebacterium_glutamicum_2hop_subgraph_full_labels.png`

**create_full_label_visualizations.py** - Create both 1-hop and 2-hop visualizations in one run

```bash
python create_full_label_visualizations.py
```

Outputs both PNG files above.

### Extracting Custom Subgraphs

**create_1hop_subgraph.py** - Extract and visualize custom 1-hop subgraphs from the full merged knowledge graph

```bash
# Using default paths (looks for data/merged/merged-kg_*.tsv in repo)
python create_1hop_subgraph.py

# Specifying custom paths
python create_1hop_subgraph.py \
  --nodes /path/to/merged-kg_nodes.tsv \
  --edges /path/to/merged-kg_edges.tsv \
  --center-id "NCBITaxon:1718" \
  --output ./my_output_prefix
```

**Arguments:**
- `--nodes` - Path to merged-kg_nodes.tsv file (optional if in repo structure)
- `--edges` - Path to merged-kg_edges.tsv file (optional if in repo structure)
- `--center-id` - Center node ID (default: NCBITaxon:1718 - C. glutamicum)
- `--output` - Output prefix for generated files (default: script directory)

**Outputs:**
- `{prefix}_subgraph_nodes.csv` - Subgraph nodes with hop information
- `{prefix}_subgraph_edges.csv` - Subgraph edges
- `{prefix}_subgraph.png` - Visualization
- `{prefix}_stats.json` - Summary statistics

## Requirements

```bash
pip install pandas networkx matplotlib numpy
```

## Node Category Colors

Visualizations use the following color scheme:

- **OrganismTaxon**: Red (#FF6B6B)
- **ChemicalEntity**: Teal (#4ECDC4)
- **ChemicalMixture / METPO:1004005**: Blue (#45B7D1)
- **Enzyme**: Green (#96CEB4)
- **PhenotypicQuality**: Yellow (#FFEAA7)
- **EnvironmentalFeature**: Purple (#DDA0DD)
- **ActivityAndBehavior**: Orange (#FFB347)

## Notes

- All scripts use relative paths based on script location
- PNG outputs are high-resolution (300 DPI) suitable for publications
- **Output files (*.png) are not committed to the repository** - they are generated locally when you run the scripts
- Visualization layout algorithms may vary between runs due to randomization
- For large subgraphs (>100 nodes), consider limiting labels or using interactive tools
