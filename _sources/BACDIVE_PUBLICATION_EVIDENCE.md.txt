# BacDive item-level publication evidence

The metabolite-utilization emitter resolves each item's `@ref` against that record's `Reference` entries. The reference and utilization blocks both accept dictionary or list shapes; reference keys may be numeric strings or integers. Explicit multiple-reference lists are supported. Unresolved pointers do not borrow another item's citation.

`primary_knowledge_source` remains the scalar `infores:bacdive`. The `publications` field contains the existing BacDive record-page URL and the referenced publication DOI. Plain DOI, `doi:` CURIE, and DOI resolver-URL spellings normalize to one lower-case DOI token. Repeated equivalent evidence is deduplicated; different papers supporting the same predicate/object remain separate observations through source finalization and KGX serialization.

Catalogue URLs, malformed DOI fields, and BacDive's own record DOI are not treated as scientific publication citations. Conflicting publication DOIs for the same reference key are left unresolved rather than selected by input order. This performs identifier validation, not live DOI registration verification.

Scope is **metabolite utilization only**, replacing the unsafe provenance approach proposed in PR #776. Other BacDive sections retain their existing record evidence and do not gain record-wide DOI lists. Issue #770's broader statement-level citation coverage therefore remains follow-up work.

Offline regression fixtures are explicitly synthetic. Tests exercise the production utilization emitter and record writer, actual source finalization, and a public KGX archive roundtrip; they do not run the complete BacDive transform or require local ontology databases.
