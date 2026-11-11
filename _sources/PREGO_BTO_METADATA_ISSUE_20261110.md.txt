The EdgeMech pinned-release audit identified 367 PREGO BTO nodes without names.
PREGO emits their identifiers and dictionary synonyms, but no authoritative
names; the static ontology-stub input list does not cover these endpoints.

Use the existing declared BTO SemSQL download as a consumed, hash-bound metadata
input. Hydrate only BTO class IDs actually emitted by PREGO, retaining identifiers,
categories, source assertions and source-version provenance. Require an explicit
ontology class declaration and label; missing declarations stay unresolved with
an audit record. Preserve obsolete status without silently replacing IDs.
Dictionary synonyms are not an authoritative label fallback.

Acceptance: hermetic input, missing-label, deprecation and provenance-mutation
tests; one real retained-input canary before the 367-ID replay; persisted node and
audit artifacts. The available local BTO version is 2021-10-26, so the report must
state that version and leave new-release reconciliation explicit.

This repairs an upstream cause of https://github.com/CultureBotAI/EdgeMech/issues/36;
it does not rewrite the historical graph or count a bounded metadata replay as
complete PREGO transform and release regeneration.
