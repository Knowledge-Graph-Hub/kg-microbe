# Assessment: Can special_chemical_mappings.tsv be added to METPO Ontology TSV?

**Date:** 2026-04-04  
**Question:** Can `special_chemical_mappings.tsv` be integrated into the METPO ontology TSV like other metatrait mapping cases?  
**Answer:** **NO** - They serve fundamentally different purposes  

---

## TL;DR

**No, it cannot be added to the METPO ontology TSV** because:

1. **Different mapping types**: METPO TSV maps traits → phenotype classes; special_chemical_mappings maps trait patterns → chemical entities
2. **Different data structure**: METPO TSV returns METPO term IDs; special_chemical_mappings returns chemical IDs + predicates
3. **Different purposes**: METPO TSV for "organism HAS phenotype"; special_chemical_mappings for "organism USES chemical"
4. **Remote vs local**: METPO TSV is maintained remotely by METPO team; special_chemical_mappings is project-specific

**Current implementation (separate file) is the correct approach.**

---

## Detailed Analysis

### What is METPO Ontology TSV?

**Source:** Remote ROBOT template maintained by METPO ontology team
```
https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2026-03-24/src/templates/metpo_sheet.tsv
```

**Purpose:** Maps trait synonyms to METPO phenotype/quality classes

**Structure:**
```tsv
ID              label           metatraits synonym
METPO:1000127   GC content      GC percentage
METPO:1000304   temperature optimum   optimal temperature
METPO:1000331   pH optimum      optimal pH
```

**Output format:**
```python
{
    "GC percentage": {
        "curie": "METPO:1000127",
        "label": "GC content",
        "predicate": "biolink:has_phenotype",
        "inferred_category": "biolink:PhenotypicQuality"
    }
}
```

**Usage:** Organism → has phenotype → METPO class
```
NCBITaxon:562 biolink:has_phenotype METPO:1000127
```

### What is special_chemical_mappings.tsv?

**Source:** Local project-specific file
```
kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv
```

**Purpose:** Maps trait patterns to chemical entities with appropriate predicates

**Structure:**
```tsv
trait_pattern                          chemical_name      ontology_id   predicate      category
electron acceptor: sulfur compounds    sulfur compounds   CHEBI:26833   METPO:2000008  biolink:ChemicalEntity
degradation: plastic                   plastic            ENVO:01000970 METPO:2000007  biolink:EnvironmentalMaterial
```

**Output format:**
```python
{
    "electron acceptor: sulfur compounds": {
        "curie": "CHEBI:26833",           # The CHEMICAL entity
        "name": "sulfur molecular entity",
        "predicate": "METPO:2000008",     # The PREDICATE to use
        "category": "biolink:ChemicalEntity"
    }
}
```

**Usage:** Organism → predicate → Chemical entity
```
NCBITaxon:562 METPO:2000008 CHEBI:26833
              (uses as electron acceptor)
```

---

## Key Differences

| Aspect | METPO TSV Mappings | special_chemical_mappings |
|--------|-------------------|---------------------------|
| **Maps FROM** | Trait synonym | Trait pattern |
| **Maps TO** | METPO phenotype class | Chemical entity |
| **Provides** | Phenotype term ID | Chemical ID + Predicate |
| **Purpose** | Categorize traits | Link organisms to chemicals |
| **Edge type** | organism→phenotype | organism→chemical |
| **Example** | "GC percentage" → METPO:1000127 | "electron acceptor: sulfur compounds" → CHEBI:26833 |
| **Predicate** | has_phenotype | uses_as_electron_acceptor |
| **Maintained by** | METPO ontology team (remote) | kg-microbe project (local) |
| **Update process** | Pull from GitHub | Edit local file |

---

## Why They Cannot Be Merged

### Reason 1: Different Semantic Purpose

**METPO mappings answer:** "What phenotype/quality does the organism have?"
- Example: Organism has optimal temperature of 37°C
- Edge: `NCBITaxon:562 has_phenotype METPO:1000304`

**special_chemical_mappings answer:** "What chemical does the organism interact with and how?"
- Example: Organism uses sulfur compounds as electron acceptor
- Edge: `NCBITaxon:562 METPO:2000008 CHEBI:26833`

### Reason 2: Different Data Requirements

**METPO mappings need:**
- Trait synonym (e.g., "optimal temperature")
- METPO phenotype class (e.g., METPO:1000304)

**special_chemical_mappings need:**
- Trait pattern (e.g., "electron acceptor: sulfur compounds")
- Chemical entity (e.g., CHEBI:26833)
- METPO predicate (e.g., METPO:2000008)
- Biolink category (e.g., biolink:ChemicalEntity)

**Missing in METPO TSV:** Chemical entity ID column

### Reason 3: Compound Mapping

special_chemical_mappings is a **compound mapping** that provides TWO pieces of information:
1. **OBJECT:** The chemical entity (CHEBI:26833)
2. **PREDICATE:** The relationship (METPO:2000008)

METPO mappings only provide ONE piece:
- The phenotype class (METPO:1000127)

**You cannot split a compound mapping into the METPO TSV structure.**

### Reason 4: Maintenance and Ownership

**METPO TSV:**
- Maintained remotely by METPO ontology developers
- Part of official ontology release
- Changes require ontology team approval
- Tagged releases (e.g., 2026-03-24)

**special_chemical_mappings:**
- Project-specific implementation detail
- Addresses kg-microbe's specific data patterns
- Can be updated immediately for project needs
- Not part of any ontology standard

**Adding project-specific chemical mappings to METPO TSV would:**
- Require ontology team buy-in
- Mix implementation with ontology
- Slow down project iteration
- Not be semantically appropriate

---

## How They Work Together

### Resolution Hierarchy in metatraits.py

```python
def _resolve_chemical_trait(self, trait_name: str) -> Optional[dict]:
    # 1. Check special mappings FIRST (parent classes, materials)
    trait_key = trait_name.strip().lower()
    if trait_key in self.special_chemical_mappings:
        return self.special_chemical_mappings[trait_key].copy()  # Returns CHEMICAL + PREDICATE
    
    # 2. Try standard ChEBI lookup
    chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)
    if chebi_id:
        return {
            "curie": chebi_id,            # Chemical entity
            "predicate": metpo_predicate  # From pattern match
        }
    
    return None

def _build_trait_mapping(self) -> None:
    # Builds trait → METPO phenotype mappings
    for synonym, metpo_data in self.metpo_mappings.items():
        self.trait_mapping[synonym] = {
            "curie": metpo_data["curie"],       # METPO phenotype class
            "predicate": "biolink:has_phenotype"
        }
```

**They serve complementary roles:**
- **METPO mappings:** General trait categorization (phenotypes/qualities)
- **special_chemical_mappings:** Specific organism-chemical relationships

---

## Alternative: Could METPO TSV Be Extended?

**Theoretically:** Yes, METPO TSV could add columns for chemical objects

**Practically:** No, because:

1. **Scope creep:** METPO is a phenotype ontology, not a chemical relationship database
2. **Redundancy:** ChEBI/ENVO/FOODON already provide chemical entities
3. **Maintenance burden:** METPO team would need to maintain thousands of chemical mappings
4. **Not their role:** METPO defines predicates and phenotypes, not specific chemical bindings

**Better approach:** Keep chemical mappings separate (current implementation)

---

## Comparison to Other Mapping Cases

### BacDive Mappings
```python
self.bacdive_metpo_mappings = load_metpo_mappings("bacdive keyword synonym")
```
- Maps BacDive keywords → METPO phenotype classes
- Example: "aerobic" → METPO:1000602
- **Same type as METPO mappings** ✅ Can use METPO TSV

### Madin et al. Mappings
```python
self.madin_metpo_mappings = load_metpo_mappings("madin synonym or field")
```
- Maps Madin field names → METPO phenotype classes
- Example: "growth temperature" → METPO:1000304
- **Same type as METPO mappings** ✅ Can use METPO TSV

### special_chemical_mappings
- Maps trait patterns → CHEMICAL ENTITIES + predicates
- Example: "electron acceptor: sulfur compounds" → CHEBI:26833 + METPO:2000008
- **Different type from METPO mappings** ❌ Cannot use METPO TSV

---

## Recommendations

### ✅ Current Implementation is Correct

Keep `special_chemical_mappings.tsv` as a separate local file because:

1. **Semantic clarity:** Clearly separates phenotype mappings from chemical mappings
2. **Flexibility:** Can be updated quickly without ontology dependency
3. **Appropriate scope:** Project-specific implementation, not ontology standard
4. **Maintainability:** Clear ownership and update process

### ✅ Document the Distinction

Ensure documentation clarifies:
- METPO mappings: trait → phenotype class
- special_chemical_mappings: trait pattern → chemical + predicate

### ❌ Do NOT Add to METPO TSV

**Reasons:**
- Wrong semantic type (chemicals vs phenotypes)
- Wrong maintenance model (local vs ontology)
- Wrong data structure (compound mapping vs simple mapping)

---

## Conclusion

**Q: Can special_chemical_mappings.tsv be added to METPO ontology TSV?**

**A: No.** They are fundamentally different mapping types:

| METPO TSV | special_chemical_mappings |
|-----------|---------------------------|
| Trait → Phenotype | Pattern → Chemical + Predicate |
| Remote ontology | Local implementation |
| Single value | Compound mapping |
| Phenotype categorization | Chemical relationship |

**The current implementation (separate files) is architecturally correct and should be maintained.**

---

## Summary Table

| Feature | METPO TSV Mappings | special_chemical_mappings | Can Merge? |
|---------|-------------------|---------------------------|------------|
| **Source** | Remote (METPO GitHub) | Local (kg-microbe) | ❌ |
| **Maps to** | METPO phenotype classes | Chemical entities | ❌ |
| **Provides** | Phenotype ID | Chemical ID + Predicate | ❌ |
| **Edge type** | has_phenotype | metabolic predicate | ❌ |
| **Maintenance** | METPO team | kg-microbe team | ❌ |
| **Purpose** | Trait categorization | Chemical relationships | ❌ |
| **Data structure** | Simple mapping | Compound mapping | ❌ |

**Verdict: Keep them separate** ✅
