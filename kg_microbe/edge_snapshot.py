"""Verify immutable KGX snapshots and export lossless, bounded occurrence shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

CONTRACT = "kg-microbe-curation/v1"
DEFAULT_EDGE_MEMBER = "merged-kg_edges.tsv"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
DEFAULT_ROW_BYTES = 16 * 1024 * 1024
DEFAULT_SHARD_BYTES = 32 * 1024 * 1024
DEFAULT_SHARD_ROWS = 100_000


def canonical_json(value: object) -> bytes:
    """Encode the shared identity contract without lexical or semantic normalization."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def occurrence_id(payload: dict) -> str:
    """Identify one release occurrence, never a canonical biological assertion."""
    envelope = {"contract": CONTRACT, "kind": "occurrence", "payload": payload}
    return "urn:kg-microbe:occurrence:v1:" + hashlib.sha256(canonical_json(envelope)).hexdigest()


def _unique_object(pairs: list[tuple]) -> dict:
    """Reject duplicate JSON keys instead of silently selecting one declaration."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def _regular_open(path: Path):
    """Open a regular file without following a final symlink or accepting a FIFO."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Expected a regular, non-symlink file: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    handle = os.fdopen(descriptor, "rb")
    opened = os.fstat(handle.fileno())
    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
        handle.close()
        raise ValueError(f"Input changed while opening: {path}")
    return handle


def _signature(info: os.stat_result) -> tuple:
    """Track inode replacement and metadata changes while a snapshot is scanned."""
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _load_manifest(path: Path) -> tuple[dict, bytes]:
    """Read bounded, unambiguous manifest-v1 metadata and retain its exact bytes."""
    with _regular_open(path) as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Source manifest exceeds the size limit")
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    canonical_json(manifest)  # Reject nonfinite values even in otherwise opaque provenance.
    if not isinstance(manifest, dict) or type(manifest.get("manifest_version")) is not int:
        raise ValueError("Expected manifest_version 1")
    if manifest["manifest_version"] != 1 or not isinstance(manifest.get("members"), dict) or not manifest["members"]:
        raise ValueError("Expected manifest_version 1 with nonempty members")
    for name, identity in manifest["members"].items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.tsv", name):
            raise ValueError(f"Unsafe or unsupported member name: {name!r}")
        if not isinstance(identity, dict) or set(identity) != {"sha256", "bytes", "rows"}:
            raise ValueError(f"Invalid member identity: {name}")
        if not isinstance(identity["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]):
            raise ValueError(f"Invalid member SHA-256: {name}")
        if any(type(identity[key]) is not int or identity[key] < 0 for key in ("bytes", "rows")):
            raise ValueError(f"Invalid member byte/row count: {name}")
    return manifest, raw


def _cells(raw: bytes) -> list[str]:
    """Parse literal UTF-8 TSV without quote handling or missing-value coercion."""
    content = raw[:-1] if raw.endswith(b"\n") else raw
    if content.endswith(b"\r") and raw.endswith(b"\n"):
        content = content[:-1]
    if b"\r" in content or b"\x00" in content:
        raise ValueError("TSV contains an embedded CR or NUL")
    return content.decode("utf-8").split("\t")


class _Shards:
    """Keep only one bounded output record and one output handle in memory."""

    def __init__(self, directory: Path, rows: int, size: int):
        """Set output limits without opening any output files yet."""
        self.directory = directory
        self.max_rows = rows
        self.max_bytes = size
        self.handle = None
        self.digest = None
        self.current = None
        self.shards = []
        self.total = 0

    def write(self, record: dict) -> None:
        """Rotate before exceeding either shard bound; never split an occurrence."""
        encoded = canonical_json(record) + b"\n"
        if len(encoded) > self.max_bytes:
            raise ValueError("An occurrence exceeds the shard byte limit")
        if self.current and (
            self.current["rows"] >= self.max_rows or self.current["bytes"] + len(encoded) > self.max_bytes
        ):
            self.close()
        if self.handle is None:
            name = f"occurrences-{len(self.shards) + 1:06d}.jsonl"
            self.handle = (self.directory / name).open("xb")
            self.digest = hashlib.sha256()
            self.current = {"file": name, "bytes": 0, "rows": 0, "first_row": record["row_number"]}
        self.handle.write(encoded)
        self.digest.update(encoded)
        self.current["bytes"] += len(encoded)
        self.current["rows"] += 1
        self.current["last_row"] = record["row_number"]
        self.total += 1

    def close(self) -> None:
        """Finish a shard and record the exact serialized identity."""
        if self.handle is not None:
            self.handle.close()
            self.current["sha256"] = self.digest.hexdigest()
            self.shards.append(self.current)
            self.handle = None
            self.current = None


def _scan(
    manifest_path: Path, edge_member: str, max_row_bytes: int, writer=None, max_rows: int = 0
) -> tuple[dict, bytes]:
    """Verify all members, optionally serializing a leading subset of edge occurrences."""
    manifest, raw_manifest = _load_manifest(manifest_path)
    if edge_member not in manifest["members"]:
        raise ValueError(f"Edge member is not in the manifest: {edge_member}")
    manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
    verified = {}
    signatures = {}
    for name, expected in sorted(manifest["members"].items()):
        path = manifest_path.parent / name
        digest = hashlib.sha256()
        size = rows = 0
        with _regular_open(path) as handle:
            before = _signature(os.fstat(handle.fileno()))
            header = None
            while True:
                raw = handle.readline(max_row_bytes + 1)
                if not raw:
                    break
                if len(raw) > max_row_bytes:
                    raise ValueError(f"Row exceeds the byte limit: {name}:{rows + 1}")
                digest.update(raw)
                size += len(raw)
                values = _cells(raw)
                if header is None:
                    header = values
                    header_row = raw.decode("utf-8")
                    if any(not cell or cell != cell.strip() for cell in header) or len(set(header)) != len(header):
                        raise ValueError(f"Blank, padded, or duplicate header: {name}")
                    continue
                rows += 1
                if len(values) != len(header):
                    raise ValueError(f"Inconsistent field count: {name}:{rows + 1}")
                if writer is not None and name == edge_member and (not max_rows or rows <= max_rows):
                    payload = {
                        "manifest_sha256": manifest_sha,
                        "member": name,
                        "member_sha256": expected["sha256"],
                        "row_number": rows,
                        "row_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                    writer.write(
                        {"occurrence_id": occurrence_id(payload), **payload, "source_row": raw.decode("utf-8")}
                    )
            if header is None:
                raise ValueError(f"Missing TSV header: {name}")
            if before != _signature(os.fstat(handle.fileno())) or before != _signature(path.lstat()):
                raise ValueError(f"Input changed during verification: {name}")
        actual = {"sha256": digest.hexdigest(), "bytes": size, "rows": rows}
        if actual != expected:
            raise ValueError(f"Member does not match source manifest: {name}")
        signatures[name] = before
        verified[name] = {**actual, "header": header, "header_row": header_row}
    # Also catch a previously scanned member being replaced while later members were read.
    if any(_signature((manifest_path.parent / name).lstat()) != value for name, value in signatures.items()):
        raise ValueError("Snapshot changed during verification")
    _, final_manifest = _load_manifest(manifest_path)
    if final_manifest != raw_manifest:
        raise ValueError("Source manifest changed during verification")
    return {
        "contract": CONTRACT,
        "format": "edge-snapshot-inventory",
        "format_version": 1,
        "source_manifest_sha256": manifest_sha,
        "source_manifest": manifest,
        "members": verified,
        "input_complete": True,
    }, raw_manifest


def inventory_snapshot(
    manifest: Path, *, edge_member: str = DEFAULT_EDGE_MEMBER, max_row_bytes: int = DEFAULT_ROW_BYTES
) -> dict:
    """Verify every listed member in full and return headers, hashes, counts, and provenance."""
    if max_row_bytes <= 0:
        raise ValueError("max_row_bytes must be positive")
    return _scan(Path(manifest), edge_member, max_row_bytes)[0]


def export_snapshot(
    manifest: Path,
    output: Path,
    *,
    edge_member: str = DEFAULT_EDGE_MEMBER,
    max_rows: int = 0,
    shard_rows: int = DEFAULT_SHARD_ROWS,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    max_row_bytes: int = DEFAULT_ROW_BYTES,
) -> dict:
    """Stage new occurrence shards, verify the whole snapshot, then publish one directory."""
    if type(max_rows) is not int or max_rows < 0 or min(shard_rows, shard_bytes, max_row_bytes) <= 0:
        raise ValueError("max_rows must be nonnegative and shard/row bounds must be positive")
    manifest, output = Path(manifest).absolute(), Path(output).absolute()
    if output.is_symlink() or output.exists():
        raise FileExistsError(output)
    if manifest.resolve().is_relative_to(output.resolve()):
        raise ValueError("Output must not contain the source snapshot")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Serialize cooperating exporters, then publish the complete staged directory.
    lock = output.with_name(f".{output.name}.export-lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    stage = None
    writer = None
    try:
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.export-", dir=output.parent))
        writer = _Shards(stage, shard_rows, shard_bytes)
        result, source_manifest = _scan(manifest, edge_member, max_row_bytes, writer, max_rows)
        writer.close()
        result["format"] = "edge-occurrence-export"
        result["source_manifest_file"] = "source-manifest.json"
        result["selection"] = {
            "edge_member": edge_member,
            "max_rows": max_rows,
            "exported_rows": writer.total,
            "complete_export": writer.total == result["members"][edge_member]["rows"],
        }
        result["shard_limits"] = {"rows": shard_rows, "bytes": shard_bytes}
        result["shards"] = writer.shards
        (stage / "source-manifest.json").write_bytes(source_manifest)
        (stage / "manifest.json").write_bytes(canonical_json(result) + b"\n")
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        stage.rename(output)
        stage = None
        return result
    finally:
        if writer is not None:
            writer.close()
        if stage is not None:
            shutil.rmtree(stage)
        lock.unlink()


def main(argv: list[str] | None = None) -> None:
    """Run a local inventory or export without downloading or modifying graph inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "export"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path, help="Local manifest-v1 JSON beside its TSV members")
        command.add_argument("--edge-member", default=DEFAULT_EDGE_MEMBER)
        command.add_argument("--max-row-bytes", type=int, default=DEFAULT_ROW_BYTES)
        if name == "export":
            command.add_argument("output", type=Path, help="New output directory; existing output is refused")
            command.add_argument("--max-rows", type=int, default=0, help="Export the first N edges; 0 exports all")
            command.add_argument("--shard-rows", type=int, default=DEFAULT_SHARD_ROWS)
            command.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)
    args = vars(parser.parse_args(argv))
    action = args.pop("command")
    try:
        result = export_snapshot(**args) if action == "export" else inventory_snapshot(**args)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Snapshot {action} failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
