# Next tasks

Snapshot of the work remaining on 2026-10-17, after PR [#1401] (the
validation-upstream candidate) merged to `master` as `bac582f4e`. Master has
since moved to `1acb8b61f` (following [#1442], [#1443], [#1444], [#1467], the
[#1420]/[#1441] release-authority re-bindings, and the ten-PR batch [#1652],
[#1653], [#1656], [#1657], [#1661], [#1663], [#1666], [#1667], [#1669],
[#1672]). This page covers what is needed to rebuild and accept the candidate.

GitHub issues are the authoritative status. Update this page, or retire it, as
items close. The root [`NEXT_TASKS.md`](../NEXT_TASKS.md) is the older curated
backlog, last reconciled on 2026-08-16.

## Decisions

- **[#1420]: pin strategy (decided 2026-10-12 and implemented on `master`;
  [decision and plan](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1420#issuecomment-6129515541)).**
  - Re-bound each policy to its ontology release plus a canonical digest of only
    the content it reviewed (`d8829479d` and follow-ups).
  - Pinned `download.yaml` to stable release URLs, including PO's imports
    ([#1441]).
  - `python -m kg_microbe.utils.release_preflight <raw>` checks every pinned
    input before NCBITaxon and ChEBI processing starts.
- **[#1427], [#1428], [#1429]: category modeling.** Resolved in pre-freeze
  code before the rebuild candidate is frozen (section 1).
- **[#1431], [#1433].** Resolve before the freeze, or accept explicitly as
  known deviations in the merged review.

## 1. Before freezing the rebuild candidate

Each item here can change producer output or shared code. Resolve it, or defer
it explicitly, before the head used for the rebuild is frozen. Anything that
changes output after the freeze means rebuilding again.

### Resolved blockers (landed on `master`)

- **[#1420] & [#1441]: exact-byte pins re-bound to release + reviewed-statement
  digests (closed).** Policies that previously pinned whole-file SHA-256 digests
  of locally rebuilt or rewritten inputs (`ro.json`, `pato.json`, `uberon.json`,
  `mondo.json`, `foodon.json`, `go.db`, `ncit.db`, `upa.json`, `envo.json`,
  `pato.owl`, `mesh2026.nt.gz`, Rhea pair, MicrobeDecoder `database.zip`) now
  bind to canonical release metadata and statement-scoped digests, and PO's
  import closure ([#1441]) is pinned locally so `ontologies_stubs` does not
  fetch live imports during the rebuild.
- **[#1421]: BacDive withheld supplied-taxid records preserved in deposit
  resolution (closed via PR [#1467], `bb3072f59`).** The deposits `Chol-1`,
  `SN-1` and `ATCC-15578` no longer equate unrelated organisms through
  `close_match`.
- **[#1442], [#1443], [#1444] and the ten-PR batch (`1acb8b61f`).** Together
  they:
  - skip optional Bakta when it has no input;
  - run `ontologies_stubs` and the SemSQL builds on the ROBOT pinned in
    `download.yaml` (jar and wrapper), restoring the XML limits JDK 24 lowered;
  - pin MicrO and its 20 import modules;
  - close read-only SQLite handles and harden UPA's merge-time `go.db` check
    ([#1661]) and SemSQL toolchain check ([#1672]);
  - automatically delete stale SemSQL intermediates (`go.db.tmp`,
    `go-relation-graph.tsv`) before building `go.db` ([#1663]);
  - allow symlinked RO release files matching pinned content ([#1666]);
  - include nodes declared only in merge-excluded ontology files in the stub
    report ([#1667]) and set `provided_by` on UPA RHEA stubs ([#1669]);
  - raise MicrobeDecoder's CSV field limit to file size ([#1656]), move
    BacDive per-record trace output to debug logging ([#1653]), and add phased
    HPC array submission ([#1657]).

Still open outside the 15 standard-merge producers:

- KEGG fails the default batch when its manually fetched cache is absent
  ([#1448]).
- Stale Bakta per-dataset outputs can be merged ([#1458]).

### Also before the freeze

- **[#1422] & [#1362].** Emit `mondo_xrefs.tsv` and `unipathways_xrefs.tsv`
  atomically under the `ontologies` output directory instead of rewriting
  tracked files under `kg_microbe/transform_utils/ontologies/xrefs/`, and
  preserve all order-independent native UPA GO xrefs and multi-pathway RHEA/UCR
  routes.
- **Modeling and pre-freeze producer fixes.** Land [#1427], [#1428], [#1429],
  [#1355] (7 de-parented `FOODON` meat subjects), [#1074] (`OIO:*` exclusion and
  `WD_Entity:` $\to$ `WIKIDATA:` normalization), [#1433] (MicrobeDecoder genome
  `in_taxon` vs `close_match`), [#431] (deterministic BacDive
  `predicate -> relation` lookup), [#1424] (regenerate unified SSSOM under
  ingredient-context identity policy), [#1437] (MetaTraits `input_base_dir`
  resolution), [#5] (Madin per-value pathway fallback and ID normalization),
  [#790] (over-narrow `Reptilia` isolation-source row), and [#1674]
  (merge-time single-valued node column canonicalization, description
  deduplication, and non-blank `name` preservation).
- **The other [#1401] review findings** (section 3). Each fix changes producer
  inputs or shared code, so it lands before the freeze or waits until after
  acceptance.
- **Source-contract review.** Independently review each changed source contract
  and its negative controls.

## 2. Freeze, gate and rebuild

1. **Freeze and gate.** Prepare and commit the final candidate following the
   [testing policy](TESTING.md), then run
   `poetry run python scripts/run_pr_gates.py <label>` on its clean tracked tree.
   This checks lock/config and code quality before one full pytest run; do not
   add a duplicate standalone full run. Passing the frozen-head gate closes the
   three gate-only holds ([#1324], [#1343], [#1346]).
2. **Stage the rebuild worktree.**
   - **On the M1 host:** The staged worktree
     (`data/validation-upstream-20260930.DbltzT/worktree`) is host-local to that
     machine and holds its receipt-bound `data/raw`. Move that worktree to the
     frozen head without disturbing its staged inputs, stage any newly pinned
     inputs with targeted downloads recorded in its staging receipt, and run
     `python -m kg_microbe.utils.release_preflight data/raw`.
   - **On any other host (where `data/validation-upstream-20260930.DbltzT/worktree`
     is not present on disk):** Create a dedicated rebuild worktree at the
     frozen head, stage a receipt-bound `data/raw` from pinned release assets /
     verified local caches (never a blanket `kg download -i`), and verify all
     pins upfront with
     `poetry run python -m kg_microbe.utils.release_preflight data/raw`.
   - Note: Manual [#1413] `go.db.tmp` / `go-relation-graph.tsv` cleanup is now
     performed automatically before every SemSQL build ([#1663]; see section 5).
3. **Rebuild the 15 standard-merge producers.**
   - **Where to run.** Run inside the staged worktree with its default
     `data/raw` and `data/transformed`, without `-i` or `-o`, using one process
     per source (`kg transform -s <source>` or the phased runner) so memory does
     not accumulate across sources ([#1046]).
   - **Which sources.** Name each producer explicitly. The default
     `kg transform` batch has 18 sources, including `bakta`, `cog` and `kegg`,
     which are outside the standard merge.
   - **No reuse.** Rebuild in these dependency phases, and never reuse or
     relabel earlier outputs as fresh:

   | Phase | Producers |
   | --- | --- |
   | 1 | `ontologies`: the whole 14-member producer (the only phase that builds `go.db`, [#1643]), with actual finalization, freshness and authority-epoch checks before anything else |
   | 2 | `ontologies_stubs`, `gtdb`, `bacdive`, `madin_etal`, `metatraits`, `rhea_mappings`, `prego` (habitat) |
   | 3 | `gold`, `lpsn`, `mediadive`, `bactotraits`, `metatraits_gtdb` |
   | 4 | `lpsn_api`, `microbedecoder` |

   `poetry run python scripts/transform_phases.py` derives these phases from each
   source's `TRANSFORM_INPUTS`, and `hpc/submit_phased_transforms.sh` submits
   them on Slurm, one array job per phase, each starting only after the
   previous phase succeeded ([#1567]).

   `rhea_mappings` runs inside this rebuild, not as a separate Rhea run.
   - **Inputs.** It uses the pinned Rhea pair (`mappings/rhea_release.json`) and
     the prepared `chebi.db`, `go.db` and `ec.db` label databases, which depend
     on the ontology preparation.
   - **Release label.** Rhea label 142 is a local cache label, not verified
     tagged-release provenance.
   - **No fallback.** It never falls back to the latest release or a cache.
4. **Merge.** Create a fresh merge, with no semantic edits after serialization.
   The canonical merge still excludes MONDO. Then reconcile:
   - source observations;
   - category unions;
   - archive and member identities;
   - manifests;
   - zero unexpected `|` pooling anomalies in single-valued node columns
     ([#1398], [#1674]).
5. **Review the exact archive at 100% row coverage ([#810]).** Run fresh model,
   external KGXVal, strict-KGX and path reviews on that exact candidate with
   full row coverage (`--merged --max-rows 0`, or `--max-rows` at least the
   merged edge total). Partial-sample `kg-model-review` artifacts print a bold
   `**sampled M of N rows (P%)**` warning and are rejected by `kg_release.py`
   (`needs-attention`). Strict-Biolink exceptions stay visible. Project
   conventions stay distinct from strict conformance, and both stay distinct
   from scientific acceptance.
6. **Close.** On acceptance, close the held issues in section 4.

These steps follow the acceptance steps in
[Remaining 93 diagnostics](REMAINING_93_UPSTREAM_WORK.md#acceptance-still-required),
which also records per-package status, and in
[Rhea directions](RHEA_DIRECTIONS.md#acceptance-still-required). The native RO
row in the per-package table predates [#1400]; [RO relations](RO_RELATIONS.md)
gives the current 516-assertion scope.

## 3. Open findings from the [#1401] review

Each finding was verified against the code and filed as an issue. The 18 issues
[#1402] to [#1419] were fixed in [#1401] and are all closed, and blockers
[#1420] and [#1421] (with [#1441]) are now resolved on `master`. The remaining
findings are listed below.

Each fix below changes producer inputs or shared code. For example, [#1424]
regenerates a mapping file that six producers declare as an input, and [#1426]
and [#1430] change shared code. So each one lands before the freeze or waits until
after acceptance.

| Kind | Issue | Finding |
| --- | --- | --- |
| Modeling decision | [#1427] | The generic category authority types PO whole-plant descendants (pollen, embryo, seedling) as `OrganismTaxon` |
| Modeling decision | [#1428] | Abiotic ENVO features are typed `AnatomicalEntity` through ENVO's UBERON anatomy `is_a` |
| Modeling decision | [#1429] | MICRO culture media are typed only as `biolink:GrowthMedium`, without the documented mixture category |
| Correctness | [#1430] | `foodon_category()` still defaults to `data/raw/foodon.json`, with a silent fallback |
| Correctness | [#1431] | Category authority decisions are not reconciled with other producers' substantive categories |
| Correctness | [#1432] | MicrobeDecoder emits `close_match` to GOLD organism IDs the GOLD producer did not admit |
| Correctness | [#1433] | MicrobeDecoder asserts `close_match` between LPSN taxa and `ncbi.assembly` / `IMG` genomes |
| Correctness | [#1434] | Reviewed supplied-taxid withholding lapses when a record's priority level changes |
| Correctness | [#1437] | MetaTraits' optional `ec2go.txt` input ignores the selected `--input-dir` |
| Performance | [#1423] | PREGO payload binding copies and re-hashes about 14 GB per run, and again at merge |
| Performance | [#1426] | GOLD reference-request rescans run for every source at finalization and merge admission |
| Performance | [#1435] | BacDive ancestry authority `finish()` re-hashes the whole shared admission, including the 14 GB `ncbitaxon.db` |
| Hygiene | [#1422] | Production MONDO/UPA parses rewrite tracked xref tables in the source tree non-atomically |
| Hygiene | [#1424] | The committed unified SSSOM was not regenerated under the ingredient-context policy |
| Hygiene | [#1425] | PREGO dictionary synonyms reuse size/mtime-keyed caches outside the native-input contract |
| Hygiene | [#1436] | CI sets `KG_MICROBE_TESTS_NO_NETWORK`, but no code reads it and tox does not pass it through |

## 4. Issues held open for acceptance (78 issues, triaged 2026-10-15/16)

All 125 candidate issues from 2026-09-30 to 2026-10-08 were triaged against
`master` (`1acb8b61f`) on 2026-10-15/16:

- **Closed on 2026-10-15/16 (code/test-only review findings and superseded items):**
  [#1278], [#1280], [#1281], [#1282], [#1283], [#1284], [#1286], [#1287],
  [#1288], [#1293], [#1325], [#1329], [#1345], [#1347], [#1348], [#1349],
  [#1358], [#1368], [#1369], [#1370], [#1371], [#1372], [#1373], [#1378],
  [#1380], [#1386] (part of the 102 issues closed with evidence on
  2026-10-15/16).
- **Held until the frozen-head test/config gate (3 gate-only holds, section 2 step 1):**
  [#1324], [#1343], [#1346].
- **Held until the 4-phase rebuild + fresh merge + full-coverage review pass (75 holds, section 2 step 6):**
  - **Original 42 referenced by [#1401]:**
    [#1277], [#1290], [#1291], [#1292], [#1294], [#1295], [#1296], [#1297], [#1299], [#1300], [#1301], [#1302], [#1303], [#1305], [#1307], [#1308], [#1309], [#1310], [#1311], [#1312], [#1313], [#1315], [#1316], [#1317], [#1318], [#1319], [#1322], [#1323], [#1327], [#1330], [#1338], [#1342], [#1344], [#1353], [#1354], [#1361], [#1395], [#1396], [#1397], [#1398], [#1399], [#1400].
  - **33 additional verified rebuild-acceptance holds:**
    [#1275], [#1276], [#1279], [#1285], [#1304], [#1306], [#1314], [#1320], [#1321], [#1326], [#1328], [#1331], [#1332], [#1333], [#1334], [#1335], [#1336], [#1337], [#1339], [#1340], [#1341], [#1350], [#1351], [#1352], [#1356], [#1357], [#1359], [#1363], [#1365], [#1366], [#1367], [#1374], [#1375].
- **Kept open with narrowed scope or pending owner decision (21 issues):**
  - Narrowed pre-freeze/post-freeze work: [#270], [#1298], [#1355], [#1360], [#1362], [#1364].
  - Pending owner decision: [#1289], [#1376], and the 14 out-of-repo [#1350]
    conservation-harness issues ([#1377], [#1379], [#1381], [#1382], [#1383],
    [#1384], [#1385], [#1387], [#1388], [#1389], [#1390], [#1391], [#1392],
    [#1393]).

## 5. Local checkout housekeeping

From [#633] (2026-08-01) until [#1401] fixed [#1413], a unit test could run a real
`semsql make` inside `data/raw` whenever `data/raw/go.owl` was present. Since
PR [#1663] (`28b71f719`), `_remove_stale_intermediates` in
`kg_microbe/utils/ontology_utils.py` automatically deletes any leftover
`data/raw/go.db.tmp` and `data/raw/go-relation-graph.tsv` before building
`go.db`, and PR [#1672] verifies the local SemSQL toolchain stamp on `go.db`.
Furthermore, [#1420] (`d8829479d`) re-bound
`mappings/go_imported_subject_restrictions.json` and
`mappings/upa_reaction_projection_dispositions.json` from a single machine's
whole-file `go.db` SHA-256 to the GO release identity plus the canonical digest
of the reviewed statements (`kg_microbe/utils/go_imported_restrictions.py`). No
manual file deletion in `data/raw` is required before the phase-1 `ontologies`
build.

[#270]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/270
[#325]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/325
[#633]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/633
[#1275]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1275
[#1276]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1276
[#1277]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1277
[#1278]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1278
[#1279]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1279
[#1280]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1280
[#1281]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1281
[#1282]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1282
[#1283]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1283
[#1284]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1284
[#1285]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1285
[#1286]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1286
[#1287]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1287
[#1288]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1288
[#1289]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1289
[#1290]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1290
[#1291]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1291
[#1292]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1292
[#1293]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1293
[#1294]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1294
[#1295]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1295
[#1296]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1296
[#1297]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1297
[#1298]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1298
[#1299]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1299
[#1300]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1300
[#1301]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1301
[#1302]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1302
[#1303]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1303
[#1304]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1304
[#1305]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1305
[#1306]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1306
[#1307]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1307
[#1308]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1308
[#1309]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1309
[#1310]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1310
[#1311]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1311
[#1312]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1312
[#1313]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1313
[#1314]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1314
[#1315]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1315
[#1316]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1316
[#1317]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1317
[#1318]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1318
[#1319]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1319
[#1320]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1320
[#1321]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1321
[#1322]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1322
[#1323]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1323
[#1324]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1324
[#1325]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1325
[#1326]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1326
[#1327]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1327
[#1328]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1328
[#1329]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1329
[#1330]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1330
[#1331]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1331
[#1332]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1332
[#1333]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1333
[#1334]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1334
[#1335]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1335
[#1336]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1336
[#1337]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1337
[#1338]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1338
[#1339]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1339
[#1340]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1340
[#1341]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1341
[#1342]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1342
[#1343]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1343
[#1344]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1344
[#1345]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1345
[#1346]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1346
[#1347]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1347
[#1348]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1348
[#1349]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1349
[#1350]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1350
[#1351]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1351
[#1352]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1352
[#1353]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1353
[#1354]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1354
[#1355]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1355
[#1356]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1356
[#1357]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1357
[#1358]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1358
[#1359]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1359
[#1360]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1360
[#1361]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1361
[#1362]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1362
[#1363]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1363
[#1364]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1364
[#1365]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1365
[#1366]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1366
[#1367]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1367
[#1368]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1368
[#1369]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1369
[#1370]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1370
[#1371]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1371
[#1372]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1372
[#1373]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1373
[#1374]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1374
[#1375]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1375
[#1376]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1376
[#1377]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1377
[#1378]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1378
[#1379]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1379
[#1380]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1380
[#1381]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1381
[#1382]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1382
[#1383]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1383
[#1384]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1384
[#1385]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1385
[#1386]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1386
[#1387]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1387
[#1388]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1388
[#1389]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1389
[#1390]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1390
[#1391]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1391
[#1392]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1392
[#1393]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1393
[#1395]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1395
[#1396]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1396
[#1397]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1397
[#1398]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1398
[#1399]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1399
[#1400]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1400
[#1401]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1401
[#1402]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1402
[#1413]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1413
[#1419]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1419
[#1420]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1420
[#1421]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1421
[#1422]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1422
[#1423]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1423
[#1424]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1424
[#1425]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1425
[#1426]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1426
[#1427]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1427
[#1428]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1428
[#1429]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1429
[#1430]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1430
[#1431]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1431
[#1432]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1432
[#1433]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1433
[#1434]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1434
[#1435]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1435
[#1436]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1436
[#1437]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1437
[#1438]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1438
[#1439]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1439
[#1440]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1440
[#1441]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1441
[#1442]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1442
[#1443]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1443
[#1444]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1444
[#1448]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1448
[#1458]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1458
[#1467]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1467
[#5]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/5
[#431]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/431
[#790]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/790
[#810]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/810
[#1046]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1046
[#1074]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1074
[#1567]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1567
[#1643]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1643
[#1652]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1652
[#1653]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1653
[#1656]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1656
[#1657]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1657
[#1661]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1661
[#1663]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1663
[#1666]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1666
[#1667]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1667
[#1669]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1669
[#1672]: https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1672
[#1674]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1674
