"""
Check an explicitly selected final native bundle in a fresh private directory.

This command never constructs scientific reviews or grants installation, medium
presence, graph-release or publication authority. Run it only after the upstream
owner supplies the actual certified products and selected evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json
from kg_microbe.utils.stable_source_candidate import StableSourceCandidate, _git, _head, _require, _Snapshots


def _write(path, value):
    """Create immutable evidence without overwriting a previous execution."""
    with path.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")


def checked_code(expected_head):
    """Bind the imported consumer to this clean committed checkout."""
    import kg_microbe

    root = Path(__file__).resolve().parents[1]
    _require(re.fullmatch(r"[0-9a-f]{40}", expected_head), "select a full consumer commit")
    _require(Path(kg_microbe.__file__).resolve() == root / "kg_microbe/__init__.py", "consumer module origin differs")
    _require(_head(root) == expected_head, "consumer revision differs")
    _require(not _git(root, "status", "--porcelain", "--untracked-files=no").strip(), "consumer tracked tree is dirty")
    return root


def _output(candidate, integration_path, integration_sha256, output):
    """Refuse aliases and writes inside any selected source or producer checkout."""
    output = Path(output).absolute()
    _require(not output.exists() and not output.is_symlink(), "canary output must be new")
    _require(output == output.resolve() and not any(p.is_symlink() for p in output.parents), "aliased canary output")
    raw = Path(integration_path).read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == integration_sha256, "canary integration selection changed")
    integration = read_json(raw)
    roots = [candidate.root, candidate.producer, Path(integration["current_kgm"]["root"])]
    protected = set()
    output_parts = tuple(part.casefold() for part in output.parts)
    for root in roots:
        root = root.resolve()
        parts = tuple(part.casefold() for part in root.parts)
        _require(output_parts[: len(parts)] != parts, "canary output overlaps selected checkout")
        identity = root.stat()
        protected.add((identity.st_dev, identity.st_ino))
    for ancestor in output.parents:
        if ancestor.exists():
            identity = ancestor.stat()
            _require(
                (identity.st_dev, identity.st_ino) not in protected,
                "canary output physically overlaps selected checkout",
            )
    return output


def _graph(candidate, output, snapshots):
    """Round-trip the complete candidate projection through literal TSVs and archive."""
    from kg_microbe.merge_utils.artifact_manifest import file_identity, write_graph_archive
    from kg_microbe.utils.graph_schema import canonical_header, validate_canonical_tsv
    from kg_microbe.utils.tsv_io import tsv_dict_writer

    projected = candidate.graph_rows()
    paths = [output / "nodes.tsv", output / "edges.tsv"]
    for rows, path, is_node in zip(projected, paths, (True, False), strict=True):
        columns = {key for row in rows for key in row}
        with path.open("x", encoding="utf-8", newline="") as stream:
            writer = tsv_dict_writer(
                stream, fieldnames=canonical_header(columns, is_node), quoting=csv.QUOTE_NONE, quotechar=None
            )
            writer.writeheader()
            writer.writerows(rows)
        _require(validate_canonical_tsv(path, is_node=is_node) == len(rows), "serialized candidate row count differs")
    identities = {path.name: file_identity(path) for path in paths}
    for path in paths:
        snapshots.add(path, identities[path.name]["sha256"])
    provenance = {
        "mode": "isolated_candidate_projection",
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "production_authorized": False,
        "source_manifest_sha256": candidate.selection["source_output"]["manifest_sha256"],
        "selection_sha256": candidate.fingerprint,
    }
    archive_path = output / "candidate-projection.tar.gz"
    write_graph_archive(archive_path, paths, provenance, expected_members=identities)
    archive_identity = file_identity(archive_path)
    snapshots.add(archive_path, archive_identity["sha256"])
    roundtrip = []
    with tarfile.open(archive_path) as archive:
        _require(set(archive.getnames()) == {"manifest.json", "nodes.tsv", "edges.tsv"}, "archive inventory differs")
        manifest = json.load(archive.extractfile("manifest.json"))
        _require(manifest["members"] == identities and manifest["provenance"] == provenance, "archive manifest differs")
        for path in paths:
            raw = archive.extractfile(path.name).read()
            _require(hashlib.sha256(raw).hexdigest() == identities[path.name]["sha256"], "archive bytes differ")
            roundtrip.append(list(csv.DictReader(io.StringIO(raw.decode()), delimiter="\t", quoting=csv.QUOTE_NONE)))
    candidate.verify_graph_rows(*roundtrip)
    snapshots.verify()
    return {"members": identities, "archive": archive_identity, "nodes": len(projected[0]), "edges": len(projected[1])}


def _persisted(output, pin, snapshots):
    """Keep every exported product current after the reload's own bounded check."""
    manifest = read_json(snapshots.add(output / "manifest.json", pin))
    snapshots.directory(output, {"manifest.json", *manifest["files"]})
    for name, digest in manifest["files"].items():
        snapshots.add(output / name, digest)
    snapshots.verify()


def check_bundle(candidate, *, integration_path, integration_sha256, output):
    """Require final admission, persistence, explicit re-admission and projection parity."""
    admitted = candidate.verify_final_combined(integration_path, selection_sha256=integration_sha256)
    output = _output(candidate, integration_path, integration_sha256, output)
    # Export performs the native input overlap/currentness checks before creating
    # this new directory. No scientific source or product is rewritten.
    pin = candidate.export_candidate(output / "candidate")
    snapshots = _Snapshots()
    _persisted(output / "candidate", pin, snapshots)
    loaded = StableSourceCandidate.reload(output / "candidate", manifest_sha256=pin)
    repeated = loaded.verify_final_combined(integration_path, selection_sha256=integration_sha256)
    _require(admitted == repeated and candidate.payload() == loaded.payload(), "reloaded final admission differs")
    graph = _graph(loaded, output, snapshots)
    candidate.verify_current()
    loaded.verify_current()
    result = {
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "production_authorized": False,
        "medium_presence_authorized": False,
        "release_authorized": False,
        "selection_sha256": candidate.fingerprint,
        "integration_selection_sha256": integration_sha256,
        "persisted_candidate_manifest_sha256": pin,
        "admission": repeated,
        "native_execution": candidate.native_execution,
        "reload_native_execution": loaded.native_execution,
        "graph_projection": graph,
        "semantic_audit": loaded.audit(),
    }
    snapshots.verify()
    _write(output / "canary-result.json", result)
    snapshots.add(output / "canary-result.json", hashlib.sha256(canonical_json(result) + b"\n").hexdigest())
    snapshots.verify()
    return result


def main():
    """Run only the explicit selected canary, preserving failures without repairing inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--integration-selection", type=Path, required=True)
    parser.add_argument("--integration-sha256", required=True)
    parser.add_argument("--consumer-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = checked_code(args.consumer_head)
    candidate = StableSourceCandidate(args.selection, selection_sha256=args.selection_sha256)
    result = check_bundle(
        candidate,
        integration_path=args.integration_selection,
        integration_sha256=args.integration_sha256,
        output=args.output,
    )
    checked_code(args.consumer_head)
    _write(args.output / "consumer-code.json", {"root": str(root), "head": args.consumer_head})
    print(
        json.dumps({"status": result["status"], "output": str(args.output.absolute()), "production_authorized": False})
    )


if __name__ == "__main__":
    main()
