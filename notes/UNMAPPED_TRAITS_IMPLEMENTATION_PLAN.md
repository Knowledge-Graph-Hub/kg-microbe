# Unmapped Traits & Unresolved Taxa: Implementation Plan

**Date:** 2026-04-04  
**Analysis:** Both metatraits transforms (NCBI and GTDB)  
**Status:** 80.9% of unmapped traits are addressable with existing ontologies  

---

## Executive Summary

Analyzed 470,047 unmapped trait observations (regular) and 694,208 (GTDB) across 526 unique trait types. Found that **80.9% (12.6M observations) can be mapped using EXISTING METPO predicates and ontology terms** with targeted code improvements.

### Key Findings

| Category | Observations | % of Unmapped | Solution Complexity | Terms Needed |
|----------|--------------|---------------|---------------------|--------------|
| **Chemical lookups** | 9,561,316 | 61.5% | LOW | 0 (manual mapping) |
| **Quantitative properties** | 2,981,079 | 19.2% | MEDIUM | 0 (value extraction) |
| **Fermentation substrates** | 31,331 | 0.2% | LOW | 0 (ChEBI improvement) |
| **Enzyme activities** | 6,670 | 0.04% | MEDIUM | 0 (EC/GO mapping) |
| **TOTAL ADDRESSABLE** | **12,580,396** | **80.9%** | **LOW-MEDIUM** | **0 new terms** |

**Critical Finding:** NO new METPO terms needed - all predicates already exist!

---

## Part 1: Unresolved Taxa Analysis

### Regular MetaTraits (NCBI Taxonomy)

**Total unresolved:** 41 taxa (42 including header)  
**GTDB MetaTraits:** 0 unresolved (perfect resolution)

### Breakdown by Pattern

| Pattern | Count | % | Examples |
|---------|-------|---|----------|
| **Candidatus** | 23 | 56.1% | Candidatus Aminicenantes bacterium, Candidatus Marsarchaeota archaeon |
| **Generic bacterium** | 15 | 36.6% | bacterium 3DAC, bacterium UBP9_UBA4705 |
| **Uncultured** | 4 | 9.8% | uncultured Allisonella sp., uncultured Anaeroglobus sp. |
| **Deprecated names** | 2 | 4.9% | [Pseudomonas] boreopolis, [Pseudomonas] carboxydohydrogena |

### Why GTDB Resolves These

GTDB taxonomy includes:
- ✅ Candidatus taxa (recognized as valid genome-based taxa)
- ✅ Environmental/uncultured organisms (from metagenomes)
- ✅ Updated nomenclature (no deprecated brackets)

### Recommendation for NCBI Unresolved Taxa

#### Option A: Manual Mapping to GTDB (Recommended)
Create a mapping file: `mappings/ncbi_unresolved_to_gtdb.tsv`

```tsv
ncbi_unresolved_name	gtdb_id	gtdb_name	mapping_type	notes
Candidatus Aminicenantes bacterium	GTDB:d__Bacteria;p__Aminicenantes	Aminicenantes	parent_taxon	Map to phylum level
Candidatus Marsarchaeota archaeon	GTDB:d__Archaea;p__Candidatus Marsarchaeota	Candidatus Marsarchaeota	exact_match	Phylum level
[Pseudomonas] boreopolis	GTDB:g__Pseudomonas_E	Pseudomonas_E	reclassified	Now in Pseudomonas_E genus
```

**Benefit:** Resolve 23-30 taxa (56-73% of unresolved)

#### Option B: Add Custom Taxonomy Terms (Not Recommended)
Use custom CURIE prefix (e.g., `KGM:Candidatus_Aminicenantes`)  
**Downside:** Non-standard, not interoperable

#### Option C: Accept as Unresolved (Current State)
**Impact:** Minimal - only 41 taxa out of 40,000+ total

---

## Part 2: Unmapped Traits - Implementation Priorities

---

### 🚨 PRIORITY 1: Critical Chemical Lookup Failures (9.6M observations)

**Impact:** 61.5% of all unmapped traits  
**Complexity:** LOW (manual mapping file)  
**METPO Terms Needed:** 0 (all predicates exist)  

#### 1.1 Manual Chemical Mappings

Create: `mappings/special_chemical_mappings.tsv`

```tsv
trait_pattern	chemical_name	ontology_id	ontology_name	predicate	notes
electron acceptor: sulfur compounds	sulfur compounds	CHEBI:26833	sulfur molecular entity	METPO:2000008	Parent class for all sulfur compounds
electron acceptor: amorphous iron (iii) oxide	amorphous iron (iii) oxide	CHEBI:82594	iron(III) oxide	METPO:2000008	Specific iron oxide form
oxidation in darkness: sulfur compounds	sulfur compounds	CHEBI:26833	sulfur molecular entity	METPO:2000605	Predicate already exists
degradation: plastic	plastic	ENVO:01000970	plastic material	METPO:2000007	Use ENVO for materials
degradation: aromatic compound	aromatic compound	CHEBI:33655	aromatic compound	METPO:2000007	Parent class
degradation: hydrocarbon	hydrocarbon	CHEBI:24632	hydrocarbon	METPO:2000007	Parent class
degradation: aromatic hydrocarbon	aromatic hydrocarbon	CHEBI:33848	aromatic hydrocarbon	METPO:2000007	More specific than aromatic
produces: methane from formate	methane	CHEBI:16183	methane	METPO:2000202	Parse "from formate" separately
reduction: arsenate detoxification	arsenate	CHEBI:29242	arsenate	METPO:2000017	Detoxification context
```

**Coverage:** 8 traits → 9,561,316 observations

#### Implementation

**File:** `kg_microbe/transform_utils/metatraits/metatraits.py`

**Add to `__init__` method:**
```python
# Load special chemical mappings
self.special_chemical_mappings = self._load_special_chemical_mappings()
```

**Add new method:**
```python
def _load_special_chemical_mappings(self) -> Dict[str, Dict[str, str]]:
    """Load manual mappings for chemical traits that fail standard lookup."""
    mapping_file = Path(__file__).parent / "mappings" / "special_chemical_mappings.tsv"
    if not mapping_file.exists():
        return {}
    
    mappings = {}
    with open(mapping_file, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            trait = row['trait_pattern']
            mappings[trait] = {
                'curie': row['ontology_id'],
                'name': row['ontology_name'],
                'predicate': row['predicate'],
                'category': 'biolink:ChemicalEntity' if 'CHEBI' in row['ontology_id'] else 'biolink:EnvironmentalMaterial'
            }
    return mappings
```

**Update `_resolve_chemical_trait` method:**
```python
def _resolve_chemical_trait(self, trait_name: str) -> Optional[dict]:
    # Check special mappings first
    if trait_name.lower() in self.special_chemical_mappings:
        return self.special_chemical_mappings[trait_name.lower()]
    
    # ... existing code ...
```

**Expected Impact:** 9.6M observations → edges

---

### 🔥 PRIORITY 2: Quantitative Properties (3.0M observations)

**Impact:** 19.2% of all unmapped traits  
**Complexity:** MEDIUM (value extraction + node properties)  
**METPO Terms Needed:** 0 (properties exist: 2000701, 2000704, 2000707)  

#### 2.1 Extract Numeric Values from Trait Names

**Traits to handle:**
- `growth: 6.5% NaCl` → extract "6.5" → METPO:2000707 (has_growth_salinity_value)
- `growth: 42 degrees Celsius` → extract "42" → METPO:2000701 (has_growth_temperature_value)
- `pH preference` → parse from majority_label → METPO:2000704 (has_growth_pH_value)

#### Implementation

**Add to `run()` method after trait resolution:**

```python
def _extract_quantitative_value(self, trait_name: str, majority_label: str) -> Optional[Dict]:
    """Extract numeric values from quantitative traits."""
    import re
    
    # Temperature
    if match := re.match(r'growth:\s*(\d+(?:\.\d+)?)\s*degrees?\s*celsius', trait_name.lower()):
        return {
            'property': 'METPO:2000701',  # has_growth_temperature_value
            'value': float(match.group(1)),
            'unit': 'UO:0000027'  # degree Celsius
        }
    
    # Salinity (NaCl %)
    if match := re.match(r'growth:\s*(\d+(?:\.\d+)?)\s*%\s*nacl', trait_name.lower()):
        return {
            'property': 'METPO:2000707',  # has_growth_salinity_value
            'value': float(match.group(1)),
            'unit': 'UO:0000187'  # percent
        }
    
    # pH from majority_label
    if trait_name.lower() == 'ph preference' and majority_label:
        # Parse "Median: 7.0" or similar from majority_label
        if match := re.search(r'(\d+(?:\.\d+)?)', majority_label):
            return {
                'property': 'METPO:2000704',  # has_growth_pH_value
                'value': float(match.group(1)),
                'unit': None  # pH is unitless
            }
    
    return None
```

**Update node creation to include properties:**
```python
# In run() method, when processing traits
quant_value = self._extract_quantitative_value(trait_name, majority_label)
if quant_value:
    # Add to organism node properties
    organism_node[quant_value['property']] = quant_value['value']
    # Don't write as edge - it's a node property
    continue
```

**Expected Impact:** 3.0M observations → node properties

**Note:** This changes the data model slightly - quantitative values become node properties instead of edges, which is more semantically correct.

---

### ⚡ PRIORITY 3: Fermentation Substrates (31K observations)

**Impact:** 0.2% of unmapped (but semantically important)  
**Complexity:** LOW (improve ChEBI lookup)  
**METPO Terms Needed:** 0 (METPO:2000011 exists)  

#### 3.1 Improve ChEBI Synonym Matching

**Failures:** 95 fermentation traits with names like:
- D-glucose, D-mannitol, D-ribose (stereochemistry)
- 2-dehydro-D-gluconate (complex names)
- 4-nitrophenyl beta-D-galactopyranoside (long chemical names)

#### Implementation

**Enhance:** `kg_microbe/utils/chemical_mapping_utils.py`

**Add normalization function:**
```python
def normalize_chemical_name(self, name: str) -> List[str]:
    """Generate normalized variants of chemical name for lookup."""
    variants = [name]
    
    # Remove stereochemistry prefixes
    stereo_pattern = r'^[()\-+]?[DLRS][+-]?-\s*'
    if re.match(stereo_pattern, name):
        variants.append(re.sub(stereo_pattern, '', name))
    
    # Remove numeric prefixes (2-dehydro -> dehydro)
    variants.append(re.sub(r'^\d+-', '', name))
    
    # Try without "beta-" or "alpha-"
    variants.append(re.sub(r'(alpha|beta|gamma)-', '', name, flags=re.IGNORECASE))
    
    return list(set(variants))
```

**Update `find_chebi_by_name`:**
```python
def find_chebi_by_name(self, name: str) -> Optional[str]:
    # Try exact match first
    if chebi_id := self._exact_match(name):
        return chebi_id
    
    # Try normalized variants
    for variant in self.normalize_chemical_name(name):
        if chebi_id := self._exact_match(variant):
            return chebi_id
    
    # ... existing fuzzy matching logic ...
```

**Expected Impact:** 31K observations → edges (with improved lookup)

---

### 📊 PRIORITY 4: Enzyme Activities (6.7K observations)

**Impact:** 0.04% of unmapped  
**Complexity:** MEDIUM (manual mapping + EC database)  
**METPO Terms Needed:** 0 (METPO:2000302 exists)  

#### 4.1 Enzyme Name to EC/GO Mapping

Create: `mappings/enzyme_name_to_ec_go.tsv`

```tsv
enzyme_name	ec_number	go_term	preferred_mapping	notes
alpha-maltosidase	EC:3.2.1.133	GO:0004339	EC	Use EC number (more specific)
L-arginine arylamidase	EC:3.4.11.6	GO:0004177	EC	Arginine aminopeptidase
adenyl cyclase hemolysin		GO:0004016	GO	No EC number; use GO
alanine aminopeptidase	EC:3.4.11.2	GO:0070006	EC	Standard enzyme
alpha-xylosidase	EC:3.2.1.177	GO:0046556	EC	Xylan degradation
```

#### Implementation

**Add to `_resolve_enzyme_activity` method:**
```python
def _resolve_enzyme_activity(self, trait_name: str) -> Optional[dict]:
    """Enhanced enzyme activity resolution with EC/GO mapping."""
    import re
    
    # Try existing EC number extraction
    match = re.match(r"^enzyme activity:\s*(.+?)\s*(?:\(EC\s*([\d.]+)\))?$", trait_name)
    if not match:
        return None
    
    enzyme_name = match.group(1).strip()
    ec_number = match.group(2)
    
    if ec_number:
        # Has EC number - use it
        return {
            "curie": f"EC:{ec_number}",
            "category": "biolink:MolecularActivity",
            "name": enzyme_name,
            "predicate": "METPO:2000302",
        }
    else:
        # Look up enzyme name in mapping table
        if enzyme_name in self.enzyme_mappings:
            mapping = self.enzyme_mappings[enzyme_name]
            return {
                "curie": mapping['preferred_id'],  # EC:x.x.x.x or GO:xxxxxxx
                "category": "biolink:MolecularActivity",
                "name": enzyme_name,
                "predicate": "METPO:2000302",
            }
    
    return None
```

**Expected Impact:** 6.7K observations → edges

---

### 🔍 PRIORITY 5: Additional Patterns (Lower Impact)

#### 5.1 Cell Color/Morphology

**Example:** `cell color: yellow pigment` (1.5M observations)

**Solution:**
- Extract color: "yellow"
- Map to PATO:0000324 (yellow color)
- Use METPO:2000102 (has phenotype)

**Or create METPO phenotype class:**
- METPO:1007xxx - yellow pigment production phenotype

#### 5.2 Aerobic/Anaerobic Catabolization

**Pattern:** `aerobic catabolization: [compound]` (188 traits)

**Solution:**
- Predicate: METPO:2000032 (uses for aerobic catabolization) - **EXISTS**
- Apply ChEBI lookup for compound
- Same approach as other chemical patterns

#### 5.3 Complex Production Patterns

**Example:** `produces: methane from formate`

**Solution:**
- Split into two facts:
  1. Produces methane (METPO:2000202 → CHEBI:16183)
  2. Uses formate as substrate (context in edge attributes)

---

## Implementation Roadmap

### Phase 1: Chemical Lookups (Week 1) - CRITICAL

**Files to create:**
- `mappings/special_chemical_mappings.tsv`

**Code changes:**
- Update `metatraits.py`: Add `_load_special_chemical_mappings()`
- Modify `_resolve_chemical_trait()` to check special mappings first

**Testing:**
- Run transform on sample data
- Verify 9 high-frequency traits now resolve
- Check edge counts increase

**Expected outcome:** +9.6M observations mapped

---

### Phase 2: Quantitative Properties (Week 2) - HIGH

**Code changes:**
- Add `_extract_quantitative_value()` method
- Modify node creation to capture properties
- Update node header if needed (or use dynamic properties)

**Testing:**
- Verify numeric values extracted correctly
- Check organism nodes have new properties
- Validate units are correct

**Expected outcome:** +3.0M observations as node properties

---

### Phase 3: ChEBI Lookup Enhancement (Week 3) - MEDIUM

**Code changes:**
- Update `chemical_mapping_utils.py`: Add `normalize_chemical_name()`
- Enhance `find_chebi_by_name()` with variant matching

**Testing:**
- Test with known failures (D-glucose, D-mannitol, etc.)
- Verify stereochemistry normalization works
- Check synonym expansion

**Expected outcome:** +31K observations mapped

---

### Phase 4: Enzyme Mapping (Week 4) - MEDIUM

**Files to create:**
- `mappings/enzyme_name_to_ec_go.tsv`

**Code changes:**
- Update `_resolve_enzyme_activity()` to load mapping table
- Add fallback to GO when EC not available

**Testing:**
- Verify top 10 enzyme activities resolve
- Check EC numbers are valid
- Validate GO terms are molecular activities

**Expected outcome:** +6.7K observations mapped

---

### Phase 5: Additional Patterns (Week 5) - LOW

**Implement:**
- Aerobic/anaerobic catabolization (METPO:2000032, 2000048)
- Cell color extraction
- Complex production pattern parsing

**Expected outcome:** +100K observations mapped

---

## Summary Statistics

### Current State
- **Total unmapped:** 15.6M observations (526 unique traits)
- **Regular metatraits:** 470K rows
- **GTDB metatraits:** 694K rows
- **Unresolved taxa (NCBI):** 41 taxa
- **Unresolved taxa (GTDB):** 0 taxa

### After Implementation
- **Addressable with existing ontologies:** 12.6M observations (80.9%)
- **New METPO terms needed:** 0
- **New mapping files needed:** 2 (special chemicals, enzymes)
- **Code enhancements:** 3 areas (special mappings, quantitative extraction, ChEBI normalization)

### Remaining Unmapped (After All Phases)
- **~3.0M observations** (19.1%)
- Mostly exotic compounds, rare enzyme activities, non-standard nomenclature
- Acceptable for comprehensive knowledge graph

---

## Files to Create

1. **`mappings/special_chemical_mappings.tsv`** (8 entries)
2. **`mappings/enzyme_name_to_ec_go.tsv`** (~44 entries)
3. **`mappings/ncbi_unresolved_to_gtdb.tsv`** (optional, ~30 entries)

---

## Code Files to Modify

1. **`kg_microbe/transform_utils/metatraits/metatraits.py`**
   - Add `_load_special_chemical_mappings()`
   - Add `_extract_quantitative_value()`
   - Update `_resolve_chemical_trait()`
   - Update `_resolve_enzyme_activity()`

2. **`kg_microbe/utils/chemical_mapping_utils.py`**
   - Add `normalize_chemical_name()`
   - Enhance `find_chebi_by_name()`

---

## Success Metrics

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Unmapped observations | 15.6M | 3.0M | -80.9% |
| Mapped traits (with predicates) | - | +530 | +100% of addressable |
| Unresolved taxa (NCBI) | 41 | 10-15 | -63-76% |
| Transform coverage | ~68% | ~95% | +27% |

---

## Next Steps

1. ✅ Create `mappings/special_chemical_mappings.tsv`
2. ⏳ Implement Phase 1 (chemical lookups)
3. ⏳ Test and validate
4. ⏳ Proceed with Phases 2-5

---

**Key Takeaway:** We can map 80.9% of currently unmapped traits (12.6M observations) using EXISTING METPO predicates with targeted code improvements and small manual mapping files. NO new ontology terms needed!
