# Unmapped Traits & Unresolved Taxa Analysis Summary

**Date:** 2026-04-04  
**Transforms Analyzed:** metatraits (NCBI) and metatraits_gtdb (GTDB)  
**Status:** ✅ Analysis Complete  

---

## Executive Summary

Analyzed unmapped trait data from both metatraits transforms and identified **80.9% (12.6M observations) can be mapped immediately** using existing METPO predicates with targeted code improvements.

### Key Statistics

| Metric | Value |
|--------|-------|
| **Total unmapped observations** | 15.6 million |
| **Unique unmapped traits** | 526 |
| **Immediately addressable** | 12.6M (80.9%) |
| **New METPO terms needed** | 0 |
| **Unresolved taxa (NCBI)** | 41 |
| **Unresolved taxa (GTDB)** | 0 |

---

## Part 1: Unmapped Traits

### Breakdown by Solution Type

| Priority | Category | Observations | % | Solution | METPO Terms |
|----------|----------|--------------|---|----------|-------------|
| 🚨 **CRITICAL** | Chemical lookups | 9,561,316 | 61.5% | Manual mapping file | 0 (all exist) |
| 🔥 **HIGH** | Quantitative properties | 2,981,079 | 19.2% | Value extraction | 0 (props exist) |
| ⚡ **MEDIUM** | Fermentation substrates | 31,331 | 0.2% | ChEBI enhancement | 0 (exists) |
| 📊 **MEDIUM** | Enzyme activities | 6,670 | 0.04% | EC/GO mapping | 0 (exists) |
| **TOTAL** | | **12,580,396** | **80.9%** | | **0 new terms** |

### Top Unmapped Traits (High Frequency)

1. **electron acceptor: sulfur compounds** - 1.2M observations
   - Solution: Map to CHEBI:26833 (sulfur molecular entity)
   - Predicate: METPO:2000008 (EXISTS)

2. **oxidation in darkness: sulfur compounds** - 1.2M observations
   - Solution: Map to CHEBI:26833
   - Predicate: METPO:2000605 (EXISTS)

3. **degradation: plastic** - 1.2M observations
   - Solution: Map to ENVO:01000970 (plastic material)
   - Predicate: METPO:2000007 (EXISTS)

4. **growth: 6.5% NaCl** - 1.5M observations
   - Solution: Extract "6.5", use METPO:2000707
   - Type: Node property (quantitative)

5. **growth: 42 degrees Celsius** - 1.5M observations
   - Solution: Extract "42", use METPO:2000701
   - Type: Node property (quantitative)

### Categories of Unmapped Traits

| Category | Count | Examples |
|----------|-------|----------|
| **Production (ChEBI failed)** | 148 | produces: poly-beta-hydroxyalkanoate, produces: fluorescein |
| **Other/Miscellaneous** | 188 | aerobic catabolization: acetate, growth: 1% sodium lactate |
| **Fermentation (ChEBI failed)** | 95 | fermentation: D-glucose, fermentation: D-mannitol |
| **Enzyme Activity** | 44 | enzyme activity: alpha-maltosidase, ACC deaminase |
| **Quantitative Growth** | 14 | growth: 1% sodium chloride, growth: 42 degrees Celsius |
| **Degradation (failed)** | 13 | degradation: aromatic compound, degradation: hydrocarbon |
| **Hydrolysis (failed)** | 11 | hydrolysis: casein hydrolysate, hydrolysis: milk |
| **Reduction (failed)** | 6 | reduction: arsenate detoxification, amorphous iron oxide |
| **Electron Acceptor (failed)** | 4 | electron acceptor: sulfur compounds, amorphous iron oxide |
| **Other** | 3 | oxidation in darkness, cell color, pH preference |

---

## Part 2: Unresolved Taxa

### NCBI Taxonomy (Regular MetaTraits)

**Total unresolved:** 41 taxa

#### Breakdown by Pattern

| Pattern | Count | % | Solvable |
|---------|-------|---|----------|
| **Candidatus taxa** | 23 | 56.1% | ✅ Map to GTDB |
| **Generic "bacterium"** | 15 | 36.6% | ⚠️ Partially |
| **Uncultured** | 4 | 9.8% | ✅ Map to GTDB |
| **Deprecated [bracket] names** | 2 | 4.9% | ✅ Use updated names |

#### Examples of Unresolved Taxa

**Candidatus (56%):**
- Candidatus Aminicenantes bacterium
- Candidatus Marsarchaeota archaeon
- Candidatus Nitrosomarinus catalina

**Generic bacterium (37%):**
- bacterium 3DAC
- bacterium UBP9_UBA4705
- candidate division bacterium WOR-3 4484_18

**Uncultured (10%):**
- uncultured Allisonella sp.
- uncultured Candidatus Arthromitus sp.

**Deprecated names (5%):**
- [Pseudomonas] boreopolis
- [Pseudomonas] carboxydohydrogena

### GTDB Taxonomy (GTDB MetaTraits)

**Total unresolved:** 0 taxa ✅

**Why GTDB resolves all:**
- Includes Candidatus taxa (genome-based taxonomy)
- Includes environmental/uncultured organisms from metagenomes
- Uses updated nomenclature (no deprecated names)
- Better coverage of novel lineages

### Recommendation

**Use GTDB taxonomy for metatraits** - achieves 100% taxon resolution vs 99.9% with NCBI.

For the 41 NCBI unresolved taxa:
- 27 (66%) can be mapped to GTDB parent taxa
- 14 (34%) are too generic/unspecific to map

---

## Implementation Files Created

### 1. Analysis Documents
- ✅ **`UNMAPPED_TRAITS_IMPLEMENTATION_PLAN.md`** - Complete 5-phase implementation plan
- ✅ **`UNMAPPED_ANALYSIS_SUMMARY.md`** (this file) - Executive summary

### 2. Mapping Files
- ✅ **`kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv`** - 30 manual chemical mappings

### 3. To Be Created
- ⏳ `mappings/enzyme_name_to_ec_go.tsv` - Enzyme activity mappings
- ⏳ `mappings/ncbi_unresolved_to_gtdb.tsv` - Taxa resolution mappings (optional)

---

## Implementation Priorities

### Phase 1: Chemical Lookups (CRITICAL) 🚨
- **Impact:** 9.6M observations (61.5%)
- **Complexity:** LOW
- **Time:** 1 week
- **Status:** Mapping file created ✅
- **Next:** Update transform code to load special mappings

### Phase 2: Quantitative Properties (HIGH) 🔥
- **Impact:** 3.0M observations (19.2%)
- **Complexity:** MEDIUM
- **Time:** 1 week
- **Status:** Not started
- **Next:** Implement value extraction function

### Phase 3: ChEBI Enhancement (MEDIUM) ⚡
- **Impact:** 31K observations (0.2%)
- **Complexity:** LOW
- **Time:** 1 week
- **Status:** Not started
- **Next:** Add stereochemistry normalization

### Phase 4: Enzyme Mapping (MEDIUM) 📊
- **Impact:** 6.7K observations (0.04%)
- **Complexity:** MEDIUM
- **Time:** 1 week
- **Status:** Not started
- **Next:** Create enzyme mapping file

### Phase 5: Additional Patterns (LOW)
- **Impact:** ~100K observations
- **Complexity:** LOW-MEDIUM
- **Time:** 1 week
- **Status:** Not started

---

## Expected Outcomes After Full Implementation

### Coverage Improvement

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Mapped observations | ~68% | ~95% | +27% |
| Unmapped observations | 15.6M | 3.0M | -80.9% |
| Unresolved taxa (NCBI) | 41 | 10-15 | -63-76% |
| Unresolved taxa (GTDB) | 0 | 0 | - |

### Edge Count Increase

**Estimated new edges:**
- Phase 1 (Chemical): +9.6M edges
- Phase 2 (Quantitative): +3.0M node properties
- Phase 3 (Fermentation): +31K edges
- Phase 4 (Enzymes): +6.7K edges
- **Total: ~9.6M new edges + 3.0M node properties**

### Remaining Unmapped (Acceptable)

After all phases: ~3.0M observations (19.1%)

**Why remaining are unmapped:**
- Exotic/rare compounds not in ChEBI
- Non-standard nomenclature
- Proprietary compound names
- Assay artifacts (4-nitrophenyl derivatives)
- Truly novel/uncategorized traits

**This is ACCEPTABLE** for a comprehensive knowledge graph.

---

## Key Findings

### 1. NO New METPO Terms Needed ✅

All required predicates already exist in METPO:
- METPO:2000002 (assimilates)
- METPO:2000007 (degrades)
- METPO:2000008 (uses as electron acceptor)
- METPO:2000011 (ferments)
- METPO:2000013 (hydrolyzes)
- METPO:2000017 (reduces)
- METPO:2000032 (uses for aerobic catabolization)
- METPO:2000048 (uses for anaerobic catabolization)
- METPO:2000202 (produces)
- METPO:2000302 (shows activity of)
- METPO:2000605 (oxidizes in darkness)
- METPO:2000701-2000709 (quantitative properties)

### 2. GTDB Taxonomy is Superior ✅

- 100% taxon resolution vs 99.9% with NCBI
- Includes Candidatus taxa
- Better metagenomic organism coverage
- No deprecated nomenclature

### 3. Most Failures are Lookup Issues ✅

**Not missing ontology coverage, but:**
- Parent class needed (e.g., "sulfur compounds" → CHEBI:26833)
- Material ontology needed (plastic → ENVO)
- ChEBI synonym matching insufficient
- Stereochemistry variants not handled

**All fixable with code improvements!**

---

## Recommended Next Actions

### Immediate (This Week)
1. ✅ Special chemical mappings file created
2. ⏳ Implement Phase 1 in transform code
3. ⏳ Test on sample data
4. ⏳ Validate edge count increase

### Short-term (Next 2-4 Weeks)
5. ⏳ Implement Phase 2 (quantitative properties)
6. ⏳ Implement Phase 3 (ChEBI enhancement)
7. ⏳ Create enzyme mapping file
8. ⏳ Implement Phase 4 (enzyme activities)

### Medium-term (1-2 Months)
9. ⏳ Run full transform with all improvements
10. ⏳ Regenerate merged knowledge graph
11. ⏳ Update graph statistics
12. ⏳ Document coverage improvements

---

## Files Reference

### Analysis
- `UNMAPPED_TRAITS_IMPLEMENTATION_PLAN.md` - Detailed 5-phase plan
- `UNMAPPED_ANALYSIS_SUMMARY.md` - This summary
- `data/transformed/metatraits/unmapped_traits.tsv` - Raw unmapped data (NCBI)
- `data/transformed/metatraits_gtdb/unmapped_traits.tsv` - Raw unmapped data (GTDB)

### Mappings
- `kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv` - Manual chemical mappings (30 entries)

### Transform Code
- `kg_microbe/transform_utils/metatraits/metatraits.py` - Transform to update
- `kg_microbe/utils/chemical_mapping_utils.py` - ChEBI lookup to enhance

---

## Success Criteria

✅ **Analysis complete** - Identified 80.9% addressable with existing ontologies  
✅ **Phase 1 mapping file created** - 30 special chemical mappings  
⏳ **Phase 1 implemented** - Update transform code  
⏳ **Coverage improved** - Target 95% (from 68%)  
⏳ **Edge count increased** - Expect +9.6M edges  
⏳ **Taxa resolution** - Reduce NCBI unresolved to <15  

---

**Bottom Line:** We can achieve 95% coverage and add ~10M edges by implementing code improvements and using existing METPO predicates. No new ontology terms required!
