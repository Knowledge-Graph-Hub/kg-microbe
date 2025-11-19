# Bakta Genome Annotations Transform

This transform processes Bakta genome annotation files and converts them to KGX format for integration into KG-Microbe.

## Setup

### 1. SAMN to NCBITaxon Mapping

The transform requires a mapping file to convert SAMN (BioSample) IDs to NCBITaxon IDs:

```bash
# Generate the mapping (this queries NCBI and takes ~15-30 minutes for 145 genomes)
# Note: Biopython is already installed as a dependency
poetry run python kg_microbe/transform_utils/bakta/create_samn_mapping.py \
  --input data/raw/pfas_bakta/bakta \
  --output kg_microbe/transform_utils/bakta/samn_to_ncbitaxon.tsv \
  --email your_email@example.com

# To resume if interrupted:
poetry run python kg_microbe/transform_utils/bakta/create_samn_mapping.py \
  --input data/raw/pfas_bakta/bakta \
  --output kg_microbe/transform_utils/bakta/samn_to_ncbitaxon.tsv \
  --email your_email@example.com \
  --resume
```

**Notes**:
- NCBI requires an email address for API access
- Set `NCBI_API_KEY` environment variable for higher rate limits (10 req/sec vs 3 req/sec)
- The script uses manual XML parsing to avoid Biopython DTD/Schema parsing issues
- Get an API key from: https://www.ncbi.nlm.nih.gov/account/settings/

### 2. GO Ontology Setup (Optional but Recommended)

For accurate GO term aspect mapping (biological_process vs molecular_function vs cellular_component), set up the GO ontology:

#### Option A: Convert OWL to SQLite (Recommended for Performance)

```bash
# Install semsql if not available
pip install oaklib[semsql]

# Convert GO OWL to SQLite (run once, takes a few minutes)
runoak -i data/raw/go.owl dump -o data/raw/go.db -O sql
```

#### Option B: Use OBO Format

Add to `download.yaml`:
```yaml
-
  url: http://purl.obolibrary.org/obo/go.obo
  local_name: go.obo
```

Then update `constants.py`:
```python
GO_SOURCE = RAW_DATA_DIR / "go.obo"
```

#### Option C: Skip GO Aspect Mapping

The transform will work without the GO ontology - all GO terms will default to `biolink:MolecularActivity` and use the `enables` predicate. This is acceptable but less precise than proper aspect mapping.

## Usage

### Transform Bakta Annotations

```bash
# Transform all Bakta genomes
poetry run kg transform -s bakta

# Output will be in data/transformed/bakta/
# - nodes.tsv (~1.09M nodes)
# - edges.tsv (~4M edges)
```

### Run Tests

```bash
# Run Bakta-specific tests
poetry run pytest tests/test_bakta.py -v

# Run all tests with quality checks
poetry run tox
```

## Data Structure

### Input

Bakta genome annotations in `data/raw/pfas_bakta/bakta/`:
```
bakta/
├── SAMN00103324/
│   ├── SAMN00103324.bakta.tsv  (main annotation file)
│   ├── SAMN00103324.bakta.gff3
│   ├── SAMN00103324.bakta.faa
│   └── ...
├── SAMN00117502/
└── ... (145 total genomes)
```

### Output

KGX TSV files:
- **nodes.tsv**: Organism, Gene, Protein, GO, EC, COG, KEGG nodes
- **edges.tsv**: Relationships between entities

## Annotation Coverage

Based on analysis of ~145 genomes with ~580,000 genes:

| Annotation Type | Coverage | Count | Biolink Category |
|----------------|----------|-------|------------------|
| UniRef/RefSeq | 86-100% | ~580K | Protein IDs |
| GO Terms | ~66% | ~385K | BiologicalProcess, MolecularActivity, CellularComponent |
| COG Groups | ~38% | ~220K | GeneFamily |
| EC Numbers | ~17% | ~99K | MolecularActivity |
| KEGG KOs | ~12% | ~70K | GeneFamily |

## Node Types

- `biolink:OrganismTaxon` - Bacterial organisms (via SAMN → NCBITaxon mapping)
- `biolink:Gene` - Genes with composite IDs (e.g., `SAMN00139461:JEECHJ_00005`)
- `biolink:Protein` - Proteins (RefSeq preferred, UniRef50 fallback)
- `biolink:BiologicalProcess` - GO biological processes
- `biolink:MolecularActivity` - GO molecular functions and EC numbers
- `biolink:CellularComponent` - GO cellular components
- `biolink:GeneFamily` - COG functional groups and KEGG orthologs

## Edge Types

- Organism `biolink:has_gene` Gene (`RO:0002551`)
- Gene `biolink:has_gene_product` Protein (`RO:0002205`)
- Protein `biolink:enables` MolecularActivity (`RO:0002327`)
- Protein `biolink:involved_in` BiologicalProcess (`RO:0002331`)
- Protein `biolink:located_in` CellularComponent (`RO:0001025`)
- Gene `biolink:member_of` COG (`RO:0002350`)
- Gene `biolink:orthologous_to` KEGG (`RO:HOM0000017`)

## Troubleshooting

### "no such table: rdfs_label_statement" Error

This means the ontology SQLite database wasn't properly created. Solutions:

1. **Convert OWL to SQLite** (see Setup section above)
2. **Let OAK auto-detect format** - the transform will handle this automatically
3. **Use without ontology** - the transform will default all GO terms to molecular_function

The transform has been updated to handle missing GO ontology gracefully.

### NCBI API Rate Limits

When creating the SAMN mapping:
- Without API key: 3 requests/second (default)
- With API key: 10 requests/second

Set `NCBI_API_KEY` environment variable:
```bash
export NCBI_API_KEY="your_api_key_here"
```

Get an API key from: https://www.ncbi.nlm.nih.gov/account/settings/

### Memory Requirements

Processing 145 genomes with ~580K genes requires:
- Minimum: 8 GB RAM
- Recommended: 16 GB RAM

For very large datasets, consider processing in batches.

## Files

- `bakta.py` - Main BaktaTransform class
- `utils.py` - Helper functions for parsing and processing
- `create_samn_mapping.py` - Script to generate SAMN → NCBITaxon mappings
- `samn_to_ncbitaxon.tsv` - Mapping file (generated by script)
- `tmp/` - Temporary processing files

## Integration with KG-Microbe

The Bakta transform is registered in `kg_microbe/transform.py` and configured in `merge.yaml`. It integrates with:

- **BacDive** - May share overlapping SAMN/organism IDs
- **Ontologies** - Uses GO, EC terms from ontology transforms
- **MediaDive** - Complementary organism-level data
