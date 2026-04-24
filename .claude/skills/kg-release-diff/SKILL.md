---
name: kg-release-diff
description: Produce a standardized semantic-modeling diff report between two KG-Microbe merged-KG releases. Use when comparing KG versions to quantify changes in biolink/METPO categories, predicates, relations, CURIE prefixes, knowledge sources, and predicate × category signatures.
---

# KG-Microbe Release Semantic Diff

## Purpose

Compare two merged-KG releases (e.g. `data/merged/20260120` vs `data/merged/20260422_nometatraits`) along the axes that matter for **semantic modeling**, not just row counts:

1. **Schema** — which columns appear in nodes/edges in each release
2. **Biolink / METPO categories** — added, removed, count deltas; flags deprecated biolink categories still in use
3. **Predicates** — added, removed, count deltas; biolink vs METPO vocabulary shift
4. **Relation column** — added, removed, count deltas (RO / domain terms)
5. **CURIE prefix coverage** — on node ids, edge subjects, edge objects
6. **Knowledge-source / provided_by distribution** — which transforms contribute nodes/edges
7. **Predicate × (subject category, object category) signatures** — the strongest structural fingerprint of modeling choices

The report is a single Markdown file suitable for PRs, release notes, or hand-off to ontology reviewers.

## Usage

```bash
# Two release directories under data/merged/
poetry run python .claude/skills/kg-release-diff/kg_release_diff.py \
    --old data/merged/20260120 \
    --new data/merged/20260422_nometatraits \
    --out data/merged/release_diff_20260120_vs_20260422_nometatraits.md

# Or provide explicit TSV paths (either can be gzipped)
poetry run python .claude/skills/kg-release-diff/kg_release_diff.py \
    --old-nodes data/merged/old/merged-kg_nodes.tsv \
    --old-edges data/merged/old/merged-kg_edges.tsv \
    --new-nodes data/merged/new/merged-kg_nodes.tsv \
    --new-edges data/merged/new/merged-kg_edges.tsv \
    --old-label 20260120 \
    --new-label 20260422_nometatraits \
    --out release_diff.md
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--old PATH` / `--new PATH` | — | Directory containing `merged-kg_nodes.tsv` + `merged-kg_edges.tsv` (accepts `.gz`) |
| `--old-nodes/--old-edges/--new-nodes/--new-edges` | — | Explicit file paths (overrides directory lookup) |
| `--old-label STR` / `--new-label STR` | directory name | Human-friendly labels that appear in the report header |
| `--out PATH` | stdout | Write the Markdown report here |
| `--max-rows N` | 0 (no cap) | Row cap per file — useful for smoke tests |
| `--no-signatures` | false | Skip the predicate × category signature pass (saves ~150 MB RAM on large releases) |

## When to invoke

- Preparing release notes for a new merged KG
- Validating that a transform change produced the intended modeling shift (e.g. biolink → METPO predicate preservation)
- Auditing deprecated biolink terms across releases
- Diagnosing which knowledge source contributes which edge types

## How to report findings

When run interactively, after the script finishes:

1. Read back the **Summary** table and the top 3–5 rows from each change list
2. Call out any deprecated-biolink categories or unregistered-prefix warnings
3. Surface the predicate vocabulary shift (biolink vs METPO %) as a one-sentence takeaway — this is often the headline
4. Point the user at the full report path

The script emits progress lines to stderr (`[scan] old nodes: …`) so long runs don't look hung.

## Implementation

- `kg_release_diff.py` — streams both TSVs with `csv.DictReader` (reads by column name, tolerating column order / count differences).
- Counter-based aggregation keeps memory bounded regardless of file size, except for the node `id → category` map used for predicate × category signatures (~150 MB for a 2 M-node release; disable with `--no-signatures` if memory-constrained).
- Deprecated biolink categories are listed in `BIOLINK_DEPRECATED_CATEGORIES` near the top of the script — update as the Biolink Model evolves.

## Output structure

The generated Markdown has exactly these sections:

1. Summary (one numbers table)
2. Schema (columns) — nodes and edges subsections
3. Biolink / METPO category usage — added/removed/delta tables + deprecated list
4. Predicate usage — added/removed/delta tables + biolink-vs-METPO shift table
5. Relation column usage
6. CURIE prefix coverage — node id, subject, object subsections
7. `primary_knowledge_source` distribution
8. `provided_by` distribution on nodes
9. Predicate × (subject category, object category) signatures (omitted when `--no-signatures`)

Each added/removed/delta table is capped at 40 rows with a `…and N more` footer.
