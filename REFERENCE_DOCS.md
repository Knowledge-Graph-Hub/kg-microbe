# Reference Documentation - kg-microbe

**Last Updated**: January 10, 2026

This document lists all reference documentation and specifications used by kg-microbe.

---

## Schema and Format Specifications

### Biolink Model

**Purpose**: Standard schema for biological knowledge graphs

**Files:**
- **Python package**: biolink-model 3.6.0 (installed via Poetry)
  - Location: virtualenv/lib/python3.10/site-packages/biolink_model/
  - Used for: Programmatic validation, Python imports

- **YAML specification**: biolink-model.yaml v4.3.6
  - Location: data/raw/biolink-model.yaml
  - Downloaded from: https://raw.githubusercontent.com/biolink/biolink-model/v4.3.6/biolink-model.yaml
  - Used for: Schema reference, predicate lookup, deprecation tracking
  - Size: 445 KB

**Documentation:**
- Official docs: https://biolink.github.io/biolink-model/
- GitHub repo: https://github.com/biolink/biolink-model
- Changelog: https://github.com/biolink/biolink-model/blob/master/ChangeLog

**Version discrepancy note**: See BIOLINK_PREDICATE_CHANGES.md for details on why YAML is v4.3.6 but Python package is v3.6.0 (dependency conflict with pyobo).

---

### KGX Format

**Purpose**: Knowledge Graph Exchange format specification (TSV/CSV/JSON serialization)

**Files:**
- **Markdown specification**: kgx-format.md
  - Location: data/raw/kgx-format.md
  - Downloaded from: https://raw.githubusercontent.com/biolink/kgx/master/docs/kgx_format.md
  - Used for: File format reference, validation rules
  - Size: 20 KB

- **Python package**: kgx 2.4.0+ (installed via Poetry)
  - Used for: Graph operations, merging, validation

**Documentation:**
- Official docs: https://kgx.readthedocs.io/
- Format spec: https://kgx.readthedocs.io/en/latest/kgx_format.html
- GitHub repo: https://github.com/biolink/kgx

**Key points from specification:**
- KGX uses Biolink Model JSON Schema for validation
- Node/edge properties must conform to Biolink Model
- Supports TSV, CSV, JSON, JSON Lines, RDF Turtle formats
- Each node/edge represented with all describing properties
- Lenient with non-Biolink properties for inclusivity

---

## Schema Compliance Reports

### Node Category Compliance

**File**: NAMEDTHING_ANALYSIS.md

**Summary**: Analysis of biolink:NamedThing usage across all transforms

**Key findings:**
- Total nodes analyzed: 1.1M+
- NamedThing occurrences: 1 (0.0001%)
- Compliance: Excellent (99.9999%)
- Action items: Filter RO:0002333 from EC ontology

---

### Node/Edge Property Compliance

**File**: SCHEMA_COMPLIANCE_ANALYSIS.md

**Summary**: Analysis of property misuse (node properties in edges, edge properties in nodes)

**Key findings:**
- Edge properties in nodes: 0 violations
- Node properties in edges: 0 violations
- Compliance score: 10/10
- Status: Production-ready

---

### Predicate Deprecations

**File**: BIOLINK_PREDICATE_CHANGES.md

**Summary**: Documentation of deprecated predicates between Biolink v3.6.0 and v4.3.6

**Key changes:**
- `biolink:assesses` - REMOVED
- `biolink:is_assessed_by` - REMOVED
- `biolink:was_tested_for_effect_on` - DEPRECATED
- Replacement: Use `biolink:affects` and subpredicates

**Migration status**: Pending search of kg-microbe codebase for usage

---

## Ontology Sources

### Local Ontologies (downloaded)

All ontologies are downloaded to `data/raw/` via `poetry run kg download`:

| Ontology | Format | Size | Version | Purpose |
|----------|--------|------|---------|---------|
| NCBITaxon | OWL.gz | Large | Latest | Organism taxonomy |
| ChEBI | OWL.gz | Large | Latest | Chemical entities |
| ENVO | JSON | Medium | Latest | Environments |
| GO | JSON/OWL | Large | Latest | Gene ontology |
| EC | JSON/OWL.gz | Medium | Latest | Enzyme classification |
| METPO | OWL | Small | Latest | Metabolomics |
| MONDO | JSON | Large | Latest | Diseases (commented out) |
| HP | JSON | Medium | Latest | Phenotypes (commented out) |
| UBERON | OWL | Large | Latest | Anatomy |
| FOODON | OWL | Large | Latest | Food |
| UniPathways | OWL | Small | Latest | Metabolic pathways |

---

## Data Source Documentation

### Transform Documentation

Each data source transform should have a README.md in its directory:

- `kg_microbe/transform_utils/bacdive/README.md`
- `kg_microbe/transform_utils/mediadive/README.md`
- `kg_microbe/transform_utils/bakta/README.md`
- etc.

### External Data Sources

All external data sources configured in `download.yaml`:

**Databases:**
- BacDive: Bacterial diversity
- MediaDive: Growth media
- BactoTraits: Bacterial traits
- Madin et al: Condensed traits

**Mappings:**
- Rhea: Reaction mappings (GO, EC)
- COG: Clusters of Orthologous Groups
- KEGG: Kyoto Encyclopedia of Genes and Genomes
- MicroMediaParam: Chemical compound mappings

**Proteomes:**
- UniProt Functional Microbes
- UniProt Human (commented out)

---

## Quick Reference Commands

### Download all reference documentation
```bash
poetry run kg download
```

### Check installed package versions
```bash
poetry show biolink-model
poetry show kgx
poetry show pyobo
poetry show curies
```

### Validate against Biolink Model
```bash
# Using kgx (Python package - uses v3.6.0)
poetry run kgx validate -i data/transformed/source/nodes.tsv -i data/transformed/source/edges.tsv

# Manual check against v4.3.6 YAML
# Use data/raw/biolink-model.yaml for reference
```

### Search for deprecated predicates
```bash
grep -r "assesses\|is_assessed_by" kg_microbe/
grep "assesses\|is_assessed_by" data/transformed/*/edges.tsv
```

---

## Version Control

**Reference documents in version control:**
- ✅ download.yaml (tracked)
- ✅ BIOLINK_PREDICATE_CHANGES.md (tracked)
- ✅ NAMEDTHING_ANALYSIS.md (tracked)
- ✅ SCHEMA_COMPLIANCE_ANALYSIS.md (tracked)
- ✅ REFERENCE_DOCS.md (tracked)

**Reference documents in .gitignore:**
- ❌ data/raw/biolink-model.yaml (not tracked - downloaded via kg download)
- ❌ data/raw/kgx-format.md (not tracked - downloaded via kg download)
- ❌ data/raw/*.owl, *.json (not tracked - downloaded via kg download)

**Rationale**: Raw data files are regenerated via `poetry run kg download`, so we only track the configuration (download.yaml) and analysis reports.

---

## Updating Reference Documentation

### When Biolink Model updates

1. Check for new release: https://github.com/biolink/biolink-model/releases
2. Update download.yaml version number
3. Run `poetry run kg download`
4. Review changelog for breaking changes
5. Update BIOLINK_PREDICATE_CHANGES.md if needed
6. Attempt `poetry add biolink-model@latest` (may fail due to dependencies)
7. Re-run compliance reports if schema changes significantly

### When KGX format updates

1. Check for new release: https://github.com/biolink/kgx/releases
2. Run `poetry run kg download` to get latest kgx-format.md
3. Update `poetry add kgx@latest`
4. Review changelog for format changes
5. Test merge operations: `poetry run kg merge -y merge.yaml`

---

## Related Documentation

- **Project documentation**: CLAUDE.md (general project guide)
- **Branch work summaries**: docs/202512_*.md
- **Modeling decisions**: docs/METPO_*.md, docs/CHEMICAL_*.md

---

**Maintained by**: kg-microbe team
**Repository**: https://github.com/KG-Hub/KG-Microbe
