# Finite ENVO/PO native evidence

These are smaller, independently hashed excerpts, not complete ontology files.
`origin.json` distinguishes each complete selected source hash from its fixture
hash and records the complete selected native witness. Tests explicitly re-pin
only the fixture bytes; they do not bypass witness, policy or lifecycle checks.

The ENVO fixture comes from the pristine 2026-06-26 release, SHA-256
`c3c288b9d95cf1e62b0146bcb2a365bdbd294b0072bbf2efab8819e5db8fff2b`.
Issue #1338 corrects the earlier pin to a locally filtered derivative of that
same release. All five selected class declarations and both reviewed category
paths are unchanged. The full selected witness additionally preserves the
native `ENVO:01001436 is_a OBI:0000011` assertion.

`OBI:0000011` is explicitly obsolete in the same authority. Its complete
declaration and the extra parent assertion are preserved here as evidence, not
used as live category ancestry, a new output edge, or an automatic replacement
with `COB:0000035`. Existing ontology preprocessing drops obsolete declarations
and their incident edges only in its private derived conversion member.

The fixture also includes the complete original ten PREGO retired declarations
and four live ENVO replacement declarations, rejoined to that same pristine
release. This permits both consumers to be exercised with one native authority.
No finite-category membership, category choice, PO authority, or PREGO identity
policy is changed. The existing six asserted-ancestry ENVO controls remain.
