# Reviewed MIM paired-promotion acceptance record — 2026-09-25

## Status: candidate accepted; full local gates passed; CI pending

This record is an acceptance ledger, **not a statement that a new KG is
release-ready**. Both byte-exact mapping files are staged together in the reviewed
topic branch; production integration awaits exact-head review and green CI.
The selected input is an immutable upstream commit/export, not a newly published
release tag. Review is agent-assisted with independent adversarial review, not
human curator signoff.

The earlier hydration candidate passed its original 17 audit gates and repeated
byte-identically, but whole-MediaDive follow-up exposed three unsafe historical
fallback pairs (#1169). That candidate is superseded diagnostic evidence.
Final revised candidate hashes, consumer replay and whole-media review are
recorded below. Full local gates pass; CI remains required before production integration.

The subsequent quantity-preserving audit also exposed a pre-existing name-keyed
recipe overwrite: 80 duplicate-name groups across 71 solutions contain 161
source occurrences, losing 81 occurrences in the old dictionary representation.
Solution 5787's two nickel-chloride additions (284 mg and 166 mg) demonstrate the
loss. Preserving source occurrence identity and quantity through emission and
merge was an additional blocking gate, now addressed by #1171 and independently
tested; unchanged identity-resolution keys alone do not establish lossless
recipe coverage.

| Acceptance boundary | Status |
|---|---|
| Immutable source/export selection and local archive binding | Verified; pin retained |
| Original candidate build, cycle 2 and original 17 audit gates | Passed for the diagnostic revision only |
| All 55 historical MIM-lineage special override dispositions | Final-code replay passes all 330 probes and 55 manual routes |
| Initial whole-MediaDive hydration delta | Reviewed; #1167/#1168 recovery defects identified and implemented |
| Recipe follow-up's 18 positive transitions | 15 supported; three finite holds required by #1169 |
| Final revised candidate and second cycle | Built; all six convergence checks pass |
| Complete occurrence-aware candidate audit suite | All 19 gates pass on the frozen consumer/builder pair |
| Final consumer and whole-MediaDive results | All 39,879 occurrences and nine whole-source gates pass |
| Final paired-change full pytest, tox and lock/config checks | **PASS**; 2,910 passed / 55 skipped in both full test runs |
| Exact-head review and CI | **PENDING**; required before production integration |
| Paired artifacts staged and hashes verified | Both exact files staged together; production integration pending |
| Fresh transforms, merge, model/path reviews and graph release validation | **NOT PERFORMED** |

## Immutable origin

The independently committed `mappings/mim_reviewed_release.json` is schema 2,
`origin=immutable_commit_export`, with `mode=candidate_only`. It binds:

| Item | Identity or SHA256 |
|---|---|
| Upstream commit | `1848b0fe521bc2462f165912fcf92d09ad9a8cec` |
| Commit-addressed source archive | `33ff549d7a2bf34e943156e800e00149736a30dfc0a974f3ca9a9884358bfef2` |
| Complete export manifest | `9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af` |
| Supported `ingredient_mappings.sssom.tsv` | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| Withheld `withheld_mappings.sssom.tsv` | `c37491ed4191889d375b02510137a178ee9b44a341131e42afec07d7953e8405` |
| Complete `mapping-dispositions.tsv` | `87b4a72969681e4b808c526552c84c36daa17c6697970735a4e0ba0270523154` |
| Archived original source SSSOM | `7567e33fe5e5f4239afbe42065e3d119ea3b4023ba28cb5559781ddc0f41f260` |
| Archived review JSON | `85b222601f2d588a36443123a256e871b7d64b12a1651af8dd5ea0ede014f32e` |
| Archived `uv.lock` | `f5ce4325376797ada321c0ffba1e6050355e3185c0a079d2c731d17480aeca1a` |
| Archived reviewed-SSSOM workflow | `474246379fb470807e53330469a0ed0724c1edbd6f94f306105c78ddf3d21c4e` |

The complete export has 1,747 supported exact rows and 1,252 withheld rows,
partitioning all 2,999 source assertions. Only the supported product is eligible
for installation as the vendored MIM input. Withheld rows are not a global ban
on independently supported ontology/source assertions.

Upstream locked Python 3.13 validation:
[run 36109949250](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/36109949250).
The local verifier checked archive safety and actual archived source/review/
workflow/lock bytes against the pin and manifest; it did not rerun a scientific
curation or make an online claim about future CI state. Durable reproduction
instructions are in [MIM_REVIEWED_RELEASE.md](../../MIM_REVIEWED_RELEASE.md).

## Preserved diagnostic candidate evidence

Evidence directory: `data/mim-ship-20260925.QDVfoK/`. These reports retain their
original meaning and are not overwritten with final acceptance claims.

Builder/audit revision: `a0089a37c5e390ad013ded7e8c54dd52cbf31868`, clean before
and after its five audits. Candidate SHA256:
`9e481e31f23b7a2414537f967ea513a7b494824799a002ca4300765f5acea0f1`.
It had 591,893 mapping rows and 120,185 entities, versus 610,059 baseline rows.
The first build quarantined 39,064 original rows, including 2,571
identity-policy rows, and repaired six historical object labels. Those figures
are candidate-layer diagnostics, not counts from a regenerated graph.

`hydrate-cycle2-audit.json` passed all six checks: identical full gzip bytes,
identical ordered semantic rows, identical non-baseline selected inputs,
unchanged protected inputs, identical reproducibility context and upstream
provenance. Both cycles had ordered-row SHA256
`073e748f06941398393ab68bcb192592234b080d86de1d2cd371761d32086a47`.
Report SHA256:
`05bb6505917007d686654f645a16898d996921ac7aacf4b30f8ce0d1606b5bc4`.

`candidate-audits/acceptance.json` passed these 17 gates at that revision:

1. All five audits completed successfully.
2. Frozen code remained clean and unchanged.
3. All fingerprinted inputs remained unchanged.
4. Every reported input was fingerprinted before execution.
5. The builder environment still matched.
6. Coverage audit code remained unchanged.
7. All exposed producers were traced.
8. No coverage route remained unresolved.
9. All 1,747 supported assertions were counted and all 1,696 subject routes matched.
10. All supported names were reviewed without unresolved cases.
11. Only the explicitly accepted Xanthine scope distinction remained.
12. All eleven ingredient identity/CAS cases passed.
13. Finite identity, formula and native-positive controls passed.
14. All 98 historical conflicts retained their 196 complete original rows.
15. Three source-local compounds had no inherited external equivalence.
16. All 55 historical override scientific dispositions were replayed.
17. All 330 special-resolver probes and 55 manual routes passed.

That report's SHA256 is
`1bf794ad0de80de37c9160a1aa86f33ceee9cf2088c2d3aa9e180a0dea01c56a`.
Its missing-entity exposure audit traced 67 currently exposed IDs, 510 existing
producer edge rows and 355 runtime routes. These are exposure/disposition
counts from existing source outputs, not observed losses in a newly built KG.

## Whole-source review and resulting changes

Initial replay covered all 1,213 compound records and 5,430 nested solutions:
87 compound routes and 7,487 recipe entries changed, grouped into 97 unique
transitions. All 17 external-positive transitions had native target evidence;
80 source-local transitions avoided unsupported external identities.

The independent full ledger and review are retained as:

- `all-media-hydrate-independent-ledger.json`, SHA256
  `38b08d0613d32a07aba3e976a10ec84e99db048ef6f3366a6fd30988a8f68f5b`.
- `ALL-MEDIA-HYDRATE-REVIEW.md`, SHA256
  `057f53c7a5fee893cc44b9a447267e7bd9e8bfe6a91439dfca140cde0776a561`.

That review identified #1167 (original formula punctuation must survive lookup)
and #1168 (evaluate an explicitly supplied hydrate ID only with native name/
scope and correctly directed chemical-parent evidence). The ten native hydrate
pairs are preserved in `tests/resources/mediadive_hydrate_columns.{tsv,md}`.
No water stripping or same-water-count chemical guessing is admitted.

Follow-up consumer revision `64babb4913c51c956b79d174bc30f0b69a22295a` changed
ten compound routes and 2,734 recipe entries, grouped into 18 positive
transitions. Fifteen were independently supported. Three others exposed old
legacy mistakes and blocked acceptance:

- `Tris(hydroxymethyl)methylamine` is not the TES derivative CHEBI:44356.
- `(NH4) citrate` does not establish the three counterions of CHEBI:63037.
- `(NH4)2S4` cannot be silently repaired to sulfate CHEBI:62946.

#1169 introduces finite name/target holds across unified, legacy, embedded and
recipe paths, including observed normalized spellings. Native TES and sulfate,
explicit di-/triammonium citrate, and independently supplied Tris remain usable.
No replacement chemical is guessed. Raw/native evidence is committed in
`tests/resources/recipe_scope_1169.{json,md}`; the full 18-transition review is
retained in `FINAL-FOLLOWUP-REVIEW.md`. The initial cohort of 2,628 potential
hydrate recoveries was an upper bound: eight raw `Mg(SO4) x 7 H2O` occurrences
must not inherit a different, punctuation-normalized source mapping.

## Final acceptance

These results come from separately executed final runs, not reassigned
diagnostic pass statuses:

- Final builder/policy revision: frozen at
  `e69939be466329287f812538bc6792e4382698cb`; the new build is written separately
  to `data/mim-ship-20260925.QDVfoK/candidate-1848b0fe-final-scopes/`.
- Rebuilt unified candidate SHA256:
  `9e481e31f23b7a2414537f967ea513a7b494824799a002ca4300765f5acea0f1`;
  591,893 rows / 120,185 entities. The three additional policy holds change the
  provenance disposition, not candidate bytes: 2,574 identity-policy rows and
  39,064 total original rows in quarantine, SHA256
  `2f7b28e592bee9f605884351d1cf23abd748a15e6cb7bc7837e92e5ca0e9909a`.
- Rebuilt second-cycle byte/semantic stability: all six checks **PASS** in
  `final-scopes-cycle2-audit.json`, with ordered-row SHA256
  `073e748f06941398393ab68bcb192592234b080d86de1d2cd371761d32086a47`.
- `final-scope-candidate-audits/acceptance.json` is a preserved **FAILED**
  diagnostic: four noncoverage audits pass, but the newly strengthened recipe
  quantity check aborts on the real duplicate-occurrence loss. Its unchanged
  code/input fingerprints do not make it a promotion approval. Complete
  occurrence-aware consumer acceptance is recorded separately below.
- `occurrence-candidate-audits/acceptance.json` passes all 19 gates, SHA256
  `657174b0c4e982226d94b61b8c354c5d6ff104db32e321bb05531ca7e85d5774`.
  All five audits exit zero; the consumer, original builder, environment and
  every fingerprinted input remain unchanged. All 1,747 supported assertions,
  1,696 subject/name groups, 11 identity/CAS cases, 98 historical conflicts
  (196 complete original rows), 55 override dispositions, 330 resolver probes,
  55 manual routes and all seven #1169 source routes pass. The finite coverage
  audit traces 67 exposed IDs, 510 historical edge rows and 356 runtime routes,
  with zero unresolved routes. These are exposure counts, not measurements of
  a rebuilt KG; the added route is a recovered duplicate source occurrence.
- Final consumer revision: `20c9bccdbe4ada5df3a495c5980e8ea6c05b86df`.
  The only runtime difference from the frozen builder is the reviewed MediaDive
  occurrence-preservation change; builder inputs/code remain separately bound.
  `all-media-final-occurrences.json` passes all nine whole-source gates, SHA256
  `b47adbe3b7901c6d93fd207eb043b984f94427b3658bcec2d4340e19d0a595be`.
  It covers 1,213 compounds and 5,430 solutions, preserving all 39,879 ordered
  raw occurrences (35,073 compounds and 4,806 nested solutions), including all
  81 previously overwritten positions across 80 collision groups. Full source
  payloads, scalar types and quantities survive; caches, code and inputs are
  unchanged, with no network calls or unreviewed chemical-identity changes.
  The 17 original and 15 follow-up supported transitions and all three #1169
  holds remain intact. The earlier display-keyed oracle is used only for
  identity after checking exact original-name/source-kind/typed-ID agreement,
  never as an occurrence-count or quantity oracle.
  Separate immutable regression tests pass 21 deliberately difficult
  occurrences through the real writer, strict source finalization and KGX
  compressed archive, including equal-quantity repetitions and contextual
  liquid/solid-medium alternatives. Values are neither summed nor reinterpreted
  as simultaneous required ingredients; qualifiers remain in `source_record`.
- Corrected full local gates: direct pytest **2,910 passed, 55 skipped**
  (1,139.93 seconds); tox **all six environments pass**, including its separate
  pytest run **2,910 passed, 55 skipped** (1,147.62 seconds). Both report 304
  warnings. `poetry check --lock` and generated merge-config checks also pass.
  Logs: `paired-final-pytest-corrected.log` and
  `paired-final-tox-corrected.log` under the evidence directory.
  Exact committed-head independent review and CI remain required; their results
  belong on the PR, not a retroactive claim about these local runs.
- Independent final evidence review passes: it rehashes 467 relevant paths,
  verifies all 19 + nine gates and six convergence checks, and compares every
  raw occurrence and all 81 recovered positions. Report
  `final-pair-acceptance-independent.json`, SHA256
  `024b4a717097ef1f6859cb57326a70c1968332f9d89f51146610d5a884a352c6`.
  This does not replace full project tests, CI or fresh-graph validation.
- Both files are staged in the same reviewed repository change and their hashes
  were recomputed after copying the accepted bytes:
  supported `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb`;
  unified `9e481e31f23b7a2414537f967ea513a7b494824799a002ca4300765f5acea0f1`.
  No withheld product or original upstream source table is installed.

The byte-exact supported TSV intentionally retains empty final fields. Plain
`git diff --check` reports their delimiter tabs as trailing whitespace; stripping
them would violate the immutable product hash. All other paths pass the ordinary
check. Only this artifact is checked with `core.whitespace=-blank-at-eol`, in
addition to exact SHA256 and SSSOM schema checks. No repository-wide whitespace
rule is relaxed.

The first full paired pytest run exposed a new test-contract mistake: it
incorrectly required the unified artifact to declare `predicate_semantics:
skos`. The builder intentionally retains the baseline's absent declaration;
the accepted unified artifact contains 336,050 exact and 255,843 close matches,
with zero broad/narrow rows. The supported product independently declares SKOS.
#1170's corrected test explicitly verifies both contracts and the full predicate
distribution, retaining separate legacy/asymmetric mechanism fixtures. Both
artifact hashes are unchanged. The failed run (2,908 passes, one failure) and
stopped redundant tox run remain diagnostic evidence; both corrected full runs
passed independently as recorded above.

Candidate and consumer acceptance authorize staging the byte-exact supported
product and accepted unified candidate together; full paired-change tests,
independent review and green CI are required before production integration.
Keep `candidate_only` as the refresh
CLI publication boundary; it is not a switch that authorizes automatic writes.
Do not change freshness receipts to make old outputs look current. Recompute
the actual producer closure, rerun transforms and merge, then review model,
paths, manifests and release validation on that newly built archive. This
acceptance record alone does not close the graph-release gate.
