"""Verify the bounded native LPSN delta approved in #1852 (2026-11-14).

Inputs: preserved before/after directories from audit_lpsn_domain_edges_20261110.
Output: an exclusive JSON receipt proving only the four deposit predicate/relation
pairs changed; native nodes, API edges and source rows remain byte-identical.
This compares source-method canaries, not source finalization or release admission.
Each preserved artifact is checked against its own recorded native receipt before
comparison (#1861); the selected GSS CSV uses selection.json's selected_csv role.
Recorded absolute paths are provenance, so relocated evidence copies are supported.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

GSS_EDGES = "transformed/lpsn/edges.tsv"
GSS_NODES = "transformed/lpsn/nodes.tsv"
API_RECORD_REPORT = "transformed/lpsn_api/lpsn_api_records.tsv"
REQUIRED_OUTPUTS = {GSS_EDGES, GSS_NODES, "transformed/lpsn_api/nodes.tsv", "transformed/lpsn_api/edges.tsv"}


def identity(path):
    """Bind a finite canary artifact while streaming its bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def table(path):
    """Read the bounded eight-row native GSS edge table, preserving every cell."""
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    if not fields or len(rows) != 8 or any(None in row or None in row.values() for row in rows):
        raise ValueError("Expected the complete bounded eight-row GSS edge table")
    return fields, rows


def _check_binding(binding, actual, role, *, require_bytes=False):
    """Require the recorded digest, and recorded size when supplied, to match local bytes."""
    if not isinstance(binding, dict) or binding.get("sha256") != actual["sha256"]:
        raise ValueError(f"Missing or mismatched SHA256 binding: {role}")
    if (require_bytes or "bytes" in binding) and binding.get("bytes") != actual["bytes"]:
        raise ValueError(f"Missing or mismatched byte-count binding: {role}")


def _validate_canary(directory):
    """Bind local outputs and selected sources without opening historical absolute paths."""
    artifacts = {}

    def local(relative):
        """Read only canonical relative paths inside this preserved canary directory."""
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise ValueError(f"Invalid canary-relative path: {relative}")
        target = directory / path
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"Artifact escapes its canary directory: {relative}")
        if relative not in artifacts:
            artifacts[relative] = identity(target)
        return artifacts[relative]

    local("receipt.json")
    receipt = json.loads((directory / "receipt.json").read_text())
    if receipt.get("status") != "pass_bounded_native_lpsn_edges":
        raise ValueError("Both native canaries must have completed successfully")
    outputs = receipt.get("outputs", {})
    actual_outputs = {path.relative_to(directory).as_posix() for path in (directory / "transformed").rglob("*.tsv")}
    if not isinstance(outputs, dict) or not REQUIRED_OUTPUTS <= outputs.keys() or set(outputs) != actual_outputs:
        raise ValueError("Native output membership or receipt hash bindings are incomplete")
    for relative, binding in outputs.items():
        _check_binding(binding, local(relative), f"outputs/{relative}", require_bytes=True)

    contract = receipt.get("native_contract", {})
    records = contract.get("records", {})
    if contract.get("version") != 2 or not records or any(not key.isascii() or not key.isdecimal() for key in records):
        raise ValueError("Missing or invalid native API record contract")
    cache_names = {path.name for path in (directory / "raw/lpsn/api_cache").glob("*.json")}
    if cache_names != {f"{key}.json" for key in records}:
        raise ValueError("Native API cache membership differs from its receipt")
    consumed = receipt.get("consumed_inputs", {})
    expected_roles = {"lpsn_api_gss_nodes", "lpsn_api_gss_edges"} | {f"lpsn_api_record_{key}" for key in records}
    if set(consumed) != expected_roles:
        raise ValueError("Missing or unexpected consumed-input hash bindings")
    for role, relative, key in (
        ("lpsn_api_gss_nodes", GSS_NODES, "gss"),
        ("lpsn_api_gss_edges", GSS_EDGES, "gss_edges"),
    ):
        _check_binding(contract.get(key), local(relative), f"native_contract/{key}")
        _check_binding(consumed[role], local(relative), f"consumed_inputs/{role}")

    originals = receipt.get("original_inputs")
    if not isinstance(originals, dict) or not originals:
        raise ValueError("Missing original-input hash bindings")
    for key, binding in records.items():
        relative = f"raw/lpsn/api_cache/{key}.json"
        actual = local(relative)
        if binding.get("state") != "present":
            raise ValueError(f"Native API cache record was not present: {key}")
        _check_binding(binding, actual, f"native_contract/records/{key}")
        role = f"lpsn_api_record_{key}"
        _check_binding(consumed[role], actual, f"consumed_inputs/{role}")
        # Original cache roots can differ by host; the native numeric record
        # filename identifies its input role, never an absolute path to reopen.
        source_bindings = [value for path, value in originals.items() if Path(path).name == f"{key}.json"]
        if len(source_bindings) != 1:
            raise ValueError(f"Missing or ambiguous original cache binding: {key}")
        _check_binding(source_bindings[0], actual, f"original_inputs/cache/{key}", require_bytes=True)

    local("selection.json")
    selection = json.loads((directory / "selection.json").read_text())
    if selection.get("original_inputs") != originals:
        raise ValueError("Selection and receipt disagree on original input bindings")
    _check_binding(
        selection.get("selected_csv"), local("raw/lpsn_gss.csv"), "selection/selected_csv", require_bytes=True
    )
    with (directory / "raw/lpsn_gss.csv").open(newline="") as stream:
        selected_rows = list(csv.DictReader(stream))
    if selected_rows != selection.get("gss_complete_rows") or len(selected_rows) != receipt.get("gss_rows"):
        raise ValueError("Selected GSS rows differ from their recorded selection")
    return {"artifacts": artifacts, "outputs": set(outputs), "cache_names": cache_names}


def compare(before, after):
    """Reject any delta beyond the explicit native deposit modeling decision."""
    verified = [_validate_canary(directory) for directory in (before, after)]
    if verified[0]["outputs"] != verified[1]["outputs"] or verified[0]["cache_names"] != verified[1]["cache_names"]:
        raise ValueError("Native output or API cache membership changed")
    # The API report legitimately records different run paths and GSS-edge
    # hashes. Its bytes are bound to each own receipt, not asserted identical.
    identical = ["raw/lpsn_gss.csv", *sorted(verified[0]["outputs"] - {GSS_EDGES, API_RECORD_REPORT})]
    identical.extend(f"raw/lpsn/api_cache/{name}" for name in sorted(verified[0]["cache_names"]))
    unchanged = []
    for relative in identical:
        old, new = identity(before / relative), identity(after / relative)
        if (old["bytes"], old["sha256"]) != (new["bytes"], new["sha256"]):
            raise ValueError(f"Unexpected source/node/API delta: {relative}")
        unchanged.append({"relative_path": relative, "before": old, "after": new})
    old_path, new_path = (directory / GSS_EDGES for directory in (before, after))
    old_fields, old_rows = table(old_path)
    new_fields, new_rows = table(new_path)
    if old_fields != new_fields:
        raise ValueError("Native GSS edge columns changed")
    expected_pairs = {
        ("kgmicrobe.strain:JCM-33998", "lpsn:18880"),
        ("kgmicrobe.strain:KCTC-25006", "lpsn:18880"),
        ("kgmicrobe.strain:LMG-31064", "lpsn:10674"),
        ("kgmicrobe.strain:LMG-31064", "lpsn:5244"),
    }
    changed = []
    for row in old_rows:
        if row["subject"].startswith("kgmicrobe.strain:"):
            if (row["predicate"], row["relation"]) != ("biolink:in_taxon", "RO:0002162"):
                raise ValueError("Unexpected historical deposit predicate/relation")
            changed.append((row["subject"], row["object"]))
            row["predicate"], row["relation"] = "biolink:subclass_of", "rdfs:subClassOf"
    if len(changed) != 4 or set(changed) != expected_pairs:
        raise ValueError("The four independent historical/current-name deposit controls changed")
    if Counter(tuple(row[field] for field in old_fields) for row in old_rows) != Counter(
        tuple(row[field] for field in new_fields) for row in new_rows
    ):
        raise ValueError("Native GSS output changed beyond the approved predicate/relation pairs")
    for directory, evidence in zip((before, after), verified, strict=True):
        for relative, recorded in evidence["artifacts"].items():
            if identity(directory / relative) != recorded:
                raise ValueError(f"Canary artifact changed during comparison: {relative}")
    return {
        "status": "pass_exact_lpsn_1852_delta",
        "changed_deposit_edges": 4,
        "changed_columns": ["predicate", "relation"],
        "deposit_endpoints": sorted(expected_pairs),
        "gss_edges": {"before": identity(old_path), "after": identity(new_path)},
        "unchanged": unchanged,
        "canary_receipts": [evidence["artifacts"]["receipt.json"] for evidence in verified],
        "canary_selections": [evidence["artifacts"]["selection.json"] for evidence in verified],
        "receipt_bound_artifacts": [evidence["artifacts"] for evidence in verified],
        "external_receipt_authenticity_claimed": False,
        "helper": identity(Path(__file__).resolve()),
        "strict_biolink_domain_conformance_claimed": False,
        "source_finalization_or_release_admission_claimed": False,
    }


def main():
    """Compare one preserved native pair and save a new receipt without overwriting evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.before.resolve(), args.after.resolve())
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "changed_deposit_edges": 4}))


if __name__ == "__main__":
    main()
