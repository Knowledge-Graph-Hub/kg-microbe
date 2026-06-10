#!/usr/bin/env python3
"""Render a GTDB phylogenetic diagram with node sizes scaled by non-taxon edges.

Single streaming pass over the merged KG resolves three things at once:

1. The GTDB hierarchy (from `GTDB:* --biolink:subclass_of--> GTDB:*` edges).
2. The GTDB <-> NCBITaxon mapping (from `biolink:close_match` edges + GTDB
   metadata + the published GTDB2NCBI/NCBI2GTDB tables).
3. Per-taxon counts of "non-taxon" edges -- edges where the other endpoint is
   NOT a `NCBITaxon:`, `GTDB:`, `kgmicrobe.strain:`, or `kgmicrobe.genus:`
   prefix. These are the biologically interesting edges (phenotypes, media,
   chemicals, etc.).

Counts on NCBITaxon and strain nodes are folded onto their GTDB equivalent;
counts on internal GTDB clades are then propagated cumulatively up the tree.

Outputs:

- gtdb_tree.nwk                       (full species-level Newick)
- itol_node_sizes.txt                 (iTOL DATASET_SIMPLEBAR annotation)
- gtdb_tree_phylum.{png,svg}          (rank-collapsed, Bio.Phylo + matplotlib)
- gtdb_tree_class.{png,svg}           (rank-collapsed)
- gtdb_tree_family.{png,svg}          (rank-collapsed; large)
- gtdb_tree_full.{png,svg}            (full species, toytree if available)
- gtdb_tree_interactive.html          (interactive toytree HTML)
- ncbi_strain_to_gtdb.tsv             (the resolved mapping, with provenance)
- per_node_edge_counts.tsv            (every GTDB clade's leaf + cumulative count)
- report.md                           (gaps + statistics)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from Bio import Phylo
    from Bio.Phylo.BaseTree import Clade, Tree
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "biopython is required. Install with `poetry add biopython` "
        "(it's already a project dep, so `poetry install` should suffice)."
    ) from exc

TAXON_PREFIXES = ("NCBITaxon:", "GTDB:", "kgmicrobe.strain:", "kgmicrobe.genus:")
RANK_PREFIX_TO_NAME = {
    "d__": "domain",
    "p__": "phylum",
    "c__": "class",
    "o__": "order",
    "f__": "family",
    "g__": "genus",
    "s__": "species",
}
RANK_ORDER = ["domain", "phylum", "class", "order", "family", "genus", "species"]

csv.field_size_limit(sys.maxsize)


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


@dataclass
class Mapping:
    target_gtdb: str
    source: str
    confidence: float


@dataclass
class Stats:
    gtdb_nodes: int = 0
    ncbi_nodes_seen: int = 0
    strain_nodes_seen: int = 0
    edges_total: int = 0
    taxon_taxon_edges_skipped: int = 0
    classification_edges_skipped: int = 0
    non_taxon_edges_counted: int = 0
    gtdb_subclass_edges: int = 0
    close_match_edges: int = 0
    strain_parent_edges: int = 0
    ncbi_mapped: int = 0
    ncbi_unmapped: int = 0
    strain_mapped: int = 0
    strain_unmapped: int = 0
    mapping_source_counts: Counter = field(default_factory=Counter)
    unmapped_ncbi_sample_predicates: Counter = field(default_factory=Counter)


# ----------------------------------------------------------------------------
# Stage 1: read merged-kg nodes for GTDB metadata
# ----------------------------------------------------------------------------


def load_gtdb_nodes(nodes_tsv: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (gtdb_id_to_name, gtdb_name_to_id) for every GTDB:* node."""
    gtdb_id_to_name: dict[str, str] = {}
    gtdb_name_to_id: dict[str, str] = {}
    opener = gzip.open if nodes_tsv.suffix == ".gz" else open
    with opener(nodes_tsv, "rt", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            curie = row.get("id", "")
            if not curie.startswith("GTDB:"):
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue
            gtdb_id_to_name[curie] = name
            gtdb_name_to_id[name] = curie
    return gtdb_id_to_name, gtdb_name_to_id


def rank_of(name: str) -> str:
    return RANK_PREFIX_TO_NAME.get(name[:3], "unknown")


def normalize_taxon_name(name: str) -> str:
    """Match what `kg_microbe.transform_utils.gtdb.utils.clean_taxon_name` does.

    The merged KG stores taxon names with spaces replaced by underscores
    (e.g. `s__Escherichia_coli`). Both the GTDB metadata file and the published
    NCBI2GTDB table keep raw spaces. Normalize both to the merged-KG form so
    the join via `gtdb_name_to_id` actually matches.
    """
    return (name or "").strip().replace(" ", "_")


# ----------------------------------------------------------------------------
# Stage 2: single streaming pass over merged-kg edges
# ----------------------------------------------------------------------------


def stream_edges(
    edges_tsv: Path,
    gtdb_id_to_name: dict[str, str],
    stats: Stats,
) -> tuple[
    dict[str, str],         # gtdb_parent: child_gtdb -> parent_gtdb
    dict[str, str],         # ncbi_to_gtdb_closematch
    dict[str, str],         # strain_to_ncbi
    dict[str, int],         # taxon_edge_count (non-taxon edges per taxon CURIE)
    dict[str, Counter],     # per-NCBI unmapped predicate samples
]:
    gtdb_parent: dict[str, str] = {}
    ncbi_to_gtdb_closematch: dict[str, str] = {}
    strain_to_ncbi: dict[str, str] = {}
    taxon_edge_count: dict[str, int] = defaultdict(int)
    per_ncbi_predicates: dict[str, Counter] = defaultdict(Counter)

    opener = gzip.open if edges_tsv.suffix == ".gz" else open
    with opener(edges_tsv, "rt", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            stats.edges_total += 1
            subj = row.get("subject") or ""
            obj = row.get("object") or ""
            pred = row.get("predicate") or ""
            subj_is_taxon = subj.startswith(TAXON_PREFIXES)
            obj_is_taxon = obj.startswith(TAXON_PREFIXES)

            if subj_is_taxon and obj_is_taxon:
                # Both endpoints are taxa -> structural edge, skip from counts
                stats.taxon_taxon_edges_skipped += 1
                if pred == "biolink:subclass_of":
                    if subj.startswith("GTDB:") and obj.startswith("GTDB:") and subj in gtdb_id_to_name:
                        gtdb_parent[subj] = obj
                        stats.gtdb_subclass_edges += 1
                    elif subj.startswith("kgmicrobe.strain:") and obj.startswith("NCBITaxon:"):
                        strain_to_ncbi[subj] = obj
                        stats.strain_parent_edges += 1
                elif pred == "biolink:close_match":
                    if subj.startswith("GTDB:") and obj.startswith("NCBITaxon:"):
                        ncbi_to_gtdb_closematch[obj] = subj
                        stats.close_match_edges += 1
                    elif subj.startswith("NCBITaxon:") and obj.startswith("GTDB:"):
                        ncbi_to_gtdb_closematch[subj] = obj
                        stats.close_match_edges += 1
                continue

            # subclass_of with one taxon endpoint is a classification edge,
            # not metadata -- e.g. GenBank:<genome> --subclass_of--> GTDB:<species>
            # (~732K of these, one per GTDB genome). Excluding them keeps the
            # circle size meaning "biologically interesting edges" (phenotype,
            # isolation source, growth media, METPO traits) rather than
            # "how many genomes GTDB has for this clade".
            if pred == "biolink:subclass_of":
                stats.classification_edges_skipped += 1
                continue

            # At least one endpoint is non-taxon -> "non-taxon edge"
            if subj_is_taxon:
                taxon_edge_count[subj] += 1
                stats.non_taxon_edges_counted += 1
                if subj.startswith("NCBITaxon:"):
                    per_ncbi_predicates[subj][pred] += 1
            if obj_is_taxon:
                taxon_edge_count[obj] += 1
                stats.non_taxon_edges_counted += 1
                if obj.startswith("NCBITaxon:"):
                    per_ncbi_predicates[obj][pred] += 1

    return gtdb_parent, ncbi_to_gtdb_closematch, strain_to_ncbi, taxon_edge_count, per_ncbi_predicates


# ----------------------------------------------------------------------------
# Stage 3: NCBI -> GTDB mapping from multiple sources, in priority order
# ----------------------------------------------------------------------------


def load_gtdb_metadata_mapping(
    gtdb_raw_dir: Path,
    gtdb_name_to_id: dict[str, str],
) -> dict[str, Mapping]:
    """ncbi_taxid -> GTDB:N (species level) from bac120/ar53 metadata."""
    out: dict[str, Mapping] = {}
    for fname in ("bac120_metadata.tsv.gz", "ar53_metadata.tsv.gz"):
        path = gtdb_raw_dir / fname
        if not path.exists():
            continue
        with gzip.open(path, "rt", newline="") as fh:
            header = next(fh).rstrip("\n").split("\t")
            try:
                tax_idx = header.index("gtdb_taxonomy")
                tid_idx = header.index("ncbi_taxid")
            except ValueError:
                continue
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) <= max(tax_idx, tid_idx):
                    continue
                tid = parts[tid_idx]
                tax = parts[tax_idx]
                if not tid or tid in ("none", "NA", "") or not tax:
                    continue
                ranks = tax.split(";")
                if len(ranks) < 7:
                    continue
                species_str = normalize_taxon_name(ranks[6])
                if not species_str.startswith("s__"):
                    continue
                gtdb_id = gtdb_name_to_id.get(species_str)
                if not gtdb_id:
                    continue
                ncbi_curie = f"NCBITaxon:{tid}"
                if ncbi_curie not in out:
                    out[ncbi_curie] = Mapping(gtdb_id, "gtdb-metadata", 1.0)
    return out


def load_published_gtdb_ncbi(
    mapping_path: Path,
    gtdb_name_to_id: dict[str, str],
    min_majority_fraction: float,
) -> dict[str, Mapping]:
    """data/raw/NCBI2GTDB.tsv.gz -> NCBITaxon -> GTDB:N via species-string join."""
    out: dict[str, Mapping] = {}
    if not mapping_path.exists():
        return out
    with gzip.open(mapping_path, "rt", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            ncbi_tid = (row.get("taxonID NCBI") or "").strip()
            mf_raw = (row.get("majority fraction") or "").strip()
            try:
                mf = float(mf_raw) if mf_raw else 0.0
            except ValueError:
                mf = 0.0
            if mf < min_majority_fraction or not ncbi_tid:
                continue
            sp_gtdb = (row.get("species (GTDB)") or "").strip()
            if not sp_gtdb:
                continue
            gtdb_id = gtdb_name_to_id.get(normalize_taxon_name(f"s__{sp_gtdb}"))
            if not gtdb_id:
                continue
            ncbi_curie = f"NCBITaxon:{ncbi_tid}"
            if ncbi_curie not in out:
                out[ncbi_curie] = Mapping(gtdb_id, "gtdb-published-r220", mf)
    return out


def build_ncbi_to_gtdb(
    closematch: dict[str, str],
    metadata: dict[str, Mapping],
    published: dict[str, Mapping],
) -> dict[str, Mapping]:
    """Union with priority: closematch > metadata > published."""
    out: dict[str, Mapping] = {}
    for ncbi, gtdb in closematch.items():
        out[ncbi] = Mapping(gtdb, "merged-kg-close-match", 1.0)
    for ncbi, m in metadata.items():
        out.setdefault(ncbi, m)
    for ncbi, m in published.items():
        out.setdefault(ncbi, m)
    return out


# ----------------------------------------------------------------------------
# Stage 4: build Bio.Phylo tree from merged-KG GTDB hierarchy
# ----------------------------------------------------------------------------


def build_tree(
    gtdb_id_to_name: dict[str, str],
    gtdb_parent: dict[str, str],
) -> Tree:
    """Synthesize a rooted Tree from the parent map."""
    clades: dict[str, Clade] = {}
    for gid, name in gtdb_id_to_name.items():
        c = Clade(name=gid)
        c.gtdb_name = name
        c.rank = rank_of(name)
        c.leaf_count = 0
        c.cumulative_count = 0
        clades[gid] = c

    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in gtdb_parent.items():
        if parent in clades and child in clades:
            children[parent].append(child)

    # Roots = clades whose id is not a child of any other in our map.
    all_children = set(gtdb_parent.keys())
    root_ids = [gid for gid in clades if gid not in all_children or gtdb_parent.get(gid) not in clades]

    # Wire children into parents (one pass; tree is a DAG-free taxonomy).
    for parent_id, child_ids in children.items():
        clades[parent_id].clades = [clades[c] for c in child_ids]

    # Synthetic root over all rootless clades (typically d__Bacteria + d__Archaea).
    root = Clade(name="GTDB:root")
    root.gtdb_name = "root"
    root.rank = "root"
    root.leaf_count = 0
    root.cumulative_count = 0
    root.clades = [clades[r] for r in root_ids if r in clades]
    return Tree(root=root, rooted=True)


# ----------------------------------------------------------------------------
# Stage 5: fold counts + propagate up the tree
# ----------------------------------------------------------------------------


def fold_and_propagate(
    tree: Tree,
    taxon_edge_count: dict[str, int],
    ncbi_to_gtdb: dict[str, Mapping],
    strain_to_ncbi: dict[str, str],
    per_ncbi_predicates: dict[str, Counter],
    stats: Stats,
) -> tuple[dict[str, int], list[tuple[str, str, str]]]:
    """Returns (per_clade_leaf_count, mapping_rows_for_persistence)."""
    by_clade: dict[str, int] = defaultdict(int)
    mapping_rows: list[tuple[str, str, str, str]] = []  # (source_curie, gtdb, source, conf)

    # Direct GTDB counts.
    for curie, n in taxon_edge_count.items():
        if curie.startswith("GTDB:"):
            by_clade[curie] += n

    # NCBI counts folded.
    seen_ncbi: set[str] = set()
    for ncbi, n in taxon_edge_count.items():
        if not ncbi.startswith("NCBITaxon:"):
            continue
        seen_ncbi.add(ncbi)
        m = ncbi_to_gtdb.get(ncbi)
        if m is None:
            stats.ncbi_unmapped += 1
            for pred, cnt in per_ncbi_predicates[ncbi].most_common(5):
                stats.unmapped_ncbi_sample_predicates[pred] += cnt
            continue
        by_clade[m.target_gtdb] += n
        stats.ncbi_mapped += 1
        stats.mapping_source_counts[m.source] += 1
        mapping_rows.append((ncbi, m.target_gtdb, m.source, f"{m.confidence:.3f}"))

    # Also persist NCBI mappings that exist even if they have no edges (the
    # mapping is data the user wants to keep).
    for ncbi, m in ncbi_to_gtdb.items():
        if ncbi in seen_ncbi:
            continue
        mapping_rows.append((ncbi, m.target_gtdb, m.source, f"{m.confidence:.3f}"))

    # Strain counts folded via NCBI parent.
    for strain, n in taxon_edge_count.items():
        if not strain.startswith("kgmicrobe.strain:"):
            continue
        parent_ncbi = strain_to_ncbi.get(strain)
        if not parent_ncbi:
            stats.strain_unmapped += 1
            continue
        m = ncbi_to_gtdb.get(parent_ncbi)
        if m is None:
            stats.strain_unmapped += 1
            continue
        by_clade[m.target_gtdb] += n
        stats.strain_mapped += 1
        stats.mapping_source_counts[f"strain-via-parent:{m.source}"] += 1
        mapping_rows.append((strain, m.target_gtdb, f"strain-via-parent:{m.source}", f"{m.confidence:.3f}"))

    # Attach to clades.
    def attach(clade: Clade) -> int:
        leaf = by_clade.get(clade.name, 0)
        clade.leaf_count = leaf
        cum = leaf
        for child in clade.clades:
            cum += attach(child)
        clade.cumulative_count = cum
        return cum

    attach(tree.root)
    return by_clade, mapping_rows


# ----------------------------------------------------------------------------
# Stage 6: rendering
# ----------------------------------------------------------------------------


def collapse_at_rank(tree: Tree, target_rank: str) -> Tree:
    """Return a deep-copied tree pruned at the given rank.

    Clades at or shallower than `target_rank` are preserved; their subtrees are
    discarded but their `cumulative_count` already reflects the full subtree.
    """
    from copy import deepcopy

    new_tree = deepcopy(tree)
    target_depth = RANK_ORDER.index(target_rank) if target_rank in RANK_ORDER else None

    def truncate(clade: Clade) -> None:
        for child in list(clade.clades):
            if child.rank == target_rank:
                child.clades = []
            elif target_depth is not None and child.rank in RANK_ORDER:
                if RANK_ORDER.index(child.rank) >= target_depth:
                    child.clades = []
                else:
                    truncate(child)
            else:
                truncate(child)

    truncate(new_tree.root)
    return new_tree


def render_with_biopython(
    tree: Tree,
    out_png: Path,
    out_svg: Path,
    title: str,
    max_height_in: float = 200.0,
) -> None:
    """Draw a tree with Bio.Phylo and overlay scaled scatter markers at tips."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    leaves = tree.get_terminals()
    n = max(len(leaves), 1)
    fig_height = min(max(n * 0.08, 6), max_height_in)
    fig_width = 14
    fig = plt.figure(figsize=(fig_width, fig_height))
    ax = fig.add_subplot(1, 1, 1)

    def label(clade: Clade) -> str:
        nm = getattr(clade, "gtdb_name", clade.name or "")
        cnt = getattr(clade, "cumulative_count", 0)
        return f"{nm} ({cnt})" if cnt else nm

    Phylo.draw(tree, axes=ax, do_show=False, label_func=label)

    # Overlay sized markers using internal Bio.Phylo coordinate helpers.
    depths = tree.depths(unit_branch_lengths=True)
    y_positions = {leaf: i + 1 for i, leaf in enumerate(leaves)}
    xs, ys, sizes, colors = [], [], [], []
    domain_color = {"d__Bacteria": "#3a7bd5", "d__Archaea": "#d54e3a"}
    for leaf in leaves:
        cnt = getattr(leaf, "cumulative_count", 0)
        if cnt <= 0:
            continue
        xs.append(depths.get(leaf, 0))
        ys.append(y_positions[leaf])
        sizes.append(20 + 6 * math.sqrt(cnt))
        # Walk to domain ancestor to pick color.
        d_color = "#888888"
        # Find this leaf's domain ancestor name by tracing the tree.
        for clade in tree.find_clades():
            if leaf in clade.clades or leaf is clade:
                pass
        # Faster lookup using a recursive search of root children.
        for top in tree.root.clades:
            if leaf is top or any(leaf is t for t in top.get_terminals()):
                d_color = domain_color.get(getattr(top, "gtdb_name", ""), "#888888")
                break
        colors.append(d_color)

    if xs:
        ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.65, edgecolors="black", linewidths=0.3, zorder=5)

    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    fig.savefig(out_svg, bbox_inches="tight")
    plt.close(fig)


def _sanitize_label(name: str) -> str:
    """Make a clade name safe for toytree's Newick parser.

    toytree splits node strings on ':' expecting exactly name:distance, so a
    CURIE label like `GTDB:42559` (or `GTDB:s__Escherichia_coli`) breaks it.
    Reduce to `[A-Za-z0-9_.-]`, turning the colon and any other structural
    character into `_`. The integer/taxon-string suffix keeps the result
    unique, which is all we need since these labels are only used to join
    node sizes back (tip labels are hidden in the figure).
    """
    import re
    return re.sub(r"[^0-9A-Za-z_.-]", "_", name or "")


def render_with_toytree(tree: Tree, out_dir: Path, stem: str) -> Optional[str]:
    """Render full-species figure + interactive HTML via toytree, if available."""
    from copy import deepcopy

    try:
        import toytree
        import toyplot
        import toyplot.svg
        import toyplot.png
    except Exception as exc:
        return f"toytree not available ({exc}); skipping {stem} figures"

    # Sanitize labels on a copy so colons in CURIEs don't break the parser,
    # and key the size lookup on the same sanitized names.
    safe_tree = deepcopy(tree)
    name_to_count: dict[str, int] = {}
    for clade in safe_tree.find_clades():
        original = clade.name or ""
        clade.name = _sanitize_label(original)
        name_to_count[clade.name] = int(getattr(clade, "cumulative_count", 0) or 0)
        # Unit branch lengths: GTDB taxonomy has no distances, and toytree's
        # circular layout needs non-zero lengths to spread nodes radially by
        # depth. Without this, every node collapses onto one point and the
        # figure degenerates into concentric circles along a line.
        clade.branch_length = 1.0

    # Map each tip to its domain color (only tips are colored; internal hidden).
    DOMAIN_COLORS = {"d__Bacteria": "#3a7bd5", "d__Archaea": "#d54e3a"}
    tip_color: dict[str, str] = {}
    for top in safe_tree.root.clades:
        col = DOMAIN_COLORS.get(getattr(top, "gtdb_name", ""), "#888888")
        for term in top.get_terminals():
            tip_color[term.name] = col

    nwk_path = out_dir / "_tmp_toytree.nwk"
    Phylo.write(safe_tree, str(nwk_path), "newick")
    try:
        tt = toytree.tree(str(nwk_path))
    except Exception as exc:
        nwk_path.unlink(missing_ok=True)
        return f"toytree failed to parse Newick ({exc}); skipping {stem} figures"

    # toytree wants node_sizes/node_colors for ALL nodes (tips + internal) in
    # node-idx order. Tips are idx 0..ntips-1. Size tips by their folded edge
    # count, capped small (~10px) because 143K tips pack tightly around the
    # circle; leave internal nodes at size 0 (the root's huge cumulative count
    # would draw a giant central blob, and internal-rank sizing is already
    # covered by the matplotlib rank-collapsed figures).
    ntips = tt.ntips
    node_names = tt.get_node_data()["name"].tolist()
    sizes, colors = [], []
    for i, name in enumerate(node_names):
        if i < ntips:
            c = name_to_count.get(name, 0)
            sizes.append(min(2.0 + 1.0 * math.sqrt(c), 10.0) if c > 0 else 1.5)
            colors.append(tip_color.get(name, "#888888"))
        else:
            sizes.append(0)
            colors.append("#888888")

    # Circular fan: layout='c' + edge_type='c' (toytree requires the curved
    # edge type with the circular layout). tree_style is NOT the layout knob.
    try:
        canvas, axes, mark = tt.draw(
            layout="c",
            edge_type="c",
            tip_labels=False,        # 143K tips would overwhelm
            node_sizes=sizes,
            node_colors=colors,
            edge_widths=0.25,
            edge_colors="#555555",
            width=2400,
            height=2400,
        )
        canvas.style = {"background-color": "white"}
        toyplot.svg.render(canvas, str(out_dir / f"{stem}.svg"))
        toyplot.png.render(canvas, str(out_dir / f"{stem}.png"))
    except Exception as exc:
        nwk_path.unlink(missing_ok=True)
        return f"toytree static render failed ({exc})"

    # Interactive HTML.
    try:
        import toyplot.html
        canvas2, axes2, mark2 = tt.draw(
            layout="c",
            edge_type="c",
            tip_labels=False,
            node_sizes=sizes,
            node_colors=colors,
            edge_widths=0.25,
            edge_colors="#555555",
            width=1600,
            height=1600,
        )
        canvas2.style = {"background-color": "white"}
        toyplot.html.render(canvas2, str(out_dir / "gtdb_tree_interactive.html"))
    except Exception as exc:
        nwk_path.unlink(missing_ok=True)
        return f"toytree HTML render failed ({exc})"

    nwk_path.unlink(missing_ok=True)
    return None


# ----------------------------------------------------------------------------
# Stage 7: iTOL annotation
# ----------------------------------------------------------------------------


def write_itol_simplebar(tree: Tree, out_path: Path) -> None:
    header = (
        "DATASET_SIMPLEBAR\nSEPARATOR TAB\nDATASET_LABEL\tnon_taxon_edges_cumulative\n"
        "COLOR\t#3a7bd5\nDATA\n"
    )
    with out_path.open("w") as fh:
        fh.write(header)
        for leaf in tree.get_terminals():
            cnt = int(getattr(leaf, "cumulative_count", 0) or 0)
            if cnt > 0:
                fh.write(f"{leaf.name}\t{cnt}\n")


# ----------------------------------------------------------------------------
# Stage 8: report
# ----------------------------------------------------------------------------


def write_report(
    out_path: Path,
    stats: Stats,
    tree: Tree,
    gtdb_id_to_name: dict[str, str],
    merged_dir: Path,
    notes: list[str],
) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# GTDB phylogenetic diagram report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Merged KG: `{merged_dir}`")
    lines.append("")

    lines.append("## Edge accounting")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Total edges in merged KG | {stats.edges_total:,} |")
    lines.append(f"| Taxon-to-taxon edges (skipped) | {stats.taxon_taxon_edges_skipped:,} |")
    lines.append(f"| Classification subclass_of (skipped, e.g. genome->species) | {stats.classification_edges_skipped:,} |")
    lines.append(f"| Non-taxon edges counted (sizes the circles) | {stats.non_taxon_edges_counted:,} |")
    lines.append(f"| GTDB subclass_of (tree) | {stats.gtdb_subclass_edges:,} |")
    lines.append(f"| GTDB <-> NCBITaxon close_match | {stats.close_match_edges:,} |")
    lines.append(f"| Strain --> NCBITaxon parent | {stats.strain_parent_edges:,} |")
    lines.append("")

    lines.append("## Mapping resolution")
    lines.append("")
    lines.append("| Group | Mapped | Unmapped |")
    lines.append("|---|---|---|")
    lines.append(f"| NCBITaxon -> GTDB | {stats.ncbi_mapped:,} | {stats.ncbi_unmapped:,} |")
    lines.append(f"| kgmicrobe.strain -> GTDB | {stats.strain_mapped:,} | {stats.strain_unmapped:,} |")
    lines.append("")

    lines.append("### Mapping-source distribution")
    lines.append("")
    if stats.mapping_source_counts:
        lines.append("| Source | Count |")
        lines.append("|---|---|")
        for src, cnt in stats.mapping_source_counts.most_common():
            lines.append(f"| `{src}` | {cnt:,} |")
    else:
        lines.append("(no mappings resolved)")
    lines.append("")

    lines.append("### Unmapped NCBITaxon predicate fingerprint (top 15)")
    lines.append("")
    lines.append("If the unmapped NCBITaxon nodes carry a lot of phenotype/trait edges, "
                 "that's exactly what we're missing from the GTDB view.")
    lines.append("")
    if stats.unmapped_ncbi_sample_predicates:
        lines.append("| Predicate | Edges on unmapped NCBI nodes |")
        lines.append("|---|---|")
        for pred, cnt in stats.unmapped_ncbi_sample_predicates.most_common(15):
            lines.append(f"| `{pred}` | {cnt:,} |")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Tree shape (per-rank node count)")
    lines.append("")
    rank_counts: Counter = Counter()
    for clade in tree.find_clades():
        rank_counts[getattr(clade, "rank", "unknown")] += 1
    lines.append("| Rank | Nodes |")
    lines.append("|---|---|")
    for r in RANK_ORDER + ["root", "unknown"]:
        if rank_counts.get(r):
            lines.append(f"| {r} | {rank_counts[r]:,} |")
    lines.append("")

    lines.append("## Top-20 most heavily annotated clades (cumulative edge count)")
    lines.append("")
    ranked = sorted(
        ((clade for clade in tree.find_clades() if (clade.name or "").startswith("GTDB:") and getattr(clade, "cumulative_count", 0) > 0)),
        key=lambda c: c.cumulative_count,
        reverse=True,
    )[:20]
    lines.append("| GTDB ID | Name | Rank | Cumulative | Leaf-only |")
    lines.append("|---|---|---|---|---|")
    for c in ranked:
        lines.append(f"| `{c.name}` | {getattr(c, 'gtdb_name', '')} | {c.rank} | "
                     f"{c.cumulative_count:,} | {c.leaf_count:,} |")
    lines.append("")

    if notes:
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("## Upstream issue flagged: synthetic-integer GTDB CURIEs")
    lines.append("")
    lines.append("The GTDB transform mints `GTDB:N` integer CURIEs from a monotonic counter "
                 "(`kg_microbe/transform_utils/gtdb/gtdb.py::_get_or_create_taxon_id`). These IDs are "
                 "not resolvable on GTDB's site, are not stable across builds, and break joins with any "
                 "downstream consumer that uses canonical GTDB taxon strings or accessions. This skill "
                 "works around it by joining via the node `name` column (the canonical taxon string), "
                 "but the transform should be fixed to mint CURIEs like `GTDB:s__Escherichia_coli`.")
    lines.append("")
    lines.append("## Known limitations")
    lines.append("")
    lines.append("- The full-species static figure compresses ~143K leaves into a single canvas; "
                 "use the interactive HTML or iTOL annotation for legible exploration.")
    lines.append("- NCBITaxon nodes with no published or in-graph mapping to a GTDB species "
                 "(common for higher-rank taxa and 'environmental sample' entries) are folded into "
                 "the unmapped bucket and surface in the predicate fingerprint above.")
    lines.append("- Strain mapping requires both a strain->NCBITaxon parent edge and an NCBITaxon->GTDB "
                 "mapping; missing either step drops the strain.")
    lines.append("- `cumulative_count` propagates up the tree by summation, so a high count at a "
                 "phylum reflects all of its descendants' edges, not the phylum node itself.")

    out_path.write_text("\n".join(lines) + "\n")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged-dir", default="data/merged/20260523_nometatraits",
                    help="Directory containing merged-kg_nodes.tsv and merged-kg_edges.tsv")
    ap.add_argument("--gtdb-raw-dir", default="data/raw/gtdb")
    ap.add_argument("--gtdb-published-map", default="data/raw/NCBI2GTDB.tsv.gz")
    ap.add_argument("--out-dir", default=None,
                    help="Where to write outputs (default: data/processed/gtdb_phylo_diagram_<release>)")
    ap.add_argument("--collapse-ranks", default="phylum,class,family",
                    help="Comma-separated rank names to render rank-collapsed figures at")
    ap.add_argument("--min-majority-fraction", type=float, default=0.5,
                    help="Min majority_fraction for NCBI2GTDB.tsv.gz mappings")
    ap.add_argument("--skip-full", action="store_true",
                    help="Skip full-species toytree static figure")
    ap.add_argument("--skip-interactive", action="store_true",
                    help="Skip interactive toytree HTML")
    ap.add_argument("--skip-render", action="store_true",
                    help="Skip all rendering (data outputs only)")
    args = ap.parse_args()

    merged_dir = Path(args.merged_dir).resolve()
    nodes_tsv = merged_dir / "merged-kg_nodes.tsv"
    edges_tsv = merged_dir / "merged-kg_edges.tsv"
    if not nodes_tsv.exists() or not edges_tsv.exists():
        print(f"error: missing nodes/edges TSV in {merged_dir}", file=sys.stderr)
        return 2

    release = merged_dir.name
    out_dir = Path(args.out_dir) if args.out_dir else Path(f"data/processed/gtdb_phylo_diagram_{release}")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[info] output dir: {out_dir}", file=sys.stderr)

    stats = Stats()
    notes: list[str] = []

    print("[1/8] reading GTDB nodes from merged KG...", file=sys.stderr)
    gtdb_id_to_name, gtdb_name_to_id = load_gtdb_nodes(nodes_tsv)
    stats.gtdb_nodes = len(gtdb_id_to_name)
    print(f"      {stats.gtdb_nodes:,} GTDB nodes", file=sys.stderr)

    print("[2/8] streaming merged-kg edges (single pass)...", file=sys.stderr)
    gtdb_parent, closematch, strain_to_ncbi, taxon_edge_count, per_ncbi_predicates = stream_edges(
        edges_tsv, gtdb_id_to_name, stats,
    )
    print(f"      {stats.edges_total:,} edges; "
          f"{stats.gtdb_subclass_edges:,} GTDB hierarchy; "
          f"{stats.close_match_edges:,} close_match; "
          f"{stats.strain_parent_edges:,} strain parents", file=sys.stderr)

    print("[3/8] loading GTDB metadata mapping...", file=sys.stderr)
    meta_map = load_gtdb_metadata_mapping(Path(args.gtdb_raw_dir), gtdb_name_to_id)
    print(f"      {len(meta_map):,} ncbi->gtdb from metadata", file=sys.stderr)

    print("[4/8] loading published NCBI2GTDB table...", file=sys.stderr)
    published_map = load_published_gtdb_ncbi(
        Path(args.gtdb_published_map), gtdb_name_to_id, args.min_majority_fraction,
    )
    print(f"      {len(published_map):,} ncbi->gtdb from published "
          f"(>= {args.min_majority_fraction} majority_fraction)", file=sys.stderr)

    ncbi_to_gtdb = build_ncbi_to_gtdb(closematch, meta_map, published_map)
    print(f"      union: {len(ncbi_to_gtdb):,} ncbi->gtdb total", file=sys.stderr)

    print("[5/8] building Bio.Phylo tree from merged-KG hierarchy...", file=sys.stderr)
    tree = build_tree(gtdb_id_to_name, gtdb_parent)

    print("[6/8] folding counts onto GTDB clades + propagating...", file=sys.stderr)
    _by_clade, mapping_rows = fold_and_propagate(
        tree, taxon_edge_count, ncbi_to_gtdb, strain_to_ncbi, per_ncbi_predicates, stats,
    )

    # Persist mapping + per-clade counts.
    print("[7/8] writing TSV outputs...", file=sys.stderr)
    map_path = out_dir / "ncbi_strain_to_gtdb.tsv"
    with map_path.open("w") as fh:
        fh.write("source_curie\tgtdb_curie\tsource\tconfidence\n")
        for row in mapping_rows:
            fh.write("\t".join(row) + "\n")
    print(f"      wrote {map_path.name} ({len(mapping_rows):,} rows)", file=sys.stderr)

    counts_path = out_dir / "per_node_edge_counts.tsv"
    with counts_path.open("w") as fh:
        fh.write("gtdb_curie\tgtdb_name\trank\tleaf_count\tcumulative_count\n")
        for clade in tree.find_clades():
            if not (clade.name or "").startswith("GTDB:"):
                continue
            fh.write(f"{clade.name}\t{getattr(clade, 'gtdb_name','')}\t"
                     f"{getattr(clade, 'rank','')}\t{int(getattr(clade,'leaf_count',0))}\t"
                     f"{int(getattr(clade,'cumulative_count',0))}\n")
    print(f"      wrote {counts_path.name}", file=sys.stderr)

    # Newick + iTOL annotation.
    nwk_path = out_dir / "gtdb_tree.nwk"
    Phylo.write(tree, str(nwk_path), "newick")
    print(f"      wrote {nwk_path.name}", file=sys.stderr)
    itol_path = out_dir / "itol_node_sizes.txt"
    write_itol_simplebar(tree, itol_path)
    print(f"      wrote {itol_path.name}", file=sys.stderr)

    # Rendering.
    if not args.skip_render:
        print("[8/8] rendering figures...", file=sys.stderr)
        for rank in [r.strip() for r in args.collapse_ranks.split(",") if r.strip()]:
            if rank not in RANK_ORDER:
                notes.append(f"unknown rank `{rank}` requested in --collapse-ranks; skipped")
                continue
            print(f"      collapsing at {rank}...", file=sys.stderr)
            collapsed = collapse_at_rank(tree, rank)
            png = out_dir / f"gtdb_tree_{rank}.png"
            svg = out_dir / f"gtdb_tree_{rank}.svg"
            try:
                render_with_biopython(collapsed, png, svg, f"GTDB tree collapsed at {rank}")
            except Exception as exc:
                notes.append(f"Bio.Phylo render for rank `{rank}` failed: {exc}")

        if not args.skip_full or not args.skip_interactive:
            print("      toytree pass (full-species + interactive)...", file=sys.stderr)
            err = render_with_toytree(tree, out_dir, "gtdb_tree_full")
            if err:
                notes.append(err)
    else:
        notes.append("Rendering skipped (--skip-render).")

    print("[done] writing report.md", file=sys.stderr)
    write_report(out_dir / "report.md", stats, tree, gtdb_id_to_name, merged_dir, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
