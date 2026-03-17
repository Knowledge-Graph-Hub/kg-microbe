# Chemical Mappings

This directory contains unified chemical mapping resources for KG-Microbe.

## Unified Chemical Mappings

**`unified_chemical_mappings.tsv`** - Consolidated chemical mappings from all KG-Microbe sources

### File Structure

| Column | Description |
|--------|-------------|
| `chebi_id` | Canonical ChEBI identifier (e.g., CHEBI:42758) |
| `canonical_name` | Preferred chemical name from ChEBI |
| `formula` | Chemical formula (when available) |
| `synonyms` | Pipe-delimited list of alternative names |
| `xrefs` | Pipe-delimited list of external database references |
| `sources` | Pipe-delimited list of source mapping files |

### Statistics

- **Total chemicals**: 164,702 unique ChEBI IDs
- **Chemicals with synonyms**: 1,596
- **Total cross-references**: 405,564
- **Sources consolidated**: 6 mapping files

### Source Files Consolidated

1. **`chemical_mappings.tsv`** - KEGG/BacDive to ChEBI mappings
   - Original KEGG compound IDs
   - BacDive API terms
   - BacDive metabolite names

2. **`data/raw/compound_mappings_strict.tsv`** - MediaDive ingredient mappings
   - Growth medium ingredients
   - Complex ingredients (peptone, yeast extract)
   - Concentration and unit metadata

3. **`data/raw/compound_mappings_strict_hydrate.tsv`** - Hydrated compound mappings
   - Hydrated forms (e.g., CuSO4.5H2O)
   - Base compound identification
   - Corrected molar concentrations

4. **`kg_microbe/transform_utils/bacdive/metabolite_mapping.json`** - BacDive metabolites
   - Antibiotics and resistance markers
   - 197 manually curated mappings

5. **`kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv`** - ChEBI cross-references
   - CAS Registry Numbers
   - KEGG Compound IDs
   - PubChem IDs
   - Other database identifiers

6. **`kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv`** - Expert annotations
   - Manually curated corrections
   - Trait dataset mappings

### Usage Examples

#### Find a chemical by name
```bash
grep -i "glucose" mappings/unified_chemical_mappings.tsv
```

#### Get all synonyms for a ChEBI ID
```bash
awk -F'\t' '$1=="CHEBI:42758" {print $4}' mappings/unified_chemical_mappings.tsv
```

#### Find chemicals with KEGG cross-references
```bash
grep "kegg.compound" mappings/unified_chemical_mappings.tsv
```

### Regenerating the Unified Mapping

To regenerate the unified mapping file after updating source files:

```bash
python scripts/consolidate_chemical_mappings.py
```

This will:
1. Load all source mapping files
2. Merge entries by ChEBI ID
3. Consolidate synonyms and cross-references
4. Deduplicate by normalized chemical name
5. Export to `mappings/unified_chemical_mappings.tsv`

### Notes

- **Deduplication**: Entries with the same normalized chemical name are merged, with the lowest ChEBI ID retained as primary
- **Synonyms**: All variant names from different sources are collected (case variations, alternative names)
- **Cross-references**: External database IDs are preserved with their source prefix (e.g., `kegg.compound:C00031`)
- **Hydrates**: Hydrated forms are linked to their anhydrous base compounds via cross-references

### Data Quality

- **High-confidence mappings**: KEGG and ChEBI cross-references are well-established
- **Medium-confidence**: MediaDive ingredient mappings may have complex/mixture compounds
- **Manual curation**: Expert annotations provide corrections for trait dataset terms

### Related Files

- **`chemical_mappings_mismatches.tsv`** - Compounds that couldn't be mapped to ChEBI
- **Original source files** - Preserved in their original locations for reference

## Maintenance

Last updated: 2026-03-16

Maintainer: KG-Microbe team

For questions or to report mapping errors, please open an issue on the KG-Microbe GitHub repository.
