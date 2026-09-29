# MicrobeDecoder source-value typing

Reviewed source values are retained as `biolink:Attribute` nodes. The optional
**node property** `has_attribute_type` identifies the native METPO class that
describes a reviewed source-column/literal pair. It is not an edge predicate.
No METPO categories, LPSN categories, source record identifiers, original
literal values, or evidence tiers are changed to make the model validate.

The pinned Biolink 4.4.2 schema declares `has attribute type` as a single-valued
Attribute slot with range OntologyClass. It does not make it a descendant of
`related to`, so checking domain/range alone would not authorize a new KG edge.
The slot uses the native class category, including OntologyClass; this is not
an attempt to retype METPO qualities as PhenotypicFeature.

## Evidence and query semantics

The original record-qualified `has_attribute` edges remain the observations.
Attribute identifiers are shared by exact source column and literal, not by
record. Multiple records using the same value therefore have separate source
edges to the same attribute, with one reviewed type on that node. That type is
KG-Microbe's normalization, not a new biological experiment or a statement
that every strain in the LPSN taxon has the property.

Node extensions separate the curation from the original observation provider:

- `has_attribute_type`: one native target CURIE, never a pipe list;
- `attribute_type_source`: KG-Microbe's project URI;
- `attribute_type_evidence`: the reviewed rule's evidence URLs;
- `attribute_type_rationale`: the rule's field-specific interpretation.

The `phenotype_normalizations.tsv` report still binds each use to its original
source record, column, literal and evidence tier. Its historical disposition
`reviewed_literal_grounding_not_graph_assertion` means no new organism-phenotype
edge is asserted; the class is now also queryable as node metadata.

A query must join an original source edge's object to the Attribute node ID,
then filter the node's `has_attribute_type`. It must return the edge's
`source_record`, `source_column`, `value`, `primary_knowledge_source`,
`knowledge_level`, and `agent_type`. Do not turn the result into a universal
species/strain phenotype or treat two records as independent experiments.

## Reviewed scope

The table contains 35 finite source-column/literal rules: 22 BacDive-origin
textual values (Gram stain, cell shape, oxygen tolerance), nine reviewed
numeric/sign codes, and four exact FAPROTAX labels (chemoheterotrophy,
photoautotrophy, photoheterotrophy, plant_pathogen). The latter are trophic or
host-type annotations, not biological process identities: their former local
`capable_of` process objects become reported source Attribute objects, using
`has_attribute`. They retain `infores:faprotax`, `prediction`, and
`computational_model`. Source spelling and source record provenance remain
unchanged. Qualified variants and generic phototrophy are not silently folded
into these reviewed types.

The nine codes are motility `0`/`1`, pathogenicity animal/human/plant `1`, and
indole/Voges–Proskauer `+`/`-`. Their field-specific meanings are established by
the immutable MicrobeDecoder preprocessing code at commit
`872726c257b39d14ffb1827df09127b5c8ef72bb`. The selected local source's 16,317
nonempty field cells and associated BacDive IDs match that commit's database
export by LPSN ID. Whole CSV hashes and headers differ: this is selected-cohort
compatibility, not a claim that the entire local database has that revision.
The immutable codebook receipt and hashes are in
`tests/resources/microbedecoder/phenotype_codebook.json`; individual curation
rows link the decoder, its field-mode call site, and native METPO targets.

Other codes, generic spore formation, unreviewed cell shapes, flagellar
arrangements and ambiguous values remain original attributes without a type.
The native spore-forming METPO definition is specifically about **endospores**;
decoding a generic source boolean is not sufficient to establish that scope.
The `+/-` assay token stays separate and untyped; contradictory `+` and `-`
observations are not combined into it. A negative assay outcome is not missing
data, and neither assay sign creates a chemical production/consumption edge.
No general numeric/sign decoder is applied to other fields.

## Contracts and regression tests

Every producer run validates exact mapping columns, allowed source fields,
single native class IDs, unique active authoritative declarations, expected
labels/categories, and read-time input fingerprints before opening outputs.
It never invents native target stubs. Source finalization and the actual KGX
archive serializer retain the optional node fields. Tests cover raw snapshot
edge byte identity with and without reviewed node typing, record/literal
identity, singleton slots, unreviewed values, FAPROTAX evidence tiers, and
actual merge/archive round trips of every curation field.
