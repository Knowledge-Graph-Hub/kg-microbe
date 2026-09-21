# Post-Merge TSV Cleanup

This document describes what happens when you see this line during
`poetry run kg merge -y merge.yaml`:

```
[merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place
```

## Where it runs

`kg_microbe/merge_utils/merge_kg.py::_cleanup_merged_outputs()`, invoked from
`load_and_merge()` immediately after `kgx.cli.cli_utils.merge` finishes. The
public command first validates finalized source bundles and current producer
dependencies, then runs KGX in a private staging directory. Required
serialization, graph-validation and manifest failures propagate and prevent
publication; they do not leave a partially cleaned replacement archive.
Optional invariant reports and statistics have separate failure handling.
See [source finalization responsibilities](PREMERGE_SOURCE_FINALIZATION.md).

## Why it exists

KGX's `TsvSink` produces three classes of artifacts we see in practice, and
the cleanup provides serialization compatibility for each:

1. **Duplicate header columns** (e.g. `provided_by` x2, `agent_type` x2) when
   source files are headerless subsets of each other and column order is
   reconstructed from per-record property sets.
2. **Auxiliary columns** that leak through from obograph ingestion —
   `subsets`, `meta`, and an edge `id` column — plus the deprecated
   `knowledge_source` sitting alongside its biolink 3.x replacement
   `primary_knowledge_source`.
3. **Stray `\r` characters** emitted mid-header by `TsvSink` when a source
   description contained an embedded CR (seen in ChEBI descriptions). This
   corrupts CSV-reader parsing of the merged file downstream — it was the
   exact cause of the "subject=`knowledge_level`, object=`meta`" false
   positive that `kg-model-review` used to report when it read the stale
   `merged-kg_default_edges.tsv`.

Transform-level schema normalization (each transform writes a canonical
header) removes most causes of (1) and (2). This post-merge step is
idempotent at the TSV-content level and becomes a schema no-op when sources
are already uniform. It normalizes transport CRLF only; an embedded `\r`
is an error requiring a source-level correction, not a byte to erase.
Category, identifier and ontology-reference decisions occur during source
finalization, not after graph union.

## Step-by-step

For each destination in `merged_graph.destination` in `merge.yaml` whose
`format: tsv`:

1. **Resolve paths** from the destination's `filename` (e.g. `merged-kg`):
   - `nodes_file = output_dir/merged-kg_nodes.tsv`
   - `edges_file = output_dir/merged-kg_edges.tsv`
   - `archive   = output_dir/merged-kg.tar.gz`
2. **Extract if compressed.** When `compression: tar.gz` is set and the
   archive exists but the loose TSVs do not, copy only its two regular TSV
   members into the private staging `output_dir`. Arbitrary archive members,
   links and paths are not extracted. This is the
   step that prints:
   ```
   [merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place
   ```
   A flag (`extracted_from_archive`) is remembered so the loose TSVs can be
   deleted again after re-archiving (KGX's sink didn't leave them behind, so
   neither do we).
3. **Normalize nodes** (`_normalize_nodes_tsv`):
   - Read the literal TSV header; normalize CRLF line endings via
     `_iter_clean_lines`, rejecting embedded carriage returns.
   - Plan output columns: canonical order (`id, category, name, description,
     xref, provided_by, synonym, deprecated, same_as`), then any unknown
     forward-compat columns; drop `subsets, meta, iri`; dedup any repeated
     column names by coalescing identical nonempty values. Conflicting
     nonempty duplicate-column values fail; no value silently wins.
   - Log the schema diff: `dropped=[…] added=[…] deduped=[…]`, or
     `schema already canonical (no-op)` when nothing changed.
   - Rewrite the file atomically via a tempfile `replace`.
4. **Normalize edges** (`_normalize_edges_tsv`):
   - Same header cleaning and canonical reordering
     (`subject, predicate, object, relation, primary_knowledge_source,
     knowledge_level, agent_type`).
   - Append the `has_percentage` extension column if present (metatraits).
   - Drop internal `id, key, meta` and legacy `knowledge_source` columns.
   - Merge legacy `knowledge_source` into `primary_knowledge_source`: when
     `primary_knowledge_source` is empty, fall back to `knowledge_source` on
     the same row before dropping the latter.
   - Same schema diff log line for edges.
5. **Validate and report.** Required canonical representation and endpoint
   validation writes `merged-kg_reference_resolution.tsv`, explicitly
   recording no semantic rewrites. It does not consult live ontology
   authorities or retarget/drop biological assertions. Optional invariant
   diagnostics and final TSV statistics follow. A failed stats annotation
   withholds that stats output rather than publishing misleading counts.
6. **Package the destination.** For `compression: tar.gz`, `_rewrite_tarball`
   atomically writes the TSV pair and
   validation report into the staged archive, plus `manifest.json` with each
   member's exact SHA256, byte size and row count. Members are flat, with no
   nested directory. The manifest also identifies configuration, schema and
   source-marker evidence. Uncompressed TSV destinations instead retain
   their loose pair/report and receive `<base>_manifest.json` beside them.
7. **Publish and remove temporary loose files.** If step 2 extracted the
   pair, remove those staging copies after packaging. The public command
   publishes completed staged artifacts only after required work succeeds.
   Existing unrelated older artifacts are warned about, not deleted.

## Configuration prerequisites

The cleanup only runs for destinations that are `format: tsv`. The archive
path is `<output_directory>/<filename>.tar.gz`, where both fields come from
`merge.yaml`:

```yaml
configuration:
  output_directory: data/merged
merged_graph:
  destination:
    merged-kg-tsv:
      format: tsv
      compression: tar.gz
      filename: merged-kg
```

Given that config, the cleanup will target `data/merged/merged-kg.tar.gz`.

## How to read the log output

| Log line | What it means |
|---|---|
| `[merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place` | Loose TSVs were missing; archive was untarred so normalizer could edit them. |
| `[merge-cleanup] nodes merged-kg_nodes.tsv: schema already canonical (no-op)` | Transform-level normalization did its job; nothing to fix here. |
| `[merge-cleanup] edges merged-kg_edges.tsv: dropped=['meta'] added=[] deduped=['agent_type']` | Dropped `meta` column, collapsed duplicate `agent_type` into one. |
| `[merge-validation] ...; no semantic rewrites` | Required validation completed; ontology and identity decisions were made upstream. |
| `[merge-invariants] check skipped: <error>` | Optional diagnostic failed; investigate, but this is separate from required graph validation. |
| `[merge-stats] annotation skipped: <error>` | Optional stats annotation failed; the failed stats file is withheld. |

A traceback from required normalization, validation or packaging aborts the
public command before replacing the previous archive. It is not a successful
but merely unnormalized merge.

## Idempotency

Already-normalized TSVs yield two schema no-op log lines. Validation,
statistics and packaging still run. TSV bytes can remain identical while
the archive hash changes because manifests and archive metadata record the
new build. Use the public command and its source gates, not direct cleanup,
to produce a new accepted merged artifact.

## Related

- Source: `kg_microbe/merge_utils/merge_kg.py`
- Constants: `CANONICAL_NODE_HEADER`, `CANONICAL_EDGE_HEADER`,
  `EDGE_COLUMNS_TO_DROP`, `NODE_COLUMNS_TO_DROP`, `EDGE_EXTENSION_COLUMNS`
  at the top of the same file.
- Downstream: `.claude/skills/kg-model-review/kg_model_review.py` reads the
  normalized `merged-kg.tar.gz` via `iter_tsv_from_tar`.
