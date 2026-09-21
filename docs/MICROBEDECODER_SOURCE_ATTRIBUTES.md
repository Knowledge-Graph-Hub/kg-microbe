# MicrobeDecoder reported source attributes

Decision for [#1104](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1104),
scoped to the 27 `BacDive_*` snapshot columns. This does not change the broader
taxon/phenotype convention tracked in #643 or the taxonomic backbone in #834.

## Evidence and model

The reviewed transform emits 362,361 `has_phenotype` edges from these columns.
Their objects are ungrounded raw field tokens, not a curated phenotype ontology:
they include salt units (8,086), incubation periods (5,095), isolation-source
categories (66,194), numeric ranges, assay signs and undecoded 0/1 codes.
Attaching every token as a biological phenotype is therefore unjustified,
independently of the strict validator's category complaint.

The source now records:

```text
lpsn:<taxon> --biolink:has_attribute / SIO:000008--> kgmicrobe.source_attribute:<id>
                                                   category: biolink:Attribute
```

The attribute means **MicrobeDecoder reports this source field value for this
taxon record**, not that every organism in that taxon has a decoded phenotype.
Its node name explicitly says `reported <dimension>: <token> (source value)`;
its description states that no phenotype was decoded. The asserting edge keeps
`source_record` (source SHA256 plus CSV-record ordinal), `source_column`, `value`,
`value_encoding`, and `primary_knowledge_source=infores:microbedecoder`.

The new namespace deliberately distinguishes a reported field attribute from
the old `kgmicrobe.trait:*` phenotype placeholder identity. IDs are deterministic:
the readable source/column stem is followed by SHA256 of the JSON tuple
`[microbedecoder, source_column, exact split token]`. Different source dimensions,
inequalities and raw codes cannot collide. Identical field/value pairs can share
an attribute node, while edge-level source records distinguish observations.
No equivalence assertion is minted between old phenotype placeholders and new
reported attributes.

## Why this is not a validator workaround

Pinned Biolink 4.4.2 defines `has phenotype` as BiologicalEntity to
PhenotypicFeature. OrganismTaxon is a NamedThing, not a BiologicalEntity;
PhenotypicQuality descends from OrganismAttribute and Attribute, not
PhenotypicFeature. `has attribute` is Entity to Attribute with exact mapping
SIO:000008. The project explicitly kept this spec-faithful predicate in
[#1000](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1000#issuecomment-5581362580).

The new categories describe the actual source objects rather than adding a
second biological category to the taxon merely to pass validation. There is no
allowlist relaxation and no post-merge semantic rewrite.

Alternatives considered:

- Keep PhenotypicQuality and only change the predicate: still incorrectly calls
  raw unit/isolation/assay-code tokens biological qualities.
- Use METPO:2000102 (`has phenotype`): its domain is a material microbe and its
  range phenotype. It does not justify treating salt units or isolation fields
  as phenotypes. Its Biolink link is only `skos:closeMatch`, not equivalence.
- Retype LPSN taxa as OrganismalEntity/BiologicalEntity: changes taxon identity
  and does not fix the heterogeneous raw field semantics.
- Reify each source record/assay: useful if future work reconstructs experimental
  conditions and assay outcomes, but the current snapshot does not warrant
  inventing assays or material organism instances. Record-scoped provenance
  remains explicit on every attribute edge without those additional claims.

Future curated interpretations may add separate biological assertions only
with a documented field/code mapping, conditions and evidence. They must not
replace the original source observation. No `0`, `1`, `+`, `-`, Gram-negative
or numeric bound is automatically converted to a positive/negative phenotype.

The existing parser dropped a lone `-` as missing but retained it in a mixed
`+,-` cell. The snapshot-specific splitter now retains a lone `-` in the two
signed assay fields, `BacDive_Indole_test` and `BacDive_Voges_proskauer`, without
decoding it. Other empty markers and all other field conventions are unchanged.
The reviewed raw input contains 2,612 and 2,077 such cells respectively; their
4,689 newly retained observations are expected only after a source rerun and
are not a claim that the production merged artifact has already changed.

## Validation and migration

Hermetic fixtures exercise all 27 field families, positive/negative and coded
values, column-specific identities, numeric inequalities, repeat-run stability,
source-record distinctions, provenance, and actual KGX archive round trips.
A focused immutable excerpt of the pinned Biolink schema verifies both endpoints
and the SIO mapping; the same signature was also checked with BMT against the
complete local pinned model during the review.

Rerun `microbedecoder`, then merge with the new source output. Consumers that
previously read these raw snapshot observations through `has_phenotype` should
query `has_attribute`, scoped by MicrobeDecoder provenance and `source_column`.
The live BacDive transform, curated phenotype assertions from other sources,
LPSN identities, and strain/taxon `subclass_of` edges are unchanged.
