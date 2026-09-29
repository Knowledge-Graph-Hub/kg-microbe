# Finite tetramethyl ammonium chloride alias (#1242)

This reviewed name route addresses a current coverage gap found while tracing
#286's recovered historical CAS cohort. It does not validate every historical
CAS assignment or authorize a graph release.

Current saved MediaDive compound 720 and solution 1577, recipe position 4,
explicitly name `Tetramethyl ammonium chloride`, with amount 1 g and g_l 1.
The source has no CAS field. Its finalized pre-change target is local
`mediadive.ingredient:720`. Native active CHEBI:7070 declares the complete
chloride salt, with preferred name `N,N,N-Trimethylmethanaminium chloride`,
synonym `Tetramethylammonium chloride`, and CAS annotation `cas:75-57-0`.

[MediaDive's ingredient groups](https://www.bacmedia.dsmz.de/ingredient-groups?asc=0&limit=100&order=name)
independently associates the exact spaced spelling with CAS 75-57-0 and formula
C4H12N.Cl. It separately lists unqualified `Tetramethyl ammonium`, which is not
the chloride salt. [PubChem CID 6379](https://pubchem.ncbi.nlm.nih.gov/compound/6379)
corroborates the chloride identity and distinguishes parent CID 6380. Public
records were checked on 2026-09-29; no immutable web-content checksum is claimed.
Independent agent review corroborated the source, native target, and finite alias.

Only one existing `ingredient_name_scopes.tsv` entry is added. It uses the
existing bounded name-scope normalization, not a new global whitespace-removal
algorithm. The target must already be declared by the selected mapping input.
The unqualified raw compound 1649 / solution 3797 recipe position 1 stays
`kgmicrobe.compound:tetramethyl_ammonium`; other counterions and hydrates receive
no new mapping. No public CAS value is inserted into either raw source record.

`tests/resources/tetramethylammonium_chloride.json` retains the two exact selected
raw records, their positions, prior targets, a labeled native-node projection,
and SHA-256 identities of the complete original source/native files. Tests use
small declared-target inputs; they never consult a live service. The fixture's
native xref is an annotation, not a newly emitted equivalence edge.

Immutable supported MIM and pin bytes are unchanged. Full producer replay must
still reconcile every changed target and node while preserving quantities,
source assertions and raw evidence. Final all-source freshness and merged-KG
review remain separate gates; focused tests are not build acceptance.
