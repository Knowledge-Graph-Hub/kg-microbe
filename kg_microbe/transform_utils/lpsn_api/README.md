# LPSN JSON API transform

Enriches the GSS-based `lpsn` transform with the fields that only live
in LPSN's authenticated JSON API (per-record):

- **Publication provenance** — `publication_doi`, `publication_pmid`,
  `ijsem_list_doi` become `biolink:close_match` edges to `doi:*` /
  `PMID:*` CURIEs plus minimal `biolink:Publication` stub nodes.
- **Full above-genus taxonomy** — `lpsn_parent_id` becomes a
  `biolink:subclass_of` edge that connects genera up to family / order
  / class / phylum / domain LPSN records the GSS export doesn't include.
- **Nomenclatural genealogy** — `basonym_id` becomes a
  `biolink:same_as` edge (relation `skos:exactMatch`) from a comb. nov.
  name to its basonym.
- **Node-level detail** — `is_legitimate` (boolean) and richer
  `nomenclatural_status` / `lpsn_taxonomic_status` prose folded into
  each node's `description`.

Intentionally out of scope (per issue #484): `molecules` (LPSN's 16S
rRNA links). Natural follow-up if the merged KG grows a
molecular-sequence layer.

## Prerequisites

1. **Run the GSS transform first**:

   ```bash
   poetry run kg transform -s lpsn
   ```

   This creates `data/transformed/lpsn/nodes.tsv`, which the API
   transform reads to know which `record_no` values to enrich.

2. **Register a free LPSN account** at <https://lpsn.dsmz.de/register>.

3. **Install the `lpsn` Python package** (not in poetry deps by
   default; add manually only when you're ready to run this transform):

   ```bash
   poetry add lpsn
   ```

4. **Add credentials to `.env` at the repo root** (same pattern the
   BacDive transform uses):

   ```
   LPSN_USERNAME=your.email@example.com
   LPSN_PASSWORD=your-password
   ```

   `.env` is already gitignored.

## Run

```bash
poetry run kg transform -s lpsn_api
```

Output: `data/transformed/lpsn_api/{nodes,edges}.tsv`.

Every API response is cached to `data/raw/lpsn/api_cache/<record_no>.json`
(gitignored) so partial runs resume cleanly and re-runs skip
already-fetched records.

## Expected wall-clock

- **Cold cache** — 6–10 hours for 34,300 records (LPSN's empirical
  ~1–2 req/s rate). Best run overnight.
- **Warm cache** — seconds. All hits are read from disk.

## Fail-safe behaviour

- Missing `LPSN_USERNAME` / `LPSN_PASSWORD` → `RuntimeError` with the
  fix instructions.
- Missing `lpsn` PyPI package → `RuntimeError` telling you to
  `poetry add lpsn`.
- Any per-record fetch error → counted, logged, and the run continues.
  Re-run to pick up whatever's left.

## Licensing note

LPSN data (both GSS CSV and JSON API responses) is CC BY-SA 4.0. This
transform stays code-only — its outputs are not currently ingested by
`merge.yaml` — until the licensing decision on issue #484 is made.
