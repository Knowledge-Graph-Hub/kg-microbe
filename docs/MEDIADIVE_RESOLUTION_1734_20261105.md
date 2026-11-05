# MediaDive #1734 resolution — 2026-11-05

Draft checkpoint: 2026-11-05T22:09:11.570962+00:00. Existing isolated M5 worktree and [PR #1750](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1750). Evidence prefix `R` means `data/rebuild-evidence/20261105/mediadive-resolution-1734/`. This report records completed evidence separately from the remaining production gates.

The admitted raw generation accounts for all 6,688 endpoints across 3,344 media: **6,056 nonempty, 632 unknown/unavailable, zero explicit empty, zero transport errors, zero malformed responses and zero missing evidence**. This is complete endpoint accounting, with **`association_coverage_complete=false`**. No strain association was recovered and no unknown was converted to empty, negative growth, biological absence or a nonexistent-medium claim.

Production raw-generation activation **passed** in stage `mediadive-resolution-admission-r2` (exit 0, 56.348 seconds). The active pointer selects `resolution-admitted-r2`, manifest SHA256 `fa3c9e47bad5ff298b35e32382de7bd642e6be6ed95540db128d7d674058924f`; `R/admission-r2.json` has SHA256 `c0d7f181cc6a0f0999c1bd8618a0f26317a2fa16eb290d992f43da86cff67db2`. Independent audit `R/admission-r2-independent-audit-1.json` passed (SHA256 `7202e5c85461a4af99e40731e130495d37b4e9e707cfca16d1aa334a0323f9ad`), including actual production reader/consumer admission, all 632 policy cases, native JSON/cache preservation and 69 protected originals. Activation made zero new requests. This is raw-input admission; MediaDive graph production and final release admission remain separate.

The failed first activation is preserved. It exited 1 because the reader expected the observed wire message literally in official documentation that describes the same ambiguous 404 differently. [#1772](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1772) now validates the exact scoped `GetMediumStrains` / `Error 404` / `DataNotFound` documentation record while retaining the unchanged strict wire classifier. Review 3 exercised the real applied-policy branch against the full pinned bundle and exact source-derived excerpt; the policy/source bytes and failed child were preserved.

The renewed user instruction is retained in `R/user-resolution-instructions.md`. The initial generation imported the prior 6,056 successes, 583 unknown observations and 49 latest transport failures. One actual retry canary for medium 1154 returned the documented unknown response; only after its checkpoint was verified did the batch request the remaining 48 transport cases. All 49 acquired subsequent actual404 evidence. The other 583 unknown heads retain their historical timestamps. The three immutable receipts are `resolution-seed-r1-receipt.json`, `resolution-canary-r1-receipt.json` and `resolution-batch-r1-receipt.json`; their verified acquisition status does not mean production admission. The batch manifest SHA256 is `155d98e2bd927c5c7be7527f6e42219c9f15490e55cee7cf815d77d478201ff9`.

`R/seed-canary-batch-independent-audit-1.json` independently checked all three generations: 6,056 original cache blobs unchanged, all four native JSON exports unchanged, prior observations retained, and 69 protected original files checked. The current-reader replay also passed against the unchanged batch. Historical failure receipts remain historical; none were restamped.

The production contract now distinguishes `nonempty`, `explicit_empty`, `unknown_unavailable`, `transport_error`, `malformed` and `missing_evidence`. Acquisition retains source bodies, observations, timestamps, native cache and exports in sealed generations. An atomic `current.json` selects an admissible generation. Interrupted intents remain evidence; a later validated response can resolve them. Explicit recovery and publication locks preserve interrupted work and refuse changed pointer or recovery identities.

MediaDive consumer contract v3 requires the selected pointer, manifest, endpoint outcomes, copied policy and current curated policy as actual consumed inputs. Full replay checks the original bodies/cache/native exports. A reviewed unknown returns a distinct unavailable state and omits only unsupported strain/growth assertions while recipes continue. Producer completion, fresh-instance restoration and public admission bind the mandatory endpoint TSV and its qualification. Merge carries the same limitation and audit into release artifacts, identifying direct graph inputs versus admitted dependencies.

The unchanged finite 632-case policy SHA256 is `2e1915efda265be4cbaea8921f126a7a1ea04e7c8110194ead915cfc1cecbd08`. `R/finite-policy-and-helper-independent-review-3.json` (SHA256 `7dcf25477fdcc659aa2096868ae9a85738b7881bff1a4d91d0b4d8269b3baafe`) approved those exact cases and the corrected production reader before activation: 583 retained unknowns plus 49 fresh unknowns resolving transport failures. It binds catalogue, latest observations, bodies, official documentation, impact, omitted assertions and downstream handling. Review 2's operational omission and the actual first activation failure remain recorded; review 3 closed that gap without changing the scientific disposition.

Official SPARQL discovery did not provide a replacement association dataset. Exact identities for 1366, 220 and J22 matched retained REST records. Two positive controls matched native strain 8 / DSM 9 / BacDive 683 and typed `hasGrowthIndicator=true`; medium 220 retains a modification context whose full equivalence was not established. The bounded query for 1366 returned zero rows. Neither those rows nor their absence establishes negative polarity, dataset freshness, complete associations or explicit-empty REST evidence. No alternative-source association was admitted. Retained comparisons and requests are under `R/official-review/`, `R/sparql-probes/`, `R/identity-comparison-1.json` and `R/control-r2-scientific-comparison-1.json`.

All review findings were filed. `R/filed-findings-live-1.json` records #1757–1771 as open; the subsequent documentation correction is #1772. Implemented changes and retained controls cover:

| Issue | Finding addressed |
| --- | --- |
| [#1757](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1757) | Deterministic SQLite WAL lifecycle/refusal test |
| [#1758](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1758) | Reject backend metadata error envelopes |
| [#1759](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1759) | Enforce response byte ceiling before writing |
| [#1760](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1760) | Preserve valid unnamed index metadata without freshness claims |
| [#1761](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1761) | Bind SPARQL branch variables before aliasing |
| [#1762](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1762) | Explicit synthetic generations; immutable historical fixture bytes preserved |
| [#1763](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1763) | Later fresh evidence can resolve interrupted intents |
| [#1764](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1764) | Recover sealed pointer publication under identity checks and writer exclusion |
| [#1765](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1765) | Preserve exact JSON scalar types through acquisition and consumer replay |
| [#1766](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1766) | Order timezone-aware observation instants |
| [#1767](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1767) | Capture source edge identity before omission checks |
| [#1768](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1768) | Reconstruct cached audit bytes from validated outcomes |
| [#1769](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1769) | Keep reviewed policy/review bytes bound through activation |
| [#1770](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1770) | Preserve repeated observations sharing a strain entity ID, without deduplication or renumbering |
| [#1771](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1771) | Decode stream-mode tar members without Python 3.10 `seekable()` failure |
| [#1772](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1772) | Validate the scoped official error description independently of the native wire wording |

Completed focused logs record 45 passing WAL/probe tests, 69 integration tests, 61 generation/consumer contract tests and 118 disposition/fixture tests. The documentation/remaining-consumer run then had 312 passes and two fixture assertion failures; the affected fixture rerun passed 27/27. The repaired archive verifier passed all 15 offline archive controls (`R/artifact-focused-r2.log`). These selections overlap and are not a cumulative test total; earlier failures remain retained.

Required formatting/codespell preparation passed with all 1,241 measured files byte-identical (`R/format-preservation-r1.json`). Lint passed and the actual required `docstr-coverage` check passed at 100%. A mistaken optional `doclint` invocation failed because its configured `docs/source/` directory was absent; `R/optional-doclint-command-correction.json` records the correction to the actual PR-gate command, without changing configuration or waiving a required check. No full-suite or CI pass is claimed for this changed candidate.

The archive helper's frozen SHA256 is `6cd653f2c0274c249a687975de669d54fcec9c7a1e3c3ef381a7d2aa8162a150`. Post-fix read-only inspection against installed Python 3.10 confirms `codecs.iterdecode` consumes member lines through the buffered reader without calling `seekable`, retains strict UTF-8 decoding and flushes at EOF. Exact endpoint checks, streamed manifest verification and final source guards are unchanged. This is author review of the narrow fix; the root's independent draft review is retained separately in `R/artifact-verifier-root-review-1.json`. Existing offline archive regressions remain unchanged and now pass 15/15.

The canonical planner and ontology prerequisite were revalidated separately: 28 positive graph files and 194 admitted artifacts, with unchanged producer/shared-finalizer/schema fingerprints and prior receipt bytes. See `R/current-ontology-revalidation-r1.json`. The raw-input release preflight exited 0 and reported all reviewed upstream inputs ready. Neither result admits MediaDive or the final graph.

The October comparison baseline is independently preserved under `data/rebuild-evidence/20261105/october-baseline/`: original MediaDive edges, merged archive and merged stats, with exact original/copy hashes and separate inodes. `scripts/adhoc/kgm_rebuild_comparison_20261105.py` SHA256 `0077fb45b31613bd03c4c5df33bd4e424df4223d7fa85644316365a486ed82eb` performed preservation successfully (exit 0, 0.839 seconds); see `R/october-preservation-r1.json`. Its later comparison will stream actual graph distributions and run the existing ingredient coverage checker against the preserved edges without updating the committed baseline. No October/new comparison has run yet, and descriptive counts will not grant semantic admission.

Phase 2 is running as `mediadive-resolution-phase2-r1` with seven planned producers: `ontologies_stubs`, `bacdive`, `gtdb`, `madin_etal`, `metatraits`, `rhea_mappings` and `prego`. Launch is not completion. No merged graph has been produced in this continuation.

Remaining checkpoints, to replace only with actual completed receipts:

- **In progress:** phase 2 production; completion and persisted admission remain pending.
- **Pending:** legitimate MediaDive graph producer completion, remaining dependency phases and admission of every selected source.
- **Pending:** local merge, general rebuild admission and independent archive qualification verification of 6688 unique endpoints, 632 unknowns and zero unresolved states.
- **Pending:** actual October/new graph and ingredient-coverage comparison, with reviewed differences.
- **Pending:** final candidate preparation, the single complete PR gate and required CI checks.

No GitHub merge, external publication, upstream messaging or assertion of complete association coverage is authorized or reported.
