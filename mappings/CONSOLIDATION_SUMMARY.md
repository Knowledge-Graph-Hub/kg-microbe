# Chemical Mapping Consolidation Summary

**Branch**: `chemical_mappings`  
**Date**: 2026-03-16  
**Commit**: 1849ff71

## Overview

Consolidated 6 disparate chemical mapping sources into a single unified resource at `mappings/unified_chemical_mappings.tsv`.

## Statistics

### Input Sources

| Source File | Records | Type |
|------------|---------|------|
| `mappings/chemical_mappings.tsv` | 17,293 | KEGG/BacDive → ChEBI |
| `data/raw/compound_mappings_strict.tsv` | 17,654 | MediaDive ingredients |
| `data/raw/compound_mappings_strict_hydrate.tsv` | 17,654 | Hydrated compounds |
| `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` | 197 | BacDive metabolites |
| `kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv` | 164,508 | ChEBI cross-references |
| `kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv` | 6 | Manual annotations |
| **Total Input Records** | **217,312** | |

### Output

| Metric | Count |
|--------|-------|
| **Unique chemicals** | 164,702 |
| **Chemicals with synonyms** | 1,596 |
| **Total synonyms** | 1,596 |
| **Total cross-references** | 405,564 |
| **Merged duplicates** | 15 |

### Cross-Reference Coverage

The unified mapping includes cross-references to:
- KEGG Compound
- CAS Registry Numbers
- PubChem
- Beilstein
- Reaxys
- KNApSAcK
- LipidMaps
- MetaCyc
- DrugBank
- Wikipedia
- PubMed
- And more...

## Key Features

### 1. Deduplication

- **By ChEBI ID**: Primary key for merging records
- **By normalized name**: Case-insensitive, punctuation-normalized matching
- **Preference**: Lowest ChEBI ID retained when duplicates found

### 2. Synonym Consolidation

Examples of chemicals with multiple synonyms:

```
CHEBI:42758 (glucose):
  - D(+)-Glucose
  - D-Glucose
  - D-glucose
  - Dextrose
  - glucose
  - α-D-Glucose
```

### 3. Comprehensive Cross-References

Example entry with multiple xrefs:

```
CHEBI:10002 (visnagin):
  - cas:82-57-5
  - kegg.compound:C09049
  - knapsack:C00002447
  - lincs.smallmolecule:LSM-25873
  - lipidmaps:LMPK13110003
  - wikipedia.en:Visnagin
  - Multiple PubMed citations
```

### 4. Source Attribution

Each chemical tracks which mapping files contributed to its entry:

```
CHEBI:100241 (ciprofloxacin):
  Sources: primary_mappings[bacdive_metabolite] | chebi_xrefs
```

## Data Quality

### Confidence Levels

- **High confidence**: KEGG, ChEBI xrefs (well-established databases)
- **Medium confidence**: MediaDive ingredients (some complex mixtures)
- **Expert curated**: Manual annotations (highest trust for specific corrections)

### Known Limitations

1. **Complex mixtures**: Some MediaDive ingredients are complex (peptone, yeast extract)
2. **Hydration states**: Hydrated vs. anhydrous forms linked via xrefs
3. **Name variations**: Some synonyms represent different preparation methods

## File Structure

### Unified Mapping Columns

```
chebi_id         - Canonical ChEBI identifier
canonical_name   - Preferred chemical name (from ChEBI)
formula          - Chemical formula (when available)
synonyms         - Pipe-delimited alternative names
xrefs            - Pipe-delimited external database IDs
sources          - Pipe-delimited source file list
```

### Sample Records

```tsv
CHEBI:42758	aldehydo-D-glucose	C6H12O6	D(+)-Glucose|D-Glucose|...	kegg.compound:C00031|...	primary_mappings|chebi_xrefs
CHEBI:100241	ciprofloxacin		ciprofloxacin	kegg.compound:C05349|...	primary_mappings|bacdive_metabolites|chebi_xrefs
```

## Reproducibility

To regenerate the unified mapping:

```bash
python scripts/consolidate_chemical_mappings.py
```

The consolidation script:
1. Loads all 6 source mapping files
2. Extracts ChEBI IDs, names, formulas
3. Collects synonyms from all sources
4. Merges entries by ChEBI ID
5. Deduplicates by normalized chemical name
6. Exports to TSV format

## Usage Examples

### Find chemical by name

```bash
grep -i "ciprofloxacin" mappings/unified_chemical_mappings.tsv
```

### Get all synonyms for ChEBI ID

```bash
awk -F'\t' '$1=="CHEBI:42758" {print $4}' mappings/unified_chemical_mappings.tsv
```

### Find chemicals with KEGG xrefs

```bash
grep "kegg.compound" mappings/unified_chemical_mappings.tsv | head -10
```

### Count chemicals from each source

```bash
cut -f6 mappings/unified_chemical_mappings.tsv | \
  tr '|' '\n' | \
  sort | uniq -c | sort -rn
```

## Next Steps

### Potential Enhancements

1. **Add PubChem mappings**: Integrate PubChem Compound database
2. **Add InChI/SMILES**: Include structure identifiers
3. **Add molecular weight**: Extract from ChEBI ontology
4. **Add category information**: Link to Biolink categories (SmallMolecule, Macromolecule, Role)
5. **Validate formulas**: Cross-check chemical formulas across sources
6. **Add parent/child relationships**: Include ChEBI hierarchy

### Integration with Transforms

The unified mapping can be used by transform classes to:
- Resolve chemical names to ChEBI IDs
- Look up cross-references for data integration
- Validate chemical identifiers
- Standardize chemical names

## Files Modified

- ✅ `mappings/unified_chemical_mappings.tsv` - New unified mapping (164,702 chemicals)
- ✅ `mappings/README.md` - Documentation for mapping files
- ✅ `scripts/consolidate_chemical_mappings.py` - Consolidation script
- ✅ `mappings/CONSOLIDATION_SUMMARY.md` - This summary document

## Git Information

```bash
Branch: chemical_mappings
Commit: 1849ff71
Message: Add unified chemical mapping consolidation
Files:  3 files changed, 165,191 insertions(+)
```

---

**Prepared by**: Claude Opus 4.6  
**For**: KG-Microbe project
