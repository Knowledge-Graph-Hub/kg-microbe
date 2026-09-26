---
name: kg-postprocess-report
description: Generate a structured Markdown report on every post-transform and post-merge operation needed to take KG-Microbe from per-source TSVs to the final shipped data products (merged KG, RDF copy, release tarballs). Reports each operation's purpose, command, inputs, outputs, severity, and current freshness against the on-disk repo state. Use when planning a release, onboarding, auditing what is stale, or producing a "what's left to ship" punch list.
---

# KG-Microbe Post-Processing Report

## Purpose

The catalog covers source finalization, merge/release validation, and recommended or optional downstream operations. Not every listed conversion or report is required for every release. The inspector verifies selected graph artifact integrity and distinguishes content-bound review evidence from mere file presence.

This skill walks a hand-maintained catalog of those operations and emits a single Markdown report that, for each one, answers:

- What does it do, and why?
- Which command runs it?
- Which files does it read and write?
- Is its output content-verified, present but unverified, invalid, or missing? Are timestamps only suggesting staleness?
- Does it block a release, or is it merely recommended / optional?

It does **not** run any of the operations. It is a read-only inspector that tells you what state the repo is in and what work remains.

## Usage

```bash
# Discover artifacts under data/merged/ and dated children; refuse ambiguous choices
poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py

# Select exactly one canonical, variant, or relocated archive and review directory
poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py \
    --archive data/merged/merged-kg.tar.gz \
    --review-dir data/review-merged-20260920.example

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
| `--merged-dir PATH` | root and dated children of `data/merged/` | Directory containing one unambiguous graph artifact |
| `--archive PATH` | auto-discovery | Exact archive; overrides discovery and may be a variant or relocated file |
| `--review-dir PATH` | auto-discovery | Additional review-evidence directory; repeatable |
| `--transformed-dir PATH` | `data/transformed` | Per-source transform output root |
| `--out PATH` | stdout | Write the Markdown report here |

## What's in the report

1. **Top-line summary** — blockers that are missing, invalid, unverified, timestamp-stale, or have no completion evidence; none are silently treated as green.
2. **Per-stage detail** — for each of the four stages:
   - `post-transform` — operations on `data/transformed/<source>/*.tsv` (mapping consolidation, validators, coverage reports, METPO proposal extraction).
   - `post-merge` — canonical first-write serialization, validation, final statistics, single archive construction, and optional N-Triples/Neo4j/DuckDB consumers.
   - `review-gate` — Claude-driven reviews that hard-block release (`kg-model-review`, `kg-path-review`) plus the recommended `audit-mappings`.
   - `release` — `kg-release-diff` and `kg-release` themselves.
3. **Per-operation entry** — purpose, command, inputs, outputs, status, severity, and any operational notes.

Status meanings:

| Status | Means |
|---|---|
| `ok` | The stated content-bound evidence verified; artifact integrity is not a biological or global release verdict |
| `invalid` | Archive/manifest integrity or matching review verdict failed |
| `unverified` | Output/report exists, but sufficient content-bound completion evidence is unavailable |
| `stale` | Timestamp-only hint that an input is newer; not proof of content drift |
| `missing` | Expected output not found |
| `auto` | Catalog execution mode only, never proof of successful completion |
| `n/a` | Operation has no tracked artifact; must be re-run to verify state |

Severity meanings:

| Severity | Means |
|---|---|
| `blocker` | Requires verified completion before release; presence or mtime alone is insufficient |
| `recommended` | Usually part of release prep; skip with care |
| `optional` | Consumer-driven (e.g. Neo4j, holdouts, downstream queries) |

## When to invoke

- **Before cutting a release** — to produce the punch list of what's still stale.
- **After a long branch of transform work** — to see which downstream artifacts now need regeneration.
- **Onboarding** — single-page tour of the post-pipeline machinery.
- **Auditing** — comparing the catalog of "what should happen" against "what actually happened" for a given release.

## Maintaining the catalog

### Content evidence and selection

The inspector does not extract archives or load graph TSVs into memory. It streams member SHA-256, byte lengths, and physical header-excluding row counts, comparing every member against `manifest.json`. Duplicate, unsafe, nonregular, incomplete, malformed, or corrupt members invalidate the artifact. Loose `*_manifest.json` bundles receive the same checks. A legacy archive or loose pair without a manifest is **unverified**, not missing and not verified. Artifact timestamps and directory timestamps never certify integrity. Multiple root/directory alternatives require explicit `--archive` selection (or a directory with exactly one artifact); old loose files are never silently preferred over an archive.

Review discovery includes `--review-dir`, `data/review-*`, and the corresponding skill's `reviews/` directory. Markdown that mentions the selected archive SHA-256 is only "report present; verdict not machine-certified". To certify a review, its producer may write a `*.receipt.json` alongside the report:

```json
{
  "receipt_version": 1,
  "skill": "kg-model-review",
  "archive_sha256": "<exact compressed archive SHA-256>",
  "scope": "full",
  "verdict": "pass",
  "report": "REVIEW.md",
  "report_sha256": "<exact report-byte SHA-256>"
}
```

`kg-path-review` requires its own receipt. Only an exact archive/report match, full scope, and explicit pass can yield `ok`. A matching non-pass receipt blocks release; mismatched, incomplete, or changed evidence cannot pass. This reporter never creates pass receipts, reruns reviews, or infers pass from prose. Existing reviews without receipts remain unverified even when their hash matches.

### Pipeline boundaries

Audited identifier/category/provenance and schema migration belongs to source finalization. The serializer emits canonical literal LF TSVs on first write; merge validates source admission and cross-source closure, recounts final statistics (retaining original KGX counts separately), constructs the archive once, and publishes only after required checks. Required validation/manifest failures propagate; optional diagnostics are separately reported. No post-merge biological repair or extract/rewrite/recompress cycle is expected on the standard path.

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
