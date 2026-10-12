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
4. Place the file at `data/raw/lpsn_gss.csv` in this repo.

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
  both parent and child rows are present in the same CSV and the parent
  scientific-name tuple resolves to exactly one native record ID. These
  remain structured-name joins, not explicit native numeric-parent fields.
  Ambiguous tuples never use row order, nomenclatural status, synonym links
  or the separately cached API to choose a parent (#1292).
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

## Ambiguity audit and completion

Every run writes `lpsn_parent_dispositions.tsv`, including a header-only file
when there are no ambiguous parents. Each ambiguity preserves the child,
every candidate's complete native CSV record and physical coordinates, source
path/SHA-256, all candidate projections, and the calculated legacy last-row
projection. Those projections are audit evidence, not graph assertions.
The legacy result is not labelled as a witnessed previous release assertion.

Malformed records are rejected before candidate construction; silently skipping
a malformed parent could manufacture apparent uniqueness. Duplicate native IDs,
missing/noncanonical IDs or genera, inconsistent subspecies fields, malformed
quoting, headers and row widths all abort. Valid missing-parent records retain
their nodes without invented edges.

The actual selected CSV (including a `data_file` override) and original audit
bytes are mandatory producer evidence. Finalization and merge admission refuse
missing/changed evidence. Atomic replacement of individual files is not a claim
of cross-file rollback or a completed source generation; the CLI invalidates
previous completion before running and records completion only after successful
finalization. No post-merge taxonomy repair is performed.

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
