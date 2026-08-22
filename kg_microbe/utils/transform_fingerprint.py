"""
Record which code and curation data produced a transform's output.

Freshness detection has been timestamp-based, and timestamps do not survive
routine git operations. Two failure modes, both observed:

- ``git checkout`` rewrites a tracked file's mtime with no content change, so
  visiting another branch flips the verdict (#797). Moving to commit time fixed
  that one.
- A **squash merge** mints a new commit for content that already existed, so
  commit time jumps forward while the bytes stay identical (#836). #832 squashed
  at 19:30 for code the gold transform had already run against at 19:06, and the
  guard reported stale output that was byte-for-byte current.

Content is the only signal immune to both. A transform writes a fingerprint of
its inputs beside its output; anything comparing them asks whether the bytes
match rather than which timestamp is larger.

Code and data are fingerprinted separately so a stale output can still say
*why* — the distinction `kgm-freshness-check` reports as ``STALE_VS_CODE``
versus ``STALE_VS_DATA``.
"""

import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional

from kg_microbe.utils.atomic_io import atomic_write

#: Filename written beside ``nodes.tsv`` / ``edges.tsv``.
FINGERPRINT_FILE = "source_fingerprint.json"

#: Bumped when the hashing scheme changes, so an old marker is treated as
#: absent rather than silently compared under different rules.
FINGERPRINT_VERSION = 1

# Files at or below this size are cheap enough to hash completely. Larger graph
# TSVs are sampled at evenly spaced offsets so a freshness check does bounded IO
# rather than rereading hundreds of gigabytes before every query.
FULL_HASH_LIMIT = 8 * 1024 * 1024
SAMPLE_SIZE = 128 * 1024
SAMPLE_COUNT = 8


def bounded_file_fingerprint(path: Path) -> str:
    """
    Return a content-sensitive fingerprint with bounded IO for large files.

    Small files are hashed in full. For larger files, the digest covers the
    size and eight evenly spaced 128 KiB windows (including both ends). This is
    intentionally stronger than size/mtime metadata while keeping database
    startup independent of graph size. It is a cache-invalidation signal, not
    a cryptographic proof that two multi-gigabyte files are identical.

    :param path: File to fingerprint.
    :return: Versioned SHA-256 digest string.
    """
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(b"kg-microbe-bounded-file-fingerprint-v1\0")
    digest.update(str(size).encode("ascii"))
    digest.update(b"\0")
    with path.open("rb") as handle:
        if size <= FULL_HASH_LIMIT:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            return f"full-sha256:{digest.hexdigest()}"

        last_offset = max(size - SAMPLE_SIZE, 0)
        offsets = sorted(
            {(last_offset * index) // (SAMPLE_COUNT - 1) for index in range(SAMPLE_COUNT)}
        )
        for offset in offsets:
            handle.seek(offset)
            sample = handle.read(SAMPLE_SIZE)
            digest.update(offset.to_bytes(8, "big"))
            digest.update(len(sample).to_bytes(8, "big"))
            digest.update(sample)
    return f"sampled-sha256:{digest.hexdigest()}"


def _hash_files(paths: Iterable[Path]) -> str:
    """
    Hash a set of files by path and content, order-independently.

    The path is folded in as well as the bytes, so renaming a file — which
    changes what runs without changing any content — is a different
    fingerprint. Missing files are folded in as such rather than skipped: a
    deleted curation file is a change, and skipping it would read as no change.

    :param paths: Files to fingerprint.
    :return: Hex digest.
    """
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            digest.update(b"<absent>")
        digest.update(b"\0")
    return digest.hexdigest()


def code_fingerprint(code_dir: Path) -> str:
    """
    Fingerprint every Python file in a transform's package directory.

    Directory rather than the single module, matching what the freshness check
    already treats as "this transform's code": several transforms are split
    across helper modules in the same package, and a change to one of those
    changes the output just as much.

    :param code_dir: e.g. ``kg_microbe/transform_utils/gold``.
    :return: Hex digest, or the digest of nothing when the directory is absent.
    """
    return _hash_files(code_dir.rglob("*.py")) if code_dir.is_dir() else _hash_files([])


def data_fingerprint(repo_root: Path, data_inputs: Iterable[str]) -> str:
    """
    Fingerprint a transform's declared curation inputs.

    :param repo_root: Repository root, which ``DATA_INPUTS`` are relative to.
    :param data_inputs: Repo-relative paths from ``Transform.DATA_INPUTS``.
    :return: Hex digest.
    """
    return _hash_files(repo_root / rel for rel in data_inputs)


def write_fingerprint(output_dir: Path, code_dir: Path, repo_root: Path, data_inputs: Iterable[str]) -> dict:
    """
    Record the fingerprint of a completed run.

    Call **after** the outputs are written, so a run that dies partway leaves
    no marker claiming its output matches the current inputs. Written through
    ``atomic_write`` for the same reason a torn marker would be worse than none.

    :param output_dir: Where the transform wrote its TSVs.
    :param code_dir: The transform's package directory.
    :param repo_root: Repository root.
    :param data_inputs: Repo-relative curation paths.
    :return: The recorded payload.
    """
    payload = {
        "version": FINGERPRINT_VERSION,
        "code": code_fingerprint(code_dir),
        "data": data_fingerprint(repo_root, data_inputs),
    }
    with atomic_write(output_dir / FINGERPRINT_FILE, encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def read_fingerprint(output_dir: Path) -> Optional[dict]:
    """
    Read a recorded fingerprint, if one is present and readable.

    A marker from a different scheme version, or one that will not parse, reads
    as absent. Callers fall back to their timestamp comparison in that case,
    which is weaker but defined — better than asserting a mismatch on a marker
    we cannot interpret.

    :param output_dir: Directory holding the transform's output.
    :return: The payload, or None.
    """
    path = output_dir / FINGERPRINT_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != FINGERPRINT_VERSION:
        return None
    return payload
