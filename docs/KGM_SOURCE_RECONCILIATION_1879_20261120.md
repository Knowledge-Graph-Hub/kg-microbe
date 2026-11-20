# Historical KGM source reconciliation — 2026-11-20

The bounded source reconciliation for #1879 / draft PR #1884 is complete for the intentionally selected historical f10 generation. Its already-consumed MIM input is bound independently of the future final MIM canary. No production pin, transform, graph merge, public release or active MIM input was changed. The old backlog goal remains paused.

Durable selector: `/Users/marcin/agent-work/kg-microbe/source-reconciliation-1879-20261120/evidence/SOURCE-SELECTION-r1.json`, SHA256 `f7f935ced327088826e5a6614a5bfce3065679ed081d5a93c314ce4f97397721`. This is a handoff description with exact source/review bindings and prerequisites, not a new native consumer or production-acceptance receipt.

| Selected object | Exact identity |
|---|---|
| KGM root | `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe-mim-1788-20261107` |
| Full KGM revision | `f10fb3909ed32898a54176ca77e509a950d16b84` |
| New source receipt | `/Users/marcin/agent-work/kg-microbe/source-reconciliation-1879-20261120/data/closure-v2/source-manifest.json` |
| New receipt SHA256 | `02b2d617172b879efc0b3df80831fc44d647eb3f0399146f162e4712fdaeeae2` |
| Preserved historical receipt | `e2f4252a44aabaffaad7d3d3ca27ac0fb96e50b58939747e095e2ca1b9e3b48e` |
| Committed prior pin record | `8c66be0b68dcb773a908b17de56ff34b6270dc9eebf114e759552b07c3907cd5` |
| Already-consumed MIM revision | `0dac278466699129a083343a921c2e0ca18a9ab4` |
| Full row proof | `be8fb286f5e7f9d875bf1940cf89472e61756da4bdd095bbc88a8ff10524b847` |
| Final independent artifact review | `061a65ea90af8d516d9074587c40bd000d8a5a508daf93eed49b1d5286dd7090` |

Canonical committed/worktree `mappings/mim_reviewed_release.json` equals the historical `proposed-immutable-pin-r1.json` bytes. The prior supported table is `7e68fea7fd788928f29c7671156198af101baaa3b3051f19bab78a5479d2a940`; its paired unified artifact is `f1314a41ede9b143c595399ada5178e52306364e69b467810cf71e7cdc4be23d`. Actual producer bindings and declared dependencies verify prior consumption. This does not promote a future release.

Selecting f10 preserves the original MIM cohort. Substituting the separate newer checkout would remove four maltose-hydrate diagnostic rows from each MetaTraits lane; omission does not establish resolution. No current-master freshness is claimed. The historical root's pre-existing `merged_graph_stats.yaml` modification was preserved.

The new closure retains all **95 historical members** and contains **212 files / 179 upstream snapshots / 7,299,133,276 member bytes**, including every **35 generated graph/audit members**, all **91 unique consumed dependencies**, and **10 recursively checked fingerprint markers**. Ontology stubs bind their ontology dependency. PREGO remains diagnostic-only; the 15-source inventory does not select every source for chemical curation. Native unmapped diagnostics retain historical hashes; no native helper was rerun or newly admitted.

| Source | Complete nodes | Complete edges | Provider cases | Selected occurrences |
|---|---:|---:|---:|---:|
| MediaDive | 32,065 | 114,164 | 415 | 5,332 |
| MetaTraits | 55,394 | 4,365,896 | 82 | 120 |
| MetaTraits GTDB | 33,954 | 3,407,092 | 42 | 63 |
| MicrobeDecoder | 23,139 | 511,145 | 10 | 225 |
| Total | 144,552 | 8,398,297 | 549 | 5,740 |

The 549 provider cases represent **507 identities**; all **42** GTDB compound identities also occur in MetaTraits. Full original/combined rows, values, units, qualifiers, source payloads and holds survive in JSON/TSV ledgers without SPO deduplication. Twenty-one nodes use different valid case-ledger and source-table provider orders. Exact ordered provider/case-ID pairs bind the pinned case ledger; independent arrays retain their literal order and exact multiplicity.

MediaDive recipe observations join exact graph assertion IDs; incoming solution references remain context. MetaTraits incidences retain full coordinates and roles. MicrobeDecoder's 225-row subset ordinals are distinguished from full graph positions through counted full-row joins, retaining raw records and holds. All ten compound candidates, including rare cases, remain accounted for against the 6,661-row unmapped denominator.

Original KG transport manifest `cb80d955ba7470e2b956df1845dd9a1f5653333c1a67a7bdb2604694ae0483c9` projects losslessly into historical combined manifest `4b0ffd069550995850c59c1fe88ca01d2f43cdf9f9e42d181d70c69689105c4e`; the first KG occurrence is global row 2,912. Its older 2,911 CM occurrences are never relabeled as accepted v3.

Accepted CM v3 remains bound to source manifest `ede822e6424433644ae25f363cb5bfb88b154b453c1e954185ecc2c6cb3c829f`, prepared intake `6bcc92540daba081d8180346d135c2ae40471c9fb0a7005b46aa5c9902d684f7`, reviewed intake `9fd1da62fad47c3b5b7290ea3f9fc2b687b23fc8c98e8dc926e1460572c3f1d8` and binding review `b548dbcb6271f59083693da632a2318bfbbf868b5b2a208e86a77bb4ae77fa4a`. Transport package `cf7e1f1434ab2dfc61922a47ae785f474c06cf4f88fbfd76d09e6b55993f70c8` is distinct. All five were rehashed and independently checked. Retain **209,784 positive inventory / 163 context-only / 138 held occurrences**, distinct from **623 supported / 4,384 withheld binding cases**. Inventory and identity support do not confer medium presence. Zero concentrations, REMOVE, displaced descriptors, experimental stages, P3556 and MediaDive unknown qualifications remain binding.

The stack remains #1750 → #1804 → #1833 → #1884. Both real MIM scientific reports and native `manifest.inputs` must consume identical selected KG/CM evidence and member closure. Actual original CM preparation/review replay, explicit required/absent companion selection, full R3 comparison and the final native-artifact canary remain separate prerequisites. `CONSUMER_LINEAGE_UNRESOLVED` and `PRIVATE_NOT_KG_ACCEPTED` do not mean production acceptance. See [the integration report](CM_MIM_KGM_INTEGRATION_687_20261119.md) and [reviewed-release requirements](MIM_REVIEWED_RELEASE.md).

Review findings [#1887](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1887), [#1888](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1888) and [#1889](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1889) are repaired: recursive lineage, parsed ledger completeness, reserved names, copied-byte readback, compound authority, path containment, schema/case binding, CSV-state restoration and historical metadata provenance. Focused validation passed **112 row/downstream checks and 40 collector checks**. Formatting/spelling preparation passed. Actual row execution completed exit 0 on `fe6656070a8ab166c47f2754da8e5dcdc4828612`; final capture completed exit 0 on `c2937a5cef14ddcc629abc80eee9a82b695ad212`. Independent complete row review and final closure rehash passed with no remaining artifact findings.

Failed preparatory attempts and closure-v1 remain preserved. The selected receipt names its actual parent and labels old native-helper outcomes with their original timestamp; no old receipt was restamped. The exact-head repository gate uses `scripts/run_pr_gates.py --require-stable-mim` with all three explicit native selectors. Its result and CI are recorded separately on #1884 and in the final handoff; prior `b186a357` validation applies only to that older candidate.

Helpers, artifacts, reviews and actual execution receipts remain under `/Users/marcin/agent-work/kg-microbe/source-reconciliation-1879-20261120`. Future paired pin promotion, dependency-derived rebuild, source admission, canonical merge, archive/model/path/release checks and merge/publication approval remain pending. None is a prerequisite for the prior MIM input binding completed here.
