"""Compare semantic modeling between two KG-Microbe merged-KG releases.

Produces a standardized Markdown report covering:
 - Schema differences (columns present/absent)
 - Node/edge counts
 - Biolink/METPO category usage (added, removed, count deltas)
 - Predicate usage (biolink vs METPO), added/removed, deltas
 - Relation column usage
 - CURIE prefix coverage on node ids, subjects, objects
 - primary_knowledge_source / provided_by distribution
 - Predicate x (subject_category, object_category) type signatures

Invocation:
    poetry run python .claude/skills/kg-release-diff/kg_release_diff.py \\
        --old  data/merged/20260120 \\
        --new  data/merged/20260422_nometatraits \\
        --out  release_diff_20260120_vs_20260422_nometatraits.md

Accepts either a directory containing `merged-kg_nodes.tsv` + `merged-kg_edges.tsv`
or explicit --old-nodes/--old-edges/--new-nodes/--new-edges paths.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

csv.field_size_limit(sys.maxsize)

NODE_BASENAMES = ("merged-kg_nodes.tsv", "nodes.tsv")
EDGE_BASENAMES = ("merged-kg_edges.tsv", "edges.tsv")

BIOLINK_DEPRECATED_CATEGORIES = {
    "biolink:ChemicalSubstance": "biolink:SmallMolecule",
    "biolink:GenomicEntity": "biolink:NucleicAcidEntity",
}

MAX_ENUMERATED_ROWS = 40


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _prefix_of(curie: str) -> str:
    if not curie:
        return ""
    if ":" not in curie:
        return "<no-prefix>"
    return curie.split(":", 1)[0]


@dataclass
class NodeStats:
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    category_counts: Counter = field(default_factory=Counter)
    prefix_counts: Counter = field(default_factory=Counter)
    provided_by_counts: Counter = field(default_factory=Counter)
    id_to_category: dict[str, str] = field(default_factory=dict)
    duplicate_ids: int = 0
    empty_category_rows: int = 0
    deprecated_category_rows: int = 0


@dataclass
class EdgeStats:
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    predicate_counts: Counter = field(default_factory=Counter)
    relation_counts: Counter = field(default_factory=Counter)
    subject_prefix_counts: Counter = field(default_factory=Counter)
    object_prefix_counts: Counter = field(default_factory=Counter)
    primary_source_counts: Counter = field(default_factory=Counter)
    predicate_signature: Counter = field(default_factory=Counter)  # (pred, subj_cat, obj_cat) -> count
    metpo_predicate_count: int = 0
    biolink_predicate_count: int = 0
    other_predicate_count: int = 0
    dangling_subject_count: int = 0
    dangling_object_count: int = 0


@dataclass
class ReleaseStats:
    label: str
    nodes_path: Path
    edges_path: Path
    nodes: NodeStats = field(default_factory=NodeStats)
    edges: EdgeStats = field(default_factory=EdgeStats)


def resolve_release(
    label: str,
    dir_arg: Path | None,
    nodes_arg: Path | None,
    edges_arg: Path | None,
) -> ReleaseStats:
    if dir_arg is not None:
        nodes = _find_file(dir_arg, NODE_BASENAMES)
        edges = _find_file(dir_arg, EDGE_BASENAMES)
    else:
        if not nodes_arg or not edges_arg:
            raise SystemExit(f"Release '{label}' requires --{label}-nodes and --{label}-edges when --{label} is not given")
        nodes, edges = nodes_arg, edges_arg
    if not nodes.exists():
        raise SystemExit(f"nodes file not found for '{label}': {nodes}")
    if not edges.exists():
        raise SystemExit(f"edges file not found for '{label}': {edges}")
    return ReleaseStats(label=label, nodes_path=nodes, edges_path=edges)


def _find_file(directory: Path, candidates: tuple[str, ...]) -> Path:
    for name in candidates:
        p = directory / name
        if p.exists():
            return p
        gz = directory / (name + ".gz")
        if gz.exists():
            return gz
    raise SystemExit(f"Could not find any of {candidates} in {directory}")


def scan_nodes(release: ReleaseStats, max_rows: int) -> None:
    ns = release.nodes
    seen_ids: set[str] = set()
    with _open_text(release.nodes_path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        ns.columns = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            if max_rows and i >= max_rows:
                break
            ns.rows += 1
            nid = (row.get("id") or "").strip()
            cat = (row.get("category") or "").strip()
            prov = (row.get("provided_by") or "").strip()
            if not cat:
                ns.empty_category_rows += 1
            else:
                ns.category_counts[cat] += 1
                if cat in BIOLINK_DEPRECATED_CATEGORIES:
                    ns.deprecated_category_rows += 1
            if nid:
                ns.prefix_counts[_prefix_of(nid)] += 1
                if nid in seen_ids:
                    ns.duplicate_ids += 1
                else:
                    seen_ids.add(nid)
                    if cat:
                        ns.id_to_category[nid] = cat
            for src in prov.split("|"):
                src = src.strip()
                if src:
                    ns.provided_by_counts[src] += 1


def scan_edges(release: ReleaseStats, max_rows: int, signatures: bool) -> None:
    es = release.edges
    id2cat = release.nodes.id_to_category if signatures else {}
    with _open_text(release.edges_path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        es.columns = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            if max_rows and i >= max_rows:
                break
            es.rows += 1
            subj = (row.get("subject") or "").strip()
            obj = (row.get("object") or "").strip()
            pred = (row.get("predicate") or "").strip()
            rel = (row.get("relation") or "").strip()
            pks = (row.get("primary_knowledge_source") or "").strip()
            if pred:
                es.predicate_counts[pred] += 1
                if pred.startswith("biolink:"):
                    es.biolink_predicate_count += 1
                elif pred.startswith("METPO:"):
                    es.metpo_predicate_count += 1
                else:
                    es.other_predicate_count += 1
            if rel:
                es.relation_counts[rel] += 1
            if subj:
                es.subject_prefix_counts[_prefix_of(subj)] += 1
            if obj:
                es.object_prefix_counts[_prefix_of(obj)] += 1
            if pks:
                es.primary_source_counts[pks] += 1
            if signatures and id2cat:
                sc = id2cat.get(subj, "<unknown>")
                oc = id2cat.get(obj, "<unknown>")
                if sc == "<unknown>" and subj:
                    es.dangling_subject_count += 1
                if oc == "<unknown>" and obj:
                    es.dangling_object_count += 1
                es.predicate_signature[(pred, sc, oc)] += 1


def _fmt_count(n: int) -> str:
    return f"{n:,}"


def _pct(numer: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{(100.0 * numer / denom):.2f}%"


def _diff_sets(a: Counter, b: Counter) -> tuple[list[str], list[str], list[tuple[str, int, int, int]]]:
    """Return (added_keys, removed_keys, delta_rows sorted by abs delta desc)."""
    a_keys = set(a)
    b_keys = set(b)
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    common = a_keys & b_keys
    deltas = []
    for k in common:
        av, bv = a[k], b[k]
        if av != bv:
            deltas.append((k, av, bv, bv - av))
    deltas.sort(key=lambda r: abs(r[3]), reverse=True)
    return added, removed, deltas


def _table_added_removed(title: str, added: list[str], counts_new: Counter, removed: list[str], counts_old: Counter) -> list[str]:
    lines = []
    if added:
        lines.append(f"#### Added in new ({len(added)})")
        lines.append("")
        lines.append("| Key | New count |")
        lines.append("|---|---:|")
        for k in sorted(added, key=lambda x: counts_new.get(x, 0), reverse=True)[:MAX_ENUMERATED_ROWS]:
            lines.append(f"| `{k}` | {_fmt_count(counts_new.get(k, 0))} |")
        if len(added) > MAX_ENUMERATED_ROWS:
            lines.append(f"| _…and {len(added) - MAX_ENUMERATED_ROWS} more_ | |")
        lines.append("")
    if removed:
        lines.append(f"#### Removed in new ({len(removed)})")
        lines.append("")
        lines.append("| Key | Old count |")
        lines.append("|---|---:|")
        for k in sorted(removed, key=lambda x: counts_old.get(x, 0), reverse=True)[:MAX_ENUMERATED_ROWS]:
            lines.append(f"| `{k}` | {_fmt_count(counts_old.get(k, 0))} |")
        if len(removed) > MAX_ENUMERATED_ROWS:
            lines.append(f"| _…and {len(removed) - MAX_ENUMERATED_ROWS} more_ | |")
        lines.append("")
    if not added and not removed:
        lines.append(f"_No {title.lower()} added or removed._")
        lines.append("")
    return lines


def _table_deltas(title: str, deltas: list[tuple[str, int, int, int]]) -> list[str]:
    lines = []
    if not deltas:
        lines.append(f"_No {title.lower()} count changes._")
        lines.append("")
        return lines
    lines.append(f"#### Top count changes ({len(deltas)} keys with shared membership changed)")
    lines.append("")
    lines.append("| Key | Old | New | Δ |")
    lines.append("|---|---:|---:|---:|")
    for k, av, bv, d in deltas[:MAX_ENUMERATED_ROWS]:
        sign = "+" if d > 0 else ""
        lines.append(f"| `{k}` | {_fmt_count(av)} | {_fmt_count(bv)} | {sign}{_fmt_count(d)} |")
    if len(deltas) > MAX_ENUMERATED_ROWS:
        lines.append(f"| _…and {len(deltas) - MAX_ENUMERATED_ROWS} more_ | | | |")
    lines.append("")
    return lines


def _schema_diff(old_cols: list[str], new_cols: list[str]) -> list[str]:
    old_set, new_set = set(old_cols), set(new_cols)
    lines = []
    lines.append(f"- old columns: `{old_cols}`")
    lines.append(f"- new columns: `{new_cols}`")
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    if added:
        lines.append(f"- columns added in new: {', '.join(f'`{c}`' for c in added)}")
    if removed:
        lines.append(f"- columns removed in new: {', '.join(f'`{c}`' for c in removed)}")
    if not added and not removed:
        lines.append("- schema: identical column set")
    return lines


def _top_signature_delta(old: Counter, new: Counter, top_n: int = 30) -> list[str]:
    keys = set(old) | set(new)
    rows = []
    for k in keys:
        av = old.get(k, 0)
        bv = new.get(k, 0)
        if av == bv:
            continue
        rows.append((k, av, bv, bv - av))
    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    lines = []
    if not rows:
        lines.append("_No predicate-signature differences._")
        lines.append("")
        return lines
    lines.append(f"Top {min(top_n, len(rows))} of {len(rows)} (pred, subj-category, obj-category) signatures with count changes:")
    lines.append("")
    lines.append("| Predicate | Subject category | Object category | Old | New | Δ |")
    lines.append("|---|---|---|---:|---:|---:|")
    for (pred, sc, oc), av, bv, d in rows[:top_n]:
        sign = "+" if d > 0 else ""
        lines.append(f"| `{pred}` | `{sc}` | `{oc}` | {_fmt_count(av)} | {_fmt_count(bv)} | {sign}{_fmt_count(d)} |")
    lines.append("")
    return lines


def build_report(old: ReleaseStats, new: ReleaseStats, include_signatures: bool) -> str:
    out: list[str] = []
    ap = out.append
    ap(f"# KG-Microbe Semantic Modeling Diff: `{old.label}` → `{new.label}`")
    ap("")
    ap(f"- **Old release:** `{old.nodes_path.parent}` (`{old.label}`)")
    ap(f"- **New release:** `{new.nodes_path.parent}` (`{new.label}`)")
    ap("")

    # --- 1. Summary counts
    ap("## 1. Summary")
    ap("")
    ap("| Metric | Old | New | Δ |")
    ap("|---|---:|---:|---:|")
    for name, a, b in [
        ("Nodes", old.nodes.rows, new.nodes.rows),
        ("Edges", old.edges.rows, new.edges.rows),
        ("Distinct categories", len(old.nodes.category_counts), len(new.nodes.category_counts)),
        ("Distinct predicates", len(old.edges.predicate_counts), len(new.edges.predicate_counts)),
        ("Distinct relations", len(old.edges.relation_counts), len(new.edges.relation_counts)),
        ("Distinct node prefixes", len(old.nodes.prefix_counts), len(new.nodes.prefix_counts)),
        ("METPO predicate edges", old.edges.metpo_predicate_count, new.edges.metpo_predicate_count),
        ("Biolink predicate edges", old.edges.biolink_predicate_count, new.edges.biolink_predicate_count),
        ("Other predicate edges", old.edges.other_predicate_count, new.edges.other_predicate_count),
        ("Duplicate node IDs", old.nodes.duplicate_ids, new.nodes.duplicate_ids),
        ("Empty category node rows", old.nodes.empty_category_rows, new.nodes.empty_category_rows),
        ("Deprecated-category node rows", old.nodes.deprecated_category_rows, new.nodes.deprecated_category_rows),
    ]:
        d = b - a
        sign = "+" if d > 0 else ""
        ap(f"| {name} | {_fmt_count(a)} | {_fmt_count(b)} | {sign}{_fmt_count(d)} |")
    ap("")

    # --- 2. Schema
    ap("## 2. Schema (columns)")
    ap("")
    ap("### Nodes")
    out.extend(_schema_diff(old.nodes.columns, new.nodes.columns))
    ap("")
    ap("### Edges")
    out.extend(_schema_diff(old.edges.columns, new.edges.columns))
    ap("")

    # --- 3. Categories
    ap("## 3. Biolink / METPO category usage")
    ap("")
    added, removed, deltas = _diff_sets(old.nodes.category_counts, new.nodes.category_counts)
    out.extend(_table_added_removed("Categories", added, new.nodes.category_counts, removed, old.nodes.category_counts))
    out.extend(_table_deltas("Category", deltas))

    # Flag deprecated biolink categories still present
    deprecated_new = {c: v for c, v in new.nodes.category_counts.items() if c in BIOLINK_DEPRECATED_CATEGORIES}
    if deprecated_new:
        ap("#### Deprecated Biolink categories still present in new release")
        ap("")
        ap("| Category | Count | Replacement |")
        ap("|---|---:|---|")
        for c, v in sorted(deprecated_new.items(), key=lambda kv: -kv[1]):
            ap(f"| `{c}` | {_fmt_count(v)} | `{BIOLINK_DEPRECATED_CATEGORIES[c]}` |")
        ap("")

    # --- 4. Predicates
    ap("## 4. Predicate usage")
    ap("")
    added, removed, deltas = _diff_sets(old.edges.predicate_counts, new.edges.predicate_counts)
    out.extend(_table_added_removed("Predicates", added, new.edges.predicate_counts, removed, old.edges.predicate_counts))
    out.extend(_table_deltas("Predicate", deltas))

    # Biolink vs METPO proportions
    ap("#### Predicate vocabulary shift")
    ap("")
    ap("| Vocabulary | Old edges | Old % | New edges | New % |")
    ap("|---|---:|---:|---:|---:|")
    ap(
        f"| `biolink:*` | {_fmt_count(old.edges.biolink_predicate_count)} | "
        f"{_pct(old.edges.biolink_predicate_count, old.edges.rows)} | "
        f"{_fmt_count(new.edges.biolink_predicate_count)} | "
        f"{_pct(new.edges.biolink_predicate_count, new.edges.rows)} |"
    )
    ap(
        f"| `METPO:*` | {_fmt_count(old.edges.metpo_predicate_count)} | "
        f"{_pct(old.edges.metpo_predicate_count, old.edges.rows)} | "
        f"{_fmt_count(new.edges.metpo_predicate_count)} | "
        f"{_pct(new.edges.metpo_predicate_count, new.edges.rows)} |"
    )
    ap(
        f"| other | {_fmt_count(old.edges.other_predicate_count)} | "
        f"{_pct(old.edges.other_predicate_count, old.edges.rows)} | "
        f"{_fmt_count(new.edges.other_predicate_count)} | "
        f"{_pct(new.edges.other_predicate_count, new.edges.rows)} |"
    )
    ap("")

    # --- 5. Relations
    ap("## 5. Relation column usage")
    ap("")
    added, removed, deltas = _diff_sets(old.edges.relation_counts, new.edges.relation_counts)
    out.extend(_table_added_removed("Relations", added, new.edges.relation_counts, removed, old.edges.relation_counts))
    out.extend(_table_deltas("Relation", deltas))

    # --- 6. CURIE prefixes
    ap("## 6. CURIE prefix coverage")
    ap("")
    ap("### Node-id prefixes")
    added, removed, deltas = _diff_sets(old.nodes.prefix_counts, new.nodes.prefix_counts)
    out.extend(_table_added_removed("Node-id prefixes", added, new.nodes.prefix_counts, removed, old.nodes.prefix_counts))
    out.extend(_table_deltas("Node-id prefix", deltas))
    ap("### Edge-subject prefixes")
    added, removed, deltas = _diff_sets(old.edges.subject_prefix_counts, new.edges.subject_prefix_counts)
    out.extend(_table_added_removed("Subject prefixes", added, new.edges.subject_prefix_counts, removed, old.edges.subject_prefix_counts))
    out.extend(_table_deltas("Subject prefix", deltas))
    ap("### Edge-object prefixes")
    added, removed, deltas = _diff_sets(old.edges.object_prefix_counts, new.edges.object_prefix_counts)
    out.extend(_table_added_removed("Object prefixes", added, new.edges.object_prefix_counts, removed, old.edges.object_prefix_counts))
    out.extend(_table_deltas("Object prefix", deltas))

    # --- 7. Primary knowledge source
    ap("## 7. primary_knowledge_source distribution")
    ap("")
    added, removed, deltas = _diff_sets(old.edges.primary_source_counts, new.edges.primary_source_counts)
    out.extend(_table_added_removed("Sources", added, new.edges.primary_source_counts, removed, old.edges.primary_source_counts))
    out.extend(_table_deltas("Source", deltas))

    # --- 8. provided_by on nodes
    ap("## 8. provided_by distribution on nodes")
    ap("")
    added, removed, deltas = _diff_sets(old.nodes.provided_by_counts, new.nodes.provided_by_counts)
    out.extend(_table_added_removed("provided_by values", added, new.nodes.provided_by_counts, removed, old.nodes.provided_by_counts))
    out.extend(_table_deltas("provided_by", deltas))

    # --- 9. Predicate x category signatures
    if include_signatures:
        ap("## 9. Predicate × (subject category, object category) signatures")
        ap("")
        out.extend(_top_signature_delta(old.edges.predicate_signature, new.edges.predicate_signature))
        ap(
            f"Dangling-subject edges (subject id missing from nodes table) — "
            f"old: {_fmt_count(old.edges.dangling_subject_count)}, new: {_fmt_count(new.edges.dangling_subject_count)}"
        )
        ap(
            f"Dangling-object edges — "
            f"old: {_fmt_count(old.edges.dangling_object_count)}, new: {_fmt_count(new.edges.dangling_object_count)}"
        )
        ap("")

    ap("---")
    ap("")
    ap("_Generated by `.claude/skills/kg-release-diff/kg_release_diff.py`._")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", type=Path, help="Directory containing old release's nodes/edges TSVs")
    ap.add_argument("--new", type=Path, help="Directory containing new release's nodes/edges TSVs")
    ap.add_argument("--old-nodes", type=Path)
    ap.add_argument("--old-edges", type=Path)
    ap.add_argument("--new-nodes", type=Path)
    ap.add_argument("--new-edges", type=Path)
    ap.add_argument("--old-label", default=None)
    ap.add_argument("--new-label", default=None)
    ap.add_argument("--out", type=Path, default=None, help="Output markdown path (default: stdout)")
    ap.add_argument("--max-rows", type=int, default=0, help="Row cap per file (0 = all)")
    ap.add_argument("--no-signatures", action="store_true", help="Skip predicate × category signature pass (saves memory)")
    args = ap.parse_args()

    old_label = args.old_label or (args.old.name if args.old else "old")
    new_label = args.new_label or (args.new.name if args.new else "new")

    old = resolve_release("old", args.old, args.old_nodes, args.old_edges)
    new = resolve_release("new", args.new, args.new_nodes, args.new_edges)
    old.label = old_label
    new.label = new_label

    include_signatures = not args.no_signatures

    print(f"[scan] old nodes: {old.nodes_path}", file=sys.stderr)
    scan_nodes(old, args.max_rows)
    print(f"[scan] old edges: {old.edges_path}", file=sys.stderr)
    scan_edges(old, args.max_rows, include_signatures)
    print(f"[scan] new nodes: {new.nodes_path}", file=sys.stderr)
    scan_nodes(new, args.max_rows)
    print(f"[scan] new edges: {new.edges_path}", file=sys.stderr)
    scan_edges(new, args.max_rows, include_signatures)

    if include_signatures:
        old.nodes.id_to_category.clear()
        new.nodes.id_to_category.clear()

    report = build_report(old, new, include_signatures)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"[done] wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
