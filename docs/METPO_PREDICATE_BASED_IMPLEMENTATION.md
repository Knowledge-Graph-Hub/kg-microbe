# METPO Predicate-Based Implementation for Unmapped Traits

**Date**: 2026-03-28
**Approach**: Use existing METPO predicates + minimal new data properties
**Addresses**: 148 unmapped traits (183,810 occurrences)

---

## Overview

METPO supports **predicate-based patterns** where organisms link directly to chemical entities via specific predicates, rather than creating separate capability classes for each substrate. This approach is more scalable and aligned with METPO's design philosophy.

### Core Pattern

```turtle
# Instead of creating METPO:glucose_fermentation_capability
# Use existing predicates:
NCBITaxon:562 METPO:2000011 CHEBI:17234 .  # ferments glucose
```

---

## Solution 1: Fermentation Traits → Use Existing Predicate

### Current State
- **Unmapped traits**: 95 fermentation patterns (e.g., `fermentation: D-glucose`)
- **Total occurrences**: ~7,500 across metatraits data

### METPO Predicates Already Available
| Predicate | Label | Usage |
|-----------|-------|-------|
| `METPO:2000011` | ferments | Organism ferments chemical (POSITIVE) |
| `METPO:2000037` | does not ferment | Organism does not ferment chemical (NEGATIVE) |

### Implementation Pattern

**Edge Format**:
```python
{
    "subject": "NCBITaxon:562",          # E. coli
    "predicate": "METPO:2000011",        # ferments
    "object": "CHEBI:17234",             # D-glucose
    "relation": "METPO:2000011",
    "primary_knowledge_source": "infores:metatraits"
}
```

**RDF/Turtle**:
```turtle
NCBITaxon:562 METPO:2000011 CHEBI:17234 .
CHEBI:17234 rdfs:label "D-glucose" .
```

### Mapping Table for Transform

Create mapping from unmapped trait labels to CHEBI IDs:

| Unmapped Trait | CHEBI ID | CHEBI Label | Occurrences |
|----------------|----------|-------------|-------------|
| fermentation: D-glucose | CHEBI:17234 | D-glucose | 3,896 |
| fermentation: D-mannitol | CHEBI:16899 | D-mannitol | 2,087 |
| fermentation: D-ribose | CHEBI:47013 | D-ribose | 1,546 |
| fermentation: D-xylose | CHEBI:18222 | D-xylose | 1,329 |
| fermentation: lactose | CHEBI:17716 | lactose | 321 |
| ... | ... | ... | ... |

**File**: `mappings/fermentation_trait_to_chebi.tsv` (see separate file)

### Transform Code Pattern

```python
from kg_microbe.transform_utils.constants import METPO_FERMENTS

# Load fermentation → CHEBI mapping
fermentation_map = load_fermentation_mapping()

# Parse trait
if trait.startswith("fermentation: "):
    substrate = trait.replace("fermentation: ", "").strip()
    chebi_id = fermentation_map.get(substrate)

    if chebi_id:
        edge = {
            "subject": organism_id,
            "predicate": METPO_FERMENTS,  # METPO:2000011
            "object": chebi_id,
            "relation": METPO_FERMENTS,
            "primary_knowledge_source": "infores:metatraits"
        }
    else:
        # Log unmapped substrate for manual review
        logger.warning(f"No CHEBI mapping for fermentation substrate: {substrate}")
```

---

## Solution 2: Electron Acceptor Traits → Use Existing Predicate

### Current State
- **Unmapped trait**: `electron acceptor: sulfur compounds` (99,543 occurrences)
- **Other traits**: `electron acceptor: amorphous iron (iii) oxide` (8 occurrences)

### METPO Predicate Already Available
| Predicate | Label | Usage |
|-----------|-------|-------|
| `METPO:2000008` | uses as electron acceptor | Chemical serves as electron acceptor |

### Implementation Pattern

**Edge Format**:
```python
{
    "subject": "NCBITaxon:872",          # Desulfovibrio vulgaris
    "predicate": "METPO:2000008",        # uses as electron acceptor
    "object": "CHEBI:16189",             # sulfate
    "relation": "METPO:2000008",
    "primary_knowledge_source": "infores:metatraits"
}
```

**RDF/Turtle**:
```turtle
NCBITaxon:872 METPO:2000008 CHEBI:16189 .  # uses sulfate as electron acceptor
CHEBI:16189 rdfs:label "sulfate" .
```

### Mapping Strategy

For compound terms like "sulfur compounds":
1. **Option A**: Map to parent CHEBI class (e.g., CHEBI:26833 "sulfur molecular entity")
2. **Option B**: Map to specific compound if context suggests (e.g., CHEBI:16189 "sulfate")
3. **Option C**: Create multiple edges for known sulfur acceptors (sulfate, sulfite, thiosulfate)

**Recommended**: Option A (parent class) for broad terms, Option B for specific compounds

| Unmapped Trait | CHEBI ID | CHEBI Label | Approach |
|----------------|----------|-------------|----------|
| electron acceptor: sulfur compounds | CHEBI:26833 | sulfur molecular entity | Parent class |
| electron acceptor: amorphous iron (iii) oxide | CHEBI:82594 | iron(III) oxide | Specific |
| electron acceptor: nitrate | CHEBI:17632 | nitrate | Specific |

**File**: `mappings/electron_acceptor_trait_to_chebi.tsv`

---

## Solution 3: Quantitative Properties → NEW Data Properties

### Current State
- **Temperature traits**: `growth: [X] degrees Celsius` (85,311 occurrences)
- **Salt traits**: `growth: [X]% NaCl` (85,311 occurrences)
- **pH traits**: `pH preference` (5,479 occurrences)

### Problem
Existing METPO predicates don't support quantitative measurements directly. We need **data properties** to attach numerical values to organisms.

### Proposed Data Properties (9 NEW)

#### Temperature Properties
```turtle
METPO:has_growth_temperature_optimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature optimum"@en ;
    obo:IAO_0000115 "The optimal temperature at which an organism achieves maximum growth rate (in degrees Celsius)."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000027" ;  # degree Celsius
    .

METPO:has_growth_temperature_minimum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature minimum"@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .

METPO:has_growth_temperature_maximum a owl:DatatypeProperty ;
    rdfs:label "has growth temperature maximum"@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .
```

#### Salt Tolerance Properties
```turtle
METPO:has_NaCl_concentration_optimum a owl:DatatypeProperty ;
    rdfs:label "has NaCl concentration optimum"@en ;
    obo:IAO_0000115 "The optimal NaCl concentration for growth expressed as weight/volume percentage."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    oboInOwl:hasDbXref "UO:0000187" ;  # percent
    rdfs:comment "Value should be w/v percentage. Example: 6.5 for 6.5% NaCl" ;
    .

METPO:has_NaCl_concentration_minimum a owl:DatatypeProperty ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .

METPO:has_NaCl_concentration_maximum a owl:DatatypeProperty ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .
```

#### pH Properties
```turtle
METPO:has_pH_optimum a owl:DatatypeProperty ;
    rdfs:label "has pH optimum"@en ;
    obo:IAO_0000115 "The optimal pH for growth on the pH scale (0-14)."@en ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .

METPO:has_pH_minimum a owl:DatatypeProperty ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .

METPO:has_pH_maximum a owl:DatatypeProperty ;
    rdfs:domain biolink:OrganismTaxon ;
    rdfs:range xsd:decimal ;
    .
```

### Usage Pattern

**Direct attachment to organism node**:
```turtle
NCBITaxon:1392 a biolink:OrganismTaxon ;
    rdfs:label "Bacillus anthracis" ;
    METPO:has_growth_temperature_optimum "35.0"^^xsd:decimal ;
    METPO:has_growth_temperature_minimum "15.0"^^xsd:decimal ;
    METPO:has_growth_temperature_maximum "45.0"^^xsd:decimal ;
    METPO:has_NaCl_concentration_optimum "0.5"^^xsd:decimal ;
    METPO:has_pH_optimum "7.0"^^xsd:decimal ;
    .
```

**In KGX TSV format** (nodes.tsv):
```
id	category	name	has_growth_temperature_optimum	has_NaCl_concentration_optimum	has_pH_optimum
NCBITaxon:1392	biolink:OrganismTaxon	Bacillus anthracis	35.0	0.5	7.0
```

### Transform Implementation

```python
# Parse quantitative trait
if trait.startswith("growth: ") and "degrees Celsius" in trait:
    # Extract temperature value
    temp_match = re.search(r'(\d+(?:\.\d+)?)', trait)
    if temp_match:
        temp_value = float(temp_match.group(1))

        # Add as node property
        organism_node["has_growth_temperature_optimum"] = temp_value

elif trait.startswith("growth: ") and "% NaCl" in trait:
    # Extract NaCl concentration
    nacl_match = re.search(r'(\d+(?:\.\d+)?)', trait)
    if nacl_match:
        nacl_value = float(nacl_match.group(1))
        organism_node["has_NaCl_concentration_optimum"] = nacl_value

elif trait == "pH preference":
    # Parse pH value from context (may need additional data)
    organism_node["has_pH_optimum"] = ph_value
```

---

## Summary of Changes Needed

### No New Classes Required
- ✅ Fermentation: Use existing `METPO:2000011` (ferments)
- ✅ Electron acceptors: Use existing `METPO:2000008` (uses as electron acceptor)

### 9 New Data Properties Required
1. `METPO:has_growth_temperature_optimum`
2. `METPO:has_growth_temperature_minimum`
3. `METPO:has_growth_temperature_maximum`
4. `METPO:has_NaCl_concentration_optimum`
5. `METPO:has_NaCl_concentration_minimum`
6. `METPO:has_NaCl_concentration_maximum`
7. `METPO:has_pH_optimum`
8. `METPO:has_pH_minimum`
9. `METPO:has_pH_maximum`

### 2 New Mapping Files Required
1. `mappings/fermentation_trait_to_chebi.tsv` - Map 95 fermentation substrates to CHEBI IDs
2. `mappings/electron_acceptor_trait_to_chebi.tsv` - Map electron acceptor compounds to CHEBI IDs

---

## Coverage Impact

| Solution | Traits Addressed | Occurrences | Implementation Complexity |
|----------|------------------|-------------|---------------------------|
| Fermentation predicate | 95 | ~7,500 | LOW (mapping file only) |
| Electron acceptor predicate | 2-5 | 99,551 | LOW (mapping file only) |
| Quantitative data properties | 3 | 176,101 | MEDIUM (9 new properties) |
| **Total** | **~100** | **~283,000** | **LOW-MEDIUM** |

---

## Implementation Roadmap

### Phase 1: Mapping Files (Week 1)
1. Create `fermentation_trait_to_chebi.tsv` with all 95 substrates → CHEBI mappings
2. Create `electron_acceptor_trait_to_chebi.tsv` with acceptor compounds → CHEBI mappings
3. Validate CHEBI IDs exist in current ChEBI release

### Phase 2: METPO Data Properties (Week 2)
1. Submit 9 data property definitions to METPO GitHub as issue/PR
2. Wait for METPO maintainer review and ID assignment
3. Update METPO ontology locally for testing

### Phase 3: Transform Implementation (Week 3)
1. Update metatraits/metatraits_gtdb transforms to:
   - Load fermentation and electron acceptor mapping files
   - Use `METPO:2000011` for fermentation traits
   - Use `METPO:2000008` for electron acceptor traits
   - Attach quantitative data properties to organism nodes
2. Test with sample data
3. Run full transforms

### Phase 4: Validation (Week 4)
1. Verify edge counts: expect 95 × occurrence_count new fermentation edges
2. Verify node properties populated with temperature/NaCl/pH values
3. Compare coverage: should reduce unmapped traits by ~18%

---

## Files Generated

1. **`mappings/metpo_predicate_based_proposal.tsv`** - 9 data property definitions
2. **`docs/METPO_PREDICATE_BASED_IMPLEMENTATION.md`** - This document
3. **`mappings/fermentation_trait_to_chebi.tsv`** - (To be created) 95 fermentation mappings
4. **`mappings/electron_acceptor_trait_to_chebi.tsv`** - (To be created) Electron acceptor mappings

---

## References

- METPO Predicates: `docs/METPO_PREDICATES.md`
- METPO GitHub: https://github.com/berkeleybop/metpo
- Unmapped Traits Analysis: `docs/UNMAPPED_TRAITS_ONTOLOGY_ANALYSIS.md`
- ChEBI: https://www.ebi.ac.uk/chebi/
