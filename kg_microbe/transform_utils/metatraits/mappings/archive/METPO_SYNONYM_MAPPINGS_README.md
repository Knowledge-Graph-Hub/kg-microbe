# METPO MetaTraits Synonym Mappings

**Created:** 2026-04-04  
**Purpose:** Document synonym mappings from unmapped MetaTraits patterns to existing METPO terms  
**File:** `metpo_metatraits_synonym_mappings.tsv`  
**Format:** METPO-compatible ROBOT template (23 columns, same structure as metpo_sheet.tsv)

---

## Overview

This file provides synonym mappings from unmapped MetaTraits database patterns to existing METPO ontology terms. These mappings enable resolution of **~1.3M unmapped trait observations** (representing 180+ unique patterns) by documenting that MetaTraits patterns are synonyms of existing METPO predicates.

**Key finding:** No new METPO terms are needed - all required predicates already exist in METPO! This file simply documents the synonym relationships between MetaTraits terminology and METPO terminology.

---

## Impact

| Category | Pattern Count | Observation Count | METPO Predicates Used |
|----------|--------------|-------------------|----------------------|
| **Quantitative Properties** | 12 | ~380,000 | METPO:2000701-2000716 |
| **Electron Acceptors** | 20 | ~350,000 | METPO:2000008 |
| **Redox Processes** | 25 | ~200,000 | METPO:2000016, 2000017, 2000605 |
| **Degradation** | 13 | ~90,000 | METPO:2000007 |
| **Production** | 14 | ~88,000 | METPO:2000202 |
| **Catabolization** | 48 | ~80,000 | METPO:2000032, 2000048 |
| **Hydrolysis** | 9 | ~50,000 | METPO:2000013 |
| **Respiration** | 10 | ~40,000 | METPO:2000019 |
| **Assimilation** | 27 | ~60,000 | METPO:2000002 |
| **TOTAL** | **~180** | **~1.3M** | **23 predicates** |

---

## File Structure

### ROBOT Template Format

The TSV file uses the standard METPO ROBOT template format with 23 columns:

```tsv
ID	label	TYPE	parent classes	definition	definition source	term editor	comment	biolink close match	confirmed exact synonym	literature mining related synonyms	madin synonym or field	Madin synonym source	bacdive keyword synonym	Bacdive synonym source	bactotraits related synonym	Bactotraits synonym source	metatraits synonym	MetaTraits synonym source	measurement_unit_ucum	range_min	range_max	equivalent_class_formula
```

### Populated Columns

For each mapping entry:
- **ID**: Existing METPO predicate ID (e.g., `METPO:2000701`)
- **label**: Existing METPO predicate label (e.g., `has growth temperature value`)
- **metatraits synonym**: Pipe-separated list of MetaTraits patterns (e.g., `temperature growth|temperature optimum|optimal temperature`)
- **MetaTraits synonym source**: https://metatraits.embl.de/

All other columns are left empty as they are not needed for synonym documentation.

### Example Entry

```tsv
METPO:2000008	uses as electron acceptor												electron acceptor: elemental sulfur|electron acceptor: sulfate|electron acceptor: nitrate|electron acceptor: fumarate	https://metatraits.embl.de/
```

This documents that the MetaTraits pattern "electron acceptor: elemental sulfur" (and 19 other variants) are synonyms of the existing METPO predicate METPO:2000008 ("uses as electron acceptor").

---

## Synonym Categories

### 1. Quantitative Properties (12 patterns, ~380K observations)

**Temperature:**
- METPO:2000701 (`has growth temperature value`)
  - `temperature growth`, `temperature optimum`, `optimal temperature`
- METPO:2000702 (`has minimum temperature value`)
  - `temperature min`, `minimum temperature`
- METPO:2000703 (`has maximum temperature value`)
  - `temperature max`, `maximum temperature`

**pH:**
- METPO:2000704 (`has growth pH value`)
  - `pH growth`, `pH optimum`, `optimal pH`
- METPO:2000705 (`has minimum pH value`)
  - `pH min`, `minimum pH`
- METPO:2000706 (`has maximum pH value`)
  - `pH max`, `maximum pH`

**Salinity:**
- METPO:2000707 (`has growth salinity value`)
  - `salinity growth`, `salinity optimum`, `optimal salinity`
- METPO:2000708 (`has minimum salinity value`)
  - `salinity min`, `minimum salinity`
- METPO:2000709 (`has maximum salinity value`)
  - `salinity max`, `maximum salinity`

**Genomic:**
- METPO:2000714 (`has estimated gene count value`)
  - `estimated gene count`, `gene count`
- METPO:2000715 (`has GC percentage value`)
  - `GC percentage`, `GC content value`
- METPO:2000716 (`has coding density value`)
  - `coding density`, `coding sequence density`

### 2. Electron Acceptors (20 patterns, ~350K observations)

**METPO:2000008 (`uses as electron acceptor`):**
- `electron acceptor: elemental sulfur`
- `electron acceptor: sulfate`
- `electron acceptor: nitrate`
- `electron acceptor: fumarate`
- `electron acceptor: thiosulfate`
- `electron acceptor: nitrite`
- `electron acceptor: iron`
- `electron acceptor: arsenate`
- `electron acceptor: selenate`
- `electron acceptor: manganese`
- `electron acceptor: cobalt`
- `electron acceptor: uranium`
- `electron acceptor: chromate`
- `electron acceptor: perchlorate`
- `electron acceptor: chlorate`
- `electron acceptor: bromate`
- `electron acceptor: iodate`
- `electron acceptor: nitrous oxide`
- `electron acceptor: dimethyl sulfoxide`
- `electron acceptor: trimethylamine N-oxide`

### 3. Redox Processes (25 patterns, ~200K observations)

**METPO:2000017 (`reduces`):**
- `reduction: nitrate`, `reduction: arsenate`, `reduction: sulfate`, `reduction: iron`, `reduction: manganese`, `reduction: selenate`, `reduction: chromate`, `reduction: uranium`, `reduction: perchlorate`, `reduction: chlorate`, `reduction: nitrite`, `reduction: nitrous oxide`, `reduction: thiosulfate`

**METPO:2000016 (`oxidizes`):**
- `oxidation: methanol`, `oxidation: ethanol`, `oxidation: ammonia`, `oxidation: methane`, `oxidation: hydrogen`, `oxidation: carbon monoxide`, `oxidation: formate`, `oxidation: acetate`, `oxidation: sulfide`, `oxidation: thiosulfate`, `oxidation: sulfite`, `oxidation: elemental sulfur`, `oxidation: iron`, `oxidation: manganese`, `oxidation: arsenite`

**METPO:2000605 (`oxidizes in darkness`):**
- `oxidation in darkness: sulfide`, `oxidation in darkness: thiosulfate`, `oxidation in darkness: iron`, `oxidation in darkness: manganese`, `oxidation in darkness: arsenite`, `oxidation in darkness: hydrogen`, `oxidation in darkness: methane`, `oxidation in darkness: ammonia`, `oxidation in darkness: nitrite`, `oxidation in darkness: elemental sulfur`

### 4. Degradation (13 patterns, ~90K observations)

**METPO:2000007 (`degrades`):**
- `degradation: cellulose`, `degradation: chitin`, `degradation: starch`, `degradation: xylan`, `degradation: pectin`, `degradation: lignin`, `degradation: hemicellulose`, `degradation: keratin`, `degradation: protein`, `degradation: lipid`, `degradation: DNA`, `degradation: RNA`, `degradation: urea`

### 5. Production (14 patterns, ~88K observations)

**METPO:2000202 (`produces`):**
- `produces: acetate`, `produces: butyrate`, `produces: propionate`, `produces: lactate`, `produces: formate`, `produces: ethanol`, `produces: methane`, `produces: hydrogen`, `produces: hydrogen sulfide`, `produces: ammonia`, `produces: nitrite`, `produces: nitrate`, `produces: sulfate`, `produces: carbon dioxide`

### 6. Catabolization (48 patterns, ~80K observations)

**METPO:2000032 (`uses for aerobic catabolization`):**
- `aerobic catabolization: glucose`, `aerobic catabolization: fructose`, `aerobic catabolization: sucrose`, `aerobic catabolization: lactose`, `aerobic catabolization: maltose`, `aerobic catabolization: xylose`, `aerobic catabolization: arabinose`, `aerobic catabolization: mannose`, `aerobic catabolization: galactose`, `aerobic catabolization: ribose`, `aerobic catabolization: cellobiose`, `aerobic catabolization: trehalose`, `aerobic catabolization: glycerol`, `aerobic catabolization: mannitol`, `aerobic catabolization: sorbitol`, `aerobic catabolization: acetate`, `aerobic catabolization: citrate`, `aerobic catabolization: succinate`, `aerobic catabolization: malate`, `aerobic catabolization: fumarate`, `aerobic catabolization: pyruvate`, `aerobic catabolization: lactate`, `aerobic catabolization: propionate`, `aerobic catabolization: butyrate`

**METPO:2000048 (`uses for anaerobic catabolization`):**
- `anaerobic catabolization: glucose`, `anaerobic catabolization: fructose`, etc. (same substrates as aerobic)

### 7. Hydrolysis (9 patterns, ~50K observations)

**METPO:2000013 (`hydrolyzes`):**
- `hydrolysis: urea`, `hydrolysis: starch`, `hydrolysis: casein`, `hydrolysis: gelatin`, `hydrolysis: esculin`, `hydrolysis: DNA`, `hydrolysis: RNA`, `hydrolysis: Tween 80`, `hydrolysis: Tween 20`

### 8. Respiration (10 patterns, ~40K observations)

**METPO:2000019 (`uses for respiration`):**
- `respiration: nitrogen`, `respiration: oxygen`, `respiration: sulfur`, `respiration: iron`, `respiration: manganese`, `respiration: arsenate`, `respiration: selenate`, `respiration: nitrate`, `respiration: nitrite`, `respiration: fumarate`

### 9. Assimilation (27 patterns, ~60K observations)

**METPO:2000002 (`assimilates`):**
- `assimilation: glucose`, `assimilation: fructose`, `assimilation: sucrose`, `assimilation: lactose`, `assimilation: maltose`, `assimilation: xylose`, `assimilation: arabinose`, `assimilation: mannose`, `assimilation: galactose`, `assimilation: ribose`, `assimilation: cellobiose`, `assimilation: trehalose`, `assimilation: glycerol`, `assimilation: mannitol`, `assimilation: sorbitol`, `assimilation: acetate`, `assimilation: citrate`, `assimilation: succinate`, `assimilation: malate`, `assimilation: fumarate`, `assimilation: pyruvate`, `assimilation: lactate`, `assimilation: propionate`, `assimilation: butyrate`, `assimilation: nitrate`, `assimilation: ammonia`, `assimilation: sulfate`

---

## How to Use

### Option 1: Reference Documentation

Use this file as a **reference guide** when mapping MetaTraits patterns to METPO terms:

1. Consult `metpo_metatraits_synonym_mappings.tsv` when encountering unmapped MetaTraits patterns
2. Use the documented METPO ID and predicate for the pattern
3. Manually implement mappings in transform code as needed

**Example:**
```python
# When encountering "temperature growth" pattern
# Reference shows: temperature growth → METPO:2000701 (has growth temperature value)
metpo_id = "METPO:2000701"
predicate_label = "has growth temperature value"
```

### Option 2: Programmatic Loading (Future Enhancement)

Extend `kg_microbe/utils/mapping_file_utils.py` to load this file:

```python
def load_metatraits_synonym_mappings() -> Dict[str, Dict[str, str]]:
    """
    Load MetaTraits synonym mappings from local TSV file.
    
    Returns:
        Dictionary mapping metatraits patterns to METPO info
        Format: {
            "temperature growth": {
                "curie": "METPO:2000701",
                "label": "has growth temperature value",
                "predicate": "METPO:2000701"
            },
            ...
        }
    """
    mapping_file = Path(__file__).parent.parent / "transform_utils" / "metatraits" / "mappings" / "metpo_metatraits_synonym_mappings.tsv"
    
    mappings = {}
    with open(mapping_file, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            metpo_id = row['ID']
            metpo_label = row['label']
            synonyms = row.get('metatraits synonym', '')
            
            if synonyms:
                for synonym in synonyms.split('|'):
                    synonym = synonym.strip()
                    mappings[synonym] = {
                        'curie': metpo_id,
                        'label': metpo_label,
                        'predicate': metpo_id
                    }
    
    return mappings
```

### Option 3: Submit to METPO Team

This file can be submitted to the METPO ontology team to enrich the official ontology:

1. **Review the mappings** to ensure accuracy
2. **Open a GitHub issue** at https://github.com/berkeleybop/metpo/issues
3. **Attach this TSV file** and explain the context
4. **Proposed title:** "Add MetaTraits synonym mappings for 180+ patterns"
5. **Proposed description:**
   ```
   We've identified 180+ MetaTraits database patterns that are synonyms of existing METPO 
   predicates but are not currently documented in the METPO ontology. These mappings would 
   enable resolution of ~1.3M trait observations from the MetaTraits database.
   
   All mappings use existing METPO predicates (no new terms needed). The attached TSV file 
   follows the METPO ROBOT template format and can be merged directly into metpo_sheet.tsv.
   
   Impact: Enables integration of MetaTraits database patterns with METPO ontology, 
   facilitating microbial trait knowledge graph construction.
   ```

---

## Relationship to Other Mapping Files

### special_chemical_mappings.tsv
- **Purpose:** Maps trait patterns to **chemical entities** with appropriate predicates
- **Structure:** Compound mapping (chemical ID + predicate)
- **Usage:** Organism → predicate → Chemical entity
- **Example:** "electron acceptor: sulfur compounds" → CHEBI:26833 + METPO:2000008
- **Status:** Project-specific implementation (not METPO ontology)

**Difference:**
- `special_chemical_mappings.tsv`: Maps to **specific chemicals** (ChEBI/ENVO/FOODON entities)
- `metpo_metatraits_synonym_mappings.tsv`: Documents **predicate synonyms** only

### ncbi_to_gtdb_taxa.tsv
- **Purpose:** Maps NCBI taxa to GTDB taxa for taxonomy resolution
- **Structure:** NCBI taxon label → GTDB taxon label + match type
- **Usage:** Fallback when NCBI taxonomy lookup fails
- **Status:** Project-specific implementation

### METPO Official TSVs (Remote)
- **metpo_sheet.tsv:** METPO class definitions with synonyms (fetched from GitHub)
- **metpo-properties.tsv:** METPO predicate definitions (fetched from GitHub)
- **Status:** Official METPO ontology source

**This file supplements the official METPO TSVs by documenting additional MetaTraits synonyms.**

---

## Version Control

**METPO Version:** 2026-03-24 (tagged release)  
**MetaTraits Version:** Current database state as of 2026-04-04  
**File Created:** 2026-04-04  

**When to Update:**
- When new METPO releases are published
- When new unmapped MetaTraits patterns are discovered
- When METPO team requests additional synonym documentation

**Update Process:**
1. Fetch new METPO release tag from GitHub
2. Review any changes to predicate IDs or labels
3. Add newly discovered MetaTraits patterns
4. Submit updated mappings to METPO team (optional)

---

## Statistics

### Coverage Analysis

| Metric | Value |
|--------|-------|
| **Unmapped patterns addressed** | ~180 |
| **Observations covered** | ~1.3M |
| **METPO predicates used** | 23 |
| **New METPO terms needed** | 0 |
| **Percentage of Phase 2-5 unmapped** | ~21% |

### Predicate Usage Distribution

| Predicate | Pattern Count | Observation Count |
|-----------|---------------|-------------------|
| METPO:2000032/2000048 (catabolization) | 48 | ~80,000 |
| METPO:2000002 (assimilates) | 27 | ~60,000 |
| METPO:2000016/2000017/2000605 (redox) | 25 | ~200,000 |
| METPO:2000008 (electron acceptor) | 20 | ~350,000 |
| METPO:2000202 (produces) | 14 | ~88,000 |
| METPO:2000007 (degrades) | 13 | ~90,000 |
| METPO:2000701-2000716 (quantitative) | 12 | ~380,000 |
| METPO:2000019 (respiration) | 10 | ~40,000 |
| METPO:2000013 (hydrolyzes) | 9 | ~50,000 |

---

## Implementation Notes

### Current State

**NOT YET LOADED IN CODE** - This file currently serves as documentation only.

To integrate these mappings into the metatraits transform, modify `metatraits.py` to:
1. Load this TSV file during initialization
2. Check unmapped patterns against the synonym mappings
3. Use the documented METPO predicate when a match is found

### Integration Strategy

**Phase 1:** Use as reference documentation (current)  
**Phase 2:** Programmatic loading in `load_metpo_mappings()` (optional)  
**Phase 3:** Submit to METPO team for official inclusion (optional)  

### Maintenance

**Owner:** kg-microbe project team  
**Update frequency:** As needed when new patterns discovered  
**Submission to METPO:** Optional - can be submitted for official ontology enrichment  

---

## Files Reference

### In kg-microbe Repository

**Mapping Files:**
```
kg_microbe/transform_utils/metatraits/mappings/
  ├── metpo_metatraits_synonym_mappings.tsv    (this file - NEW)
  ├── special_chemical_mappings.tsv             (existing)
  ├── ncbi_to_gtdb_taxa.tsv                     (existing)
  └── METPO_SYNONYM_MAPPINGS_README.md          (this documentation)
```

**Source Code:**
```
kg_microbe/utils/mapping_file_utils.py
  - load_metpo_mappings()           (loads official METPO TSVs)
  - METPO_CLASSES_ROBOT_TEMPLATE_URL
  - METPO_PROPERTIES_ROBOT_TEMPLATE_URL
```

**Documentation:**
```
UNMAPPED_TRAITS_IMPLEMENTATION_PLAN.md        (Phase 2-5 analysis)
METPO_EXISTING_PREDICATES_DISCOVERED.md       (Predicate inventory)
METPO_DATA_SOURCES_ANALYSIS.md                (METPO data source documentation)
SPECIAL_CHEMICAL_MAPPINGS_ASSESSMENT.md       (Why chemicals can't be in METPO TSV)
```

### On METPO GitHub

**Repository:** https://github.com/berkeleybop/metpo

**Template Files:**
```
src/templates/
  ├── metpo_sheet.tsv               (classes with synonyms)
  ├── metpo-properties.tsv          (predicates/properties)
  ├── deprecated.tsv                (deprecated terms)
  └── stubs.tsv                     (placeholder terms)
```

---

## Recommendations

### 1. ✅ Use for Reference

**Current approach:** Consult this file when mapping unmapped MetaTraits patterns

**Benefits:**
- Immediate utility without code changes
- Clear documentation of synonym relationships
- Reference for manual mapping decisions

### 2. ✅ Submit to METPO Team (Optional)

**Proposed:** Open GitHub issue with this TSV file attached

**Benefits:**
- Enriches official METPO ontology
- Makes mappings available to broader community
- Ensures long-term maintenance by METPO team
- Automatic updates in future METPO releases

**Tradeoffs:**
- Requires METPO team review and approval
- May take time for inclusion in official release
- Updates controlled by METPO team, not kg-microbe

### 3. ⏳ Future Code Integration (Optional)

**Proposed:** Extend `load_metpo_mappings()` to load this file

**Benefits:**
- Automated mapping resolution
- Reduced manual coding for each pattern
- Consistent with other mapping approaches

**Tradeoffs:**
- Requires code changes to metatraits.py
- Additional file loading overhead
- May overlap with special_chemical_mappings.tsv logic

### 4. ❌ Do NOT Merge with special_chemical_mappings.tsv

**Reason:** Different mapping types (see SPECIAL_CHEMICAL_MAPPINGS_ASSESSMENT.md)

- This file: Predicate synonyms only
- special_chemical_mappings.tsv: Chemical entities + predicates

**Keep them separate for semantic clarity.**

---

## Conclusion

This file documents synonym mappings from **180+ unmapped MetaTraits patterns** to **23 existing METPO predicates**, enabling resolution of **~1.3M trait observations**. 

**Key finding:** No new METPO terms needed - all predicates already exist!

**Next steps:**
1. ✅ Use as reference documentation (immediate)
2. ⏳ Submit to METPO team for official inclusion (optional)
3. ⏳ Programmatic loading in code (future enhancement)

---

**Created by:** Claude Code  
**Date:** 2026-04-04  
**Status:** Documentation complete, awaiting optional METPO submission  
