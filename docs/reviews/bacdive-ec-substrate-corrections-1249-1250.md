# Four finite BacDive EC/substrate corrections (#1249, #1250)

These corrections address four complete historical mapping rows, not a global
CHEBI:54684 replacement, a CAS identity export, or the complete #286 backlog.
Raw `bacdive_mappings.tsv` remains unchanged. The canonical policy retains all
eight original cells, including the trailing space in the glucoside name.
Actual matching uses complete cells, not historical physical line numbers.

| Original source line (reviewed snapshot) | Exact source assay | Target | Scope |
|---|---|---|---|
|119|API_ID32E_alpha GLU|CHEBI:91122|alpha-D-glucopyranoside / EC:3.2.1.20|
|28|API_rID32A_alpha GAL|CHEBI:546840|alpha-D-galactoside / EC:3.2.1.22|
|120|API_ID32E_alpha GAL|CHEBI:546840|same molecule; contradictory KEGG cell is audit-only|
|271|API_rID32STR_alpha GAL|CHEBI:546840|alpha-D-galactoside / EC:3.2.1.22|

The immutable test fixture retains complete original rows, complete native
ChEBI records and incident edges, selected native TSV rows, primary structural
facts/URLs, and scientific input hashes. Native CHEBI:91122's exact IUPAC
synonym and full InChI match [manufacturer 487506](https://www.sigmaaldrich.com/US/en/product/mm/487506),
which identifies alpha-glucosidase substrate use. Native CHEBI:546840's distinct
stereostructure matches [manufacturer N0877](https://www.sigmaaldrich.com/US/en/product/sigma/n0877).
The two stereospecific InChIKeys differ; equal formulas and CAS annotations alone
would not establish this identity. Official EC nomenclature corroborates
[alpha-glucosidase](https://iubmb.qmul.ac.uk/enzyme/EC3/2/1/20.html) and
[alpha-galactosidase](https://iubmb.qmul.ac.uk/enzyme/EC3/2/1/22.html).

Evidence caveats remain explicit: the glucoside ChEBI prose mentions beta-D-
glucopyranose despite its exact IUPAC name, parent, stereostructure and supplier
evidence agreeing on alpha glucoside. N0877's marketing subtitle names
alpha-glucosidase, while its formal product/application sections and EC authority
support alpha-galactosidase. The original conflicting text is documented, not
used as corroboration. Supplier records do not prove which commercial batch an
API kit used or substrate specificity of every enzyme in an EC class.

Line120's original [KEGG:C01083](https://www.kegg.jp/entry/C01083) denotes
trehalose, not nitrophenyl galactoside. `withheld_source_fields=KEGG_ID` clears
only that cell in the corrected in-memory row; its complete original claim
remains in the raw file, curated rule, immutable fixture and audit. No KEGG or
CAS identity edge, assay-to-reagent assertion, or taxon phenotype is introduced.

The selected native export does not declare CHEBI:54684 or an official alias/
replacement. Native absence is not proof of historical obsolescence, and digit
similarity to CHEBI:546840 is not the correction's basis. The raw ontology SHA
is `a5d40380ab78bde0e8b5a704dbee3cba2bcaa7608be46eebc2f4a92932516c9b`;
the reviewed legacy source SHA is
`f39e9753fe2879877b2cba51c9896f44515f3a5785e790deb0d0bd5ca02c9379`.
These are review witnesses, not runtime pins forcing future source snapshots.

## Producer boundary

The real run consumes the finite canonical policy and legacy mapping through
immutable snapshots before opening graph outputs. Malformed/duplicate policy
fields fail; changes within a recognized reviewed scope require new review.
Exact already-corrected rows are idempotent, and an absent cohort is normal.
Unrelated old-ID uses do not acquire either reviewed target. Source row
multiplicity is retained through correction, before ordinary graph deduplication.

`ec_substrate_corrections.tsv` is mandatory producer audit output. It retains
each original complete source row, actual physical ordinal, original and emitted
seven-field edge claims, reason, primary evidence URLs, source/policy locations
and original read hashes. The producer's final input guards verify the same
admission, including symlink targets; finalization and merge enforce the original
audit bytes through existing producer-audit hooks. Even an empty cohort writes
a header-only audit and binds both required consumed roles.

The existing EC edge predicate, relation and provenance tier are unchanged.
Ontology dependencies and ordinary finalization still govern native endpoint
closure. No unified artifact, immutable supported MIM table, release pin, raw
record, or shared finalizer is edited. A fresh real source rebuild and graph
reviews remain necessary; focused fixture tests are not production acceptance.
