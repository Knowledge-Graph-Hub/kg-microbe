# Official Biolink 4.4.6 fixture epoch

The three YAML files are complete, unchanged upstream artifacts acquired from
the official v4.4.6 GitHub tag. `origin.json` records their source URLs, observed
HTTP results and exact byte identities. The two JSON files contain exact class
records selected from that model for the finite NCIT and MeSH policies; they
are explicitly excerpts and are checked independently against the complete
model. They are not generated from the production policy in tests.

Historical 4.4.2 fixture bytes and diagnostic profiles remain unchanged.
Historical ingredient acceptance explicitly selects its old full model and
reconstructs the original finite NCIT policy from its immutable 4.4.2 class
excerpt; its canonical policy identity is checked against the pre-upgrade
identity recorded here before private fixture-byte binding.

Review: `mappings/biolink_4_4_6_category_review.json`, issue #1724.
Native decisions are carried forward only for the existing finite class sets.
This does not approve incident relationship claims or a new diagnostic waiver.
