# Combined material-scope candidate: isolated staging, 2026-09-29

Status: the accepted derived unified artifact and reviewed native-pair test are
staged in the isolated combined-materials worktree, after source integration at
`620c9c9ea9c5d3e5ab777cb635ab85f9438cd550`. The coordinator preserved the
production checkout and its mapping artifact, archive and user statistics.
The 19 native paired-artifact/predicate tests and 584 broader source-integration
tests passed after staging. Actual combined source replay/comparison, final
repository gates and CI remain pending at this checkpoint. This is not release
acceptance or evidence of fresh production transforms.

## Exact paired artifacts

| Role | SHA-256 |
| --- | --- |
| Previous Potato-only unified baseline | `09c44642ab13b234e89ce113f7510aa9efb56969e4b539cb7843b43dcb425ba7` |
| Staged unified candidate, 13,374,300 bytes | `67c48e1bf6bed1f1fef03a0da1d7d1b56af9fc72374dddd703c222fb36df3cd4` |
| Unchanged supported MIM table | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| Unchanged reviewed MIM release pin | `f082c05656a0910c85176eec7b41deeb77c27967aecb80393fddc262819b6d97` |
| Unchanged identity-only writer | `257fe4d8bf16f92eb78d5e375065e030ea56d7c1174d859fecd2baa80ac18c27` |
| Identity-policy fingerprint | `4670cbb9255bdac7e9654fc415c9bfd35e55955fea5f27865a74e55849810b4c` |
| Applied native paired-artifact test | `e77a1c342549097e94542dc8fcc4e424bb475eb94ddff0c47f6a781ff47bc7ad` |

Upstream remains immutable MIM commit
`1848b0fe521bc2462f165912fcf92d09ad9a8cec`, manifest
`9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af`:
1,747 supported exact mappings and 1,696 names. This is not a new upstream
release, repin or supported-MIM rewrite. The policy fingerprint binds the
curated exclusions plus the shared identity and CAS implementations.

## Completed candidate checks

The complete streaming delta removed exactly three generic CHEBI:86658 claims
(two exact, one close) and changed only `object_label` on four retained native
structural-synonym rows. All other row bytes/order and unrelated metadata stayed
identical. Only the description's policy fingerprint changed; the writer,
assertion dates, historical unified version and legacy predicate semantics did
not. The seven original complete rows and native synonym witness remain in the
[immutable P3556 fixture](../../../tests/resources/mediadive/p3556_scope.json),
SHA-256 `7c06f4e2179356ddf1d917a6938cba5e3bdf6669f42a29019b93963e4a70646c`.

The candidate contains **591,946 rows**, **120,183 distinct targets**,
**336,048 exact** and **255,898 close** matches, with no broad/narrow rows.
The coordinator independently confirmed these counts by a full gzip/CSV stream
under unchanged before/after candidate hashes.

Three serial native consumer phases completed with exit zero and settled
process groups: a second identity-only export and fresh reader processes with
synonyms enabled and disabled. The second export removed/relabelled zero rows
and reproduced the exact compressed candidate bytes. Both reader modes passed
their finite native controls. Generic lexical phosphatidylcholine can still
reach a class in synonym mode; that is not approval to assign the whole P3556
product to that class. The source-qualified local guard and real source replay
remain necessary.

The completed checks ran at frozen pre-BacDive-integration head
`b8f18b838f5797c9dc4f4a64451c27298713e7ef`; they are not represented as new
execution at the subsequent integrated/staged head. Local evidence resides in
the primary checkout under
`data/issue1224-quarantine-20260929.xjuS9H/combined-identity-candidate.9eHuMu/`:

- [Finite delta receipt](../../../data/issue1224-quarantine-20260929.xjuS9H/combined-identity-candidate.9eHuMu/review-delta-01/result.json):
  `a4ec8a0c7a3d30d46208a16ac034301bdb1dae8209cbb951681856b596f0af5d`.
- [Complete original/changed-row ledger](../../../data/issue1224-quarantine-20260929.xjuS9H/combined-identity-candidate.9eHuMu/review-delta-01/complete-row-delta.json):
  `13fbefd64155d220a75731dfecfd9e5ab64df3f29e42e561c705d266aad6e50c`.
- [Completed consumer receipt](../../../data/issue1224-quarantine-20260929.xjuS9H/combined-identity-candidate.9eHuMu/consumer-review-01/result.json):
  `fa785548ca557e87057acf2d19b4e543437d3e39e28e7b160641617dd90f1100`,
  status `PASS_FINITE_CANDIDATE_CONSUMER_CHECKS_ONLY`.

These project-relative evidence links refer to retained local data, not files
duplicated into the isolated worktree or a published release.

## Separate source changes and remaining acceptance

The seven-row mapping delta must not be conflated with recipe/assay changes:

- [P3556](../mediadive-p3556-scope-1241.md) retains the qualified whole product
  on its existing local ID and preserves full imported candidate evidence.
- [Qualified mixed Sugar](../mediadive-sugar-context-1245.md) uses its exact
  source-context decision. Generic supported MIM Sugar remains unchanged.
- [Two finite peptone holds](../mediadive-peptone-scope-1248.md) reject only the
  reviewed name/CID combinations; independent alternative targets are not
  globally banned. Their [26 original occurrences](../../../tests/resources/mediadive/peptone_scope.json)
  and all original matching legacy claims remain preserved.
- [Tetramethyl ammonium chloride](../tetramethylammonium-chloride-20260929.md)
  gains its finite existing-name route; unqualified tetramethylammonium is not
  the salt.
- [BacDive EC/substrate corrections](../bacdive-ec-substrate-corrections-1249-1250.md)
  match four complete original rows and preserve their full mandatory audit,
  including the withheld contradictory KEGG cell. They do not change this
  unified artifact or establish a global identifier replacement.

The [historical Potato promotion](../mediadive-potato-scope-20260929/PROMOTION.md)
and earlier MIM promotion records are unchanged. No historical receipt is
restamped as current acceptance. The updated paired-artifact test preserves
their CAS, Potato, native-provenance and generic Sugar/Mucin controls.

Next require approved real source replay/comparison with full
raw/quantity/provenance preservation and manual
node-delta review. Replay may precede or accompany frozen-head repository gates.
All four full gates, green exact-head CI and independent review are required
before PR merge. A fresh all-15-source transform batch, candidate-only merge,
source-to-merged evidence retention and final KG reviews remain separate release
requirements. This checkpoint does not close the broader #286 backlog.
