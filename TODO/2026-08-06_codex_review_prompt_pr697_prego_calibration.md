# Codex review prompt — PREGO gold-standard analysis + threshold calibration (PR #697)

Generated 2026-08-06 via `/codex-review-kg-microbe`. Hand the fenced block below to
`Agent(subagent_type="codex:codex-rescue", prompt="<block>")` or paste into `codex exec`.

Extends the standard six-dimension template with a **seventh dimension (statistical
validity)**, because the substance of this branch is a measurement claim, not just
code — and the two defects already found in it were both methodological rather than
ordinary logic bugs.

---

```
You are an experienced code reviewer performing a focused review of the PREGO
confidence-calibration and gold-standard-analysis work in KG-Microbe
(Knowledge-Graph-Hub/kg-microbe), branch `feat/prego-confidence-calibration`
(PR #697, design issue #696).

## Repo context

KG-Microbe is a Python knowledge-graph construction pipeline with three stages —
**Download → Transform → Merge** — emitting Biolink-modeled `nodes.tsv` +
`edges.tsv` per source plus a merged KG.

- CLI: `poetry run kg download | transform | merge` (`kg_microbe/run.py`, Click).
- Transforms: `kg_microbe/transform_utils/<source>/<source>.py`, subclasses of
  `Transform` in `transform_utils/transform.py`, registered in `DATA_SOURCES`.
- Shared conventions: `transform_utils/constants.py` (column names, path
  constants), `transform_utils/custom_curies.yaml`.
- Merge uses the KGX library (`kg_microbe/merge_utils/merge_kg.py`).

## What this branch does

PREGO (Zafeiropoulos et al. 2022, Microorganisms 10:293) is a text-mined +
database-derived taxon↔function/environment/disease resource. Its KG-Microbe
ingest emits **44,716,161 edges in a 7.38 GB `edges.tsv`** — about 76% of all
merge input by size, and the reason a full merge exhausts a 64 GB machine.

The branch adds a tunable confidence threshold so the source can be reduced, plus
the machinery to test whether that threshold actually selects better edges.

Files changed (1,301 insertions):

- `kg_microbe/transform_utils/prego/calibration.py` (new, 327 lines) —
  per-resource percentile calibration. Continuous-channel rows are remapped
  `star = 4 * F_r(score)` where `F_r` is the empirical CDF within resource `r`;
  flat channels are rated by their own score. One knob, `tau in [0,4]`; keep
  iff `star >= tau`. Cutoffs come from fixed-width binned histograms
  (`BIN_WIDTH = 1e-4` over `[0, SCORE_MAX=4.01]`).
- `kg_microbe/transform_utils/prego/quality.py` (new, 235 lines) — fold-enrichment
  measurement against a gold standard: `fold = P(hit | window) / P(hit)`.
- `kg_microbe/transform_utils/prego/prego.py` (+183) — two-pass wiring
  (`_collect_calibration` then the emit pass), `PREGO_MIN_CONFIDENCE` env var,
  `prego_source` column now emitted (previously `del source`), payload memoization,
  calibration-table output.
- `kg_microbe/transform_utils/constants.py` (+5) — `PREGO_SOURCE_COLUMN`.
- Tests (+555 across three files).

## Domain facts established empirically — treat as given, do not re-derive

- `prego_score` runs **0 to 4.00735** (mean 2.92). The paper documents a cap of 4;
  the shipped data exceeds it.
- The score is **not one scale**. Per PREGO's authors (§2.3), the genome-derived
  channels were "assigned arbitrarily a confidence level of four out of five" and
  BioProject/PMID rows three of five. Only the Environmental Samples channel has a
  computed, varying score. PREGO computes **no cross-channel combined score**.
- Channel composition of emitted edges: continuous (`<N of M samples>`) **53.00%**;
  flat (Isolates 28.66%, Genome annotation 9.17%, MAG 7.27%, SAG 1.79%,
  PMID 0.05%) **47.00%**.
- The continuous channel aggregates three resources with materially different
  cutoffs at the same tau: MG-RAST metagenome **1.717**, MG-RAST amplicon **0.575**,
  MGnify **0.848**. MG-RAST metagenome is 99.62% of the channel.
- **MG-RAST amplicon holds 46.4% of its rows at the score cap**, so every tau above
  ~2.5 retains that same 46.4%.
- A real calibration pass sees 23,698,632 continuous rows vs 23,697,432 in the
  emitted `edges.tsv` (0.005% apart).
- Two gold standards were built and **they disagree on the direction of the
  score/quality relationship**:
  - UniProt (from `data/merged/20250222_function/`, joining
    `protein -derives_from-> NCBITaxon` with `protein -participates_in|located_in-> GO`):
    14,411,869 pairs, 4,209 GO terms, 41.5% of PREGO taxon→GO edges comparable.
    Fold **rises**: 0.94x, 0.96x, 1.04x, 1.19x. Flat channels 2.19x.
  - metatraits + metatraits_gtdb + madin_etal (trait-derived): 333,407 pairs,
    78 GO terms, 1.0% comparable. Fold **falls**: 1.61x, 1.59x, 1.56x.
    Flat channels 1.00x.
- A GO term's edge count correlates with its mean score at Spearman **+0.26**,
  driven by rare terms scoring low (0.67 mean in the lowest-ubiquity decile vs
  ~2.0 above).

## Review scope

Focus on: **kg_microbe/transform_utils/prego/ and tests/test_prego_*.py**

Read `calibration.py`, `quality.py`, and the changed regions of `prego.py` in full.
Ignore `data/`, `.tox/`, `.venv/`, `__pycache__/`, and generated TSVs.

## Review dimensions — required

Evaluate against **all seven**. Not every file will have findings in every
dimension; do not skip one.

1. **Code logic** — control flow, off-by-one, wrong operator precedence,
   mis-ordered arguments, values computed but never reaching a writer.
   Specifically: is `ScoreHistogram.cutoff()` solving `4*F(s) >= tau` correctly at
   the boundaries? Is `_bin_index` clamping correct for `score <= 0`, `score` at
   exactly `SCORE_MAX`, and `score > SCORE_MAX`? Does `star_for_row` return the
   right thing for each of {continuous with cutoff, continuous without cutoff,
   recognised flat, unrecognised}?

2. **Consistency** — does the calibration path duplicate logic that already exists
   elsewhere in the repo? Is `_KEEP_OUTCOMES` genuinely the same predicate the emit
   pass applies, or can the two diverge? Is `is_continuous_channel` (shape-matching
   on `"N of M samples"`) duplicated anywhere? Does the env-var convention match
   `METATRAITS_WORKERS` / `KG_MEDIADIVE_ALLOW_STALE_CACHE`?

3. **Robustness** — malformed rows, missing columns, absent archives, a resource
   present in pass 2 but absent from pass 1's cutoff table, empty histograms,
   `float()` on user-supplied text, non-idempotency, `atomic_write` usage for the
   calibration table.

4. **Bugs** — provable on real inputs. Each MUST include file:line, ≤2-sentence
   description, minimal repro, expected vs actual.

5. **Bottlenecks** — the two-pass design reads the archives twice. Is
   `_ensure_payload` memoization actually hit on both passes? Is `tarfile.getmembers()`
   on an 8.7 GB gzipped tar avoided where possible? Any per-row work that belongs
   outside the loop?

6. **Scalability** — the emit path streams 44.7M rows and the calibration pass
   another 44.7M. Flag anything O(N) in memory. `ScoreHistogram` uses a dict keyed
   by bin index — bound its worst case. Does anything accumulate per-row state that
   would break past 5M rows? Would this survive being run under the metatraits-style
   multiprocessing pool?

7. **Statistical validity** *(added for this branch — the substance here is a
   measurement claim, and both defects found so far were methodological)*
   - **Tie handling.** `enrichment_by_window` aggregates by exact score so window
     boundaries fall only where the score changes. Verify that is airtight,
     including float-equality keying of scores, and that no code path can
     reintroduce index-based slicing. Prior bug: an analysis sorted
     `(score, is_hit)` tuples, so the sort tiebreak pushed non-hits below the 4.0
     block and hits above it, fabricating a 0.44x window adjacent to a 1.95x one.
   - **Baseline definition.** `GoldStandard.baseline` uses
     `|gold ∩ shared| / (|shared subjects| × |shared objects|)`. Is that the right
     null? It assumes every subject×object cell is an equally likely draw, which
     ignores that taxa differ enormously in annotation depth. Would a
     degree-preserving null change the conclusions? State the direction of any bias.
   - **Circularity.** The UniProt gold standard is genome-derived and PREGO's flat
     channels are genome-derived (JGI IMG, Struo-GTDB). Is the 2.19x flat-channel
     enrichment measuring quality or shared provenance? Is there any independent
     gold standard in-repo that avoids this?
   - **Multiple comparisons / effect size.** Fold enrichment spans ~1.0–1.2x across
     the continuous channel. Given n≈8.6M, is that distinguishable from structured
     noise? Are confidence intervals warranted before any of this is cited?
   - **The percentile remap's meaning.** `star = 4*F_r(score)` equalises rank within
     a resource. Is calling the output "confidence" defensible given no quality
     anchor, and does the code or its docstrings overclaim anywhere?
   - **Ubiquity confound.** Spearman +0.26 between GO-term degree and mean score.
     Does that undermine the fold-enrichment result — i.e. could the enrichment
     trend be explained entirely by term frequency rather than by the score?
     Propose the specific stratified test that would settle it.

## Output format — required

For every finding:

```
### {severity} · {dimension} · {short-title}

- **File:** `<path>:<line>`
- **Category:** one of {logic | consistency | robustness | bug | bottleneck | scalability | statistical}
- **Severity:** one of {CRITICAL | HIGH | MEDIUM | LOW}
- **Confidence:** {HIGH | MEDIUM | LOW}
- **Impact:** one sentence — who / what is affected on a real run.
- **Fix sketch:** one or two sentences; if > 20 lines say `fix requires refactor; see notes`.
- **Notes:** free text; minimal repro for bugs, cross-file refs for consistency,
  and for statistical findings the specific test that would confirm or refute.
```

End with a **summary table** grouped by `(dimension, severity)` with counts, plus
**top 5 to fix first** ranked by `severity × confidence × blast-radius`.

Additionally, answer these three directly, as a short section before the table:

1. Is the threshold safe to ship as a **size** lever (its stated purpose in #693),
   independent of the unresolved quality question? Yes/no + why.
2. Is any claim in the module docstrings or test docstrings **not supported** by the
   evidence described above? Quote it.
3. What is the single highest-value experiment that would resolve the
   UniProt-vs-metatraits disagreement?

## Explicit non-goals

Do NOT:
- Propose renames, formatter fixes, or docstring additions unless they block
  correctness or fix an overclaim.
- Rewrite files. Fix sketches only, never diffs.
- Comment on ontology curation choices (which GO IDs are "right"), only on how the
  code handles them.
- Re-derive the empirical numbers above; they came from full passes over the real
  archives. Do challenge the **method** by which they were obtained.
- Flag dependency deprecation warnings KG-Microbe cannot fix.
- Duplicate a finding across dimensions — pick the best fit.

## Ground rules

- All file paths are repo-relative.
- Prefer high-confidence findings; mark speculative ones `Confidence: LOW` and say
  what you would need to raise it.
- For a systemic issue, describe it once with a representative site plus a
  grep-friendly pattern rather than listing every occurrence.
- Run today (date: 2026-08-06). Note any finding whose behavior depends on a data
  snapshot that may have changed — in particular the PREGO archives, which
  `lab42open-team/prego_daemons` recomputes periodically, and
  `data/merged/20250222_function/`, which is a February 2025 build.
- `poetry run tox` is currently green (888 passed). A finding that would break it
  should say so.
```
