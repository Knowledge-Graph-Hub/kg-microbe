# Next tasks

Snapshot of the work remaining on 2026-10-12, after PR [#1401] (the
validation-upstream candidate) merged to `master` as `bac582f4e`. Master has
since moved to `82c083a83` with [#1442], [#1443] and [#1444]. This page covers what is
needed to rebuild and accept the candidate.

GitHub issues are the authoritative status. Update this page, or retire it, as
items close. The root [`NEXT_TASKS.md`](../NEXT_TASKS.md) is the older curated
backlog, last reconciled on 2026-08-16.

## Decisions

- **[#1420]: pin strategy (decided 2026-10-12;
  [decision and plan](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1420#issuecomment-6129515541)).**
  - Re-bind each policy to its ontology release plus a canonical digest of only
    the content it reviewed.
  - Pin `download.yaml` to stable release URLs. Use a dated release directory
    where one resolves, and otherwise a release asset or a commit.
  - Check every pinned input before NCBITaxon and ChEBI processing starts.
- **[#1427], [#1428], [#1429]: category modeling (open).** Decide these before the
  rebuild candidate is frozen (section 1).
- **[#1431], [#1433] (open).** Fix these before the freeze, or accept them explicitly
  as known deviations in the merged review.

## 1. Before freezing the rebuild candidate

Each item here can change producer output or shared code. Resolve it, or defer
it explicitly, before the head used for the rebuild is frozen. Anything that
changes output after the freeze means rebuilding again.

### Blockers

- **[#1420]: exact-byte pins cannot be reproduced.** Several reviewed policies pin
  the whole-file SHA-256 of raw inputs, and a fresh environment cannot obtain
  those exact bytes:
  - some pins are of files the transform used to rewrite in place, with no
    pristine copy kept: `ro.json`, `pato.json`, `uberon.json`, `mondo.json`,
    `foodon.json`;
  - some files are built locally: `go.db`, `ncit.db`, and ROBOT-converted JSON
    such as `upa.json`;
  - `lpsn_gss.csv` is account-gated, so `kg download` cannot fetch it;
  - the rest come from rolling URLs, which serve whatever is current:
    - `envo.json`, `pato.owl` and `mesh2026.nt.gz`;
    - Rhea's `rhea-directions.tsv` and `rhea.rdf.gz`;
    - MicrobeDecoder's `database.zip`. Its upstream changed on 2026-09-08, so a
      fresh download fails today.

  Even `kg download -i` cannot reproduce them.
  - **Where it fails.** Outside the staged worktree, each affected producer
    fails closed at its first mismatched input.
  - **Skipped sources.** In a multi-source batch, every source that declares the
    ontologies transform in `TRANSFORM_INPUTS`, directly or transitively, is then
    skipped.
  - **When it fails.** Most pins are checked only when their ontology is parsed,
    so the main checkout aborts at ENVO after hours of NCBITaxon and ChEBI work.

  The decided fix re-binds the policies one at a time, each with its own
  independent review; the plan lists the steps. [#1441] belongs to the same work:
  PO's imports are still fetched live, so `ontologies_stubs` needs the network
  during the rebuild.
- **[#1421]: BacDive withheld supplied-taxid records drop out of deposit
  resolution.** As a result, the deposits `Chol-1`, `SN-1` and `ATCC-15578` would
  equate unrelated organisms through `close_match`. The fix is in review as
  PR [#1467].

### Landed after [#1401]

[#1442], [#1443] and [#1444] merged on 2026-10-12. Together they:

- skip optional Bakta when it has no input;
- run `ontologies_stubs` and the SemSQL builds on the ROBOT pinned in
  `download.yaml` (jar and wrapper), restoring the XML limits JDK 24 lowered;
- pin MicrO and its 20 import modules.

They closed [#325], [#1438], [#1439] and [#1440] and most of their review findings.
Still open:

- PO's imports are fetched live ([#1441]).
- KEGG fails the default batch ([#1448]).
- Stale Bakta per-dataset outputs can be merged ([#1458]).

KEGG and Bakta are outside the 15 standard-merge producers.

### Also before the freeze

- **[#1422].** The ontologies run parses MONDO and UPA, and those parses rewrite
  the tracked `mondo_xrefs.tsv` and `unipathways_xrefs.tsv` non-atomically. That
  includes the staged worktree, whose delivery files must stay unchanged. Fix
  this first, or restore and account for both tables after the run.
- **Modeling decisions.** Decide [#1427], [#1428], [#1429], [#1431] and [#1433] as listed
  above. Any decision that changes emitted output (categories, predicates or
  edges) must be implemented before the freeze.
- **The other [#1401] review findings** (section 3). Each fix changes producer
  inputs or shared code, so it lands before the freeze or waits until after
  acceptance.
- **Source-contract review.** Independently review each changed source contract
  and its negative controls, including [#1467] and each [#1420] re-binding.
- **Triage the other open candidate issues** (section 4).

## 2. Freeze, gate and rebuild

1. **Freeze and gate.** Freeze the final head and run the full gates on it:
   `pytest`, `tox`, `poetry check --lock` and
   `python scripts/generate_merge_configs.py --check`.
2. **Move the staged worktree.** The staged worktree
   (`data/validation-upstream-20260930.DbltzT/worktree`, detached at `845f2add1`)
   holds the receipt-bound `data/raw` for the rebuild.
   - Clean up the [#1413] leftovers first (section 5).
   - Move the worktree to the frozen head without disturbing its staged inputs.
   - Stage the inputs the frozen head newly pins, and record them in the staging
     receipt. These include at least MicrO's 20 `micro_imports/` modules,
     `micro.owl` at its pinned commit if its bytes differ, and anything the
     [#1420] work re-pins.
   - Do not run a blanket `kg download -i`.
3. **Rebuild the 15 standard-merge producers.**
   - **Where to run.** Run inside the staged worktree with its default
     `data/raw` and `data/transformed`, without `-i` or `-o`. Some producers
     resolve paths relative to the code checkout (`RAW_DATA_DIR` in
     `transform_utils/constants.py`).
   - **Which sources.** Name each producer explicitly. The default
     `kg transform` batch has 18 sources, including `bakta`, `cog` and `kegg`,
     which are outside the standard merge.
   - **No reuse.** Rebuild in these dependency phases, and never reuse or
     relabel earlier outputs as fresh:

   | Phase | Producers |
   | --- | --- |
   | 1 | `ontologies`: the whole 14-member producer, with actual finalization, freshness and authority-epoch checks before anything else |
   | 2 | `ontologies_stubs`, `gtdb`, `bacdive`, `madin_etal`, `metatraits`, `rhea_mappings`, `prego` (habitat) |
   | 3 | `gold`, `lpsn`, `mediadive`, `bactotraits`, `metatraits_gtdb` |
   | 4 | `lpsn_api`, `microbedecoder` |

   `poetry run python scripts/transform_phases.py` derives these phases from each
   source's `TRANSFORM_INPUTS`, and `hpc/submit_phased_transforms.sh` submits
   them on Slurm, one array job per phase, each starting only after the
   previous phase succeeded (#1567).

   `rhea_mappings` runs inside this rebuild, not as a separate Rhea run.
   - **Inputs.** It uses the pinned Rhea pair (`mappings/rhea_release.json`) and
     the prepared `chebi.db`, `go.db` and `ec.db` label databases, which depend
     on the ontology preparation.
   - **Release label.** Rhea label 142 is a local cache label, not verified
     tagged-release provenance.
   - **No fallback.** It never falls back to the latest release or a cache.

   The previous attempt stopped in phase 1, at ENVO's native RO evidence ([#1400]).
   [#1401] added the fix.
4. **Merge.** Create a fresh merge, with no semantic edits after serialization.
   The canonical merge still excludes MONDO. Then reconcile:
   - source observations;
   - category unions;
   - archive and member identities;
   - manifests.
5. **Review the exact archive.** Run fresh model, external KGXVal, strict-KGX and
   path reviews on that exact candidate. Strict-Biolink exceptions stay visible.
   Project conventions stay distinct from strict conformance, and both stay
   distinct from scientific acceptance.
6. **Close.** On acceptance, close the held issues in section 4.

These steps follow the acceptance steps in
[Remaining 93 diagnostics](REMAINING_93_UPSTREAM_WORK.md#acceptance-still-required),
which also records per-package status, and in
[Rhea directions](RHEA_DIRECTIONS.md#acceptance-still-required). The native RO
row in the per-package table predates [#1400]; [RO relations](RO_RELATIONS.md)
gives the current 516-assertion scope.

## 3. Open findings from the [#1401] review

Each finding was verified against the code and filed as an issue. The 18 issues
[#1402] to [#1419] were fixed in [#1401] and are all closed. [#1420] and [#1421] are the
blockers above. The rest remain open.

Each fix below changes producer inputs or shared code. For example, [#1424]
regenerates a mapping file that six producers declare as an input, and [#1426]
and [#1430] change shared code. So each one lands before the freeze or waits until
after acceptance. [#1422], [#1427], [#1428], [#1429], [#1431] and [#1433] also appear in
section 1.

| Kind | Issue | Finding |
| --- | --- | --- |
| Modeling decision | [#1427] | The generic category authority types PO whole-plant descendants (pollen, embryo, seedling) as `OrganismTaxon` |
| Modeling decision | [#1428] | Abiotic ENVO features are typed `AnatomicalEntity` through ENVO's UBERON anatomy `is_a` |
| Modeling decision | [#1429] | MICRO culture media are typed only as `biolink:GrowthMedium`, without the documented mixture category |
| Correctness | [#1430] | `foodon_category()` still defaults to `data/raw/foodon.json`, with a silent fallback |
| Correctness | [#1431] | Category authority decisions are not reconciled with other producers' substantive categories |
| Correctness | [#1432] | MicrobeDecoder emits `close_match` to GOLD organism IDs the GOLD producer did not admit |
| Correctness | [#1433] | MicrobeDecoder asserts `close_match` between LPSN taxa and `ncbi.assembly` genomes |
| Correctness | [#1434] | Reviewed supplied-taxid withholding lapses when a record's priority level changes |
| Correctness | [#1437] | MetaTraits' optional `ec2go.txt` input ignores the selected `--input-dir` |
| Performance | [#1423] | PREGO payload binding copies and re-hashes about 14 GB per run, and again at merge |
| Performance | [#1426] | GOLD reference-request rescans run for every source at finalization and merge admission |
| Performance | [#1435] | BacDive ancestry authority `finish()` re-hashes the whole shared admission, including the 14 GB `ncbitaxon.db` |
| Hygiene | [#1422] | Production MONDO/UPA parses rewrite tracked xref tables in the source tree non-atomically |
| Hygiene | [#1424] | The committed unified SSSOM was not regenerated under the ingredient-context policy |
| Hygiene | [#1425] | PREGO dictionary synonyms reuse size/mtime-keyed caches outside the native-input contract |
| Hygiene | [#1436] | CI sets `KG_MICROBE_TESTS_NO_NETWORK`, but no code reads it and tox does not pass it through |

## 4. Issues held open, and issues to triage

### Held until acceptance

[#1401] referenced these 42 issues as part of the candidate but deliberately left
them open. Each one closes only when producer acceptance and the merged review
pass:

[#1277], [#1290], [#1291], [#1292], [#1294], [#1295], [#1296], [#1297], [#1299], [#1300], [#1301], [#1302], [#1303], [#1305], [#1307], [#1308], [#1309], [#1310], [#1311], [#1312], [#1313], [#1315], [#1316], [#1317], [#1318], [#1319], [#1322], [#1323], [#1327], [#1330], [#1338], [#1342], [#1344], [#1353], [#1354], [#1361], [#1395], [#1396], [#1397], [#1398], [#1399], [#1400].

### To triage

125 issues created between 2026-09-30 and 2026-10-08 are still open. Besides
the 42 above, 83 come from the same candidate work and were not referenced by
[#1401]. For each one, decide whether it:

- is fixed by [#1401] and can close;
- belongs with the held set;
- stays open as work.

Start with these, which are probably fixed in the candidate and so should be held
like the 42 once verified:

- [#1306] and [#1314], whose packages
  [Remaining 93 diagnostics](REMAINING_93_UPSTREAM_WORK.md) records as cleared;
- [#1320], which says its implementation is in the candidate;
- [#1335], [#1336] and [#1337], whose author recorded the bounded implementation
  review as clear. Master has the [#1335] guard and cites [#1337];
- [#1343], whose two failing tests now exist and pass;
- the older [#270], that page's "Clinical BacDive tags" package.

Many of the other 76 record that implementation and independent review are
complete and that rebuild acceptance is pending, for example [#1275], [#1331],
[#1374] and [#1384]. Most of them will probably join the held set.

<details>
<summary>The other 76 open candidate issues</summary>

[#1275], [#1276], [#1278], [#1279], [#1280], [#1281], [#1282], [#1283], [#1284], [#1285], [#1286], [#1287], [#1288], [#1289], [#1293], [#1298], [#1304], [#1321], [#1324], [#1325], [#1326], [#1328], [#1329], [#1331], [#1332], [#1333], [#1334], [#1339], [#1340], [#1341], [#1345], [#1346], [#1347], [#1348], [#1349], [#1350], [#1351], [#1352], [#1355], [#1356], [#1357], [#1358], [#1359], [#1360], [#1362], [#1363], [#1364], [#1365], [#1366], [#1367], [#1368], [#1369], [#1370], [#1371], [#1372], [#1373], [#1374], [#1375], [#1376], [#1377], [#1378], [#1379], [#1380], [#1381], [#1382], [#1383], [#1384], [#1385], [#1386], [#1387], [#1388], [#1389], [#1390], [#1391], [#1392], [#1393].

</details>

## 5. Local checkout housekeeping

From [#633] (2026-08-01) until [#1401] fixed [#1413], a unit test could run a real
`semsql make` inside `data/raw` whenever `data/raw/go.owl` was present. In any
checkout where that happened:

- **An interrupted build** leaves `data/raw/go.db.tmp` and
  `data/raw/go-relation-graph.tsv`. Delete both before the next real GO build,
  because a stale `go-relation-graph.tsv` can short-circuit `semsql make`.
- **A completed build** may have replaced `data/raw/go.db` itself and left no
  stray files. Check `go.db` against its pinned digest, `a3903d4c…`, in
  `mappings/go_imported_subject_restrictions.json` and
  `mappings/upa_reaction_projection_dispositions.json`.

The staged worktree (`data/validation-upstream-20260930.DbltzT/worktree`) has
both stray files. Its `data/raw` is receipt-bound, so remove only those two
files, and record any later additions in the staging receipt.

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
[#1467]: https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1467
