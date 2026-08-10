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
2. **BTO is not an independent replication of ENVO.** Both project the *same* BacDive isolation source. With tie-safe strata it is 6 of 8 terms (n=843 in-stratum), an unclustered one-sided sign test around p≈0.1 — a sensitivity check, not confirmation. **Now partly addressed** by an independent standard — see [Independent replication](#independent-replication) — which reproduces the direction and the threshold peak at reduced strength.
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

#### What that does to the merge budget

KGX holds every source graph in the parent simultaneously, so the number that
matters for #693 is total merge input, not PREGO alone. Measured across the 20
`merge.yaml` sources present on disk:

| | total input | prego | prego share |
|---|---:|---:|---:|
| today | **9.72 GiB** | 7.40 GiB | **76.2%** |
| after the #703 columns | **13.26 GiB** | 10.94 GiB | **82.5%** |
| `merge.noprego.yaml` | **2.32 GiB** | — | — |

Three things follow, and they are the actual budgeting answer:

1. **Merge input grows 36.4% overall** (9.72 → 13.26 GiB) from a change that
   touches one source. PREGO's own +48% dilutes to +36% at the merge level only
   because the other 19 sources together are 2.32 GiB.
2. **PREGO's share of bytes goes 76.2% → 82.5%**, so it dominates input size
   more than before. But see the caveat below before treating that as a
   memory ranking — it is not one.
3. **`merge.noprego.yaml` is a 4.2x reduction today and 5.7x after #703.**
   Nothing else available comes close: even deleting every non-PREGO source
   would save less than PREGO's growth alone.

#### Bytes and objects rank differently — do not read the table as memory

Peak RSS is not measured here. This is input bytes, and KGX's in-memory
representation is several times larger and not a fixed multiple. **No merge
benchmark has been run at the new size.**

More than a magnitude gap, though: KGX peak RSS is dominated by per-object
Python overhead, which scales with the **number** of nodes and edges, not their
width. On that axis the picture shifts:

| source | rows | share of rows | share of bytes |
|---|---:|---:|---:|
| prego | 44,768,164 | **68.6%** | **76.2%** |
| metatraits | 4,651,069 | 7.1% | |
| bacdive | 4,516,195 | 6.9% | |
| metatraits_gtdb | 4,239,260 | 6.5% | |
| gtdb | 2,619,745 | 4.0% | |
| ncbitaxon | 1,850,570 | 2.8% | |
| **total** | **65,258,838** | | |

Two things follow that the bytes table hides:

- **Non-PREGO is ~31% of objects (20.5M), not ~24%**, and it is concentrated in
  four sources. Halving metatraits + metatraits_gtdb + bacdive would be a real
  memory win, not a rounding error.
- **The #703 columns add zero rows.** They widen existing rows by ~85 B. So in
  object terms PREGO stays at 68.6% before and after, and if RSS is
  object-dominated the merge's peak grows by considerably less than the 36.4%
  the byte table implies.

An earlier version of this section concluded "any future work on merge memory
that is not about PREGO is rounding error." That was a memory ranking argued
from a byte measurement, and the row counts do not support it.

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

### Habitat terms do **not** repeat the GO pattern

Measured 2026-08-10 on the current `edges.tsv` (12.17 GB, post-#722) with
`ubiquity_check.py --shape envo|bto`. Degree here is **distinct taxa**, not edge
count: MG-RAST contributes both amplicon and metagenome studies, so one
(term, taxon) pair can be reported twice (ENVO 1.063 edges per distinct taxon;
BTO exactly 1.000). The published GO run used edge count, which was sound for
that shape but would have overstated habitat degree by ~6%.

| decile | ENVO degree range | ENVO mean score | BTO degree range | BTO mean score |
|---:|---|---:|---|---:|
| 1 | 56–106 | 1.050 | 50–68 | 0.559 |
| 2 | 120–275 | 1.017 | 70–110 | 0.747 |
| 3 | 292–510 | 1.093 | 117–142 | 0.511 |
| 4 | 561–868 | **0.675** | 147–179 | 0.561 |
| 5 | 890–1,289 | **0.633** | 204–345 | 0.775 |
| 6 | 1,291–1,693 | 0.727 | 383–401 | 1.277 |
| 7 | 1,694–2,129 | 1.010 | 417–506 | 1.202 |
| 8 | 2,159–2,518 | 1.060 | 528–606 | 1.349 |
| 9 | 2,563–3,086 | 1.330 | 676–856 | 1.664 |
| 10 | 3,187–8,582 | 1.586 | 891–1,657 | 1.550 |

**Spearman: ENVO +0.3016 (223 terms), BTO +0.5967 (70 terms).**

Read the shape, not the coefficient — the same instruction as for GO, with the
opposite conclusion. **ENVO is U-shaped, not monotone.** The rarest three
deciles score ~1.0–1.09, *above* the mid-ubiquity deciles 4–6 (0.63–0.73), and
only the top two deciles rise clearly (1.33, 1.59). So for ENVO the score does
**not** systematically punish rare, specific habitats — the pathology that makes
`τ` dangerous for GO does not transfer. The positive Spearman is carried by the
rising top tail, not by a rare-terms-score-low gradient.

**BTO is closer to monotone** (+0.5967, rising 0.56 → 1.66) and does look like a
ubiquity ranking. It is also only 70 terms and, per the caveats, not independent
of ENVO.

### The genome channel is not flat for habitat edges

`CLAUDE.md` records that the `annotated_genomes_isolates` channel is
"predominantly a flat 4.0" with "roughly 0.1% of rows" carrying a 3, worth "on
the order of 20k edges" above `τ = 3`. That is true of the channel *overall*,
which is dominated by the 44.3M `capable_of` edges. It is badly wrong for the
habitat subset:

| shape | channel | score 3 | score 4 | share at 3 |
|---|---|---:|---:|---:|
| ENVO | `annotated_genomes_isolates` | 12,562 | 25,187 | **33.3%** |
| BTO | `annotated_genomes_isolates` | 5,360 | 1,301 | **80.5%** |

Genome-channel habitat scores are *exactly* 3 or 4 — no other value occurs.
Those 17,922 rows at 3 are ~89% of the ~20k the docs attribute to the whole
channel, so the "small incidental data-quality signal" is in fact almost
entirely habitat. **Any `τ > 3` deletes 4.0% of all habitat edges outright**, on
provenance rather than on quality.

Note also that the BTO *continuous* channel is not continuous above 2.0: 23,565
edges score < 2.0 and 5,596 score exactly 4.0, with **nothing in between**. Every
threshold from 2.0 to 4.0 is therefore the same filter.

---

<a name="independent-replication"></a>
## Independent replication on a non-BacDive habitat standard

Measured 2026-08-10, `fold_enrichment_envo.py --gold madin`.

Every habitat number above rests on **one** gold standard used twice — the
confound named above. Madin et al.'s condensed traits carry 14,888
`ENVO -location_of-> NCBITaxon` pairs already at taxon level, and are effectively
BacDive-free: of the 172,324 raw rows with an `isolation_source`, BacDive
contributes **1,336 (0.78%)**, the bulk coming from GOLD (52%), PATRIC (10%),
engqvist (7%) and GenBank (7%).

**One trap had to be closed first.** PREGO's genome-channel habitat edges are
*all* `JGI IMG`, and GOLD is also JGI. Scored against each other that is
circular, and those 37,749 edges are 53% of everything retained at `τ ≥ 3`.
Measured all-channel, Madin appears to show 3.85x rising to 11.29x — but the
clean test restricted to the MG-RAST/MGnify continuous channel, which shares no
provenance with GOLD, is materially weaker:

| | BacDive (all channels) | Madin (continuous only) |
|---|---:|---:|
| comparable edges | 11,008 | 27,803 |
| baseline | 0.03411 | 0.03444 |
| fold at τ=0 | **7.89x** | **2.01x** |
| fold at τ=1.0 | 11.59x | 2.45x |
| fold at τ=3.0 | **18.79x** (peak) | **4.38x** (peak) |
| fold at τ=3.5 | 16.71x (falls) | 4.17x (falls) |
| within-term, tie-safe | 18/20 terms, **1.49x** | 15/22 terms, **1.32x** |
| one-sided sign test | p=0.0002 | p=0.0669 |

**What replicates.** The direction (higher score agrees more), the monotone rise
to `τ = 3.0`, and the fall above it. The peak at 3.0 was previously an in-sample
optimum with no held-out validation; it now lands in the same place on a standard
that does not share BacDive's provenance. That is the single most useful thing
this test buys.

**What weakens.** Absolute enrichment drops roughly fourfold (7.89x → 2.01x) and
the within-term ratio from 1.49x to 1.32x, with the sign test falling to
p=0.0669 — suggestive, not significant at the conventional bar. Some of the gap
is expected from coverage differences (Madin spans 43 ENVO terms and 13,209 taxa
against BacDive's 63 and 8,664), but the honest reading is that habitat
discrimination is **real and weaker than the BacDive-only numbers imply**.

The all-channel Madin figures are reported here only to document the circularity;
**do not quote 3.85x or 11.29x** as independent evidence.

---

## Threshold recommendation for habitat ingest

**Mind the denominator.** The threshold table above is **all-channel** ENVO
(416,229 edges); the coverage table below is **continuous-channel only**
(378,480). They reconcile exactly — at every τ the difference is the genome
contribution, 37,749 for τ ≤ 3 and 25,187 at τ = 4 — but the fold figures and
the retention figures are not quoted against the same base, so do not divide one
by the other. Policy-level retention is given after the table.

Coverage cost per threshold, continuous channel only
(`habitat_threshold_check.py`). Median term degree is the distinct-taxon degree
of the term each *surviving edge* belongs to, computed once on the unfiltered
set so the baseline does not move with the filter:

| ≥ τ | ENVO edges | kept | terms kept | taxa kept | median term degree |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 378,480 | 100% | 100% (275) | 100% (13,316) | 2,585 |
| 0.5 | 264,239 | 69.8% | 82.2% | 72.2% | 2,691 |
| **1.0** | **180,205** | **47.6%** | **70.9%** | **60.6%** | **2,958** |
| 1.5 | 116,124 | 30.7% | 61.8% | 51.1% | 3,187 |
| 2.0 | 72,172 | 19.1% | 55.3% | 44.6% | 3,582 |
| 2.5 | 44,078 | 11.6% | 49.5% | 41.1% | 4,198 |
| 3.0 | 32,809 | 8.7% | 47.3% | 37.3% | 4,140 |
| 4.0 | 27,192 | 7.2% | 47.3% | 31.1% | 3,325 |

**Recommendation: `τ = 1.0` on the continuous channel, genome channel kept
whole.** What that policy actually retains, counted over *all* habitat edges —
not just the continuous ones, since 125 of the 400 ENVO terms appear only in the
genome channel:

| shape | edges | terms | taxa |
|---|---|---|---|
| ENVO | 416,229 → 217,954 (52.4%) | 400 → 351 (**87.8%**) | 21,183 → 16,008 (**75.6%**) |
| BTO | 35,822 → 19,791 (55.2%) | 382 → 368 (**96.3%**) | 7,248 → 6,629 (**91.5%**) |

The 52.4% is exactly the threshold table's `τ = 1.0` row (217,954), because every
genome-channel habitat edge scores 3 or 4 and so survives `τ = 1.0` regardless.
**11.59x therefore applies precisely to this set** — the two tables agree once
the denominator is made explicit.

The reasoning, and its limits:

- It is the knee. Fold enrichment goes 7.89x → 11.59x (+47%) while retaining
  **87.8% of distinct ENVO habitat terms and 75.6% of taxa**. Every further step
  buys less: within the continuous channel, 1.0 → 2.0 costs 15.6 points of term
  coverage for +2.9x.
- Specificity damage is small here (median degree +14%, 2,585 → 2,958) and the
  U-shaped ubiquity curve says the rarest habitats are not the ones being cut.
  The damage peaks at τ = 2.5 (4,198, +62%) and then *eases*, so the mid-range
  thresholds are the worst of both worlds.
- `τ = 3.0` maximises measured overlap (18.79x) but keeps 8.7% of edges and 37%
  of taxa. Overlap is not precision — the standard is positive-only — so paying
  63% of taxa for it is not an obvious trade for a recall-oriented KG. Note the
  "selected in-sample, never validated" objection to 3.0 **no longer holds**: the
  independent Madin standard peaks at 3.0 too. What still argues against it is
  the coverage cost, which is a values judgement rather than a measurement.
- The genome channel must stay whole: at `τ > 3` it loses 17,922 habitat edges
  for provenance reasons that say nothing about quality.

**This is a judgement, not a measurement.** No precision/utility target exists
for habitat edges, and one would change the answer: a precision-first consumer
should prefer 3.0, and a pure-recall consumer 0.0. What the data settles is the
*shape* of the trade, not the point on it.

**For BTO, do not threshold** beyond 1.0. Its ubiquity correlation is twice
ENVO's (+0.5967), so a threshold does preferentially keep ubiquitous anatomy
terms, and its score gap makes every τ in [2.0, 4.0] identical anyway.

`PREGO_MIN_CONFIDENCE` **cannot express this policy** — it applies one star
threshold globally, so it cannot keep the genome channel whole while filtering
the continuous one, and at τ > 3 it would also delete the literature channel.
Ingest everything and filter downstream on `(prego_channel, prego_score)`:

```bash
awk -F'\t' 'NR==1 || ($2=="biolink:location_of" &&
  ($9!="environmental_samples" || $8>=1.0))' \
  data/transformed/prego/edges.tsv > habitat_tau1.tsv
```

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
