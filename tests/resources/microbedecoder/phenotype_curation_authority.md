# Source Attribute typing authority

The canonical phenotype table contains **35 finite source-column/literal
rules**: 22 textual BacDive values, nine field-specific numeric/sign pairs,
and four FAPROTAX trait labels. They reference 34 distinct native METPO classes
(plant pathogen is used by both BacDive and FAPROTAX). The fixture
`metpo_nodes.tsv` holds those exact minimal declarations plus three existing
process declarations. No source transform creates or changes these ontology
nodes.

Reviewed types are emitted only through an Attribute node's singleton
`has_attribute_type` property, never as an edge predicate. Original
record-qualified source edges and the normalization report remain separate
evidence of each source use. See the current
[model and query contract](../../../docs/microbedecoder_observation_curation.md).

## Native authority and original textual cohort

- METPO release: `2026-06-12`.
- Native `data/raw/metpo.json` SHA-256:
  `fbef7ad9b436b28c59d142876eac3d98ffcf1777edab33a67e35fabd841d391a`.
- Original textual-cohort review's native
  `data/transformed/ontologies/metpo_nodes.tsv` SHA-256 (historical export
  receipt, not the expanded fixture's hash):
  `192d7dcb5f9f9facae2cd5d42f29a005a95d997d61bd613084c6d053cbe7f446`.

Each of the original 22 textual targets has a definition, phenotype ancestry, and a
related synonym whose literal matches the relevant BacDive field and whose
native synonym provenance is `https://bacdive.dsmz.de/`. Related synonyms are
field-scoped normalization witnesses, not universal exact synonyms or `same_as`.
The owner exports these classes as `biolink:OntologyClass`; the fixture and rules
preserve that category.

This textual cohort is Gram stain (3), oxygen tolerance (9), and defined cell shapes (10).
The nine other exact shape synonyms without textual definitions, generic
`other`, and flagellar descriptions remain outside the admitted rules.
In particular, `spore-shaped` does not imply spore formation.

The source vocabulary and multi-value assembly are witnessed by immutable
MicrobeDecoder commit `872726c257b39d14ffb1827df09127b5c8ef72bb`:

- [Gram stain export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/gram_stain.csv)
- [Cell shape export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/cell_shape.csv)
- [Oxygen tolerance export](https://raw.githubusercontent.com/thackmann/MicrobeDecoder/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/BacDive/data/oxygen_tolerance.csv)
- [Assembly helper](https://github.com/thackmann/MicrobeDecoder/blob/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/functions/helperFunctions.R#L568-L599)

## Nine numeric/sign rules

The same immutable commit's app preprocessing establishes the meanings of
standalone codes in nonnumeric fields. The complete 29-field mode vector,
decoder/call-site hashes, upstream database hashes, and selected local cohort
comparison are recorded in [phenotype_codebook.json](phenotype_codebook.json).
The nine admitted pairs are:

- `BacDive_Motility`: `0` and `1`;
- `BacDive_Pathogenicity_animal`, `_human`, and `_plant`: `1` only;
- `BacDive_Indole_test` and `BacDive_Voges_proskauer`: `+` and `-`.

All 16,317 nonempty selected local field cells and associated BacDive IDs match
the immutable upstream database by LPSN ID. Whole CSV hashes and headers differ:
this establishes **selected-field coding compatibility**, not the entire local
database's build revision. The decoder's other string or chemical rewrites
are not imported, and no general numeric/sign decoder is implemented.

Generic spore-formation codes remain untyped because the native METPO targets
specifically concern endospores. `+/-`, wrong-field signs/codes, pathogenicity
`0`, and other unreviewed values stay distinct and untyped. Negative assay
results are not missing data; positive or negative outcomes do not authorize
new chemical consumption/production edges.

## Four FAPROTAX trait rules

Exact `FAPROTAX_Type_of_metabolism` labels `chemoheterotrophy`,
`photoautotrophy`, `photoheterotrophy`, and `plant_pathogen` are typed using
native METPO definitions and their reviewed FAPROTAX 1.2.12 group evidence.
Each canonical row records its evidence URI and rationale; the
[current curation documentation](../../../docs/microbedecoder_observation_curation.md)
describes the source-grain limits. Generic or qualified variants do not acquire
these exact types automatically.

These four labels are trophic/host-type source annotations, not process
identities. Their former local `capable_of` routes become `has_attribute`
observations while preserving `infores:faprotax`, `prediction`,
`computational_model`, source record, literal, and citation. The nine numeric
rules above change node metadata only and do not change original BacDive
observation edge bytes.

## Model and provenance constraints

The resolver supplies no graph predicate/relation or evidence-tier fields.
Native targets retain their authority-owned `biolink:OntologyClass` category.
The pinned Biolink model excludes `OrganismTaxon` from the `has_phenotype`
domain and generic `OntologyClass` from its `PhenotypicFeature` range; this
patch does not assert that relation or retype either endpoint to admit it.
The chosen `has_attribute_type` node slot has range OntologyClass and is not
a relationship predicate. Node curation source/evidence/rationale are kept
separate from the original observation's provider and evidence tier.

Integration must retain every original source attribute, source record, literal,
field, and provenance tier. The report must retain separate positive and negative
observations instead of inventing a `variable` observation, and must not
propagate assertions to other organisms. Attribute nodes are shared by exact
source column/literal; their asserting edges carry record identity. Neither
shared node typing nor taxon-level joins establishes universal strain traits or
independent experiments. Current online BacDive predictions absent from the
saved source are not imported.
