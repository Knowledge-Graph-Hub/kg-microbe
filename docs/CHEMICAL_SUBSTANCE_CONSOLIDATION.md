# ChemicalSubstance vs ChemicalEntity Consolidation

## Current State

KG-Microbe currently uses both `biolink:ChemicalSubstance` and `biolink:ChemicalEntity` inconsistently across the codebase.

### Constants Defined

From `kg_microbe/transform_utils/constants.py`:

```python
# General chemical category
CHEMICAL_CATEGORY = "biolink:ChemicalSubstance"              # Line 514

# Specific chemical categories
MEDIUM_CATEGORY = "biolink:ChemicalEntity"                    # Line 214
SOLUTION_CATEGORY = "biolink:ChemicalEntity"                  # Line 216
INGREDIENT_CATEGORY = "biolink:ChemicalEntity"                # Line 217
CARBON_SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"          # Line 220
METABOLITE_CATEGORY = "biolink:ChemicalEntity"                # Line 225
SUBSTRATE_CATEGORY = "biolink:ChemicalEntity"                 # Line 226
MEDIUM_TYPE_CATEGORY = "biolink:ChemicalMixture"              # Line 215
```

## Biolink Model History

### Historical Context
- **Biolink 1.x**: Used `biolink:ChemicalSubstance`
- **Biolink 2.x+**: Renamed to `biolink:ChemicalEntity` (ChemicalSubstance deprecated)
- **Current**: `biolink:ChemicalEntity` is the standard term

### Biolink Model Class Hierarchy

```
biolink:ChemicalEntity (current standard)
├── biolink:ChemicalMixture (mixtures of chemicals)
├── biolink:SmallMolecule (< 500 Da)
├── biolink:Polypeptide
├── biolink:Nucleic Acid Entity
└── ... (other subtypes)
```

**Note**: `biolink:ChemicalSubstance` was the old name for what is now `biolink:ChemicalEntity`.

## Problem

The codebase mixes both terms:
1. **CHEMICAL_CATEGORY** uses the deprecated `ChemicalSubstance`
2. **Specific categories** (media, metabolites, etc.) use the correct `ChemicalEntity`
3. This creates inconsistency and potential confusion

## Recommendation

**Standardize on `biolink:ChemicalEntity` throughout the codebase.**

### Rationale:
1. **Biolink compliance**: ChemicalEntity is the current standard
2. **Consistency**: All chemical-related categories should use the same base class
3. **Future-proofing**: ChemicalSubstance may be removed in future Biolink versions
4. **Semantic clarity**: "Entity" is more inclusive than "Substance"

## Proposed Changes

### Step 1: Update CHEMICAL_CATEGORY constant

```python
# kg_microbe/transform_utils/constants.py
- CHEMICAL_CATEGORY = "biolink:ChemicalSubstance"
+ CHEMICAL_CATEGORY = "biolink:ChemicalEntity"
```

### Step 2: Verify all usages

Check where `CHEMICAL_CATEGORY` is used:
```bash
grep -r "CHEMICAL_CATEGORY" kg_microbe/transform_utils/
```

Expected locations:
- Ontology transforms (ChEBI, etc.)
- Chemical node creation in various transforms

### Step 3: Update visualization scripts

Files using ChemicalSubstance for color coding:
- `neo4j/create_1hop_subgraph.py:95`
- `create_2hop_full_labels.py:44`
- `create_full_label_visualizations.py:69`
- `create_full_label_visualizations.py:194`
- `create_1hop_full_labels.py:70`

Change color map keys from `biolink:ChemicalSubstance` to `biolink:ChemicalEntity`.

## Category Hierarchy Recommendations

### Current Usage (Keep As-Is)

These specific categories are correctly using ChemicalEntity/ChemicalMixture:

| Category Constant | Biolink Class | Usage | Correct? |
|-------------------|---------------|-------|----------|
| MEDIUM_CATEGORY | ChemicalEntity | Growth media | ✅ (Consider ChemicalMixture) |
| SOLUTION_CATEGORY | ChemicalEntity | Chemical solutions | ✅ |
| INGREDIENT_CATEGORY | ChemicalEntity | Media ingredients | ✅ |
| CARBON_SUBSTRATE_CATEGORY | ChemicalEntity | Carbon sources | ✅ |
| METABOLITE_CATEGORY | ChemicalEntity | Metabolites | ✅ |
| SUBSTRATE_CATEGORY | ChemicalEntity | Reaction substrates | ✅ |
| MEDIUM_TYPE_CATEGORY | ChemicalMixture | Medium type classification | ✅ |

### Future Consideration

As discussed in `CHEMICAL_MIXTURE_ANALYSIS.md`, consider changing:
- `MEDIUM_CATEGORY` → `biolink:ChemicalMixture` (growth media are mixtures)
- Keep ingredients as `ChemicalEntity` (individual components)

## Impact Analysis

### Affected Nodes (Estimated)
Based on grep results from transformed data:
- **ChemicalSubstance nodes**: ~452,304 (will become ChemicalEntity)
- **ChemicalEntity nodes**: ~15,620 (already correct)
- **ChemicalMixture nodes**: 2+ (medium types, potentially more)

### Backward Compatibility
- ✅ **No breaking changes**: ChemicalEntity is a valid Biolink class
- ✅ **Semantic equivalence**: ChemicalSubstance was just renamed to ChemicalEntity
- ✅ **Predicate compatibility**: All predicates valid for ChemicalSubstance work with ChemicalEntity

### Testing Requirements
After making changes:
1. Run transforms: `poetry run kg transform`
2. Check node categories: Verify all chemical nodes use ChemicalEntity or ChemicalMixture
3. Run merge: `poetry run kg merge -y merge.yaml`
4. Validate: Check merged graph statistics for category distribution

## Implementation Priority

**Priority: Low**

This is a **cleanup/standardization** task, not a bug fix. Should be done:
- When making other category-related updates
- Before major Biolink model version upgrade
- During codebase refactoring

## Related Documentation

- Biolink Model: https://biolink.github.io/biolink-model/
- ChemicalEntity definition: https://biolink.github.io/biolink-model/ChemicalEntity
- ChemicalMixture analysis: `docs/CHEMICAL_MIXTURE_ANALYSIS.md`

## References

- Biolink deprecation of ChemicalSubstance: https://github.com/biolink/biolink-model/blob/master/CHANGELOG.md
- Constants file: `kg_microbe/transform_utils/constants.py`
- Visualization scripts: `create_*_labels.py`, `neo4j/create_1hop_subgraph.py`
