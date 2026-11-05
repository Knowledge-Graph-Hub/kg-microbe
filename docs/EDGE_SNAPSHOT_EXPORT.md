# Verified edge occurrence exports

`kg_microbe.edge_snapshot` inventories an existing local KGX snapshot or exports
its edge rows for a curation consumer. It does not download data, run transforms,
normalize identifiers, merge duplicate observations, or certify scientific review.
The exporter uses Python 3.10+ and the standard library; it adds no CLAW dependency.

The input is an explicit version-1 graph manifest beside its uncompressed TSV
members. Both the archive's extracted `manifest.json` and a loose merge's
`merged-kg_manifest.json` work. Archive extraction and remote acquisition are
separate steps. All manifest members must be regular files with safe basename
names; links, duplicate JSON keys, unsupported manifest versions, and malformed
TSV rows are refused. The input manifest may include auxiliary tables in addition
to edges and nodes: every listed member is verified.

```bash
poetry run python -m kg_microbe.edge_snapshot inventory data/snapshot/manifest.json
poetry run python -m kg_microbe.edge_snapshot export \
  data/snapshot/manifest.json data/edge-exports/canary --max-rows 100
```

The default edge member is `merged-kg_edges.tsv`; use `--edge-member NAME.tsv`
for other manifest-bound filenames. `--max-rows 0` (the default) exports all edges.
An explicit bound exports the first N data rows, keeping their original ordinals.
**Even a one-row export reads and verifies the complete snapshot.** A checksum,
byte count, row count, encoding, or structural failure anywhere prevents publication.
An inventory also always verifies all members; it is not a sampling command.

For a standalone checkout without KG-Microbe's installed dependencies, run
`python kg_microbe/edge_snapshot.py ...`. The module itself imports only standard
library modules. The `python -m` form additionally executes KG-Microbe's existing
package initializer and therefore uses the normal installed project environment.

## Output and identity contract

A successful export creates a new directory containing:

- `manifest.json`: export contract `kg-microbe-curation/v1`, format
  `edge-occurrence-export`, version 1, verified input identities, headers,
  selection, shard bounds, and ordered shard descriptors.
- `source-manifest.json`: the exact original manifest bytes, independently
  verifiable against `source_manifest_sha256`; `source_manifest_file` names it.
- `occurrences-000001.jsonl`, etc.: newline-delimited UTF-8 JSON occurrences.
  An empty edge table produces zero shards and a complete empty export.

Each occurrence has `occurrence_id`, `manifest_sha256`, `member`,
`member_sha256`, `row_number`, `row_sha256`, and `source_row`.
`row_number` starts at 1 and excludes the header. `source_row` preserves the exact
UTF-8 source text, including its original LF/CRLF terminator or the absence of a
final terminator. Quotes, backslashes, pipe-separated strings, empty fields,
negation, qualifiers, and unfamiliar extension columns remain literal values.
The source row SHA-256 hashes its exact UTF-8 bytes, including the terminator.
The member descriptor includes both ordered `header` cells and exact `header_row`
text. Concatenating `header_row` and all occurrences' `source_row` in row order
reconstructs a complete exported edge member byte for byte.

The occurrence ID is `urn:kg-microbe:occurrence:v1:` followed by the SHA-256 of
the UTF-8 canonical JSON encoding of this envelope:

```json
{
  "contract": "kg-microbe-curation/v1",
  "kind": "occurrence",
  "payload": {
    "manifest_sha256": "<exact source manifest SHA-256>",
    "member": "merged-kg_edges.tsv",
    "member_sha256": "<complete member SHA-256>",
    "row_number": 1,
    "row_sha256": "<exact source row SHA-256>"
  }
}
```

Canonical JSON uses `sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=False`, and `allow_nan=False`. It applies no Unicode, identifier,
case, whitespace, or biological normalization. Location is not part of identity:
moving an unchanged snapshot preserves IDs. Changing manifest bytes changes its
snapshot identity, even if the only change is JSON formatting. Repeated identical
rows have distinct occurrence IDs because their ordinals differ. These IDs are
release occurrences, **not semantic observation IDs**, and do not match the
prefix-context-dependent RDF statement identifiers proposed in PR #1585.

`input_complete: true` means every input member was fully verified.
`selection.complete_export` independently reports whether all input edges were
exported. `selection.exported_rows` is the number actually persisted. Every shard
descriptor records its filename, SHA-256, byte count, row count, and first/last
source row number. No metadata marks an imported occurrence as reviewed.

## Bounds and publication

Default shard bounds are 100,000 occurrences and 32 MiB, whichever is reached
first (`--shard-rows`, `--shard-bytes`). A single serialized occurrence exceeding
the byte bound fails rather than violating it. Input rows, including headers,
are capped at 16 MiB (`--max-row-bytes`); source manifests are capped at 4 MiB.
Memory holds one input row, one serialized occurrence, and small file/shard
metadata, never the full graph. Compression and analytical Parquet exports are
separate future consumers of this lossless interchange.

All outputs are staged in a private sibling directory. Only after all checks
succeed is the directory renamed into its final location. Existing output is
refused. An exclusive sibling `.NAME.export-lock` serializes cooperating
exporters; unexpected termination can leave this lock or a private staging
directory, which requires inspection before a retry. Ordinary failures remove
only this invocation's stage and lock. Inputs and pre-existing outputs are never
rewritten. Do not concurrently create or replace the chosen destination through
another program during publication.

The command prints metadata, not source rows, and returns nonzero on failure.
Consumers should verify the source-manifest copy, each shard identity, contiguous
ordinals, exact row hashes, and occurrence IDs before admitting an export. The
first production use should be one bounded export through the real consuming
launcher, followed by verification that persisted counters and artifacts match.
