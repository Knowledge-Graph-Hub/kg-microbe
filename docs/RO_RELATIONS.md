# RO (Relations Ontology) Usage in kg-microbe

**Last Updated**: January 10, 2026

This document lists all Relations Ontology (RO) terms used in kg-microbe transforms.

---

## Overview

The Relations Ontology (RO) provides standardized relation terms for biological and biomedical relationships. kg-microbe uses RO terms extensively to express semantic relationships between entities in the knowledge graph.

**RO Ontology**:
- **Source**: http://purl.obolibrary.org/obo/ro.owl
- **Download**: Included in `download.yaml`
- **Transform**: Processed by ontologies transform
- **Documentation**: https://www.obofoundry.org/ontology/ro.html

---

## RO Relations by Category

### Organism Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002215 | capable of / biological process | Organism capability predicates |
| RO:0002438 | trophically interacts with | Organism to carbon substrate interaction |
| RO:0001015 | location of | Organism to isolation source |
| RO:0002200 | has phenotype | Organism phenotype relationships |
| RO:0002551 | has gene | Organism to gene relationship |

### Molecular Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002327 | enables | Protein/gene enables molecular function |
| RO:0002436 | molecularly interacts with | Chemical-protein interactions |
| RO:0002233 | has input | Reaction/process has chemical input |
| RO:0002234 | has output | Reaction/process has chemical output |
| RO:0002333 | enabled by | Process enabled by enzyme |

### Process Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0000056 | participates in | Entity participates in process/assay |
| RO:0000057 | has participant | Process has entity as participant |
| RO:0002331 | involved in | Gene/protein involved in biological process |

### Structural Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0001025 | located in | Protein/component located in cellular location |
| RO:0001000 | derives from | Protein derives from organism |
| RO:0000052 | related to | General relatedness |

### Functional Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0000087 | has role | Chemical entity has functional role |
| RO:0002205 | has gene product | Gene has protein product |
| RO:0002326 | contributes to | Protein contributes to disease |
| RO:0002350 | member of | Gene is member of ortholog group/COG |

### Disease-Microbe Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:0002610 | correlated with | Disease-microbe abundance correlations (Disbiome, Wallen et al) |

### Homology Relations

| RO Term | Label | Usage |
|---------|-------|-------|
| RO:HOM0000017 | orthologous to | Gene orthology relationships (KEGG KO) |

---

## Transform Usage

### Exact native ontology assertions (#1277)

The finite policy `mappings/native_ro_predicate_dispositions.json` retains 516
reviewed supplier assertions in ontology transform outputs with their exact native predicates:

| Native predicate | Supplier | Assertions | Projection rejected |
| --- | --- | ---: | --- |
| RO:0002216, capable of part of | UBERON |157| realized participation |
| RO:0002216, capable of part of | PATO |21| realized participation |
| RO:0002503, towards | PATO |6| active involvement |
| Six existence-boundary relations: RO:0002488/2489/2492/2493/2496/2497 | UBERON / PATO |63 / 35| generic process temporal relation |
| RO:0002285, developmentally replaces | UBERON / PATO |8 / 2| process preceded-by |
| RO:0002082, simultaneous with | UBERON / PATO |11 / 6| broader temporal relation |
| RO:0002087, immediately preceded by | UBERON / PATO |7 / 1| broader preceded-by |
| RO:0002223, starts | UBERON / PATO |3 / 1| broader temporal relation |
| RO:0002229, ends | UBERON / PATO |2 / 1| broader temporal relation |
| RO:0002230, ends with (finite stage cohort only) | UBERON / PATO |1 / 1| broader temporal relation |
| Existing protected native relations, exact imported cohort (#1400) | MONDO |188| same broader projections as above |
| RO:0002229, ends (#1400) | ENVO |2| broader temporal relation |

The approved supplier extension preserves all original 326 records, eight
unchanged GO controls and fourteen RO declarations. Its 190 additional rows
are source-specific: 126 MONDO triples overlap the earlier cohort, 61 concern
HsapDv immediate-predecessor assertions, and one repeats ENVO sedimentation.
They remain distinct supplier assertions, not permission for a relation-wide
rewrite. The ENVO and MONDO release files and their exact graph IDs are pinned;
ENVO's native graph ID ends in `envo.json`, not `envo.owl`.

Capability to perform part of a process is not evidence of realized
participation or of capability to execute the entire process. Relational
quality dependence (`towards`) is not active participation. The ontology
transform changes only these projected predicates, preserving subjects,
objects, directions, native relations and source provenance. No intermediate
processes, replacements, or post-merge semantic edits are introduced.

The additional 108 temporal assertions were explicitly approved separately.
An anatomical entity's existence boundary is not process ordering, and
developmental replacement is not a claim that one process completed before
another. Native comments include unvetted or directionally ambiguous wording;
retention preserves their asserted direction without repairing definitions,
reversing endpoints or deriving new temporal consequences.

A separately approved 34-assertion extension retains exact ordering/synchrony
predicates on a finite supplier/subject/relation/object cohort. These broader
Biolink projections were model-declared narrow mappings, not demonstrated false
temporal claims; native retention preserves their more precise traversal meaning.
The remaining 28 assertions already have exact BFO-to-Biolink mappings and stay
unchanged. Eight GO-to-GO assertions using RO:0002230 are explicitly outside the
approved stage cohort and retain their original broader projection. The policy
does not apply a relation-wide replacement to them. Unexpected new assertions
of the protected relations fail closed.

Immutable scientific fixtures prove all 62 class restrictions as existential
`owl:someValuesFrom`, including two explicitly linked blank-node restrictions.
They do not assert a relation between every instance of both endpoint classes;
inverse properties do not license reversing class-level restrictions. Literal
upstream formula/comment inconsistencies and axiom annotations are preserved,
not repaired locally. Runtime evidence remains the full native JSON exports
of the pinned releases and the complete RO property declarations. The additional
OWL excerpts are scientific test evidence, not a claim of new runtime OWL
consumption.

The policy binds exact supplier/triples and RO property declarations. It also
binds each authority to one release (#1420):

- **Release file.** It records the upstream file's SHA-256: `envo.json` and
  `mondo.json` as published, and the `ro.owl`, `pato.owl` and `uberon.owl` the
  JSON is converted from. A converted JSON's own bytes are not pinned, so an
  in-place rewrite or a different serialization does not break a fresh checkout.
- **Release version.** The JSON must declare that release's `versionIRI`.
- **Reviewed content.** A canonical digest covers exactly the reviewed content:
  every supplier assertion that uses a protected relation, and the 14 RO property
  declarations.

`download.yaml` fetches those releases from their dated URLs. Full ontology runs
process RO before its consumers. An explicit PATO/UBERON/ENVO/MONDO run needs
`data/raw/ro.json`, converted from the pinned `ro.owl`.
Sanitization and KGX read private admitted copies, leaving native evidence
unchanged. Unexpected sources, changed native bytes, wrong projections,
missing/duplicate assertions and absent mandatory audits abort the run.

`data/transformed/ontologies/native_relation_dispositions.tsv` records original
normalization-input rows, canonical prior/final rows, native assertion objects,
RO declarations, consumed-input identities and the explicit disposition
`native_predicate_retained_not_strict_biolink_conformant`. Unrelated single-module
runs emit a mandatory header-only audit. Input and audit hashes remain bound
at source finalization and merge admission.

These numeric RO predicates are **not strict Biolink4.4.2 predicates**. The
installed strict KGX validator still reports them as invalid; tests preserve
that outcome. This finite scientific disposition does not modify the pinned
model, suppress strict errors, or certify the resulting merged graph. The
516 count describes full ontology-producer supplier coverage, not a new release
acceptance or a forecast of merged strict errors. Canonical `merge.yaml` still
excludes MONDO; this change does not modify that selection. ENVO's native RO,
parent and retirement roles retain the original selected authority locator,
not the private copy subsequently sanitized and filtered for KGX.
The LifeStage category also lacks the pinned model's Occurrent mixin: this
truthful category/model limitation remains visible, without category coercion,
model edits, strict-validation waivers or post-merge semantic rewrites.

### BacDive Transform
**File**: `kg_microbe/transform_utils/bacdive/bacdive.py`

**Relations used**:
- **RO:0002233** (has input) - Enzyme to substrate relationships
  - Example: `EC:3.5.1.5 → has_input → CHEBI:16199 (urea)`

---

### Bakta Transform
**File**: `kg_microbe/transform_utils/bakta/bakta.py`

**Relations used**:
- **RO:0002551** (has gene) - Organism to gene relationships
  - Example: `NCBITaxon:12345 → has_gene → gene:SAMN123_00001`

- **RO:0002205** (has gene product) - Gene to protein relationships
  - Example: `gene:SAMN123_00001 → has_gene_product → UniProtKB:P12345`

- **RO:0002327** (enables) - Protein enables molecular function
  - Example: `UniProtKB:P12345 → enables → GO:0005524 (ATP binding)`

- **RO:0002350** (member of) - Gene membership in ortholog groups
  - Example: `gene:SAMN123_00001 → member_of → COG:COG0001`

- **RO:0002331** (involved in) - Gene/protein involved in biological process
  - Example: `gene:SAMN123_00001 → involved_in → GO:0006412 (translation)`

- **RO:HOM0000017** (orthologous to) - Gene orthology to KEGG KO
  - Example: `gene:SAMN123_00001 → orthologous_to → KEGG:K00001`

---

### MediaDive Transform
**File**: `kg_microbe/transform_utils/mediadive/mediadive.py`

**Relations used**:
- **RO:0000087** (has role) - Chemical entity to functional role
  - Example: `CHEBI:16199 → has_role → CHEBI:78295 (nitrogen source role)`

---

### Madin et al Transform
**File**: `kg_microbe/transform_utils/madin_etal/madin_etal.py`

**Relations used**:
- **RO:0000087** (has role) - Chemical entity to functional role
  - Example: `CHEBI:17234 → has_role → CHEBI:78297 (carbon source role)`

- **RO:0001015** (location of) - Organism to isolation source
  - Example: `NCBITaxon:12345 → location_of → ENVO:00002030 (aquatic environment)`

---

### BactoTraits Transform
**File**: `kg_microbe/transform_utils/bactotraits/bactotraits.py`

**Relations used**:
- **RO:0002215** (capable of / biological process) - Organism capability predicates
  - Example: `NCBITaxon:12345 → capable_of → GO:0015976 (carbon fixation)`

- **RO:0002200** (has phenotype) - Organism phenotype relationships
  - Example: `NCBITaxon:12345 → has_phenotype → PATO:0001396 (motile)`

---

### UniProt Transform
**File**: `kg_microbe/utils/uniprot_utils.py`

**Relations used**:
- **RO:0001000** (derives from) - Protein to organism
  - Example: `UniProtKB:P12345 → derives_from → NCBITaxon:12345`

- **RO:0002327** (enables) - Protein to EC enzyme
  - Example: `UniProtKB:P12345 → enables → EC:3.5.1.5`

- **RO:0002436** (molecularly interacts with) - Chemical to protein
  - Example: `CHEBI:16199 → molecularly_interacts_with → UniProtKB:P12345`

- **RO:0000056** (participates in) - Protein participates in process
  - Example: `UniProtKB:P12345 → participates_in → GO:0006412`

- **RO:0001025** (located in) - Protein cellular location
  - Example: `UniProtKB:P12345 → located_in → GO:0005737 (cytoplasm)`

- **RO:0002326** (contributes to) - Protein to disease
  - Example: `UniProtKB:P12345 → contributes_to → MONDO:0005148`

- **RO:0002205** (has gene product) - Gene to protein
  - Example: `gene:SAMN123_00001 → has_gene_product → UniProtKB:P12345`

---

### Rhea Mappings Transform
**File**: `kg_microbe/transform_utils/rhea_mappings/rhea_mappings.py`

**Relations used**:
- **RO:0002233** (has input) - Reaction to substrate
  - Example: `RHEA:10000 → has_input → CHEBI:16199`

- **RO:0002234** (has output) - Reaction to product
  - Example: `RHEA:10000 → has_output → CHEBI:16234`

- **RO:0002333** (enabled by) - Reaction enabled by enzyme
  - Example: `RHEA:10000 → enabled_by → EC:3.5.1.5`

---

### Disbiome Transform
**File**: `kg_microbe/transform_utils/disbiome/disbiome.py`

**Edge Direction**: Disease → Microbe (flipped from previous implementation)

**Rationale**: Represents observational correlation between disease state and microbial abundance. The direction Disease→Microbe better captures the clinical observation perspective: "Disease X is correlated with increased/decreased abundance of Microbe Y"

**Relations used**:
- **RO:0002610** (correlated with) - Disease-microbe abundance correlations
  - Elevated cases use `biolink:positively_correlated_with`
  - Reduced cases use `biolink:negatively_correlated_with`
  - Example: `MONDO:0005180 → positively_correlated_with → NCBITaxon:1678`
  - Example: `MONDO:0005066 → negatively_correlated_with → NCBITaxon:853`

---

### Wallen et al Transform
**File**: `kg_microbe/transform_utils/wallen_etal/wallen_etal.py`

**Edge Direction**: Disease → Microbe (same as Disbiome for consistency)

**Relations used**:
- **RO:0002610** (correlated with) - Parkinson's disease to microbe abundance correlations
  - Higher PD abundance: `biolink:positively_correlated_with`
  - Higher control abundance: `biolink:negatively_correlated_with`
  - Example: `MONDO:0005180 → positively_correlated_with → NCBITaxon:239935`

---

## Constants Reference

All RO relations are defined as constants in `kg_microbe/transform_utils/constants.py`:

```python
# Core RO relations
TROPHICALLY_INTERACTS_WITH = "RO:0002438"
LOCATION_OF = "RO:0001015"
BIOLOGICAL_PROCESS = "RO:0002215"
HAS_ROLE = "RO:0000087"
HAS_PARTICIPANT = "RO:0000057"
PARTICIPATES_IN = "RO:0000056"
HAS_PHENOTYPE = "RO:0002200"
CAPABLE_OF = "RO:0002215"

# Molecular relations
DERIVES_FROM = "RO:0001000"
ENABLES = "RO:0002327"
MOLECULARLY_INTERACTS_WITH = "RO:0002436"
LOCATED_IN = "RO:0001025"
CONTRIBUTES_TO = "RO:0002326"
HAS_GENE_PRODUCT = "RO:0002205"
HAS_INPUT_RELATION = "RO:0002233"
HAS_OUTPUT_RELATION = "RO:0002234"
ENABLED_BY_RELATION = "RO:0002333"
RELATED_TO_RELATION = "RO:0000052"

# Bakta-specific relations
HAS_GENE = "RO:0002551"
MEMBER_OF = "RO:0002350"
INVOLVED_IN = "RO:0002331"
ORTHOLOGOUS_TO = "RO:HOM0000017"

# Disease-microbe relations
CORRELATED_WITH = "RO:0002610"
POSITIVELY_CORRELATED_WITH = CORRELATED_WITH
NEGATIVELY_CORRELATED_WITH = CORRELATED_WITH
```

---

## Non-RO Relations

kg-microbe also uses relations from other ontologies:

| Ontology | Relations Used |
|----------|---------------|
| **BFO** (Basic Formal Ontology) | BFO:0000050 (part of), BFO:0000051 (has part) |
| **NCIT** (NCI Thesaurus) | NCIT:C153110 (assessed activity) |
| **PATO** (Phenotype Ontology) | PATO:0001668 (associated with) |
| **SKOS** | skos:closeMatch, skos:exactMatch |
| **RDFS** | rdfs:subClassOf |
| **UPA** (UniPathways) | OBO:upa#has_alternate_enzymatic_reaction |

---

## Validation

To validate all RO relations against the downloaded ontology, use:

```bash
python scripts/validate_ro_relations.py
```

This script:
1. Extracts all valid RO terms from `data/raw/ro.owl`
2. Checks all relation values in transformed edge files
3. Reports numeric-only relations (missing `RO:` prefix)
4. Reports invalid RO term IDs

---

## Best Practices

1. **Always use constants**: Never hardcode RO values like `"RO:0002327"`
   - ✅ Good: `ENABLES`
   - ❌ Bad: `"RO:0002327"`

2. **Verify term validity**: Check new RO terms against the ontology
   - Use OLS Browser: https://www.ebi.ac.uk/ols/ontologies/ro
   - Or download and search local ro.owl

3. **Document new constants**: When adding new RO constants:
   - Add to `constants.py` with descriptive name and comment
   - Update this document with usage examples
   - Run validation script

4. **Prefer specific over general**: Use most specific applicable relation
   - ✅ Good: `enables` for protein→function
   - ❌ Bad: `related_to` for protein→function

---

## References

- **RO OBO Foundry**: https://www.obofoundry.org/ontology/ro.html
- **RO GitHub**: https://github.com/oborel/obo-relations
- **RO Documentation**: https://github.com/oborel/obo-relations/wiki
- **OLS Browser**: https://www.ebi.ac.uk/ols/ontologies/ro
- **Biolink Model**: https://biolink.github.io/biolink-model/

---

**Maintained by**: kg-microbe team
**Repository**: https://github.com/KG-Hub/KG-Microbe
