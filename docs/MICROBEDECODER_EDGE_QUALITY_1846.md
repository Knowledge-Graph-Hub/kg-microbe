# MicrobeDecoder source observations and edge quality

Issues [#1846](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1846) and [#1827](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1827) distinguish unsupported graph assertions from the source's original observations. A hash in a source Attribute ID is not itself an error: the readable label, source field, complete literal, record identity and evidence tier make the observation interpretable.

The BacDive snapshot is audit-only by default. `MICROBEDECODER_INCLUDE_BACDIVE_SNAPSHOT=true` explicitly enables the historical graph representation; both modes retain the native finite join refusals and original observations. The selected Boolean mode is bound in the native producer contract. An admitted run cannot change mode during finalization or replay.

Exact Bergey `Other` metabolism and `Not reported` substrate values are retained in `reported_observations.tsv`; they do not assert biology or negative growth. Every emitted `IMG:*` genome endpoint is declared as `biolink:Genome` with MicrobeDecoder provenance. Genome membership remains `biolink:in_taxon`, not taxonomic identity.

## Thirty reviewed FAPROTAX labels

The finite policy is `mappings/canonical/microbedecoder_faprotax_dispositions.tsv`. Twenty exact source-column/literal combinations retain their original `biolink:has_attribute` assertions and receive one of six native METPO `has_attribute_type` classifications. The original assertions remain `prediction` / `computational_model` with `infores:faprotax` provenance. Oxygen, host and other qualifiers stay in the literal; broader classification does not replace them or establish independent experiments. Ten unsupported combinations are audit-only, with their complete original claims preserved.

The six classifications are chemoheterotrophic (`METPO:1000636`), methylotrophic (`METPO:1000651`), photoautotrophic (`METPO:1000656`), photoheterotrophic (`METPO:1000657`), plant pathogen (`METPO:1004003`) and human pathogen (`METPO:1004004`). Exact labels, categories and active status must match the consumed ontology-owned export. No global synonyms or ontology stubs are added.

The review corrected wrong identifiers and unsupported implications in the requested table ([#1847](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1847)): for example, the proposed symbiont and parasite IDs actually mean spore shaped and spiral shaped; the proposed gut ID means circulatory system. Human association does not entail symbiosis, and anoxygenic photoautotrophy does not establish the Calvin cycle or a dark reaction. Human-pathogen subgroups do not establish a disease event in a patient.

The pinned Biolink 4.4.2 `has phenotype` domain/range do not match taxonomic classes and the ontology-owned class declarations. [#1850](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1850) therefore preserves the existing reported-Attribute model: `has attribute` relates the taxon to its reported Attribute, and `has attribute type` is a node property classifying that value. Neither the taxon nor the ontology class is retyped.

## Evidence and validation

The official FAPROTAX1.2.12 ZIP is `https://pages.uoregon.edu/slouca/LoucaLab/archive/FAPROTAX/SECTION_Download/MODULE_Downloads/CLASS_Latest%20release/UNIT_FAPROTAX_1.2.12/FAPROTAX_1.2.12.zip`, SHA256 `87e229e5201c23f8286aeb5f092f50a95bfe6281c7746d89a50c0aac11a5923c`. Its `FAPROTAX.txt` member is SHA256 `e5b9eead9f936316410c1a3d58aaa5fe4c2fafb8e859d250796ac70486c12963`. This supplies group semantics; it does not prove which version generated the pinned MicrobeDecoder CSV.

The audit retains every original occurrence, unsplit source cell, complete original/emitted claim and finite disposition/evidence. Independent native replay requires the full source CSV, policy and ontology identity, exact ordered audit occurrences, complete emitted edge multiplicity and native Attribute declaration/type. Graph deduplication remains distinct from audit occurrence conservation. Finalization and merge admission retain these guards.

The issue's thirty row counts sum to **42,487**, while its stated subtotal is **42,483**. These historical reported numbers are not a current regeneration result. Full original and changed run evidence belongs under `data/edge-quality-20261110`; no historical graph is claimed regenerated without a genuine recorded producer execution.
