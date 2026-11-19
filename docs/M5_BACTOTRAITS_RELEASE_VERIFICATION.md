# M5 bounded release verification, 2026-11-16

The merged correction at `2d94ed094167d94402f21400a9ad7dc4f7f20438` was
replayed on M5 with a new baseline at `ef27b97a0b450767da54235c6105b5250c178adc`.
Both executions used the same pinned Python 3.10.11 environment and shared
inputs. The baseline emitted 21 edges and 22 nodes. The candidate emitted no
edges or nodes and one complete quarantine audit for original row8521/BacDive17851.

The new `scripts/adhoc/finalize_bactotraits_identity_130_20261116.py` performs
another actual producer run and calls `finalize(fresh_run=True)` on that same
object. It binds current implementation, policies, schema, configuration,
original/staged inputs and the preceding fresh pair. The persisted finalized
candidate still has zero rows and its complete quarantine audit is unchanged.
It then calls strict `load_and_merge(processes=1)`, which refuses the missing
completed BacDive upstream. No graph is merged and no release is verified.

| New M5 receipt | SHA256 |
| --- | --- |
| Baseline | `8d2a780d27670106456450fb4c8d1063424570b7bf9277387c8abcb09a389eb0` |
| Candidate before finalization | `03446ab15dbe56bf277d25c810b5b0a612a73fe5850d73447d112ab74e611477` |
| Separate finalized candidate | `0c832333ac93018e95e81d2ba53e9e587b58c4838840859ba823f8f7fd441996` |

The stages are named `baseline-m5-20261116-r1`, `candidate-m5-20261116-r1`
and `candidate-finalized-m5-20261116-r1` under `data/validation-bactotraits-130/`
in the isolated release task checkout. Copies and independent review live under
the EdgeMech invocation's `.temp/m5-worker-run-20261116/`. All original v3
receipts and nested cache files remain unchanged. The finalization helper's
executed SHA256 is `29ef5410fcce9908284e970cd18131861d6318ca100ebdaf00d3bc522b1c4523`.

The corrected source's quarantine audit SHA256 is
`28d62147d49735406a35c721db345497c7e044f69f6d723caa0367f996158918`.
Finalization changes the empty edge header to canonical columns, producing
SHA256 `1a1f91d2da59ddf2aad7f854f52b7e2b23aaba455918bdd7382980bf6e25079f`.
It does not add graph assertions. The historical Madin output has an equivalent
SPO with its own raw source lineage; graph-wide SPO absence is not the criterion.

## Production dependency probes

`inspect_bactotraits_dependencies_20261116.py` inventories only named inputs,
toolchain records, source sizes and disk availability. Raw `release_preflight`
passes on the original M5 input root. Fresh completion still requires the whole
ontologies → BacDive → BactoTraits chain; October fingerprints do not satisfy it.

`run_bactotraits_production_unit_20261116.py` launches one actual CLI source
with exclusive unit-relative output, private caches/temp and one process. Its
plan binds all shared non-Python inputs, and its receipt inventories task raw
side effects as well as unit outputs. The original checks addressed
[#1869](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1869) and
the inventory portion of
[#1870](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1870), found
during separate read-only review before the first unit ran. The later review
below completed the permitted-write enforcement required by #1870.

The first two RO probes each persisted 880 nodes/85 edges, then correctly
failed finalization on missing isolated-stage ENVO and FOODON authorities,
respectively. No completion marker was written. Those authorities exist in
the retained original inputs; these failures do not prove full-build infeasibility.
Failed stages and every plan remain preserved. Later production-probe outcomes,
exact final gate results and publication blockers are recorded in the
[EdgeMech M5 report](https://github.com/CultureBotAI/EdgeMech/blob/verify/m5-release-evidence-20261116/docs/validation/m5-bactotraits-release-20261116.md).

## Publication boundary

GitHub latest release remained `2025-03-07` at the live inspection. The retained
canonical M5 archive's manifest identifies an October 18 build from
`bcfa6bf5b-dirty`, predating the correction. Its bytes were preserved.
[#887](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/887) remains
open concerning retired download URLs in release publication. A fresh corrected
complete graph, a working publication source, separate human approval and
verification of the published assets remain necessary.

The bounded result does not infer trait falsity, a replacement organism,
neighboring-row quarantine, or graph-wide scientific validation. Six focused
finalization tests and four production-launcher regression tests passed before
the final repository gate. Final gate results are recorded separately against
the committed candidate; a source canary is not a release.

## Adversarial guard follow-up, 2026-11-19

The subsequent independent review recorded three additional defects in
[#1874](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1874),
[#1875](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1875) and
[#1876](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1876), and
identified the remaining permitted-write requirement in
[#1870](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1870).

The production launcher now binds the child package and CLI module to its
selected checkout instead of accepting ambient Python import routing. It copies
retained inputs privately, verifies their complete identities, then publishes
them without overwriting a competing target. An interrupted copy retains private
failure evidence without publishing a truncated canonical input.

New production plans and receipts use `bactotraits-production-unit-v2`. Declare
each permitted raw derivative using repeatable `--allow-raw-write PATH` options;
paths are exact and relative to the isolated task's raw directory. The launcher
inventories nested raw entries and records additions, changes and deletions.
An undeclared effect fails the unit and retains a failure diagnostic. A permitted
raw effect does not establish producer finalization, scientific acceptance or
release readiness.

The bounded finalizer also checks the preceding candidate's complete code
inventory and consumed identity-policy path and SHA256 against the current
plan. Matching Git revisions alone do not establish matching code or policy
when a candidate replay permits local changes.

The original M5 plans, receipts, graph counts and hashes above describe their
original executions. They remain historical evidence and are not relabeled as
runs of these new guards. Validate the new helper on one actual unit before a
larger production run. Source freshness, downstream completion and publication
gates remain in force.

## Preserving the verification checkout before removal

`scripts/adhoc/preserve_pr1871_worktree_artifacts_20261119.py` prepares a
read-only plan, moves one canary, then preserves the remaining untracked and
ignored artifacts using exclusive same-volume renames. It does not delete
artifacts or remove Git worktrees. Before applying it, the caller must quiesce
writers and verify there are no active or outside consumers of the selected
paths. Preserve the tracked source separately with `git archive` and retain a
Git bundle for recovery.

The archive must be durable and outside registered worktrees. Plans bind exact
HEAD, branch and recursive metadata; symlinks are retained as opaque objects.
Each move has an intent and verification receipt. Completion reconciles the
remaining source paths and every retained inventory, including resumed runs,
as required by the independent cleanup review
[#1877](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1877).
Recheck the checkout and consumers immediately before normal Git removal.

Relocated virtual environments and historical receipts retain their original
bytes, including absolute paths. Reconstruct and requalify a runtime before
using it again. Preservation does not reclaim the retained data's disk space
or validate old graph outputs against new code.
