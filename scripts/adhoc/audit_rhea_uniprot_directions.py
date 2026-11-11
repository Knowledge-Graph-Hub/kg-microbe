#!/usr/bin/env python3
"""
Audit explicit local Rhea-UniProt mappings against pinned reaction directions.

Purpose: extract a conservative reader from legacy uniprot&metanetx without
its inferred master links, network calls, or identity rewrites. Date: 2026-10-13.
Inputs: four-column mapping TSV, expected SHA-256, directions TSV, release policy.
Outputs: associations.tsv and manifest.json in a new audit directory.
PR: direction-aware Rhea-UniProt legacy-branch extraction; not production admission.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

HEADER = ("RHEA_ID", "DIRECTION", "MASTER_ID", "ID")
NUMBER = re.compile(r"[1-9][0-9]*\Z")
PROTEIN_TOKEN = re.compile(r"[A-Z0-9]+(?:-[1-9][0-9]*)?\Z")


def file_identity(path):
    """Hash a regular local source using bounded reads and retain its size."""
    if not path.is_file():
        raise ValueError(f"Not a regular input file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def file_signature(path):
    """Detect file replacement or restored-byte writes during the audit."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def mapping_rows(stream):
    """Yield every exact source row; never skip a headerless first observation."""
    reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE, strict=True)
    try:
        if tuple(next(reader, ())) != HEADER:
            raise ValueError("Expected exact RHEA_ID, DIRECTION, MASTER_ID, ID TSV header")
        for row in reader:
            if len(row) != 4:
                raise ValueError(f"Mapping line {reader.line_num}: expected exactly four cells")
            reaction, direction, master, protein = row
            if not NUMBER.fullmatch(reaction) or not NUMBER.fullmatch(master):
                raise ValueError(f"Mapping line {reader.line_num}: noncanonical numeric reaction ID")
            if direction not in {"UN", "LR", "RL", "BI"}:
                raise ValueError(f"Mapping line {reader.line_num}: unsupported direction")
            if not PROTEIN_TOKEN.fullmatch(protein):
                raise ValueError(
                    f"Mapping line {reader.line_num}: expected a single untrimmed protein identifier token"
                )
            yield reader.line_num, dict(zip(HEADER, row, strict=True))
    except csv.Error as error:
        raise ValueError(f"Malformed mapping TSV near line {reader.line_num}") from error


def publish_directory(staging, destination):
    """Publish into an owned empty reservation, preserving other writers and original failures."""
    destination.mkdir()
    reserved = destination.lstat()

    def owned():
        """Recognize this process's reservation without following substituted symlinks."""
        current = destination.lstat()
        return (current.st_dev, current.st_ino, current.st_mode) == (reserved.st_dev, reserved.st_ino, reserved.st_mode)

    try:
        if not owned() or any(destination.iterdir()):
            raise ValueError("Output reservation changed; refusing to replace it")
        os.replace(staging, destination)
    except BaseException:
        try:
            if owned():
                destination.rmdir()  # Only our still-empty reservation, never another writer's content.
        except OSError:
            pass  # Cleanup must not mask the publication exception or remove populated directories.
        raise


def audit_mapping(mapping, mapping_sha256, directions, release_policy, output):
    """Publish source-preserving associations only after family and snapshot checks."""
    # Reuse current native contracts, with no ontology adapters or cache selectors.
    # Keep these imports local so argument help is dependency-free.
    from kg_microbe.transform_utils.constants import RHEA_NEW_PREFIX
    from kg_microbe.transform_utils.rhea_mappings.native_inputs import read_release_policy
    from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
        DIRECTIONS_HEADER,
        RHEA_DIRECTION_FIELD,
        RHEA_MASTER_FIELD,
        load_reaction_families,
    )

    if not isinstance(mapping_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", mapping_sha256):
        raise ValueError("An explicit lowercase mapping SHA-256 is required")
    paths = [Path(path).resolve(strict=True) for path in (mapping, directions, release_policy)]
    mapping, directions, release_policy = paths
    if len(set(paths)) != 3:
        raise ValueError("Mapping, directions and policy must be distinct files")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if any(output.resolve() == path or output.resolve() in path.parents for path in paths):
        raise ValueError("Audit destination must not contain an input")
    signatures = [file_signature(path) for path in paths]
    identities = [file_identity(path) for path in paths]
    if identities[0]["sha256"] != mapping_sha256:
        raise ValueError("Mapping does not match the explicitly selected SHA-256")
    with release_policy.open(encoding="utf-8") as stream:
        policy = read_release_policy(stream)
    expected = policy["files"]["rhea-directions.tsv"]
    if any(identities[1][key] != expected[key] for key in ("sha256", "bytes")):
        raise ValueError("Directions do not match the selected release policy")
    with directions.open(encoding="utf-8", newline="") as stream:
        families = load_reaction_families(stream)
    index = {
        member: (family, direction, line)
        for line, family in enumerate(families, 2)
        for member, direction in family.members
    }
    fields = (
        "source_line",
        "rhea_id",
        RHEA_DIRECTION_FIELD,
        RHEA_MASTER_FIELD,
        "protein_identifier",
        "source_row_json",
        "directions_line",
        "family_row_json",
    )
    counts = Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rhea-uniprot-", dir=output.parent) as temporary:
        report = Path(temporary) / "report"
        report.mkdir()
        with (
            mapping.open(encoding="utf-8", newline="") as source,
            (report / "associations.tsv").open("w", encoding="utf-8", newline="") as target,
        ):
            writer = csv.DictWriter(target, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for line, original in mapping_rows(source):
                reaction = RHEA_NEW_PREFIX + original["RHEA_ID"]
                master = RHEA_NEW_PREFIX + original["MASTER_ID"]
                if reaction not in index:
                    raise ValueError(f"Mapping line {line}: reaction is absent from the selected directions table")
                family, direction, family_line = index[reaction]
                if master != family.master or original["DIRECTION"] != direction:
                    raise ValueError(f"Mapping line {line}: direction or master contradicts the selected family")
                native_family = dict(
                    zip(
                        DIRECTIONS_HEADER,
                        [member[len(RHEA_NEW_PREFIX) :] for member, _ in family.members],
                        strict=True,
                    )
                )
                writer.writerow(
                    {
                        "source_line": line,
                        "rhea_id": reaction,
                        RHEA_DIRECTION_FIELD: direction,
                        RHEA_MASTER_FIELD: master,
                        "protein_identifier": original["ID"],
                        "source_row_json": json.dumps(original, sort_keys=True, separators=(",", ":")),
                        "directions_line": family_line,
                        "family_row_json": json.dumps(native_family, sort_keys=True, separators=(",", ":")),
                    }
                )
                counts[direction] += 1
        if [file_identity(path) for path in paths] != identities or [
            file_signature(path) for path in paths
        ] != signatures:
            raise ValueError("Input changed during the audit; no report published")
        manifest = {
            "format": "rhea-uniprot-direction-audit-v1",
            "inputs": dict(zip(("mapping", "directions", "release_policy"), identities, strict=True)),
            "selected_policy_snapshot_id": policy["snapshot_id"],
            "mapping_expected_sha256": mapping_sha256,
            "rows": sum(counts.values()),
            "rows_by_direction": {direction: counts[direction] for direction in ("UN", "LR", "RL", "BI")},
            "directions_families": len(families),
            "production_admission": False,
            "mapping_release_provenance_verified": False,
            "interpretation": (
                "Only four-column source associations and selected directions-table compatibility are checked. "
                "The auxiliary mapping is not admitted by the two-file native Rhea release policy. "
                "No extra master mapping, catalytic assertion, organism scope, UniProt existence, "
                "RDF status or physiological flux is inferred. Duplicate rows remain separate observations."
            ),
        }
        (report / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        publish_directory(report, output)
    return manifest


def main(argv=None):
    """Read explicit local evidence only; do not resolve latest snapshots or network resources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--mapping-sha256", required=True)
    parser.add_argument("--directions", required=True, type=Path)
    parser.add_argument("--release-policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = audit_mapping(args.mapping, args.mapping_sha256, args.directions, args.release_policy, args.output)
    print(json.dumps(manifest, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
