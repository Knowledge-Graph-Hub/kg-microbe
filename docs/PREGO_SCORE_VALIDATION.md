# PREGO score validation — findings

**Date:** 2026-08-06 · **Branch:** `feat/prego-confidence-calibration` · **PR:** #697
**Issues:** #693 (merge RAM), #694 (`prego_channel`), #695 (edge metadata), #696 (calibration design), #698 (statistical review), #702 (validation coverage)

Companion to [`PREGO_INGEST_PLAN.md`](PREGO_INGEST_PLAN.md), which covers acquisition and schema. This document covers **whether PREGO's `prego_score` means anything**, measured against four independent gold standards.

---

## Verdict

**The score discriminates on `location_of` edges and not on `capable_of` edges.**

| predicate | edge types | count | score works? | within-term ratio |
|---|---|---:|---|---|
| `biolink:location_of` | `ENVO→taxon`, `BTO→taxon` | 452,051 | **yes** | 1.57x (18/19 terms), 1.94x (7/9 terms) |
| `biolink:capable_of` | `taxon→GO` | 44,258,939 | **no** | 0.84x — wrong direction, or flat |
| `biolink:associated_with` | `taxon→MONDO` | 5,171 | untested | no in-graph reference exists |

**Mechanism.** PREGO's environmental-samples score counts taxon–sample co-occurrence. That is *direct* evidence for "this organism is found in location X" and only *indirect* evidence for "this organism can perform function Y". The split is what the score is measuring, not a defect.

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

Standard 3 is the only one with **labelled negatives**, so it supports direct precision measurement with no null model.

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

**7.89x overall.** Stratified within ENVO term: **18 of 19** terms with ≥100 comparable edges have the higher-score half agreeing more; pooled 0.211 → 0.331 (**1.57x**).

### `BTO -location_of-> NCBITaxon` — 35,822 edges (0.08%)

| window | score range | n | hit rate | fold |
|---|---|---:|---:|---:|
| 1 | 0.010–0.489 | 222 | 0.099 | 1.66x |
| 2 | 0.490–1.032 | 221 | 0.086 | 1.44x |
| 3 | 1.036–3.000 | 427 | 0.351 | **5.89x** |
| 4 | 4.000 (tied) | 232 | 0.272 | 4.55x |

**3.86x overall.** Stratified: **7 of 9** BTO terms (≥30 edges) agree; pooled **1.94x**.

### `NCBITaxon -associated_with-> MONDO` — 5,171 edges (0.01%)

Untested. PREGO is the only source of MONDO edges in the graph. Emitting BacDive pathogenicity as `taxon→MONDO` would unlock it and has independent value.

---

## Threshold selection for `location_of` edges

Measured on ENVO (the larger of the two):

Baseline 0.03411, over the entity space shared between PREGO and the gold standard (the TISSUES protocol).

| ≥ T | precision | fold | ENVO kept |
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

**Precision peaks at 3.0 and then falls.** Thresholds above 3.0 lose recall *and* precision, so they are strictly dominated — the upper bound is not a judgement call.

Below 3.0 the choice is precision vs recall. Two defensible settings: **3.0** (precision 0.64, keeps 17%) or **1.0** (precision 0.40, keeps 52%, still a 47% precision gain over unfiltered).

Note the floor: **unfiltered ENVO edges are already 7.9x enriched.** The threshold improves a signal that is present without it.

---

## Recommendations (Claude's, for review)

| edge type | count | recommendation | basis |
|---|---:|---|---|
| `ENVO -location_of->` | 416,229 | keep; threshold at 3.0 (or 1.0) | score validated, 18.8x at optimum |
| `BTO -location_of->` | 35,822 | keep; same threshold | same predicate, 1.94x within-term |
| `taxon -capable_of-> GO`, flat channels | ~20.9M | keep, **no** threshold | provenance: 1.39x disjoint, 2.19x UniProt |
| `taxon -capable_of-> GO`, continuous | ~23.3M | **drop** | 0.91x — below chance under the only test with negatives |
| `taxon -associated_with-> MONDO` | 5,171 | keep, flag unvalidated | no reference exists |

Supporting arguments:

1. **Filter GO edges by channel, not by score.** The evidence speaks to provenance, not to the score. A channel filter is expressible in `merge.yaml` via `edge_filters` today (exact-string matching), so it needs no numeric comparison.
2. **Per-predicate thresholds, not one global knob.** A single `min_confidence` is a validated quality filter on `location_of` and an arbitrary cut on `capable_of` simultaneously.
3. **Dropping the continuous GO block removes ~52% of PREGO** — the part with no supporting evidence under any standard — taking `edges.tsv` from 7.4 GB to roughly 3.5 GB and largely dissolving the 48 GB merge problem in #693 as a side effect, without inventing a confidence claim to justify it.

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
6. **Inconsistent fold baselines between two of my own ENVO runs.** The window table used the shared entity space (baseline 0.03411) while the threshold table used the full gold space (0.02421), so the latter's fold column was inflated — 11.11x rather than 7.89x at T=0. Caught by smoke-testing the extracted scripts against the published figures. Both now use the shared space; precision and the location of the optimum were unaffected, only the multipliers.

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
