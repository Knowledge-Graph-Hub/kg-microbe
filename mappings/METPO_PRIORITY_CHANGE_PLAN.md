# METPO Priority Change Implementation Plan

## Executive Summary

This document outlines the plan to change the metatraits trait resolution order to prioritize METPO ontology mappings first, before manual TSV mappings. The analysis revealed:

1. **CRITICAL BUG**: phenotype_mappings.tsv contains 8 incorrect METPO CURIEs creating wrong edges
2. **32% of Tier 1 mappings** (8/25) use METPO terms and can be removed after priority change
3. **68% of Tier 1 mappings** (17/25) correctly delegate to external ontologies (ChEBI, GO, EC)
4. **100% of pattern resolvers** (32 patterns) correctly use METPO predicates

## Current Resolution Order (Problematic)

```
1. Tier 1: Manual mappings (4 TSV files)
   - chemical_mappings.tsv (7 ChEBI mappings)
   - enzyme_mappings.tsv (5 EC/GO mappings)
   - pathway_mappings.tsv (4 GO mappings)
   - phenotype_mappings.tsv (9 METPO mappings - 8 INCORRECT!)
2. Tier 1.5-2.0: Pattern-based resolvers (32 patterns)
3. Tier 3: METPO synonym matching (load_metpo_mappings)
4. Tier 4: OAK adapter search
```

## Proposed Resolution Order (Better)

```
1. Tier 1: METPO synonym matching (classes + properties)
   - Direct lookup from METPO ontology
   - 257 classes + 103 properties
   - Always up-to-date with METPO releases
2. Tier 2: Manual mappings (external ontologies only)
   - Remove METPO duplicates from phenotype_mappings.tsv
   - Keep ChEBI, GO, EC mappings
3. Tier 3: Pattern-based resolvers
   - Chemical patterns (carbon source, produces, ferments, etc.)
   - Metabolic patterns (electron acceptor, respiration, etc.)
   - Growth/trophic/enzyme/phenotype patterns
4. Tier 4: OAK adapter search (fallback)
```

## Critical Issues Found

### Issue 1: Incorrect METPO CURIEs in phenotype_mappings.tsv

**Impact**: Current KG has WRONG phenotype edges for these traits.

| Trait | Current (WRONG) | Actual Label | Correct CURIE | Should Be |
|-------|----------------|--------------|---------------|-----------|
| gram positive | METPO:1000606 | obligately aerobic | METPO:1000698 | gram positive |
| gram negative | METPO:1000607 | obligately anaerobic | METPO:1000699 | gram negative |
| sporulation | METPO:1000614 | psychrophilic | METPO:1000870 | sporulation |
| obligate aerobic | METPO:1000616 | thermophilic | METPO:1000606 | obligately aerobic |
| obligate anaerobic | METPO:1000870 | sporulation | METPO:1000607 | obligately anaerobic |
| presence of motility | METPO:1002005 | Fermentation | METPO:1000702 | motile |
| psychrophilic | METPO:1000660 | phototrophic | METPO:1000614 | psychrophilic |
| thermophilic | METPO:1000656 | photoautotrophic | METPO:1000616 | thermophilic |
| voges-proskauer test | METPO:1005017 | NOT FOUND | N/A | Remove or custom |

**Example of current bug**:
- Trait: "gram positive"
- Current mapping: METPO:1000606 → "obligately aerobic"
- **Result**: Gram-positive organisms are incorrectly labeled as obligately aerobic!

### Issue 2: Duplicate METPO Mappings

8 phenotype mappings duplicate METPO synonym matching capability:
- After fixing CURIEs, all 8 can be removed (METPO will resolve them automatically)
- Reduces manual maintenance burden
- Ensures consistency with METPO ontology

## Implementation Plan

### Phase 1: Fix Critical Bugs (URGENT)

**Tasks:**
1. ✅ Create corrected phenotype_mappings.tsv (see mappings/phenotype_mappings_corrected.tsv)
2. ⬜ Back up current phenotype_mappings.tsv
3. ⬜ Replace phenotype_mappings.tsv with corrected version
4. ⬜ Run transform to verify edge counts change as expected
5. ⬜ Compare edge outputs: should see phenotype changes for affected taxa

**Validation:**
```bash
# Before fix: check current edges
poetry run kg transform -s metatraits
grep "METPO:1000606" data/transformed/metatraits/edges.tsv | head -5

# After fix: edges should reference correct phenotypes
grep "METPO:1000698" data/transformed/metatraits/edges.tsv | head -5
```

### Phase 2: Implement METPO-First Resolution

**Code changes needed:**

1. **Modify metatraits.py:_resolve_trait()** to reorder resolution tiers:

```python
def _resolve_trait(self, trait_name: str) -> Optional[dict]:
    """Resolve trait name to ontology term with METPO-first priority."""

    # Tier 1: METPO synonym matching (HIGHEST PRIORITY)
    if metpo_result := self.trait_mapping.get(trait_name.lower()):
        return metpo_result

    # Tier 2: Manual external ontology mappings (ChEBI, GO, EC only)
    if manual_result := self.microbial_trait_mappings.get(trait_name.lower()):
        # Skip if it's a METPO mapping (should have been caught by Tier 1)
        if not manual_result.get("curie", "").startswith("METPO:"):
            return manual_result

    # Tier 3: Pattern-based resolvers
    for resolver in [
        self._resolve_chemical_trait,
        self._resolve_metabolic_trait,
        self._resolve_growth_substrate,
        self._resolve_trophic_mode,
        self._resolve_enzyme_activity,
        self._resolve_phenotype_trait,
    ]:
        if result := resolver(trait_name):
            return result

    # Tier 4: OAK adapter search (fallback)
    if self.oak_adapter:
        return self._oak_fallback(trait_name)

    return None
```

2. **Clean up phenotype_mappings.tsv** after METPO-first is working:

Remove these 8 entries (will be resolved by METPO automatically):
- gram positive → METPO:1000698
- gram negative → METPO:1000699
- sporulation → METPO:1000870
- obligate aerobic → METPO:1000606
- obligate anaerobic → METPO:1000607
- presence of motility → METPO:1000702
- psychrophilic → METPO:1000614
- thermophilic → METPO:1000616

Keep only:
- voges-proskauer test (if needed, or remove entirely)

**Validation:**
```bash
# Run transform with METPO-first
poetry run kg transform -s metatraits

# Compare edge counts by predicate
cut -f2 data/transformed/metatraits/edges.tsv | sort | uniq -c

# Verify no METPO edges are lost
# Should see same or more edges (better coverage from METPO synonyms)
```

### Phase 3: Testing & Validation

**Test cases:**

1. **Tier 1 (METPO) tests:**
   - "gram positive" → METPO:1000698 (was wrong, now correct)
   - "aerobic" → METPO:1000602 (from METPO synonym)
   - "facultative" → METPO:1001026 (from METPO synonym)

2. **Tier 2 (Manual external) tests:**
   - "produces: ethanol" → CHEBI:16236
   - "carbon source: acetate" → CHEBI:30089
   - "nitrogen fixation" → GO:0009399
   - "enzyme activity: catalase (EC1.11.1.6)" → EC:1.11.1.6

3. **Tier 3 (Pattern) tests:**
   - "carbon source: glucose" → ChEBI lookup → CHEBI:17234
   - "electron acceptor: sulfate" → ChEBI lookup → CHEBI:16189
   - "growth: phototrophy" → GO:0009579
   - "aerotolerant" → METPO:1001025

4. **Edge count validation:**
   - Compare before/after edge counts
   - Ensure no regressions in coverage
   - Document any changes in trait resolution

### Phase 4: Documentation Updates

**Files to update:**

1. **README.md** - Update trait resolution section
2. **kg_microbe/transform_utils/metatraits/README.md** - Document new tier order
3. **CLAUDE.md** - Update metatraits section
4. **This document** - Mark as implemented

## Expected Benefits

### 1. Data Quality Improvements

- **Fixes critical bug**: 8 incorrect phenotype mappings corrected
- **Better coverage**: METPO synonyms provide broader trait matching
- **Consistency**: All METPO terms use official labels and predicates
- **Up-to-date**: Automatic updates when METPO ontology is updated

### 2. Maintenance Reduction

- **8 fewer manual mappings** to maintain in phenotype_mappings.tsv
- **Reduced TSV file complexity**: Only external ontology bridges remain
- **Clearer separation**: Manual mappings focus on ChEBI/GO/EC only

### 3. Scientific Accuracy

- **Correct phenotypes**: Organisms get correct trait labels
- **Ontology alignment**: Better integration with METPO standard
- **Traceable mappings**: Clear provenance from METPO ontology

## Risk Assessment

### Low Risk

- ✅ Pattern resolvers already use METPO predicates correctly
- ✅ External ontology mappings (ChEBI, GO, EC) are independent of METPO
- ✅ METPO synonym matching already tested and working

### Medium Risk

- ⚠️ Tests may expect wrong phenotype CURIEs (need to update)
- ⚠️ Edge counts may change slightly (better METPO coverage)
- ⚠️ Some traits may resolve to different METPO terms (verify equivalence)

### Mitigation

1. **Before/after comparison**: Run full transform before and after, compare outputs
2. **Test updates**: Update test fixtures to expect correct CURIEs
3. **Incremental rollout**: Fix bugs first, then change priority order
4. **Logging**: Add debug logging to track which tier resolves each trait

## Timeline

- **Week 1**: Phase 1 (Fix critical bugs) - URGENT
- **Week 2**: Phase 2 (Implement METPO-first resolution)
- **Week 3**: Phase 3 (Testing & validation)
- **Week 4**: Phase 4 (Documentation & release)

## Success Metrics

- [ ] 0 incorrect METPO CURIEs in manual mappings
- [ ] 8 duplicate METPO mappings removed from phenotype_mappings.tsv
- [ ] All test cases pass with new resolution order
- [ ] Edge counts stable or improved (no regressions)
- [ ] Documentation updated and accurate

## Files Created

- `mappings/custom_mappings_not_in_metpo.tsv` - Full mapping analysis
- `mappings/CUSTOM_MAPPINGS_ANALYSIS.md` - Detailed analysis report
- `mappings/phenotype_mappings_corrected.tsv` - Corrected phenotype mappings
- `mappings/METPO_PRIORITY_CHANGE_PLAN.md` - This implementation plan (you are here)

## References

- METPO Ontology: https://github.com/berkeleybop/metpo
- METPO Classes: https://github.com/berkeleybop/metpo/blob/main/src/templates/metpo_sheet.tsv
- METPO Properties: https://github.com/berkeleybop/metpo/blob/main/src/templates/metpo-properties.tsv
- KG-Microbe metatraits transform: kg_microbe/transform_utils/metatraits/metatraits.py
