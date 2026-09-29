# Eight material-name exclusions: paired promotion checkpoint

Status: **Installed in the isolated review branch; repository/replay/CI gates pending.**
2026-09-29. This is a paired mapping checkpoint, not a production release.

## Reviewed source and candidate

The source/policy/audit changes for #1262 and #1263 were reviewed at clean source
commit `d6a21f0d4234931c9a9435f033def48c0041e379`. This is the pre-promotion
execution epoch, not a future staged, merged or released commit.

| Role | SHA-256 |
| --- | --- |
| Historical unified baseline | `67c48e1bf6bed1f1fef03a0da1d7d1b56af9fc72374dddd703c222fb36df3cd4` |
| Accepted finite-delta candidate, 13,373,982 bytes | `59464e08017cc907a1240a4378d2462efc9e2c1b9d6c3cf0b08b4344ef695ae8` |
| Unchanged supported MIM table | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| Unchanged reviewed MIM pin | `f082c05656a0910c85176eec7b41deeb77c27967aecb80393fddc262819b6d97` |
| Unchanged identity-only writer | `257fe4d8bf16f92eb78d5e375065e030ea56d7c1174d859fecd2baa80ac18c27` |
| New identity-policy fingerprint | `559b47b3c946601350bd2351fc8686fd731038908a1c90277dfe94981c0573b0` |
| Reviewed historical-claim catalogue | `b94ecaa4935082a6ed79faddfa448ed3a1768a858a572bc63306d20f43701e03` |
| Immutable source/native/full-row fixture | `e6db6174173a12101875104c33478f1868f4454ddd296db8e46b47ab6119f126` |

The existing full-stream delta receipt
`issue1262-candidate-review/actual-delta-01/result.json`, SHA-256
`ffeb368239d12af206e1f6f421f737bdf92bc84980b3fdf4592a6e091faa6c83`,
accepted exactly thirteen complete lexical synonym removals and zero relabels.
All 591,933 retained rows remain byte-, order- and multiplicity-identical.
Unrelated metadata is unchanged; only the reviewed policy fingerprint changes.
The upstream MIM origin, supported product and pin are not changed or republished.

Terminal consumer receipt `issue1262-consumers/actual-consumers-02/result.json`
has SHA-256 `95adaf0d976f8b9930848cda622a00779100fc1fc9b9d03e16bb001a253703b9`.
It reports `PASS_CANDIDATE_CONSUMERS_ONLY` at the original d6a21f0 source epoch.
All four actual phases exited zero and settled: baseline cold reader, second
identity-only build, synonym-enabled cold reader and canonical-only cold reader.
The second build is byte-identical; all twelve complete reader indices preserve
unrelated entries, native IDs and controls. No alternative requires review.

The first attempt is retained as rejected evidence: its phases completed, but
review/planning documentation added during execution changed input-directory
membership. No guard was weakened or result restamped; the fresh second attempt
reran every phase with frozen directories and passed all terminal guards.

## Finite scientific scope and preservation

The eight exact source-material/native-target contradictions cover 289 archived
source observations. The policy withholds those pairs, not the native chemical
classes globally. Independently justified alternative targets are not banned or
automatically approved. Source `K2HSO4` remains unresolved; no corrected salt is
invented. Seven distinct nested Selenite-tungstate solution IDs and all raw
recipes, quantities and context remain separate.

The required catalogue retains all thirteen original complete mapping claims
and baseline ordinals as historical audit evidence, never active identities.
The immutable fixture also preserves the complete 133-row eleven-ID cohort:
98 rows on the eight held targets and 35 rows on chelator, kinetin and
TMAC-chloride controls. The native paired-artifact test requires exactly
that full-row Counter minus the thirteen original claims (120 retained rows),
unchanged control rows and all eight native canonical declarations/labels.
All older CAS, Potato, P3556, native-provenance and generic Sugar/Mucin assertions
remain. The post-installation native streaming test verified 336,048 exact /
255,885 close mappings and 120,183 distinct targets, including all finite
full-row, canonical-label and prior-policy assertions.

The companion source changes preserve producer-time audit bytes and bind
catalogue/policy inputs through ordinary finalization, including empty cohorts.
#1263 closes finite policy-spelling and reader-compatible target-whitespace
audit coverage gaps. Current and historical candidates retain their complete
fields, provenance and duplicate-row multiplicity; the audit records the actual
retained identity.

## Installation and remaining gates

Installation: the exact accepted compressed candidate was copied to a temporary
sibling, byte-compared, then atomically installed as W11's canonical unified
artifact. Its hash and the unchanged supported MIM/pin hashes were rechecked.
The previous unified bytes remain in Git and the retained baseline worktree.
The ensuing promotion commit is distinct from the original consumer execution
epoch. ROOT and historical receipts are untouched.

Native-pair/focused tests after staging: **193 passed in 7.81 seconds**, exit0.
The three modules were `test_sssom_asymmetric_direction.py`,
`test_mediadive_material_alias_policy.py` and
`test_mediadive_reviewed_material_audit.py`. JUnit SHA-256:
`9f2656f57f31bf695f8effe011e4e44baa2d56c23cc31f40e4d30fe5b9d250e6`.
Actual whole-MediaDive replay, complete edge/audit comparison and manual node
review: **PENDING**. All four repository gates and exact-head CI: **PENDING**.
Historical promotion records remain unchanged; actual consumer failures remain
distinct failed evidence, not relabelled success.

This checkpoint does not establish fresh production transforms, merged-graph
acceptance or publication permission. The all-15 rebuild and candidate archive
acceptance remain separate. It does not close the broader #650 or #286 work.
