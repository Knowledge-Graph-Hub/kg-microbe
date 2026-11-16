#!/usr/bin/env python3
"""
2026-11-16: inspect named local inputs before considering a whole dependency rebuild.

Read-only metadata inventory, independent of ignore rules, without traversing
raw-data directories. Sizes are retained-file observations, not peak-space or
runtime guarantees. This never builds databases or contacts upstream providers.
"""

import argparse
import ast
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def identity(path):
    """Observe one named path, including ignored files and symlink resolution."""
    if not path.exists():
        return {"path": str(path), "present": False}
    status = path.stat()
    return {
        "path": str(path),
        "present": True,
        "resolved": str(path.resolve()),
        "bytes": status.st_size,
        "mtime_ns": status.st_mtime_ns,
        "is_symlink": path.is_symlink(),
        "is_file": path.is_file(),
    }


def main():
    """Report the producer's finite named ontology set and additional BacDive authorities."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "kg_microbe/transform_utils/ontologies/ontologies_transform.py"
    selected = next(
        ast.literal_eval(node.value)
        for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ONTOLOGIES_MAP" for target in node.targets)
    )
    raw = args.input_root / "data/raw"
    names = set(selected.values())
    for ontology in selected:
        names.update((f"{ontology}.json", f"{ontology}.owl"))
    names.add("ncbitaxon_removed_subset.json")
    for ontology in ("ncbitaxon", "chebi", "go", "ec", "ncit"):
        names.update((f"{ontology}.db", f"{ontology}.db.toolchain.json"))
    names.update(
        (
            "po.owl",
            "micro.owl",
            "taxdump.tar.gz",
            "mesh2026.nt.gz",
            "bacdive_strains.json",
            "assay_kits_simple.json",
            "lpsn_gss.csv",
            "metpo_sheet.tsv",
            "metpo-properties.tsv",
            "biolink-model.yaml",
            "attributes.yaml",
            "predicate_mapping.yaml",
            "robot",
            "robot.jar",
        "exclusion_branches.tsv",
        )
    )
    raw_files = [identity(raw / name) for name in sorted(names)]
    transformed = [
        identity(args.input_root / "data/transformed/ontologies" / f"{ontology}_{kind}.tsv")
        for ontology in selected
        for kind in ("nodes", "edges")
    ]
    transformed.extend(
        identity(args.input_root / "data/transformed" / name / member)
        for name in ("ontologies", "bacdive", "bactotraits")
        for member in ("source_finalization.json", "source_fingerprint.json")
    )
    bacdive_cache = [
        identity(args.input_root / "kg_microbe/transform_utils/bacdive/tmp" / name)
        for name in ("bacdive.tsv", "bacdive_mappings.tsv")
    ]
    tools = {name: shutil.which(name) for name in ("semsql", "rdftab", "relation-graph", "java")}
    java = tools["java"]
    if java:
        result = subprocess.run(  # noqa: S603 -- PATH-resolved Java, fixed read-only version probe.
            [java, "-version"], capture_output=True, text=True, check=False, timeout=30
        )
        tools["java_probe"] = {"returncode": result.returncode, "output": (result.stderr or result.stdout).strip()}
    go_record = raw / "go.db.toolchain.json"
    usage = shutil.disk_usage(root)
    result = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "raw_root": str(raw),
        "named_inventory_includes_ignored_files": True,
        "directory_traversal": False,
        "ontology_source_names": selected,
        "raw_files": raw_files,
        "transformed_files": transformed,
        "bacdive_cache": bacdive_cache,
        "tools_on_actual_path": tools,
        "go_record": json.loads(go_record.read_text()) if go_record.is_file() else None,
        "existing_named_raw_file_bytes": sum(item.get("bytes", 0) for item in raw_files),
        "existing_named_transformed_file_bytes": sum(item.get("bytes", 0) for item in transformed),
        "disk_free_bytes": usage.free,
        "scope": "Named retained artifacts only; not full input validity, peak resource sizing or producer freshness.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
