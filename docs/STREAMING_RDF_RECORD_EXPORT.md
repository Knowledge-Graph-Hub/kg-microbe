# Streaming RDF record export

This small extraction replaces the historical `make-nt` branch's full-file
Pandas loads and lossy identifier replacements. It does not activate a new
transform or modify any merged artifact.

```bash
poetry run python -m scripts.adhoc.export_kgx_records_nt \
  --nodes data/merged/merged-kg_nodes.tsv \
  --edges data/merged/merged-kg_edges.tsv \
  --prefix-map data/reviewed-prefixes.json \
  --output data/exports/merged-records.nt
```

Select the actual input paths explicitly. Supply a reviewed local JSON object
mapping prefixes to namespace IRIs; the tiny test map is not a production map.
No remote contexts, automatic namespace guesses, or graph-scale in-memory
objects are used. Inputs must be literal UTF-8, LF-terminated TSVs. Quotes and
pipe-delimited values are source text, not CSV quoting or automatic lists.

## Deliberately conservative RDF contract

This is **lossless record-oriented RDF**, not a full Biolink RDF projection:

- Every edge row has an `rdf:Statement` resource with `rdf:subject`,
  `rdf:predicate`, and `rdf:object` pointing to the expanded identifiers.
- The corresponding unconditional triple is **not asserted**. Doing so would
  turn negated or qualified observations into unconditional positive facts.
- Every original cell, including empty cells, is retained as a literal under
  `urn:kg-microbe:tsv-field:<percent-encoded-column-name>`. No metadata is lost
  and independent observations are not pooled. Consumers must interpret the
  original qualifier and provenance columns before deriving biological claims.
- Each node declaration is a `urn:kg-microbe:tsv-record:NodeRow`, with its
  expanded identifier in `rdf:subject` and all cells preserved in the same way.
- Row-resource identifiers include the prefix-map SHA-256, input SHA-256 and
  one-based data-row ordinal. Duplicate source rows remain separately
  identifiable; exports using different contexts cannot collide when combined.
- File comments contain the format version, input/prefix-map hashes, column
  order and row counts. Original TSV bytes remain the canonical artifacts.

Only declared CURIE expansion and RDF string escaping occur. Invalid IRIs
fail with an upstream-correction request; `°`, arrows and other legal Unicode
are not replaced. Unknown prefixes fail rather than acquiring invented bases.

Output is streamed to a sibling temporary file and published atomically using
a no-overwrite hard link after successful EOF and input-stability checks.
An existing destination (including a symlink) is never replaced. Temporary
files are removed after failure. Memory is bounded by the largest row and the
explicit prefix map, not graph size. Disk use includes the final N-Triples
file, which can be substantially larger than the source TSVs.

A conventional Biolink RDF projection, compression/archive packaging and
production merge integration are separate work. This PR intentionally does
not claim those capabilities or silently discard assertion qualifiers.
