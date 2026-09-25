# Ingredient scope acceptance

Issue #1136 checks the reviewed producer bundle through consolidation, contextual
lookup, the real ingredient transform, source finalization, public KGX merge,
archive serialization and reload. It uses complete pinned Biolink 4.4.2 in fresh
offline subprocesses. The source-level scientific decisions remain those in
MIM #775; these tests do not approve additional ingredient mappings.

Run the complete focused gate:

```bash
poetry run pytest -q \
  tests/test_ingredient_acceptance.py \
  tests/test_ingredient_legacy_projection.py \
  tests/test_sssom_identity_policy.py \
  tests/test_ingredient_bundle.py \
  tests/test_ingredient_kgx.py
```

To retain the normal and synthetic candidate reports outside pytest's temporary
directory, choose new output directories:

```bash
poetry run python -m tests.ingredient_acceptance_runner /tmp/ingredient-candidate
poetry run python -m tests.ingredient_acceptance_runner /tmp/ingredient-reversed --reverse
poetry run python -m tests.ingredient_acceptance_runner /tmp/ingredient-products --synthetic
```

Each successful run writes `acceptance.json` after checking the archived graph.
A failure exits nonzero before that report is written. The report binds the
producer, native input versions, lookup, original claims and archived graph by
hash. It records `candidate_only` and `production_promotion_authorized: false`.
Tests compare semantic graph hashes across native-input row orders, since tar
container timestamps need not be reproducible. The fixture generator archives
the producer inputs deterministically.

| Check | Required behavior |
| --- | --- |
| Rifamycin | Three unqualified production/resistance lookups use CHEBI:26580; explicit SV uses CHEBI:29673. Family has no single CAS. |
| Xanthine | Source-scoped MIM ingredient uses CHEBI:17712; generic trait lookup uses CHEBI:15318. Native subclass edge survives without inherited CAS. |
| BSA | NCIT:C85253 retains verified current CAS; all seven recipe occurrences and their preparations remain intact. A7030 stays source-specific; A9647/A7409 remain unselected alternatives. |
| Registry claims | Complete source/status/evidence tuples survive. Acriflavine's current CAS is active; FDA SUPERSEDED and the source's reported old number remain separate claims. Invalid lysozyme CAS is excluded from active xrefs. |
| Products | Two explicitly synthetic catalog products share a CAS but retain distinct IDs. Two occurrences from the same synthetic source retain distinct preparations and scalar JSON text. |
| Broader alignment | Original legacy rows pass the real MediaDive writer, finalization and public merge as broad_match. Native ChEBI subclass assertions remain classification. |
| Admission | Unknown scope, unsupported predicates, invalid extension types, missing targets, unsupported capabilities, changed inputs and contradictory exact/nonidentity pairs are rejected or retained only outside identity lookup, as appropriate. |
| Unresolved materials | Lysozyme and sorbitan monooleate retain reviewed local IDs; no replacement CAS, Tween 80 identity or molecule is invented. |

The normal candidate has 20 reviewed identities, 18 registry claims, three catalog
records and ten occurrences: 71 projected nodes and 51 assertions. Merging the
independent native excerpt produces 73 nodes and 53 assertions, including the
two original ChEBI subclass edges. All 20 current CAS policies agree with the
existing reviewed implementation. The synthetic fixture adds two products, two
registry claims and two occurrences; it is clearly labeled as software test
data throughout the producer evidence.

The new lookup admission rejects a legacy companion that asserts both exactMatch
and broad/narrow/relatedMatch for the same unordered endpoint pair. Hashes do not
resolve a semantic contradiction. The historical production file contains 98
exact/broader pairs among 143 broader rows; its hash and an untouched conflicting
excerpt are recorded under `tests/resources/ingredient_bundle/native`. This is a
candidate rejection criterion, not automatic scientific adjudication or a
change to the historical production file. See #1147 and #1123.

Required capabilities are enforced when the original bundle is loaded; selected
lookup and source inputs are rechecked at publication boundaries. Registering
`mim_ingredients` does not add it to the default production batch, and a
`production` selection is refused. Fixture success does not grant release
promotion: #1123 still owns authorization, the actual affected producer closure,
coverage comparison and inspection of production merged output. The small native
excerpts certify their own bytes and behavior, not the complete production data.

Generation commands and source hashes are in
`tests/resources/ingredient_bundle/native/README.md` and the adjacent origin
files. After the focused gate, run the repository's full pytest/tox, Poetry lock
and generated-merge-config checks. CI runs these acceptance tests as part of the
ordinary test suite on every supported Python version.
