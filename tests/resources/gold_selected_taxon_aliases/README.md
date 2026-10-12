# Finite GOLD selected-taxonomy alias fixtures

`native_evidence.json` contains exact native rows for three explicit selected
NCBI alias resolutions affecting eleven original GOLD records. Source file
SHA-256s, complete target declarations, all 27 incident native GOLD rows and
original full-source coordinates are retained. Test staging creates excerpts;
their local record coordinates are deliberately different from the documented
original full-source ordinals. This is not a complete stand-alone graph.

The selected JSON is `ncbitaxon_removed_subset.json`, not the full raw NCBI
ontology or a name lookup. The native DB and selected JSON independently agree
on 53360→53362 and 659496→33920; 1194211→36030 in the taxdump converges because
the selected native 4927 declaration explicitly lists both retired IDs. No
organism identity, strain class, ecological location or excluded-branch waiver
is implied. Future changes to these finite source records or authority targets
require new review; unrelated native sources exercise a genuine zero case.

Evidence generation and independent complete native reconciliation are recorded
in issue #1327. The curated policy pins complete relevant target/source payloads,
not only labels or favorable fields. Tests construct separate, explicitly
synthetic corruptions to challenge fail-closed scientific/lifecycle behavior.

`producer_contexts.json` adds the actual native context required by the standard
GOLD producer: all eleven original referents, all 27 incident assertions, all 27
required declarations and seven complete ecosystem parent assertions. The
`record` and `ending_physical_line` fields in this saved witness refer to the
original full native files, not the test-created excerpt. Tests retain their
own local consumed-input hashes/coordinates separately. Five native Study links
remain excluded from graph output, and four root-only habitat assertions remain
uninformative; seven source-owned environment observations survive. A linked
Study's unusual title is preserved as source evidence, not endorsed as organism
identity. The raw source hashes are checked before and after fixture selection.
