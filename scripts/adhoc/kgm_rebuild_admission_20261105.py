#!/usr/bin/env python3
"""
Plan and admit the isolated 2026-11-05 rebuild without changing production evidence.

Inputs: canonical merge.yaml, registered dependency declarations, staged raw inputs,
finalized transform bundles, and the merged archive. Outputs: JSON on stdout and,
when requested, a new receipt under data/rebuild-evidence/20261105. This helper
never runs producers, rewrites completion markers, or accepts diagnostic bypasses.
The production freshness gate and artifact inspector remain the admission authorities.
"""

import argparse
import csv
import io
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("data/rebuild-evidence/20261105")
ONTOLOGIES = frozenset("ncbitaxon chebi envo go ec upa mondo hp metpo uberon foodon pato ro taxrank".split())
EXCLUDED = frozenset({"kegg", "cog", "bakta"})


def require(condition, message):
    """Fail closed with a concrete missing or contradictory item."""
    if not condition:
        raise ValueError(message)


def resolve(root, value):
    """Resolve an explicit locator relative to the selected checkout."""
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def read_config(path):
    """Read a merge configuration through the production semantic contract."""
    import yaml

    from kg_microbe.merge_utils.merge_contract import validate_merge_semantics

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_merge_semantics(config)
    require(not config.get("configuration", {}).get("allow_unfinalized_sources"), "Diagnostic merge bypass refused")
    return config


def normalized_config(config):
    """Remove only permitted runtime publication and source path relocations."""
    result = json.loads(json.dumps(config))
    result["configuration"]["output_directory"] = "<output>"
    for source in result["merged_graph"]["source"].values():
        files = source["input"]["filename"]
        require(isinstance(files, list), "Configured input filenames must be a list")
        source["input"]["filename"] = [f"{Path(name).parent.name}/{Path(name).name}" for name in files]
    for operation in result["merged_graph"].get("operations", []):
        operation["args"]["filename"] = "<stats>"
    return result


def build_plan(root, raw, transformed, config_path, merged):
    """Resolve the standard graph and its complete dependency closure from current code."""
    import kg_microbe.transform as dispatcher
    from scripts.transform_phases import plan

    config = read_config(config_path)
    canonical = read_config(root / "merge.yaml")
    require(normalized_config(config) == normalized_config(canonical), "Merge config changes canonical graph scope")
    require(set(dispatcher._ontology_map()) == ONTOLOGIES, "Whole-ontology inventory changed; review the rebuild plan")
    selected, files = set(), {}
    for name, source in config["merged_graph"]["source"].items():
        paths = [resolve(root, value) for value in source["input"]["filename"]]
        require(bool(paths), f"No configured graph members: {name}")
        for path in paths:
            require(
                path.is_relative_to(transformed), f"Configured input outside selected transformed directory: {path}"
            )
            require(path.parent.parent == transformed, f"Unexpected source output layout: {path}")
        producer = paths[0].parent.name
        require(all(path.parent.name == producer for path in paths), f"Mixed producer directories: {name}")
        producer = "prego" if producer == "prego_habitat" else producer
        require(producer in dispatcher.DATA_SOURCES, f"Unregistered configured producer: {producer}")
        selected.add(producer)
        files.setdefault(producer, []).extend(str(path) for path in paths)
    pending = list(selected)
    while pending:
        producer = pending.pop()
        cls = dispatcher.DATA_SOURCES[producer].transform_class
        for upstream in cls.TRANSFORM_INPUTS:
            require(upstream in dispatcher.DATA_SOURCES, f"Unregistered dependency: {upstream}")
            if upstream not in selected:
                selected.add(upstream)
                pending.append(upstream)
    require(not selected & EXCLUDED, f"Excluded producers selected: {sorted(selected & EXCLUDED)}")
    require("prego" in selected, "Standard habitat PREGO source missing")
    for name, default in {
        "PREGO_SHAPES": "habitat",
        "PREGO_MIN_CONFIDENCE": "0",
        "PREGO_HABITAT_MIN_SCORE": "1.0",
    }.items():
        value = os.environ.get(name, default)
        valid = value == default if name == "PREGO_SHAPES" else float(value) == float(default)
        require(valid, f"{name}={value!r} changes the approved PREGO scope")
    require(
        os.environ.get("GOLD_APPLY_TAXON_TRIM", "true").lower() not in {"false", "0", "no"},
        "Microbial GOLD trim disabled",
    )
    phases, skipped = plan(sorted(selected), input_dir=raw)
    require(not skipped, f"Configured sources cannot be skipped: {skipped}")
    require(phases and phases[0] == ["ontologies"], "First dependency phase must be the whole ontology canary")
    for producer in selected:
        if producer == "ontologies":
            files[producer] = [
                str(transformed / producer / f"{name}_{kind}.tsv")
                for name in sorted(ONTOLOGIES)
                for kind in ("nodes", "edges")
            ]
        elif producer not in files:
            directory = transformed / ("prego_habitat" if producer == "prego" else producer)
            files[producer] = [str(directory / name) for name in ("nodes.tsv", "edges.tsv")]
    configured_output = Path(config["configuration"]["output_directory"])
    output = (
        configured_output if configured_output.is_absolute() else config_path.parent / configured_output
    ).resolve()
    require(output == merged, f"Configured output {output} differs from selected merged directory {merged}")
    return {
        "phases": phases,
        "sources": files,
        "excluded": sorted(EXCLUDED),
        "merge_config": str(config_path),
        "raw_directory": str(raw),
        "transformed_directory": str(transformed),
        "merged_directory": str(merged),
    }


def verify_sources(plan, sources):
    """Require current whole-source evidence through the production read-only admission API."""
    from kg_microbe.merge_utils.artifact_manifest import file_identity
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness
    from kg_microbe.utils.source_finalization import FINALIZATION_FILE
    from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

    paths = [Path(name) for source in sources for name in plan["sources"][source]]
    admission = verify_source_freshness(paths)
    result = {}
    for source in sources:
        source_paths = [Path(name) for name in plan["sources"][source]]
        directory = source_paths[0].parent
        report_path = directory / FINALIZATION_FILE
        report = admission.read_json(report_path)
        marker = directory / FINGERPRINT_FILE
        admission.read_json(marker)
        require(
            Path(report["raw_input_directory"]).resolve() == Path(plan["raw_directory"]),
            f"{source}: completion used another raw directory",
        )
        require(
            set(path.name for path in source_paths) <= set(report["members"]),
            f"{source}: whole-source completion omits expected graphs",
        )
        counts = {}
        for path in source_paths:
            identity = file_identity(path)
            require(identity["bytes"] > 0, f"Empty graph file: {path}")
            require(
                {key: identity[key] for key in ("bytes", "sha256")} == admission.capture(path),
                f"Graph changed while counting: {path}",
            )
            if source == "ontologies":
                require(identity["rows"] > 0, f"Ontology graph has no rows: {path}")
            counts[path.name] = identity
        authority = report.get("consumed_inputs", {}).get("ncbi_taxonomy_authority")
        if source == "ontologies":
            require(
                set(report["members"]) == set(counts) and len(counts) == 28,
                "Ontology completion must cover exactly 28 graphs",
            )
            require(authority is not None, "Ontology completion lacks NCBI authority evidence")
        if authority is not None:
            require(
                Path(authority["path"]).resolve() == Path(plan["raw_directory"]) / "taxdump.tar.gz",
                f"{source}: NCBI authority is outside selected raw inputs",
            )
        result[source] = {
            "graphs": counts,
            "finalization": admission.capture(report_path),
            "producer_marker": admission.capture(marker),
            "ncbi_authority": authority,
            "audits": report["audit_members"],
        }
    admission.verify()
    return {"sources": result, "admitted_file_count": len(admission.identities)}, admission


def table_rows(stream):
    """Read bounded audit records with literal TSV field semantics."""
    yield from csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)


def verify_merge(plan, config_path, root):
    """Verify persisted archive, provenance, counts and reports without rerunning publication."""
    import yaml

    from kg_microbe.merge_utils.artifact_manifest import MANIFEST_MEMBER, file_identity
    from kg_microbe.merge_utils.invariants import (
        STRAIN_PARENT_REPORT,
        STRAIN_PARENT_REPORT_HEADER,
        STUB_NODE_DETAILS_HEADER,
        STUB_NODE_DETAILS_REPORT,
        STUB_NODE_REPORT,
        STUB_NODE_REPORT_HEADER,
    )
    from kg_microbe.merge_utils.stats_provenance import git_commit, source_markers, stats_filename_from_config
    from kg_microbe.utils.postprocess_artifacts import MAX_METADATA_BYTES, inspect_artifact
    from kg_microbe.utils.transform_fingerprint import schema_fingerprint

    source_result, admission = verify_sources(plan, [source for phase in plan["phases"] for source in phase])
    config = read_config(config_path)
    config_identity = admission.capture(config_path)
    graph = config["merged_graph"]
    require(len(graph["destination"]) == 1, "Expected one standard graph destination")
    destination = next(iter(graph["destination"].values()))
    require(destination.get("compression") == "tar.gz", "Standard graph requires a tar.gz archive")
    base = destination["filename"]
    merged = Path(plan["merged_directory"])
    archive_path = merged / f"{base}.tar.gz"
    archive_identity = admission.capture(archive_path)
    artifact = inspect_artifact(archive_path)
    require(artifact.status == "ok", artifact.detail)
    require(artifact.archive_sha256 == archive_identity["sha256"], "Archive changed during inspection")
    for name in (f"{base}_nodes.tsv", f"{base}_edges.tsv"):
        require(artifact.members.get(name, {}).get("rows", 0) > 0, f"Missing/empty archive graph member: {name}")
    with tarfile.open(archive_path, "r:gz") as archive:
        with archive.extractfile(MANIFEST_MEMBER) as stream:
            payload = stream.read(MAX_METADATA_BYTES + 1)
            require(len(payload) <= MAX_METADATA_BYTES, "Manifest exceeds metadata limit")
            manifest = json.loads(payload)
        with archive.extractfile(f"{base}_reference_resolution.tsv") as stream:
            validation = list(table_rows(io.TextIOWrapper(stream, encoding="utf-8")))
    provenance = manifest.get("provenance", {})
    require(
        provenance.get("merge_config") == {"name": config_path.name, "sha256": config_identity["sha256"]},
        "Archive merge config identity differs",
    )
    require(
        provenance.get("source_finalization") == {"required": True, "diagnostic_opt_out": False},
        "Archive lacks production finalization admission",
    )
    require(
        provenance.get("repository_schema") == schema_fingerprint(root), "Archive schema differs from staged schema"
    )
    stats_path = resolve(root, stats_filename_from_config(config))
    require(
        provenance.get("commit") == git_commit(root, ignore=(stats_path,)),
        "Archive commit differs from current candidate",
    )
    markers = source_markers(config, root)
    require(provenance.get("configured_source_markers") == markers, "Archive source provenance differs")
    node_count = artifact.members[f"{base}_nodes.tsv"]["rows"]
    edge_count = artifact.members[f"{base}_edges.tsv"]["rows"]
    require(len(validation) == 1 and validation[0].get("status") == "pass", "Merged reference validation did not pass")
    require(
        int(validation[0]["nodes"]) == node_count and int(validation[0]["edges"]) == edge_count,
        "Merged validation counts disagree",
    )
    stats = yaml.safe_load(admission.capture(stats_path, retain=True))
    require(
        stats["node_stats"]["total_nodes"] == node_count and stats["edge_stats"]["total_edges"] == edge_count,
        "Stats counts disagree with verified archive",
    )
    require(sum(stats["edge_stats"]["count_by_raw_predicate"].values()) == edge_count, "Raw predicate counts disagree")
    stats_provenance = stats.get("provenance", {})
    require(
        stats_provenance.get("sources") == markers and stats_provenance.get("commit") == provenance["commit"],
        "Stats source/commit provenance differs",
    )
    require(resolve(root, stats_provenance.get("merge_config", "")) == config_path, "Stats names another merge config")
    require(
        resolve(root, stats_provenance.get("edges_archive", "")) == archive_path
        and stats_provenance.get("edges_archive_member") == f"{base}_edges.tsv",
        "Stats names another edges artifact",
    )
    reports = {}
    for name, header in (
        (STRAIN_PARENT_REPORT, STRAIN_PARENT_REPORT_HEADER),
        (STUB_NODE_REPORT, STUB_NODE_REPORT_HEADER),
        (STUB_NODE_DETAILS_REPORT, STUB_NODE_DETAILS_HEADER),
    ):
        path = merged / name
        identity = admission.capture(path)
        summary = file_identity(path)
        require({key: summary[key] for key in ("bytes", "sha256")} == identity, f"Report changed: {path}")
        if name == STRAIN_PARENT_REPORT:
            require(summary["rows"] == 0, "Merged strain-parent violations require review")
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            require(reader.fieldnames == header, f"Missing/malformed report header: {path}")
            if name != STRAIN_PARENT_REPORT:
                unexpected = sum(1 for row in reader if row.get("expected", "").lower() not in {"true", "yes", "1"})
                require(unexpected == 0, f"{path}: {unexpected} unexpected stub records require review")
        reports[name] = summary
    admission.verify()
    return {
        **source_result,
        "archive": {"path": str(archive_path), **archive_identity, "members": artifact.members},
        "provenance": provenance,
        "stats": {"path": str(stats_path), **admission.capture(stats_path)},
        "reports": reports,
    }


def write_receipt(path, root, result):
    """Create only a new task evidence receipt, refusing collisions or input overwrites."""
    path = resolve(root, path)
    require(path.is_relative_to(root / EVIDENCE), f"Receipt must be under {root / EVIDENCE}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv=None):
    """Run a read-only plan or gate and optionally retain its exact outcome as new evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "verify-ontologies", "verify-sources", "verify-merge"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--transformed-dir", type=Path, default=Path("data/transformed"))
    parser.add_argument("--merged-dir", type=Path, default=Path("data/merged"))
    parser.add_argument("--merge-config", type=Path, default=Path("merge.yaml"))
    parser.add_argument("--through-phase", type=int, help="verify phases 1 through N, including the ontology canary")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = {"command": args.command, "checked_at": datetime.now(timezone.utc).isoformat(), "root": str(root)}
    try:
        require(root == ROOT and Path.cwd().resolve() == root, "Run this helper from its own worktree root")
        sys.path.insert(0, str(root))
        import kg_microbe

        require(
            Path(kg_microbe.__file__).resolve().parent.parent == root, "KG modules resolve outside the owned worktree"
        )
        raw, transformed, merged, config_path = (
            resolve(root, value) for value in (args.raw_dir, args.transformed_dir, args.merged_dir, args.merge_config)
        )
        require(
            all(path.is_relative_to(root / "data") for path in (raw, transformed, merged)),
            "Rebuild directories must remain under owned worktree data/",
        )
        plan = build_plan(root, raw, transformed, config_path, merged)
        result["plan"] = plan
        require(
            args.through_phase is None or args.command == "verify-sources",
            "--through-phase applies only to verify-sources",
        )
        if args.command == "verify-ontologies":
            result["verification"], _ = verify_sources(plan, ["ontologies"])
        elif args.command == "verify-sources":
            through = args.through_phase if args.through_phase is not None else len(plan["phases"])
            require(1 <= through <= len(plan["phases"]), "--through-phase is outside the current plan")
            result["verification"], _ = verify_sources(
                plan, [source for phase in plan["phases"][:through] for source in phase]
            )
        elif args.command == "verify-merge":
            result["verification"] = verify_merge(plan, config_path, root)
        result["status"] = "planned" if args.command == "plan" else "pass"
    except Exception as error:  # noqa: BLE001 - preserve a failed gate as evidence, never admit it
        result.update(status="fail", error=f"{type(error).__name__}: {error}")
    if args.receipt:
        try:
            require(root == ROOT, "Receipt root must be this helper’s worktree")
            write_receipt(args.receipt, root, result)
        except (OSError, ValueError) as error:
            result.update(status="fail", receipt_error=f"{type(error).__name__}: {error}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(result["status"] == "fail")


if __name__ == "__main__":
    raise SystemExit(main())
