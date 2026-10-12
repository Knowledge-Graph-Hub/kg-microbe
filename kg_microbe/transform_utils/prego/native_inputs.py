"""Require PREGO's dynamic archive selection and actual parsed payload identities."""

import hashlib
import tarfile
from contextlib import nullcontext
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.prego.envo_identity import POLICY_FILE
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.source_finalization import SourceFinalizationRequired


def archive_paths(raw_dir):
    """Resolve the exact association archive inventory, excluding the optional dictionary."""
    return tuple(
        sorted(
            str(path.absolute())
            for path in (Path(raw_dir) / "prego").glob("*.tar.gz")
            if path.name != "prego_dictionary.tar.gz"
        )
    )


def archive_payload_identity(archive_path, *, destination=None):
    """Stream actual archive bytes to prove the exact member identity; receipts are not authority."""
    result = None
    output = atomic_write(destination, "wb") if destination is not None else nullcontext(None)
    with output as target, tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            if Path(member.name).name != "database_pairs.tsv":
                continue
            if result is not None or not member.isfile():
                raise SourceFinalizationRequired("PREGO archive requires exactly one regular database_pairs.tsv member")
            digest, size = hashlib.sha256(), 0
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
                    if target is not None:
                        target.write(block)
            if size != member.size:
                raise SourceFinalizationRequired("PREGO archive payload is truncated")
            result = {"member": member.name, "payload_sha256": digest.hexdigest(), "payload_bytes": size}
        if result is None:
            raise SourceFinalizationRequired("PREGO archive has no database_pairs.tsv member")
    return result


def verify_native_contract(contract, snapshots, raw_dir, *, admission=None, policy_path=POLICY_FILE):
    """Check every actual archive/payload read and keep selection in merge admission."""
    guard = admission if admission is not None else SourceAdmission()
    guard.verify(metadata_only=True)
    for role, path in (
        ("prego_envo_policy", Path(policy_path)),
        ("prego_native_envo", Path(raw_dir) / "envo.json"),
        ("prego_native_foodon", Path(raw_dir) / "foodon.json"),
    ):
        identity = guard.capture(path)
        if snapshots.get(role) != {"path": str(path.resolve()), "sha256": identity["sha256"]}:
            raise SourceFinalizationRequired(f"PREGO native authority locator changed: {role}")
    selected = guard.capture_resolution(archive_paths, raw_dir)
    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "raw_locator", "raw_directory", "archives"}
        or type(contract["version"]) is not int
        or contract["version"] != 1
        or contract["raw_locator"] != str(Path(raw_dir).absolute())
        or contract["raw_directory"] != str(Path(raw_dir).resolve())
        or not isinstance(contract["archives"], dict)
        or not selected
        or set(contract["archives"]) != set(selected)
    ):
        raise SourceFinalizationRequired("PREGO native archive inventory missing or changed; rerun the producer")
    for locator in selected:
        archive = Path(locator)
        record = contract["archives"][locator]
        if not isinstance(record, dict) or set(record) != {
            "version",
            "archive",
            "archive_sha256",
            "member",
            "payload_sha256",
            "payload_bytes",
        }:
            raise SourceFinalizationRequired("Malformed PREGO extraction provenance")
        if (
            type(record["version"]) is not int
            or record["version"] != 1
            or record["archive"] != str(archive.resolve())
            or not isinstance(record["member"], str)
            or Path(record["member"]).name != "database_pairs.tsv"
            or type(record["payload_bytes"]) is not int
            or record["payload_bytes"] < 0
        ):
            raise SourceFinalizationRequired("Invalid PREGO archive/member provenance")
        payload = archive.parent / archive.stem.replace(".tar", "_extracted") / "database_pairs.tsv"
        for kind, path in (("archive", archive), ("payload", payload)):
            digest = record[f"{kind}_sha256"]
            identity = guard.capture(path)
            if (
                snapshots.get(f"prego_{kind}_{archive.name}") != {"path": str(path.resolve()), "sha256": digest}
                or identity["sha256"] != digest
                or (kind == "payload" and identity["bytes"] != record["payload_bytes"])
            ):
                raise SourceFinalizationRequired(f"PREGO {kind} provenance disagrees with consumed bytes")
        # Cache only proof produced by a real archive read in this admission
        # epoch, never metadata from a receipt or a finalization report.
        if not hasattr(guard, "prego_verified_members"):
            guard.prego_verified_members = {}
        native = guard.prego_verified_members.get(archive.resolve())
        if native is None:
            native = archive_payload_identity(archive)
            guard.prego_verified_members[archive.resolve()] = native
        if any(record[key] != value for key, value in native.items()):
            raise SourceFinalizationRequired("PREGO exact archive member disagrees with recorded payload provenance")
    guard.verify(metadata_only=True)
    return guard
