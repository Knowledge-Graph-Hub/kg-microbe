# MediaDive material-scope fixtures

`catalase_scope.json` is an immutable literal extraction for issue #1290. It
contains all eight selected native compound-270 occurrences, their actual
one-based solution recipe positions, the native catalog record, four current
NCIT lexical mapping rows, and the relevant historical companion rows. The
`source_inputs` evidence records bind the original selected input bytes. Tests
pad omitted recipe positions with explicitly synthetic noningredient records;
they do not invent positive ingredient or human-protein evidence.

`catalase_native_assays.json` preserves the three actual native CAT wells from
`data/raw/assay_kits_simple.json`, each originally at zero-based well index 20.
These are enzyme-activity controls, not ingredient protein identities. The
original source-file SHA-256 is included. The real assay generators must keep
their EC:1.11.1.6 and GO:0004096 activity targets.

The finite policy in `mappings/ingredient_context_dispositions.json` retains
MediaDive's Catalase reagent catalog class as `mediadive.ingredient:270`, while
each observation preserves its complete qualifiers and quantities. This does
not claim identical supplier composition or assign human/bovine origin to the
shared node. The native NCIT:C61062 concept describes the human CAT gene
product; its 27 exact native statements and parent-database digest are kept in
`mappings/catalase_native_authority.json`. Native metadata remains available;
unqualified ingredient name/xref lookup is not proof of human protein identity.

Both policies and native excerpts are byte-pinned. Six historical grounding
claims in `mappings/catalase_historical_groundings.json` are audit evidence,
never runtime lookup authority. Actual current mapping candidates are collected
separately with their consumed file hash and row locator. The material-scope
audit is mandatory source output, not a post-merge rewrite.

Unsupported lexical identities become explicitly nonidentity native metadata
in reconstructed SSSOM (`skos:relatedMatch`, comment
`native_authority_metadata_only`). The shared classifier admits only the finite
native metadata shape without exposing it through ingredient name, formula or
xref identity lookup. Conservative reconstruction preserves complete original
identity candidates in its quarantine file. No accepted MIM mapping is changed
or any WITHHOLD disposition promoted.
