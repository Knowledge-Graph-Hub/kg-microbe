# Synonym vs Same_As in KGX/Biolink Model

## Quick Answer

**Neither `synonym` nor `same_as` are required by KGX/Biolink** - only `id` and `category` are required fields.

However, both are valuable for data integration and should be populated when available.

## Detailed Comparison

### 1. `synonym` - Node Property

**Type**: Node property (attribute)
**Purpose**: Alternative human-readable names for the same entity
**Biolink Definition**: "Alternate human-readable names for a thing"
**Multivalued**: Yes (pipe-separated in TSV: `name1 | name2 | name3`)

**Example**:
```tsv
id: CHEBI:15377
name: water
synonym: H2O | dihydrogen oxide | aqua
```

**Mappings**:
- skos:altLabel
- oboInOwl:hasExactSynonym
- oboInOwl:hasBroadSynonym
- oboInOwl:hasNarrowSynonym

**Use Case**:
- Different names for the same concept in different contexts
- Common names vs scientific names
- Abbreviations and acronyms
- Historical names

---

### 2. `same_as` - Identity Mapping

**Type**: Predicate (in Biolink model), but stored as node property in KGX TSV
**Purpose**: Equivalent identifiers for the same real-world entity
**Biolink Definition**: "Holds between two entities that are considered equivalent to each other"
**Multivalued**: Yes (pipe-separated in TSV)

**Example**:
```tsv
id: CHEBI:15377
same_as: KEGG.COMPOUND:C00001 | PUBCHEM.COMPOUND:962 | HMDB:HMDB0002111
```

**Mappings**:
- owl:sameAs
- skos:exactMatch
- WIKIDATA_PROPERTY:P2888

**Use Case**:
- Linking identifiers from different databases
- Cross-referencing equivalent concepts
- Merging knowledge from multiple sources
- Enabling federated queries

---

## Semantic Difference

| Aspect | synonym | same_as |
|--------|---------|---------|
| **What it represents** | Alternative labels/names | Equivalent identifiers |
| **Applies to** | Single entity's names | Multiple entities (cross-database) |
| **Value type** | Human-readable strings | CURIEs/identifiers |
| **Biolink type** | Node property | Predicate (stored as node property in TSV) |
| **Symmetry** | N/A | Symmetric (A same_as B ⟺ B same_as A) |
| **Purpose** | Improve human readability | Enable data integration |

---

## KG-Microbe Usage

### Current Node Header (8 columns)
```python
[id, category, name, description, xref, provided_by, synonym, same_as]
```

### Required vs Optional

**Required (by Biolink/KGX)**:
- ✅ `id` - Unique identifier (CURIE format)
- ✅ `category` - Biolink category (e.g., biolink:ChemicalEntity)

**Recommended (for data quality)**:
- ⭐ `name` - Primary label
- ⭐ `provided_by` - Knowledge source (infores:*)

**Optional (but valuable)**:
- 📝 `synonym` - Alternative names
- 🔗 `same_as` - Equivalent identifiers
- 📄 `description` - Longer description
- 🔍 `xref` - External cross-references

---

## Examples from KG-Microbe

### BacDive Organism Node
```tsv
id: NCBITaxon:562
category: biolink:OrganismTaxon
name: Escherichia coli
synonym: E. coli | ATCC 11775
same_as:
provided_by: infores:bacdive
```

### ChEBI Chemical Node (from ontologies)
```tsv
id: CHEBI:16236
category: biolink:ChemicalEntity
name: ethanol
synonym: ethyl alcohol | EtOH | grain alcohol | C2H5OH
same_as: KEGG.COMPOUND:C00469 | HMDB:HMDB0000108
provided_by: infores:chebi
```

### MediaDive Medium Component
```tsv
id: CHEBI:17234
category: biolink:ChemicalEntity
name: glucose
synonym: dextrose | D-glucose | grape sugar
same_as: KEGG.COMPOUND:C00293
provided_by: infores:mediadive
```

---

## When to Use Each

### Use `synonym` when you have:
- Common names vs scientific names
- Abbreviations
- Historical/deprecated names
- Names in different languages
- Different naming conventions

### Use `same_as` when you have:
- Identifiers from other databases
- Multiple CURIEs for the same concept
- Owl:sameAs assertions
- SKOS exact matches
- Cross-reference mappings

---

## Implementation Notes

### In `_create_node_row()` Helper
```python
def _create_node_row(
    self,
    node_id: str,
    category: str,
    name: str,
    description: str = None,
    xref: str = None,
    synonym: str = None,      # Pipe-separated alternative names
    same_as: str = None,      # Pipe-separated equivalent CURIEs
) -> list:
    """Create a properly formatted node row with all columns."""
    node_row = [None] * len(self.node_header)
    node_row[0] = node_id           # REQUIRED
    node_row[1] = category          # REQUIRED
    node_row[2] = name              # Recommended
    node_row[3] = description       # Optional
    node_row[4] = xref              # Optional
    node_row[5] = self.knowledge_source  # Recommended
    node_row[6] = synonym           # Optional
    node_row[7] = same_as           # Optional
    return node_row
```

### Populating Values

**For synonym**:
```python
# From BacDive LPSN data
synonyms = lpsn.get(SYNONYMS, {})
if isinstance(synonyms, list):
    synonym_parsed = " | ".join(
        synonym.get(SYNONYM, {}) for synonym in synonyms
    )
```

**For same_as**:
```python
# From cross-reference mappings
equivalent_ids = [
    f"KEGG.COMPOUND:{kegg_id}",
    f"PUBCHEM.COMPOUND:{pubchem_id}",
]
same_as = " | ".join(equivalent_ids)
```

---

## Best Practices

1. **Always populate if available** - Both fields enhance data integration
2. **Use pipe separator** - `|` with spaces: `"name1 | name2 | name3"`
3. **Use CURIEs in same_as** - Not human-readable names
4. **Don't duplicate in synonym** - If it's in `name`, don't repeat in `synonym`
5. **Be consistent** - Use same format across all transforms

---

## References

- [KGX Documentation](https://kgx.readthedocs.io/)
- [Biolink Model Documentation](https://biolink.github.io/biolink-model/)
- [Biolink Model: synonym slot](https://biolink.github.io/biolink-model/synonym/)
- [Biolink Model: same as predicate](https://biolink.github.io/biolink-model/same_as/)
- [KG-Hub paper](https://academic.oup.com/bioinformatics/article/39/7/btad418/7211646)
