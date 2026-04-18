# Archived Mapping Files

**Archive Date:** 2026-04-07  
**Reason:** Phase 2 migration - consolidated into unified_chemical_mappings.tsv.gz

---

## Archived Files

### metabolite_mapping.json

**Original Purpose:** Manual ChEBI ID mappings for BacDive antibiotic/chemical names

**Entries:** 193 mappings (antibiotics, antimicrobials, selective agents)

**Migration:**
- All 193 mappings consolidated into `mappings/unified_chemical_mappings.tsv.gz`
- Now searchable via `ChemicalMappingLoader.find_chebi_by_name()`
- Source tracking: `bacdive_antibiotics[manual_pre-2026]`

**Provenance:** See `metabolite_mapping_provenance.md` (retained in parent directory)

**Format Before Migration:**
```json
{
  "CHEBI:28971": "ampicillin",
  "CHEBI:17698": "chloramphenicol",
  ...
}
```

**Usage Before Migration:**
```python
# Old approach (hard-coded JSON)
with open("metabolite_mapping.json") as f:
    METABOLITE_MAP = json.load(f)

# Reverse lookup: name -> ChEBI ID
name_to_chebi = {v: k for k, v in METABOLITE_MAP.items()}
chebi_id = name_to_chebi.get(compound_name)
```

**Usage After Migration:**
```python
# New approach (data-driven unified file)
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

chemical_loader = ChemicalMappingLoader()
chebi_id = chemical_loader.find_chebi_by_name(compound_name)
# Automatically searches unified file including all synonyms
```

---

## Migration Categories

The 193 BacDive mappings included:

| Category | Count | Examples |
|----------|-------|----------|
| Beta-lactam antibiotics | 45 | ampicillin, cephalothin, imipenem |
| Aminoglycosides | 17 | streptomycin, gentamicin, kanamycin |
| Macrolides | 12 | erythromycin, clarithromycin |
| Fluoroquinolones | 13 | ciprofloxacin, levofloxacin |
| Tetracyclines | 7 | tetracycline, doxycycline |
| Sulfonamides | 11 | sulfamethoxazole, trimethoprim |
| Glycopeptides | 4 | vancomycin, teicoplanin |
| Miscellaneous | 84 | Various antibiotics and chemicals |

Full categorization in `metabolite_mapping_provenance.md`

---

## Migration Details

**Commit:** [Migration commit hash]  
**Branch:** `fix_metatraits`  
**Documentation:**
- `metabolite_mapping_provenance.md` - Full provenance for all 193 mappings
- `CHEMICAL_MAPPINGS_MIGRATION_PLAN.md` - Migration strategy

---

## Restoration

This file was never tracked in git (listed in .gitignore). Restoration from archive:

```bash
cp kg_microbe/transform_utils/bacdive/archive/metabolite_mapping.json \
   kg_microbe/transform_utils/bacdive/
```

**Note:** Restoring file does NOT undo the migration. The unified file remains the authoritative source.

---

## Why Archive Instead of Delete?

1. **Historical reference** - Preserve original curation work (193 manual mappings)
2. **Provenance chain** - Maintain link to original data
3. **Verification** - Enable comparison with unified file if needed
4. **Clinical importance** - Antibiotics are critically important; preserve all records

---

**See Also:**
- `PROVENANCE_WORK_SUMMARY.md` - Phase 1 & 2 overview
- `metabolite_mapping_provenance.md` - Complete antibiotic/chemical provenance
- `mappings/unified_chemical_mappings.tsv.gz` - Current authoritative source
