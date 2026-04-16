# MetaTraits Round 3 Enhancement - Implementation Summary

**Date:** 2026-03-22
**Branch:** fix_metatraits

## Overview

Implemented MetaTraits Third Round Enhancement to map additional unmapped traits by adding 5 new pattern resolvers and expanding METPO predicate coverage from 30 to 42 predicates.

## Baseline (Before Round 3)

- **Unmapped traits:** 5,051,076 observations (1,985 unique trait names)
- **Mapped edges:** 1,048,641 edges
- **METPO predicates:** 30 predicates

## Expected Results (After Round 3)

- **Unmapped reduction:** 30-50% (1.5-2.5M observations mapped)
- **Unique trait reduction:** 25-40% (500-800 traits resolved)
- **Edge increase:** +350K-550K edges (+33-52%)
- **New METPO predicates:** 12 additional predicates (total: 42)

---

## Implementation Details

### Phase 8: Expanded METPO Predicates

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py:40-82`

Added 12 new predicates to `METPO_TO_BIOLINK_PREDICATE` dictionary:

**New Predicates:**
1. `METPO:2000003` - builds acid from → `biolink:produces`
2. `METPO:2000004` - builds base from → `biolink:produces`
3. `METPO:2000005` - builds gas from → `biolink:produces`
4. `METPO:2000008` - uses as electron acceptor → `biolink:capable_of`
5. `METPO:2000009` - uses as electron donor → `biolink:capable_of`
6. `METPO:2000010` - uses as energy source → `biolink:capable_of`
7. `METPO:2000014` - uses as nitrogen source → `biolink:capable_of`
8. `METPO:2000015` - uses in other way → `biolink:interacts_with`
9. `METPO:2000020` - uses as sulfur source → `biolink:capable_of`
10. `METPO:2000028` - does not build acid from → `biolink:produces`
11. `METPO:2000044` - does not reduce → `biolink:capable_of`
12. `METPO:2000046` - does not use for respiration → `biolink:capable_of`

**Also added:**
- `METPO:2000101` - has quality → `biolink:has_attribute`
- Added `biolink:has_attribute` → `RO:0000086` (has quality) to `PREDICATE_TO_RELATION`

**Total predicates:** 42 (was 30)

---

### Phase 1: Metabolic Process Resolver

**Method:** `_resolve_metabolic_trait(trait_name: str) -> Optional[dict]`
**Location:** `metatraits.py:337-421`

**Patterns matched:**
- `electron acceptor: [chemical]` → METPO:2000008
- `respiration: [chemical]` → METPO:2000008
- `reduction: [chemical]` → METPO:2000017
- `oxidation: [chemical]` → METPO:2000016
- `oxidation in darkness: [chemical]` → METPO:2000016
- `denitrification: [chemical]` → METPO:2000017
- `ammonification: [chemical]` → METPO:2000014
- `degradation: [material]` → METPO:2000007
- `hydrolysis: [material]` → METPO:2000013

**Chemical lookups:**
- Uses `ChemicalMappingLoader` to resolve chemical names to ChEBI IDs
- Supports 164,705 ChEBI entries from `unified_chemical_mappings.tsv.gz`

**Material mappings (fallback for non-ChEBI):**
- urea → CHEBI:16199
- casein → KGM:casein (custom)
- gelatin → KGM:gelatin (custom)
- esculin → CHEBI:4806
- starch → CHEBI:28017

**Target traits (43,770-49,457 observations each):**
- electron acceptor: elemental sulfur, sulfate, thiosulfate, nitrate, fumarate
- respiration: nitrogen, iron, sulfur
- reduction: nitrate, sulfite, thiosulfate
- oxidation: methanol, manganese, ammonia, hydrogen
- denitrification: nitrate, nitrite, nitrous oxide
- degradation: cellulose, lignin, plastic, chitin, xylan
- hydrolysis: urea, casein, gelatin, esculin, starch

**Expected impact:** ~2M observations mapped

---

### Phase 2: Growth Substrate Resolver

**Method:** `_resolve_growth_substrate(trait_name: str) -> Optional[dict]`
**Location:** `metatraits.py:423-468`

**Patterns matched:**
- `growth: [substrate]` → METPO:2000012 (uses for growth)
- `builds acid from: [substrate]` → METPO:2000003 (builds acid from)

**Exclusions:**
- Skips trophic modes (phototrophy, chemoheterotrophy, etc.) - handled by Phase 3

**Target traits (41,047-41,090 observations each):**
- growth: cellobiose, D-mannitol, D-mannose, D-sorbitol, L-rhamnose, D-xylose
- growth: raffinose, maltose, lactose, tartrate, glycerol, myo-inositol
- growth: L-arabinose, trehalose, sucrose, salicin, melibiose, acetate

**Expected impact:** ~1M observations mapped

---

### Phase 3: Trophic Mode Resolver

**Method:** `_resolve_trophic_mode(trait_name: str) -> Optional[dict]`
**Location:** `metatraits.py:470-547`

**Patterns matched:**

1. **Trophic modes (growth: X):**
   - phototrophy → GO:0009579 (phototrophic process)
   - chemoheterotrophy → GO:0044281 (small molecule metabolic process)
   - photoautotrophy → GO:0009541 (photoautotrophic process)
   - photoheterotrophy → GO:0009581 (photoheterotrophic process)
   - anoxygenic photoautotrophy → GO:0019685 (photosynthesis, anoxygenic)
   - anoxygenic phototrophy → GO:0019685

2. **Aerobic/anaerobic growth:**
   - aerobic growth: * → METPO:1001003 (aerobe phenotype)
   - anaerobic growth: * → METPO:1001004 (anaerobe phenotype)

**Predicate:**
- Trophic modes → METPO:2000103 (capable of)
- Aerobic/anaerobic → METPO:2000102 (has phenotype)

**Target traits (43,770 observations each):**
- growth: phototrophy, chemoheterotrophy, photoautotrophy, etc.
- aerobic growth: chemoheterotrophy, anoxygenic phototrophy
- anaerobic growth: [various contexts]

**Expected impact:** ~350K observations mapped

---

### Phase 4: Enzyme Activity Resolver

**Method:** `_resolve_enzyme_activity(trait_name: str) -> Optional[dict]`
**Location:** `metatraits.py:549-574`

**Patterns matched:**
- `enzyme activity: [name] (EC[number])` → EC:[number]
  - Example: "enzyme activity: alkaline phosphatase (EC3.1.3.1)" → EC:3.1.3.1

**Predicate:**
- METPO:2000302 (shows activity of)

**Category:**
- biolink:MolecularActivity

**Non-EC enzymes:**
- Falls through to trait_mapping (existing METPO mappings handle these)

**Target traits (41,000-43,108 observations each):**
- alkaline phosphatase (EC3.1.3.1)
- arginine dihydrolase (EC3.5.3.6)
- lysine decarboxylase (EC4.1.1.18)
- ornithine decarboxylase (EC4.1.1.17)

**Expected impact:** ~170K observations mapped (EC-numbered only)

---

### Phase 5: Phenotype Resolver

**Method:** `_resolve_phenotype_trait(trait_name: str) -> Optional[dict]`
**Location:** `metatraits.py:576-602`

**Patterns matched (direct lookup):**
- aerotolerant → METPO:1001025
- facultative anaerobe → METPO:1001026
- acidophilic → METPO:1001015 (acidophile)
- capnophilic → KGM:capnophilic (custom, no METPO ID)

**Predicate:**
- METPO:2000102 (has phenotype)

**Category:**
- biolink:PhenotypicQuality

**Target traits (56,492 observations for aerotolerant alone):**
- aerotolerant - 56,492
- facultative anaerobe - ~20,000 (estimated)
- acidophilic - ~10,000 (estimated)

**Expected impact:** ~90K observations mapped

---

### Phase 7: Integration into Trait Resolution Hierarchy

**Location:** `metatraits.py:742-820`

**New tier hierarchy:**

1. **Tier 1:** Curated microbial-trait-mappings (existing)
2. **Tier 1.5:** Chemical trait resolver (Round 2 - produces, ferments, carbon source)
3. **Tier 1.6:** Metabolic process resolver (NEW - electron acceptor, respiration, oxidation, reduction)
4. **Tier 1.7:** Growth substrate resolver (NEW - growth: X, builds acid from: X)
5. **Tier 1.8:** Trophic mode resolver (NEW - phototrophy, aerobic/anaerobic)
6. **Tier 1.9:** Enzyme activity resolver (NEW - enzyme activity with EC numbers)
7. **Tier 2.0:** Phenotype resolver (NEW - aerotolerant, facultative, acidophilic)
8. **Tier 2/3:** METPO mappings + custom_curies (existing fallback)

**Implementation:**
- Uses walrus operator (`:=`) for clean conditional assignment
- Each tier checks pattern, extracts data, converts METPO predicate to biolink
- Falls through to next tier if no match

---

## Code Quality

**Linting:** ✅ Passed `poetry run ruff check`
**Formatting:** ✅ Formatted with `poetry run black`
**Line length:** All lines ≤ 120 characters

---

## Testing Plan

### Pre-transform baseline:
```bash
wc -l /tmp/unmapped_before_round3.tsv
# 5,051,077 lines (5,051,076 unmapped + 1 header)

wc -l data/transformed/metatraits/edges.tsv
# 1,048,642 lines (1,048,641 edges + 1 header)
```

### Post-transform verification:
```bash
# Check new unmapped count
wc -l data/transformed/metatraits/unmapped_traits.tsv

# Check unique trait count
cut -f1 data/transformed/metatraits/unmapped_traits.tsv | tail -n +2 | sort -u | wc -l

# Check new edge count
wc -l data/transformed/metatraits/edges.tsv

# Validate new predicates
cut -f2 data/transformed/metatraits/edges.tsv | sort | uniq -c | sort -rn

# Check ChEBI/EC coverage
grep -c "CHEBI:" data/transformed/metatraits/edges.tsv
grep -c "^EC:" data/transformed/metatraits/edges.tsv
grep -c "GO:" data/transformed/metatraits/edges.tsv
grep -c "METPO:" data/transformed/metatraits/edges.tsv

# Quality checks
poetry run tox
```

### Success Criteria:
- ✅ Unmapped traits reduced by 30-50% (1.5-2.5M observations)
- ✅ Unique unmapped trait count reduced by 25-40% (500-800 traits)
- ✅ Edge count increases by 350K-550K (+33-52%)
- ✅ New predicates used: METPO:2000003, 2000008, 2000009, 2000014, 2000020
- ✅ Electron acceptors mapped to ChEBI (sulfate, nitrate, etc.)
- ✅ Degradation substrates mapped (cellulose, lignin, chitin, plastic)
- ✅ Enzyme activities with EC numbers mapped to EC: namespace
- ✅ Growth substrates mapped to ChEBI (carbohydrates, organic acids)
- ✅ All tests pass

---

## Files Modified

1. `kg_microbe/transform_utils/metatraits/metatraits.py`
   - Expanded METPO_TO_BIOLINK_PREDICATE dictionary (lines 40-82)
   - Added PREDICATE_TO_RELATION mapping for has_attribute (lines 85-91)
   - Added `_resolve_metabolic_trait()` method (lines 337-421)
   - Added `_resolve_growth_substrate()` method (lines 423-468)
   - Added `_resolve_trophic_mode()` method (lines 470-547)
   - Added `_resolve_enzyme_activity()` method (lines 549-574)
   - Added `_resolve_phenotype_trait()` method (lines 576-602)
   - Integrated new resolvers into `run()` method (lines 742-820)

---

## Next Steps (Round 4 - Deferred)

**Phase 6: Growth Condition Numeric Extraction**
- Temperature/pH/salinity ranges with numeric values (823K observations)
- Requires parsing "Median: X UNIT" from majority_label
- Complex attribute node creation
- **Defer to Round 4:** Focus on higher-impact categorical traits first

**Non-EC Enzyme Name Resolution:**
- Enzymes without EC numbers (DNase, coagulase, etc.) - ~20 types
- Requires manual curation or ML-based GO molecular function matching
- **Defer to Round 4:** Focus on EC-numbered enzymes first

**Protein/Complex Materials:**
- Casein, gelatin, casamino acids, casein hydrolysate
- No single ChEBI IDs (complex mixtures)
- **Defer to Round 5:** Requires custom ontology or mixture handling

---

## References

- **Plan:** `/Users/marcin/.claude/projects/-Users-marcin-Documents-VIMSS-ontology-KG-Hub-KG-Microbe-kg-microbe/963df37a-d593-48bd-9f61-2804578a0686.jsonl`
- **METPO Predicates:** `docs/METPO_PREDICATES.md`
- **Chemical Mappings:** `mappings/unified_chemical_mappings.tsv.gz` (164,705 ChEBI IDs)
- **Round 2 Summary:** `METATRAITS_ENHANCEMENT_SUMMARY.md`
- **Unmapped Traits List:** `/tmp/unmapped_traits_by_frequency.txt` (1,985 unique traits)
