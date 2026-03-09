---
name: metpo-ontology
description: Finds patterns so metatraits output follows KGX format and METPO semantics without adding extra terms. Use when working with unmapped traits, metatraits transform output, KGX format, trait ontology mapping, or label-to-CURIE resolution.
---

# METPO Ontology and Metatraits Conformance

## Purpose

Find patterns so metatraits output follows KGX format and METPO semantics. Do **not** add extra terms—use only existing ontology terms.

## Instructions

1. **Allowed ontologies**: Metatraits should express traits using **GO, CHEBI, EC, METPO, and RHEA** only.

2. **Ontology data location**: `data/transformed/ontologies/` (nodes/edges for these ontologies).

3. **Known unmapped relationship types**: Reference `docs/metatraits/unmapped_traits_unique.tsv` for relationship types derived from `unmapped_traits.tsv` and taxa in `data/transformed/metatraits/`.

4. **Label-to-CURIE mappings**: [https://metatraits.embl.de/traits](https://metatraits.embl.de/traits) shows relations between labels and CURIEs for chemicals, enzymes, etc. Use this to resolve unmapped traits—look up the mapping between term labels and term CURIEs.

5. **Conformance**: Ensure output conforms to KGX format and METPO semantics; do not introduce new terms.

## Reference Material

- **Metatraits traits browser**: [https://metatraits.embl.de/traits](https://metatraits.embl.de/traits) — label-to-CURIE mappings for chemicals, enzymes, and other terms (use when resolving unmapped traits)
- **Ontology data**: `data/transformed/ontologies/` (GO, CHEBI, EC, METPO, RHEA)
- **METPO**: [https://github.com/berkeleybop/metpo](https://github.com/berkeleybop/metpo) — Microbial Ecophysiological Trait and Phenotype Ontology (Berkeley BOP)
- **OMP**: Ontology of Microbial Phenotypes (related, broader)
