# BacDive record-shadowing regression (#1173)

`run_records.json` is a synthetic, immutable run-path fixture, not a biological
curation assertion. It combines source-schema fields that previously appeared
only in separate helper tests: enzyme activity, matched keywords, routed
phenotypes, signed metabolite utilization, and record-local reference pointers.

The first record has two positive observations supported by different papers,
a negative observation, an unresolved pointer, and a missing pointer. The second
reuses reference ID 7 for a different paper. The third has a pointer but no
Reference block. An unrelated record DOI must not spread to every assertion.
The tests vary enzyme/keyword and top-level input shapes, but never replace
the utilization, phenotype, writer, or deduplication implementations.

Production failure: the enzyme loop replaced the outer record variable with a
scalar before `reference_dois`; keyword loops could replace it with a mapping
dictionary and silently lose citations. Later phenotype routing also received
the overwritten value. The regression checks actual emitted rows for all three
paths, rather than only the DOI helper or a spy's arguments.
