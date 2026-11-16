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

## Retained single-row replay, 2026-11-16 UTC

The [replay launcher](../scripts/adhoc/replay_bactotraits_identity_130_20261115.py)
ran the actual transform on the original row and actual BacDive lookup slice.
It used existing NCBITaxon database statements through a read-only label adapter;
the queried label and DB/OWL release (`2026-07-12`) agreed. It did not rebuild the
ontology database, fabricate a label, or hash the entire 14 GB database. The
receipt pins its metadata and exact queried statements, source subsets, METPO
templates, mappings, implementation files and Python/package versions.

| Saved output | Baseline `ef27b97a` | Candidate `9c1fb3633` |
| --- | ---: | ---: |
| Assertions contributed by the mixed row | 21 | 0 |
| Nodes emitted by this one-row slice | 22 | 0 |
| Quarantine audit records | 0 | 1 |

The baseline includes the exact reviewed `NCBITaxon:1123071`
`biolink:has_phenotype` `METPO:1000703` assertion. The candidate's audit preserves
the complete original row, actual slice ordinal 1, reviewed ordinal 8521,
original mapped taxon, disposition and policy/source hashes. Its graph TSVs are
header-only. There were no unaffected real rows in this slice; unaffected-row
retention is covered by the separate synthetic control test, not this replay.

Private stages are `data/validation-bactotraits-130/baseline-v3-20261116/` and
`candidate-v3-20261116/`. Receipt SHA256 values are, respectively,
`0000d1fd631d4bbfddf1d4d378824485911435c7a0fa162c939cbfb55ce2556d` and
`f33f8387be6518514ebcde34b56687947d64897484db8abc3c72f889745c6599`.
Both runs used launcher SHA256
`060d7e4dbb6189051f989a4a9efbf55336408e4224ecba5a4975e710538ea90e`.
Persisted output hashes and receipt readback were checked before proceeding.

The first baseline stopped on an import-time cache write outside the stage,
recorded as [#1866](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1866).
Its partial stage and log remain preserved. The launcher now redirects dependency
caches into the private stage without changing `HOME` or weakening its write and
network guards. A fresh-process import regression passed before the fresh
baseline and candidate runs. All replay files use mode 0600 inside private
directories. Both successful runs made zero provider calls.

Separate adversarial review then found that the v2 receipts omitted the consumed
prefix registry ([#1868](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1868)).
The v3 launcher retains and hashes `prefixmap.json`, binds baseline/candidate
equality, directs URI conversion to that staged copy before producer construction,
and rejects original or staged input drift. Both registries have SHA256
`a11f11fc43db2d3d0ffd74aca08fbc1da08033074b355ef2e0a1d6d547c29762`.
Five focused launcher regressions passed before the fresh v3 replays. The v2
stages remain unchanged as superseded evidence. The obsolete full gate at
`df6bc8d58` was deliberately interrupted with exit 2 after this finding; its
partial test count is not a full-suite pass. Final validation uses a new run label.

These are actual producer outputs before source finalization, graph merge or
release publication. They establish this bounded quarantine behavior, not
biological falsity, model correctness, a complete source review or release
readiness. The original occurrence and source files remain unchanged. The
companion evidence record is [EdgeMech PR #135](https://github.com/CultureBotAI/EdgeMech/pull/135).
