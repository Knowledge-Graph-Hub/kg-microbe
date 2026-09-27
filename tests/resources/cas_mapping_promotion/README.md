# Prior assertions for invalid-CAS promotion

`prior_claims.tsv` is a literal, full-column subset of the **previous** tracked
unified mapping, SHA256
`fe54cd1a1dc14123b41bd8f08c9c42096cf2815b2ae5a5bb4ce4bd349041c98d`,
available at repository commit `409caa076db725ea0dc7c925d133ad61b22d8bfe`.
It is not extracted from the replacement candidate. Original row order and all
13 fields are preserved; every selected row occurred exactly once.

The fixed selection contains all 33 previously inventoried invalid-CAS endpoint
claims (32 ChEBI exact matches and one MediaDive close match), plus all 90
`chebi_xrefs` lexical assertions for their 32 ChEBI targets. The first cohort
must disappear; the second must remain unchanged. The selection is not the
unrecovered historical 234-CAS cohort from #286 or a general curation oracle.

Independent review matched the latter 90 full assertions to native ChEBI names
and synonyms from the unchanged native node table, SHA256
`c161f8aea7ffeb1a2557f24100b3b3b67bfd62196d484b33c675921154c8b152`.
The accepted reconstruction adds exactly those existing lexical assertions with
`source=native_ontology:chebi` and `mapping_date=2026-09-24`: 32 canonical exact
matches and 58 synonym close matches. Tests derive these two-field provenance
changes from this prior fixture, not from candidate-observed rows. They compare
all fields and multiplicities and retain the original assertions as controls.
This is provenance preservation, not new scientific identity approval; existing
competing lexical targets and scientific caveats remain unresolved.

Fixture SHA256:
`629198d090f7e45f7f17ce97a124eb9cad879b0bb066930b11ea8cf80ce15b2c`.
