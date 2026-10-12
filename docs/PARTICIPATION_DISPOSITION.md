# Finite participation disposition (#1277)

The historical review found 323 supplier assertions (242 distinct native
triples). Complete selected native OBOGraph inputs contain every original edge
and both endpoint declarations. This is a scientific disposition of that finite
cohort, **not a validator waiver, a new inference rule, or release acceptance**.

| Original relation | Historical assertions | Retained assertions | Predicate projection |
| --- | ---: | ---: | --- |
| RO:0000056 participates in | 28 | 28 | Exact `biolink:participates_in` |
| RO:0000057 has participant | 33 | 33 | Exact `biolink:has_participant` |
| RO:0004007 has primary input or output | 145 | 143 | Broader `biolink:has_participant` |
| RO:0002565 results in movement of | 109 | 109 | Broader `biolink:has_participant` |
| OBI:0000293 has specified input | 8 | 8 | Broader `biolink:has_participant` |

The two separately audited #1302 quarantines are PATO's original
`GO:0006082 / RO:0004007 / CHEBI:64709` and
`GO:0043603 / RO:0004007 / CHEBI:32988` restrictions. They must not be moved to
the broader GO:0008152 subject. Removing exactly these two leaves **321 supplier
assertions / 240 distinct triples**: 61 exact mappings and 260 generalizations.
The historical ledger retains all 323 rows. Fresh rebuilt outputs must still be
reconciled; these counts are not statistics for a newly accepted merge.

## What the evidence supports

The complete selected RO JSON supplies `RO:0004007 subPropertyOf RO:0000057`
and `RO:0002565 subPropertyOf RO:0040036 subPropertyOf RO:0000057`.
FOODON supplies `OBI:0000293 subPropertyOf RO:0000057` directly. The original
stronger `relation` must survive each broader predicate projection, with the
original subject, object and supplier evidence. Plain `has_participant` alone
does not convey movement, primary input/output or a plan-specified input.

RO:0000056 and RO:0000057 have a formal inverse axiom. The selected FOODON
OBI:0000293/OBI:0000295 declarations contain subproperty axioms and a textual
inverse definition, but **no formal inverse axiom between those OBI properties**.
The direct subproperty witness suffices; do not invent an inverse proof.

The full available FOODON/PATO/UBERON OWL files establish existential restriction
forms for 314 historical assertions, including two referenced blank-node forms.
The remaining nine ENVO assertions are independently verified OBOGraph class
projections; the selected raw tree has no ENVO OWL counterpart after an
ignored-inclusive search. No independent OWL quantifier proof is claimed for
those nine. The two quarantined GO statements also occur under their original
subjects in native OWL: their defect was later subject transfer.

`A subclass_of (R some B)` is not an instance-level relationship between the
class identifiers. It does not entail `B subclass_of (inverse(R) some A)`:
some B instances may never participate in any A. Generic KG paths must not
silently reverse that quantification or infer that every organism performs a
process. `capable_of` and relational-quality `towards` are not participation
evidence just because endpoint categories appear compatible.

## Pinned-model limitations remain visible

Biolink 4.4.2 describes participation between a continuant and a process, but
sets the continuant-side domain/range to `occurrent`. Both slots inherit
`related to at instance level`. The checked-in excerpt preserves those actual
fields, including the inconsistency; the local model is not patched.

Valid category corrections are not a substitute for those semantics. LifeStage
is an OrganismalEntity, not an Occurrent subtype in this model. ENVO includes
physical/environmental processes that are not necessarily biological processes.
133 endpoint occurrences (128 distinct supplier/ID pairs) lack explicit paths
to the checked BFO roots in their supplier imports. Missing imported axioms do
not demonstrate biological incompatibility, but also do not prove universal
domain/range compatibility. Strict findings must remain reported explicitly.

## Evidence and regression boundary

`tests/resources/participation_disposition/` contains a hash-bound property/model
excerpt, a separate 323-row historical ledger, and seven representative native
OWL/OBOGraph contexts. Original file SHA-256 values and exact native JSON
coordinates are preserved. Endpoint excerpts in the ledger deliberately retain
only ID, label, class type and native coordinates; they are not complete native
ontology exports. Complete property and selected OWL declarations remain in the
other fixture files. No live service or mutable raw directory is needed for the
hermetic tests.

Tests check native subproperty direction, exact versus broader projections,
the literal model discrepancy, historical/quarantine conservation, native blank
nodes and a counterexample to invalid class-edge reversal. They also exercise
the common ontology normalization stage on all 321 retained assertions. That
bounded test is **not** a substitute for full standard-producer execution,
GO admission, or a model/path review of the rebuilt archive.

The #1322 regression controls join every historical subject, object, original
relation, projected predicate, supplier and endpoint declaration to its native
evidence and pinned-model mapping. The two quarantined GO subject transfers are
checked separately through their explicit original-subject records. Selected
complete OWL examples, including referenced blank nodes, are reparsed to verify
their existential witnesses rather than trusting extracted metadata. Property
paths must rejoin the selected native supplier edges, and OWL annotation links
must not be treated as logical subclass restrictions. Nine
contradictory-evidence tests refresh the fixture manifest and still require
semantic rejection; a refreshed hash is not scientific validation.

This package introduces no runtime allowance and makes no post-merge edits.
The remaining temporal and FOODON taxon-restriction cohorts have separate
dispositions; the approved 292 native-RO retention policy is not expanded here.
