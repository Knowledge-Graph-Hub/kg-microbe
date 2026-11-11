# Offline isolation-source evidence

This small extraction retains the useful intent of the historical
`feat/schema-automator-isolation-sources` and `isolation-source-fix` branches:
group BacDive isolation descriptions by native record without losing evidence.
It does **not** activate a transform, change downloads or merge configuration,
create KGX nodes/edges, or infer an ontology identity from a label.

## Explicit local inputs and outputs

```bash
python scripts/adhoc/reshape_isolation_evidence.py \
  --input data/raw/bacdive_isolation_sources.csv \
  --output data/isolation-evidence-20261013.json
```

The input is a UTF-8 CSV, optionally with a BOM. Required header names are
`ID`, `Species`, `Culture collection number`, `Isolation source`, `Country`,
`Continent`, `Category 1`, `Category 2`, `Category 3`; their corresponding
snake-case names are also accepted. Header order may vary, but unknown,
missing or duplicate logical columns fail. IDs must be canonical positive
decimal strings: ambiguous values are rejected, never repaired or omitted.
Blank physical records, empty inputs, field-width errors and malformed quoting
also fail. The parser limits individual CSV fields to 16 MiB.

The output parent must already exist. The tool publishes **one new JSON file**
only after completing the export and checking that the source bytes remain
unchanged. Existing files, directories and symlinks are never overwritten,
including a destination created concurrently. A same-filesystem hard link
publishes the completed temporary file atomically; unsupported filesystems fail
without an alternative overwrite path. Ordinary failures and interruptions
clean up only the private temporary directory. Forced process termination can
leave that private directory, not a claimed complete result.

The tool uses only Python's standard library. Grouping and distinct-value
indexes use a private SQLite database, including nonadjacent rows for one ID.
Neither the full input nor all rows for a record group are collected in memory.
The output is streamed; downstream large-data readers should stream
`records.item` rather than load the complete JSON document.

## What is preserved

- Every parsed source row, including exact duplicate occurrences, is retained
  with its data-record ordinal and physical start/end line numbers.
- `raw_fields` preserves literal decoded cell strings and original column
  names. Quoted commas/newlines, `NA`, `N/A`, whitespace, case and `#` prefixes
  are not treated as missing values or replaced by ontology labels.
- `source` records the selected path, complete original-byte SHA-256, byte
  count and explicit header mapping. This identifies the parsed snapshot;
  it is not a claim that the local file is a verified current upstream release.
- Distinct derived lists split `###` only in isolation description, country
  and continent, trimming the derived tokens. The original cells remain exact.
  Species and culture collection strings are not delimiter-split or coerced.
- Conflicting nonempty species or culture-collection strings are all retained
  and flagged in `conflicting_fields`. Nothing chooses the first or preferred
  value. Duplicate counts do not remove raw occurrences.
- Summary counts `distinct_bacdive_ids` and `conflicting_bacdive_ids` describe
  native record IDs, not counts of distinct biological strains or taxa.
- Category paths preserve their three source levels, including absent levels
  as empty strings. They are not flattened into unrelated category labels.

The structural contract is
[`bacdive_isolation_evidence.schema.json`](../schema/bacdive_isolation_evidence.schema.json).
It uses JSON Schema with local references and the project's existing
`jsonschema` test dependency. It is not an inferred LinkML biological model;
schema validity alone cannot establish conservation or scientific correctness.
Tests separately check occurrence conservation, conflict retention and atomic
publication. The small CSV fixture is **synthetic**, not a captured BacDive
release, and explicitly exercises conflicting and ambiguous descriptions.

## Deliberately undecided biological interpretation

The text `mouth`, for example, remains a source string. No primary-label or
exact-synonym first hit is chosen. A later, separately reviewed mapping tool
would need explicit source context, complete ambiguity reporting, pinned
authorities and user-reviewed dispositions. It must distinguish descriptions,
host/anatomical sites, materials, qualities and source classification headings.
This export asserts no `EnvironmentalFeature`, `location_of`, category
hierarchy, disease state, organism phenotype or equivalence.

Historical full-BacDive coercion schemas, June merged-graph schemas, Fermentation
Explorer payloads and in-place ENVO annotation scripts are intentionally not
included. No schema-automator installation or network lookup occurs.
