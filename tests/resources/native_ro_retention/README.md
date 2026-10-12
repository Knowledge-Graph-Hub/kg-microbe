# Native RO retention fixtures

These are deterministic, verbatim native JSON record excerpts from the
reviewed full PATO, UBERON, ENVO, MONDO and RO exports. `origin.json` records both full-source
and excerpt SHA-256 hashes separately. Tests explicitly substitute excerpt
hashes; they never claim an excerpt is the full production authority.

Since policy version 3 (#1420), each excerpt also carries its graph's
`meta.version`, the release the policy binds. Each excerpt contains exactly the
reviewed selected content, so its content digest equals production's. Fixture
policies therefore substitute only the upstream release-file binding, naming the
excerpt itself. The `full_source_sha256` values are the whole-file pins that
policies before version 3 carried. The history tests still rebuild those earlier
policies from them.

The original fixtures contain every one of the first 326 approved assertions, their native
class endpoints and all 14 complete RO property declarations. The original
184 capability/towards assertions are joined by 98 existence-boundary and
10 developmental-replacement assertions and 34 ordering/synchrony assertions,
with unchanged native direction.
`origin.json` separately records the temporal evidence and prior policy hashes.
One actual native
RO:0000056 participation assertion per supplier serves as an unchanged control.
No native definitions, labels or annotations have been spell-corrected.

The curated production policy is
`mappings/native_ro_predicate_dispositions.json`. Native predicates remain in
the main KG, with explicit strict-Biolink nonconformance. The ordinary KGX
conversion and strict-predicate test uses the full immutable4.4.2 model under
`tests/resources/ingredient_bundle/native`, not a fabricated passing schema.

## Additional ordering/synchrony evidence

`temporal62_native.json` preserves complete literal native class/property/XML
restriction stanzas, original namespace bindings, source-file hashes and native
line coordinates for the 62 reviewed ordering assertions. Both logically linked
blank-node restrictions and their distinct axiom annotations are retained.
There are 34 newly approved native predicates, 28 unchanged exact BFO
projections and eight separate GO-to-GO controls. This scientific evidence is
not represented as an additional runtime input: runtime consumes the pinned
full PATO, UBERON and RO JSON exports.

The JSON excerpts include all 326 retained assertions, eight unchanged GO
controls, all 28 exact BFO controls and the original participation controls.
Fixture hashes in `origin.json` remain distinct from full native input hashes.

## ENVO/MONDO supplier extension (#1400)

The original 326 records and eight controls are unchanged. The separate ENVO
and MONDO excerpts add exactly 2 and 188 supplier assertions, respectively,
for 516 producer-level assertions. MONDO remains excluded by the canonical
merge configuration; this count does not predict merged-graph exceptions.
All new class and edge dictionaries are verbatim native records. ENVO includes
one real obsolete class and both excerpts include real annotation properties
to exercise private-copy sanitation without changing the native read receipts.

`mondo_go_metadata.json` contains exactly 142 selected statement rows for the
45 GO imports in the MONDO excerpt (labels, namespaces, definitions and seven
alternative IDs), not an invented ontology or full database. `origin.json`
pins both this test-only excerpt and the independently reviewed source database.
The real parsing/finalization test also reuses the separately pinned immutable
UBERON temporal-category ancestry fixture; neither substitution changes the
production authority policy or bypasses finalization/admission.
