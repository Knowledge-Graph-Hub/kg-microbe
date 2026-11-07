# Reviewed MIM pair accepted locally

The source and paired-artifact review for [#1788](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1788) is complete. The isolated `rebuild/mim-1788-20261107` worktree now contains the reviewed native supported table and its conservative unified companion. This work starts from PR #1750 at `3b07c58bb63776fdf1482dae34a8ca2212980620`.

**Mapping acceptance is complete. Final code/CI gates, production canaries, all 15 genuine current-worktree producers, and the new graph/archive admission remain pending at this checkpoint.** The old graph is preserved. This report grants no GitHub merge or release-publication permission; the old backlog goal stays paused.

The [source checkpoint](README.md) and [compatibility checkpoint](COMPATIBILITY.md) retain their earlier states. The [accepted-pair index](accepted-pair/index.json) binds exact copies of the later evidence. Complete source archives, products, historical quarantine, row-level witnesses, raw comparisons, helper sources and failed attempts remain under `data/rebuild-evidence/mim-1788-20261107/`.

## Pair and native decisions

| Binding | Accepted value |
| --- | --- |
| Selected immutable MIM source | `0dac278466699129a083343a921c2e0ca18a9ab4` |
| Native manifest SHA256 | `b02a92446e8a613fd0d96b0dd8147d439733fcf73e731b363a6388e95d616703` |
| Native supported table SHA256 | `7e68fea7fd788928f29c7671156198af101baaa3b3051f19bab78a5479d2a940` |
| Conservative unified artifact SHA256 | `f1314a41ede9b143c595399ada5178e52306364e69b467810cf71e7cdc4be23d` |
| Current pin SHA256 | `8c66be0b68dcb773a908b17de56ff34b6270dc9eebf114e759552b07c3907cd5` |
| Actual conservative writer SHA256 | `ade61c8ac18bd7f1883e7c43a7ef7c5637c4774af7b8f4593ae4e6f5682fd95f` |

The complete native partition is 3,014 rows: 1,739 SUPPORTED (1,737 exact and two broader) and 1,275 WITHHOLD. Supported/withheld subset dates remain 2026-11-01/2026-11-03. The original publisher products are unchanged. The unified artifact retains its historical version 2026-09-06 and now explicitly declares SKOS direction; no historical release or profile is relabeled.

KGM separately holds the exact unchanged P3556 claim under its existing material-scope review: 1,739 native supported = one downstream-held + 1,738 eligible (1,736 exact and two broader). The [mandatory ledger](accepted-pair/downstream-held.json) retains all original row fields, all 11 native decision fields, the real archive owner, and current policy/native witnesses. This is not a change to the publisher's WITHHOLD partition. A changed or unfamiliar conflict remains fatal.

The two broader source claims project to exactly four directed rows, each binding the full source hashes of its broad claim and explicit same-subject exact sibling:

| Explicit form identity | Parent |
| --- | --- |
| `cas:10030-67-8` | `CHEBI:6731` |
| `kgmicrobe.compound:d-_-melezitose_monohydrate` | `CHEBI:6731` |
| `cas:7791-07-3` | `CHEBI:132103` |
| `kgmicrobe.compound:sodium_perchlorate_monohydrate` | `CHEBI:132103` |

These relations add parent navigation without granting exact identity, parent aliases, formulas or reverse parent relations. Modifier-bearing supported rows are rejected before positive reconstruction.

## Complete artifact review

The [independent conservation audit](accepted-pair/conservation-review.json) streams every baseline/candidate/quarantine row with all fields and multiplicities. Baseline 591,933 rows reconcile as 580,192 unchanged rows, 11,737 historical originals in quarantine, and four existing Catalase rows contextualized as metadata-only relations. All four originals are also retained in quarantine. The candidate has 591,914 rows over 120,173 target IDs: 336,027 exact, 255,879 close, four broader and four related. The related rows preserve their full original Catalase payloads except the explicitly reviewed predicate/comment change.

All 11,718 rebuilt rows have [independent direct-input lineage](accepted-pair/reconstructed-lineage-review.json): 1,736 identifier claims, 1,736 canonical names, 8,242 synonyms and four broader rows; zero unresolved. The new category rows (78 ChemicalMixture, 18 GrowthMedium, 26 PhysicalEntity and four InformationContentEntity) have current native witnesses. The 374 prefix-based ChemicalEntity defaults are explicitly distinguished from native declarations. No reconstructed entity had a nonempty prior formula, and none receives an invented formula. The 580,192 unchanged historical rows are not newly scientifically curated.

The genuine [second conservative build](accepted-pair/second-cycle.json) reproduces the compressed and decoded candidate bytes, complete held ledger and all broader derivations. Its input inventory changes only the baseline locator and hash. Scope shrinks by the 13 withdrawn local/CAS targets; it does not expand. Both existing production historical-conflict audits pass. Second-cycle quarantine retains all 11,718 originals/multiplicities from the first candidate; the first quarantine remains preserved separately.

The [60-check finite scientific/runtime review](accepted-pair/scientific-review.json) preserves the CAS, Potato, material, P3556, hydration, source-qualified ingredient and native-category controls. Four P3556 structured rows, the complete eight-target material cohort and its 35 controls, and the historical native lexical cohort remain unchanged. All 13 withdrawn targets retain their original claims in quarantine and explicit current source-review dispositions. The four added NCIT assertions in the full upstream source are WITHHOLD; the consumed stub-ID cohort remains exactly NCIT90/mesh100/MICRO60/BTO3/PO8.

The P3556 structural-name alternative was already reviewed in closed [#1253](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1253). [Current raw evidence](accepted-pair/native-alternative-1253.json) re-extracts three complete nodes and 27 incident edges, compares five molecular properties, preserves all 19 competing rows, and checks the exact synonym-enabled/disabled query modes. CHEBI:196822 is permitted only for the previously reviewed structural spelling; the generic CHEBI:16110 class remains distinct from molecular or supplier-product identity. The current raw JSON serialization has its own digest. Earlier overstrict reviewer diagnostics remain preserved, with no duplicate issue or runtime precedence change. A [wording erratum](accepted-pair/field-count-erratum.json) corrects the count to seven policy fields plus two TSV transport fields; the actual field comparison was already exact.

The complete historical 55-override [baseline/candidate comparison](accepted-pair/historical55-comparison.json) passes 330 class/mode/member outcomes and 1,650 route checks, including all five current local corrections. Full outcomes match; the selected mapping artifact is the only changed bound input. These overrides return before unified lookup, so this result does not substitute for the separate actual broader/identity-reader checks.

## Repairs, checks and retained failures

All findings were filed and triaged before implementation. The source/compatibility checkpoints cover #1789–#1799. Later independent review repaired [#1800](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1800) (exact held-ledger bytes instead of Python bool/int equality), [#1801](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1801) (the complete 11-field native decision), and [#1802](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1802) (a coherent policy-mutation fixture). The failed 8-pass/1-failure fixture attempt remains retained.

The coordinated affected run passed **694 tests**, with all 753 Python identities unchanged. Formatting/spelling preparation passed without changes. These are development checks; the final clean-candidate full gate is still required. The later [artifact-focused run](accepted-pair/artifact-tests.json) passed 73 tests across five modules in 24.07 seconds, with both promoted artifact hashes and all 753 Python files unchanged. The [final formatting preparation](accepted-pair/final-format-preparation.json) also passed with zero changes. The accepted artifact test updates preserve all existing immutable full-row controls and add the six original source claims, four actual broader-reader cases and exact Catalase metadata rows.

[Promotion](accepted-pair/promotion.json) succeeded through the saved launcher after [#1803](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1803) repaired the evidence helper's import context. A bare helper process saw fewer package metadata entries until the actual builder imported the same virtual environment's bundled setuptools dependencies. Four independent probes reproduced the difference and exact original context. The fix imports and verifies the real builder before the unchanged strict equality; no environment, pin, digest or scientific artifact was restamped. The rejected first attempt changed neither canonical file. A refused direct-path historical-replay launch also remains preserved; its successful replacement used the launcher's supported module path with verified origin.

The native TSV keeps its required empty final cells and exact official bytes. A generic `git diff --check` flags those separators on four added rows; the code-only whitespace check passes, and complete native schema/partition/byte checks cover the table. No source delimiters were stripped.

## Production continuation

The mappings-only semantic closure remains nine producers as documented in [the release guide](../../MIM_REVIEWED_RELEASE.md). This isolated worktree requires all 15 genuine producer completions because existing receipts bind the old producer paths. No receipt is relocated or restamped. The copied GO database, toolchain receipt and existing lock are independently preserved for the genuine strict rebuild tracked in #1796.

After final code/CI validation, run release preflight, the complete ontology canary, native phase gates, the reviewed one-medium MediaDive transform canary, remaining dependent sources, the authorized process-only authenticated LPSN workflow, full source admission and the canonical local merge. Compare the nine resulting native authority tables with the exact inputs used by this mapping review; investigate any difference before accepting dependent results. Graph and archive checks must pass before the descriptive comparison is treated as a completed rebuild.

The completed old-mapping archive remains SHA256 `0e9e76fa59cde699ead4aeff52a8df8a8373bab9e0ddbb8cc718b70db9ef104e`, with 3,441,450 nodes and 17,936,301 edges. Independent copies of that archive, MediaDive edges and stats are retained. Its two read-only archive gates are still running at this checkpoint. MediaDive's **632 unknown/unavailable association endpoints and `association_coverage_complete=false`** remain binding in both generations. Unknown associations do not become empty lists, negative growth or complete associations.
