# Next tasks

Snapshot of remaining work on 2026-10-11, after PR #1401 (the validation-upstream
candidate) merged to `master` as `bac582f4e`. GitHub issues are the authoritative
status. Update this page, or retire it, as items close.

## Decisions needed

- **#1420: pin strategy.** It blocks the rebuild; see below.
- **#1427, #1428, #1429: category modeling.** Listed under the open review findings.

## 1. Rebuild blockers

Both must be resolved before any producer is rebuilt with the #1401 code.

- **#1420: exact-byte pins cannot be reproduced from `download.yaml`.** Several
  reviewed policies pin the whole-file SHA-256 of raw inputs. Some are fetched
  from rolling URLs, some are rewritten in place, and some are built locally:
  - native RO: `ro.json`, `pato.json`, `uberon.json`, `mondo.json`;
  - `envo.json`;
  - Rhea: `rhea-directions.tsv`, `rhea.rdf.gz`;
  - finite import categories, UBERON temporal, GO restrictions and MeSH:
    `foodon.json`, `uberon.json`, `pato.json`, `pato.owl`, `go.db`,
    `mesh2026.nt.gz`;
  - MicrobeDecoder's BacDive join: `lpsn_gss.csv`.

  A fresh `kg download && kg transform -s ontologies` therefore fails closed, and
  every source that declares the ontologies transform in `TRANSFORM_INPUTS` is
  skipped. `kg download` cannot repair this, because it skips existing files.
  The issue lists the options:
  - versioned release IRIs (and a pinned ROBOT version), with the pins
    re-derived from those bytes;
  - canonical digests of the selected content, as the ontology parent and FOODON
    kernel policies already use;
  - checking every selected authority before NCBITaxon parsing starts, so a
    mismatch fails early;
  - documented input staging.

  Re-pinning any policy needs independent review of that policy.
- **#1421: BacDive withheld supplied-taxid records drop out of deposit
  resolution.** As a result the deposits `Chol-1`, `SN-1` and `ATCC-15578` would
  equate unrelated organisms through `close_match`. A fix is in progress on
  branch `fix/bacdive-withheld-deposit-contest-1421`: withheld candidates
  contest a deposit's parent without supporting one.

## 2. Producer acceptance, rebuild and merged review

Do these in order, after both blockers are resolved:

1. **Producer acceptance.** Use the pinned Rhea pair (`mappings/rhea_release.json`)
   and the prepared selected-root label databases. Rhea label 142 is a local cache
   label, not verified tagged-release provenance, and there is no implicit
   latest-release or cache fallback.
2. **Ontologies.** Rerun the whole ontologies transform, with actual
   finalization, freshness and authority-epoch checks, before any other producer.
   The previous attempt stopped at ENVO's native RO evidence (#1400), and #1401
   added the fix.
3. **The other 14 producers.** Rebuild them in the same isolated all-producer
   run.
4. **Merge and review.** Merge, then review the exact resulting archive:
   - strict-Biolink validation exceptions stay visible;
   - no semantic repair is applied after the merge;
   - the canonical merge still excludes MONDO.
5. **Close the referenced issues.** On acceptance, close the issues #1401
   referenced but deliberately left open (section 4).

Per-package acceptance status is recorded in
[Remaining 93 diagnostics](REMAINING_93_UPSTREAM_WORK.md#acceptance-still-required)
and [Rhea directions](RHEA_DIRECTIONS.md#acceptance-still-required).

## 3. Open findings from the #1401 review

Each finding was verified against the code and filed as an issue. #1402–#1419
were fixed in #1401, and #1420 and #1421 are the blockers above. These remain:

| Kind | Issue | Finding |
| --- | --- | --- |
| Modeling decision | #1427 | The generic category authority types PO whole-plant descendants (pollen, embryo, seedling) as `OrganismTaxon` |
| Modeling decision | #1428 | Abiotic ENVO features are typed `AnatomicalEntity` through ENVO's UBERON anatomy `is_a` |
| Modeling decision | #1429 | MICRO culture media are typed only as `biolink:GrowthMedium`, without the documented mixture category |
| Correctness | #1430 | `foodon_category()` still defaults to `data/raw/foodon.json`, with a silent fallback |
| Correctness | #1431 | Category authority decisions are not reconciled with other producers' substantive categories |
| Correctness | #1432 | MicrobeDecoder emits `close_match` to GOLD organism IDs the GOLD producer did not admit |
| Correctness | #1433 | MicrobeDecoder asserts `close_match` between LPSN taxa and `ncbi.assembly` genomes |
| Correctness | #1434 | Reviewed supplied-taxid withholding lapses when a record's priority level changes |
| Correctness | #1437 | MetaTraits' optional `ec2go.txt` input ignores the selected `--input-dir` |
| Performance | #1423 | PREGO payload binding copies and re-hashes about 14 GB per run, and again at merge |
| Performance | #1426 | GOLD reference-request rescans run for every source at finalization and merge admission |
| Performance | #1435 | BacDive ancestry authority `finish()` re-hashes the whole shared admission, including the 14 GB `ncbitaxon.db` |
| Hygiene | #1422 | Production MONDO/UPA parses rewrite tracked xref tables in the source tree non-atomically |
| Hygiene | #1424 | The committed unified SSSOM was not regenerated under the ingredient-context policy |
| Hygiene | #1425 | PREGO dictionary synonyms reuse size/mtime-keyed caches outside the native-input contract |
| Hygiene | #1436 | CI sets `KG_MICROBE_TESTS_NO_NETWORK`, but no code reads it and tox does not pass it through |

## 4. Issues held open until acceptance

#1401 referenced these 42 issues as part of the candidate but deliberately left
them open. Each one closes only when producer acceptance and the merged review
pass:

#1277, #1290–#1292, #1294–#1297, #1299–#1303, #1305, #1307–#1313,
#1315–#1319, #1322, #1323, #1327, #1330, #1338, #1342, #1344, #1353, #1354,
#1361, #1395–#1400.

## 5. Local checkout housekeeping

Before #1413 was fixed, a unit test ran a real `semsql make` inside `data/raw`.
A checkout that ran the test suite in that period may contain
`data/raw/go.db.tmp` and `data/raw/go-relation-graph.tsv` from that test.
The staged rebuild worktree is one such checkout. Delete both files before the
next real GO build, because a stale `go-relation-graph.tsv` can short-circuit
`semsql make`.
