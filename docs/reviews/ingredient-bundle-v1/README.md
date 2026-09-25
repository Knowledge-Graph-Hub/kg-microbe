# Ingredient bundle consumption review

Tracking: #1134; review finding #1140. Producer: MIM #775, implementing MIM #769
and #770. Identity predicate guard: #1139.

The consumer reads the actual 20-case producer bundle pinned in
`contract-origin.json` and `tests/resources/ingredient_bundle/origin.json`.
Source-scoped resolution, current xrefs, complete registry history and original
occurrences remain separate. All 20 canonical owners match the current curated
CAS policy; that policy is retained until the combined integration gate passes.

Round 1 passed 50 focused checks. Round 2 reproduced a missing-target hole after
serialization: a rehashed legacy input could omit CHEBI:29673 while retaining its
reviewed SV mapping. The reload path now streams usable declarations and requires
every authorized target. Nonidentity/quarantined rows do not provide an identity
endpoint. The regression and existing checks pass: 51 tests.

The tests use actual producer bytes; the small legacy/native declarations passed
to the consolidator are controlled test inputs. They establish software behavior,
not independent validation of the entire production ontology closure. The full
producer-to-transform-to-merge acceptance fixture and activation gate remain #1136.

The vendored schema is byte-identical to the producer's. Portable validator ASTs
match after the documented relative import, formatting and docstring adaptations.
No scientific review disposition or production release pin changes in this PR.
