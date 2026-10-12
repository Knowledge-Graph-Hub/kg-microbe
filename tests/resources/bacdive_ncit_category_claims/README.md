# Four native BacDive source-classification observations (#1323)

`records.json` retains four complete, unedited native records from
`data/raw/bacdive_strains.json` (784,112,058 bytes; SHA-256
`57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2`).
The reviewed export has 99,392 records. The fixture is explicitly a selected
excerpt, not a byte-identical copy of that full export. Canonical structured
record digests in `mappings/bacdive_ncit_category_claims.json` bind the full
records independently of JSON whitespace and object-key ordering.

Native IDs 13026, 157411 and 157533 contain literal `#Lesion (incl. Necrosis)`
leaf categories in an Infection / Plant infections group. Native ID156949 has
a `#Parasite` leaf under Host Body Product / Plant, and two separate water/pool
isolation entries. The group arrays do not establish a one-to-one join to an
isolation entry. Neither clinical causation/necrosis nor parasitism/host identity
is inferred.

The finite decision retains the four native tags as record/coordinate-scoped
Attribute observations. Original full NCIT location rows, both original curated
mapping claims, all raw citation/context fields and exact source coordinates
remain in the mandatory producer audit. Missing catalog URLs are not invented.
The NCIT concepts and their separately reviewed categories remain available;
this is not a global ontology-target exclusion.

The original native array positions are 12915, 79951, 80491 and 80569. Test
subsets and legacy object-shaped source containers retain their own actual root
coordinates in the audit. Internal category-group indices are never filtered
or renumbered, preserving existing PRIDE and clinical scoped identifiers.

Tests cover the complete producer run and public finalization/admission, not
only a synthetic label lookup. Unrelated ontology/assay context is explicitly
supplied by the existing hermetic run harness; no live adapter is queried.
An independent full-native source-field replay is documented separately. That
bounded replay is not a complete fresh graph build or release acceptance.
