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

## Output shape (MVP)

- **Nodes** — one `biolink:OrganismTaxon` node per LPSN record, with
  CURIE `lpsn:<record_no>`. Rows whose `status` matches an
  illegitimate / synonym / rejected category carry `deprecated=True`.
- **Edges** — `biolink:subclass_of` from subspecies → species → genus
  when both parent and child rows are present in the same CSV. No
  external cross-references in the MVP (see follow-up section).

## Follow-ups (issue #484)

The MVP intentionally omits:

- **NCBITaxon cross-refs** — LPSN doesn't publish these natively; we
  need a name-matching layer against NCBI's taxonomy.
- **GTDB cross-refs** — same story; via GTDB's own metadata, which
  cites LPSN IDs for species names.
- **BacDive cross-refs** — LPSN's `type_strain_names` (via the JSON
  API, not the GSS CSV) links to culture-collection designations
  (`DSM 12345`, `ATCC 12345`) that BacDive tracks. Normalizing
  requires either the LPSN JSON API (also login-gated) or a merge-time
  reconciliation step.

These cross-refs are the point of the follow-up work tracked on
issue #484.

## Redistribution

The LPSN copyright statement
(<https://lpsn.dsmz.de/text/copyright>) requires that websites making
use of the GSS files link back to LPSN. KG-Microbe includes an
`xref` field pointing at each record's canonical LPSN URL to satisfy
this.

The GSS CSV itself is NOT redistributed inside this repository — each
user must download their own copy via their LPSN account.
