# METPO Proposal Executive Summary
## Phases 1, 2, 3: KG-Microbe MetaTraits Integration

**Date:** 2026-04-03  
**Status:** Ready for METPO GitHub submission  
**Contact:** KG-Microbe Project Team  

---

## The Ask

Request **44 new METPO terms** to enable comprehensive microbial trait data integration from BacDive.

| Phase | Term Type | Count | Priority |
|-------|-----------|-------|----------|
| **1** | Data Properties (Quantitative) | 9 | CRITICAL |
| **2** | Object Properties (Metabolic) | 4 | CRITICAL |
| **3** | Classes (Phenotypic) | 31 | HIGH |
| **TOTAL** | | **44** | **CRITICAL-HIGH** |

---

## The Impact

### Coverage Improvement
- **Traits resolved:** 514+ unmapped traits → mapped (57% reduction in unmapped)
- **Observations mapped:** ~700,000 additional observations (14% increase in coverage)
- **Data sources enabled:** BacDive (85,000+ taxa), GTDB taxonomy

### What This Enables

#### Phase 1: Quantitative Growth Modeling (176K observations)
✅ Optimal growth conditions for biotechnology (temperature, pH, salinity)  
✅ Environmental niche prediction for ecology  
✅ Culture condition optimization for industry  

**Example:** "Find thermophiles with optimum >60°C that tolerate pH 3-5"

#### Phase 2: Metabolic Pathway Completeness (495K observations)
✅ Nutrient assimilation vs. fermentation distinction  
✅ Energy source vs. carbon source modeling  
✅ Complete electron transport chains (donor + acceptor)  

**Example:** "Find organisms that use H₂ as electron donor and SO₄²⁻ as acceptor"

#### Phase 3: Basic Microbiology Characterization (26K observations)
✅ Cell morphology (shape, size, color) for identification  
✅ Genomic properties (GC%, genome size) for taxonomy  
✅ Biochemical tests (indole, MR, hemolysis) for diagnostics  

**Example:** "Find rod-shaped organisms with GC% >65% and indole positive"

---

## The Details

### Phase 1: Quantitative Data Properties (9 terms)

| Property Group | Properties | Example Value | Observations |
|----------------|-----------|---------------|--------------|
| **Temperature** | optimum, min, max | 37.0°C | 85,311 |
| **Salinity** | optimum, min, max | 0.5% NaCl | 85,311 |
| **pH** | optimum, min, max | 7.0 | 5,479 |

**Why:** METPO has qualitative terms (thermophile, halophile) but no quantitative measurements. Industry needs precise values.

**Usage:**
```turtle
NCBITaxon:562 METPO:has_growth_temperature_optimum "37.0"^^xsd:decimal .
```

---

### Phase 2: Metabolic Process Predicates (4 terms)

| Predicate | Traits | Example | Why Needed |
|-----------|--------|---------|------------|
| **assimilates** | 266 | glucose | Broader than carbon source (includes all nutrients) |
| **uses as energy source** | 97 | acetate | Distinct from carbon (ATP vs biomass) |
| **uses as nitrogen source** | 57 | ammonia | Biosynthetic nitrogen incorporation |
| **uses as electron donor** | 53 | H₂ | Complements existing electron acceptor |

**Why:** Current METPO lacks fundamental metabolic distinctions critical for pathway modeling.

**Usage:**
```turtle
NCBITaxon:562 METPO:2000021 CHEBI:17234 .  # E. coli assimilates glucose
NCBITaxon:562 METPO:2000022 CHEBI:30089 .  # E. coli uses acetate as energy source
```

---

### Phase 3: Phenotypic Quality Classes (31 terms)

| Category | Count | Examples | Why Needed |
|----------|-------|----------|------------|
| **Morphological** | 5 | cell shape, length, width, color, flagella | Taxonomic identification |
| **Genomic** | 4 | GC%, genome size, gene count | Taxonomic markers |
| **Environmental** | 12 | O₂ requirement, pH/temp/salinity ranges | Niche modeling |
| **Biochemical** | 3 | indole, methyl red, hemolysis | Diagnostic tests |
| **Growth** | 3 | selective media, bile resistance, BSL | Culture collection metadata |

**Why:** Standard microbiology characterization traits missing from METPO.

**Usage:**
```turtle
NCBITaxon:562 METPO:2000102 METPO:1007001 .  # E. coli has phenotype: rod-shaped
```

---

## Comparison to Current METPO

| Metric | Current METPO | After Phases 1-3 | Change |
|--------|---------------|------------------|--------|
| Total terms | ~168 | ~212 | +44 (+26%) |
| Data properties | ~10 | 19 | +9 (+90%) |
| Object properties | ~51 | 55 | +4 (+8%) |
| Classes | ~107 | 138 | +31 (+29%) |
| Quantitative support | Limited | Comprehensive | **NEW** |
| Metabolic specificity | Good | Excellent | **Enhanced** |

---

## Key Distinctions from Existing METPO

### Not Duplicates - These Fill Gaps:

1. **Assimilates** ≠ Carbon Source
   - Carbon source = specifically for biomass carbon
   - Assimilates = ANY nutrient uptake/incorporation

2. **Energy Source** ≠ Carbon Source
   - Carbon source = biosynthetic building blocks
   - Energy source = ATP/energy generation

3. **Electron Donor** ≠ Electron Acceptor
   - Acceptor already exists (METPO:2000008)
   - Donor is the complement (NEW)

4. **Quantitative Properties** ≠ Qualitative Phenotypes
   - Thermophile = qualitative classification
   - has_growth_temperature_optimum = precise measurement

---

## Industry Relevance

### Biotechnology Applications
- **Strain selection:** "Find organisms with temp optimum 80°C that produce acetone"
- **Scale-up:** Precise pH/temperature/salinity requirements for fermenters
- **Quality control:** Morphology and biochemical test validation

### Research Applications
- **Systems biology:** Complete metabolic network reconstruction
- **Ecology:** Environmental niche prediction and distribution modeling
- **Genomics:** Correlation of genotype (GC%, genome size) with phenotype

### Culture Collections
- **DSMZ, ATCC, JGI:** Standard catalog metadata now mappable to ontology
- **Interoperability:** Machine-readable strain datasheets
- **Search:** "Find all BSL-1 psychrophiles that grow on MacConkey agar"

---

## Implementation Plan

### Timeline (9 weeks)
1. **Weeks 1-2:** METPO maintainer review
2. **Weeks 3-4:** ID assignment
3. **Weeks 5-6:** Transform implementation
4. **Weeks 7-8:** Testing & validation
5. **Week 9:** Documentation & release

### Deliverables
- ✅ Formal proposal document (METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md)
- ✅ Term summary table (metpo_phases_1_2_3_terms.tsv)
- ✅ GitHub issue template (METPO_GITHUB_ISSUE_TEMPLATE.md)
- ⏳ METPO ontology updates (awaiting ID assignment)
- ⏳ KG-Microbe transform code updates
- ⏳ Updated merged knowledge graph

### Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| METPO maintainer bandwidth | Phased approach: prioritize Phase 1+2 (critical) |
| Term definition disagreements | Flexible - happy to revise based on feedback |
| ID conflicts | Suggested ranges; defer to maintainer assignments |
| Scope concerns (e.g., BSL) | Open to excluding regulatory/non-phenotypic terms |

---

## Next Steps

### Immediate (This Week)
1. ✅ Finalize proposal documents
2. ⏳ Internal review with KG-Microbe team
3. ⏳ Submit GitHub issue to METPO repository

### Short-term (Weeks 1-4)
4. ⏳ Respond to METPO maintainer questions
5. ⏳ Revise definitions based on feedback
6. ⏳ Receive ID assignments

### Medium-term (Weeks 5-9)
7. ⏳ Update metatraits transforms
8. ⏳ Regenerate KG-Microbe knowledge graph
9. ⏳ Publish updated graph statistics

---

## Questions?

See full documentation:
- **Detailed proposal:** `METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md`
- **Term table:** `mappings/metpo_phases_1_2_3_terms.tsv`
- **GitHub template:** `METPO_GITHUB_ISSUE_TEMPLATE.md`
- **Unmapped analysis:** `mappings/additional_metpo_mappings.tsv`

Contact: KG-Microbe Project Team  
GitHub: https://github.com/Knowledge-Graph-Hub/kg-microbe

---

## Key Takeaways

### 🎯 The Goal
Enable comprehensive microbial trait representation in knowledge graphs

### 📊 The Numbers
44 new terms → 514 traits mapped → 700K observations covered

### 🔬 The Science
Standard microbiology characterization now ontology-backed

### 🏭 The Value
Industry-ready strain metadata, research-grade metabolic models, culture collection interoperability

### ✅ The Status
**Ready for METPO submission**
