# Archived Mapping Files

**Archive Date:** 2026-04-07  
**Reason:** Phase 2 migration - consolidated into unified_chemical_mappings.tsv.gz

---

## Archived Files

### chemical_name_synonyms.tsv

**Original Purpose:** Manual ChEBI ID mappings for MetaTraits chemical names that failed direct lookup

**Entries:** 81 mappings (45 original + 19 Priority 2 + 17 Priority 3)

**Migration:**
- All 81 mappings consolidated into `mappings/unified_chemical_mappings.tsv.gz`
- Synonyms now searchable via `ChemicalMappingLoader.find_chebi_by_name()`
- Source tracking: `metatraits_chemical_synonyms[manual_2026-04-07]`

**Provenance:** See `chemical_name_synonyms_provenance.tsv` (retained in parent directory)

**Usage Before Migration:**
```python
# Old approach (hard-coded)
self.chemical_name_synonyms = self._load_chemical_name_synonyms()
if chemical_name in self.chemical_name_synonyms:
    synonym_data = self.chemical_name_synonyms[chemical_name]
    chebi_id = synonym_data["chebi_id"]
```

**Usage After Migration:**
```python
# New approach (data-driven)
from kg_microbe.utils.chemical_mapping_utils import find_chebi_by_name

chebi_id = find_chebi_by_name(chemical_name)
# Automatically searches unified file including all synonyms
```

---

## Migration Details

**Commit:** [Migration commit hash]  
**Branch:** `fix_metatraits`  
**Documentation:**
- `PROVENANCE.md` - Master provenance documentation
- `chemical_name_synonyms_provenance.tsv` - Full provenance for all 81 mappings
- `CHEMICAL_MAPPINGS_MIGRATION_PLAN.md` - Migration strategy and implementation

---

## Restoration

If you need to restore these files for historical comparison:

```bash
# View file contents from git history
git show HEAD~1:kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv

# Restore file to working directory (does not undo migration)
git restore --source=HEAD~1 kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv
```

**Note:** Restoring files does NOT undo the migration. The unified file remains the authoritative source.

---

## Why Archive Instead of Delete?

1. **Historical reference** - Preserve original curation work
2. **Provenance chain** - Maintain link to original data files
3. **Verification** - Enable comparison with migrated data if needed
4. **Documentation** - Shows evolution of mapping architecture

---

**See Also:**
- `PROVENANCE_WORK_SUMMARY.md` - Phase 1 & 2 overview
- `mappings/unified_chemical_mappings.tsv.gz` - Current authoritative source
