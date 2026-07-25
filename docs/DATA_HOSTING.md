# Hosting vendored data files

Some KG-Microbe inputs cannot be fetched by `poetry run kg download`: their
upstream URL is dead, TLS-broken, or permission-gated. They are **not
regenerable** — we hold none of the upstream observations they summarize — so
the only options are to host a copy or to copy one by hand from a reference
`data/raw_*` directory.

This file is the manifest for hosting those copies on the public LBNL Google
Drive, plus the interim copy-by-hand procedure.

## Files to host

Six files, ~81 MB total. Checksums are from the copies currently in `data/raw`,
which came from `data/raw_202607_andOLD_mixed/`. Each md5 is also recorded inline
in `download.yaml` next to its placeholder.

| file | size | md5 | placeholder token in download.yaml |
|---|---|---|---|
| `gtdb_species_summary.jsonl.gz` | 46 MB | `aca98ae9c978f238ae7844beaccec63b` | `REPLACE_ME_gtdb_species_summary` |
| `gtdb_genus_summary.jsonl.gz` | 16 MB | `159828de09d22a7c85e2116e8a97944a` | `REPLACE_ME_gtdb_genus_summary` |
| `gtdb_family_summary.jsonl.gz` | 4.4 MB | `1443132d2aa0f3d8743b23096ce23a13` | `REPLACE_ME_gtdb_family_summary` |
| `NCBI2GTDB.tsv.gz` | 2.8 MB | `eca29d35869dd9035730caa12de12598` | `REPLACE_ME_ncbi2gtdb` |
| `GTDB2NCBI.tsv.gz` | 2.8 MB | `a313f89ac32b7137c7225c789f724f63` | `REPLACE_ME_gtdb2ncbi` |
| `BactoTraits_databaseV2_Jun2022.csv` | 8.6 MB | `e6bca5b947c1aa692d45ac24aa9025f3` | `REPLACE_ME_bactotraits_v2_jun2022` |

All five MetaTraits files are hosted together so the KG builds against one fixed
MetaTraits release, matching the three `ncbi_*_summary.jsonl.gz` inputs that are
already Drive-hosted under the `metatraits` tag.

### Why pin the crosswalks rather than fetch them live

`NCBI2GTDB.tsv.gz` and `GTDB2NCBI.tsv.gz` *are* still published upstream — they
moved off the dead `metatraits.embl.de/static/downloads/` path to the Bork
group's web space, linked from <https://metatraits.embl.de/documentation>:

```
https://www.bork.embl.de/~robbani/metatraits/NCBI2GTDB.tsv.gz
https://www.bork.embl.de/~robbani/metatraits/GTDB2NCBI.tsv.gz
```

Verified 2026-07-25: both are **byte-identical** to the copies in `data/raw`.

We deliberately do not point `download.yaml` at them. That is an unversioned
personal directory whose files are regenerated in place — the current build is
dated 2025-08-14 and the name carries no release identifier — so two KG builds
months apart would silently use different crosswalks with no way to tell from
the config. The Drive copy fixes the release. **Those URLs are the refresh
source**: when you want a newer crosswalk, download from there, re-upload, and
update the md5 in `download.yaml` and in the table above as a deliberate act.

### Why each one needs hosting

- **`gtdb_*_summary.jsonl.gz`** — MetaTraits (EMBL) products, keyed by GTDB
  r220 taxon name (so independent of which NCBITaxon release we build against).
  The JSONL serialization has been **discontinued upstream**: the Bork directory
  now publishes only `.tsv.gz`, in two variants per rank (`_all` and
  `_no_predictions`). Our vendored JSONL corresponds to **`_all`** — verified by
  comparing per-taxon trait sets at family rank: 73.9% of taxa match `_all`
  exactly (the rest differ only because `_all` is a newer build adding traits
  like `generalism score`, `generalist`, `habitat count`), versus 0.4% against
  `_no_predictions`, which carries far fewer traits per taxon (6 vs 130 for
  `0-14-0-10-38-17`). Note the taxa *counts* coincide (4,511 in both our JSONL
  and `_no_predictions`) — that resemblance is misleading, so compare trait sets
  rather than record counts if you revisit this.
  Consumer: `metatraits_gtdb` reads the species summary
  (`METATRAITS_GTDB_INPUT_FILES`); genus and family are declared for
  completeness but currently commented out in the transform.

  **Switching to the TSV form would require a transform change** — the JSONL is
  one object per taxon with a nested `summaries` list, while the TSV is one row
  per taxon-trait pair with richer columns (`ontology_ids` carrying OMP terms,
  `group_1`/`group_2` trait categories, min/median/mean/max, `taxon_lineage`).
  It is also much larger: `gtdb_species_summary_all.tsv.gz` is 135 MB versus
  46 MB for the JSONL. Until that work happens, hosting the vendored JSONL keeps
  the transform running unchanged.
- **`BactoTraits_databaseV2_Jun2022.csv`** — the host
  (`ordar.otelo.univ-lorraine.fr`) serves an incomplete TLS intermediate chain
  that no CA bundle can verify, so the download aborts the whole run. Static
  Jun-2022 dataset; it will not change.

### Deliberately NOT hosted

- **`lpsn_gss.csv`** — the LPSN GSS export is account-gated, and LPSN's
  copyright terms (see `kg_microbe/transform_utils/lpsn/README.md`) require
  attribution and restrict redistribution. Publishing it to a public Drive link
  *is* redistribution. Keep the manual procedure documented in `download.yaml`:
  register free at <https://lpsn.dsmz.de/register>, download the GSS CSV, place
  it at `data/raw/lpsn_gss.csv`.
- **Anything derived from a downloaded ontology release** — `ncbitaxon.db`,
  `ncbitaxon_removed_subset.json`, `chebi.{db,owl,json}`, `go.{db,json}`,
  `ec.db`, `bto.db`, `ncit.db`, `*-relation-graph.tsv.gz`, and the ROBOT-derived
  `pato/ro/taxrank/uberon/upa/foodon.json`. These must be rebuilt from the OWL
  you actually downloaded. Hosting or copying them silently pins the KG to an
  older ontology release: the transforms skip regeneration when the derived file
  already exists.

## Upload procedure

1. Upload each file to the public LBNL Drive folder **as binary**. Do not let
   Drive or the browser recompress or rename anything.
2. Set sharing to **anyone with the link can view** — `kghub-downloader`'s
   `gdrive:` handler is unauthenticated.
3. **Verify the round trip before trusting it.** Download your own upload and
   check the md5 against the table above:

   ```bash
   curl -sL "https://drive.google.com/uc?export=download&id=<id>" -o /tmp/check
   md5 -q /tmp/check
   ```

   This step is not optional. Drive has silently served `.gz` uploads
   decompressed — that is exactly how the already-hosted
   `ncbi_*_summary.jsonl.gz` ended up as plain JSON under a `.gz` name in
   `data/raw`, and the five files below go up the same way.

   Every MetaTraits read path now tolerates a decompressed `.gz` via
   `_open_maybe_gzipped` (`transform_utils/metatraits/metatraits.py`), so this
   no longer breaks a build. It used to matter most for the crosswalk:
   `_load_ncbi_gtdb_mappings` wraps its read in `except Exception`, so a
   `BadGzipFile` there never crashed — it silently produced **zero** mappings
   and the NCBI→GTDB fallback quietly stopped working. Verifying the checksum
   still matters, because a decompressed upload has a different md5 than the
   table above and is no longer the pinned artifact.
4. Take the file ID from the sharing link's `/d/<id>/` segment and paste it over
   the placeholder in `download.yaml`:

   ```yaml
   -
     url: gdrive:1AbCdEfGhIjKlMnOpQrStUvWxYz          # was gdrive:REPLACE_ME_...
     local_name: gtdb_species_summary.jsonl.gz
     tag: metatraits_gtdb
   ```

5. Confirm the entry works in isolation:

   ```bash
   mv data/raw/gtdb_species_summary.jsonl.gz /tmp/backup.gz   # keep a copy first
   poetry run kg download -t metatraits_gtdb
   md5 -q data/raw/gtdb_species_summary.jsonl.gz              # must match the table
   ```

   Move the file aside rather than relying on `-i`: `-i` deletes the local copy
   *before* fetching, so a failed download leaves you with nothing.

## Interim: copy from a reference directory

Until the files are hosted, `kg download` skips them with a message naming each
one (see `PENDING_HOSTING_MARKER` in `kg_microbe/download.py`). Restore them by
hand:

```bash
REF=data/raw_202607_andOLD_mixed
cp -n $REF/gtdb_species_summary.jsonl.gz $REF/gtdb_genus_summary.jsonl.gz \
      $REF/gtdb_family_summary.jsonl.gz $REF/NCBI2GTDB.tsv.gz \
      $REF/GTDB2NCBI.tsv.gz $REF/BactoTraits_databaseV2_Jun2022.csv data/raw/
```

### These are NOT GTDB downloads

Worth stating plainly, because the names suggest otherwise: none of these files
come from GTDB. The GTDB release directory
(<https://data.gtdb.ecogenomic.org/releases/latest/>) publishes only
`{bac120,ar53}_taxonomy.tsv[.gz]`, `{bac120,ar53}_metadata.tsv.gz`, trees, MSA
masks and genomic files — no phenotypic trait summaries and no NCBI crosswalk.
All of `gtdb_*_summary.*`, `NCBI2GTDB.tsv.gz` and `GTDB2NCBI.tsv.gz` are
MetaTraits (EMBL, Bork group) products that are merely *keyed by* GTDB taxonomy.
The four GTDB files we do fetch from GTDB proper are tagged `gtdb`, not
`metatraits_gtdb`.

Two related caches worth restoring the same way, both of which cost hours to
rebuild and neither of which is a `download.yaml` entry:

```bash
cp -Rn $REF/mediadive data/raw/     # 4 bulk JSONs; skips a ~1h MediaDive crawl
cp -Rn $REF/lpsn data/raw/          # 34,301 per-record LPSN API responses
cp -n  $REF/lpsn_gss.csv data/raw/
```

Note both caches live *inside* `data/raw`, so rotating or replacing that
directory loses them — which is what caused a full 34,300-record LPSN re-fetch.
Once the six files above are hosted, only the LPSN artifacts still need this
treatment.

Two inputs cannot be restored from any reference directory:

- `kegg/ko_minimal.json` (~30 MB) — run `python scripts/download_kegg_minimal.py`
  (~50 min). The `kegg` transform errors without it. A 894 MB `ko_details.json`
  fallback exists in `data/raw_last5/kegg/`.
- `bakta/<dataset>/` — `BAKTA` is active in `DATA_SOURCES` but no copy exists in
  `data/raw` or in the reference directory; `data/raw_last5/bakta/` holds a
  170 MB `cmm_bakta_test1` only.
