#!/usr/bin/env python3
"""Report status of every post-transform / post-merge operation in KG-Microbe.

Walks a hand-maintained catalog of operations that run *after* `kg transform`
and `kg merge` to arrive at the final shipped data products. For each
operation, inspects the filesystem to determine current freshness and emits a
structured Markdown report.

Default invocation scans the most-recent merged release directory it can find:

    poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py

Pin a specific release or destination:

    poetry run python .claude/skills/kg-postprocess-report/kg_postprocess_report.py \\
        --merged-dir data/merged/20260423 \\
        --out reports/postprocess_status.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import sys
from dataclasses import dataclass, field
from pathlib import Path

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_MISSING = "missing"
STATUS_NA = "n/a"
STATUS_AUTO = "auto"

# Severity used to decide whether the operation blocks a release. Tweak per row
# in the catalog. "blocker" rows are summarized at the top of the report.
SEV_BLOCKER = "blocker"
SEV_RECOMMENDED = "recommended"
SEV_OPTIONAL = "optional"


@dataclass
class Operation:
    name: str
    stage: str
    title: str
    purpose: str
    command: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    required_for: str = ""
    severity: str = SEV_RECOMMENDED
    auto: bool = False
    notes: str = ""


# ----------------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------------

def build_catalog(merged_dir: Path | None, transformed_dir: Path) -> list[Operation]:
    """Return the full list of catalogued operations.

    `merged_dir` may be None when no merged release has been built yet; in that
    case post-merge entries will simply report "missing".
    """
    merged_nodes = str(merged_dir / "merged-kg_nodes.tsv") if merged_dir else ""
    merged_edges = str(merged_dir / "merged-kg_edges.tsv") if merged_dir else ""
    merged_stats = str(merged_dir / "merged-kg_stats.yaml") if merged_dir else ""
    merged_tar = str(merged_dir / "merged-kg.tar.gz") if merged_dir else ""

    transformed_glob = f"{transformed_dir}/*/nodes.tsv"

    ops: list[Operation] = [
        # -------------------- POST-TRANSFORM --------------------
        Operation(
            name="chemical-mapping-unify",
            stage="post-transform",
            title="Unified chemical mapping regeneration",
            purpose=(
                "Consolidate KEGG / BacDive / MediaDive / ChEBI / CultureBotAI "
                "mappings into the single canonical SSSOM file used by every "
                "transform that touches chemical identifiers."
            ),
            command="poetry run python scripts/consolidate_chemical_mappings.py",
            inputs=[
                "scripts/consolidate_chemical_mappings.py",
                "mappings/ingredient_mappings.sssom.tsv",
                "data/raw/mediadive/*",
                "data/raw/bacdive/*",
            ],
            outputs=["mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"],
            required_for="bacdive / mediadive / metatraits transforms (reads this file)",
            severity=SEV_BLOCKER,
            notes=(
                "If this is stale, transforms emit phantom CHEBI/PubChem mappings "
                "or drop ingredients silently. See `chemical-mapping` skill."
            ),
        ),
        Operation(
            name="isolation-source-schema-validate",
            stage="post-transform",
            title="Isolation-source mapping schema validation",
            purpose=(
                "Schema-level validation (CURIE shape, predicate vocab, category "
                "allowlists, lexical drift) on the isolation-source curation file."
            ),
            command="make validate-isolation-source-schema",
            inputs=["mappings/isolation_source_to_ontology.tsv"],
            outputs=[],  # validator prints to stdout, no artifact
            required_for="merged-KG quality gate",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="ingredient-mapping-schema-validate",
            stage="post-transform",
            title="Ingredient mapping schema validation",
            purpose="SSSOM schema check on the MediaDive ingredient mapping file.",
            command="make validate-ingredient-schema",
            inputs=["mappings/ingredient_mappings.sssom.tsv"],
            outputs=[],
            required_for="chemical-mapping-unify (consumes this file)",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="manual-mapping-validate",
            stage="post-transform",
            title="Hardcoded-mapping conflict scan",
            purpose=(
                "Detect duplicates / conflicts across hand-curated mapping files "
                "used by transforms."
            ),
            command="poetry run python mappings/validate_manual_mappings.py",
            inputs=["mappings/*.tsv", "mappings/*.yaml"],
            outputs=[],
            required_for="merged-KG quality gate",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="metatraits-unmapped-aggregate",
            stage="post-transform",
            title="Metatraits unmapped-trait aggregation",
            purpose=(
                "Extract unique unmapped trait IDs and relation prefixes from "
                "metatraits output for the curation backlog."
            ),
            command="make process-metatraits-unmapped",
            inputs=[f"{transformed_dir}/metatraits/unmapped_traits.tsv"],
            outputs=[f"{transformed_dir}/metatraits/unmapped_traits_unique.tsv"],
            required_for="metpo-proposals workflow",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="metatraits-coverage-report",
            stage="post-transform",
            title="Metatraits coverage report",
            purpose=(
                "Quantify METPO / CHEBI / GO / EC mapping coverage across "
                "metatraits edges; count unmapped by predicate."
            ),
            command="poetry run python scripts/generate_coverage_report.py",
            inputs=[
                f"{transformed_dir}/metatraits/edges.tsv",
                f"{transformed_dir}/metatraits_gtdb/edges.tsv",
            ],
            outputs=[],  # prints to stdout / no fixed artifact
            required_for="release notes",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="metpo-proposals-extract",
            stage="post-transform",
            title="METPO term-proposal extraction",
            purpose=(
                "Mine unmapped traits to draft new METPO terms with definitions "
                "and candidate parents."
            ),
            command="poetry run python scripts/extract_metpo_proposals.py",
            inputs=[f"{transformed_dir}/metatraits/unmapped_traits.tsv"],
            outputs=[],
            required_for="upstream METPO submission",
            severity=SEV_OPTIONAL,
            notes="See `/metpo-proposal` skill for the full workflow.",
        ),
        Operation(
            name="ro-relations-validate",
            stage="post-transform",
            title="RO / relation column validation",
            purpose="Check every `relation` value exists in RO; flag domain drift.",
            command="poetry run python scripts/validate_ro_relations.py",
            inputs=[transformed_glob],
            outputs=[],
            required_for="merged-KG quality gate",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="knowledge-sources-validate",
            stage="post-transform",
            title="Knowledge-source provenance validation",
            purpose=(
                "Verify every `provided_by` / `primary_knowledge_source` is "
                "registered in infores or a known alias."
            ),
            command="poetry run python scripts/validate_knowledge_sources.py",
            inputs=[transformed_glob],
            outputs=[],
            required_for="merged-KG quality gate",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="metpo-custom-mapping-audit",
            stage="post-transform",
            title="Custom METPO mapping audit",
            purpose=(
                "Analyze hardcoded METPO mappings across transform code for "
                "consistency; surface candidate new terms."
            ),
            command="poetry run python scripts/analyze_custom_metpo_mappings.py",
            inputs=["kg_microbe/transform_utils/**/*.py"],
            outputs=[],
            required_for="metpo-proposals workflow",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="gtdb-metatraits-overlap",
            stage="post-transform",
            title="GTDB vs metatraits overlap analysis",
            purpose=(
                "Detect redundant or conflicting claims between metatraits and "
                "metatraits_gtdb."
            ),
            command="poetry run python scripts/analyze_gtdb_metatraits_overlap.py",
            inputs=[
                f"{transformed_dir}/metatraits/edges.tsv",
                f"{transformed_dir}/metatraits_gtdb/edges.tsv",
            ],
            outputs=[],
            required_for="merge variant decision (merge.yaml vs merge.no_metatraits.yaml)",
            severity=SEV_OPTIONAL,
        ),

        # -------------------- POST-MERGE (automatic) --------------------
        Operation(
            name="merge-cleanup",
            stage="post-merge",
            title="Merged TSV cleanup & canonical column order",
            purpose=(
                "Dedup columns, drop auxiliary KGX columns (`subsets`, `meta`, "
                "`id`), strip stray `\\r`, fold deprecated `knowledge_source` "
                "into `primary_knowledge_source`, reorder to the canonical "
                "schema, and re-tar if compression is enabled."
            ),
            command="(runs automatically inside `kg merge`)",
            inputs=[],
            outputs=[merged_nodes, merged_edges] if merged_dir else [],
            required_for="all downstream consumers",
            severity=SEV_BLOCKER,
            auto=True,
            notes=(
                "Implemented in `kg_microbe/merge_utils/merge_kg.py::"
                "_cleanup_merged_outputs`. If you see un-normalized columns "
                "this hook silently failed — re-run merge."
            ),
        ),
        Operation(
            name="merge-graph-stats",
            stage="post-merge",
            title="Merged-KG statistics YAML",
            purpose="Counts of nodes / edges by category, predicate, and SPO signature.",
            command="(emitted by KGX during `kg merge`)",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[merged_stats, "merged_graph_stats.yaml"] if merged_dir else ["merged_graph_stats.yaml"],
            required_for="release notes, kg-release-diff",
            severity=SEV_RECOMMENDED,
            auto=True,
        ),
        Operation(
            name="run-summary",
            stage="post-merge",
            title="Quick summary dump",
            purpose=(
                "Print high-level node/edge counts by major prefix and "
                "relationship type to sanity-check a merge."
            ),
            command="make run-summary",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[],
            required_for="manual smoke test after merge",
            severity=SEV_OPTIONAL,
        ),

        # -------------------- POST-MERGE (format conversion / DBs) --------------------
        Operation(
            name="convert-merged-to-nt",
            stage="post-merge",
            title="TSV → N-Triples conversion",
            purpose="Produce an RDF N-Triples copy of the merged KG for SPARQL endpoints.",
            command="kgx transform --transform-config convert_merged_to_nt.yaml",
            inputs=["convert_merged_to_nt.yaml", merged_nodes, merged_edges] if merged_dir else ["convert_merged_to_nt.yaml"],
            outputs=[str(merged_dir / "merged-kg.nt")] if merged_dir else [],
            required_for="SPARQL endpoint, semantic-web downstream users",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="neo4j-upload",
            stage="post-merge",
            title="Neo4j bulk load",
            purpose="Load merged-KG into a local Neo4j instance for graph queries.",
            command="make neo4j-upload",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[],  # external DB; no tracked file
            required_for="Neo4j-based exploration",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="duckdb-load",
            stage="post-merge",
            title="DuckDB query cache",
            purpose="Build a SQL-queryable copy of the merged KG (used by `kg query-organism`).",
            command="poetry run kg query-organism <organism>  # auto-builds on first call",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[str(merged_dir / "kg_microbe.duckdb")] if merged_dir else [],
            required_for="`kg query-organism`",
            severity=SEV_OPTIONAL,
        ),
        Operation(
            name="holdouts",
            stage="post-merge",
            title="Train / test / validation edge splits",
            purpose="Generate positive/negative holdouts for ML link-prediction training.",
            command="poetry run kg holdouts -n <nodes.tsv> -e <edges.tsv> -o data/holdouts/",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=["data/holdouts/"],
            required_for="ML training workflows (consumer-driven; not a release gate)",
            severity=SEV_OPTIONAL,
        ),

        # -------------------- REVIEW GATES (release prerequisites) --------------------
        Operation(
            name="kg-model-review",
            stage="review-gate",
            title="Single-edge KGX / Biolink / METPO review",
            purpose=(
                "Validate KGX schema, Biolink Model conformance, METPO semantics, "
                "and CURIE prefix registration on the merged KG."
            ),
            command="invoke `/kg-model-review` skill",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[".claude/skills/kg-model-review/reviews/*.md"],
            required_for="kg-release (hard gate unless --ignore-review)",
            severity=SEV_BLOCKER,
        ),
        Operation(
            name="kg-path-review",
            stage="review-gate",
            title="Multi-hop semantic path review",
            purpose=(
                "Walk multi-hop paths through the merged KG and flag modeling "
                "bugs (cross-contamination, self-loops, phantom intermediates, "
                "missing expected paths, cardinality outliers)."
            ),
            command="invoke `/kg-path-review` skill",
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=[".claude/skills/kg-path-review/reviews/*.md"],
            required_for="kg-release (hard gate unless --ignore-review)",
            severity=SEV_BLOCKER,
        ),
        Operation(
            name="audit-mappings",
            stage="review-gate",
            title="Mapping / code-pattern audit",
            purpose=(
                "Scan code + curation files for hardcoded mappings, dead files, "
                "schema heterogeneity, and repeated 'data masquerading as code'."
            ),
            command="invoke `/audit-mappings` skill",
            inputs=["mappings/", "kg_microbe/"],
            outputs=[],
            required_for="release hygiene (not a hard gate)",
            severity=SEV_RECOMMENDED,
        ),

        # -------------------- RELEASE --------------------
        Operation(
            name="kg-release-diff",
            stage="release",
            title="Inter-release semantic diff",
            purpose=(
                "Quantify category / predicate / relation / prefix / "
                "knowledge-source deltas vs the prior release."
            ),
            command=(
                "poetry run python .claude/skills/kg-release-diff/"
                "kg_release_diff.py --old <prior> --new <current> --out <report.md>"
            ),
            inputs=[merged_nodes, merged_edges] if merged_dir else [],
            outputs=["data/merged/release_diff_*.md"],
            required_for="release notes",
            severity=SEV_RECOMMENDED,
        ),
        Operation(
            name="kg-release",
            stage="release",
            title="GitHub release bundling",
            purpose=(
                "Bundle merged-KG + transformed + raw into tarballs, split parts "
                "over 1.9 GiB, fall back to Zenodo for very large raw, gate on "
                "review verdicts, publish to GitHub."
            ),
            command=(
                "poetry run python .claude/skills/kg-release/kg_release.py "
                "--release <vYYYYMMDD> --merged-dir <merged_dir>"
            ),
            inputs=[merged_tar, merged_nodes, merged_edges] if merged_dir else [],
            outputs=["releases/*/MANIFEST_*.json"],
            required_for="public distribution",
            severity=SEV_BLOCKER,
        ),
    ]
    return ops


# ----------------------------------------------------------------------------
# Status evaluation
# ----------------------------------------------------------------------------

def _expand(paths: list[str], repo: Path) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p:
            continue
        abs_pattern = p if Path(p).is_absolute() else str(repo / p)
        if any(ch in p for ch in "*?["):
            out.extend(Path(m) for m in glob.glob(abs_pattern, recursive=True))
        else:
            out.append(Path(abs_pattern))
    return out


def _latest_mtime(paths: list[Path]) -> dt.datetime | None:
    latest: dt.datetime | None = None
    for p in paths:
        if p.exists():
            mt = dt.datetime.fromtimestamp(p.stat().st_mtime)
            if latest is None or mt > latest:
                latest = mt
    return latest


def evaluate(op: Operation, repo: Path) -> tuple[str, str]:
    if op.auto:
        outs = _expand(op.outputs, repo)
        out_mt = _latest_mtime(outs) if outs else None
        if out_mt is None and op.outputs:
            return STATUS_MISSING, "Auto-step ran in a prior merge but output is gone — re-run `kg merge`."
        if out_mt:
            return STATUS_AUTO, f"Last produced {out_mt.isoformat(timespec='seconds')} (auto)."
        return STATUS_AUTO, "Runs automatically inside its parent command."

    outs = _expand(op.outputs, repo)
    ins = _expand(op.inputs, repo)
    out_mt = _latest_mtime(outs) if outs else None
    in_mt = _latest_mtime(ins) if ins else None

    if not op.outputs:
        return STATUS_NA, "No tracked artifact — status is unknown without running."
    if out_mt is None:
        first = op.outputs[0]
        return STATUS_MISSING, f"Expected output not found: {first}"
    if in_mt and in_mt > out_mt:
        return STATUS_STALE, (
            f"Inputs newer than output "
            f"({in_mt.isoformat(timespec='seconds')} > {out_mt.isoformat(timespec='seconds')})."
        )
    return STATUS_OK, f"Last produced {out_mt.isoformat(timespec='seconds')}."


# ----------------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------------

STAGE_ORDER = ["post-transform", "post-merge", "review-gate", "release"]
STAGE_TITLE = {
    "post-transform": "Post-transform operations",
    "post-merge": "Post-merge operations",
    "review-gate": "Review gates (release prerequisites)",
    "release": "Release",
}


def render(ops: list[Operation], statuses: dict[str, tuple[str, str]], repo: Path,
           merged_dir: Path | None, transformed_dir: Path) -> str:
    now = dt.datetime.now().isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# KG-Microbe post-processing status report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Repo: `{repo}`")
    lines.append(f"Transformed dir: `{transformed_dir}`")
    lines.append(f"Merged dir: `{merged_dir if merged_dir else '(none detected)'}`")
    lines.append("")

    # Top-line summary
    blockers_missing = [
        op for op in ops
        if op.severity == SEV_BLOCKER and statuses[op.name][0] in (STATUS_MISSING, STATUS_STALE)
    ]
    lines.append("## Top-line summary")
    lines.append("")
    if blockers_missing:
        lines.append(f"**{len(blockers_missing)} release blocker(s) need attention:**")
        for op in blockers_missing:
            status, detail = statuses[op.name]
            lines.append(f"- `{op.name}` ({status}) — {detail}")
    else:
        lines.append("All release-blocker operations are present and fresh.")
    lines.append("")

    counts: dict[str, int] = {}
    for op in ops:
        s = statuses[op.name][0]
        counts[s] = counts.get(s, 0) + 1
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for status in (STATUS_OK, STATUS_AUTO, STATUS_STALE, STATUS_MISSING, STATUS_NA):
        if counts.get(status):
            lines.append(f"| {status} | {counts[status]} |")
    lines.append("")

    # Per-stage detail
    for stage in STAGE_ORDER:
        stage_ops = [op for op in ops if op.stage == stage]
        if not stage_ops:
            continue
        lines.append(f"## {STAGE_TITLE[stage]}")
        lines.append("")
        lines.append("| Operation | Status | Severity | Detail |")
        lines.append("|---|---|---|---|")
        for op in stage_ops:
            status, detail = statuses[op.name]
            lines.append(f"| `{op.name}` | {status} | {op.severity} | {detail} |")
        lines.append("")

        for op in stage_ops:
            status, detail = statuses[op.name]
            lines.append(f"### `{op.name}` — {op.title}")
            lines.append("")
            lines.append(f"- **Status:** {status} — {detail}")
            lines.append(f"- **Severity:** {op.severity}")
            lines.append(f"- **Purpose:** {op.purpose}")
            lines.append(f"- **Command:** `{op.command}`")
            if op.inputs:
                lines.append("- **Inputs:**")
                for p in op.inputs:
                    lines.append(f"  - `{p}`")
            if op.outputs:
                lines.append("- **Outputs:**")
                for p in op.outputs:
                    lines.append(f"  - `{p}`")
            if op.required_for:
                lines.append(f"- **Required for:** {op.required_for}")
            if op.notes:
                lines.append(f"- **Notes:** {op.notes}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Legend: `ok` = output fresh relative to inputs; `stale` = inputs newer "
                 "than output; `missing` = expected output not found; `auto` = runs "
                 "automatically inside another command; `n/a` = no tracked artifact, "
                 "must be re-run to confirm.")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def autodetect_merged_dir(repo: Path) -> Path | None:
    candidates: list[Path] = []
    merged_root = repo / "data" / "merged"
    if merged_root.exists():
        for child in merged_root.iterdir():
            if child.is_dir() and (child / "merged-kg_nodes.tsv").exists():
                candidates.append(child)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=".",
        help="Path to the kg-microbe repo root (default: cwd).",
    )
    parser.add_argument(
        "--merged-dir", default=None,
        help="Specific merged release dir under data/merged/. "
             "Auto-detects the most-recent if omitted.",
    )
    parser.add_argument(
        "--transformed-dir", default="data/transformed",
        help="Per-source transform output root (default: data/transformed).",
    )
    parser.add_argument(
        "--out", default=None,
        help="Write report here (default: stdout).",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    transformed_dir = Path(args.transformed_dir)
    if not transformed_dir.is_absolute():
        transformed_dir = repo / transformed_dir

    if args.merged_dir:
        merged_dir = Path(args.merged_dir)
        if not merged_dir.is_absolute():
            merged_dir = repo / merged_dir
        if not merged_dir.exists():
            print(f"warning: merged dir not found: {merged_dir}", file=sys.stderr)
            merged_dir = None
    else:
        merged_dir = autodetect_merged_dir(repo)
        if merged_dir:
            print(f"[info] auto-detected merged dir: {merged_dir}", file=sys.stderr)
        else:
            print("[info] no merged release found; post-merge entries will show as missing",
                  file=sys.stderr)

    ops = build_catalog(merged_dir, transformed_dir)
    statuses = {op.name: evaluate(op, repo) for op in ops}
    report = render(ops, statuses, repo, merged_dir, transformed_dir)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = repo / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"[ok] wrote {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
