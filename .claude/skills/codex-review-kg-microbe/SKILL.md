---
name: codex-review-kg-microbe
description: Emit a Codex-ready review prompt for the KG-Microbe repository focused on code logic, consistency, robustness, bugs, bottlenecks, and scalability. Use before delegating a deep review pass to Codex (via the codex:rescue subagent) or another external code-review agent so the target is precisely scoped and the review dimensions are enforced.
---

# codex-review-kg-microbe

## Purpose

Compose a single self-contained prompt string that Codex (or any comparable
LLM-backed code reviewer) can consume to review the KG-Microbe repository
across six specific dimensions:

1. **Code logic** — control flow, data flow, semantic correctness
2. **Consistency** — API usage, naming, error handling, prefix/CURIE handling, config conventions
3. **Robustness** — edge cases, malformed input handling, IO failure paths, retry/backoff, idempotency
4. **Bugs** — provable errors reachable on real inputs (not stylistic)
5. **Bottlenecks** — hot paths, quadratic patterns, redundant IO, missed batching, sync-in-async
6. **Scalability** — memory footprint on realistic sizes (150 M UniProt edges, 12 GB `data/raw`, 500 GB RAM regime), streaming vs load-all, multiprocessing correctness

The output is a prompt only — this skill never talks to Codex directly.
Hand the emitted text off to `codex:rescue` (the `Agent(subagent_type='codex:codex-rescue', ...)` path) or paste it into `codex exec`.

## Usage

`/codex-review-kg-microbe [scope]`

- `scope` (optional) — a repo-relative subtree the review should focus on.
  Examples: `kg_microbe/transform_utils/bacdive`,
  `kg_microbe/transform_utils/metatraits_gtdb`,
  `kg_microbe/merge_utils`, `kg_microbe/utils`, `scripts`, `tests`.
  Default: the whole repo (`.`).

## Behavior when invoked

When invoked, output the prompt exactly as constructed below, substituting
`{{scope}}` and today's date (`YYYY-MM-DD`). Do NOT execute the review
yourself; do NOT edit any files; do NOT summarize the repo.

If `scope` is not supplied, use `.` and add the line
`Prioritize kg_microbe/transform_utils/ and kg_microbe/merge_utils/ over auxiliary directories.`
at the end of the "What to focus on" section.

---

## Prompt template

Emit the following as a single fenced block, ready to be piped into Codex.
The `{{scope}}` placeholder and today's date get filled in; everything
else is literal.

```
You are an experienced code reviewer performing a repo-wide review of
KG-Microbe (Knowledge-Graph-Hub/kg-microbe) at commit HEAD.

## Repo context

KG-Microbe is a Python knowledge-graph construction pipeline with three
stages — **Download → Transform → Merge** — that ingests BacDive,
MediaDive, BactoTraits, UniProt, CTD, Disbiome, Wallen et al., Madin et
al., MetaTraits, GTDB, Rhea, and a handful of OBO ontologies (ENVO,
ChEBI, GO, NCBITaxon, MONDO, HP, EC), and emits Biolink-modeled
`nodes.tsv` + `edges.tsv` per source plus a merged KG.

Key entry points:

- CLI: `poetry run kg download | transform | merge | query-organism`
  (`kg_microbe/run.py`, Click-based).
- Transforms: `kg_microbe/transform_utils/<source>/<source>.py`, each a
  subclass of `Transform` in `transform_utils/transform.py`. Registered
  in `DATA_SOURCES` in `transform.py`.
- Merge: `kg_microbe/merge_utils/merge_kg.py` (KGX library).
- Shared conventions: `transform_utils/constants.py` (column names,
  path constants), `transform_utils/custom_curies.yaml`
  (CURIE→URI map), `transform_utils/translation_table.yaml`
  (entity-type translations).

Scale to keep in mind:
- BacDive transform emits ~1 M edges.
- MetaTraits (GTDB variant) processes ~85 K taxa; sequential mode
  takes 5–8 h, multiprocessing 1.5–2.5 h. Multiproc is auto-enabled
  when ≥ 2 input files exist or a single file is chunk-split. Each
  worker needs ~3 GB RAM (OAK adapter + processing).
- Merged KG has ~150 M nodes / 555 M edges when UniProt is included.
- `data/raw/` is ~12 GB; some transforms have historically required
  >500 GB RAM (NCBI taxonomy trim, UniProt processing).

## Review scope

Focus on: **{{scope}}**

Recurse into every Python file under that path. Ignore vendored data
files, `data/`, `notebooks/`, `.tox/`, `.venv/`, `__pycache__/`,
generated `data/transformed/*/nodes.tsv|edges.tsv`, and anything under
`.gitignore`.

## Review dimensions — required

Evaluate every file you read against **all six** of these dimensions.
Not every file will have findings in every dimension; that's expected.
Do not skip a dimension.

1. **Code logic**
   - Incorrect control flow, off-by-one indexing, wrong operator
     precedence, mis-ordered arguments, wrong CURIE / predicate
     applied to the wrong biolink category.
   - Data-flow bugs where a transformed value never reaches its writer
     or a computed CURIE is silently dropped.
   - Category / predicate assignments that violate Biolink's
     subject/object constraints for the given predicate (see
     `transform_utils/constants.py` and `metpo_predicates.py`).

2. **Consistency**
   - Two transforms doing the same thing differently (e.g. CURIE
     construction, node-header ordering, provenance recording) when
     they should be sharing a helper.
   - Inline CURIE literals in code that duplicate rows already in
     `mappings/` — "data masquerading as code".
   - Diverging naming for the same concept
     (`ncbitaxon_id` vs `ncbi_taxid` vs `taxon`).
   - Ad-hoc error handling styles (bare `except`, `print` vs
     `logging`, `sys.exit` mid-function).

3. **Robustness**
   - Malformed input (partial JSON, empty TSV, missing column,
     truncated download) that the transform assumes is well-formed.
   - IO paths that don't check `.exists()` / permissions, or that
     open files without context managers.
   - Retry / backoff missing where an external API is called
     (BacDive API, UniProt API, OLS).
   - Non-idempotent transforms — running twice produces different
     output than running once.
   - Silent `except Exception: pass` blocks; dict `.get(k)` without
     validating the return; `int(str_value)` without try/except when
     the source column is user-provided.

4. **Bugs**
   - Findings that are provably wrong on real inputs, not stylistic.
     Each bug finding MUST include:
     - Exact file:line
     - The bug in ≤ 2 sentences
     - A minimal reproducing scenario (input shape or CLI command)
     - The expected vs actual behavior
   - Prefer high-confidence, small-surface bugs over "this looks
     suspicious" gestures. If you cannot show it's reachable, put it
     under Robustness instead.

5. **Bottlenecks**
   - Nested loops or per-row `pd.DataFrame.apply` on a hot path.
   - Repeated per-row lookups against a dataframe / dict that should
     have been indexed once at the top.
   - Redundant IO: reading the same JSON / TSV multiple times per
     transform run when once would suffice.
   - Synchronous chains of remote API calls when batching or async
     would drop wall-clock by >2×.
   - Missing streaming when a full file load is not required (large
     JSONL / TSV read into memory then iterated once).

6. **Scalability**
   - Data structures that grow O(N) with input where a streaming
     accumulator would be O(1). Explicitly flag anything that would
     break past ~5 M rows.
   - Multiprocessing correctness: shared-state hazards, pickling of
     un-picklable objects, forked workers duplicating a 10 GB parent,
     unbounded worker counts.
   - Assumptions that a file fits in RAM (e.g. `pd.read_csv` without
     `chunksize`).
   - Global mutable state that would race under multiprocessing.

## Output format — required

For every finding, emit a Markdown-formatted block:

```
### {severity} · {dimension} · {short-title}

- **File:** `<path>:<line>` (single canonical location; add others in body if needed)
- **Category:** one of {logic | consistency | robustness | bug | bottleneck | scalability}
- **Severity:** one of {CRITICAL | HIGH | MEDIUM | LOW}
- **Confidence:** {HIGH | MEDIUM | LOW}
- **Impact:** one sentence — who / what is affected on a real run.
- **Fix sketch:** one or two sentences. If the fix would be > 20 lines,
  say `fix requires refactor; see notes`.
- **Notes:** free text; include the minimal repro for bugs and the
  cross-file references for consistency.
```

At the very end, produce a single **summary table** grouped by
`(dimension, severity)` with counts, plus a **top 5 to fix first**
ranked by `severity × confidence × repo-blast-radius`.

## Explicit non-goals

Do NOT:
- Propose renames, formatter fixes, or docstring additions unless they
  block correctness.
- Rewrite files. Only fix sketches, never diffs.
- Comment on ontology curation choices (which CHEBI IDs are "right"),
  only on how the code handles them.
- Flag deprecation warnings from dependencies that KG-Microbe cannot
  fix on its side.
- Duplicate a finding across dimensions — pick the one that best fits
  the failure mode.

## Ground rules

- All file paths are repo-relative.
- Prefer high-confidence findings; when a finding is speculative,
  mark it `Confidence: LOW` and say what you would need to see to
  raise the confidence.
- If you spot a systemic issue that recurs across many files, describe
  it once with a representative site and a full grep-friendly pattern,
  rather than listing every occurrence.
- Run today (date: {{today}}). Note any finding where behavior depends
  on a specific data snapshot or model release that may have changed
  since this scan.
```

## Notes on companion skills

- To hand this prompt to Codex, use the `codex:rescue` subagent:
  `Agent(subagent_type="codex:codex-rescue", prompt="<emitted prompt>")`.
- After receiving Codex's findings, the `kg-model-review` skill can be
  used to cross-check any category / predicate claims against the
  Biolink + METPO models; do not rely on Codex alone for those.
- If the scope is a single transform, follow up with
  `kg-path-review` on that transform's `nodes.tsv` / `edges.tsv` to
  confirm any suspected modeling bugs actually surface in output.
