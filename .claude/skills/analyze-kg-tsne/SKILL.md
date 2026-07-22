---
name: analyze-kg-tsne
description: Produce interpretation and parameter-optimization reports for a KG-Microbe DeepWalk -> tSNE/UMAP edge/node visualization. Use when the user invokes /analyze-kg-tsne or asks to interpret/optimize a KG tSNE figure.
---

# Analyze KG tSNE Skill

Produce an interpretation report and parameter-optimization report for a
KG-Microbe tSNE edge/node visualization (DeepWalk embedding → tSNE/UMAP).

## Usage

When the user invokes `/analyze-kg-tsne`, run the analysis workflow.

Arguments (free text): one or more of
- path to the tSNE PNG/SVG image
- path to the merged KG directory (containing `merged-kg_edges.tsv`, `merged-kg_nodes.tsv`)
- path to the DeepWalk training script (e.g., `kg_microbe_DeepWalk_*.py`)
- path to the tSNE SLURM script (e.g., `src/tSNE_edges_only_*.sl`)

If any of these are missing, ask the user for them before proceeding.

## Instructions

1. **Gather evidence** (run in parallel when independent):
   - `Read` the tSNE image. Note the title, axis ranges, legend order, cluster count, and visually dominant regions.
   - `Read` the tSNE SLURM script. Record `--method`, `--sample-size`,
     `--edge-method`, `--perplexity`, `--n-iter`, `--learning-rate`,
     `--max-legend-types`, and the resource request (`--mem`, `--cpus`, `--time`).
   - `Read` the DeepWalk Python script. Record `embedding_size`, `walk_length`,
     `iterations`, `window_size`, `epochs`, `normalize_by_degree`,
     and the path to nodes/edges TSVs.
   - In the KG dir, run (via `Bash` with `cut | sort | uniq -c | sort -rn`):
     * edge counts per predicate (top 20)
     * node counts per `category` (top 15)
     * total edge and node counts (`wc -l`)
   - Cross-reference predicate CURIEs against `PREDICATE_LABELS` in
     `src/kg_microbe_pipeline_utils.py` (Grep for `PREDICATE_LABELS`).

2. **Synthesize interpretation** — write
   `<kg_dir>/tsne_interpretation_report.md` with sections:
   - Graph composition table (nodes by category, top predicates by edge count).
   - "What the tSNE is actually showing" — explain the edge-embedding operator
     (Hadamard / concatenate / average / l1 / l2) and what proximity means.
   - "Structures visible in the figure" — describe each visible cluster/lobe
     and hypothesize which predicate(s) drive it, cross-referencing predicate
     counts. Flag positive/negative METPO twin clusters if present.
   - "What the plot says about the KG itself" — 5-8 numbered observations
     about balance, curation artefacts, node-type dominance, hierarchy signal,
     chemistry vs phenotype weight.
   - "Limitations of this view" — predicate conflation by the chosen operator,
     direction loss (if symmetric), 2D compression, density vs cardinality.
   - "Quick verifications worth running next" — concrete follow-up plots.

3. **Synthesize optimization recommendations** — write
   `<kg_dir>/tsne_parameter_optimizations.md` with:
   - Section A: DeepWalk parameters. For each suggestion include
     current value, proposed value, expected improvement (⭐–⭐⭐⭐),
     runtime cost, and one-sentence rationale. Known high-value knobs:
     `window_size`, `iterations` (walks/node), `walk_length`, `embedding_size`,
     `epochs`, `normalize_by_degree`, Node2Vec `p`/`q` biases.
     End with a "recommended recipe" code block.
   - Section B: tSNE parameters. Known high-value knobs:
     `learning_rate` (use `N/12` auto rule for N>100K — frequently the single
     biggest win), `perplexity` (try multiscale 50+500 for large N),
     `n_iter` + early-exaggeration schedule, method swap to `cuml_tsne`/
     `tsnecuda` for GPU, `edge-method` (hadamard vs concatenate),
     `sample-size`, `max-legend-types`, plotting `alpha`/`point-size`,
     coord persistence for re-plotting.
   - Section C: priority ordering (do these N first).
   - Section D: evaluation protocol — explicit downstream metric
     (e.g., balanced accuracy on a held-out binary medium classifier at
     `src/kg_microbe_train_binary_medium__pipeline.py 514 --data EC_RHEA`)
     and a tSNE-quality score (k-NN predicate purity, 2D vs N-D).

4. **Report** — summarize for the user in ≤5 lines:
   - Path to each generated report
   - Top 3 priority changes (usually: learning-rate auto, walks-per-node bump, GPU method swap)
   - Any blockers noticed (e.g., script missing arg, path mismatch)

## Conventions and gotchas

- Always cross-reference the legend labels against `PREDICATE_LABELS` before
  naming predicates — METPO CURIEs are remapped to readable names.
- Hadamard is symmetric: do **not** claim direction is preserved.
- When citing cluster sizes, prefer "edges of predicate X (count N)" over
  "this cluster has N points" because α-overdraw distorts perceived counts.
- Do not claim a cluster "is" a predicate from colour alone — frame as
  "consistent with" unless a coord-level dump was inspected.
- Report DeepWalk defaults explicitly when the script relies on them
  (Grape `DeepWalkSkipGramEnsmallen` defaults: `walk_length=128`,
  `iterations=10`, `window_size=5`, `epochs=30`, `learning_rate=0.01`,
  `number_of_negative_samples=5`).
- For openTSNE/FIt-SNE, `learning_rate="auto"` resolves to `max(200, N/12)`.
- tSNE "sample + transform" mode smears rare predicates; point this out
  when interpreting small peripheral clusters.

## Output conventions

- Both reports go in the KG merge directory (same dir as the PNG and TSVs).
- Use absolute paths in report headers.
- Tables for composition, bulleted ⭐ priority scores for recommendations.
- Include one "recommended recipe" code block per script at the end of
  each section.
