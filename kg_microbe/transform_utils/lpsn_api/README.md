# LPSN JSON API transform

Enriches the GSS-based `lpsn` transform with the fields that only live
in LPSN's authenticated JSON API (per-record):

- **Publication provenance** — `publication_doi`, `publication_pmid`,
  `ijsem_list_doi` supply `doi:*` / `PMID:*` publication subjects with
  `biolink:mentions` / `IAO:0000136` edges to the LPSN taxon, plus
  `biolink:Publication` nodes. Their labels use the
  corresponding `publication_text` or `ijsem_list_text` citation supplied by
  LPSN, with the source field recorded in the description. These are complete
  source citations, not separately verified paper titles. Repeated identifiers
  are emitted once; conflicting nonempty citation strings leave the label
  unresolved and retain the alternatives in the description. Missing or malformed
  citation text supplies no label. No identifier-derived label is invented (#1834).
- **Full above-genus taxonomy** — `lpsn_parent_id` becomes a
  `biolink:subclass_of` edge that connects genera up to family / order
  / class / phylum / domain LPSN records the GSS export doesn't include.
- **Nomenclatural genealogy** — `basonym_id` becomes a
  `biolink:same_as` edge (relation `skos:exactMatch`) from a comb. nov.
  name to its basonym.
- **Node-level detail** — `is_legitimate` (boolean) and richer
  `nomenclatural_status` / `lpsn_taxonomic_status` prose folded into
  each node's `description`.

- **16S rRNA sequence provenance** — `molecules[]` supplies INSDC
  (GenBank / EMBL / DDBJ) accession subjects with `biolink:in_taxon` /
  `RO:0002162` edges to the LPSN taxon, plus a `biolink:NucleicAcidEntity`
  node per accession.
- **Selected GSS overlap** — only exact hierarchy or basionym triples already
  emitted in the selected sibling `edges.tsv` are suppressed. The presence of
  a taxon ID alone does not suppress a link. Higher parents and other API-only
  relationships remain, along with their linked-record evidence.

Both selected GSS files are consumed and audited under native input contract
version 2. Their bytes and selected locators remain mandatory during source
finalization and downstream admission. A version-1 completion requires producer
regeneration; it cannot be relabeled as having consumed the GSS edges.

## Prerequisites

1. **Run the GSS transform first**:

   ```bash
   poetry run kg transform -s lpsn
   ```

   This creates `data/transformed/lpsn/nodes.tsv` and `edges.tsv`. The API
   transform reads the former for record selection and the latter for exact
   overlap suppression. Both files are required, including for a custom selection.

2. **Register a free LPSN account** at <https://lpsn.dsmz.de/register>.

3. **Install dependencies.** The `lpsn` Python client is now a project
   dependency (`lpsn = "^1.0.0"` in `pyproject.toml`), so a normal
   `poetry install` provides it — no manual `poetry add` needed.

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

Output: `data/transformed/lpsn_api/{nodes,edges}.tsv`, plus the required
`lpsn_api_records.tsv` consumed-record audit.

Every API response is cached to `data/raw/lpsn/api_cache/<record_no>.json`
(gitignored) so partial runs resume cleanly and re-runs skip
already-fetched records.

Cached and live API payloads must be objects with an `id` that exactly matches
the requested record number before any source field is attributed (#1837).
New responses are written atomically, then parsed from immutable consumed-input
snapshots. The GSS selection and every consumed API record's bytes are bound to
source completion, together with their selected lexical cache paths (#1838).
Changed, missing or redirected inputs invalidate completion and require a new
run. The record audit also records requested cache paths that stayed absent;
an absent cache file is not evidence of a remote API answer. Unrequested cache
entries are outside the inventory. An initially empty cache remains supported
because generated API records are recorded dynamically after persistence.
Admission independently reconstructs the required inventory from the verified
GSS selection and API parent/basonym links, using production's ordering, cycle
and depth rules. Dropping a selected record from the ledger and rehashing its
metadata cannot remove that record from the required input set (#1840).

Records the API does not serve at all — every basonym that predates the
Approved Lists (665 in the 2026-09-10 graph, #1004) — are labelled from
LPSN's public web page `https://lpsn.dsmz.de/taxon/<record_no>` instead:
rank and name from the page title, nomenclatural and taxonomic status from
the page body. Those are cached apart, under `data/raw/lpsn/web_cache/`,
and the node's description says the label came from the page. No edges are
minted from a page. If the page fetch fails too, the node is an unnamed
stub in our namespace, as before.

The new consumed-record contract covers API-derived fields, including publication
citation labels. Existing web-fallback names are outside this API-specific input
binding; the audit does not claim to verify their page bytes.

## Expected wall-clock

- **Cold cache** — 6–10 hours for 34,300 records (LPSN's empirical
  ~1–2 req/s rate). Best run overnight.
- **Warm cache** — seconds. All hits are read from disk.

## Fail-safe behaviour

- Missing `LPSN_USERNAME` / `LPSN_PASSWORD` → `RuntimeError` with the
  fix instructions.
- Missing `lpsn` PyPI package → `RuntimeError` telling you to
  `poetry add lpsn`.
- Per-record transport errors → counted, logged, and the run continues.
  Re-run to pick up whatever's left.
- Malformed or misidentified cached/live API payloads, failed cache writes or
  changed consumed inputs → abort before source completion; no silent re-fetch
  substitutes new bytes for failed consumed evidence.
