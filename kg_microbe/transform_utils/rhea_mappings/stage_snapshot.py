"""Explicitly stage a reviewed native Rhea pair; never repin or overwrite an existing snapshot."""

import argparse
import hashlib
import io
import json
import os
import stat
import tempfile
from pathlib import Path

from kg_microbe.transform_utils.rhea_mappings.native_graph import native_xrefs
from kg_microbe.transform_utils.rhea_mappings.native_inputs import NATIVE_FILES, POLICY_PATH, read_release_policy
from kg_microbe.transform_utils.rhea_mappings.native_rdf import RH, load_native_rdf
from kg_microbe.transform_utils.rhea_mappings.reaction_families import load_reaction_families, validate_family_cohort


def _identity(path):
    """Hash complete file bytes, returning the same finite identity as the reviewed policy."""
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _assert_pins(directory, policy):
    """Require both actual payloads to match, without treating a URL or directory name as proof."""
    for name in NATIVE_FILES.values():
        expected = {key: policy["files"][name][key] for key in ("sha256", "bytes")}
        if _identity(directory / name) != expected:
            raise ValueError(f"Rhea snapshot pin mismatch: {name}")


def _validate_pair(directory, policy):
    """Verify exact bytes and native cohort, direction, participant and selected cross-reference structure."""
    _assert_pins(directory, policy)
    with (directory / "rhea-directions.tsv").open(encoding="utf-8", newline="") as stream:
        families = load_reaction_families(stream)
    with (directory / "rhea.rdf.gz").open("rb") as stream:
        native = load_native_rdf(stream, compressed=True)
    cohort = validate_family_cohort(families, native.reactions)
    for family in families:
        for identifier, _ in family.members:
            tuple(native_xrefs(native.reactions[identifier]))
        for side in native.reactions[family.master][RH + "side"]:
            native.chemical_participants(side)
    _assert_pins(directory, policy)
    return cohort


def _copy_pinned(source, destination, expected):
    """Copy into an owned unpublished file, rejecting excess bytes and mismatches before publication."""
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            size += len(block)
            if size > expected["bytes"]:
                raise ValueError(f"Rhea snapshot pin mismatch: {source.name}")
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"Rhea snapshot pin mismatch: {source.name}")


def _refuse_linked_payloads(directory):
    """Certify an existing snapshot only by its own payload files, never links into another tree."""
    for name in NATIVE_FILES.values():
        try:
            mode = (directory / name).lstat().st_mode
        except FileNotFoundError:
            continue  # a partial destination is refused by _validate_pair
        if not stat.S_ISREG(mode):
            raise ValueError(f"Refusing a symlink or non-regular Rhea payload: {name}")


def _same_directory(path, identity):
    """Recognize only the empty reservation created by this invocation, not a replacement or symlink."""
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return (current.st_dev, current.st_ino, current.st_mode) == identity


def stage_snapshot(source_dir, input_dir, *, policy_path=POLICY_PATH):
    """
    Stage a complete local export under input_dir/rhea, or verify an identical existing snapshot.

    Sources may be an explicitly chosen local export or the rhea_download
    quarantine directory. This function never performs network requests and
    never changes the reviewed pin. Differing or partial existing destinations
    are refused, not repaired or removed. The brief exclusive empty reservation
    is replaced by the fully validated directory, never by one payload at a time.
    """
    source_dir, input_dir, policy_path = Path(source_dir), Path(input_dir), Path(policy_path)
    policy_bytes = policy_path.read_bytes()
    policy = read_release_policy(io.StringIO(policy_bytes.decode("utf-8")))
    destination = input_dir / "rhea"

    def result(disposition, cohort):
        """Report bounded acquisition evidence, not transform or release acceptance."""
        if policy_path.read_bytes() != policy_bytes:
            raise ValueError("Rhea policy changed during staging")
        return {
            "disposition": disposition,
            "source_directory": str(source_dir.resolve()) if disposition == "staged" else None,
            "destination_directory": str(destination.absolute()),
            "acquisition_method": "explicit_local_copy" if disposition == "staged" else "verified_existing",
            "snapshot_id": policy["snapshot_id"],
            "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
            "files": {name: {key: pin[key] for key in ("sha256", "bytes")} for name, pin in policy["files"].items()},
            "families": cohort["families"],
            "active_reactions": cohort["members"],
            "obsolete_reactions": len(cohort["obsolete_ids"]),
            "production_transform_run": False,
            "release_ready": False,
        }

    if destination.is_symlink():
        raise ValueError("Refusing a symlink Rhea destination; select a real input directory")
    if destination.exists():
        _refuse_linked_payloads(destination)
        return result("already_matching", _validate_pair(destination, policy))
    input_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rhea-stage-", dir=input_dir) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        for name in NATIVE_FILES.values():
            _copy_pinned(source_dir / name, staging / name, policy["files"][name])
        cohort = _validate_pair(staging, policy)
        receipt = result("staged", cohort)
        (staging / "snapshot_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        try:
            destination.mkdir()  # exclusive reservation: never overwrite a preexisting destination
        except FileExistsError:
            if destination.is_symlink():
                raise ValueError("Rhea destination became a symlink during staging") from None
            _refuse_linked_payloads(destination)
            return result("already_matching", _validate_pair(destination, policy))
        status = destination.lstat()
        identity = (status.st_dev, status.st_ino, status.st_mode)
        try:
            if not _same_directory(destination, identity) or any(destination.iterdir()):
                raise ValueError("Rhea destination reservation changed during staging")
            if policy_path.read_bytes() != policy_bytes:
                raise ValueError("Rhea policy changed during staging")
            os.replace(staging, destination)
        except BaseException:
            if _same_directory(destination, identity):
                try:
                    destination.rmdir()  # only our still-empty reservation; never recursive cleanup here
                except OSError:
                    pass
            raise
    return receipt


def main():
    """Provide an explicit offline staging command for hash-pinned acquisition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="Directory containing the exact reviewed pair")
    parser.add_argument(
        "--input-dir", type=Path, default=Path("data/raw"), help="Raw root; publishes its rhea child only"
    )
    args = parser.parse_args()
    print(json.dumps(stage_snapshot(args.source_dir, args.input_dir), indent=2))


if __name__ == "__main__":
    main()
