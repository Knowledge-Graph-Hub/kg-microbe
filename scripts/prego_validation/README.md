# PREGO score validation scripts

Reproduce the measurements in [`docs/PREGO_SCORE_VALIDATION.md`](../../docs/PREGO_SCORE_VALIDATION.md).

These are **analysis scripts, not pipeline code** — they read transform output and
merged KGs, write nothing into `data/`, and are kept so the findings can be
re-derived when the PREGO archives are refreshed (`lab42open-team/prego_daemons`
recomputes them periodically) or when a better gold standard appears.

The reusable measurement API lives in
`kg_microbe/transform_utils/prego/quality.py` and is tested in
`tests/test_prego_quality.py`. These scripts predate parts of that module and
inline some of the same logic; prefer the module for new work.

| script | builds / measures | runtime | reads |
|---|---|---|---|
| `build_uniprot_gold.py` | taxon→GO gold from UniProt proteomes | ~25 min | `data/merged/20250222_function/` (28.6 GB) |
| `build_assay_gold.py` | taxon→GO gold **with negatives** from BacDive assays | seconds | `data/transformed/bacdive/` |
| `fold_enrichment_go.py` | fold enrichment vs the UniProt gold, tie-safe windows | ~8 min | `data/transformed/prego/` (7.4 GB) |
| `precision_assay_go.py` | precision + lift vs labelled assay evidence | ~8 min | as above |
| `fold_enrichment_envo.py` | fold enrichment of ENVO edges vs a habitat gold (`--gold bacdive\|madin`, `--channel any\|continuous\|genome`) | ~2 min | as above |
| `fold_enrichment_bto.py` | fold enrichment of BTO edges vs BacDive host anatomy | ~2 min | as above |
| `ubiquity_check.py` | Spearman corr. of term degree vs mean score, any shape (`--shape go\|envo\|bto`) | ~1 min | as above |
| `habitat_threshold_check.py` | edges / terms / taxa retained per threshold, and whether survivors are the ubiquitous habitats | ~40 s | as above |

Run order: build the gold standards first (they pickle to `/tmp`), then the
measurements.

## Two traps these scripts exist to document

**Tie splitting.** An earlier version sorted `(score, is_hit)` tuples and sliced
by index. Because the sort tiebreak decided which tied rows fell either side of a
window boundary, it pushed every non-hit below the 4.0 block and every hit above
it — fabricating a 0.44x window adjacent to a 1.95x one out of pure ordering.
Windows must break only where the score changes; `quality.enrichment_by_window`
does this correctly.

**Baseline choice.** Fold enrichment here uses a uniform subject × object null,
which controls for neither taxon annotation depth nor term ubiquity (#698). The
**within-term stratified ratios** are what address that confound — the raw fold
numbers do not. Where labelled negatives exist (the assay standard), prefer
precision, which needs no null at all.
