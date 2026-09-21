# Assay Node Evolution Across KG-Microbe Releases

**Date**: 2026-01-12
**Status**: ANALYSIS
**Releases Compared**: 20250222 vs. 20251217

---

## Executive Summary

KG-Microbe has undergone significant changes in how assay data is modeled between the February 2025 and December 2025 releases:

| Aspect | 20250222 (Feb 2025) | 20251217 (Dec 2025) | Change |
|--------|---------------------|---------------------|--------|
| **Deprecated predicates used** | ⚠️ 119,094 `assesses` + 112 `is_assessed_by` | ⚠️ 112 `is_assessed_by` only | Removed 119K assesses edges |
| **Assay nodes** | 428 nodes (`PhenotypicQuality`) | 349 nodes (`NamedThing`) | -79 nodes, category changed |
| **Organism→Assay edges** | ❌ 0 direct edges | ❌ 0 direct edges | No change |
| **Assay→Organism edges** | ✅ 119,094 edges (assesses) | ❌ 0 edges | All removed |
| **Organism→Entity predicates** | Biolink standard | METPO predicates | Major change |
| **Direct organism edges** | ~237K Biolink edges | ~74K METPO edges | Significant reduction |

**Key Finding**: The graph modeling has shifted from using deprecated `biolink:assesses` to METPO predicates, but neither release properly implements organism→assay→entity two-hop paths.

---

## Detailed Comparison

### 1. Deprecated Predicate Usage

#### Release 20250222 (February 2025)

**`biolink:assesses`** - DEPRECATED ⚠️
- **Count**: 119,094 edges
- **Direction**: assay → organism/strain
- **Pattern**: `assay:API_rID32A_alpha_GAL --biolink:assesses--> NCBITaxon:1262`
- **Meaning**: "This assay was performed on this organism"
- **Knowledge source**: bacdive:[record_id]

**Example edges**:
```tsv
subject: assay:API_rID32A_alpha_GAL
predicate: biolink:assesses
object: NCBITaxon:1262
relation: NCIT:C153110 (assessed_activity)
knowledge_source: bacdive:146792
```

**`biolink:is_assessed_by`** - DEPRECATED ⚠️
- **Count**: 112 edges
- **Direction**: EC enzyme → assay
- **Pattern**: `EC:4.1.99.1 --biolink:is_assessed_by--> assay:API_20A_IND`
- **Meaning**: "This enzyme is detected by this assay"
- **Knowledge source**: bacdive_mappings.tsv

#### Release 20251217 (December 2025)

**`biolink:assesses`** - DEPRECATED ⚠️
- **Count**: 0 edges ✅
- **Status**: Removed (no longer used)

**`biolink:is_assessed_by`** - DEPRECATED ⚠️
- **Count**: 112 edges ⚠️
- **Direction**: EC enzyme → assay
- **Pattern**: Same as 20250222
- **Status**: Still present (not yet replaced)

**Progress**: Removed 119,094 deprecated `assesses` edges, but 112 `is_assessed_by` edges remain.

---

### 2. Assay Node Structure

#### Release 20250222

**Count**: 428 assay nodes

**Node structure**:
```tsv
id: assay:API_rID32A_alpha_GAL
category: biolink:PhenotypicQuality
name: API rID32A - alpha GAL
description: (empty)
```

**Characteristics**:
- ✅ Has names (kit + test label)
- ❌ No descriptions
- ⚠️ Category: `biolink:PhenotypicQuality` (questionable choice)
- ❌ No metadata fields (kit_name, well_name, test_type)

**Coverage**: 428 nodes across multiple kits

#### Release 20251217

**Count**: 349 assay nodes

**Node structure**:
```tsv
id: assay:API_zym_Trypsin
category: biolink:NamedThing
name: (empty)
description: (empty)
```

**Characteristics**:
- ❌ No names
- ❌ No descriptions
- ⚠️ Category: `biolink:NamedThing` (too generic)
- ❌ No metadata fields
- ⚠️ 237 orphaned nodes (no edges)

**Coverage**: 349 nodes (79 fewer than 20250222)

**Distribution**:
```
API 50CHas:    49 nodes
API ID32E:     31 nodes
API rID32STR:  29 nodes
API rID32A:    27 nodes
API ID32STA:   26 nodes
[...15 kits total...]
```

**Missing kits** (compared to new metadata):
- API 50CHac (49 wells) - Fermentation tests
- API biotype100 (99 wells) - Growth tests

---

### 3. Organism→Entity Relationships

#### Release 20250222: Direct Edges with Biolink Predicates

**Pattern**: `NCBITaxon → Biolink predicate → GO/EC/ChEBI`

**Predicates used**:
| Predicate | Count | Target | Example |
|-----------|-------|--------|---------|
| `biolink:consumes` | 139,025 | ChEBI | NCBITaxon:296 → CHEBI:27689 |
| `biolink:capable_of` | 65,522 | EC/GO | NCBITaxon:296 → EC:3.5.3.6 |
| `biolink:occurs_in` | 28,838 | Pathways | NCBITaxon → pathways |
| `biolink:associated_with_sensitivity_to` | 9,729 | Compounds | Antibiotic sensitivity |
| `biolink:associated_with_resistance_to` | 5,593 | Compounds | Antibiotic resistance |
| `biolink:produces` | 3,791 | ChEBI | Metabolic products |

**Total**: ~252,000 direct organism→entity edges

**Characteristics**:
- ✅ Uses standard Biolink predicates
- ✅ Compliant with Biolink model (except deprecated assesses)
- ❌ No METPO domain-specific semantics
- ❌ No connection to assay nodes

#### Release 20251217: Direct Edges with METPO Predicates

**Pattern**: `NCBITaxon → METPO predicate → GO/EC/ChEBI`

**Predicates used**:
| Predicate | Count | Meaning (inferred) |
|-----------|-------|-------------------|
| `METPO:2000006` | 36,817 | Metabolizes chemicals |
| `METPO:2000517` | 30,031 | Unknown trait |
| `METPO:2000103` | 7,495 | Capable of enzyme activity |

**Total**: ~74,000 direct organism→entity edges

**Characteristics**:
- ✅ Uses domain-specific METPO predicates
- ✅ Richer biological semantics
- ❌ Not using full range of METPO predicates (only 3 types)
- ❌ No connection to assay nodes
- ⚠️ Significantly fewer edges than 20250222 (~74K vs ~252K)

---

### 4. Graph Structure Comparison

#### Release 20250222 Structure

```
# Assay → Organism (deprecated pattern)
assay:API_rID32A_alpha_GAL --biolink:assesses--> NCBITaxon:1262

# Organism → Entity (direct, no assay)
NCBITaxon:296 --biolink:consumes--> CHEBI:27689
NCBITaxon:296 --biolink:capable_of--> EC:3.5.3.6

# EC → Assay (methodological reference)
EC:4.1.99.1 --biolink:is_assessed_by--> assay:API_20A_IND
```

**Issues**:
- ⚠️ Assay→organism direction is backwards (should be organism→assay)
- ⚠️ Uses deprecated `assesses` predicate (119K edges)
- ⚠️ Uses deprecated `is_assessed_by` predicate (112 edges)
- ❌ Assays don't connect to what they test (GO/EC/ChEBI)

#### Release 20251217 Structure

```
# No Assay → Organism edges (removed)

# Organism → Entity (direct, no assay)
NCBITaxon:693023 --METPO:2000006--> CHEBI:17992
NCBITaxon:28448 --METPO:2000103--> GO:0030245

# EC → Assay (methodological reference)
EC:4.1.99.1 --biolink:is_assessed_by--> assay:API_20A_IND
```

**Improvements**:
- ✅ Removed 119K deprecated `assesses` edges
- ✅ Uses METPO predicates (richer semantics)

**Remaining issues**:
- ⚠️ Still uses deprecated `is_assessed_by` (112 edges)
- ❌ Organisms still don't connect to assay nodes
- ❌ Assay nodes are mostly orphaned
- ⚠️ Only uses 3 METPO predicates (not the full range)

---

### 5. Missing Predicates in Current Releases

The API kit-specific METPO predicates we identified are **NOT** used in either release:

| METPO Predicate | Label | Status in 20250222 | Status in 20251217 |
|-----------------|-------|-------------------|-------------------|
| METPO:2000302 | shows activity of | ❌ Not used | ❌ Not used |
| METPO:2000303 | does not show activity of | ❌ Not used | ❌ Not used |
| METPO:2000011 | ferments | ❌ Not used | ❌ Not used |
| METPO:2000037 | does not ferment | ❌ Not used | ❌ Not used |
| METPO:2000008 | assimilates | ❌ Not used | ❌ Not used |
| METPO:2000034 | does not assimilate | ❌ Not used | ❌ Not used |
| METPO:2000012 | uses for growth | ❌ Not used | ❌ Not used |
| METPO:2000038 | does not use for growth | ❌ Not used | ❌ Not used |

**Instead**, current releases use:
- 20250222: Generic Biolink predicates (consumes, capable_of, produces)
- 20251217: Only 3 generic METPO predicates (2000006, 2000517, 2000103)

---

## What Changed Between Releases?

### Changes from 20250222 → 20251217

1. **Removed 119,094 `biolink:assesses` edges**
   - Assays no longer link to organisms
   - Complies with Biolink v4.3.6 deprecation

2. **Replaced Biolink predicates with METPO predicates**
   - Old: `biolink:consumes`, `biolink:capable_of`, `biolink:produces`
   - New: `METPO:2000006`, `METPO:2000103`, `METPO:2000517`
   - Gained: Domain-specific semantics
   - Lost: ~178K edges (252K → 74K)

3. **Changed assay node categories**
   - Old: `biolink:PhenotypicQuality`
   - New: `biolink:NamedThing`
   - Still wrong (should be `biolink:Procedure`)

4. **Lost assay node metadata**
   - Old: Had names ("API rID32A - alpha GAL")
   - New: No names, no descriptions
   - Regression in data quality

5. **Reduced assay node count**
   - Old: 428 nodes
   - New: 349 nodes
   - Lost: 79 nodes (18% reduction)

6. **Created orphaned assay nodes**
   - Old: 428 nodes all connected via `assesses` edges
   - New: 237 orphaned nodes (68% orphaned)
   - Only 112 nodes used (in `is_assessed_by` edges)

---

## Proposed Future State

Based on our proposal in `docs/ASSAY_NODE_MODELING.md`:

```
# Two-hop path with assay nodes
NCBITaxon:562 --METPO:2000302--> assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035
NCBITaxon:562 --METPO:2000011--> assay:API_50CHac_ERY --biolink:has_input--> CHEBI:17113

# Assay nodes with rich metadata
id: assay:API_zym_alkaline_phosphatase
category: biolink:Procedure
name: API zym - Alkaline phosphatase
description: Tests for Alkaline phosphatase activity using chromogenic substrate
kit_name: API zym
well_name: Alkaline phosphatase
test_type: enzyme
```

**Improvements**:
- ✅ Uses full range of METPO predicates (8 types for different processes)
- ✅ Proper two-hop paths (organism→assay→entity)
- ✅ Assay nodes with rich metadata
- ✅ Correct category (`biolink:Procedure`)
- ✅ All 503 assay wells covered
- ✅ No deprecated predicates

---

## Migration Path

### From 20251217 → Proposed State

1. **Replace 349 outdated assay nodes with 503 new nodes**
   - Add missing kits (biotype100, 50CHac)
   - Change category to `biolink:Procedure`
   - Add rich metadata

2. **Remove 112 `is_assessed_by` edges (EC→assay)**
   - Already documented as replaced with `related_to_at_instance_level`

3. **Add ~50K-100K organism→assay edges**
   - Use kit-specific METPO predicates
   - Direction: organism → assay

4. **Add ~600-800 assay→entity edges**
   - Enzyme assays → GO/EC (`has_output`)
   - Chemical assays → ChEBI (`has_input`)

5. **Decision needed: Keep or remove direct organism→entity edges?**
   - Currently: 74K direct edges with 3 generic METPO predicates
   - Option A: Remove (cleaner, 2-hop only)
   - Option B: Keep (backward compatible but redundant)

---

## Recommendations

1. **Proceed with the proposed implementation**
   - Neither current release has a good assay model
   - Clean break is better than incremental fixes

2. **Remove direct organism→entity edges**
   - Current direct edges use only 3 generic METPO predicates
   - New 2-hop paths will use 8 specific METPO predicates
   - Much richer biological context

3. **Document the evolution**
   - Users need to understand the modeling changes
   - Provide migration guide for queries
   - Show benefits of new approach

4. **Add validation tests**
   - Ensure no deprecated predicates
   - Ensure all assay nodes connected
   - Ensure proper categories

---

## Query Migration Examples

### 20250222 → Proposed

**Old (20250222)**:
```sparql
# Find organisms assessed by a specific assay
SELECT ?organism
WHERE {
  assay:API_rID32A_alpha_GAL biolink:assesses ?organism .
}
```

**New (Proposed)**:
```sparql
# Find organisms that ferment galactose via assay
SELECT ?organism
WHERE {
  ?organism METPO:2000011 ?assay .  # ferments
  ?assay biolink:has_input CHEBI:28061 .  # galactose
}
```

### 20251217 → Proposed

**Old (20251217)**:
```sparql
# Find organisms that metabolize a chemical (direct)
SELECT ?organism
WHERE {
  ?organism METPO:2000006 CHEBI:17992 .
}
```

**New (Proposed)**:
```sparql
# Find organisms that metabolize a chemical (via assay)
SELECT ?organism ?assay ?process
WHERE {
  ?organism ?metpo_predicate ?assay .
  ?assay biolink:has_input CHEBI:17992 .

  # Can distinguish ferments vs. assimilates vs. growth
  FILTER(?metpo_predicate IN (METPO:2000011, METPO:2000008, METPO:2000012))
}
```

---

## Conclusion

Both releases have incomplete assay modeling:
- **20250222**: Used deprecated predicates, wrong edge direction
- **20251217**: Removed most edges, orphaned nodes, limited predicates

The proposed implementation will:
- ✅ Use all API kit-specific METPO predicates
- ✅ Create proper two-hop paths with assay nodes
- ✅ Remove all deprecated predicates
- ✅ Provide rich methodological metadata
- ✅ Cover all 503 assay wells from 17 kits

**Next step**: Confirm migration strategy and begin implementation.

---

**Analysis Date**: 2026-01-12
**Analyst**: Claude Code
**Files**:
- `data/merged/20250222/merged-kg_*.tsv`
- `data/merged/20251217/merged-kg_*.tsv`
- `docs/ASSAY_NODE_MODELING.md`
