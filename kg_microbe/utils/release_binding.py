"""
Bind a reviewed ontology authority to its upstream release, not to converted bytes (#1420).

A JSON converted from an OWL release cannot be reproduced byte for byte: a different
ROBOT serialization, or an older transform that rewrote the file in place, changes the
bytes without changing a reviewed fact. The release file itself can be fetched again
from its stable URL. So a policy pins that file's SHA-256, checks the release the JSON
declares, and digests only the content it reviewed.
"""

import hashlib
import json
import re
from pathlib import Path


def stream_bytes(stream):
    """Return a consumed-input stream's exact bytes, whether it is opened as text or binary."""
    payload = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    return payload.encode("utf-8") if isinstance(payload, str) else payload


def graph_release(graph):
    """Return the release (``meta.version``) an obograph JSON graph declares, or None."""
    return (graph.get("meta") or {}).get("version")


def canonical_digest(value):
    """SHA-256 of a value's canonical JSON, so reviewed content is compared, not its layout."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def is_release_source(source):
    """Return whether a policy's release-file binding is well formed."""
    return (
        isinstance(source, dict)
        and set(source) == {"file", "sha256"}
        and isinstance(source.get("file"), str)
        and re.fullmatch(r"[a-z_]+\.(json|owl)", source["file"]) is not None
        and isinstance(source.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is not None
    )


def read_bound_authority(raw_dir, filename, source, opener, source_paths):
    """
    Read an authority JSON and verify the release file it is, or was converted from.

    Each file is read through ``opener``, so finalization records it as a consumed
    input. When the release is published as the JSON itself, the JSON's own bytes
    must be the pinned release; otherwise the OWL release beside it is read too.

    :param raw_dir: The selected raw directory.
    :param filename: The JSON the policy reads.
    :param source: ``{"file": ..., "sha256": ...}`` naming the pinned release file.
    :param opener: Consumed-input opener returning a context-managed stream.
    :param source_paths: Set that collects every consulted path.
    :return: The JSON's exact bytes.
    :raises ValueError: When the release file is not the pinned release.
    """
    path = Path(raw_dir) / filename
    source_paths.add(path)
    with opener(path) as stream:
        payload = stream_bytes(stream)
    release = payload
    if source["file"] != filename:
        release_path = Path(raw_dir) / source["file"]
        source_paths.add(release_path)
        with opener(release_path) as stream:
            release = stream_bytes(stream)
    if hashlib.sha256(release).hexdigest() != source["sha256"]:
        raise ValueError(f"Unreviewed release file behind {filename}: {source['file']}")
    return payload
