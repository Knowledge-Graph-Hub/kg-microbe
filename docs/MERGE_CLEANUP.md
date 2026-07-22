# Post-Merge TSV Cleanup

This document describes what happens when you see this line during
`poetry run kg merge -y merge.yaml`:

```
[merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place
```

## Where it runs

`kg_microbe/merge_utils/merge_kg.py::_cleanup_merged_outputs()`, invoked from
`load_and_merge()` immediately after `kgx.cli.cli_utils.merge` finishes. The
cleanup is wrapped in a `try/except` so a cleanup failure never masks a
successful merge — it prints `[merge] post-merge cleanup skipped: <error>`
and proceeds.

## Why it exists

KGX's `TsvSink` produces three classes of artifacts we see in practice, and
the cleanup is defensive normalization for each:

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
idempotent and becomes a no-op when sources are already uniform. It does
**not** fix `\r` upstream because the byte is injected by KGX's sink, not
by the source files.

## Step-by-step

For each destination in `merged_graph.destination` in `merge.yaml` whose
`format: tsv`:

1. **Resolve paths** from the destination's `filename` (e.g. `merged-kg`):
   - `nodes_file = output_dir/merged-kg_nodes.tsv`
   - `edges_file = output_dir/merged-kg_edges.tsv`
   - `archive   = output_dir/merged-kg.tar.gz`
2. **Extract if compressed.** When `compression: tar.gz` is set and the
   archive exists but the loose TSVs do not, untar `merged-kg.tar.gz` into
   `output_dir` so the normalizer can edit files in place. This is the
   step that prints:
   ```
   [merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place
   ```
   A flag (`extracted_from_archive`) is remembered so the loose TSVs can be
   deleted again after re-archiving (KGX's sink didn't leave them behind, so
   neither do we).
3. **Normalize nodes** (`_normalize_nodes_tsv`):
   - Read header; strip stray `\r` from every line via `_iter_clean_lines`.
   - Plan output columns: canonical order (`id, category, name, description,
     xref, provided_by, synonym, deprecated, same_as`), then any unknown
     forward-compat columns; drop `subsets, meta, iri`; dedup any repeated
     column names by coalescing (first non-empty value wins).
   - Log the schema diff: `dropped=[…] added=[…] deduped=[…]`, or
     `schema already canonical (no-op)` when nothing changed.
   - Rewrite the file atomically via a tempfile `replace`.
4. **Normalize edges** (`_normalize_edges_tsv`):
   - Same header cleaning and canonical reordering
     (`subject, predicate, object, relation, primary_knowledge_source,
     knowledge_level, agent_type`).
   - Append the `has_percentage` extension column if present (metatraits).
   - Drop `id, meta, knowledge_source`.
   - Merge legacy `knowledge_source` into `primary_knowledge_source`: when
     `primary_knowledge_source` is empty, fall back to `knowledge_source` on
     the same row before dropping the latter.
   - Same schema diff log line for edges.
5. **Re-archive** (`_rewrite_tarball`). Write the normalized TSVs into a
   temp `*.tar.gz` in the same directory and atomically `shutil.move` it
   over `merged-kg.tar.gz`. Files are stored flat (`arcname=f.name`), so the
   archive contains `merged-kg_nodes.tsv` and `merged-kg_edges.tsv` at its
   root — no nested directory.
6. **Clean up loose files.** If step 2 extracted them, delete them now.

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
| `[merge] post-merge cleanup skipped: <error>` | Non-fatal: merge succeeded, cleanup raised. Investigate the error, but output is still usable (just unnormalized). |

## Idempotency

Running cleanup on an already-normalized archive yields two no-op log
lines (nodes + edges) and rewrites the tarball with identical contents.
Safe to invoke repeatedly.

## Related

- Source: `kg_microbe/merge_utils/merge_kg.py`
- Constants: `CANONICAL_NODE_HEADER`, `CANONICAL_EDGE_HEADER`,
  `EDGE_COLUMNS_TO_DROP`, `NODE_COLUMNS_TO_DROP`, `EDGE_EXTENSION_COLUMNS`
  at the top of the same file.
- Downstream: `.claude/skills/kg-model-review/kg_model_review.py` reads the
  normalized `merged-kg.tar.gz` via `iter_tsv_from_tar`.
