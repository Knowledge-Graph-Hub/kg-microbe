---
name: audit-mappings
description: Audit transform code for hardcoded ontology mappings and generate coverage report
---

# Audit Mappings Skill

Scans KG-Microbe transform code to identify hardcoded ontology mappings and generates a comprehensive audit report. This skill helps maintain data-driven architecture by detecting inline CURIE mappings that should be moved to mapping files.

## What This Skill Audits

### Python Code Patterns
- **Hardcoded dictionaries** with CURIE values (e.g., `{"trait": "METPO:12345"}`)
- **Inline string assignments** with ontology prefixes (CHEBI:, GO:, EC:, METPO:, etc.)
- **Mapping dictionaries** embedded in transform code
- Filters out false positives: imports, comments, docstrings, configuration constants

### Mapping Files
- **TSV files** in `kg_microbe/transform_utils/*/mappings/*.tsv`
- **YAML files** like `custom_curies.yaml`
- **JSON files** matching pattern `*mapping*.json`
- Counts entries and categorizes by type

## Usage

### Audit all transforms
```bash
/audit-mappings
```

### Audit specific transform
```bash
/audit-mappings --transform metatraits
```

### Generate detailed report with code snippets
```bash
/audit-mappings --transform bacdive --verbose
```

### Generate markdown report
```bash
/audit-mappings --format md > mapping_audit_report.md
```

### Inventory mapping files only (skip code scanning)
```bash
/audit-mappings --mapping-files-only
```

## Options

- `--transform NAME` - Audit specific transform (default: all)
- `--format {text,json,md}` - Output format (default: text)
- `--verbose` - Include code snippets and line numbers
- `--mapping-files-only` - Only scan mapping files, skip Python code

## Output Format

### Text Format (default)
```
=== Hardcoded Mapping Audit Report ===
Date: 2026-04-06

Transform: metatraits
  Python hardcoded mappings: 1
    - metatraits.py:52-95 (METPO_TO_BIOLINK_PREDICATE, 44 entries)
  
  Mapping files: 5
    - chemical_name_synonyms.tsv (44 entries)
    - enzyme_name_to_go.tsv (34 entries)
    - special_chemical_mappings.tsv (35 entries)
    - ec2go.txt (4,822 entries)
  
  Status: ✅ 99.97% data-driven

---
Summary:
  Total transforms scanned: 20
  Transforms with hardcoded mappings: 15
  Total mapping files: 25
  Total mapping entries: 5,200+
```

### JSON Format
```json
{
  "report_date": "2026-04-06",
  "transforms": [
    {
      "name": "metatraits",
      "hardcoded_mappings": [...],
      "mapping_files": [...],
      "data_driven_percentage": 99.97
    }
  ],
  "summary": {...}
}
```

## Classification Rules

### Data-driven (Good) ✅
- Mappings loaded from TSV/YAML/JSON files
- Dynamic lookups via OAK/ChemicalMappingLoader
- Predicate lookups via resolver methods

### Hardcoded (Flag) ⚠️
- Inline dictionaries with >5 CURIE mappings
- String literals with CURIEs in business logic
- Should be migrated to mapping files

### Acceptable Hardcoded
- API endpoints and URLs
- Configuration constants (paths, file names)
- Schema-level mappings (e.g., METPO → Biolink predicates)
- Fallback placeholders for ontology gaps

## Use Cases

- **Audit data-driven compliance** before releases
- **Identify migration candidates** for refactoring
- **Track mapping coverage** across transforms
- **Prevent regressions** to hardcoded patterns
- **CI/CD quality checks** as part of test suite

## Implementation

See `audit_mappings.py` for the scanning logic.
