LPSN discarded source citation text when constructing DOI/PMID nodes, and PREGO
left BTO names blank even though a declared ontology input could supply them.
This preserves unique LPSN citations as explicitly described display labels and
hydrates emitted BTO classes from hash-bound SemSQL metadata with an admission
audit. Conflicts and missing authority remain explicit; identifiers and source
associations are preserved.

Real canaries preceded bounded replays: source citations cover 36,512 previously
unnamed publication IDs, and retained BTO release2021-10-26 supplies all367 BTO
labels. The existing merge fix also recovered eight EC names. Focused validation:
32 LPSN tests and151 BTO/PREGO/freshness/dependency tests passed. Final repository
gates and adversarial review are recorded below when complete.

See docs/EDGE_METADATA_REPAIRS_20261110.md for provenance, artifact hashes and
limits. Full producer/merged-release regeneration and absent IMG/INSDC names
remain under https://github.com/CultureBotAI/EdgeMech/issues/36.

Closes #1834. Closes #1835.
