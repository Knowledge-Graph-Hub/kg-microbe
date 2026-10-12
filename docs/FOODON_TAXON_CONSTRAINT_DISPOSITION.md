# FOODON organism-class taxon restrictions

## Decision and scope

Retain the 1,679 reviewed FOODON `biolink:in_taxon` projections with
`relation=RO:0002162`, literal direction, endpoints and FOODON provenance.
These are projections of native ontology class restrictions, not assertions
that a taxon classification is an individual organism in another taxon. This
documentation and regression package does not edit transformed or merged KG
rows, add a validator exemption, or claim strict Biolink conformance.

The finite diagnostic cohort has 1,679 distinct subjects and triples: 1,663
targets are NCBITaxon IDs and 16 are FOODON organism classes, including
cultivars. Each native OWL subject explicitly carries a subclass existential
restriction using `RO:0002162 someValuesFrom` the target. Thirty-five subjects
also express the same restriction in an equivalent-class intersection. All
1,714 matching restrictions are existential; none is universal.

An `in_taxon` restriction does not authorize `same_as`, `exact_match` or a new
`subclass_of` edge. Only 15 of these pairs separately have an asserted native
subclass axiom to the same target. Those independent assertions are not a
reason to convert the other 1,664 restrictions into hierarchy edges. FOODON
targets must not be replaced by guessed NCBI species identities.

## Strict schema limitation

The pinned Biolink 4.4.2 schema lists RO:0002162 as an exact mapping of
`in taxon`, with domain `thing with taxon` and range `organism taxon`.
Its `organism taxon` category descends from `named thing`, without the
`thing with taxon` mixin. KGM's organism-branch category projection therefore
produced the historical strict domain diagnostic for these class-level restrictions.
This historical cohort includes the separately reviewed wheat-kernel subject
FOODON:00005106, now categorized as Food by its own native-evidence correction.
Its valid in_taxon restriction is retained. The exact rebuilt graph must be
validated again; 1,679 is the reviewed historical cohort, not a promised new
validator finding count.

Preserve and report that diagnostic. Do not relabel all organism classes,
weaken the model, suppress validator output or infer taxon identity to obtain
a superficially clean validation result. This is a finite, evidence-backed
disposition, not a blanket exception for every OrganismTaxon in_taxon edge.

## Reproducible evidence

`tests/resources/foodon_taxon_constraints/manifest.json` records the exact
original FOODON JSON/OWL, RO JSON, pinned model and review-cohort identities.
The finite excerpts contain complete selected OWL subject declarations,
native endpoint declarations, ancestry edges and their original JSON
coordinates, historical assertion fields and the pinned model fragment.

`tests/test_foodon_taxon_constraints.py` reparses all complete selected OWL
declarations, rejoins literal assertions/provenance, verifies directed ancestry
against native edges, distinguishes the 15 separate subclass assertions, and
tests wrong direction/property/source/quantifier, annotation-as-axiom,
fabricated ancestry and invented hierarchy. A real ontology source-normalizer
test preserves all 1,679 rows unchanged. Tests do not consult production data.

The native full-source reconciliation and independent plan review found
1,679 direct restrictions plus 35 equivalent-intersection witnesses, with no
unresolved logical blank-node references in this cohort. Fresh producer
conservation and model/path/KGX reviews of the exact rebuilt archive remain
required; these tests alone do not establish release acceptance.
