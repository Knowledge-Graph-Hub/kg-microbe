# Phenotype Mappings Correction Validation Checklist

## Before Applying Fix

### 1. Backup Current File
```bash
cp kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv \
   kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv.backup_$(date +%Y%m%d)
```

### 2. Check Current Edge Counts
```bash
# Run transform with current (broken) mappings
poetry run kg transform -s metatraits

# Count edges by METPO phenotype class
grep -E "METPO:100[06]" data/transformed/metatraits/edges.tsv | cut -f3 | sort | uniq -c

# Expected (WRONG) results:
# - METPO:1000606 ("obligately aerobic") - should only be for "obligate aerobic"
#   but also incorrectly includes "gram positive"
# - METPO:1000607 ("obligately anaerobic") - should only be for "obligate anaerobic"
#   but also incorrectly includes "gram negative"
```

### 3. Sample Current Edges (showing bugs)
```bash
# See which taxa have WRONG phenotype mappings
grep "METPO:1000606" data/transformed/metatraits/edges.tsv | head -5
grep "METPO:1000607" data/transformed/metatraits/edges.tsv | head -5
```

## Applying Fix

### 1. Replace Mapping File
```bash
cp mappings/phenotype_mappings_corrected.tsv \
   kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv
```

### 2. Verify File Replacement
```bash
# Should show 9 lines (1 header + 8 corrected mappings + 1 custom)
wc -l kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv

# Should show new CURIEs (1000698, 1000699, 1000870, etc.)
cut -f3 kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv | sort
```

## After Applying Fix

### 1. Run Transform with Corrected Mappings
```bash
# Clear previous output
rm -rf data/transformed/metatraits/

# Transform with corrected mappings
poetry run kg transform -s metatraits
```

### 2. Verify Corrected Edge Counts
```bash
# Count edges by corrected METPO phenotype classes
grep -E "METPO:1000(698|699|870|606|607|702|614|616)" data/transformed/metatraits/edges.tsv | \
  cut -f3 | sort | uniq -c

# Expected (CORRECT) results:
# - METPO:1000698 ("gram positive") - only for "gram positive" traits
# - METPO:1000699 ("gram negative") - only for "gram negative" traits
# - METPO:1000606 ("obligately aerobic") - only for "obligate aerobic" traits
# - METPO:1000607 ("obligately anaerobic") - only for "obligate anaerobic" traits
# - METPO:1000702 ("motile") - only for "presence of motility" traits
# - METPO:1000870 ("sporulation") - only for "sporulation" traits
# - METPO:1000614 ("psychrophilic") - only for "psychrophilic" traits
# - METPO:1000616 ("thermophilic") - only for "thermophilic" traits
```

### 3. Verify No Custom KGM Terms (unless voges-proskauer)
```bash
# Check for KGM terms (should only be voges-proskauer if any)
grep "KGM:" data/transformed/metatraits/edges.tsv | cut -f3 | sort | uniq -c

# Expected: only KGM:voges_proskauer_test_positive (if that trait exists in data)
```

### 4. Compare Before/After Total Edge Counts
```bash
# Before (with bug):
wc -l data/transformed/metatraits_backup/edges.tsv

# After (corrected):
wc -l data/transformed/metatraits/edges.tsv

# Counts should be similar (within ~1% difference)
# Phenotype edges redistributed to correct METPO classes
```

### 5. Spot Check Specific Taxa
```bash
# Example: Find a gram-positive organism and verify it now has correct phenotype
# Before: NCBITaxon:1234 -> biolink:has_phenotype -> METPO:1000606 (WRONG: "obligately aerobic")
# After:  NCBITaxon:1234 -> biolink:has_phenotype -> METPO:1000698 (CORRECT: "gram positive")

grep -i "gram" data/raw/metatraits/*.jsonl.gz | head -1 | jq .taxon_name
# Then grep for that taxon in edges to verify phenotype mapping
```

## Expected Changes Summary

### Edges That Should Change

| Trait | Old METPO | Old Label (WRONG) | New METPO | New Label (CORRECT) |
|-------|-----------|-------------------|-----------|---------------------|
| gram positive | 1000606 | obligately aerobic | 1000698 | gram positive |
| gram negative | 1000607 | obligately anaerobic | 1000699 | gram negative |
| sporulation | 1000614 | psychrophilic | 1000870 | sporulation |
| obligate aerobic | 1000616 | thermophilic | 1000606 | obligately aerobic |
| obligate anaerobic | 1000870 | sporulation | 1000607 | obligately anaerobic |
| presence of motility | 1002005 | Fermentation | 1000702 | motile |
| psychrophilic | 1000660 | phototrophic | 1000614 | psychrophilic |
| thermophilic | 1000656 | photoautotrophic | 1000616 | thermophilic |
| voges-proskauer | 1005017 | NOT FOUND | KGM:custom | voges-proskauer |

### Total Impact Estimate

- **Affected traits**: 9 phenotype mappings
- **Affected edges**: ~50-500 edges (depends on trait frequency in metatraits data)
- **Scientific impact**: HIGH - fixes fundamental trait attribution errors
- **Breaking changes**: Tests expecting old CURIEs will fail (need updates)

## Test Updates Required

### Unit Tests
```bash
# Find tests expecting old CURIEs
grep -r "METPO:1000606" tests/
grep -r "METPO:1000607" tests/
grep -r "METPO:1000614" tests/
grep -r "METPO:1000616" tests/

# Update to expect new CURIEs
```

### Integration Tests
```bash
# Run full test suite
poetry run pytest tests/

# Expected failures: tests checking for specific METPO phenotype CURIEs
# Fix: update test fixtures to use correct CURIEs
```

## Rollback Plan (if needed)

```bash
# Restore original file
cp kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv.backup_YYYYMMDD \
   kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv

# Re-run transform
poetry run kg transform -s metatraits
```

## Sign-Off Checklist

- [ ] Backup of original phenotype_mappings.tsv created
- [ ] Before-fix edge counts documented
- [ ] Corrected mapping file applied
- [ ] Transform runs without errors
- [ ] After-fix edge counts verified
- [ ] Spot checks confirm correct phenotype assignments
- [ ] Test suite updated for new CURIEs
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Changes committed with clear message explaining bug fix

## Additional Resources

- Analysis: `mappings/CUSTOM_MAPPINGS_ANALYSIS.md`
- Implementation plan: `mappings/METPO_PRIORITY_CHANGE_PLAN.md`
- Full mapping comparison: `mappings/custom_mappings_not_in_metpo.tsv`
- Corrected mappings: `mappings/phenotype_mappings_corrected.tsv`

## Questions or Issues?

If edge counts differ significantly (>10%) or unexpected errors occur:
1. Check METPO ontology is loaded correctly
2. Verify all new CURIEs exist in current METPO release (2025-12-12)
3. Check for typos in corrected mapping file
4. Review transform logs for errors
5. Consider gradual rollout (fix a few mappings at a time)
