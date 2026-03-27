---
name: kg-query
description: Query KG-Microbe for organism information, growth media preferences, and metabolic capabilities
---

# KG-Microbe Query Skill

Query the KG-Microbe knowledge graph for organism information including taxonomy, phenotypic traits, growth media, and media composition.

## Usage

### Basic Query
```bash
poetry run kg query-organism "Eggerthella lenta"
```

### Save to File
```bash
poetry run kg query-organism "Corynebacterium glutamicum" -o report.md
```

### Options
- `--db-path PATH`: Custom database location (default: data/merged/kg-microbe.duckdb)
- `--force-reload`: Rebuild database from TSV files
- `--nodes-path PATH`: Custom nodes.tsv location
- `--edges-path PATH`: Custom edges.tsv location
- `--output FILE`: Save report to file instead of printing

## Query Capabilities

1. **Name Resolution**: Fuzzy matching on organism names and synonyms
2. **Taxonomy**: Species classification hierarchy
3. **Phenotypic Traits**: Oxygen preference, metabolism, morphology, Gram stain
4. **Media Preferences**: Growth media with METPO:2000517 (grows in) and METPO:2000518 (doesn't grow in)
5. **Media Composition**: 2-hop traversal (organism → media → solutions → chemicals)
6. **Strain Information**: All strain records linked to species

## Data Sources
- Nodes: 1.5M entries (883K organism taxa)
- Edges: 6.1M relationships
- Primary sources: BacDive, MediaDive, MadinEtal, BactoTraits, GTDB, UniProt

## Example Organisms
- Eggerthella lenta (NCBITaxon:84112) - 65+ strains, 4 growth media
- Corynebacterium glutamicum (NCBITaxon:1718)
- Escherichia coli (NCBITaxon:562)
- Bacillus subtilis (NCBITaxon:1423)

## Performance
- Initial database load: ~60 seconds (one-time, cached)
- Subsequent queries: <1 second
- Database file size: ~800MB

## Technical Details
- **Database**: DuckDB persistent storage
- **Query engine**: SQL with 1-hop and 2-hop graph traversal
- **Output format**: Markdown report with structured sections
- **Caching**: Database persisted to disk for fast repeat queries
