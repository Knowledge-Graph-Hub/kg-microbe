# Bare-Potato identity-only candidate: isolated staging, 2026-09-29

Status: the independently reviewed candidate is staged in the isolated
`fix/mediadive-potato-scope-1236` worktree only. It has **not** replaced the
production checkout's unified artifact. Full MediaDive replay, final whole-suite
gates, CI, production integration, fresh transforms/merge, and KG release review
remain pending at this checkpoint. This record does not certify a release.

The [scientific scope review](../mediadive-potato-scope-1236.md) and
[#1236](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1236) hold only
bare Potato → `cas:93348-51-7`, preserving source observations and imported
grounding claims separately. No replacement chemical, registry identity or
botanical identity is inferred. The
[metadata correction #1237](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1237)
makes the identity-only refresh identify its actual writer and preserve the
semantic description without corrupting YAML scalar values.

## Exact artifacts and origin

| Role | SHA-256 |
| --- | --- |
| Original unified baseline | `f1545663016b3871d2176ccbdc76caffdefa472838b716956e8d722aaa2caff9` |
| Accepted isolated unified candidate, 13,374,364 bytes | `09c44642ab13b234e89ce113f7510aa9efb56969e4b539cb7843b43dcb425ba7` |
| Unchanged supported MIM table | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| Unchanged reviewed-release pin | `f082c05656a0910c85176eec7b41deeb77c27967aecb80393fddc262819b6d97` |
| Current identity-only writer, `scripts/consolidate_chemical_mappings.py` | `257fe4d8bf16f92eb78d5e375065e030ea56d7c1174d859fecd2baa80ac18c27` |
| Identity-policy fingerprint | `61786a46effa48de9901f77713b172db16a7d6797f35711d5c15c01b0e0ea926` |
| Complete finite candidate review result | `447aff5399cea0dc06c947d67e25f9354ac1c9b98fbb1add204dfa3756c07232` |
| Retained removed full-row TSV, 321 bytes | `07503b97da62d9ef0d5024e167bc55a79a6bea1a6bcb96202b2be658632391b0` |

The original reconstruction writer was
`scripts/mim_conservative_refresh.py`, SHA-256
`58ec62b9b01a28f4f3b6b47ff319a11396617d4a07ada409acc2742bcb77ae6a`.
That historical provenance remains bound to the original baseline and the
[previous review](../mim-invalid-cas-20260927/PROMOTION.md); it is not presented
as the writer of the new identity-only bytes.

The upstream origin remains immutable MIM commit
`1848b0fe521bc2462f165912fcf92d09ad9a8cec`, with reviewed manifest
`9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af`.
This is not a new upstream MIM export or tag. Both mapping products were checked
as a pair; the already correct supported table and pin were not rewritten.

## Verified finite delta

The complete streaming comparison found exactly one removed 13-column lexical
row: `kgm.name:potato` / `Potato` / `skos:closeMatch` /
`cas:93348-51-7`, source `mediadive_compounds`, comment `synonym`, mapping date
`2026-09-04`. Its exact original fields remain in
`tests/resources/mediadive/potato_scope.json` (fixture SHA-256
`b4755925efe8cde9871569b047e28c185ac56e2cba6295fca20fef2901062723`)
and the removed-row evidence above. All retained mapping row bytes and order
were identical. No new mappings or replacement targets were introduced.

The candidate has 591,949 rows, 120,183 distinct targets, 336,050 exact matches
and 255,899 close matches. Only three metadata fields changed:
`mapping_tool`, `mapping_tool_version`, and `mapping_set_description`. The
description retains the original conservative-MIM manifest statement and adds
exactly one identity-policy fingerprint. All unrelated metadata bytes/order,
assertion dates, historical unified version and legacy direction contract are
unchanged. Supported MIM remains 1,747 exact mappings covering 1,696 names.

A second identity-only refresh removed/relabelled zero rows and produced the
same compressed candidate SHA-256, not merely equivalent parsed rows. Fresh
runtime lookups returned no target for `Potato`, `potato`, `(Potato)` and
`Pot.ato`; they preserved `CrKSO42 x 12 H2O` → `cas:7788-99-0`, `KH2PO3` →
`cas:13977-65-6`, `TAPSO` → `cas:68399-81-5`, `TitaniumIII chloride` →
`cas:7705-07-9`, and `Potato flour` → `FOODON:03302378`. Explicit extract and
direct-CAS query eligibility does not invent a mapping absent from these inputs.

The immutable local review directory is
`data/issue1224-quarantine-20260929.xjuS9H/identity-candidate-1236-fixed.rxU4PT/review-complete-01/`.
It contains the hash-bound `result.json`, before/after input guards,
`removed-claim.tsv` / `removed-claim.json`, and exact `second-cycle.sssom.tsv.gz`.
The earlier interrupted candidate remains diagnostic only and is not this
accepted artifact. These candidate checks do not replace producer execution
receipts or a full baseline/replay comparison.

## Remaining gates

The targeted native mapping-pair and legacy predicate-semantics modules passed
**19 tests** against the staged candidate:

```bash
python -m pytest -q tests/test_sssom_asymmetric_direction.py tests/test_sssom_predicate_semantics.py
```

The changed test module also passed Ruff, and `git diff --check` passed. These
are targeted checks, not full-suite or CI completion. The existing invalid-CAS,
native-category, supported-pair and historical-fixture controls remain intact;
the same full stream also checks absence of the exact held Potato row.

The producer audit
must retain actual complete strict/hydrate/embedded claims, source recipes and
their hashes; the historical nine-record fixture is not an assumed current
cohort. Whole-source replay must conserve all fields and occurrence multiplicity
except the reviewed grounding delta, with explicit node review. Shared policy
changes require current freshness assessment, potentially all 15 canonical
producers, followed by fresh merge admission and KG model/path/release reviews.

Green candidate checks or future green code CI alone do not complete these
production and scientific gates. No freshness receipt may be restamped to make
older outputs appear current.
