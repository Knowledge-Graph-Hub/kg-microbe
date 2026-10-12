# Finite NCIT22 category native excerpts

These are immutable, complete selected declarations from the reviewed local
NCIT SemSQL snapshot, not a complete NCIT database. `native.json` preserves all
5,460 statements (including datatype/language and explicit definition absence)
for the 75 complete named ancestors consulted for the exact 22 IDs. Historical
module, policy, role and completion-contract names retain `ncit_eight` for
compatibility; the finite set is explicitly eight plus thirteen plus Lesion.

- Full selected `data/raw/ncit.db` SHA-256:
  `7d1245d10a80ab29ba02e7eab03b37dd9940cdd18f92855d44c95578584f6eb5`.
- Full selected Biolink 4.4.2 SHA-256:
  `b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e`.
- `biolink.json` preserves the exact eight selected class records and version,
  including deprecated Mammal as a negative control. It is an excerpt.
- `source_declarations.json` preserves the 38 actual native/imported producer
  declaration occurrences and their original line numbers and source names:
  the original14 plus24 from the new14 IDs.
- `extension_incident_edges.json` preserves all202 complete incident rows for
  the new14 IDs, with source filenames, line numbers and literal row SHA-256.
  `extension_source_headers.json` records their exact three source TSV headers.
  Tests reconstruct the literal source rows and compare their original hashes;
  test-only closure nodes do not claim to be recovered native declarations.

Independent review artifacts are
`data/resolve93-20260930.2qMze1/ncit-extension-independent-01.json` and
`data/resolve93-20260930.2qMze1/ncit13-categories-independent-round01.json`.
Test setup creates a real readonly-consumed SQLite database from these literal
statements and explicitly repins a private test policy to its excerpt bytes.
No fixture claims to have the full database digest. The production policy uses
the full native and model digests and is separately pinned in source code.

The original six food decisions and two conservative CellularOrganism decisions
are unchanged. The new thirteen decisions distinguish nine ChemicalEntity
classes, MaterialSample (Aspirate), PhysicalEntity (Parasite), CellularOrganism
(Protozoa), and ChemicalMixture (Middlebrook7H10). Each has complete native
declarations and its own supporting path; no parent/prefix propagation is used.

Lesion is a separately approved PhenotypicFeature projection following its
primary structural-abnormality definition and Finding parent. Its additional
abnormal-tissue-area wording is preserved. This categorization does not validate
the three BacDive `location_of` claims or approve any source-identity mapping.

Absent primary definitions remain explicitly empty for Sodium Pyrophosphate,
Bovine Serum Albumin and Potassium Aspartate, as for the original three food
terms. Native formula, registry and semantic-type evidence is preserved without
inventing definitions, a protein sequence, a salt/hydrate choice or an exact
supplier formulation. The policy carries a rationale for every new decision.

All categorization is native-class-only. The previous Sugar/Mucin dispositions,
ingredient identity decisions and source relationship dispositions remain
separate. A source record's use of an NCIT identifier is not thereby approved.
