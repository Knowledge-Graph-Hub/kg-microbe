# MIM upgrade review checkpoint for issue 1788

This is a historical checkpoint. See [the later paired-artifact acceptance](ACCEPTANCE.md) for the installed mapping pair and current remaining production gates.

The isolated candidate starts from PR #1750 commit `3b07c58bb63776fdf1482dae34a8ca2212980620`. This checkpoint records completed source and native-product reviews. **KGM compatibility repairs, paired unified-artifact review, promotion, producer canaries, final code/CI gates and the updated graph are still pending.** The running old-mapping generation remains unchanged and will be preserved as comparison evidence. The old backlog goal remains paused; no GitHub merge or release publication is authorized.

The selected source is immutable MIM commit [`0dac278466699129a083343a921c2e0ca18a9ab4`](https://github.com/CultureBotAI/MediaIngredientMech/commit/0dac278466699129a083343a921c2e0ca18a9ab4), independently verified as official main during acquisition. It supersedes baseline `1848b0fe521bc2462f165912fcf92d09ad9a8cec` only after the remaining acceptance gates. The proposal is [bound to exact source, workflow, lock and product hashes](proposed-immutable-pin-r1.json); it has not been installed by this checkpoint.

The [source review](source-review-chain-r1.json) replayed all 17 change receipts and checked all source-row, owner and review-input identities. Source assertions change from 2,999 to 3,014. The supported/withheld split changes from 1,747/1,252 to 1,739/1,275. Of the supported payloads, 1,733 retain identical rows and owner bytes. Fourteen older supported payloads cease current approval: seven are removed, six are withheld and one melezitose CAS payload receives a fresh, exact-form assessment. Six new payloads are scoped form claims. See the [compact delta](source-delta-summary-r1.json).

The [independent actual-product review](official-product-independent-review-r1.json) checks the complete supported/withheld/disposition partition, row order, multiplicity, all disposition fields and exact manifest/product identities. The products came from successful [official run 41900248437](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/41900248437) at that exact head. The separate opt-in ingredient bundle has not been activated. [Local reproduction](native-export-reproduction-r2.json) passed the same four standalone steps under isolated Python 3.13 with the frozen lock; all four output files equal the official artifact byte-for-byte.

The initial archive-only reproduction [failed](native-export-reproduction-r1.json) because current native form reviews require real historical Git commits. The [second attempt supplied verified official history](upstream-history-fetch-r1.json), without changing source/review bytes or disabling provenance checks. The reviews retain their declared working-tree-attestation status; this is not committed-byte proof of those historical review inputs.

The [bounded primary-source check](form-evidence-review-r1.json) made eight official PubChem/EBI requests; each response was byte-identical to the retained upstream evidence. Its 24 controls preserve the distinction between each supplied monohydrate, its CAS/local form handles and its directional water-free parent relation. These are source/database assertions and agent-assisted reviews, not new experiments or human curator signoff. Role, component, whole-record and whole-graph holds remain. SNOMED765356005 remains an unresolved exact-form lead; no exhaustive absence claim is made.

| Filed finding | Triage before implementation |
| --- | --- |
| [#1789](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1789) | Review the two archive metadata links under a narrow safe policy; never follow them or weaken consumed-file binding. |
| [#1790](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1790) | Support the two reviewed broader relations without copying parent identity, aliases or cross-references into the form. |
| [#1791](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1791) | Give the new unified artifact explicit SKOS direction and preserve legacy-reader controls. The measured baseline has zero asymmetric rows. |
| [#1792](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1792) | Preserve the actual subset versions: supported 2026-11-01, withheld 2026-11-03. Do not restamp dates to force equality. |
| [#1793](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1793) | Retain the failed archive-only attempt and document the verified Git-history prerequisite demonstrated by the successful reproduction. |

The [consumer audit](kgm-consumer-audit-r1.json) reconstructs all 55 historical MIM-derived MetaTraits overrides. Five now correctly retain local identities; older targets must not be restored. The [reader matrix](reader-repair-matrix.json) separates identity lookup, parent relations, registry handles and candidate diagnostics. A new paired unified candidate and its quarantine still require an independent review before promotion.

The [staging analysis](staging-reuse-review-r1.json) distinguishes the nine-producer mapping-only semantic closure from checkout-path provenance. Existing completions bind their producer directories to the old worktree. Under current admission contracts, this fully isolated worktree needs genuine completions for all 15 canonical producers; copied or relocated receipts cannot substitute. Native downloads/caches may be independently copied and reused where their validators accept them. Other reviewed pins and canonical graph scope remain unchanged.

MediaDive's 632 unknown/unavailable association endpoints and `association_coverage_complete=false` remain binding throughout the proposed update. Unknown associations do not become empty lists, negative growth assertions or complete association coverage.

The [checkpoint index](checkpoint-index-r1.json) binds these copies to retained run evidence. All later candidate, canary, graph, archive and comparison results must be supplied as new evidence; this checkpoint must not be relabeled as their success.
