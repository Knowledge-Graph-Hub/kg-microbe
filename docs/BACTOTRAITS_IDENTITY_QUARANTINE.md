# BactoTraits mixed-strain row quarantine

The Jun-2022 BactoTraits table's data row 8521 identifies BacDive 17851 and
*Rubritalea squalenifaciens*, but gives the culture accessions DSM 19353 and
JCM 14586. Those accessions identify *Thioprofundum lithotrophicum* strain 106.
BacDive 17851 instead maps to the nominal DSM 18772 strain. The discrepancy is
tracked in [#1865](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1865)
and [EdgeMech #130](https://github.com/CultureBotAI/EdgeMech/issues/130).

Primary identity checks use [DSMZ DSM 19353](https://www.dsmz.de/collection/catalogue/details/culture/DSM-19353),
[JCM 14586](https://www.jcm.riken.jp/cgi-bin/jcm/jcm_number?JCM=14586),
[DSMZ DSM 18772](https://www.dsmz.de/collection/catalogue/details/culture/DSM-18772)
and [BacDive 17851](https://bacdive.dsmz.de/strain/17851).

The maintained transform previously used the BacDive ID without testing this
reviewed conflict. It now withholds the entire exact mixed row. It does not
replace the row's name, accession numbers, taxon or trait values: the conflict
does not establish which source fields were displaced. Other rows retain their
existing behavior, including rows that have not received identity review.

## Maintained inputs

`mappings/canonical/bactotraits_identity_quarantine.json` is a finite reviewed
policy. Each decision binds one BacDive selector, the complete raw row's SHA256,
the original mapped taxon, identity fields, rationale and evidence URLs. The row
digest uses the same `source-record-json-canonical/v1` representation as the
retained EdgeMech source packet: Latin-1-decoded CSV fields serialized with
`json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True)` and hashed as UTF-8.

The reviewed whole-source hash and ordinal are historical provenance, not a
whole-file acceptance condition. Each run records its actual consumed source
hash and actual data-row ordinal. A source slice or later export can retain the
same reviewed row, but an absent, duplicated or altered selected row fails
preflight before existing graph outputs are opened. An altered or ambiguous
BacDive-to-taxon mapping also fails before graph emission. These cases need a
new source review; they cannot silently discard the disposition.

The policy is a declared `DATA_INPUTS` dependency. The exact policy, raw CSV and
BacDive taxon lookup are mandatory consumed inputs. Preflight and emission read
the immutable raw snapshot, and subsequent input changes prevent finalization.
The policy is curation: editing it requires review and regeneration, not merely
relabeling an old output's fingerprint.

## Output and validation

Every successful run writes `bactotraits_identity_quarantine.tsv`, including a
header for an explicitly empty decision cohort. It records the original raw row
as JSON, original mapped taxon, reviewed/actual source identities, row/policy
hashes, disposition and evidence. The report is a mandatory producer audit, so
its omission or modification prevents finalized-source and merge admission.

Synthetic offline fixtures exercise both a withheld mixed row and an emitted
control, source/policy/lookup drift, duplicate selectors, bounded slices and the
required consumption/audit contracts. They do not copy the source phenotype
table. The unchanged private source row is used separately for the retained
production-path canary.

The quarantine is a source-integrity correction. It is not evidence that the
nominal strain's phenotype is false, a completed graph-wide identity review, or
proof that any published graph release has been regenerated.

Another neighboring mismatch is tracked in
[EdgeMech #132](https://github.com/CultureBotAI/EdgeMech/issues/132). It requires
independent source review and does not broaden this finite disposition.
