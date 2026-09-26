"""Read-only content evidence for postprocess status; never certify freshness from timestamps."""

import gzip
import hashlib
import json
import tarfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAX_METADATA_BYTES = 2 * 1024 * 1024


@dataclass
class ArtifactStatus:
    """Exact selected artifact identity plus bounded streaming verification results."""

    path: Path | None
    status: str
    detail: str
    archive_sha256: str | None = None
    members: dict = field(default_factory=dict)


def _snapshot(path):
    """Detect replacement or mutation during inspection, not infer content freshness."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _summary(stream):
    """Hash and count physical header-excluding TSV rows with bounded memory."""
    digest = hashlib.sha256()
    size = lines = 0
    tail = b""
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
        lines += chunk.count(b"\n")
        tail = chunk[-1:]
    return {"sha256": digest.hexdigest(), "bytes": size, "rows": max(0, lines + int(bool(tail) and tail != b"\n") - 1)}


def _file_summary(path):
    """Read an unchanged file, rejecting races rather than combining different versions."""
    before = _snapshot(path)
    with path.open("rb") as stream:
        result = _summary(stream)
    if _snapshot(path) != before:
        raise ValueError(f"Artifact changed during inspection: {path}")
    return result


def _metadata(stream):
    """Read only bounded manifest/receipt JSON, never graph-sized metadata."""
    payload = stream.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError("Manifest/receipt exceeds bounded metadata limit")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Manifest/receipt must be a JSON object")
    return value


def _safe_name(name):
    """Accept only portable flat archive/member-relative names, never paths or links."""
    return isinstance(name, str) and bool(name) and name not in {".", ".."} and not any(c in name for c in "/\\\x00")


def _graph_pair(members):
    """Require one unambiguous named node/edge pair in a selected graph artifact."""
    nodes = [name for name in members if name.endswith("_nodes.tsv")]
    edges = [name for name in members if name.endswith("_edges.tsv")]
    if len(nodes) != 1 or len(edges) != 1 or nodes[0][:-10] != edges[0][:-10]:
        raise ValueError("Artifact must contain exactly one matching node/edge TSV pair")


def _check_manifest(manifest, actual):
    """Verify every declared member identity, including counts, without trusting filenames alone."""
    if manifest.get("manifest_version") != 1 or type(manifest.get("manifest_version")) is not int:
        raise ValueError("Unsupported graph manifest version")
    expected = manifest.get("members")
    if not isinstance(expected, dict) or not expected or set(expected) != set(actual):
        raise ValueError("Manifest/member inventory mismatch")
    for name, identity in expected.items():
        if not _safe_name(name) or not isinstance(identity, dict):
            raise ValueError("Unsafe or malformed manifest member")
        if (
            type(identity.get("bytes")) is not int
            or type(identity.get("rows")) is not int
            or identity.get("bytes", -1) < 0
            or identity.get("rows", -1) < 0
            or identity != actual[name]
        ):
            raise ValueError(f"Manifest identity/count mismatch: {name}")
    _graph_pair(actual)


def inspect_artifact(path):
    """Inspect archive or loose manifest/pair without extracting or changing any graph files."""
    if path is None:
        return ArtifactStatus(None, "missing", "No merged graph artifact selected or discovered.")
    path = Path(path)
    if not path.is_file():
        return ArtifactStatus(path, "missing", f"Selected artifact missing: {path}")
    members, archive_hash = {}, None
    try:
        initial = _snapshot(path)
        if path.name.endswith(".tar.gz"):
            archive_hash = _file_summary(path)["sha256"]
            manifest = None
            seen = set()
            with gzip.open(path, "rb") as compressed:
                with tarfile.open(fileobj=compressed, mode="r|") as archive:
                    for member in archive:
                        if (
                            len(seen) >= 1000
                            or not _safe_name(member.name)
                            or not member.isfile()
                            or member.name in seen
                        ):
                            raise ValueError(
                                f"Unsafe, duplicate, nonregular or excessive archive member: {member.name}"
                            )
                        seen.add(member.name)
                        with archive.extractfile(member) as stream:
                            if member.name == "manifest.json":
                                manifest = _metadata(stream)
                            else:
                                members[member.name] = _summary(stream)
                # Tar iteration can stop before gzip's trailer. Consume the
                # remainder so CRC/truncation defects cannot appear verified.
                while compressed.read(1024 * 1024):
                    pass
            _graph_pair(members)
            if _snapshot(path) != initial:
                raise ValueError("Archive changed during inspection")
            if manifest is None:
                return ArtifactStatus(
                    path,
                    "unverified",
                    "Graph pair present; legacy archive has no integrity manifest.",
                    archive_hash,
                    members,
                )
            _check_manifest(manifest, members)
        elif path.name.endswith("_manifest.json"):
            with path.open("rb") as stream:
                manifest = _metadata(stream)
            expected = manifest.get("members")
            if not isinstance(expected, dict) or not expected or any(not _safe_name(name) for name in expected):
                raise ValueError("Unsafe or missing loose manifest inventory")
            snapshots = {}
            for name in expected:
                member_path = path.parent / name
                if member_path.is_symlink() or not member_path.is_file():
                    raise ValueError(f"Missing or nonregular loose graph member: {name}")
                snapshots[member_path] = _snapshot(member_path)
                members[name] = _file_summary(member_path)
            _check_manifest(manifest, members)
            if _snapshot(path) != initial or any(_snapshot(member) != value for member, value in snapshots.items()):
                raise ValueError("Loose graph bundle changed during inspection")
        elif path.name.endswith("_nodes.tsv"):
            edge_path = path.with_name(path.name[:-10] + "_edges.tsv")
            if not edge_path.is_file():
                return ArtifactStatus(path, "missing", f"Loose graph is incomplete; missing {edge_path.name}.")
            return ArtifactStatus(path, "unverified", "Loose graph pair present without a content manifest.")
        else:
            raise ValueError("Select a .tar.gz archive, *_manifest.json, or *_nodes.tsv")
    except (OSError, ValueError, tarfile.TarError, EOFError, UnicodeError, zlib.error) as error:
        return ArtifactStatus(path, "invalid", f"Artifact integrity failed: {error}", archive_hash, members)
    return ArtifactStatus(
        path,
        "ok",
        "Exact manifest member hashes, bytes and row counts verified; not a biological/review verdict.",
        archive_hash,
        members,
    )


def select_artifact(repo, *, merged_dir=None, archive=None):
    """Find graph artifacts themselves, refusing ambiguous siblings instead of using directory mtimes."""
    repo = Path(repo)
    if archive is not None:
        return Path(archive) if Path(archive).is_absolute() else repo / archive
    root = Path(merged_dir) if merged_dir else repo / "data" / "merged"
    if not root.is_absolute():
        root = repo / root
    directories = [root]
    if merged_dir is None and root.is_dir():
        directories.extend(child for child in root.iterdir() if child.is_dir())
    found = set()
    for directory in directories:
        found.update(directory.glob("*.tar.gz"))
        manifests = set(directory.glob("*_manifest.json"))
        found.update(manifests)
        for node in directory.glob("*_nodes.tsv"):
            if node.with_name(node.name[:-10] + "_manifest.json") not in manifests:
                found.add(node)
    found = sorted(path for path in found if path.is_file())
    if len(found) > 1:
        raise ValueError(
            "Ambiguous merged artifacts; select --archive or a unique --merged-dir: "
            + ", ".join(str(path) for path in found)
        )
    return found[0] if found else None


def review_status(skill, artifact, repo, review_dirs=()):
    """Require archive-bound, report-byte-bound full pass receipts; prose alone is unverified."""
    if artifact.status != "ok" or not artifact.archive_sha256:
        return "unverified", "Review cannot be certified without a verified selected archive identity."
    roots = [Path(path) for path in review_dirs]
    roots.extend(path for path in (Path(repo) / "data").glob("review-*") if path.is_dir())
    roots.append(Path(repo) / ".claude" / "skills" / skill / "reviews")
    receipts, markdown = set(), set()
    for root in roots:
        receipts.update(root.rglob("*.receipt.json"))
        markdown.update(root.rglob("*.md"))
    matches, invalid, failures = [], [], []
    for path in sorted(receipts):
        try:
            with path.open("rb") as stream:
                receipt = _metadata(stream)
            if receipt.get("skill") != skill or receipt.get("archive_sha256") != artifact.archive_sha256:
                continue
            report_name = receipt.get("report")
            if (
                not _safe_name(report_name)
                or type(receipt.get("receipt_version")) is not int
                or receipt["receipt_version"] != 1
            ):
                raise ValueError("Malformed review receipt")
            report = path.parent / report_name
            if (
                not report.is_file()
                or report.is_symlink()
                or _file_summary(report)["sha256"] != receipt.get("report_sha256")
            ):
                raise ValueError("Review report identity changed or missing")
            if receipt.get("scope") != "full":
                raise ValueError("Review receipt does not certify full scope")
            if receipt.get("verdict") != "pass":
                failures.append(str(path))
            else:
                matches.append(str(path))
        except (OSError, ValueError, UnicodeError) as error:
            invalid.append(f"{path}: {error}")
    if failures:
        return "invalid", "Matching full-scope review reports a non-pass verdict: " + "; ".join(failures)
    if invalid:
        return "unverified", "Review receipt cannot be verified: " + "; ".join(invalid)
    if matches:
        return "ok", "Full pass receipt binds this exact archive and report bytes: " + "; ".join(matches)
    review_kind = skill.removeprefix("kg-").removesuffix("-review")
    relevant = [
        path
        for path in markdown
        if skill in path.parts
        or path.stem.lower() == "review"
        or review_kind in path.stem.lower().replace("-", "_").split("_")
    ]
    # Prefer the named skill report to a combined REVIEW.md. An unrelated
    # mapping/KGX validation report mentioning the same hash is not evidence
    # that this modeling/path review was performed.
    for path in sorted(relevant, key=lambda item: (item.stem.lower() == "review", str(item))):
        try:
            if path.stat().st_size <= MAX_METADATA_BYTES and artifact.archive_sha256 in path.read_text(
                encoding="utf-8", errors="replace"
            ):
                return "unverified", f"Hash-matching report present at {path}; verdict/scope not machine-certified."
        except OSError:
            return "unverified", f"Review evidence unreadable or changed during inspection: {path}"
    return "missing", "No review evidence bound to this exact archive hash was found."
