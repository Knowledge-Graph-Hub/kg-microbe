# METPO Proposals - ROBOT Template Compliance

**Date:** 2026-04-06  
**Status:** ✅ ROBOT template compliant  
**Format:** METPO ROBOT template (23 columns)

---

## Files in This Directory

### 1. **New Term Proposals** 
**File:** `metpo_gaps_and_proposals.tsv`

**Format:** ROBOT template (23 columns) - matches official METPO template exactly  
**Content:** 3 new METPO term proposals  
**Entries:**
- **METPO:1003XXX - alkaliphilic** (HIGH priority)
  - Only remaining hardcoded mapping in metatraits transform
  - 5,576 observations affected
  - Sibling to existing acidophilic/neutrophilic
  
- **METPO:2000XXX - has growth organic acid observation** (LOW priority)
  - 31 observations affected
  - Predicate for growth with organic acids
  
- **METPO:1003XXX - non-pigmented** (MEDIUM priority)
  - 1.45M observations affected (but low utility - negative assertions)
  - Companion to existing pigmented classes

### 2. **Synonym Proposals**
**File:** `metpo_metatraits_synonym_mappings.tsv`

**Format:** ROBOT template (23 columns) - matches official METPO template exactly  
**Content:** 23 synonym proposals for **existing** METPO terms  
**Purpose:** Add metatraits synonyms to existing METPO terms that lack them

**Examples:**
- METPO:2000701 (has growth temperature value) + synonym "temperature growth"
- METPO:2000702 (has minimum temperature value) + synonym "temperature min"
- METPO:2000008 (uses as electron acceptor) + synonym "electron acceptor"
- And 20 more...

### 3. **Gap Metadata** (Documentation)
**File:** `metpo_gaps_metadata.tsv`

**Format:** Extended format with priority/status/notes columns  
**Content:** Additional metadata about the 3 gap proposals  
**Purpose:** Documentation only - NOT for ROBOT submission

---

## ROBOT Template Compliance

### Official Template
Source: https://github.com/berkeleybop/metpo/blob/main/src/templates/metpo_sheet.tsv

**23 Columns:**
1. ID
2. label
3. TYPE
4. parent classes (one strongly preferred)
5. definition
6. definition source
7. term editor
8. comment
9. biolink close match
10. confirmed exact synonym
11. literature mining related synonyms
12. madin synonym or field
13. Madin synonym source
14. bacdive keyword synonym
15. Bacdive synonym source
16. bactotraits related synonym
17. Bactotraits synonym source
18. metatraits synonym
19. MetaTraits synonym source
20. measurement_unit_ucum
21. range_min
22. range_max
23. equivalent_class_formula

### Validation Status

**Both proposal files validated:**
```bash
✅ metpo_gaps_and_proposals.tsv - Header matches ROBOT template
✅ metpo_metatraits_synonym_mappings.tsv - Header matches ROBOT template
✅ Both files use Unix line endings (LF)
✅ Both files have exactly 23 columns
```

---

## Submission Process

### Ready for Submission

Both files are now ready to submit to the METPO team:

1. **metpo_gaps_and_proposals.tsv** - New term proposals
2. **metpo_metatraits_synonym_mappings.tsv** - Synonym additions

### How to Submit

**Option 1: GitHub Issue**
- Create issue at: https://github.com/berkeleybop/metpo/issues
- Attach both TSV files
- Reference `METPO_GAPS_FINAL.md` for detailed rationale

**Option 2: Pull Request**
- Fork METPO repository
- Add entries to `src/templates/metpo_sheet.tsv`
- Submit PR with both new terms and synonyms

**Option 3: Direct Contact**
- Email METPO team: Chris Mungall (cjmungall@lbl.gov)
- Attach both TSV files and documentation

---

## Implementation Notes

### After METPO Acceptance

Once these terms are added to METPO:

1. **Update metpo.json**
   - Download new METPO release
   - Place in `data/raw/metpo.json`

2. **Remove placeholder**
   - Replace `KGM:alkaliphilic` with new METPO ID
   - Update code in 2 locations (pH classification and pH preference)

3. **Test transform**
   - Run: `poetry run kg transform -s metatraits -s metatraits_gtdb`
   - Verify alkaliphilic observations now map correctly

4. **Verify coverage**
   - Should map 5,576 additional observations
   - Achieve 100% data-driven trait mapping (no placeholders)

---

## Related Documentation

- **`METPO_GAPS_FINAL.md`** - Detailed gap analysis and rationale
- **`METPO_GAPS_README.md`** - Overview of METPO gaps
- **`FINAL_HARDCODED_MAPPINGS_STATUS.md`** - Status showing alkaliphilic is only remaining gap
- **`metpo_gaps_metadata.tsv`** - Extended metadata for proposals

---

## Change Log

**2026-04-06:**
- ✅ Fixed `metpo_gaps_and_proposals.tsv` to match ROBOT template exactly
- ✅ Converted line endings to Unix (LF) format
- ✅ Removed extra columns (gap_type, observations_affected, priority, etc.)
- ✅ Moved metadata to separate `metpo_gaps_metadata.tsv` file
- ✅ Validated both files match official ROBOT template
- ✅ Improved synonym and definition text for clarity
- ✅ Added MetaTraits synonym source for all proposals

**2026-04-05:**
- Initial creation of proposal files

---

**Status:** ✅ Ready for submission to METPO team  
**Format:** ROBOT template compliant (validated)  
**Priority:** HIGH - alkaliphilic is the only remaining hardcoded mapping
