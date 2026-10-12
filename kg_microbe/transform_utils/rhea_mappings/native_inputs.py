"""Read a coherent, hash-pinned local Rhea snapshot without implicit cache downloads."""

import json
import re
from pathlib import Path

from kg_microbe.transform_utils.rhea_mappings.native_rdf import load_native_rdf
from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
    load_reaction_families,
    validate_family_cohort,
)

POLICY_PATH = Path(__file__).resolve().parents[3] / "mappings" / "rhea_release.json"
NATIVE_FILES = {
    "rhea_directions": "rhea-directions.tsv",
    "rhea_rdf": "rhea.rdf.gz",
}
REQUIRED_INPUTS = ("rhea_release_manifest", *NATIVE_FILES)


def _unique_json_keys(pairs):
    """Reject conflicting or duplicated contract fields rather than keeping the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate Rhea release contract key: {key}")
        result[key] = value
    return result


def read_release_policy(stream):
    """Validate the finite two-file pin contract, never selecting paths from input JSON."""
    policy = json.load(stream, object_pairs_hook=_unique_json_keys)
    if not isinstance(policy, dict) or type(policy.get("schema_version")) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported Rhea release pin contract")
    if not isinstance(policy.get("snapshot_id"), str) or not policy["snapshot_id"].strip():
        raise ValueError("Missing Rhea snapshot identity")
    files = policy.get("files")
    if not isinstance(files, dict) or set(files) != set(NATIVE_FILES.values()):
        raise ValueError("Rhea release must pin exactly directions and RDF")
    for name, record in files.items():
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
            or type(record.get("bytes")) is not int
            or record["bytes"] <= 0
        ):
            raise ValueError(f"Malformed Rhea input identity: {name}")
    return policy


def _check_snapshot(transform, role, expected, reader):
    """Compare the actual immutable parser snapshot with its reviewed content pin."""
    snapshot = transform.consumed_input_snapshots[role]
    reader.buffer.seek(0, 2)
    size = reader.buffer.tell()
    reader.buffer.seek(0)
    if snapshot["sha256"] != expected["sha256"] or size != expected["bytes"]:
        raise ValueError(f"Rhea input does not match pinned snapshot: {role}")


def load_pinned_inputs(transform, *, policy_path=POLICY_PATH):
    """Read and cross-check all reaction families before any producer output is written."""
    with transform.consume_input("rhea_release_manifest", policy_path) as stream:
        policy = read_release_policy(stream)
    raw = transform.input_base_dir / "rhea"
    with transform.consume_input("rhea_directions", raw / NATIVE_FILES["rhea_directions"]) as stream:
        _check_snapshot(transform, "rhea_directions", policy["files"]["rhea-directions.tsv"], stream)
        families = load_reaction_families(stream)
    with transform.consume_input("rhea_rdf", raw / NATIVE_FILES["rhea_rdf"]) as stream:
        _check_snapshot(transform, "rhea_rdf", policy["files"]["rhea.rdf.gz"], stream)
        # consume_input owns an immutable byte snapshot. Read its binary buffer,
        # not its UTF-8 wrapper, because the selected source is gzip-compressed XML.
        native = load_native_rdf(stream.buffer, compressed=True)
        # Keep cross-file semantic checks inside the consumed-input context:
        # even a caller catching an inconsistency must not finalize that read.
        cohort = validate_family_cohort(families, native.reactions)
    return policy, families, native, cohort
