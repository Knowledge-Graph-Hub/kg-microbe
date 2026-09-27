# Finite native NCIT category evidence (#1180)

`native.json` preserves the exact ten direct statements in the saved
`bergey-ontologyclass-cbb58a27-source-diagnostic.json` native authority list.
The native DB, diagnostic, raw CSV and pinned Biolink schema hashes are included.
Aliases are the unchanged native stub labels from that diagnostic. Anonymous
restriction identifiers remain evidence, not new named parents or identities.
The schema projection records its Food → ChemicalMixture → ChemicalEntity path.

These facts justify only a reviewed KGM category projection for two CURIEs:
Sugar as Food; Mucin conservatively as ChemicalEntity. The P106 disjunction
does not justify Protein or Enzyme, and Sugar is not changed to sucrose.
The three own-record substrate/citation projections explicitly retain their
current endpoints; generic Sugar contextual applicability is still open.

Tests copy this JSON to an opaque binary-input path and inject an OAK-shaped
reader derived from its exact statements. This tests actual stub dispatch,
writers and native-input binding without claiming the JSON is a real SemSQL
database. Extra conceptual-negative and additional-xref cases are deliberately
synthetic controls, not added native claims. Production native files are never
read or modified by these tests.

`test_ncit_native_authority_lifetime.py` additionally copies code and curated
inputs into a disposable checkout, then runs real registered source finalization,
completion-marker publication and public freshness admission (#1192). The saved
native contract retains the selected lexical locator, its resolved byte identity,
and the complete derived set of absent SQLite sidecars. Synthetic sidecar contents
exercise absence guards; they are not represented as a valid SQLite WAL. Null
authority requires a bound canonical NCIT output without either reviewed CURIE.
The tests cover post-completion and post-admission drift, same-byte retargeting,
tampered contracts, repeat finalization, and unchanged-size/restored-mtime mutation.
They do not run production transforms or claim SQLite-engine integration coverage.
