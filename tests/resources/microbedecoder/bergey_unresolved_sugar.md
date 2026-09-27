# Two unresolved Bergey Sugar observations (#1180)

This immutable fixture is a saved selected-record projection, not a newly
downloaded upstream dataset. It copies all fields present in the three saved
raw-record dictionaries plus their exact historical finalized substrate edges
and the two existing Sugar mapping-control rows from:

- `bergey-ontologyclass-cbb58a27-source-diagnostic.json`, SHA256
  `672d0bb62d363316ea5243b813a35ee4946fdf0ba734936589138d017c7c12d9`.
- Separate native/local contribution evidence:
  `bergey-ontologyclass-cbb58a27-node-contributions.json`, SHA256
  `11964539997e06c050327cb61e40f79a4d5caa4122836a5c9f037db920733252`.

Historical CSV records 1200 / LPSN 773071 and 6810 / LPSN 776427 each report
literal `sugar` in `Bergey_Substrates_for_end_products`, literal `NA` in
`Bergey_Text_for_substrates`, and their own DOI URL ending `gbm00239` or
`gbm00020`. These record/field uses do not establish the native NCIT Food
concept or sucrose. The approved policy preserves them as two distinct local
ChemicalEntity materials, not a shared `sugar` placeholder. The full source
record content, source name, field and literal token form the canonical-JSON
SHA256 identity; CSV row/column order and the source file digest do not.
Unrelated record-field changes alter that material ID, rather than aborting;
changes to the finite LPSN/field/DOI/explanation or old mapping route require
review and abort. Duplicate identical records share a material ID but retain
their distinct existing CSV digest/ordinal assertion locators.

The source field, literal value, consumes/RO:0002438, assertion sign,
provenance, own DOI, citation text and citation base64 are unchanged. The old
NCIT:C71939 target is retained only in `original_object`; no xref, same_as or
new identity edge is asserted. The original edge description is unchanged;
the local node description explains the unresolved-context disposition.

Record 944 / LPSN 783337 with literal `mucin` and DOI ending `gbm01282` is an
unchanged-endpoint negative control. The saved MIM:Sugar and native Sugar
mapping rows are positive controls through the real tiny mapping loader;
the shared mapping tables/native nodes are not edited by this correction.
Synthetic edits in tests separately exercise record reorder, duplicate rows,
different record context, missing/changed evidence, other fields/records,
mapping failures and full public miniature KGX archive preservation.

Tests write a new small CSV under `tmp_path`; its digest and ordinals correctly
describe that fixture CSV, never pretend to be original records 1200/6810/944.
The old literal locators in `historical_edges` remain historical evidence.
