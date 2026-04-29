---
name: kg-release
description: Cut an official KG-Microbe GitHub release. Bundles merged-KG + transformed + raw, links a review verdict, splits assets that exceed GitHub's 2 GiB per-file limit, and falls back to Zenodo for very large payloads. Use when publishing a new merged KG to Knowledge-Graph-Hub/kg-microbe releases.
---

# KG-Microbe Release

## Purpose

Cut an official GitHub release for a merged KG. One command produces:

- `merged-kg_<release>.tar.gz` — merged-KG TSVs (always single-file, fits GitHub)
- `data_transformed_<release>.tar.gz` — every per-source `data/transformed/<source>/` (split if > 1.9 GiB)
- `data_raw_<release>.tar.gz` — `data/raw/` snapshot (almost always split, often Plan B)
- `release_notes_<release>.md` — review verdicts + key signature deltas
- `MANIFEST_<release>.json` — every asset's sha256 + reassembly recipe for split parts

The skill **gates the release on a review verdict**. It looks for a recent artifact from `kg-model-review`, `kg-path-review`, and `kg-release-diff`, and runs whatever's missing. A `needs-attention` verdict blocks the release unless `--ignore-review` is passed.

## Why this needs Plan B

`data/raw/` is currently ~12 GB on disk and compresses to roughly 5-8 GB. `data/transformed/` is ~2 GB on disk and compresses to roughly 0.5-1.5 GB. GitHub release assets are capped at **2 GiB per file**, with no overall per-release cap. So:

| Asset | Typical size after gzip | GitHub fit | Strategy |
|---|---|---|---|
| `merged-kg_<release>.tar.gz` | 50-150 MB | yes | upload as-is |
| `data_transformed_<release>.tar.gz` | 0.5-1.5 GB | usually yes | upload as-is, split if > 1.9 GiB |
| `data_raw_<release>.tar.gz` | 5-8 GB | **no** | split into 1.9 GiB parts **or** Plan B (Zenodo) |

### Plan A — split-and-stitch (default)

Anything > 1.9 GiB is split with `split -b 1900M -d` into `<asset>.part-00`, `<asset>.part-01`, … Every part is uploaded to the GitHub release. The manifest records the original sha256 plus each part's sha256 plus the reassembly recipe:

```bash
cat data_raw_v20260428.tar.gz.part-* > data_raw_v20260428.tar.gz
sha256sum data_raw_v20260428.tar.gz   # must match MANIFEST_v20260428.json:assets.data_raw.sha256
```

Pros: single canonical home (the GitHub release page). Cons: clunky for non-CLI users.

### Plan B — Zenodo for raw, GitHub for everything else

Zenodo gives free 50 GB per record, mints a DOI, and is the academic standard for research data drops. When total split-part count would exceed `--max-parts` (default 6) or `--zenodo-raw` is passed, the skill:

1. Builds `data_raw_<release>.tar.gz` whole (no split).
2. Posts it to Zenodo via REST API (`ZENODO_TOKEN` env var required).
3. Records the Zenodo DOI in `MANIFEST_<release>.json` and in the GitHub release notes ("Raw data available at https://doi.org/10.5281/zenodo.NNNNN").
4. Leaves merged + transformed on GitHub.

Use Plan B when you expect the raw payload to grow further or when you want a permanent DOI for citation. The Zenodo subroutine is opt-in; the script does not silently push to Zenodo.

## Usage

```bash
# Standard release: master is checked out, data/merged/<release>/ exists
poetry run python .claude/skills/kg-release/kg_release.py \
    --release v20260428 \
    --merged-dir data/merged/20260428

# Dry-run: build tarballs locally, no gh release create, no upload
poetry run python .claude/skills/kg-release/kg_release.py \
    --release v20260428 \
    --merged-dir data/merged/20260428 \
    --dry-run

# Plan B: push raw to Zenodo (requires ZENODO_TOKEN)
ZENODO_TOKEN=xxx poetry run python .claude/skills/kg-release/kg_release.py \
    --release v20260428 \
    --merged-dir data/merged/20260428 \
    --zenodo-raw

# Skip raw entirely (users can regenerate via `kg download`)
poetry run python .claude/skills/kg-release/kg_release.py \
    --release v20260428 \
    --merged-dir data/merged/20260428 \
    --skip-raw

# Force release despite needs-attention review
poetry run python .claude/skills/kg-release/kg_release.py \
    --release v20260428 \
    --merged-dir data/merged/20260428 \
    --ignore-review
```

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--release NAME` | required | Release name (also git tag and asset suffix), e.g. `v20260428` |
| `--merged-dir PATH` | required | `data/merged/<dir>/` containing `merged-kg_nodes.tsv` + `merged-kg_edges.tsv` (or already-tarballed) |
| `--repo OWNER/NAME` | from `gh repo view` | Target GitHub repo for the release |
| `--prerelease` | false | Mark as pre-release |
| `--draft` | false | Create as draft (assets uploaded, release not visible) |
| `--skip-raw` | false | Omit `data/raw/` from the release entirely |
| `--skip-transformed` | false | Omit `data/transformed/` |
| `--zenodo-raw` | false | Plan B — upload raw to Zenodo instead of splitting on GitHub |
| `--zenodo-sandbox` | false | Use Zenodo sandbox (sandbox.zenodo.org) for testing |
| `--max-parts N` | 6 | Auto-trigger Zenodo for raw when split would exceed N parts |
| `--ignore-review` | false | Proceed even if review verdict is `needs-attention` |
| `--review-max-age-days N` | 7 | How fresh review artifacts must be before they're trusted |
| `--out-dir PATH` | `releases/<release>` | Where to stage tarballs locally |
| `--dry-run` | false | Build everything but don't `gh release create` or upload |

## Workflow

1. **Pre-flight** — verify `gh auth status`, working tree clean, master/release branch, tag does not exist.
2. **Review gate** — collect most recent artifact from each review skill. If older than `--review-max-age-days` or missing, run the review. Block on `needs-attention` unless `--ignore-review`.
3. **Stage assets** in `<out-dir>`:
   - `merged-kg_<release>.tar.gz` — recompress from `<merged-dir>` (always rebuild for reproducibility).
   - `data_transformed_<release>.tar.gz` — `tar c -I 'gzip -1' data/transformed`.
   - `data_raw_<release>.tar.gz` — same for `data/raw`.
4. **Size check** — for each tarball > 1.9 GiB, split into `<asset>.part-NN` and record reassembly. If the raw split would exceed `--max-parts`, fall back to Zenodo (with confirmation) or fail with a clear "use --zenodo-raw" message.
5. **Manifest** — `MANIFEST_<release>.json` with sha256 of every asset, byte size, and Zenodo DOI if used.
6. **Release notes** — synthesize from the review reports + (optionally) `kg-release-diff` against the prior release.
7. **Publish** — `gh release create <release> --title ... --notes-file release_notes_<release>.md <assets...>`.
8. **Verify** — re-fetch the release, list assets, print URLs.

## Plan B implementation notes

Zenodo REST API requires a token. The skill uses `requests` (already a dependency via kghub-downloader) and makes:

```
POST   https://zenodo.org/api/deposit/depositions  (create empty deposit)
PUT    https://zenodo.org/api/deposit/depositions/{id}/files/{filename}  (upload, supports >5 GB)
PUT    https://zenodo.org/api/deposit/depositions/{id}  (set metadata — title/version/desc)
POST   https://zenodo.org/api/deposit/depositions/{id}/actions/publish  (publish; mints DOI)
```

The deposit metadata is auto-populated:

- title: `KG-Microbe <release> — raw source data`
- version: `<release>`
- description: a one-paragraph blurb plus a link back to the GitHub release
- creators: read from `git log` / `pyproject.toml` authors
- keywords: `["knowledge graph", "microbiology", "BacDive", "KG-Microbe"]`
- license: `cc-by-4.0` (matches KG-Hub convention)

Set `--zenodo-sandbox` to test against `sandbox.zenodo.org` first — it issues fake DOIs but otherwise behaves identically.

## Output structure

```
releases/v20260428/
├── merged-kg_v20260428.tar.gz
├── data_transformed_v20260428.tar.gz
├── data_raw_v20260428.tar.gz.part-00
├── data_raw_v20260428.tar.gz.part-01
├── data_raw_v20260428.tar.gz.part-02
├── data_raw_v20260428.tar.gz.part-03
├── MANIFEST_v20260428.json
├── release_notes_v20260428.md
└── reviews/        # snapshots of the review reports used to gate this release
    ├── kg-model-review_<ts>.md
    ├── kg-path-review_<ts>.md
    └── kg-release-diff_<ts>.md
```

The `releases/` dir is `.gitignore`d (managed by this skill).

## When to invoke

- Cutting a tagged release after a clean merge build.
- Republishing a release with corrected metadata (re-run with same `--release` and `--draft`).
- Building reproducible local artifacts before pushing to GitHub (use `--dry-run`).

## See also

- `kg-model-review` — KGX/Biolink/METPO conformance gate
- `kg-path-review` — multi-hop semantic path gate
- `kg-release-diff` — old-vs-new release diff used to populate release notes
- `kg_microbe/merge_utils/merge_kg.py` — produces the merged KG that this skill packages
