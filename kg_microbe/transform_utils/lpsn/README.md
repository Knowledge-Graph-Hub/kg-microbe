# LPSN transform

Ingests the LPSN GSS (Genus/Species/Subspecies) CSV bulk export into
KGX-format nodes and edges.

## Obtain the input CSV

LPSN publishes its GSS bulk export at
<https://lpsn.dsmz.de/downloads>, but the download is gated behind a
free LPSN account. To fetch:

1. Register at <https://lpsn.dsmz.de/register> (free; email + password).
2. Log in.
3. Navigate to <https://lpsn.dsmz.de/downloads> and download the GSS
   file (CSV).
4. Place the file at `data/raw/lpsn/lpsn_gss.csv` in this repo.

Neither `poetry run kg download` nor the transform itself will fetch
the file automatically; the login step must happen in your browser.

## Run the transform

```bash
poetry run kg transform -s lpsn
```

Output lands in `data/transformed/lpsn/nodes.tsv` and `edges.tsv`.

## Output shape

- **Nodes** — one `biolink:OrganismTaxon` node per LPSN record, with
  CURIE `lpsn:<record_no>`. Rows whose `status` matches an
  illegitimate / synonym / rejected category carry `deprecated=True`.
- **`subclass_of` edges** — from subspecies → species → genus when
  both parent and child rows are present in the same CSV.
- **`close_match` edges** — from each species / subspecies row to
  every culture-collection deposit named in `nomenclatural_type`.
  Deposits are parsed from strings like
  `"ATCC 11775 = DSM 30083 = JCM 1649"` and normalized to
  `kgmicrobe.strain:<code>` CURIEs, matching the strain CURIEs BacDive
  emits from the same culture-collection numbers. The merge step then
  reconciles both sides, giving BacDive strains a route to the
  authoritative LPSN taxon and vice-versa. Addresses the
  "normalize strain IDs" ask in issue #484 via the culture-collection
  path.

  Recognized culture-collection prefixes: `ATCC`, `DSM`, `JCM`, `LMG`,
  `NCTC`, `NRRL`, `NBRC`, `CCUG`, `CCTM`, `CIP`, `IAM`, `IFO`, `KCTC`.
  Additional prefixes can be added to the `_CULTURE_CODE` regex in
  `lpsn.py` as needed.

## Still deferred (issue #484)

- **NCBITaxon cross-refs** — LPSN doesn't publish NCBI IDs natively;
  needs a name-matching layer against NCBI's taxonomy (would use OAK's
  NCBITaxon adapter — same pattern as BacDive's transform).
- **GTDB cross-refs** — via GTDB's metadata, which cites LPSN IDs for
  species names; or via GTDB2NCBI on top of the NCBITaxon layer.
- **Full LPSN JSON API ingest** — richer than the GSS CSV
  (nomenclatural status details, publication DOI/PMID,
  `lpsn_correct_name_id` for reclassifications, `lpsn_parent_id` for
  the full taxonomic tree, 16S sequences).

## Redistribution

The LPSN copyright statement
(<https://lpsn.dsmz.de/text/copyright>) requires that websites making
use of the GSS files link back to LPSN. KG-Microbe includes an
`xref` field pointing at each record's canonical LPSN URL to satisfy
this.

The GSS CSV itself is NOT redistributed inside this repository — each
user must download their own copy via their LPSN account.
