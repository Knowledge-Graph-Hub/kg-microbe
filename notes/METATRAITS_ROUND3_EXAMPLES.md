# MetaTraits Round 3 - Mapping Examples

This document shows concrete examples of traits that are now mapped by the Round 3 enhancements.

## Metabolic Process Resolver (Tier 1.6)

### Electron Acceptors
```
Input:  "electron acceptor: sulfate"
Output: NCBITaxon:X → METPO:2000008 (uses as electron acceptor) → CHEBI:16189 (sulfate)

Input:  "electron acceptor: elemental sulfur"
Output: NCBITaxon:X → METPO:2000008 → CHEBI:26833 (sulfur)

Input:  "electron acceptor: nitrate"
Output: NCBITaxon:X → METPO:2000008 → CHEBI:17632 (nitrate)
```

### Respiration
```
Input:  "respiration: nitrogen"
Output: NCBITaxon:X → METPO:2000008 (uses as electron acceptor) → CHEBI:49637 (dinitrogen)

Input:  "respiration: iron"
Output: NCBITaxon:X → METPO:2000008 → CHEBI:18248 (iron atom)
```

### Reduction
```
Input:  "reduction: nitrate"
Output: NCBITaxon:X → METPO:2000017 (reduces) → CHEBI:17632 (nitrate)

Input:  "reduction: elemental sulfur"
Output: NCBITaxon:X → METPO:2000017 → CHEBI:26833 (sulfur)
```

### Oxidation
```
Input:  "oxidation: methanol"
Output: NCBITaxon:X → METPO:2000016 (oxidizes) → CHEBI:17790 (methanol)

Input:  "oxidation: ammonia"
Output: NCBITaxon:X → METPO:2000016 → CHEBI:16134 (ammonia)

Input:  "oxidation in darkness: sulfur"
Output: NCBITaxon:X → METPO:2000016 → CHEBI:26833 (sulfur)
```

### Denitrification
```
Input:  "denitrification: nitrate"
Output: NCBITaxon:X → METPO:2000017 (reduces) → CHEBI:17632 (nitrate)

Input:  "denitrification: nitrite"
Output: NCBITaxon:X → METPO:2000017 → CHEBI:16301 (nitrite)

Input:  "denitrification: nitrous oxide"
Output: NCBITaxon:X → METPO:2000017 → CHEBI:17045 (nitrous oxide)
```

### Ammonification
```
Input:  "ammonification: nitrate"
Output: NCBITaxon:X → METPO:2000014 (uses as nitrogen source) → CHEBI:17632 (nitrate)
```

### Degradation
```
Input:  "degradation: cellulose"
Output: NCBITaxon:X → METPO:2000007 (degrades) → CHEBI:18246 (cellulose)

Input:  "degradation: lignin"
Output: NCBITaxon:X → METPO:2000007 → CHEBI:6457 (lignin)

Input:  "degradation: plastic"
Output: NCBITaxon:X → METPO:2000007 → ENVO:01000481 (plastic)

Input:  "degradation: chitin"
Output: NCBITaxon:X → METPO:2000007 → CHEBI:17029 (chitin)
```

### Hydrolysis
```
Input:  "hydrolysis: urea"
Output: NCBITaxon:X → METPO:2000013 (hydrolyzes) → CHEBI:16199 (urea)

Input:  "hydrolysis: starch"
Output: NCBITaxon:X → METPO:2000013 → CHEBI:28017 (starch)

Input:  "hydrolysis: esculin"
Output: NCBITaxon:X → METPO:2000013 → CHEBI:4806 (esculin)

Input:  "hydrolysis: casein"
Output: NCBITaxon:X → METPO:2000013 → KGM:casein (casein - custom)

Input:  "hydrolysis: gelatin"
Output: NCBITaxon:X → METPO:2000013 → KGM:gelatin (gelatin - custom)
```

**Expected impact:** ~2M observations mapped

---

## Growth Substrate Resolver (Tier 1.7)

### Growth Substrates
```
Input:  "growth: cellobiose"
Output: NCBITaxon:X → METPO:2000012 (uses for growth) → CHEBI:17057 (cellobiose)

Input:  "growth: D-mannitol"
Output: NCBITaxon:X → METPO:2000012 → CHEBI:16899 (D-mannitol)

Input:  "growth: L-arabinose"
Output: NCBITaxon:X → METPO:2000012 → CHEBI:28061 (L-arabinose)

Input:  "growth: raffinose"
Output: NCBITaxon:X → METPO:2000012 → CHEBI:16634 (raffinose)

Input:  "growth: glycerol"
Output: NCBITaxon:X → METPO:2000012 → CHEBI:17754 (glycerol)
```

### Acid Production
```
Input:  "builds acid from: glucose"
Output: NCBITaxon:X → METPO:2000003 (builds acid from) → CHEBI:17234 (glucose)

Input:  "builds acid from: lactose"
Output: NCBITaxon:X → METPO:2000003 → CHEBI:17716 (lactose)
```

**Expected impact:** ~1M observations mapped

---

## Trophic Mode Resolver (Tier 1.8)

### Trophic Modes
```
Input:  "growth: phototrophy"
Output: NCBITaxon:X → METPO:2000103 (capable of) → GO:0009579 (phototrophic process)

Input:  "growth: chemoheterotrophy"
Output: NCBITaxon:X → METPO:2000103 → GO:0044281 (small molecule metabolic process)

Input:  "growth: photoautotrophy"
Output: NCBITaxon:X → METPO:2000103 → GO:0009541 (photoautotrophic process)

Input:  "growth: photoheterotrophy"
Output: NCBITaxon:X → METPO:2000103 → GO:0009581 (photoheterotrophic process)

Input:  "growth: anoxygenic photoautotrophy"
Output: NCBITaxon:X → METPO:2000103 → GO:0019685 (photosynthesis, anoxygenic)
```

### Aerobic/Anaerobic Growth
```
Input:  "aerobic growth: chemoheterotrophy"
Output: NCBITaxon:X → METPO:2000102 (has phenotype) → METPO:1001003 (aerobe)

Input:  "aerobic growth: anoxygenic phototrophy"
Output: NCBITaxon:X → METPO:2000102 → METPO:1001003 (aerobe)

Input:  "anaerobic growth: fermentation"
Output: NCBITaxon:X → METPO:2000102 → METPO:1001004 (anaerobe)
```

**Expected impact:** ~350K observations mapped

---

## Enzyme Activity Resolver (Tier 1.9)

### EC-Numbered Enzymes
```
Input:  "enzyme activity: alkaline phosphatase (EC3.1.3.1)"
Output: NCBITaxon:X → METPO:2000302 (shows activity of) → EC:3.1.3.1 (alkaline phosphatase)
        Category: biolink:MolecularActivity

Input:  "enzyme activity: arginine dihydrolase (EC3.5.3.6)"
Output: NCBITaxon:X → METPO:2000302 → EC:3.5.3.6 (arginine dihydrolase)

Input:  "enzyme activity: lysine decarboxylase (EC4.1.1.18)"
Output: NCBITaxon:X → METPO:2000302 → EC:4.1.1.18 (lysine decarboxylase)

Input:  "enzyme activity: ornithine decarboxylase (EC4.1.1.17)"
Output: NCBITaxon:X → METPO:2000302 → EC:4.1.1.17 (ornithine decarboxylase)
```

### Non-EC Enzymes (falls through to existing mappings)
```
Input:  "enzyme activity: DNase"
Output: [Falls through to METPO trait_mapping or unmapped]

Input:  "enzyme activity: coagulase"
Output: [Falls through to METPO trait_mapping or unmapped]
```

**Expected impact:** ~170K observations mapped (EC-numbered only)

---

## Phenotype Resolver (Tier 2.0)

### Simple Phenotypes
```
Input:  "aerotolerant"
Output: NCBITaxon:X → METPO:2000102 (has phenotype) → METPO:1001025 (aerotolerant)
        Category: biolink:PhenotypicQuality

Input:  "facultative anaerobe"
Output: NCBITaxon:X → METPO:2000102 → METPO:1001026 (facultative anaerobe)

Input:  "acidophilic"
Output: NCBITaxon:X → METPO:2000102 → METPO:1001015 (acidophile)

Input:  "capnophilic"
Output: NCBITaxon:X → METPO:2000102 → KGM:capnophilic (capnophilic - custom)
```

**Expected impact:** ~90K observations mapped

---

## Summary Statistics (Expected)

### Patterns Resolved by Tier
- **Tier 1.6** (Metabolic processes): ~2,000,000 observations
- **Tier 1.7** (Growth substrates): ~1,000,000 observations
- **Tier 1.8** (Trophic modes): ~350,000 observations
- **Tier 1.9** (Enzyme activities): ~170,000 observations
- **Tier 2.0** (Phenotypes): ~90,000 observations

**Total expected:** ~3,610,000 observations mapped (71.5% reduction from 5,051,076)

### New Namespaces in KG
- **CHEBI:** +100-200 new chemicals (electron acceptors, substrates, degradation targets)
- **EC:** +20-30 new enzyme activities (molecular activities)
- **GO:** +6 new biological processes (trophic modes)
- **METPO:** +4 new phenotypes (aerotolerant, facultative, acidophile, aerobe/anaerobe)

### New Predicates in Use
1. METPO:2000003 - builds acid from
2. METPO:2000008 - uses as electron acceptor ⭐ (high frequency)
3. METPO:2000014 - uses as nitrogen source
4. METPO:2000016 - oxidizes (extended usage)
5. METPO:2000017 - reduces (extended usage)

---

## Edge Statistics (Expected)

**Before Round 3:**
- Total edges: 1,048,641
- Unique predicates: ~15-20

**After Round 3:**
- Total edges: ~1,400,000-1,600,000 (+350K-550K, +33-52%)
- Unique predicates: ~25-30 (+5-10 new predicates in active use)

**New edge types:**
- Taxon → uses as electron acceptor → Chemical (sulfate, nitrate, etc.)
- Taxon → oxidizes → Chemical (methanol, ammonia, sulfur, etc.)
- Taxon → reduces → Chemical (nitrate, nitrite, sulfur, etc.)
- Taxon → degrades → Material (cellulose, lignin, plastic, chitin)
- Taxon → hydrolyzes → Material (urea, starch, esculin, casein)
- Taxon → uses for growth → Chemical (carbohydrates, organic acids)
- Taxon → builds acid from → Chemical (sugars)
- Taxon → capable of → BiologicalProcess (phototrophy, chemoheterotrophy)
- Taxon → has phenotype → Phenotype (aerotolerant, facultative anaerobe)
- Taxon → shows activity of → MolecularActivity (EC-numbered enzymes)

---

## Verification Commands

```bash
# Count new METPO:2000008 (electron acceptor) edges
grep "METPO:2000008" data/transformed/metatraits/edges.tsv | wc -l

# Count new METPO:2000003 (builds acid from) edges
grep "METPO:2000003" data/transformed/metatraits/edges.tsv | wc -l

# Count new METPO:2000014 (nitrogen source) edges
grep "METPO:2000014" data/transformed/metatraits/edges.tsv | wc -l

# Count EC: edges (enzyme activities)
grep "^[^\t]*\t[^\t]*\tEC:" data/transformed/metatraits/edges.tsv | wc -l

# Count GO: edges (trophic modes)
grep "GO:" data/transformed/metatraits/edges.tsv | wc -l

# Show all unique predicates
cut -f2 data/transformed/metatraits/edges.tsv | sort -u

# Show predicate frequency distribution
cut -f2 data/transformed/metatraits/edges.tsv | tail -n +2 | sort | uniq -c | sort -rn
```
