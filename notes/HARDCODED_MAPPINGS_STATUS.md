# Hardcoded Mappings Status - MetaTraits Transform

**Date:** 2026-04-05  
**Status:** Mostly data-driven, some hardcoded mappings remain

---

## ✅ Data-Driven (Loaded from Files/Ontologies)

### 1. METPO Class Lookups
**Source:** `data/raw/metpo.json`  
**Method:** `_load_metpo_lookups()`
- `metpo_label_to_class` - 281 labels
- `metpo_synonym_to_class` - 317 synonyms
- `metpo_pattern_to_predicate` - 195 pattern predicates (positive/negative pairs)

**Used for:**
- Pigmentation colors (was hardcoded, now data-driven) ✅
- Chemical predicates (was hardcoded, now data-driven) ✅
- Metabolic predicates (was hardcoded, now data-driven) ✅
- Fermentation predicates (was hardcoded, now data-driven) ✅

### 2. METPO Binned Ranges
**Source:** `data/raw/metpo.json`  
**Method:** `_load_metpo_binned_ranges()`
- Temperature optimum bins: 7 classes
- pH optimum bins: 4 classes
- NaCl optimum bins: 4 classes

**Used for:**
- Temperature classification (was hardcoded, now data-driven) ✅
- pH classification (was hardcoded, now data-driven) ✅
- Salinity classification (was hardcoded, now data-driven) ✅

### 3. Chemical Mappings
**Source:** Various TSV files + ChEBI loader
- `special_chemical_mappings` - 30 entries from `special_chemical_mappings.tsv`
- `chemical_name_synonyms` - 11 entries from `chemical_name_synonyms.tsv`
- Dynamic ChEBI lookups via `ChemicalMappingLoader`

### 4. Taxon Mappings
**Source:** TSV files + OAK adapter
- `ncbitaxon_name_to_id` - 888K entries from `ncbitaxon_nodes.tsv`
- `ncbi_to_gtdb_mappings` - 17 entries from `ncbi_to_gtdb_taxa.tsv`

### 5. Other Loaded Mappings
- `microbial_mappings` - from `load_microbial_trait_mappings()`
- `metpo_mappings` - from `load_metpo_mappings()`
- `trait_mapping` - built from METPO + custom_curies

---

## ⚠️ Still Hardcoded

### 1. Material Fallbacks (Line ~1049)
**Location:** `_resolve_metabolic_trait()` method  
**Count:** 5 materials

```python
material_fallbacks = {
    "urea": ("CHEBI:16199", "urea"),
    "casein": ("KGM:casein", "casein"),  # protein mixture
    "gelatin": ("KGM:gelatin", "gelatin"),  # protein mixture
    "esculin": ("CHEBI:4806", "esculin"),
    "starch": ("CHEBI:28017", "starch"),
}
```

**Reason:** Last-resort fallback for materials not in ChEBI loader  
**Could fix:** Add to `special_chemical_mappings.tsv` or wait for ChEBI loader to handle

### 2. Trophic Mode Mappings (Line ~1144)
**Location:** `_resolve_growth_mode_trait()` method  
**Count:** 6 trophic modes → GO terms

```python
trophic_mappings = {
    "phototrophy": ("GO:0009579", "phototrophic process", "biolink:BiologicalProcess"),
    "chemoheterotrophy": ("GO:0044281", "small molecule metabolic process", "biolink:BiologicalProcess"),
    "photoautotrophy": ("GO:0009541", "photoautotrophic process", "biolink:BiologicalProcess"),
    "photoheterotrophy": ("GO:0009581", "photoheterotrophic process", "biolink:BiologicalProcess"),
    "anoxygenic photoautotrophy": ("GO:0019685", "photosynthesis, anoxygenic", "biolink:BiologicalProcess"),
    "anoxygenic phototrophy": ("GO:0019685", "photosynthesis, anoxygenic", "biolink:BiologicalProcess"),
}
```

**Reason:** Specific GO term mappings for trophic modes  
**Could fix:** Could load from GO ontology with OAK lookups by label

### 3. Aerobic/Anaerobic Growth (Lines 1187-1199)
**Location:** `_resolve_growth_mode_trait()` method  
**Count:** 2 direct METPO IDs

```python
if trait_name.lower().startswith("aerobic growth"):
    return {"curie": "METPO:1001003", ...}  # aerobe phenotype
elif trait_name.lower().startswith("anaerobic growth"):
    return {"curie": "METPO:1001004", ...}  # anaerobe phenotype
```

**Reason:** Common patterns not in synonym mappings  
**Could fix:** Add to METPO synonym mappings or use `metpo_label_to_class` lookup

### 4. Phenotype Mappings (Line ~1249)
**Location:** `_resolve_phenotype_trait()` method  
**Count:** 4 phenotypes

```python
phenotype_mappings = {
    "aerotolerant": ("METPO:1001025", "aerotolerant"),
    "facultative anaerobe": ("METPO:1001026", "facultative anaerobe"),
    "acidophilic": ("METPO:1001015", "acidophile"),
    "capnophilic": ("KGM:capnophilic", "capnophilic"),  # No METPO ID
}
```

**Reason:** Simple phenotypes not in synonym mappings  
**Could fix:** Use `metpo_label_to_class` lookup instead

### 5. Cell Morphology (Lines ~1362-1538)
**Location:** `_resolve_cell_morphology()` method  
**Count:** ~15 METPO IDs for various traits

Direct METPO IDs for:
- Cell shape (rod, coccus, spiral, filamentous): 4 IDs
- Gram stain (positive, negative, variable, indeterminate): 4 IDs
- Sporulation (yes/no): 2 IDs
- Motility (motile/non-motile): 2 IDs

**Reason:** Cell morphology traits are well-defined in METPO  
**Could fix:** Use `metpo_label_to_class` lookup for all of these

### 6. pH Preference (Lines 1665-1673)
**Location:** `_resolve_ph_preference_trait()` method  
**Count:** 2 METPO IDs

```python
if trait_value == "acidophilic":
    return {"curie": "METPO:1003003", ...}
if trait_value == "neutrophilic":
    return {"curie": "METPO:1003001", ...}
```

**Reason:** Simple lookups not using `metpo_label_to_class`  
**Could fix:** Use `metpo_label_to_class` lookup

### 7. Growth Pattern Predicates (Lines 1092-1095)
**Location:** `_resolve_growth_pattern()` method  
**Count:** 4 METPO predicate IDs

```python
patterns = [
    (r"^growth:\s*(.+)$", "METPO:2000012"),  # uses for growth
    (r"^builds acid from:\s*(.+)$", "METPO:2000003"),  # builds acid from
    (r"^builds gas from:\s*(.+)$", "METPO:2000005"),  # builds gas from
    (r"^builds base from:\s*(.+)$", "METPO:2000004"),  # builds base from
]
```

**Reason:** Direct predicate references instead of using `metpo_pattern_to_predicate`  
**Could fix:** Use `metpo_pattern_to_predicate` lookup (already available)

---

## Summary Statistics

**Data-driven:** ~2,000+ mappings loaded from files/ontologies  
**Still hardcoded:** ~34 mappings

**Percentage data-driven:** ~98%

---

## Recommendations

### High Priority (Use Existing Lookups)
These can use already-loaded `metpo_label_to_class` or `metpo_pattern_to_predicate`:

1. **Phenotype mappings** (4 entries) → Use `metpo_label_to_class`
2. **Aerobic/anaerobic growth** (2 entries) → Use `metpo_label_to_class`
3. **pH preference** (2 entries) → Use `metpo_label_to_class`
4. **Cell morphology** (~15 entries) → Use `metpo_label_to_class`
5. **Growth pattern predicates** (4 entries) → Use `metpo_pattern_to_predicate`

**Total:** ~27 mappings that can be replaced with existing lookups

### Medium Priority (Add to TSV Files)
1. **Material fallbacks** (5 entries) → Add to `special_chemical_mappings.tsv`

### Low Priority (Requires OAK GO Lookups)
1. **Trophic mappings** (6 entries) → Could load from GO ontology dynamically

---

## Not Hardcoded (Metadata)

These are **intentionally hardcoded** as they are metadata/configuration, not data:

1. **`METPO_TO_BIOLINK_PREDICATE`** (lines 52-95) - Maps METPO predicates to biolink predicates (schema mapping)
2. **`PREDICATE_TO_RELATION`** (lines 99-105) - Maps biolink predicates to RO relations (schema mapping)
3. **`MEASUREMENT_TRAITS`** (lines 263-282) - Set of trait names to exclude from unmapped file (configuration)

These are appropriate to keep hardcoded as they define the schema/structure rather than data content.

---

**Status:** 98% data-driven, 27 easy replacements identified  
**Date:** 2026-04-05
