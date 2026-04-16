# METPO Proposals Summary

**Date**: 2026-03-28
**Status**: REVISED to use predicate-based patterns

---

## Approach Change

**Original approach** (DEPRECATED): Create 114 new METPO classes (95 fermentation + 16 electron acceptor + 3 quantitative)

**Corrected approach** (CURRENT): Use existing METPO predicates + 9 new data properties

**Rationale**: METPO supports predicate-based patterns where organisms link directly to chemicals via specific predicates (e.g., `NCBITaxon:562 --METPO:2000011--> CHEBI:17234` for "E. coli ferments glucose"), rather than creating separate capability classes for each substrate.

---

## Current Proposals

### 1. Fermentation Traits → Use Existing Predicate ✅

**Pattern**: `organism --METPO:2000011 (ferments)--> CHEBI:substrate`

**Files**:
- ✅ `mappings/fermentation_trait_to_chebi.tsv` - Maps 46 fermentation traits to CHEBI IDs
- ⚠️ Remaining 49 "other fermentable compounds" need CHEBI mapping completion

**Implementation**: No new METPO terms needed - just use existing `METPO:2000011` predicate

**Coverage**: 95 traits (~7,500 occurrences)

---

### 2. Electron Acceptor Traits → Use Existing Predicate ✅

**Pattern**: `organism --METPO:2000008 (uses as electron acceptor)--> CHEBI:acceptor`

**Files**:
- ✅ `mappings/electron_acceptor_trait_to_chebi.tsv` - Maps 13 electron acceptor compounds to CHEBI IDs

**Implementation**: No new METPO terms needed - just use existing `METPO:2000008` predicate

**Coverage**: 2-5 traits (99,551 occurrences, including high-priority "sulfur compounds" with 99,543)

---

### 3. Quantitative Properties → NEW Data Properties Required 🆕

**Pattern**: Attach data properties directly to organism nodes

**Proposal**: 9 new data properties
1. `METPO:has_growth_temperature_optimum` (xsd:decimal, UO:0000027 Celsius)
2. `METPO:has_growth_temperature_minimum`
3. `METPO:has_growth_temperature_maximum`
4. `METPO:has_NaCl_concentration_optimum` (xsd:decimal, UO:0000187 percent)
5. `METPO:has_NaCl_concentration_minimum`
6. `METPO:has_NaCl_concentration_maximum`
7. `METPO:has_pH_optimum` (xsd:decimal, pH scale 0-14)
8. `METPO:has_pH_minimum`
9. `METPO:has_pH_maximum`

**Files**:
- ✅ `mappings/metpo_predicate_based_proposal.tsv` - Formal proposal for 9 data properties

**Implementation**: Requires METPO maintainer approval and ID assignment

**Coverage**: 3 trait types (176,101 occurrences)

**Example Usage**:
```turtle
NCBITaxon:1392 a biolink:OrganismTaxon ;
    rdfs:label "Bacillus anthracis" ;
    METPO:has_growth_temperature_optimum "35.0"^^xsd:decimal ;
    METPO:has_NaCl_concentration_optimum "0.5"^^xsd:decimal ;
    METPO:has_pH_optimum "7.0"^^xsd:decimal ;
    .
```

---

## Files Status

### Active Proposal Files (Use These)
1. ✅ **`docs/METPO_PREDICATE_BASED_IMPLEMENTATION.md`** - Implementation guide
2. ✅ **`mappings/metpo_predicate_based_proposal.tsv`** - 9 data properties for METPO submission
3. ✅ **`mappings/fermentation_trait_to_chebi.tsv`** - Fermentation substrate mappings
4. ✅ **`mappings/electron_acceptor_trait_to_chebi.tsv`** - Electron acceptor mappings

### Deprecated Files (Class-Based Approach - Do Not Use)
- ❌ `docs/METPO_NEW_TERMS_PROPOSAL.md` - Contains OWL class definitions (deprecated approach)
- ❌ `mappings/metpo_fermentation_proposal.tsv` - 46 fermentation capability classes (not needed)
- ❌ `mappings/metpo_electron_acceptor_proposal.tsv` - 16 electron acceptor classes (not needed)
- ❌ `mappings/metpo_quantitative_proposal.tsv` - Old format (superseded by predicate_based_proposal.tsv)

---

## Summary of Changes Required

| Change Type | Count | Implementation Complexity | Status |
|-------------|-------|---------------------------|--------|
| **New METPO classes** | 0 | N/A | Not needed |
| **New METPO data properties** | 9 | LOW (formal proposal needed) | Pending METPO maintainer |
| **New mapping files** | 2 | LOW (TSV files ready) | Complete |
| **Transform code updates** | 2 transforms | MEDIUM (metatraits + metatraits_gtdb) | Not started |

---

## Next Steps

### Immediate (Week 1)
1. ✅ Complete fermentation_trait_to_chebi.tsv with remaining 49 substrates
2. ✅ Validate all CHEBI IDs exist in current ChEBI release
3. 🔲 Submit 9 data property proposal to METPO GitHub

### Short-term (Week 2-3)
4. 🔲 Wait for METPO maintainer review and ID assignment
5. 🔲 Update metatraits transforms to use mapping files and predicates
6. 🔲 Test with sample data

### Medium-term (Week 4+)
7. 🔲 Run full metatraits transforms with new mappings
8. 🔲 Validate edge counts and data property coverage
9. 🔲 Measure impact: expect ~18% reduction in unmapped traits

---

## Coverage Impact

| Solution | Traits | Occurrences | % of Unmapped | Status |
|----------|--------|-------------|---------------|--------|
| Fermentation predicate | 95 | ~7,500 | 0.6% | Mapping ready |
| Electron acceptor predicate | 2-5 | 99,551 | 8.6% | Mapping ready |
| Quantitative properties | 3 | 176,101 | 15.1% | Proposal ready |
| **Total** | **~100** | **~283,000** | **24.3%** | **Implementation pending** |

---

## References

- Implementation guide: `docs/METPO_PREDICATE_BASED_IMPLEMENTATION.md`
- METPO predicates: `docs/METPO_PREDICATES.md`
- Unmapped traits analysis: `docs/UNMAPPED_TRAITS_ONTOLOGY_ANALYSIS.md`
- METPO GitHub: https://github.com/berkeleybop/metpo
