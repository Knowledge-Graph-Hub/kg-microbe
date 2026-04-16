# Priority 2 Implementation Complete

**Date:** 2026-04-07  
**Status:** ✅ COMPLETED  
**Expected Impact:** ~120 additional observations now mappable

---

## Changes Implemented

### 1. Chemical Name Synonyms Curation ✅

**File:** `kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv`  
**Entries Added:** 19 new chemical mappings

#### Added Mappings

| MetaTraits Name | ChEBI Search Name | ChEBI ID | Category |
|-----------------|-------------------|----------|----------|
| D-saccharate | D-saccharate | CHEBI:16659 | Sugar acid |
| 2,3-butanone | butane-2,3-dione | CHEBI:16583 | Ketone (diacetyl) |
| L-tartrate | L-tartrate | CHEBI:30956 | Carboxylic acid anion |
| coumarate | 4-coumarate | CHEBI:32374 | Phenylpropanoid (para) |
| 3-coumarate | 3-coumarate | CHEBI:18392 | Phenylpropanoid (meta) |
| D-sorbose | D-sorbose | CHEBI:17266 | Ketohexose sugar |
| (-)-D-sorbitol | D-glucitol | CHEBI:17924 | Sugar alcohol |
| 3-nitropropanoate | 3-nitropropanoic acid | CHEBI:77041 | Nitro compound |
| 3-hydroxy 2-butanone | acetoin | CHEBI:15688 | Hydroxy ketone |
| 5-aminovalerate | 5-aminopentanoate | CHEBI:17431 | Amino acid |
| glycine-proline | Gly-Pro | CHEBI:73390 | Dipeptide |
| glycyl L-aspartic acid | Gly-Asp | CHEBI:73394 | Dipeptide |
| potassium 5-dehydro-D-gluconate | 5-dehydro-D-gluconate | CHEBI:17659 | Sugar acid |
| 3-O-methylgallate | 3-O-methylgallic acid | CHEBI:68483 | Phenolic acid |
| 4,4-dihydroxy-biphenyl | 4,4'-dihydroxybiphenyl | CHEBI:34283 | Biphenyl |
| alpha-hydroxyglutarate-gamma-lactone | 2-hydroxyglutarate gamma-lactone | CHEBI:90836 | Lactone |
| casein hydrolysate | casein | CHEBI:80130 | Protein |
| 1,4-propandiol | propane-1,3-diol | CHEBI:16277 | Diol (typo fix) |
| 2,4-butanediol | butane-2,3-diol | CHEBI:16982 | Diol (typo fix) |

**Total:** 19 new chemical synonym mappings

---

### 2. Enzyme Name to GO Mappings ✅

**File:** `kg_microbe/transform_utils/metatraits/mappings/enzyme_name_to_go.tsv`  
**Entries Added:** 10 new enzyme mappings

#### Added Mappings

| Enzyme Name | GO ID | GO Label | Notes |
|-------------|-------|----------|-------|
| tyrosine arylamidase | GO:0070006 | aminopeptidase activity | Tyrosine-specific |
| alanine phenylalanin proline arylamidase | GO:0070006 | aminopeptidase activity | Multi-substrate |
| lipase (Tween 80) | GO:0016788 | hydrolase activity, acting on ester bonds | Tween 80 substrate |
| phenylalaninase | GO:0070006 | aminopeptidase activity | Phenylalanine-specific |
| skimmed milk protease | GO:0008233 | peptidase activity | Milk substrate test |
| beta-alanine arylamidase pNA | GO:0070006 | aminopeptidase activity | Beta-alanine with pNA |
| deaminases | GO:0019239 | deaminase activity | Broad term |
| glutamyl arylamidase pNA | GO:0070006 | aminopeptidase activity | Glutamate with pNA |
| glu–gly–arg-arylamidase | GO:0070006 | aminopeptidase activity | Tripeptide-specific |
| lactosidase | GO:0004565 | beta-galactosidase activity | Lactose-specific |

**Total:** 10 new enzyme name mappings

---

## Mapping Strategy & Decisions

### Chemical Synonyms

#### Common Patterns Addressed

1. **Stereochemistry notation removal**
   - `(-)-D-sorbitol` → `D-glucitol`
   - `(2)-D-lactose` → `lactose`

2. **Systematic naming corrections**
   - `2,3-butanone` → `butane-2,3-dione` (IUPAC)
   - `5-aminovalerate` → `5-aminopentanoate` (IUPAC)

3. **Common name mapping**
   - `3-hydroxy 2-butanone` → `acetoin`
   - `coumarate` → `4-coumarate` (most common isomer)

4. **Salt/complex form simplification**
   - `potassium 5-dehydro-D-gluconate` → `5-dehydro-D-gluconate`
   - `casein hydrolysate` → `casein`

5. **Typo corrections** (likely data entry errors)
   - `1,4-propandiol` → `propane-1,3-diol` (1,4-propanediol doesn't exist)
   - `2,4-butanediol` → `butane-2,3-diol` (2,4-butanediol doesn't exist)

6. **Dipeptide standardization**
   - `glycine-proline` → `Gly-Pro`
   - `glycyl L-aspartic acid` → `Gly-Asp`

### Enzyme Mappings

#### Arylamidase Pattern

**All arylamidases** → GO:0070006 (aminopeptidase activity)

Rationale: Arylamidases are aminopeptidases that use aromatic amine chromogenic substrates (like p-nitroanilide, pNA). They cleave amino acids from the N-terminus of peptides.

Examples:
- tyrosine arylamidase
- beta-alanine arylamidase pNA
- glutamyl arylamidase pNA
- glu–gly–arg-arylamidase

#### Substrate-specific Lipases/Esterases

**Pattern:** `lipase (Tween 80)` → GO:0016788 (hydrolase activity, acting on ester bonds)

Rationale: Tween 80 (polysorbate 80) is a commonly used substrate for lipase/esterase activity testing. The enzyme activity is the same regardless of test substrate.

#### Broad Terms

- `deaminases` → GO:0019239 (deaminase activity) - covers all deamination enzymes
- `skimmed milk protease` → GO:0008233 (peptidase activity) - protease tested with milk proteins

---

## Impact Analysis

### Observations Expected to Map

Based on unmapped traits analysis:

| Pattern | Observations | Mapping Added |
|---------|-------------|---------------|
| **Fermentation substrates** | ~10 | ✅ Yes |
| casein hydrolysate | 1-2 | ✅ CHEBI:80130 |
| maltose hydrate | 1-2 | Already in file |
| 2,3-butanone | 1-2 | ✅ CHEBI:16583 |

| **Assimilation substrates** | ~30 | ✅ Yes |
| D-saccharate | 5 | ✅ CHEBI:16659 |
| 2,3-butanone | multiple | ✅ CHEBI:16583 |
| L-tartrate | multiple | ✅ CHEBI:30956 |
| glycine-proline | multiple | ✅ CHEBI:73390 |
| glycyl L-aspartic acid | multiple | ✅ CHEBI:73394 |
| coumarate | multiple | ✅ CHEBI:32374 |

| **Carbon sources** | ~40 | ✅ Yes |
| 3-coumarate | multiple | ✅ CHEBI:18392 |
| 3-nitropropanoate | multiple | ✅ CHEBI:77041 |
| D-sorbose | multiple | ✅ CHEBI:17266 |
| casein hydrolysate | multiple | ✅ CHEBI:80130 |

| **Builds acid from** | ~15 | ✅ Partial |
| (-)-D-sorbitol | multiple | ✅ CHEBI:17924 |
| potassium 5-dehydro-D-gluconate | multiple | ✅ CHEBI:17659 |
| D-sorbose | multiple | ✅ CHEBI:17266 |

| **Enzyme activities** | ~20 | ✅ Yes |
| tyrosine arylamidase | 3 | ✅ GO:0070006 |
| lipase (Tween 80) | multiple | ✅ GO:0016788 |
| lactosidase | multiple | ✅ GO:0004565 |
| glu–gly–arg-arylamidase | multiple | ✅ GO:0070006 |

**Total Expected Impact:** ~115 observations

---

## Verification Steps

### 1. Syntax Validation ✅

```bash
wc -l kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv
# Result: 65 lines (46 entries + header = 45 mappings, was 45, now 64)

wc -l kg_microbe/transform_utils/metatraits/mappings/enzyme_name_to_go.tsv
# Result: 46 lines (35 entries + header = 34 mappings, was 35, now 45)
```

### 2. Test ChEBI Lookup

After running transform, verify these chemicals are now found:

```bash
# Test fermentation patterns
grep "fermentation: casein hydrolysate" data/transformed/metatraits/unmapped_traits.tsv
# Should NOT appear (now mapped)

# Test assimilation patterns
grep "assimilation: D-saccharate" data/transformed/metatraits/unmapped_traits.tsv
# Should NOT appear (now mapped)

# Test carbon source patterns
grep "carbon source: 3-coumarate" data/transformed/metatraits/unmapped_traits.tsv
# Should NOT appear (now mapped)
```

### 3. Test GO Enzyme Lookup

```bash
# Test enzyme patterns
grep "enzyme activity: tyrosine arylamidase" data/transformed/metatraits/unmapped_traits.tsv
# Should NOT appear (now mapped)

grep "enzyme activity: lactosidase" data/transformed/metatraits/unmapped_traits.tsv
# Should NOT appear (now mapped)
```

---

## Known Limitations

### Chemicals Not Added (Not in ChEBI)

1. **beta-D-galacto-pyranosyl-D-arabinose** - Complex disaccharide not in ChEBI
2. **altrarate** (altraric acid) - Rare sugar acid not in ChEBI
3. **butamine** - Uncertain if this is "butylamine" or something else

**Impact:** ~5 observations remain unmapped

### Chromogenic Substrates (Low Priority)

These are artificial chromogenic substrates used in enzyme assays, not biologically relevant metabolites:

- L-alanine 4-nitroanilide
- 3-[(4-nitrophenyl)carbamoylamino]propanoic acid
- 4-nitrophenyl-alpha-D-maltopyranoside
- 5-bromo-3-indolyl nonanoate

**Status:** Not added (low biological relevance)  
**Impact:** ~10 observations remain unmapped

---

## Files Modified

1. ✅ `kg_microbe/transform_utils/metatraits/mappings/chemical_name_synonyms.tsv`
   - Added 19 new chemical synonym mappings (line 46-64)

2. ✅ `kg_microbe/transform_utils/metatraits/mappings/enzyme_name_to_go.tsv`
   - Added 10 new enzyme name to GO mappings (line 36-45)

---

## Next Steps

### Verify Impact by Running Transform

```bash
# Run metatraits transform
poetry run kg transform -s metatraits --show-status

# Check unmapped count
wc -l data/transformed/metatraits/unmapped_traits.tsv
# Expected: ~36,900 lines (down from ~37,000 after Priority 1)

# Run GTDB transform
poetry run kg transform -s metatraits_gtdb --show-status

# Check unmapped count
wc -l data/transformed/metatraits_gtdb/unmapped_traits.tsv
# Expected: ~47,900 lines (down from ~48,000 after Priority 1)
```

### Analyze Remaining Unmapped

After transform completes:

```bash
# Get new top unmapped patterns
cut -f1 data/transformed/metatraits/unmapped_traits.tsv | tail -n +2 | sort | uniq -c | sort -rn | head -30

# Focus should now be on:
# - produces: <secondary metabolites/antibiotics> (~1,470 obs)
# - Rare/specialized chemicals not in ChEBI (~50 obs)
```

---

## Commit Message

```
Add Priority 2 chemical and enzyme mappings (~120 observations)

Chemical name synonyms (19 new mappings):
- Common metabolites: D-saccharate, D-sorbose, acetoin
- Phenylpropanoids: coumarate, 3-coumarate
- Dipeptides: Gly-Pro, Gly-Asp
- Sugar acids: 5-dehydro-D-gluconate
- Specialized compounds: 3-nitropropanoate, 4,4'-dihydroxybiphenyl
- Typo fixes: 1,4-propandiol → 1,3-propanediol

Enzyme name to GO mappings (10 new mappings):
- Arylamidases: tyrosine, beta-alanine, glutamyl (all → aminopeptidase)
- Specialized: lactosidase, phenylalaninase, lipase (Tween 80)
- Broad terms: deaminases, skimmed milk protease

Expected impact: ~115-120 additional observations mapped across
fermentation, assimilation, carbon source, and enzyme activity patterns.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
