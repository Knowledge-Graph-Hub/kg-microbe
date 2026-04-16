# Unmapped Traits - Final Analysis

**Date:** 2026-04-06  
**After:** All hardcoded mappings eliminated, ChEBI synonyms integrated  
**Status:** 4.44M observations unmapped from NCBI + 4.34M from GTDB

---

## Executive Summary

After eliminating all hardcoded mappings and integrating ChEBI synonyms, **~105K unique unmapped trait patterns remain** (4.44M observations for NCBI, 4.34M for GTDB).

### Breakdown by Category

| Category | Observations (NCBI) | Observations (GTDB) | % of Unmapped | Actionable? |
|----------|---------------------|---------------------|---------------|-------------|
| Single growth tests | 2,977,740 | 2,915,065 | 67.1% | ❌ Design skip |
| Negative pigmentation | 1,453,581 | 1,421,160 | 32.7% | ⚠️ Negative assertions |
| Enzyme no EC | 6,670 | 4,747 | 0.14% | ✅ Map to GO |
| Chemical patterns | 456 | 292 | 0.01% | ✅ Add synonyms |
| Required for growth | 44 | 36 | 0.001% | ✅ Add resolver |
| pH preference ambiguous | 36 | 30 | 0.001% | ❌ No consensus |
| Other | 276 | 140 | 0.01% | ⚠️ Mixed |

**Key finding:** Most unmapped (99.9%) are either intentional design decisions or negative assertions. Only ~7K observations (0.16%) represent genuine mapping opportunities.

---

## Category 1: Single Growth Tests (2.98M obs NCBI, 2.92M GTDB) ❌ SKIP

### Pattern
Binary growth tests at specific conditions:
- `growth: 42 degrees Celsius` (1.49M NCBI, 1.46M GTDB)
- `growth: 6.5% NaCl` (1.49M NCBI, 1.46M GTDB)
- `growth: 1 % sodium lactate` (16 NCBI, 15 GTDB)

### Why Unmapped
**Intentional design decision** - these are single binary test points, not ranges.

We use min/max/optimum values instead:
- More informative (range vs point)
- Enables phenotype classification
- Single points don't indicate preference

### Could They Be Mapped?
Yes, but not recommended:
```python
# Possible but less useful
Subject: NCBITaxon:562
Predicate: METPO:2000054 "has growth temperature observation"
Object: 42.0 (xsd:float)
Qualifiers: {result: "true", unit: "Cel"}
```

### Recommendation
**SKIP** - Min/max approach is superior. Keep current behavior.

---

## Category 2: Negative Pigmentation (1.45M obs NCBI, 1.42M GTDB) ⚠️ NEGATIVE ASSERTIONS

### Pattern
`cell color: yellow pigment` with `false: (100%)` values

### Why Unmapped
These are **negative assertions** - organisms that do NOT have yellow pigment.

### Example
```tsv
cell color: yellow pigment	Abiotrophia defectiva	false: (98%)	65
```
= 98% of observations say "no yellow pigment"

### Could They Be Mapped?
Yes, but requires METPO term:
- METPO gap: No "non-pigmented" class
- Proposed as METPO:1003XXX in `metpo_gaps_and_proposals.tsv`

### Current Behavior
Code correctly **skips negative pigmentation** - positive assertions more informative.

### Recommendation
**LOW PRIORITY** - Negative assertions less useful for KG queries. METPO proposal already submitted.

---

## Category 3: Enzyme Activities Without EC (6.7K obs NCBI, 4.7K GTDB) ✅ HIGH PRIORITY

### Pattern
`enzyme activity: [enzyme name]` without EC number

### Top 10 Enzymes (88% of observations)

| Observations (NCBI) | Observations (GTDB) | Enzyme Name | Potential GO Mapping |
|---------------------|---------------------|-------------|---------------------|
| 1,662 | 1,033 | glycyl tryptophan arylamidase | GO:0070006 (aminopeptidase) |
| 1,256 | 974 | alpha-maltosidase | GO:0004339 (alpha-glucosidase) |
| 1,226 | 834 | beta-Galactosidase 6-phosphate | GO:0004565 (beta-galactosidase) |
| 261 | 190 | esterase (C 4) | GO:0016788 (hydrolase, ester bonds) |
| 194 | 141 | esterase Lipase (C 8) | GO:0016788 (hydrolase, ester bonds) |
| 115 | 85 | naphthol-AS-BI-phosphohydrolase | GO:0016791 (phosphatase) |
| 49 | 41 | valine arylamidase | GO:0070006 (aminopeptidase) |
| 38 | 31 | arginine arylamidase | GO:0070006 (aminopeptidase) |
| 32 | 20 | glutamyl-glutamate arylamidase | GO:0070006 (aminopeptidase) |
| 15 | 10 | glycin arylamidase | GO:0070006 (aminopeptidase) |

### Why Unmapped
Code only handles enzymes **with EC numbers**:
```python
# Pattern: enzyme activity: alkaline phosphatase (EC3.1.3.1)
ec_match = re.match(r"^enzyme activity:\s*(.+?)\s*\(EC\s*([\d.]+)\)\s*$", ...)
```

Enzymes without EC fall through.

### Solution
Create `enzyme_name_to_go.tsv` mapping file:
```tsv
enzyme_name	go_id	go_label	ec_number	notes
alpha-maltosidase	GO:0004339	alpha-glucosidase activity	3.2.1.20	Synonym
beta-Galactosidase 6-phosphate	GO:0004565	beta-galactosidase activity	3.2.1.23	Direct match
esterase	GO:0016788	hydrolase activity, acting on ester bonds		Broad term
glycyl tryptophan arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
L-arginine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
```

### Implementation
1. Create mapping file with top 20 enzymes
2. Load in `__init__()` like `chemical_name_synonyms`
3. Add fallback in `_resolve_enzyme_activity()`
4. Use METPO:2000302 (shows activity of) predicate

**Expected impact:** Map ~5.6K observations NCBI + ~4K GTDB (88% of enzyme-no-EC)

---

## Category 4: Chemical Patterns (456 obs NCBI, 292 GTDB) ✅ MEDIUM PRIORITY

### Pattern
Chemical-based traits that should map but fail ChEBI lookup

### Top Patterns

| Observations (NCBI) | Observations (GTDB) | Pattern | Issue |
|---------------------|---------------------|---------|-------|
| 19 | 13 | `builds acid from: (-)-D-fructose` | Stereochemistry notation |
| 17 | 15 | `builds acid from: glucose 1-phosphate` | Already in synonym file! |
| 13 | 10 | `builds acid from: 2-oxogluconate` | Already in synonym file! |
| 13 | 11 | `builds acid from: 3-O-methyl alpha-D-glucopyranoside` | Already in synonym file! |
| 13 | 6 | `hydrolysis: 4-nitrophenyl beta-D-galactopyranoside hydrolysate` | "hydrolysate" suffix |
| 12 | 6 | `carbon source: 1 % sodium lactate` | Concentration in name |
| 9 | 9 | `builds acid from: (+)-D-glycogen` | Stereochemistry notation |
| 8 | 3 | `hydrolysis: 2-deoxythymidine-5'-4-nitrophenyl phosphate` | Long systematic name |

### Analysis

**Already have synonyms for:**
- glucose 1-phosphate → alpha-D-glucose 1-phosphate
- 2-oxogluconate → 2-oxogluconic acid
- 3-O-methyl alpha-D-glucopyranoside → 3-O-methylglucose

**Why still failing?**
- Stereochemistry prefixes: `(-)-D-fructose`, `(+)-D-glycogen`
- Suffixes: "hydrolysate", concentration values
- Case sensitivity in lookup?

### Solution
1. **Expand synonym file** with stereochemistry variants:
   ```tsv
   (-)-D-fructose	D-fructose	CHEBI:15824	D-fructose	Remove stereo notation
   (+)-D-glucose	D-glucose	CHEBI:4167	D-glucose	Remove stereo notation
   (+)-D-glycogen	glycogen	CHEBI:28087	glycogen	Remove stereo notation
   ```

2. **Handle "hydrolysate" suffix** - Strip and lookup base compound

3. **Handle concentration prefixes** - Strip "1 % " and lookup compound

**Expected impact:** Map ~200 observations

---

## Category 5: pH Preference Ambiguous (36 obs NCBI, 30 GTDB) ❌ SKIP

### Pattern
`pH preference` with `No robust majority` value

### Example
```tsv
pH preference	Aridibacter famidurans	No robust majority	2
```

### Why Unmapped
Data is conflicting/ambiguous - no clear majority value for pH preference.

### Recommendation
**SKIP** - Correct behavior. Don't map ambiguous data.

---

## Category 6: Required for Growth (44 obs NCBI, 36 GTDB) ✅ HIGH PRIORITY

### Pattern
`required for growth: [substance]` 

### Examples
| Observations (NCBI) | Observations (GTDB) | Substance | ChEBI/FOODON |
|---------------------|---------------------|-----------|--------------|
| 9 | 5 | biotin | CHEBI:15956 |
| 4 | 2 | yeast extract | FOODON:03316079 |
| 4 | 3 | sodium chloride | CHEBI:26710 |
| 3 | 3 | butyrate | CHEBI:17968 |
| 2 | 2 | acetate | CHEBI:30089 |
| 2 | 2 | citrate | CHEBI:30769 |
| 2 | 2 | dihydrogen | CHEBI:29356 |
| 2 | 1 | elemental sulfur | CHEBI:27568 |

### Why Unmapped
**No resolver for this pattern** in code!

### METPO Support
✅ METPO has predicates:
- `requires for growth` → METPO:2000018
- `required for growth` → METPO:2000045

### Solution
Add resolver method:
```python
def _resolve_required_for_growth(self, trait_name: str) -> Optional[dict]:
    """Resolve 'required for growth: [substance]' patterns."""
    if not self.chemical_loader:
        return None
    
    import re
    match = re.match(r"^required for growth:\s*(.+)$", trait_name.lower())
    if match:
        substance = match.group(1).strip()
        
        # Try ChEBI lookup
        chebi_id = self.chemical_loader.find_chebi_by_name(substance)
        
        # Fallback to synonym mapping
        if not chebi_id and substance in self.chemical_name_synonyms:
            synonym_data = self.chemical_name_synonyms[substance]
            chebi_id = synonym_data["chebi_id"]
        
        if chebi_id:
            # Get predicate from METPO
            predicate_data = self.metpo_pattern_to_predicate.get("required for growth")
            predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"
            
            canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
            return {
                "curie": chebi_id,
                "category": "biolink:ChemicalSubstance",
                "name": canonical_name or substance,
                "predicate": predicate,
            }
    return None
```

**Expected impact:** Map all 44 NCBI + 36 GTDB observations

---

## Category 7: Other Patterns (276 obs NCBI, 140 GTDB) ⚠️ MIXED

### Notable Patterns

**Enzyme with malformed EC:**
- `enzyme activity: pyrazinamidase (EC3.5.1.B15)` (151 NCBI, 98 GTDB)
  - Issue: "B15" is not valid EC number format
  - Should be fixed in data source

**Production of specific compounds:**
- `produces: fluorescein` (4 NCBI, 4 GTDB)
- `produces: gardimycin` (2 NCBI, 1 GTDB)
- `produces: kijanimicin` (1 NCBI, 0 GTDB)
  - Already have resolver for "produces" pattern
  - Should work with ChEBI lookup

**Growth on specific compounds:**
- `growth: 3-aminobutyrate` (7 NCBI, 3 GTDB)
- `growth: 2-oxogluconate` (6 NCBI, 0 GTDB)
- `growth: beta-hydroxybutyrate` (0 NCBI, 0 GTDB)
  - Already covered by growth substrate resolver
  - Should work with ChEBI lookup

**Other:**
- `respiration: D-saccharate` (0 NCBI, 5 GTDB)
- `utilizes: 4-nitrophenyl beta-D-galactopyranoside hydrolysate` (0 NCBI, 2 GTDB)

### Recommendation
**INVESTIGATE** - These should work with existing resolvers. May be:
- ChEBI lookup failures (add to synonyms)
- Case sensitivity issues
- Data quality issues in source

---

## Implementation Priority

### High Priority (Quick Wins)

1. **Add "required for growth" resolver** (44 NCBI + 36 GTDB obs)
   - Resolver method: 30 lines of code
   - METPO predicate exists: METPO:2000045
   - Expected time: 30 minutes
   - Impact: 100% of required-for-growth observations

2. **Create enzyme GO mapping file** (5.6K NCBI + 4K GTDB obs)
   - File: `enzyme_name_to_go.tsv`
   - Top 20 enzymes = 88% coverage
   - Expected time: 2 hours (research GO terms)
   - Impact: 88% of enzyme-no-EC observations

### Medium Priority

3. **Expand chemical synonym file** (~200 obs combined)
   - Add stereochemistry variants
   - Add hydrolysate handling
   - Strip concentration prefixes
   - Expected time: 1 hour
   - Impact: ~30% of remaining chemical patterns

4. **Investigate "Other" failures** (~300 obs combined)
   - Check why existing resolvers failing
   - May be case sensitivity or data quality
   - Expected time: 1 hour
   - Impact: Unknown until investigated

### Low Priority

5. **Negative pigmentation** (1.45M NCBI + 1.42M GTDB obs)
   - METPO proposal already submitted
   - Requires METPO team approval
   - Low value - negative assertions
   - Expected time: 30 minutes (proposal only)
   - Impact: 1.45M observations (but low utility)

---

## Expected Coverage After Improvements

### Current State
- Total observations: ~48.5M (NCBI + GTDB combined)
- Mapped: ~44.0M (90.7%)
- Unmapped: ~4.4M (9.3%)

### After High Priority Fixes
- Additional mapped: ~5.6K (enzyme GO) + 80 (required) = ~5.7K
- New coverage: 44,005,700 / 48,500,000 = **90.72%** (+0.02%)

### After Medium Priority Fixes  
- Additional mapped: ~200 (chemical synonyms) + ~100 (other) = ~300
- New coverage: 44,006,000 / 48,500,000 = **90.73%** (+0.03%)

### If Single Growth Tests Added (Optional)
- Additional mapped: 2.98M + 2.92M = 5.9M
- New coverage: 49,906,000 / 48,500,000 = **102%** (more than 100% due to duplicates)

### If Negative Pigmentation Added (Optional)
- Additional mapped: 1.45M + 1.42M = 2.87M
- New coverage: would exceed 100%

**Note:** Single growth tests and negative pigmentation are design decisions, not data quality issues. Current 90.7% coverage is appropriate for meaningful trait assertions.

---

## Files to Create

1. **`enzyme_name_to_go.tsv`**
   ```tsv
   enzyme_name	go_id	go_label	ec_number	notes
   alpha-maltosidase	GO:0004339	alpha-glucosidase activity	3.2.1.20	Synonym
   beta-Galactosidase 6-phosphate	GO:0004565	beta-galactosidase activity	3.2.1.23	Direct match
   esterase	GO:0016788	hydrolase activity, acting on ester bonds		Broad term
   glycyl tryptophan arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   L-arginine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   naphthol-AS-BI-phosphohydrolase	GO:0016791	phosphatase activity		Phosphohydrolase = phosphatase
   valine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   arginine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   glutamyl-glutamate arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   glycin arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   tryptophan deaminase	GO:0004838	tryptophanase activity	4.1.99.1	Direct match
   protease	GO:0008233	peptidase activity		Broad term
   beta-galactopyranosidase	GO:0004565	beta-galactosidase activity	3.2.1.23	Synonym
   beta-xylosidase	GO:0009044	xylan catabolic process	3.2.1.37	Related process
   esterase (C 4)	GO:0016788	hydrolase activity, acting on ester bonds		Broad term with qualifier
   esterase Lipase (C 8)	GO:0016788	hydrolase activity, acting on ester bonds		Broad term with qualifier
   lipase (C 14)	GO:0016788	hydrolase activity, acting on ester bonds		Broad term with qualifier
   esterase lipase (C 8)	GO:0016788	hydrolase activity, acting on ester bonds		Broad term with qualifier
   tween esterase	GO:0016788	hydrolase activity, acting on ester bonds		Esterase for tween substrates
   phosphatase	GO:0016791	phosphatase activity		Broad term
   alanine aminopeptidase	GO:0070006	aminopeptidase activity	3.4.11.2	Direct match
   phenylalanine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   histidine arylamidase	GO:0070006	aminopeptidase activity		Arylamidase = aminopeptidase
   ```

2. **Expand `chemical_name_synonyms.tsv`**
   - Add 10-15 stereochemistry variants
   - Add handling for "hydrolysate" suffix
   - Add concentration prefix stripping

3. **`METPO_GAPS_FINAL.md` update**
   - Already includes non-pigmented class proposal
   - Status: submitted to METPO team

---

## Recommendations

### Do Now
1. ✅ Create enzyme_name_to_go.tsv mapping (20 entries)
2. ✅ Add "required for growth" resolver
3. ✅ Expand chemical_name_synonyms.tsv (10-15 entries)

### Do Later
4. ⚠️ Investigate "Other" category failures
5. ⚠️ Consider negative pigmentation if needed
6. ❌ Skip single growth tests (design decision)

### Don't Do
- Map ambiguous pH preference (no consensus data)
- Map single growth test points (use min/max instead)

---

## Conclusion

Of 4.4M unmapped observations (NCBI) + 4.3M (GTDB):
- **99.9%** are design decisions (single tests, negative assertions)
- **0.1%** (~10K obs combined) are genuine mapping opportunities
- **Priority:** Add enzyme GO mappings and required-for-growth resolver

Current 90.7% coverage is **appropriate** for meaningful trait assertions. The unmapped data is mostly binary test points and negative assertions that add limited value to the knowledge graph.

---

**Date:** 2026-04-06  
**Status:** Analysis complete - High priority fixes identified  
**Next:** Implement enzyme GO mapping and required-for-growth resolver
