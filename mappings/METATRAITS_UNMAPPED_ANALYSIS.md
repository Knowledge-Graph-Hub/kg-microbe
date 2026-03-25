# MetaTraits Unmapped Traits Analysis

**Date:** 2026-03-25
**Analyzed Files:**
- `data/transformed/metatraits_gtdb/unmapped_traits_unique.tsv` (902 unique unmapped traits)
- Manual mapping files in `kg_microbe/transform_utils/metatraits/mappings/`
- METPO ontology (loaded from GitHub repository)

## Executive Summary

Out of 902 unique unmapped traits from the metatraits_gtdb transform:

- **~35 traits** (4%) should be **METPO phenotypic quality terms** (new mappings needed)
- **~750 traits** (83%) are **chemical metabolic traits** that should map to ChEBI (pattern resolvers exist)
- **~53 traits** (6%) are **enzyme activities** that should map to EC or GO
- **~64 traits** (7%) need **new METPO predicates** for specific metabolic processes

## Current Mapping Infrastructure

### 1. Manual Curated Mappings (Tier 1)
Located in `kg_microbe/transform_utils/metatraits/mappings/`:

**phenotype_mappings.tsv** (9 mappings):
- gram positive → METPO:1000606
- gram negative → METPO:1000607
- sporulation → METPO:1000614 (endospore-forming)
- obligate aerobic → METPO:1000616
- obligate anaerobic → METPO:1000870
- presence of motility → METPO:1002005
- voges-proskauer test → METPO:1005017
- psychrophilic → METPO:1000660
- thermophilic → METPO:1000656

**chemical_mappings.tsv** (7 mappings):
- produces: ethanol → CHEBI:16236
- produces: hydrogen sulfide → CHEBI:16136
- produces: indole → CHEBI:16881
- produces: methane from acetate → CHEBI:16183
- produces: siderophore → CHEBI:26672
- carbon source: acetate → CHEBI:30089
- carbon source: ethanol → CHEBI:16236

**enzyme_mappings.tsv** (5 mappings):
- enzyme activity: catalase (EC1.11.1.6) → EC:1.11.1.6
- enzyme activity: beta-galactosidase (EC3.2.1.23) → EC:3.2.1.23
- enzyme activity: urease (EC3.5.1.5) → EC:3.5.1.5
- enzyme activity: oxidase → GO:0016491
- enzyme activity: lipase → EC:3.1.1.3

**pathway_mappings.tsv** (4 mappings):
- fermentation → GO:0006113
- nitrogen fixation → GO:0009399
- denitrification pathway → GO:0019333
- nitrification → GO:0019329

### 2. METPO Ontology Integration (Tier 1.5)
Loaded from: https://github.com/berkeleybop/metpo (tag: 2025-12-12)

**METPO Classes Sheet:** Contains ontology terms with synonyms
**METPO Properties Sheet:** Contains predicates with biolink equivalents

The transform uses `load_metpo_mappings()` to:
1. Build METPO tree structure from classes sheet
2. Map trait synonyms to METPO terms
3. Find appropriate predicates by traversing parent hierarchy

### 3. Pattern-Based Chemical Resolvers (Tier 2)

**`_resolve_chemical_trait()` patterns:**
- `carbon source: <chemical>` → METPO:2000006 (uses as carbon source)
- `produces: <chemical>` → METPO:2000202 (produces)
- `ferments: <chemical>` → METPO:2000011 (ferments)
- `hydrolyzes: <chemical>` → METPO:2000013 (hydrolyzes)
- `oxidizes: <chemical>` → METPO:2000016 (oxidizes)
- `reduces: <chemical>` → METPO:2000017 (reduces)
- `degrades: <chemical>` → METPO:2000007 (degrades)
- `utilizes: <chemical>` → METPO:2000001 (organism interacts with chemical)

**`_resolve_metabolic_trait()` patterns:**
- `electron acceptor: <chemical>` → METPO:2000008 (uses as electron acceptor)
- `respiration: <chemical>` → METPO:2000008 (respiration uses electron acceptor)
- `reduction: <chemical>` → METPO:2000017 (reduces)
- `oxidation: <chemical>` → METPO:2000016 (oxidizes)
- `degradation: <material>` → METPO:2000007 (degrades)
- `hydrolysis: <material>` → METPO:2000013 (hydrolyzes)

## Unmapped Trait Categories (Frequency Analysis)

| Category | Count | Should Map To | Notes |
|----------|-------|---------------|-------|
| assimilation | 266 | CHEBI | Need new METPO predicate for "assimilates" |
| energy source | 97 | CHEBI | Need new METPO predicate for "uses as energy source" |
| produces | 79 | CHEBI | Pattern resolver exists (METPO:2000202) |
| fermentation | 77 | CHEBI | Pattern resolver exists (METPO:2000011) |
| nitrogen source | 57 | CHEBI | Need METPO predicate (possibly METPO:2000014) |
| enzyme activity | 53 | EC/GO | Map to EC numbers when available, else GO MF |
| electron donor | 53 | CHEBI | Need new METPO predicate for "uses as electron donor" |
| builds acid from | 28 | CHEBI | Need new METPO predicate for acid production |
| carbon source | 27 | CHEBI | Pattern resolver exists (METPO:2000006) |
| growth | 25 | METPO/Mixed | Phenotypic conditions (media, temperature, pH) |
| required for growth | 22 | CHEBI/METPO | Need METPO predicate for "requires for growth" |
| builds gas from | 16 | CHEBI | Need new METPO predicate for gas production |
| degradation | 12 | CHEBI/ENVO | Pattern resolver exists (METPO:2000007) |
| hydrolysis | 9 | CHEBI | Pattern resolver exists (METPO:2000013) |
| aerobic catabolization | 9 | CHEBI | Need METPO predicate for aerobic catabolism |
| builds base from | 7 | CHEBI | Need new METPO predicate for base production |
| respiration | 6 | CHEBI | Pattern resolver exists (METPO:2000008) |
| reduction | 5 | CHEBI | Pattern resolver exists (METPO:2000017) |
| oxidation | 5 | CHEBI | Pattern resolver exists (METPO:2000016) |
| utilizes | 4 | CHEBI | Pattern resolver exists (METPO:2000001) |
| electron acceptor | 4 | CHEBI | Pattern resolver exists (METPO:2000008) |
| anaerobic catabolization | 4 | CHEBI | Need METPO predicate for anaerobic catabolism |
| sulfur source | 2 | CHEBI | Need METPO predicate for sulfur source |
| **Phenotypic traits** | **~35** | **METPO** | See below |

## High-Priority METPO Phenotypic Traits (Need New Mappings)

These are truly phenotypic traits that should be in METPO ontology:

### Morphological Characteristics
- `cell shape` - fundamental morphology (rod, coccus, spiral, etc.)
- `cell length`, `cell length minimum`, `cell length maximum` - size measurements
- `cell width`, `cell width minimum`, `cell width maximum` - size measurements
- `cell color` - pigmentation
- `cell color: yellow pigment` - specific pigmentation
- `flagellum arrangement` - structural characteristic (peritrichous, monotrichous, etc.)

### Genomic Qualities
- `GC percentage` - GC content (key taxonomic/phenotypic marker)
- `genome size` - total genome size
- `gene count` - total gene count
- `estimated genome size` - predicted genome size
- `estimated gene count` - predicted gene count
- `coding density` - percentage of genome coding for proteins

### Environmental Tolerances
- `oxygen preference` - aerobe/anaerobe/facultative classification
- `pH growth`, `pH minimum`, `pH maximum`, `pH preference` - pH tolerance
- `temperature growth`, `temperature minimum`, `temperature maximum`, `temperature preference` - temperature tolerance
- `salinity growth`, `salinity minimum`, `salinity maximum`, `salinity preference` - salinity tolerance

### Biochemical Tests
- `indole test` - tryptophanase activity test
- `methyl red test` - mixed acid fermentation test
- `presence of hemolysis` - ability to lyse red blood cells

### Growth Characteristics
- `growth: MacConkey agar` - growth on selective media
- `growth: blood agar` - growth on enriched media
- `growth: bile acid susceptible` - susceptibility to bile acids
- `growth: 42 degrees Celsius` - specific temperature growth
- `growth: 6.5% NaCl` - specific salinity growth

### Risk Assessment
- `biosafety level` - BSL classification (1-4)

## Missing METPO Predicates

These metabolic process types need new METPO predicate terms:

1. **`assimilates`** (266 traits) - uptake and incorporation of nutrients
   - Example: "assimilation: glucose"
   - Current gap: No METPO predicate for assimilation

2. **`uses as energy source`** (97 traits) - energy metabolism
   - Example: "energy source: acetate"
   - Current gap: Distinct from carbon source or electron donor

3. **`uses as nitrogen source`** (57 traits) - nitrogen metabolism
   - Example: "nitrogen source: ammonia"
   - Possible: METPO:2000014 may already exist

4. **`uses as electron donor`** (53 traits) - electron donor in respiration
   - Example: "electron donor: dihydrogen"
   - Current gap: Only electron acceptor (METPO:2000008) exists

5. **`produces acid from`** (28 traits) - acid production from substrate
   - Example: "builds acid from: glucose"
   - Current gap: Specific metabolic outcome

6. **`produces gas from`** (16 traits) - gas production from substrate
   - Example: "builds gas from: glucose"
   - Current gap: Specific metabolic outcome

7. **`produces base from`** (7 traits) - base production from substrate
   - Example: "builds base from: acetate"
   - Current gap: Specific metabolic outcome

8. **`aerobically catabolizes`** (9 traits) - aerobic breakdown
   - Example: "aerobic catabolization: 2-oxoglutarate"
   - Current gap: Specific metabolic mode

9. **`anaerobically catabolizes`** (4 traits) - anaerobic breakdown
   - Example: "anaerobic catabolization: acetate"
   - Current gap: Specific metabolic mode

10. **`uses as sulfur source`** (2 traits) - sulfur metabolism
    - Example: "sulfur source: cysteine"
    - Current gap: Specific nutrient source

11. **`requires for growth`** (22 traits) - essential growth factors
    - Example: "required for growth: biotin"
    - Current gap: Requirement vs. utilization

## Why These Unmapped Traits Remain

### Chemical Traits (83% of unmapped)
Most unmapped traits are chemical metabolic traits that:
1. **Have pattern resolvers** but the chemical name lookup fails in ChEBI
   - Example: "assimilation: 3-O-methyl alpha-D-glucopyranoside" - complex name
   - Example: "produces: poly-beta-hydroxyalkanoate" - polymer name
2. **Need new METPO predicates** (see list above)
   - Example: "assimilation: glucose" - no METPO predicate for "assimilates"
   - Example: "energy source: acetate" - no METPO predicate for energy source

### Phenotypic Traits (4% of unmapped)
Not yet in METPO ontology or manual mappings:
- Environmental tolerances (pH, temperature, salinity ranges)
- Morphological measurements (cell size dimensions)
- Genomic qualities (GC%, genome size, gene count)
- Biochemical tests (indole, methyl red, hemolysis)

### Enzyme Activities (6% of unmapped)
Missing EC numbers or GO terms:
- Example: "enzyme activity: alanine aminopeptidase" - no EC number in trait name
- Example: "enzyme activity: beta-galactopyranosidase" - variant spelling

## Recommendations

### 1. Immediate Actions (Manual Mappings)
Add to `phenotype_mappings.tsv`:
```tsv
cell shape	cell shape	METPO:XXXXXXX	cell shape	METPO	skos:exactMatch	high	semapv:ManualMappingCuration	[curator]	metatraits	biolink:has_phenotype
GC percentage	gc percentage	METPO:XXXXXXX	GC content	METPO	skos:exactMatch	high	semapv:ManualMappingCuration	[curator]	metatraits	biolink:has_phenotype
```
(Once METPO terms exist for these)

### 2. METPO Ontology Enhancement
Request new METPO terms for:
- Morphological measurements (cell dimensions, shape variants)
- Environmental tolerance ranges (pH, temperature, salinity min/max/preference)
- Genomic qualities (GC%, genome size, gene count, coding density)
- Biochemical test results (indole, methyl red, hemolysis)
- Growth characteristics (media-specific, condition-specific)

### 3. METPO Predicate Enhancement
Request new METPO predicate terms for:
- `assimilates` (METPO:2000XXX)
- `uses as energy source` (METPO:2000XXX)
- `uses as electron donor` (METPO:2000XXX)
- `produces acid from` (METPO:2000XXX)
- `produces gas from` (METPO:2000XXX)
- `produces base from` (METPO:2000XXX)
- `aerobically catabolizes` (METPO:2000XXX)
- `anaerobically catabolizes` (METPO:2000XXX)
- `requires for growth` (METPO:2000XXX)
- `uses as sulfur source` (METPO:2000XXX)

### 4. Pattern Resolver Enhancement
Extend `_resolve_chemical_trait()` once new predicates exist:
```python
patterns = [
    (r"^assimilation:\s*(.+)$", "METPO:2000XXX"),  # assimilates
    (r"^energy source:\s*(.+)$", "METPO:2000XXX"),  # uses as energy source
    (r"^nitrogen source:\s*(.+)$", "METPO:2000014"),  # uses as nitrogen source
    (r"^electron donor:\s*(.+)$", "METPO:2000XXX"),  # uses as electron donor
    (r"^builds acid from:\s*(.+)$", "METPO:2000XXX"),  # produces acid from
    (r"^builds gas from:\s*(.+)$", "METPO:2000XXX"),  # produces gas from
    (r"^builds base from:\s*(.+)$", "METPO:2000XXX"),  # produces base from
    (r"^aerobic catabolization:\s*(.+)$", "METPO:2000XXX"),  # aerobically catabolizes
    (r"^anaerobic catabolization:\s*(.+)$", "METPO:2000XXX"),  # anaerobically catabolizes
    (r"^required for growth:\s*(.+)$", "METPO:2000XXX"),  # requires for growth
    (r"^sulfur source:\s*(.+)$", "METPO:2000XXX"),  # uses as sulfur source
]
```

### 5. ChEBI Lookup Improvement
Many chemical names fail lookup due to:
- Variant naming (e.g., "D-salicin" vs "salicin")
- Stereochemistry notation (e.g., "(R)-lactate")
- Complex systematic names (e.g., "3-O-methyl alpha-D-glucopyranoside")

Consider:
- Synonym expansion in ChEBI lookup
- Name normalization (remove stereochemistry markers for broad match)
- Fallback to parent compounds

### 6. Enzyme Activity Mapping
For the 53 unmapped enzyme activities:
- Extract EC numbers when present in trait name
- Map enzyme names to EC database
- Fallback to GO molecular function terms
- Consider UniProt enzyme name synonyms

## Files Generated

1. **`additional_metpo_mappings.tsv`** - Categorized analysis of unmapped traits with mapping recommendations
2. **`METATRAITS_UNMAPPED_ANALYSIS.md`** - This comprehensive analysis document

## Next Steps

1. Review with METPO ontology team for new term requests
2. Add high-priority phenotypic mappings once METPO terms are available
3. Implement new pattern resolvers once METPO predicates are added
4. Improve ChEBI chemical name lookup for complex names
5. Consider frequency-based prioritization for chemical trait mapping
