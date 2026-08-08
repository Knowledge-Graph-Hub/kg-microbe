# PREGO score validation — findings

**Date:** 2026-08-06 · **Branch:** `feat/prego-confidence-calibration` · **PR:** #697
**Issues:** #693 (merge RAM), #694 (`prego_channel`), #695 (edge metadata), #696 (calibration design), #698 (statistical review), #702 (validation coverage)

Companion to [`PREGO_INGEST_PLAN.md`](PREGO_INGEST_PLAN.md), which covers acquisition and schema. This document covers **whether PREGO's `prego_score` means anything**, measured against four independent gold standards.

---

## Verdict

>  **Status: NOT ESTABLISHED.** Under matched taxa *and* matched label policy the
>  predicate contrast largely dissolves — interaction +0.281, clustered 95% CI
>  [−0.237, +0.624], 82.5% one-sided. Both predicates show weak positive
>  discrimination (1.40 vs 1.12) and the difference between them is not
>  distinguishable from zero. See
>  [Matched-taxa interaction test](#matched-taxa-interaction-test). The
>  per-benchmark contrast reported below was driven substantially by differences
>  in gold standard and label policy, not by the predicate.

**Original hypothesis (now unsupported): the score discriminates on `location_of` edges and not on `capable_of` edges.**

| predicate | edge types | count | score works? | within-term ratio (tie-safe) |
|---|---|---:|---|---|
| `biolink:location_of` | `ENVO→taxon`, `BTO→taxon` | 452,051 | apparently yes | 1.49x (18/20 terms), 1.69x (6/8 terms) |
| `biolink:capable_of` | `taxon→GO` | 44,258,939 | no | 0.84x — wrong direction, or flat |
| `biolink:associated_with` | `taxon→MONDO` | 5,171 | untested | no in-graph reference exists |

**Candidate mechanism (post-hoc, untested).** PREGO's environmental-samples score counts taxon–sample co-occurrence, which is *direct* evidence for "found in location X" and only *indirect* evidence for "can perform function Y". This fits the observations but no analysis tests it or excludes alternatives such as taxon ascertainment or benchmark coverage. It should not be stated as established.

<a name="matched-taxa-interaction-test"></a>
### Matched-taxa interaction test — the confound-removing analysis

External review named this the cheapest way to settle the verdict, so it was run
([`predicate_interaction.py`](../scripts/prego_validation/predicate_interaction.py)).
It removes the benchmark confound rather than adjusting for it: **only the 4,527 taxa
carrying BOTH a BacDive isolation record and a BacDive assay result**, with within-term
comparison, taxon-degree decile stratification, tie-safe boundaries, and a two-way
clustered bootstrap over taxa and terms.

| predicate | terms | in-stratum n | high/low ratio |
|---|---:|---:|---:|
| `location_of` | 66 | 9,682 | **1.502** |
| `capable_of` | 31 | 12,325 | **1.023** |

**Interaction (location − capable): +0.479, two-way clustered 95% CI [−0.015, +1.128].**
96.8% of resamples put `location_of` above `capable_of`.

That still left one confound: the **label policies differ.** Location gold is
positive-only — absence means unknown but is necessarily counted as a miss — while
function gold carries explicit negatives and excludes unlabelled pairs. Matching taxa
does not match that.

#### Matching the label policy too (`--positive-only`)

Recasting function labels as positive-only, so both predicates use identical semantics:

| predicate | terms | in-stratum n | high/low ratio |
|---|---:|---:|---:|
| `location_of` | 65 | 8,805 | **1.396** |
| `capable_of` | 31 | 28,892 | **1.115** |

**Interaction +0.281, two-way clustered 95% CI [−0.237, +0.624].** 82.5% of resamples
positive — down from 96.8%.

**Reading — this is the decisive run.** Once taxa *and* label policy are matched, the
contrast largely dissolves. The interaction nearly halves, the interval widens well
across zero, and one-sided support falls to ~0.18 (not significant). Note especially
that `capable_of` rises from 1.023 to **1.115** under matched semantics: the "no
discrimination at all for function" result was **partly an artifact of the label
policy**, not a property of the predicate.

What survives: **both** predicates show weak positive discrimination (1.40 and 1.12),
and the difference between them is not distinguishable from zero on matched data.

Verdict after this test: **not established.** The dramatic per-benchmark contrast
reported below was driven substantially by gold-standard and label-policy differences
rather than by the predicate.

<a name="confounds-that-limit-the-verdict"></a>
### Confounds that limit the verdict

1. **Predicate was inseparable from benchmark and label policy.** Addressed by the matched-taxa test above, which controls both. The contrast did not survive: interaction +0.281, CI [−0.237, +0.624].
2. **BTO is not an independent replication of ENVO.** Both project the *same* BacDive isolation source. With tie-safe strata it is 6 of 8 terms (n=843 in-stratum), an unclustered one-sided sign test around p≈0.1 — a sensitivity check, not confirmation.
3. **Within-term stratification controls term identity, not taxon degree.** In the BTO split the high-score half has mean BacDive gold degree 4.85 vs 3.56 and mean PREGO degree 23.10 vs 18.73; ENVO likewise 91.64 vs 70.67. Well-covered taxa remain an open path to apparent discrimination.
4. **No clustered uncertainty anywhere.** Edges reuse taxa, terms and resources; all intervals quoted are iid and therefore optimistic.

---

## Why this was needed

`prego_score` is not one scale. Per PREGO's authors (Zafeiropoulos et al. 2022, §2.3, verified against PMC8879827):

> "All associations extracted from these resources were assigned **arbitrarily a confidence level of four out of five**."

Appendix C.1: *"The Genome Annotation and Isolates channel has **fixed values of scores** depending on the resource."* BioProject/PMID rows get 3/5. **PREGO computes no cross-channel combined score** — the shared (0,5] range is a display convention.

Measured channel composition of emitted edges:

| channel | share | scores |
|---|---:|---|
| `<N of M samples>` (Environmental Samples) | 53.00% | continuous, mean 1.96 |
| Isolates | 28.66% | flat, all 4.0 |
| Genome annotation | 9.17% | flat, all 4.0 |
| Metagenome-Assembled Genome | 7.27% | flat, ~all 4.0 |
| Single Amplified Genome | 1.79% | flat |
| `PMID:*` | 0.05% | flat, all 3.0 |

Range is 0 to **4.00735** (mean 2.92) — the shipped data exceeds the paper's documented cap of 4.

---

## Gold standards built

All four are **in-graph**; none required external data.

| # | standard | how built | scale | provenance |
|---|---|---|---|---|
| 1 | metatraits + metatraits_gtdb + madin_etal | direct `NCBITaxon→GO` edges | 333,407 pairs, 78 GO terms | trait curation |
| 2 | UniProt proteomes | `protein -derives_from-> NCBITaxon` × `protein -participates_in\|located_in-> GO` from `data/merged/20250222_function/` | 14,411,869 pairs, 4,209 GO terms | genome annotation |
| 3 | **BacDive assays** | `strain -METPO:2000302\|2000303-> assay -has_output-> GO`, strain lifted to taxon | 36,844 pos / 67,571 neg, 36 GO terms | **wet-lab phenotype, with negatives** |
| 4 | BacDive isolation | `ENVO -location_of-> strain` and `UBERON\|CL -location_of-> strain` (BTO via `uberon_nodes.xref`) | 13,212 ENVO + 6,288 BTO pairs | isolation records |

Standard 3 is the only one with **labelled negatives**, so it supports precision measurement with no null model.

**But its negatives are strain-level and the claim is taxon-level.** "Taxon capable_of GO" is existential — some strain having the capability makes it true — so strains testing negative do not refute it. Excluding the 12,916 mixed pairs does not repair that mismatch. The 0.3215 figure is agreement with strain-lifted labels, not a taxon-level false-positive rate.

---

## Results

### `NCBITaxon -capable_of-> GO` — 44,258,939 edges (98.98%)

| gold standard | coverage | continuous | flat | trend with score |
|---|---|---|---|---|
| metatraits | 78 GO, 1.0% | 1.45x | 1.00x | **falls** 1.61→1.59→1.56; 30 of 47 terms wrong way |
| UniProt | 4,209 GO, **41.5%** | 1.07x | 2.19x | rises weakly 0.94→0.96→1.04→1.19 |
| BacDive assays | 36 GO, 0.1% | precision **0.3215**, lift **0.91** | **0.4897**, lift **1.39** | **flat** 0.303/0.318/0.307/0.350/0.331 |

Assay base rate: **0.3529** (measured).

Two readings:

- **The score does not work here.** No standard produces a usable monotone trend, and the assay test — the only one needing no null model — shows none.
- **The flat/genome channels are enriched** under both non-trait standards (2.19x, 1.39x), including the provenance-disjoint one. Their reliability comes from **provenance, not score** (they carry a constant).

The three standards disagree on the *continuous channel* (1.45x / 1.07x / 0.91x) in a pattern matching each standard's provenance. That disagreement is itself a finding: **no single gold standard is neutral here.**

### `ENVO -location_of-> NCBITaxon` — 416,229 edges (0.93%)

| window | score range | n | hit rate | fold |
|---|---|---:|---:|---:|
| 1 | 0.001–0.327 | 2,204 | 0.122 | 3.58x |
| 2 | 0.327–0.862 | 2,202 | 0.103 | 3.01x |
| 3 | 0.862–2.102 | 2,203 | 0.111 | 3.26x |
| 4 | 2.103–3.951 | 2,202 | 0.429 | **12.58x** |
| 5 | 3.951–4.007 | 2,197 | 0.581 | **17.03x** |

**7.89x overall.** Stratified within ENVO term (tie-safe boundaries): **18 of 20** terms with ≥100 comparable edges have the higher-score half agreeing more; pooled 0.219 → 0.325 (**1.49x**).

### `BTO -location_of-> NCBITaxon` — 35,822 edges (0.08%)

| window | score range | n | hit rate | fold |
|---|---|---:|---:|---:|
| 1 | 0.010–0.489 | 222 | 0.099 | 1.66x |
| 2 | 0.490–1.032 | 221 | 0.086 | 1.44x |
| 3 | 1.036–3.000 | 427 | 0.351 | **5.89x** |
| 4 | 4.000 (tied) | 232 | 0.272 | 4.55x |

**3.86x overall.** Stratified (tie-safe): **6 of 8** BTO terms (≥30 edges) agree; pooled 0.158 → 0.266 (**1.69x**). The index-median split originally published gave 7 of 9 and 1.94x — the result is tie-sensitive.

### `NCBITaxon -associated_with-> MONDO` — 5,171 edges (0.01%)

Untested. PREGO is the only source of MONDO edges in the graph. Emitting BacDive pathogenicity as `taxon→MONDO` would unlock it and has independent value.

---

## Threshold selection for `location_of` edges

Measured on ENVO (the larger of the two).

**Terminology.** BacDive isolation is **positive-only**: an edge absent from it is *unknown*, not false. The column below is therefore an **overlap rate** among comparable edges, not precision. Only the assay standard supports true precision.

Baseline 0.03411, over the entity space shared between PREGO and the gold standard (the TISSUES protocol).

| ≥ T | overlap rate | fold | ENVO kept |
|---:|---:|---:|---:|
| 0.00 | 0.269 | 7.89x | 416,229 (100%) |
| 0.50 | 0.324 | 9.51x | 301,988 (72.6%) |
| 1.00 | 0.395 | 11.59x | 217,954 (52.4%) |
| 1.50 | 0.450 | 13.19x | 153,873 (37.0%) |
| 2.00 | 0.495 | 14.51x | 109,921 (26.4%) |
| 2.50 | 0.583 | 17.10x | 81,827 (19.7%) |
| **3.00** | **0.641** | **18.79x** | **70,558 (17.0%)** |
| 3.50 | 0.570 | 16.71x | 54,615 (13.1%) |
| 4.00 | 0.585 | 17.14x | 52,379 (12.6%) |

**Overlap peaks at 3.0 and then falls** — on the same data used to select it, with no held-out validation. Calling 3.0 "strictly dominated above" is only true of observed overlap on this selection set.

The 83% figure is **retention** loss, not measured recall loss — a positive-only standard cannot enumerate all true edges. Choosing between 3.0 (keeps 17%) and 1.0 (keeps 52%) requires a stated precision/utility target that does not yet exist, and for a recall-oriented KG **unfiltered may well be preferable**. No threshold curve was computed for BTO, so transferring 3.0 to it is unsupported.

Note the floor: **unfiltered ENVO edges are already 7.9x enriched.** The threshold improves a signal that is present without it.

---

## Recommendations (Claude's, for review)

| edge type | count | recommendation | basis |
|---|---:|---|---|
| `ENVO -location_of->` | 416,229 | keep; threshold **only against a stated utility target** | overlap rises with score; 3.0 is the in-sample optimum, not a validated operating point |
| `BTO -location_of->` | 35,822 | keep; **no** threshold transfer | 1.69x tie-safe, 6/8 terms, same BacDive source as ENVO — not independent |
| `taxon -capable_of-> GO`, flat channels | ~20.9M | keep, **no** threshold | provenance: 1.39x disjoint, 2.19x UniProt |
| `taxon -capable_of-> GO`, continuous | 23,289,791 | **not yet — do not drop** | no reliable score ranking, but that is not evidence of no value; the standards reach 0.1–41.5% and PREGO-only content is unmeasurable by construction |
| `taxon -associated_with-> MONDO` | 5,171 | keep, flag unvalidated | no reference exists |

Supporting arguments:

1. **Filter GO edges by channel, not by score.** The evidence speaks to provenance, not to the score. A channel filter is expressible in `merge.yaml` via `edge_filters` today (exact-string matching), so it needs no numeric comparison.
2. **Per-predicate thresholds, not one global knob.** A single `min_confidence` is a validated quality filter on `location_of` and an arbitrary cut on `capable_of` simultaneously.
3. **Dropping the continuous GO block removes 23,289,791 rows — 52.08% of rows but only 33.33% of bytes**, since those rows are shorter. `edges.tsv` goes from 7.38 GiB to **4.92 GiB**, not the ~3.5 GB stated earlier. **No merge benchmark was run**, so the claim that this "largely dissolves" the 48 GB problem in #693 is unverified.

### Sizing: the provenance columns cost 48%

Measured 2026-08-07 over all 44,716,161 rows of the real
`data/transformed/prego/edges.tsv`, not estimated from a sample.

| | |
|---|---:|
| rows | 44,716,161 |
| `edges.tsv` before the #703 columns | **7.38 GiB** |
| bytes added | **3.54 GiB** (85.1 B/row) |
| projected `edges.tsv` | **10.93 GiB** (**+48.0%**) |

The added columns are `prego_source`, `prego_evidence_class`, `knowledge_level`
and `agent_type`, plus `prego_channel` changing from PREGO's verbatim column 6
to a channel name. The raw column-6 string is not double-counted — it *moves*
to `prego_evidence`, so it cancels.

This matters for #693: KGX holds every source graph in the parent
simultaneously, and PREGO is the single largest edge block in the merged KG. A
48% increase on that block is material to the merge's peak RSS, and it lands on
the same axis the two levers below are trying to reduce.

The columns are still worth having — `knowledge_level` and `agent_type` were
shipping empty, which made 44.7M text-mined and statistically-derived
associations indistinguishable from curated assertions. But the cost should be
budgeted rather than discovered mid-merge.

### How `PREGO_MIN_CONFIDENCE` relates to `merge.noprego.yaml`

`PREGO_MIN_CONFIDENCE` (#697) ships a single global threshold — precisely the
knob recommendation 2 above argues against. That tension is real and is not
resolved by this document, so it is worth stating plainly what the knob is for.

**`merge.noprego.yaml` (#691) is the primary size lever.** It drops PREGO
entirely — ~76% of merge input, 44.7 M edges, 7.38 GiB — and requires no
calibration pass, no histogram, no per-resource cutoffs and no threshold
semantics. If the goal is to make the merge fit in RAM, that is the mechanism
to reach for, and nothing in this document weakens it.

**`PREGO_MIN_CONFIDENCE` is the finer-grained alternative to it**, for the case
where you want *some* PREGO rather than none. It is a size lever with a
principled ordering inside one channel, not a validated quality filter:

- On `ENVO -location_of->` it is closest to a quality filter — overlap with
  BacDive rises monotonically with score — but 3.0 is an in-sample optimum, not
  a validated operating point.
- On `taxon -capable_of-> GO` it is an arbitrary cut. No gold standard
  established a score ranking there.
- On the flat channels it is not a score filter at all, but provenance
  selection by another name: those rows carry an author-assigned constant, so
  the threshold either keeps the whole channel or deletes it.

The knob defaults to `0` (no-op), so neither mechanism is on unless chosen.
Documented with the full per-channel table in `CLAUDE.md`.

---

## Ubiquity: the score tracks how common a GO term is

Measured 2026-08-07 on the full `data/transformed/prego/edges.tsv` (7.93 GB,
pre-#703 layout) via `scripts/prego_validation/ubiquity_check.py`. 3,830 GO
terms with >=50 continuous-channel edges.

| ubiquity decile | degree range | terms | mean score |
|---:|---|---:|---:|
| 1 | 54–3,036 | 383 | 0.666 |
| 2 | 3,036–5,393 | 383 | 1.657 |
| 3 | 5,406–6,322 | 383 | 1.977 |
| 4 | 6,323–6,787 | 383 | 2.031 |
| 5 | 6,793–6,839 | 383 | 2.099 |
| 6 | 6,839–6,982 | 383 | 2.056 |
| 7 | 6,982–7,106 | 383 | 2.025 |
| 8 | 7,106–7,151 | 383 | 2.021 |
| 9 | 7,151–7,184 | 383 | 2.013 |
| 10 | 7,184–7,218 | 383 | 2.007 |

**Spearman rank correlation (GO degree vs mean score): +0.2592.**

Read the shape, not just the coefficient. The relationship is **not** a smooth
gradient: mean score climbs steeply from decile 1 to decile 3 (0.67 → 1.98) and
then plateaus flat at ~2.0 for deciles 4–10. So the score separates *rare* terms
from everything else, and carries almost no ordering among the common ones.

Consequence for thresholding: raising `τ` strips the low-degree tail first —
the rare, taxon-specific annotations — while barely discriminating within the
bulk. That is the opposite of what a confidence filter should do if the goal is
to keep specific, informative edges.

---

## Caveats

- **Coverage is thin everywhere except UniProt.** Comparable fractions: 41.5% (UniProt/GO), 2.64% (ENVO), 3.08% (BTO), 0.1% (assays/GO).
- **These tests can only reach where PREGO overlaps existing sources** — precisely where it is least additive. PREGO's stated value is ~2M taxa at species-and-above rank vs BacDive's ~250K strains. That unique contribution is **unmeasurable by construction**. "Unreliable" here means *no positive evidence*, not *shown wrong*.
- **The fold-enrichment baseline is a uniform subject×object null** (#698 finding 1). It controls for neither taxon annotation depth nor term ubiquity. The **within-term stratified ratios** are what address the degree confound; the raw fold numbers do not.
- **No clustered uncertainty** (#698 finding 3). Edges reuse taxa, terms and resources, so intervals are wider than iid. Quoted CIs are iid and therefore optimistic.
- **Strain-level negatives do not cleanly refute species-level claims.** 12,916 (taxon, GO) pairs had one strain positive and another negative; those are excluded, but the granularity mismatch inflates apparent error in the assay test.
- **Positive-only standards** (1, 2, 4) cannot measure false positives; only the assay standard can.
- **Time sensitivity.** PREGO archives are recomputed periodically by `lab42open-team/prego_daemons`; `data/merged/20250222_function/` is a February 2025 build.

---

## Claims corrected during this work

Recorded because each was stated confidently before being overturned:

1. **"The score is anti-correlated with quality."** Held only against the trait-derived standard (78 GO terms, 1% coverage). Against UniProt (41.5%) it rises. Withdrawn.
2. **"0.24% of PREGO's GO space."** Wrong — used PREGO's 32,440 distinct *objects*, which include ENVO and MONDO. The correct figure against 5,230 taxon→GO terms is 1.5%.
3. **"BTO is untestable."** Wrong — 1,645 anatomy terms in `uberon_nodes.tsv` already carry BTO xrefs, the same reverse-lookup the transform uses for DOID→MONDO. No new mapping was needed.
4. **A tie-splitting bug in the analysis** sorted `(score, is_hit)` tuples, so the sort tiebreak pushed non-hits below the 4.0 block and hits above it, fabricating a 0.44x window adjacent to a 1.95x one. Fixed in `enrichment_by_window`; two regression tests.
5. **"The calibration and emit passes can never disagree."** False — the emit pass applies further checks. The 1,200-row delta reported as reassuring was a symptom of this (#699).
6. **The within-term stratification split ties.** It used an index median, so sort order rather than the score decided which tied rows fell in which half — the same defect fixed in `enrichment_by_window` and then reintroduced in the very check meant to guard against confounding. Tie-safe boundaries move ENVO from 18/19 at 1.57x to 18/20 at 1.49x, and BTO from 7/9 at 1.94x to **6/8 at 1.69x**. Found by external review.
7. **"Precision" applied to positive-only standards.** ENVO/BTO agreement rates are *overlap* rates; absence from BacDive means unknown, not false. Renamed throughout.
8. **"BTO independently replicates ENVO."** Both project the same BacDive isolation source, so it is a sensitivity check rather than independent replication.
9. **Post-filter size "roughly 3.5 GB".** Wrong: the dropped rows are 52.08% of rows but 33.33% of bytes, leaving **4.92 GiB**. And no merge benchmark was run, so "largely dissolves the 48 GB problem" was unsupported.
10. **Verdict stated as established.** Downgraded to plausible-but-unproven: predicate is confounded with benchmark design.
11. **Inconsistent fold baselines between two of my own ENVO runs.** The window table used the shared entity space (baseline 0.03411) while the threshold table used the full gold space (0.02421), so the latter's fold column was inflated — 11.11x rather than 7.89x at T=0. Caught by smoke-testing the extracted scripts against the published figures. Both now use the shared space; precision and the location of the optimum were unaffected, only the multipliers.

---

## Reproducing

Analysis scripts: [`scripts/prego_validation/`](../scripts/prego_validation/).

```bash
# 1. gold standards
poetry run python scripts/prego_validation/build_uniprot_gold.py     # ~25 min, reads 28.6 GB
poetry run python scripts/prego_validation/build_assay_gold.py       # seconds

# 2. tests
poetry run python scripts/prego_validation/fold_enrichment_go.py     # vs UniProt
poetry run python scripts/prego_validation/precision_assay_go.py     # vs assays (labelled +/-)
poetry run python scripts/prego_validation/fold_enrichment_envo.py   # vs BacDive isolation
poetry run python scripts/prego_validation/fold_enrichment_bto.py    # vs BacDive host anatomy
```

Reusable API: `kg_microbe/transform_utils/prego/quality.py` — `GoldStandard`, `LabelledEvidence`, `enrichment_by_window`, `precision_by_window`, `lift`, `is_monotone_increasing`. Tests in `tests/test_prego_quality.py`.
