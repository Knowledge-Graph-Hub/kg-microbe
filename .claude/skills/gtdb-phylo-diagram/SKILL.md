---
name: gtdb-phylo-diagram
description: Render a GTDB phylogenetic diagram from a KG-Microbe merged release with each clade sized by the count of non-taxonomy edges (phenotypes, growth media, chemicals, etc.) incident on it. Folds NCBITaxon and kgmicrobe.strain edges onto their GTDB equivalent via in-graph close_match, GTDB metadata, and the published NCBI2GTDB tables. Persists the resolved mapping and a gap report. Use when you need to see *where in the GTDB tree the metadata is concentrated* — which clades are well-characterized vs sparse.
---

# GTDB phylogenetic diagram

## Purpose

The KG-Microbe merged KG carries organism-level facts on three taxon identifier systems: `NCBITaxon:*` (~890K nodes), `kgmicrobe.strain:*` (~250K), and `GTDB:*` (~180K). Phenotypes, growth media, chemicals consumed, and isolation sources attach to whichever identifier the source data used — usually NCBITaxon or strain, rarely the GTDB equivalent.

This skill produces a phylogenetic view rooted in the GTDB taxonomy where each node is sized by the count of non-taxonomy edges incident on it (after folding NCBITaxon and strain edges onto their GTDB equivalent). It also persists the resolved NCBITaxon/strain → GTDB mapping and a small report listing gaps so the user can track curation debt.

It is intentionally a *tree* view, not a network view — for network views use the `scripts/examples/visualization/` patterns.

## What "non-taxon edges" means

Every edge in the merged KG is classified by looking at its two endpoints and predicate:

- If **both** endpoints are taxon-prefixed (`NCBITaxon:`, `GTDB:`, `kgmicrobe.strain:`, `kgmicrobe.genus:`) the edge is *structural* — it carries the GTDB hierarchy, GTDB↔NCBITaxon `close_match` links, or strain→species `subclass_of` links. **Excluded** from node sizing.
- If the predicate is `biolink:subclass_of` (regardless of the other endpoint) the edge is *classification* — most importantly the ~732K `GenBank:<genome> --subclass_of--> GTDB:<species>` edges (one per GTDB genome). **Excluded** from node sizing, otherwise the circles would measure "how many genomes GTDB has for this clade" rather than metadata richness.
- Otherwise the edge contributes +1 to the count for whichever endpoint is a taxon. These are the biologically interesting edges: `has_phenotype`, `location_of` (isolation source), growth-media (`METPO:2000517`), and the METPO trait predicates.

Counts on NCBITaxon are folded onto their GTDB equivalent via the mapping built in step 1; strain counts are folded onto the NCBITaxon parent and then onto GTDB. Cumulative counts propagate up the tree.

## Mapping resolution

NCBITaxon → GTDB is resolved by unioning three sources in priority order:

1. **`merged-kg-close-match`** — `biolink:close_match` edges directly in the merged KG (provenance `infores:gtdb`). Highest confidence: this is exactly what the GTDB transform wrote.
2. **`gtdb-metadata`** — `bac120_metadata.tsv.gz` + `ar53_metadata.tsv.gz` map `ncbi_taxid → s__species_string`, joined to GTDB:N via the merged-KG node names. Same pattern as `kg_microbe/transform_utils/metatraits_gtdb/metatraits_gtdb.py::_load_gtdb_to_ncbi_mapping`.
3. **`gtdb-published-r220`** — `data/raw/NCBI2GTDB.tsv.gz`, kept where `majority_fraction >= --min-majority-fraction` (default 0.5). Joined to GTDB:N via the species string.

Strains use the in-graph `kgmicrobe.strain:* --biolink:subclass_of--> NCBITaxon:*` edge to find their parent, then map the parent through the table above. Source label is `strain-via-parent:<inner-source>`.

## Usage

```bash
# Default: scan data/merged/20260523_nometatraits, write to data/processed/gtdb_phylo_diagram_<release>/
poetry run python .claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py

# Pin a different release
poetry run python .claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py \
    --merged-dir data/merged/20260523 \
    --out-dir data/processed/gtdb_phylo_diagram_20260523

# Data only, no figures (fast iteration on the mapping logic)
poetry run python .claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py --skip-render

# Skip the toytree-based full-species and interactive renders
poetry run python .claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py --skip-full --skip-interactive

# Tighten the published-mapping confidence floor
poetry run python .claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py --min-majority-fraction 0.8
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--merged-dir PATH` | `data/merged/20260523_nometatraits` | Dir containing `merged-kg_nodes.tsv` + `merged-kg_edges.tsv` |
| `--gtdb-raw-dir PATH` | `data/raw/gtdb` | Dir containing `bac120_metadata.tsv.gz` + `ar53_metadata.tsv.gz` |
| `--gtdb-published-map PATH` | `data/raw/NCBI2GTDB.tsv.gz` | Published NCBI→GTDB mapping table |
| `--out-dir PATH` | `data/processed/gtdb_phylo_diagram_<release>` | Output directory |
| `--collapse-ranks STR` | `phylum,class,family` | Ranks to render rank-collapsed figures at |
| `--min-majority-fraction FLOAT` | `0.5` | Floor for accepting published mappings |
| `--skip-full` | false | Skip full-species toytree static figure |
| `--skip-interactive` | false | Skip interactive toytree HTML |
| `--skip-render` | false | Skip all rendering (TSV + Newick + iTOL only) |

## Output structure

```
data/processed/gtdb_phylo_diagram_<release>/
├── gtdb_tree.nwk                       # full species-level Newick
├── itol_node_sizes.txt                 # iTOL DATASET_SIMPLEBAR annotation
├── gtdb_tree_phylum.{png,svg}          # ~150 nodes, Bio.Phylo + matplotlib
├── gtdb_tree_class.{png,svg}           # ~500 nodes
├── gtdb_tree_family.{png,svg}          # ~5,000 nodes, large canvas
├── gtdb_tree_full.{png,svg}            # full species, toytree circular
├── gtdb_tree_interactive.html          # interactive toytree HTML
├── ncbi_strain_to_gtdb.tsv             # resolved mapping with provenance
├── per_node_edge_counts.tsv            # one row per GTDB clade
└── report.md                           # gaps, statistics, top clades
```

## When to invoke

- Diagnosing whether a curation push improved coverage of a target clade (re-run, diff `per_node_edge_counts.tsv`).
- Producing release-companion figures showing where the merged KG concentrates evidence.
- Surfacing NCBITaxon nodes that carry trait edges but don't map to any GTDB species (the "unmapped predicate fingerprint" in the report).
- Producing the Newick + iTOL annotations for an external viewer (iTOL, FigTree, dendroscope).

## Implementation notes

- **One streaming pass over the 800+ MB edges TSV.** No DataFrame load. Memory ceiling is ~1.3M ints for the per-taxon counter plus ~180K Clade objects.
- **The tree is taken from the merged KG itself**, not parsed from `bac120_taxonomy.tsv` — the merged KG already encodes the hierarchy via `GTDB:* --biolink:subclass_of--> GTDB:*` and that's what the GTDB integer IDs in the KG refer to.
- **Synthetic root.** GTDB has two domain roots (`GTDB:639 d__Archaea`, `GTDB:640 d__Bacteria`); the script wraps both under a synthetic `GTDB:root`.
- **`cumulative_count` is post-order sum** of `leaf_count` over the clade's subtree, so a phylum's count reflects all its descendants' folded edges, not the phylum node itself.
- **Toytree is optional.** If it isn't installed, the full-species static and the interactive HTML are skipped with a note in `report.md`. The Bio.Phylo rank-collapsed figures still render. To install: `poetry add toytree` (see also `pyproject.toml`).
- **Toytree circular layout gotchas (already handled in code):** the layout knob is `layout="c"`, *not* `tree_style="c"`; the circular layout additionally requires `edge_type="c"`; the tree must carry non-zero branch lengths (the skill sets unit lengths) or every node collapses onto one point; and CURIE colons must be stripped from labels (the skill sanitizes them) or toytree's Newick parser fails. The toyplot canvas background is set to white explicitly.
- **Rendering large family tree.** The family-rank figure has ~5K leaves and renders as a ~A0-sized canvas at 200 dpi. Expect a multi-MB PNG and a several-hundred-MB intermediate matplotlib figure during rendering.

## Upstream transform issue (flagged in every report)

The GTDB transform currently mints `GTDB:N` integer CURIEs via a monotonic counter in `kg_microbe/transform_utils/gtdb/gtdb.py::_get_or_create_taxon_id` (line ~269). These IDs are **not resolvable** against the public GTDB and **not stable across builds** (different dict-iteration order yields different `N`). The right fix is to mint `GTDB:<slugified-taxon-string>` (e.g. `GTDB:s__Escherichia_coli`) and drop the counter; this skill works around the issue by joining via the node `name` column (the canonical taxon string), so it will keep working unchanged after the transform is fixed.

## Known limitations

- The full-species figure compresses ~143K leaves into a single canvas; legible exploration belongs in iTOL (using `itol_node_sizes.txt`) or the interactive HTML.
- NCBITaxon nodes with no published or in-graph mapping to a GTDB species (common for higher-rank taxa and `environmental sample` entries) land in the unmapped bucket — see the "Unmapped NCBITaxon predicate fingerprint" section of `report.md` to see what we're losing.
- Strain mapping requires both the strain→NCBITaxon parent edge AND an NCBITaxon→GTDB mapping; missing either step drops the strain.

## See also

- `kg-release-diff` — semantic diff between two merged releases (complements this view)
- `kg-postprocess-report` — pipeline status; this skill is one of its consumers
- `scripts/examples/visualization/` — network-based subgraph visualisations (different shape of output)
- `kg_microbe/transform_utils/gtdb/gtdb.py` — defines how the synthetic `GTDB:N` integer IDs are minted
- `kg_microbe/transform_utils/metatraits_gtdb/metatraits_gtdb.py` — original GTDB↔NCBI mapping helper this skill reuses the pattern of
