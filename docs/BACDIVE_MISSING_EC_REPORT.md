# BacDive source EC annotation diagnostic

Run against an explicit local source snapshot:

```bash
poetry run python scripts/adhoc/report_bacdive_missing_ec.py \
  --raw data/raw/bacdive_strains.json \
  --out data/reports/bacdive-missing-ec
```

This extracts the useful diagnostic from the historical `unmapped-enzymes`
branch. It does not import the generated historical report or change downloads,
transforms, mappings, or merged KG artifacts. There are no network calls or
ontology lookups. The Poetry lock already supplies `ijson`; if it is unavailable
outside that environment, the command fails with an actionable message. Help
works without importing the parser.

Inputs may be a JSON array or an object keyed by source-record identifiers.
Duplicate object keys and malformed record/enzyme containers are rejected.
One source record is held at a time; label aggregation and distinct-ID counting
use temporary SQLite tables, not an in-memory graph-sized collection. A single
unusually large source record can still require proportionate memory.

The destination must be new. The report is built in a sibling temporary
directory and published only after parsing succeeds and the source SHA-256
remains unchanged. An existing destination, including a symlink, is never
overwritten. The temporary database is not a deliverable.

| File | Meaning |
|---|---|
| `observations.tsv` | One missing/malformed-EC enzyme observation per row, with source coordinate, path, BacDive ID, literal enzyme and classification JSON. Activity and `@ref` remain in enzyme JSON. |
| `labels.tsv` | Exact source-label JSON and EC-status counts, ordered by descending count then label/status. No label normalization or identity resolution. |
| `summary.json` | Source byte fingerprint and explicit observation/record counts. |

`absent`, `null`, and `blank` are source annotation gaps. `invalid_type` is a
separate diagnostic, including numeric, boolean, array, or object EC values.
`present` only means a nonblank string, not a validated EC identifier. Negative
and unknown enzyme activities are retained, not presented as capabilities.
Nothing here establishes that the enzyme is absent from KG-Microbe or that a
name-to-EC mapping would be scientifically justified.

Counts concern source occurrences and records, not biological strains. The
distinct-ID count includes only nonempty string/integer `General.BacDive-ID`
values among reported observations; duplicate records can share that ID.
MongoDB `_id` values are never substituted for BacDive IDs. Missing identity
stays blank and the source coordinate locates the record. Evidence JSON preserves
values and numeric precision, not original whitespace or object-key order.

Do not commit generated reports. A new source snapshot needs a new output
directory; this command does not establish the historical branch's backlog size.
