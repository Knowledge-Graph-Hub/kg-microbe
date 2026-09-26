# Explicit identity routing (#1133)

The unified SSSOM reader classifies rows before indexing any identity-bearing
attributes. Legacy files retain the two explicit `kgm.name:` lexical shapes
(`canonical_name` exactMatch and `synonym` exact/closeMatch) and the separately
reviewed `recipe_equivalent_hydrate` route. Ordinary identity rows require
exactMatch. Other close/related matches and annotation predicates do not enter
name, synonym, formula or equivalent-xref lookup. Unknown predicates and any
predicate modifier, including negation, are quarantined.

The versioned MIM scope profile additionally requires SUPPORTED review,
compatible established scope/composition and explicit identity authorization.
Missing declarations, unknown profiles, incompatible scope and unsupported
review status cannot fall back to legacy identity behavior. The general
release bundle and independent proof verification remain gated by #1134/#1136.
The new profile is not a production pin change.

Broader/narrower direction continues to follow the declared SKOS/legacy
semantics. These relations retain separate parent indexes. Their unambiguous
object category is an endpoint annotation fallback, behind independent entity
metadata; it does not resolve a name or identifier. Conflicting fallback
categories are omitted. Parent-edge projection is owned by PR #1120.

`get_mapping_load_audit()` returns complete status, counts by route, explicit
policy-exclusion counts and up to 20 diagnostic source positions/triples.
Failed reloads invalidate cache success before rebuilding. The reader validates
column shape and preserves quoted multiline values containing `#`.

## Legacy snapshot audit

Compared the twelve serialized lookup indexes against PR #1130 at
`c4df95e3d17fcd36a27c59b67cf2b96c9467df89` using the same source bytes.
[index-audit.json](index-audit.json) records the source SHA256, index key counts
and SHA256 digests of `json.dumps(index, sort_keys=True, separators=(",", ":"))`.
All twelve indexes match the baseline exactly: 120,669 entities and 610,059
rows, with no quarantined rows in this legacy artifact. The 10 identity and
14 lexical exclusions are the existing reviewed case policy. This verifies
compatibility, not the scientific validity of every legacy assertion.

Review findings #1137 and #1138 have negative regression coverage for predicate
modifiers and category-only broader endpoints, including row-order reversal.
Scope validation is vendored from MIM with its exact origin and digests in
[contract-origin.json](contract-origin.json). Compare module ASTs after removing
string docstrings (formatter conventions differ); the packaged YAML is identical.
