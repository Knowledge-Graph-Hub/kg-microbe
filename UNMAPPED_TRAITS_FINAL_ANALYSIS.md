# Unmapped Traits - Final Analysis

**Date:** 2026-04-06  
**After:** All hardcoded mappings eliminated, ChEBI synonyms integrated  
**Status:** 4.44M observations unmapped from NCBI + 4.76M from GTDB

---

## Executive Summary

After eliminating all hardcoded mappings and integrating ChEBI synonyms, **105,259 unique unmapped trait patterns remain** (4.44M observations for NCBI, 4.76M for GTDB).

### Breakdown by Category

| Category | Observations (NCBI) | % of Unmapped | Actionable? |
|----------|---------------------|---------------|-------------|
| Single growth tests | 2,977,745 | 67.1% | ❌ Design skip |
| Negative pigmentation | 1,453,581 | 32.8% | ⚠️ Negative assertions |
| Enzyme no EC | 6,317 | 0.14% | ✅ Map to GO |
| Chemical patterns | 604 | 0.01% | ✅ Add synonyms |
| pH preference ambiguous | 36 | 0.001% | ❌ No consensus |
| Required for growth | 44 | 0.001% | ✅ Add resolver |
| Other | 476 | 0.01% | ⚠️ Mixed |

**Key finding:** Most unmapped (99.9%) are either intentional design decisions or negative assertions. Only ~7K observations (0.16%) represent genuine mapping opportunities.

---

## Category 1: Single Growth Tests (2.98M obs) ❌ SKIP

### Pattern
Binary growth tests at specific conditions:
- `growth: 42 degrees Celsius` (1.49M obs)
- `growth: 6.5% NaCl` (1.49M obs)
- `growth: 1 % sodium lactate` (16 obs)

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

## Category 2: Negative Pigmentation (1.45M obs) ⚠️ NEGATIVE ASSERTIONS

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
- Could add to METPO proposal

### Current Behavior
Code correctly **skips negative pigmentation** - positive assertions more informative.

### Recommendation
**LOW PRIORITY** - Negative assertions less useful for KG queries. If needed, propose `METPO:1003XXX` "non-pigmented" class.

---

## Category 3: Enzyme Activities Without EC (6.3K obs) ✅ HIGH PRIORITY

### Pattern
`enzyme activity: [enzyme name]` without EC number

### Top 10 Enzymes (88% of observations)

| Observations | Enzyme Name | Potential GO Mapping |
|--------------|-------------|---------------------|
| 1,662 | glycyl tryptophan arylamidase | GO:0070006? (aminopeptidase) |
| 1,256 | alpha-maltosidase | GO:0004339 (alpha-glucosidase) |
| 1,226 | beta-Galactosidase 6-phosphate | GO:0004565 (beta-galactosidase) |
| 781 | L-arginine arylamidase | GO:0070006 (aminopeptidase) |
| 289 | esterase | GO:0016788 (hydrolase, ester bonds) |
| 115 | naphthol-AS-BI-phosphohydrolase | GO:0016791 (phosphatase) |
| 64 | tryptophan deaminase | GO:0004838 (tryptophanase) |
| 62 | beta-galactopyranosidase | GO:0004565 (beta-galactosidase) |
| 56 | protease | GO:0008233 (peptidase) |
| 53 | beta-xylosidase | GO:0009044 (xylan catabolic process) |

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
enzyme_name	go_id	go_label	notes
alpha-maltosidase	GO:0004339	alpha-glucosidase activity	Synonym for glucosidase
beta-Galactosidase 6-phosphate	GO:0004565	beta-galactosidase activity	Direct match
esterase	GO:0016788	hydrolase activity, acting on ester bonds	Broad term
glycyl tryptophan arylamidase	GO:0070006	aminopeptidase activity	Arylamidase = aminopeptidase
L-arginine arylamidase	GO:0070006	aminopeptidase activity	Arylamidase = aminopeptidase
```

### Implementation
1. Create mapping file with top 20 enzymes
2. Load in `__init__()` like `chemical_name_synonyms`
3. Add fallback in `_resolve_enzyme_activity()`
4. Use METPO:2000302 (shows activity of) predicate

**Expected impact:** Map ~5.6K observations (88% of enzyme-no-EC)

---

## Category 4: Chemical Patterns (604 obs) ✅ MEDIUM PRIORITY

### Pattern
Chemical-based traits that should map but fail ChEBI lookup

### Top Patterns

| Observations | Pattern | Issue |
|--------------|---------|-------|
| 127 | `builds acid from: glucose 1-phosphate` | Already in synonym file! |
| 19 | `builds acid from: (-)-D-fructose` | Stereochemistry notation |
| 14 | `assimilation: 4-nitrophenyl beta-D-galactopyranoside hydrolysate` | "hydrolysate" suffix |
| 13 | `builds acid from: 2-oxogluconate` | Already in synonym file! |
| 13 | `builds acid from: 3-O-methyl alpha-D-glucopyranoside` | Already in synonym file! |
| 12 | `carbon source: 1 % sodium lactate` | Concentration in name |
| 9 | `builds acid from: (+)-D-glycogen` | Stereochemistry notation |
| 8 | `hydrolysis: 2-deoxythymidine-5'-4-nitrophenyl phosphate` | Long systematic name |

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

## Category 5: pH Preference Ambiguous (36 obs) ❌ SKIP

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

## Category 6: Required for Growth (44 obs) ✅ HIGH PRIORITY

### Pattern
`required for growth: [substance]` 

### Examples
| Observations | Substance | ChEBI/FOODON |
|--------------|-----------|--------------|
| 9 | biotin | CHEBI:15956 |
| 4 | yeast extract | FOODON:03316079 |
| 4 | sodium chloride | CHEBI:26710 |
| 3 | butyrate | CHEBI:17968 |
| 2 | acetate | CHEBI:30089 |
| 2 | citrate | CHEBI:30769 |
| 2 | dihydrogen | CHEBI:29356 |
| 2 | elemental sulfur | CHEBI:27568 |

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

**Expected impact:** Map all 44 observations

---

## Category 7: Other Patterns (476 obs) ⚠️ MIXED

### Notable Patterns

**Enzyme with malformed EC:**
- `enzyme activity: pyrazinamidase (EC3.5.1.B15)` (353 obs)
  - Issue: "B15" is not valid EC number format
  - Should be fixed in data source

**Growth on specific compounds:**
- `growth: 3-aminobutyrate` (7 obs)
- `growth: 2-oxogluconate` (6 obs)
- `growth: beta-hydroxybutyrate` (3 obs)
  - Already covered by growth substrate resolver
  - Should work with ChEBI lookup

**Nitrogen sources:**
- `nitrogen source: 2-aminobutyrate` (4 obs)
- `nitrogen source: dl-alanine` (3 obs)
  - Already have resolver for this pattern

### Recommendation
**INVESTIGATE** - These should work with existing resolvers. May be:
- ChEBI lookup failures (add to synonyms)
- Case sensitivity issues
- Data quality issues in source

---

## Implementation Priority

### High Priority (Quick Wins)

1. **Add "required for growth" resolver** (44 obs)
   - Resolver method: 30 lines of code
   - METPO predicate exists: METPO:2000045
   - Expected time: 30 minutes
   - Impact: 100% of required-for-growth observations

2. **Create enzyme GO mapping file** (5.6K obs)
   - File: `enzyme_name_to_go.tsv`
   - Top 20 enzymes = 88% coverage
   - Expected time: 2 hours (research GO terms)
   - Impact: 88% of enzyme-no-EC observations

### Medium Priority

3. **Expand chemical synonym file** (200 obs)
   - Add stereochemistry variants
   - Add hydrolysate handling
   - Strip concentration prefixes
   - Expected time: 1 hour
   - Impact: ~30% of remaining chemical patterns

4. **Investigate "Other" failures** (476 obs)
   - Check why existing resolvers failing
   - May be case sensitivity or data quality
   - Expected time: 1 hour
   - Impact: Unknown until investigated

### Low Priority

5. **Negative pigmentation** (1.45M obs)
   - Add METPO proposal for "non-pigmented"
   - Requires METPO team approval
   - Low value - negative assertions
   - Expected time: 30 minutes (proposal only)
   - Impact: 1.45M observations (but low utility)

---

## Expected Coverage After Improvements

### Current State
- Total observations: ~48.5M
- Mapped: ~44.0M (90.7%)
- Unmapped: ~4.4M (9.3%)

### After High Priority Fixes
- Additional mapped: ~5.6K (enzyme GO) + 44 (required) = ~5.7K
- New coverage: 44,005,700 / 48,500,000 = **90.72%** (+0.02%)

### After Medium Priority Fixes  
- Additional mapped: ~200 (chemical synonyms) + ~100 (other) = ~300
- New coverage: 44,006,000 / 48,500,000 = **90.73%** (+0.03%)

### If Single Growth Tests Added (Optional)
- Additional mapped: 2.98M
- New coverage: 46,986,000 / 48,500,000 = **96.88%** (+6.15%)

### If Negative Pigmentation Added (Optional)
- Additional mapped: 1.45M
- New coverage: 48,441,000 / 48,500,000 = **99.88%** (+9.15%)

**Note:** Single growth tests and negative pigmentation are design decisions, not data quality issues. Current 90.7% coverage is appropriate for meaningful trait assertions.

---

## Files to Create

1. **`enzyme_name_to_go.tsv`**
   ```tsv
   enzyme_name	go_id	go_label	ec_number	notes
   alpha-maltosidase	GO:0004339	alpha-glucosidase activity	3.2.1.20	Synonym
   beta-Galactosidase 6-phosphate	GO:0004565	beta-galactosidase activity	3.2.1.23	Direct match
   ...
   ```

2. **Expand `chemical_name_synonyms.tsv`**
   - Add 10-15 stereochemistry variants
   - Add handling for "hydrolysate" suffix
   - Add concentration prefix stripping

3. **`METPO_GAPS_FINAL.md` update**
   - Add Gap 2: non-pigmented class
   - Lower priority than alkaliphilic

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

Of 4.4M unmapped observations:
- **99.9%** are design decisions (single tests, negative assertions)
- **0.1%** (6K obs) are genuine mapping opportunities
- **Priority:** Add enzyme GO mappings and required-for-growth resolver

Current 90.7% coverage is **appropriate** for meaningful trait assertions. The unmapped data is mostly binary test points and negative assertions that add limited value to the knowledge graph.

---

**Date:** 2026-04-06  
**Status:** Analysis complete - High priority fixes identified  
**Next:** Implement enzyme GO mapping and required-for-growth resolver
