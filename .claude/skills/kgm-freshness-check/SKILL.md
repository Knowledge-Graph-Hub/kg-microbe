---
name: kgm-freshness-check
description: Determine whether local KG-Microbe transform outputs (data/transformed/<source>/) and merged KG (data/merged/) are current relative to origin/master. Compares latest commit times on origin/master touching each transform's code directory against local output mtimes; also checks merge stage against merge_utils/, merge.yaml, and every transform output. Use before cutting a release, before running kg-release, or when triaging "why did my merged KG change".
---

# kgm-freshness-check

## Purpose

Answer one question:

> Do the transform outputs on disk (`data/transformed/<source>/`) and the
> merged KG (`data/merged/`) reflect the code that is on `origin/master`
> **right now**, or has master moved on and left them stale?

Compares latest commit timestamps on `origin/master` per code directory
against local output mtimes, and prints a per-source table + a merge-stage
summary.

## Usage

```bash
poetry run python .claude/skills/kgm-freshness-check/kgm_freshness_check.py
```

Options:

- `--ref <git-ref>` — compare against a different ref (default: `origin/master`)
- `--source <name>` — check only this source (repeatable). Default: every
  transform directory that has `<name>/<name>.py`
- `--json` — emit machine-readable JSON instead of the human table
- `--skip-fetch` — don't `git fetch origin master` even if the ref is
  missing locally

Exit codes: `0` = all FRESH, `1` = some STALE / MISSING, `2` = invocation
error (ref unresolved, etc.).

## Status codes

### Per source

| Status | Meaning | Suggested action |
|---|---|---|
| `FRESH` | Output mtime is newer than the latest commit on `origin/master` touching the code dir, AND the local working tree matches master. | Nothing to do. |
| `STALE_VS_CODE` | Master has commits touching this transform newer than the local output. | `poetry run kg transform -s <source>` |
| `LOCAL_CHANGES` | Local working tree diverges from `origin/master` for this transform's code dir. "Current vs master" is undefined until the diff lands. | Land the local diff (PR + merge), then re-check. |
| `MISSING_OUTPUT` | No `.tsv` / `.tsv.gz` in `data/transformed/<source>/`. | `poetry run kg transform -s <source>` |
| `NO_CODE` | `<source>/` directory exists but no `<source>.py` — probably a helper folder, not a transform. Skipped from freshness scoring. | none |

### Merge

| Status | Meaning | Suggested action |
|---|---|---|
| `FRESH` | Merged output is newer than `merge_utils/` code on master AND newer than `merge.yaml` AND newer than every transform output. | Nothing to do. |
| `STALE_VS_INPUTS` | At least one transform output is newer than the merged output. | Re-merge. |
| `STALE_VS_YAML` | `merge.yaml` (or `merge.minimal.yaml`) is newer than the merged output. | Re-merge. |
| `STALE_VS_CODE` | `merge_utils/` has commits on master newer than the merged output. | Re-merge (and rerun transforms if their `STALE_VS_CODE` is triggered by the same code bump). |
| `MISSING_OUTPUT` | No `data/merged/merged-kg_edges.tsv[.gz]` or `data/merged/merged-kg.tar.gz` on disk. | `poetry run kg merge -y merge.yaml` |

## Example output

```
SOURCE                 STATUS           CODE COMMIT (UTC)     OUTPUT MTIME (UTC)    LOCAL  NOTE
------------------------------------------------------------------------------------------------
bacdive                STALE_VS_CODE    2026-06-25T03:11:06Z  2026-06-22T21:24:00Z  no     code advanced 2.3 days after last output build; rerun `poetry run kg transform -s bacdive`
bactotraits            FRESH            2024-07-01T00:00:00Z  2026-06-22T22:25:00Z  no
bakta                  MISSING_OUTPUT   2026-06-01T00:00:00Z  -                     no     data/transformed/bakta/ has no .tsv/.tsv.gz
metatraits_gtdb        LOCAL_CHANGES    2026-06-26T00:00:00Z  2026-06-24T13:17:00Z  yes    local code diverges from origin/master; freshness vs master is not defined until the diff lands
...

MERGE
-----
  status           : STALE_VS_INPUTS
  merged output    : data/merged/merged-kg_edges.tsv
  merged mtime     : 2026-06-20T00:00:00Z
  merge_utils code : 2026-06-10T00:00:00Z (1aaaf8f8)
  merge yaml       : merge.yaml (2026-06-18T00:00:00Z)
  stale against    :
    - data/transformed/bacdive/
    - data/transformed/metatraits_gtdb/
  action           : rerun `poetry run kg merge -y merge.yaml` (or the config in use)

SUMMARY
-------
  FRESH            8
  STALE_VS_CODE    2
  LOCAL_CHANGES    1
  MISSING_OUTPUT   1
  NO_CODE          0
  merge            STALE_VS_INPUTS
```

## When to invoke

- **Before every `kg-release`** — a release built from stale outputs is
  the failure mode this skill exists to catch.
- **When a merged KG surprised you** — is the change explained by master
  moving on and forcing a rebuild, or is it a genuine transform bug?
- **When debugging a CI diff** — the CI often builds from a specific
  commit, so a `FRESH` verdict locally + a different result in CI tells
  you the code hasn't diverged.
- **Before running `poetry run tox`** in a release-adjacent state.

## Companion skills

- `kg-release` — the release cutter is the primary caller. Add
  `poetry run python .claude/skills/kgm-freshness-check/kgm_freshness_check.py`
  as a pre-flight if the release-gate script doesn't already run it.
- `kg-model-review` and `kg-path-review` — run those on the merged KG
  after re-running any STALE transforms.

## Limitations

- Timestamps are file mtimes, not commit-time metadata inside the file.
  Copying an output from another checkout with `cp -p` preserves mtime;
  a fresh `poetry run kg transform` sets mtime to now.
- Multiprocessing rebuilds set the mtime on every worker's output, so a
  half-finished transform can look partially fresh.
- The ref default is `origin/master`. On a fork, override with `--ref`.
- The `data/raw/` inputs are not currently checked. If a raw input was
  refreshed but its transform wasn't rerun, this skill will report the
  transform FRESH. That's a known gap; add a `--check-raw` mode if it
  becomes an issue.
