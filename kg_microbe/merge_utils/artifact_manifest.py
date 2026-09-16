"""Portable manifests for the exact cleaned KGX TSV bytes shipped by a merge."""

import hashlib
import io
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Optional

import yaml

from kg_microbe.merge_utils.stats_provenance import git_commit, source_markers
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.transform_fingerprint import schema_fingerprint

MANIFEST_MEMBER = "manifest.json"


class _CountedReader:
    """Hash/count a TSV as tarfile reads it, so the manifest describes archived bytes."""

    def __init__(self, handle: BinaryIO):
        """Wrap a binary stream without buffering the graph in memory."""
        self.handle = handle
        self.digest = hashlib.sha256()
        self.size = 0
        self.lines = 0
        self.tail = b""

    def read(self, size: int = -1) -> bytes:
        """Consume bytes and count physical KGX TSV lines (fields are newline-sanitized)."""
        chunk = self.handle.read(size)
        self.digest.update(chunk)
        self.size += len(chunk)
        self.lines += chunk.count(b"\n")
        if chunk:
            self.tail = chunk[-1:]
        return chunk

    def summary(self) -> Dict:
        """Return byte identity and header-excluding row count, including an unterminated row."""
        return {
            "sha256": self.digest.hexdigest(),
            "bytes": self.size,
            "rows": max(0, self.lines + int(bool(self.tail) and self.tail != b"\n") - 1),
        }


def build_provenance(config_file: Path, repo_root: Path, ignore: Iterable[Path] = ()) -> Dict:
    """Record config identity and repository inputs without depending on external stats."""
    payload = config_file.read_bytes()
    config = yaml.safe_load(payload) or {}
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit": git_commit(repo_root, ignore=ignore),
        "python": sys.version.split()[0],
        "merge_config": {"name": config_file.name, "sha256": hashlib.sha256(payload).hexdigest()},
        # These identify repository inputs, not a claim that every configured
        # source participated in a --source-limited merge or had a fresh marker.
        "configured_source_markers": source_markers(config, repo_root),
        "repository_schema": schema_fingerprint(repo_root),
    }


def _manifest(members: Dict, provenance: Optional[Dict]) -> Dict:
    """Use member-relative names; neither the archive nor this JSON hashes itself."""
    return {"manifest_version": 1, "members": members, "provenance": provenance or {}}


def write_graph_archive(archive: Path, files: Iterable[Path], provenance: Optional[Dict] = None) -> None:
    """Atomically ship TSVs and their byte-accurate manifest; retain the old archive on failure."""
    members = {}
    with atomic_write(archive, "wb") as output:
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            for path in files:
                if path.name == MANIFEST_MEMBER or path.name in members:
                    raise ValueError(f"Duplicate or reserved archive member: {path.name}")
                with path.open("rb") as handle:
                    reader = _CountedReader(handle)
                    info = tar.gettarinfo(str(path), arcname=path.name)
                    if not info.isfile():
                        raise ValueError(f"Graph member must be a regular file: {path}")
                    tar.addfile(info, reader)
                    members[path.name] = reader.summary()
            payload = (json.dumps(_manifest(members, provenance), indent=2, sort_keys=True) + "\n").encode("utf-8")
            info = tarfile.TarInfo(MANIFEST_MEMBER)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def write_loose_manifest(destination: Path, files: Iterable[Path], provenance: Optional[Dict] = None) -> None:
    """Describe the matching uncompressed TSV pair using paths relative to the manifest."""
    members = {}
    for path in files:
        with path.open("rb") as handle:
            reader = _CountedReader(handle)
            while reader.read(1024 * 1024):
                pass
            members[path.name] = reader.summary()
    with atomic_write(destination, encoding="utf-8", newline="\n") as output:
        json.dump(_manifest(members, provenance), output, indent=2, sort_keys=True)
        output.write("\n")
