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
side effects as well as unit outputs. These checks address
[#1869](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1869) and
[#1870](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1870), found
and fixed during separate read-only review before the first unit ran.

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
