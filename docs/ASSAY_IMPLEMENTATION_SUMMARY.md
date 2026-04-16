# API Kit Assay Implementation Summary

**Date**: 2026-01-12
**Status**: APPROVED FOR IMPLEMENTATION
**See full proposal**: `docs/ASSAY_NODE_MODELING.md`

---

## Quick Reference

### Key Decisions

1. ✅ **Use METPO predicates** for organism→assay edges (preserves rich semantics)
2. ✅ **Create all assay nodes upfront** with complete methodological edges (Option A)
3. ✅ **Growth tests confirmed** in API biotype100 kit
4. ✅ **503 total assay nodes** to be created across 17 API kits

### Data Source

- **Metadata URL**: https://raw.githubusercontent.com/CultureBotAI/assay-metadata/refs/heads/main/data/assay_kits_simple.json
- **Loaded by**: `load_assay_kit_mappings()` in `kg_microbe/utils/mapping_file_utils.py`
- **Used by**: `BacDiveTransform` in `kg_microbe/transform_utils/bacdive/bacdive.py`

---

## Graph Structure

### Current Implementation (Direct Edges Only)

```
NCBITaxon:562 --METPO:2000302--> GO:0004035
NCBITaxon:562 --METPO:2000011--> CHEBI:17113
```

### New Implementation (Dual-Edge Pattern)

**Both direct edges AND assay nodes** - captures biological facts + methodology:

```
# Direct edge (biological fact)
NCBITaxon:562 --METPO:2000302--> GO:0004035
NCBITaxon:562 --METPO:2000011--> CHEBI:17113

# Two-hop path via assay (methodology + provenance)
NCBITaxon:562 --METPO:2000302--> assay:API_zym_alkaline_phosphatase --biolink:has_output--> GO:0004035
NCBITaxon:562 --METPO:2000011--> assay:API_50CHac_ERY --biolink:has_input--> CHEBI:17113
```

**Benefits**:
- Direct edges allow simple queries for biological facts
- Assay paths capture methodology and experimental provenance
- Users can choose query complexity based on needs

---

## Node Format

### Assay Node Template

```tsv
id: assay:API_{kit_name}_{well_name}
category: biolink:Procedure
name: {kit_name} - {well_label}
description: {well_description}
kit_name: {kit_name}
well_name: {well_name}
test_type: {enzyme|chemical}
```

### Example Nodes

```tsv
# Enzyme test
id: assay:API_zym_alkaline_phosphatase
category: biolink:Procedure
name: API zym - Alkaline phosphatase
description: Tests for Alkaline phosphatase activity using chromogenic substrate
kit_name: API zym
well_name: Alkaline phosphatase
test_type: enzyme

# Chemical test
id: assay:API_50CHac_ERY
category: biolink:Procedure
name: API 50CHac - Erythritol
description: Tests for utilization/fermentation of Erythritol
kit_name: API 50CHac
well_name: ERY
test_type: chemical
```

---

## Edge Types

### 1. Organism → Assay (Test Outcome)

**Predicate**: METPO predicate (varies by kit/result)
**Relation**: Varies by test type and result

| Test Type | Result | METPO Predicate | Relation | Kit Example |
|-----------|--------|-----------------|----------|-------------|
| enzyme | positive | METPO:2000302 | RO:0002215 (capable of) | API zym |
| enzyme | negative | METPO:2000303 | RO:0002215 (capable of) | API zym |
| chemical | positive (ferment) | METPO:2000011 | biolink:interacts_with | API 50CHac |
| chemical | negative (ferment) | METPO:2000037 | biolink:interacts_with | API 50CHac |
| chemical | positive (assimilate) | METPO:2000008 | biolink:interacts_with | API 20NE |
| chemical | negative (assimilate) | METPO:2000034 | biolink:interacts_with | API 20NE |
| chemical | positive (growth) | METPO:2000012 | biolink:interacts_with | API biotype100 |
| chemical | negative (growth) | METPO:2000038 | biolink:interacts_with | API biotype100 |

**Note**: METPO predicates are loaded from assay metadata `metpo_predicates` field per kit

### 2. Assay → Entity (Methodological Reference)

**Create all edges upfront** (Option A) for complete methodological documentation

| Assay Type | Predicate | Relation | Target | Purpose |
|------------|-----------|----------|--------|---------|
| enzyme | biolink:has_output | NCIT:C25284 (output) | GO term | What enzyme activity is detected |
| enzyme | biolink:has_output | NCIT:C25284 (output) | EC number | What enzyme activity is detected |
| chemical | biolink:has_input | RO:0002233 (has input) | ChEBI entity | What substrate is tested |

---

## Statistics

### Assay Node Counts

| Kit Name | Wells | Category | Process |
|----------|-------|----------|---------|
| API zym | 20 | Enzyme profiling | Enzyme activity |
| API 50CHac | 49 | Carbohydrate fermentation | Fermentation |
| API 20NE | 21 | Bacterial identification | Assimilation + Enzyme |
| API rID32STR | 32 | Bacterial identification | Mixed |
| API biotype100 | 99 | Biochemical profiling | **Growth** |
| API 20E | 19 | Bacterial identification | Mixed |
| API coryne | 21 | Bacterial identification | Mixed |
| API rID32A | 29 | Bacterial identification | Mixed |
| API ID32E | 32 | Bacterial identification | Mixed |
| API NH | 13 | Bacterial identification | Mixed |
| API ID32STA | 26 | Bacterial identification | Mixed |
| API CAM | 21 | Bacterial identification | Mixed |
| API 20STR | 20 | Bacterial identification | Mixed |
| API LIST | 10 | Bacterial identification | Mixed |
| API STA | 20 | Bacterial identification | Mixed |
| API 20A | 21 | Bacterial identification | Mixed |
| API 50CHas | 50 | Carbohydrate fermentation | Assimilation |

**Total**: 503 assay nodes

### Edge Count Estimates

**Assay→Entity edges (methodological, created upfront)**:
- ~600-800 edges (one per GO/EC/ChEBI target per well)
- Created once during transform initialization
- Independent of organism data

**Organism→Assay edges (NEW, outcome, created per organism)**:
- Varies by organism and test results
- Only created when BacDive has actual test results
- Estimated: ~50,000-100,000 edges across all organisms

**Organism→Entity edges (EXISTING, direct biological facts)**:
- ~74,000 direct edges preserved from current implementation
- Pattern: `NCBITaxon → METPO predicate → GO/EC/ChEBI`
- These are KEPT to provide simple query paths

**Total new edges added**: ~650K-800K (assay nodes + organism→assay + assay→entity)

---

## Implementation Steps

### Step 1: Update Constants

Add to `kg_microbe/transform_utils/constants.py`:

```python
# Assay node properties
ASSAY_KIT_NAME = "kit_name"
ASSAY_WELL_NAME = "well_name"
ASSAY_TEST_TYPE = "test_type"

# Assay→Entity predicates
ASSAY_HAS_OUTPUT = "biolink:has_output"
ASSAY_HAS_INPUT = "biolink:has_input"

# Assay→Entity relations
HAS_OUTPUT_RELATION = "NCIT:C25284"  # Already exists
# HAS_INPUT_RELATION = "RO:0002233"  # Already exists
```

### Step 2: Create Assay Node Generator

Add to `kg_microbe/utils/mapping_file_utils.py`:

```python
def generate_assay_nodes(assay_data: dict) -> List[List]:
    """
    Generate assay node rows from assay_kits_simple.json data.

    Returns list of rows formatted for node_writer.writerows().
    Each row: [id, category, name, description, kit_name, well_name, test_type, ...]
    """
    nodes = []
    for kit in assay_data.get("api_kits", []):
        kit_name = kit["kit_name"]
        for well in kit.get("wells", []):
            # Skip control wells or unsupported types
            if not well.get("type") or well["type"][0] not in ["enzyme", "chemical"]:
                continue

            well_name = well["name"]
            node_id = f"assay:{kit_name}_{well_name}".replace(" ", "_")

            # Build node row matching node_header
            node_row = [
                node_id,                              # id
                "biolink:Procedure",                  # category
                f"{kit_name} - {well['label'][0]}",  # name
                well["description"][0],               # description
                kit_name,                             # kit_name (custom field)
                well_name,                            # well_name (custom field)
                well["type"][0],                      # test_type (custom field)
            ]
            # Pad with None for remaining columns
            node_row += [None] * (len(node_header) - len(node_row))

            nodes.append(node_row)

    return nodes
```

### Step 3: Create Assay→Entity Edge Generator

Add to `kg_microbe/utils/mapping_file_utils.py`:

```python
def generate_assay_entity_edges(assay_data: dict) -> List[List]:
    """
    Generate assay→entity edges from assay_kits_simple.json data.

    Returns list of rows formatted for edge_writer.writerows().
    Each row: [subject, predicate, object, relation, knowledge_source, ...]
    """
    edges = []

    for kit in assay_data.get("api_kits", []):
        kit_name = kit["kit_name"]

        for well in kit.get("wells", []):
            if not well.get("type") or well["type"][0] not in ["enzyme", "chemical"]:
                continue

            well_name = well["name"]
            assay_id = f"assay:{kit_name}_{well_name}".replace(" ", "_")
            test_type = well["type"][0]

            if test_type == "enzyme":
                # Assay → GO terms (enzyme activity output)
                for go_term in well.get("go_terms", []):
                    edges.append([
                        assay_id,
                        "biolink:has_output",
                        go_term,
                        "NCIT:C25284",
                        "infores:assay-metadata",
                    ])

                # Assay → EC numbers (enzyme classification output)
                for ec_number in well.get("ec_number", []):
                    ec_id = f"EC:{ec_number}"
                    edges.append([
                        assay_id,
                        "biolink:has_output",
                        ec_id,
                        "NCIT:C25284",
                        "infores:assay-metadata",
                    ])

            elif test_type == "chemical":
                # Assay → ChEBI entities (substrate input)
                for chebi_id in well.get("chebi_id", []):
                    edges.append([
                        assay_id,
                        "biolink:has_input",
                        chebi_id,
                        "RO:0002233",
                        "infores:assay-metadata",
                    ])

    return edges
```

### Step 4: Update BacDive Transform

Modify `kg_microbe/transform_utils/bacdive/bacdive.py`:

**4a. Load assay data in `__init__`**:
```python
# Existing code loads self.assay_kit_mappings
# Add new fields:
self.assay_nodes = None
self.assay_entity_edges = None
```

**4b. Generate assay nodes/edges once in `run()` before organism loop**:
```python
def run(self):
    # ... existing setup code ...

    # Generate assay nodes and edges once
    if self.assay_kit_mappings:
        # Get raw data (need to fetch again or cache)
        response = requests.get(ASSAY_KITS_SIMPLE_JSON_URL)
        assay_data = response.json()

        self.assay_nodes = generate_assay_nodes(assay_data)
        self.assay_entity_edges = generate_assay_entity_edges(assay_data)

        # Write assay nodes
        node_writer.writerows(self.assay_nodes)

        # Write assay→entity edges
        edge_writer.writerows(self.assay_entity_edges)

    # ... continue with organism processing loop ...
```

**4c. ADD organism→assay edges (keep existing organism→entity edges)**:

**IMPORTANT**: This is ADDITIVE - we create organism→assay edges in addition to the existing organism→GO/EC/ChEBI edges.

Modify lines 2354-2435 in `bacdive.py`:

```python
if test_type == "enzyme":
    # Get assay ID
    assay_id = f"assay:{assay_name}_{test_label}".replace(" ", "_")

    # Process GO terms
    if go_terms:
        for go_term in go_terms:
            # EXISTING: Direct organism → GO edge (KEEP THIS)
            knowledge_level, agent_type = self._add_edge_metadata(
                metpo_predicate, CAPABLE_OF, go_term
            )
            edge_writer.writerow([
                organism_id,
                metpo_predicate,
                go_term,
                CAPABLE_OF,
                self.knowledge_source,
                knowledge_level,
                agent_type,
            ])

    # Process EC numbers
    if ec_numbers:
        for ec_number in ec_numbers:
            ec_id = f"{EC_PREFIX}{ec_number}"
            # EXISTING: Direct organism → EC edge (KEEP THIS)
            knowledge_level, agent_type = self._add_edge_metadata(
                metpo_predicate, CAPABLE_OF, ec_id
            )
            edge_writer.writerow([
                organism_id,
                metpo_predicate,
                ec_id,
                CAPABLE_OF,
                self.knowledge_source,
                knowledge_level,
                agent_type,
            ])

    # NEW: Add organism → assay edge (if GO or EC exists)
    if go_terms or ec_numbers:
        knowledge_level, agent_type = self._add_edge_metadata(
            metpo_predicate, CAPABLE_OF, assay_id
        )
        edge_writer.writerow([
            organism_id,
            metpo_predicate,
            assay_id,
            CAPABLE_OF,
            self.knowledge_source,
            knowledge_level,
            agent_type,
        ])

elif test_type == "chemical":
    # Get assay ID
    assay_id = f"assay:{assay_name}_{test_label}".replace(" ", "_")

    # Get ChEBI IDs
    chebi_ids = test_info.get("chebi_id", [])

    if chebi_ids:
        for chebi_id in chebi_ids:
            # EXISTING: Direct organism → ChEBI edge (KEEP THIS)
            knowledge_level, agent_type = self._add_edge_metadata(
                metpo_predicate, "biolink:interacts_with", chebi_id
            )
            edge_writer.writerow([
                organism_id,
                metpo_predicate,
                chebi_id,
                "biolink:interacts_with",
                self.knowledge_source,
                knowledge_level,
                agent_type,
            ])

        # NEW: Add organism → assay edge
        knowledge_level, agent_type = self._add_edge_metadata(
            metpo_predicate, "biolink:interacts_with", assay_id
        )
        edge_writer.writerow([
            organism_id,
            metpo_predicate,
            assay_id,
            "biolink:interacts_with",
            self.knowledge_source,
            knowledge_level,
            agent_type,
        ])
```

**Summary of changes**:
- ✅ Keep all existing organism→GO/EC/ChEBI edges
- ✅ Add new organism→assay edges
- ✅ Assay→GO/EC/ChEBI edges created once upfront
- Result: Dual-edge pattern (direct + 2-hop via assay)

### Step 5: Update Node Header

Ensure node header includes custom fields for assays:

```python
# In constants.py or bacdive.py where node_header is defined
node_header = [
    ID_COLUMN,
    CATEGORY_COLUMN,
    NAME_COLUMN,
    DESCRIPTION_COLUMN,
    ASSAY_KIT_NAME,      # NEW
    ASSAY_WELL_NAME,     # NEW
    ASSAY_TEST_TYPE,     # NEW
    # ... other existing fields ...
]
```

### Step 6: Add Tests

Create `tests/test_assay_nodes.py`:

```python
def test_assay_node_generation():
    """Test that assay nodes are created correctly."""
    # Load test data
    # Generate nodes
    # Assert 503 nodes created
    # Assert node IDs follow pattern
    # Assert categories are biolink:Procedure

def test_assay_entity_edges():
    """Test that assay→entity edges are created."""
    # Generate edges
    # Assert enzyme assays have has_output to GO/EC
    # Assert chemical assays have has_input to ChEBI

def test_organism_assay_edges():
    """Test that organism→assay edges use METPO predicates."""
    # Process sample organism data
    # Assert edges target assay nodes
    # Assert METPO predicates used
```

---

## Validation Checklist

- [ ] 503 assay nodes created (one per well across all kits)
- [ ] All assay nodes have category `biolink:Procedure`
- [ ] All assay nodes have kit_name, well_name, test_type attributes
- [ ] Enzyme assays have `has_output` edges to GO terms and EC numbers
- [ ] Chemical assays have `has_input` edges to ChEBI entities
- [ ] Organism edges target assay nodes (not GO/EC/ChEBI directly)
- [ ] METPO predicates preserved for organism→assay edges
- [ ] Growth tests handled (API biotype100 with METPO:2000012/2000038)
- [ ] All 4 METPO predicate types supported:
  - [ ] shows activity of / does not show activity of
  - [ ] ferments / does not ferment
  - [ ] assimilates / does not assimilate
  - [ ] uses for growth / does not use for growth
- [ ] Tests pass for assay node generation
- [ ] Tests pass for edge creation
- [ ] Graph validates against Biolink schema
- [ ] No deprecated predicates used (assesses, is_assessed_by)

---

## Example Queries

### Find all assays testing a specific enzyme

```sparql
SELECT ?assay ?kit ?test
WHERE {
  ?assay biolink:has_output GO:0004035 .  # alkaline phosphatase
  ?assay kit_name ?kit .
  ?assay well_name ?test .
}
```

### Find organisms that can ferment erythritol

```sparql
SELECT ?organism ?name
WHERE {
  ?organism METPO:2000011 ?assay .  # ferments
  ?assay biolink:has_input CHEBI:17113 .  # erythritol
  ?organism name ?name .
}
```

### Find all growth assays

```sparql
SELECT ?assay ?substrate
WHERE {
  ?assay kit_name "API biotype100" .
  ?assay biolink:has_input ?substrate .
}
```

---

## Migration Notes

### Breaking Changes

**None**: This is additive only
- Current direct edges remain functional for backward compatibility
- New assay nodes add additional detail without removing existing data

### Optional: Future Removal of Direct Edges

If desired, in a future version we could:
1. Remove direct organism→GO/EC/ChEBI edges
2. Keep only organism→assay→entity two-hop paths
3. Benefits: Cleaner graph, explicit methodology
4. Requires: User notification, query migration

**Recommendation**: Keep both for now (direct + assay nodes) to maintain backward compatibility

---

## Next Steps

1. Review and approve this implementation plan
2. Implement Step 1: Update constants
3. Implement Step 2-3: Create generator functions
4. Implement Step 4: Update BacDive transform
5. Implement Step 5: Update node header
6. Implement Step 6: Add tests
7. Run transform on test data
8. Validate output
9. Run full transform
10. Update documentation

---

**Questions? See full proposal**: `docs/ASSAY_NODE_MODELING.md`
