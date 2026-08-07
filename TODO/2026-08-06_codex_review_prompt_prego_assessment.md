# Codex review prompt — PREGO validation assessment + recommendations

Generated 2026-08-06. Hand the fenced block to
`Agent(subagent_type="codex:codex-rescue", prompt="<block>")` or `codex exec`.

Distinct from `2026-08-06_codex_review_prompt_pr697_prego_calibration.md`, which
reviewed the *code*. This one reviews the **empirical assessment and the
recommendations drawn from it** — whether the measurements support the
conclusions, and whether the proposed actions follow.

---

```
You are reviewing an empirical assessment and the recommendations drawn from it.
This is NOT primarily a code review — it is a review of measurement design,
inference, and whether proposed actions follow from evidence. Findings about
statistical validity and unsupported inference outrank findings about style.

## Repo context

KG-Microbe (Knowledge-Graph-Hub/kg-microbe) is a Python knowledge-graph
pipeline: Download -> Transform -> Merge, emitting Biolink-modeled nodes.tsv +
edges.tsv per source plus a merged KG.

PREGO (Zafeiropoulos et al. 2022, Microorganisms 10:293) is a text-mined +
database-derived taxon<->function/environment/disease resource. Its ingest emits
44,716,161 edges in a 7.38 GB edges.tsv — ~76% of all merge input by size, and
the reason a full merge exhausts a 64 GB machine.

## What to review

Primary: `docs/PREGO_SCORE_VALIDATION.md` — the consolidated findings and
recommendations.

Supporting:
- `scripts/prego_validation/` — the seven analysis scripts that produced every
  number in that document, plus a README.
- `kg_microbe/transform_utils/prego/quality.py` — the reusable measurement API
  (GoldStandard, LabelledEvidence, enrichment_by_window, precision_by_window,
  lift, is_monotone_increasing).
- `kg_microbe/transform_utils/prego/calibration.py` and `prego.py` — the
  threshold implementation the recommendations would configure.
- `tests/test_prego_quality.py`, `tests/test_prego_calibration.py`.
- `docs/PREGO_INGEST_PLAN.md` — the original ingest rationale, which states
  PREGO's value proposition.

You may run the fast scripts (`build_assay_gold.py`, `fold_enrichment_bto.py`,
each seconds to ~2 min) and the test suite. Do NOT run `build_uniprot_gold.py`
(~25 min, reads 28.6 GB) unless you need to check a specific claim. Do NOT edit,
stage, commit, or push. Do NOT run any transform or merge that writes into
`data/`.

## The claims under review

1. **Verdict:** the score discriminates on `biolink:location_of` edges
   (ENVO->taxon, BTO->taxon; 452,051 edges) and not on `biolink:capable_of`
   edges (taxon->GO; 44,258,939 edges).
2. **Mechanism:** the score counts taxon-sample co-occurrence, which is direct
   evidence for "found in location X" and only indirect for "can perform
   function Y".
3. **Threshold:** for location_of edges, precision peaks at score >= 3.0
   (0.641, 18.79x) and falls above it, so thresholds above 3.0 are strictly
   dominated.
4. **Recommendation:** keep and threshold the location_of edges; keep the
   flat/genome-derived GO channels unthresholded on provenance grounds; DROP
   the continuous GO channel (~23.3M edges, ~52% of PREGO); keep MONDO flagged
   unvalidated.
5. **Claimed side effect:** dropping the continuous GO block takes edges.tsv
   from 7.4 GB to ~3.5 GB and largely dissolves the 48 GB merge problem.

## Review dimensions — required, in priority order

### 1. Inferential validity (highest priority)

- Does each conclusion follow from the measurement that supposedly supports it?
  Flag any place a correlational result is stated causally, a single-benchmark
  result is generalized, or absence of evidence is reported as evidence of
  absence.
- **The verdict rests on a predicate-level split inferred from three edge types
  measured against different gold standards with wildly different coverage**
  (41.5% / 2.64% / 3.08% / 0.1%). Is "location_of works, capable_of does not"
  actually established, or is it confounded with which gold standard happened
  to be available for which edge type? What would distinguish those?
- Is the mechanism (claim 2) supported, or is it a post-hoc story that fits?
  What would falsify it?
- The document says three gold standards disagree on the continuous GO channel
  (1.45x / 1.07x / 0.91x) "in a pattern matching each standard's provenance".
  Is that pattern real, or is it small-n noise across differently-powered tests?

### 2. Measurement design

- **Baseline.** Fold enrichment uses a uniform subject x object null over the
  shared entity space. It controls for neither taxon annotation depth nor term
  ubiquity. The document claims the *within-term stratified ratios* address that
  confound. Do they? A median split within term controls for term identity but
  not for taxon degree — does that matter here, and in which direction?
- **Tie handling.** Windows break only where the score changes. Verify that
  holds in both `quality.enrichment_by_window` and every script. A prior version
  sorted `(score, is_hit)` tuples and manufactured a 0.44x window next to a
  1.95x one from sort order alone.
- **Uncertainty.** No clustered intervals anywhere. Edges reuse taxa, terms and
  resources. Which of the headline numbers would survive two-way clustered
  bootstrap by taxon and term? Specifically: is the ENVO within-term result
  (18 of 19 terms, pooled 1.57x) robust, and is the BTO one (7 of 9 terms,
  n=1,102, 9 terms clearing the bar) strong enough to claim replication?
- **Selection effects.** All gold standards can only reach where PREGO overlaps
  existing sources — precisely where PREGO is least additive. The document
  states this. Does it then draw conclusions that quietly depend on
  extrapolating to the unmeasured 99%?
- **Circularity.** UniProt is genome-derived and PREGO's flat channels are
  genome-derived. The document says the assay standard (wet-lab, disjoint)
  corroborates the flat-over-continuous ordering. Check that reasoning: are
  BacDive assays genuinely disjoint from PREGO's genome channels, given both
  ultimately concern cultured isolates?

### 3. The recommendations

- Does recommendation 4 follow from the evidence, or does it over-read it?
  Dropping 23.3M edges is irreversible in effect; is "no positive evidence
  under standards covering 0.1-41.5% of the edge type" sufficient grounds?
- Is the flat/continuous channel split the right instrument, given the flat
  channels' apparent reliability comes from a constant author-assigned score
  and not from any measurement of the edges themselves?
- Is claim 5 (the size arithmetic) correct? Verify against the actual channel
  composition rather than accepting the stated ~52%.
- Does the recommendation to threshold location_of edges at 3.0 account for the
  fact that this keeps only 17% of them, and that unfiltered they are already
  7.9x enriched? Is the marginal precision gain worth an 83% recall loss for KG
  construction, where recall is often the point?
- What is the strongest argument AGAINST each recommendation? State it even if
  you ultimately agree.

### 4. Reproducibility

- Do the scripts actually produce the documented numbers? Run the fast ones and
  compare. Report any discrepancy precisely.
- Are the scripts' inputs pinned or snapshot-dependent in ways the document does
  not disclose? PREGO archives are recomputed periodically by
  `lab42open-team/prego_daemons`; `data/merged/20250222_function/` is a February
  2025 build.
- Could someone re-derive the verdict from what is committed, or is essential
  state only in /tmp pickles?

### 5. Code correctness (lower priority, but do not skip)

Ordinary defects in `quality.py`, `calibration.py`, and the scripts: boundary
conditions, silent failure paths, float-equality keying of scores, memory
behaviour on realistic inputs.

## Output format

For every finding:

```
### {severity} · {dimension} · {short-title}

- **File / section:** `<path>` or the document heading
- **Category:** {inference | measurement | recommendation | reproducibility | code}
- **Severity:** {CRITICAL | HIGH | MEDIUM | LOW}
- **Confidence:** {HIGH | MEDIUM | LOW}
- **Claim affected:** which numbered claim above, if any
- **Why it does not hold / what is missing:** 2-4 sentences
- **What would settle it:** the specific test, statistic, or data
```

Then a summary table by (dimension, severity), and answer these five directly:

1. Is the headline verdict — location_of yes, capable_of no — **established**,
   **plausible but unproven**, or **not supported**? Justify in three sentences.
2. Which single number in the document is least trustworthy, and why?
3. Should the continuous GO channel be dropped on this evidence? Yes/no/not yet,
   with the condition that would change your answer.
4. Is 3.0 the right threshold for location_of edges, given the recall cost?
5. What is the cheapest measurement that would most reduce uncertainty about the
   verdict?

## Explicit non-goals

- Do not propose renames, formatting, or docstring additions unless they fix an
  overclaim.
- Do not rewrite files; sketches only.
- Do not re-derive the UniProt gold standard (25 min) unless a specific claim
  demands it.
- Do not comment on which GO or ENVO terms are biologically "right" — only on
  how the analysis handles them.
- Do not treat the author's own admissions of error (six are listed in the
  document) as findings; assess whether the *corrections* are complete.

## Ground rules

- Repo-relative paths. Run date 2026-08-06.
- Prefer high-confidence findings; mark speculative ones LOW and say what would
  raise them.
- If a systemic problem recurs, describe it once with a representative site.
- `poetry run tox` is green (900 passed). Say so if a finding would break it.
- The document explicitly invites challenge to its recommendations; being
  contrarian where justified is the point of this review.
```
