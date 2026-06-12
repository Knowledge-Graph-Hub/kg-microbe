---
name: kg-postprocess-report
description: Generate a structured Markdown report on every post-transform and post-merge operation needed to take KG-Microbe from per-source TSVs to the final shipped data products (merged KG, RDF copy, release tarballs). Reports each operation's purpose, command, inputs, outputs, severity, and current freshness against the on-disk repo state. Use when planning a release, onboarding, auditing what is stale, or producing a "what's left to ship" punch list.
---

# KG-Microbe Post-Processing Report

## Purpose

`kg transform` and `kg merge` are not the end of the pipeline. There are roughly **20 additional operations** — mapping consolidation, schema validators, coverage reports, review gates, format conversions, release bundling — that have to happen (or have happened automatically) to arrive at the final shipped products.

This skill walks a hand-maintained catalog of those operations and emits a single Markdown report that, for each one, answers:

- What does it do, and why?
- Which command runs it?
- Which files does it read and write?
- Is its output present and fresh relative to its inputs, or is it stale / missing?
- Does it block a release, or is it merely recommended / optional?

It does **not** run any of the operations. It is a read-only inspector that tells you what state the repo is in and what work remains.

## Usage

```bash
# Auto-detect the most-recent data/merged/<release>/ and write to stdout
poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py

# Pin a specific merged release and save the report
poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py \
    --merged-dir data/merged/20260423 \
    --out reports/postprocess_status_20260423.md

# Inspect a different transformed root (e.g. when staging a parallel build)
poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py \
    --transformed-dir data/transformed_staging
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--repo PATH` | `.` | Repo root |
| `--merged-dir PATH` | most recent under `data/merged/` | Specific release dir to inspect |
| `--transformed-dir PATH` | `data/transformed` | Per-source transform output root |
| `--out PATH` | stdout | Write the Markdown report here |

## What's in the report

1. **Top-line summary** — release blockers that are missing or stale (the "what's left to ship" punch list), plus a counts table per status.
2. **Per-stage detail** — for each of the four stages:
   - `post-transform` — operations on `data/transformed/<source>/*.tsv` (mapping consolidation, validators, coverage reports, METPO proposal extraction).
   - `post-merge` — operations on the merged-KG (auto cleanup inside `kg merge`, summary stats, N-Triples conversion, Neo4j upload, DuckDB cache, holdouts).
   - `review-gate` — Claude-driven reviews that hard-block release (`kg-model-review`, `kg-path-review`) plus the recommended `audit-mappings`.
   - `release` — `kg-release-diff` and `kg-release` themselves.
3. **Per-operation entry** — purpose, command, inputs, outputs, status, severity, and any operational notes.

Status meanings:

| Status | Means |
|---|---|
| `ok` | Output exists and is newer than its most recent input |
| `stale` | Inputs newer than output — re-run |
| `missing` | Expected output not found |
| `auto` | Runs automatically inside another command (e.g. merge cleanup inside `kg merge`) |
| `n/a` | Operation has no tracked artifact; must be re-run to verify state |

Severity meanings:

| Severity | Means |
|---|---|
| `blocker` | A release should not go out without this being fresh |
| `recommended` | Usually part of release prep; skip with care |
| `optional` | Consumer-driven (e.g. Neo4j, holdouts, downstream queries) |

## When to invoke

- **Before cutting a release** — to produce the punch list of what's still stale.
- **After a long branch of transform work** — to see which downstream artifacts now need regeneration.
- **Onboarding** — single-page tour of the post-pipeline machinery.
- **Auditing** — comparing the catalog of "what should happen" against "what actually happened" for a given release.

## Maintaining the catalog

The operation catalog lives in `build_catalog()` inside `kg_postprocess_report.py`. To add a new operation:

1. Append an `Operation(...)` entry with its `stage`, `purpose`, `command`, `inputs`, `outputs`, and `severity`.
2. If the operation runs as a side-effect of another command (like `_cleanup_merged_outputs` inside `kg merge`), set `auto=True`.
3. If the operation has no tracked file output (just a stdout report), leave `outputs=[]` — the status will surface as `n/a`.
4. Cross-reference any related skill in the `notes` field.

The catalog is intentionally explicit (not introspected) so additions are reviewable and the report stays stable across runs.

## See also

- `kg-release` — consumes the review gates listed here as hard prerequisites
- `kg-release-diff` — produces one of the artifacts this report tracks
- `kg-model-review` / `kg-path-review` — the two release-blocking review skills
- `chemical-mapping` — owns the `kgmicrobe_unified_entity_mappings.sssom.tsv.gz` regeneration step
- `audit-mappings` — owns the broader mapping/code audit pass
- `CLAUDE.md` — top-level pipeline description (Download → Transform → Merge)
