# Phenotype normalization authority

The 22 phenotype rows in `metpo_nodes.tsv` are exact minimal declarations from
the local ontology owner's export. The three pre-existing process rows are
preserved. No source transform creates or changes these ontology nodes.

- METPO release: `2026-06-12`.
- Native `data/raw/metpo.json` SHA-256:
  `fbef7ad9b436b28c59d142876eac3d98ffcf1777edab33a67e35fabd841d391a`.
- Native `data/transformed/ontologies/metpo_nodes.tsv` SHA-256:
  `192d7dcb5f9f9facae2cd5d42f29a005a95d997d61bd613084c6d053cbe7f446`.

Every selected phenotype has a textual definition, phenotype ancestry, and a
related synonym whose literal matches the relevant BacDive field and whose
native synonym provenance is `https://bacdive.dsmz.de/`. Related synonyms are
field-scoped normalization witnesses, not universal exact synonyms or `same_as`.
The owner exports these classes as `biolink:OntologyClass`; the fixture and rules
preserve that category.

The cohort is Gram stain (3), oxygen tolerance (9), and defined cell shapes (10).
The nine other exact shape synonyms without textual definitions, generic
`other`, flagellar descriptions, signed assays, and numeric codes remain outside
this cohort. In particular, `spore-shaped` does not imply spore formation.

The source vocabulary and multi-value assembly are witnessed by immutable
MicrobeDecoder commit `872726c257b39d14ffb1827df09127b5c8ef72bb`:

- [Gram stain export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/gram_stain.csv)
- [Cell shape export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/cell_shape.csv)
- [Oxygen tolerance export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/oxygen_tolerance.csv)
- [Assembly helper](https://github.com/thackmann/MicrobeDecoder/blob/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/functions/helperFunctions.R#L568-L599)

That commit is a vocabulary and assembly witness, not a claim that it generated
the locally fingerprinted database. Current online BacDive records can contain
new predictions absent from the local snapshot; these are not imported.

The resolver adds neither evidence-tier fields nor graph predicate/relation
fields. It authorizes only a separate normalization report, not new graph edges.
The pinned Biolink model excludes `OrganismTaxon` from the `has_phenotype`
domain and generic `OntologyClass` from its `PhenotypicFeature` range. Neither
retyping native nodes nor choosing a weaker substitute relation is authorized.
The existing pinned-schema regression remains unchanged.

Integration must retain every original source attribute, source record, literal,
field, and provenance tier. The report must retain separate positive and negative
observations instead of inventing a `variable` observation, and must not
propagate assertions to other organisms. Future graph representation requires
an explicit ontology-owner and taxon/phenotype model review.
