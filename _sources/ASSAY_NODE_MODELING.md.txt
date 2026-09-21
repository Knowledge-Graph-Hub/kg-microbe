# API Kit Assay Node Modeling

**Date**: 2026-01-12
**Status**: PROPOSAL
**Metadata Source**: https://raw.githubusercontent.com/CultureBotAI/assay-metadata/refs/heads/main/data/assay_kits_simple.json

---

## Executive Summary

This document proposes modeling API (Analytical Profile Index) kit assays as explicit nodes in the knowledge graph at the individual test component level. Currently, organism-to-enzyme/chemical relationships are represented directly; this proposal introduces intermediate assay nodes to capture methodological information.

---

## Current Implementation

### Direct Relationships (No Assay Nodes)

**Enzyme Tests:**
```
NCBITaxon:1234 --METPO:2000302 (shows_activity_of)--> GO:0004035 (alkaline phosphatase)
NCBITaxon:1234 --METPO:2000303 (does_not_show_activity_of)--> GO:0016788 (esterase)
```

**Chemical Tests:**
```
NCBITaxon:1234 --METPO:2000011 (ferments)--> CHEBI:17113 (erythritol)
NCBITaxon:1234 --METPO:2000037 (does_not_ferment)--> CHEBI:16731 (D-arabinose)
```

**Implementation:**
- File: `kg_microbe/transform_utils/bacdive/bacdive.py` (lines 2315-2434)
- Mappings loaded from remote JSON via `load_assay_kit_mappings()` in `mapping_file_utils.py`

---

## Proposed Implementation

### With Assay Nodes (Three-Part Relationship)

Create intermediate assay nodes representing individual test components:

**Enzyme Tests:**
```
NCBITaxon:1234 --[outcome predicate]--> assay:API_zym_alkaline_phosphatase
assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035
```

**Chemical Tests:**
```
NCBITaxon:1234 --[outcome predicate]--> assay:API_50CHac_ERY
assay:API_50CHac_ERY --biolink:has_input--> CHEBI:17113
```

---

## Assay Node Structure

### Node Format

Each well/test component becomes a node:

```tsv
id: assay:API_zym_alkaline_phosphatase
category: biolink:Procedure
name: API zym - Alkaline phosphatase test
description: Tests for Alkaline phosphatase activity using chromogenic substrate
```

### Node ID Pattern

```
assay:{KIT_NAME}_{TEST_NAME}
```

Examples:
- `assay:API_zym_alkaline_phosphatase`
- `assay:API_50CHac_ERY`
- `assay:API_20NE_nitrate_reduction`

### Node Category

**Recommended**: `biolink:Procedure`

**Rationale:**
- Assays are methodological procedures, not biological processes
- Biolink defines Procedure as "A series of actions conducted in a certain order or manner"
- Alternative considered: `biolink:InformationContentEntity` (less semantically appropriate)

---

## Predicate Recommendations

### 1. Organism → Assay (Test Outcome)

The predicate depends on **test type** and **test result**.

#### Option A: Use Biolink Standard Predicates

| Test Type | Result | Biolink Predicate | Relation (RO/NCIT) |
|-----------|--------|-------------------|-------------------|
| enzyme | positive | `biolink:capable_of` | RO:0002215 (capable of) |
| enzyme | negative | `biolink:lacks_part` | RO:0002220 (lacks part) |
| chemical | positive | `biolink:metabolizes` | RO:0002160 (metabolizes) |
| chemical | negative | `biolink:lacks_part` | RO:0002220 (lacks part) |

**Example:**
```python
# Positive enzyme test
NCBITaxon:1234 --biolink:capable_of--> assay:API_zym_alkaline_phosphatase

# Negative chemical test
NCBITaxon:1234 --biolink:lacks_part--> assay:API_50CHac_ERY
```

#### Option B: Use METPO Predicates (Outcome-Specific)

Keep using METPO predicates for biological meaning, but target assay nodes:

| Test Type | Result | METPO Predicate | Label |
|-----------|--------|-----------------|-------|
| enzyme | positive | METPO:2000302 | shows activity of |
| enzyme | negative | METPO:2000303 | does not show activity of |
| chemical | positive | METPO:2000011 | ferments |
| chemical | negative | METPO:2000037 | does not ferment |

**Example:**
```python
# Positive enzyme test
NCBITaxon:1234 --METPO:2000302--> assay:API_zym_alkaline_phosphatase

# Negative chemical test
NCBITaxon:1234 --METPO:2000037--> assay:API_50CHac_ERY
```

**Trade-off:**
- ✅ Preserves rich METPO semantics (ferments vs. utilizes vs. produces)
- ❌ METPO predicates designed for organism→entity, not organism→procedure
- ⚠️ Semantic mismatch: organism "ferments" a procedure?

#### Option C: Generic Participation Predicate

Use a neutral predicate for test participation, encode outcome as edge attribute:

```python
# Subject → Predicate → Object → Qualifiers
NCBITaxon:1234 --biolink:participates_in--> assay:API_zym_alkaline_phosphatase
  qualifiers:
    - test_outcome: positive
    - assay_result: "+"
```

**Trade-off:**
- ✅ Semantically accurate (organism participates in procedure)
- ✅ Outcome captured as structured qualifier
- ❌ Requires qualifier support in downstream tools
- ❌ Harder to query (need to filter on qualifiers)

### 2. Assay → Target Entity (What the Assay Tests)

This edge describes what the assay measures or tests for.

#### For Enzyme Tests (Assay → GO term / EC number)

**Recommended**: `biolink:has_output`

```python
assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035
assay:API_zym_esterase --biolink:has_output--> EC:3.1.1.1
```

**Relation**: NCIT:C25284 (output) or OBI:0000299 (has_specified_output)

**Rationale:**
- The assay produces/detects evidence of enzyme activity
- `has_output` is standard Biolink predicate for procedure outputs

#### For Chemical Tests (Assay → ChEBI)

**Recommended**: `biolink:has_input`

```python
assay:API_50CHac_ERY --biolink:has_input--> CHEBI:17113
assay:API_50CHac_DARA --biolink:has_input--> CHEBI:16731
```

**Relation**: RO:0002233 (has input)

**Rationale:**
- The chemical substrate is the input to the fermentation/utilization test
- `has_input` is standard Biolink predicate for procedure inputs

---

## Recommendation Summary

### ✅ APPROVED Approach: METPO Predicates + has_output/has_input

**Organism → Assay (Use METPO Predicates):**
- Enzyme positive: `METPO:2000302` (shows activity of)
- Enzyme negative: `METPO:2000303` (does not show activity of)
- Chemical fermentation positive: `METPO:2000011` (ferments)
- Chemical fermentation negative: `METPO:2000037` (does not ferment)
- Chemical assimilation positive: `METPO:2000008` (assimilates)
- Chemical assimilation negative: `METPO:2000034` (does not assimilate)
- Chemical growth positive: `METPO:2000012` (uses for growth)
- Chemical growth negative: `METPO:2000038` (does not use for growth)

**Assay → Entity (Create all methodological edges upfront - Option A):**
- Enzyme tests: `biolink:has_output` → GO/EC
- Chemical tests: `biolink:has_input` → ChEBI

**Rationale:**
1. Preserves rich METPO domain-specific semantics
2. Consistent with current implementation (already using these predicates)
3. Clear biological meaning (ferments vs. assimilates vs. uses for growth)
4. Assay→entity edges provide methodological reference for all tests
5. METPO predicates loaded dynamically from assay metadata

---

## Example Graph Structure

### Complete Example: Positive Enzyme Test

```
# Organism shows enzyme activity (via assay)
NCBITaxon:562 (E. coli)
  --predicate: METPO:2000302 (shows activity of)
  --relation: RO:0002215 (capable of)
  --> assay:API_zym_alkaline_phosphatase

# Assay node
id: assay:API_zym_alkaline_phosphatase
category: biolink:Procedure
name: API zym - Alkaline phosphatase
description: Tests for Alkaline phosphatase activity using chromogenic substrate
kit_name: API zym
well_name: Alkaline phosphatase
test_type: enzyme

# Assay detects enzyme activity
assay:API_zym_alkaline_phosphatase
  --predicate: biolink:has_output
  --relation: NCIT:C25284 (output)
  --> GO:0004035 (alkaline phosphatase activity)
```

### Complete Example: Negative Chemical Fermentation Test

```
# Organism does not ferment substrate (via assay)
NCBITaxon:1234
  --predicate: METPO:2000037 (does not ferment)
  --relation: RO:0002220 (lacks part)
  --> assay:API_50CHac_ERY

# Assay node
id: assay:API_50CHac_ERY
category: biolink:Procedure
name: API 50CHac - Erythritol
description: Tests for utilization/fermentation of Erythritol
kit_name: API 50CHac
well_name: ERY
test_type: chemical

# Assay tests substrate
assay:API_50CHac_ERY
  --predicate: biolink:has_input
  --relation: RO:0002233 (has input)
  --> CHEBI:17113 (erythritol)
```

### Complete Example: Positive Chemical Growth Test

```
# Organism uses substrate for growth (via assay)
NCBITaxon:562 (E. coli)
  --predicate: METPO:2000012 (uses for growth)
  --relation: biolink:interacts_with
  --> assay:API_biotype100_GLU

# Assay node
id: assay:API_biotype100_GLU
category: biolink:Procedure
name: API biotype100 - Glucose
description: Tests for growth using Glucose as sole carbon source
kit_name: API biotype100
well_name: GLU
test_type: chemical

# Assay tests substrate
assay:API_biotype100_GLU
  --predicate: biolink:has_input
  --relation: RO:0002233 (has input)
  --> CHEBI:17234 (glucose)
```

---

## Implementation Plan

### Step 1: Create Assay Nodes

Modify `load_assay_kit_mappings()` to generate assay node data:

```python
def generate_assay_nodes(assay_data: dict) -> List[dict]:
    """Generate assay nodes from assay_kits_simple.json."""
    nodes = []
    for kit in assay_data.get("api_kits", []):
        kit_name = kit["kit_name"]
        for well in kit.get("wells", []):
            well_name = well["name"]
            node_id = f"assay:{kit_name}_{well_name}".replace(" ", "_")
            nodes.append({
                "id": node_id,
                "category": "biolink:Procedure",
                "name": f"{kit_name} - {well['label'][0]}",
                "description": well["description"][0],
                "kit_name": kit_name,
                "well_name": well_name,
                "test_type": well["type"][0]
            })
    return nodes
```

### Step 2: Update Edge Creation Logic

Modify `bacdive.py` (lines 2315-2434) to create two-hop edges:

```python
# Current (organism → entity):
organism_id --METPO:2000302--> GO:0004035

# New (organism → assay → entity):
organism_id --biolink:capable_of--> assay:API_zym_alkaline_phosphatase
assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035
```

### Step 3: Add Predicate Mapping

Add constants to `constants.py`:

```python
# Organism → Assay predicates (outcome)
ORGANISM_CAPABLE_OF_ASSAY = "biolink:capable_of"
ORGANISM_LACKS_ASSAY = "biolink:lacks_part"
ORGANISM_METABOLIZES_ASSAY = "biolink:metabolizes"

# Assay → Entity predicates (methodology)
ASSAY_HAS_OUTPUT = "biolink:has_output"
ASSAY_HAS_INPUT = "biolink:has_input"

# Relations
CAPABLE_OF_RELATION = "RO:0002215"
LACKS_PART_RELATION = "RO:0002220"
METABOLIZES_RELATION = "RO:0002160"
HAS_INPUT_RELATION = "RO:0002233"
HAS_OUTPUT_RELATION = "NCIT:C25284"
```

### Step 4: Write Assay Nodes Once

Generate assay nodes during transform initialization (not per-organism):

```python
def run(self):
    # Generate assay nodes once at start
    assay_nodes = self._generate_assay_nodes()
    node_writer.writerows(assay_nodes)

    # Then process organism data as usual
    for organism_record in data:
        self._process_organism_assays(organism_record)
```

---

## Test Types Summary

From assay metadata analysis:

| Test Type | Count | Description |
|-----------|-------|-------------|
| enzyme | ~200 | Detects enzyme activity (GO terms, EC numbers) |
| chemical | ~300 | Tests substrate fermentation/utilization/growth (ChEBI) |

### METPO Predicate Types

Chemical tests use different METPO predicates depending on the biological process:

| Process | Kit Example | Positive Predicate | Negative Predicate |
|---------|-------------|-------------------|-------------------|
| Enzyme activity | API zym | METPO:2000302 (shows activity of) | METPO:2000303 (does not show activity of) |
| Fermentation | API 50CHac | METPO:2000011 (ferments) | METPO:2000037 (does not ferment) |
| Assimilation | API 20NE | METPO:2000008 (assimilates) | METPO:2000034 (does not assimilate) |
| Growth | API biotype100 | METPO:2000012 (uses for growth) | METPO:2000038 (does not use for growth) |

**Note**: All chemical tests (fermentation, assimilation, growth) have type "chemical" in the metadata. The distinction is at the predicate level, not the test type level.

---

## Deprecated Predicates (Do Not Use)

These were removed in Biolink Model v4.3.3:

- ❌ `biolink:assesses`
- ❌ `biolink:is_assessed_by`
- ❌ `biolink:was_tested_for_effect_on`

See `BIOLINK_PREDICATE_CHANGES.md` for migration details.

---

## Decisions Made

1. **✅ METPO predicates for organism→assay edges**
   - **Decision**: YES, preserve METPO predicates
   - **Rationale**: Rich domain-specific semantics are valuable for biological queries

2. **✅ Assay→entity edges created upfront**
   - **Decision**: YES, create all methodological reference edges (Option A)
   - **Rationale**: Complete reference allows users to understand what each assay tests, independent of organism results

3. **Growth tests verified**
   - **Finding**: API biotype100 kit uses "uses for growth" / "does not use for growth" predicates
   - **Test type**: "chemical" (same as fermentation/assimilation tests)
   - **Distinction**: At predicate level, not test type level

## Remaining Questions

1. **Node ID format: Should we sanitize/standardize well names?**
   - Current proposal: `assay:API_zym_alkaline_phosphatase` (full name, spaces → underscores)
   - Alternative: Use original well codes (`assay:API_zym_PHOS`)
   - **Consideration**: Full names are more human-readable, codes are more compact

2. **Relation selection for organism→assay edges**
   - Current: Using RO:0002215 (capable of) for positive, RO:0002220 (lacks part) for negative
   - **Question**: Are these the most appropriate RO terms for assay relationships?
   - **Alternative**: Use more generic relations like biolink:related_to or biolink:interacts_with

---

## References

- Assay metadata: https://github.com/CultureBotAI/assay-metadata
- Biolink Model v4.3.6: https://biolink.github.io/biolink-model/
- BacDive API: https://bacdive.dsmz.de/api/bacdive/
- Relation Ontology: http://www.obofoundry.org/ontology/ro.html

---

**Next Steps:**
1. Review and approve predicate choices
2. Implement assay node generation
3. Update edge creation logic
4. Add tests for new structure
5. Validate against Biolink schema
6. Generate example subgraph for review
