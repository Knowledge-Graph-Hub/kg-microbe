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

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

from kg_microbe.utils.atomic_io import atomic_write

#: Filename written beside ``nodes.tsv`` / ``edges.tsv``.
FINGERPRINT_FILE = "source_fingerprint.json"

#: Bumped when the hashing scheme changes, so an old marker is treated as
#: absent rather than silently compared under different rules.
FINGERPRINT_VERSION = 3

#: First-party code every transform runs through besides its own package.
#: A change here changes outputs just as much as a change in the package, and
#: most behaviour-changing PRs land here (#1002).
SHARED_CODE = (
    Path("kg_microbe") / "utils",
    Path("kg_microbe") / "transform_utils" / "constants.py",
    Path("kg_microbe") / "transform_utils" / "transform.py",
)

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
        offsets = sorted({(last_offset * index) // (SAMPLE_COUNT - 1) for index in range(SAMPLE_COUNT)})
        for offset in offsets:
            handle.seek(offset)
            sample = handle.read(SAMPLE_SIZE)
            digest.update(offset.to_bytes(8, "big"))
            digest.update(len(sample).to_bytes(8, "big"))
            digest.update(sample)
    return f"sampled-sha256:{digest.hexdigest()}"


def _repo_root() -> Path:
    """Return the repository root this module lives in."""
    return Path(__file__).resolve().parents[2]


def _folded_name(path: Path, relative_to: Optional[Path]) -> str:
    """
    Return the name folded into a digest for ``path``.

    Repo-relative when ``relative_to`` is given: the absolute path made the
    same files under two checkouts hash differently, so a marker carried with
    its output directory read as stale from any other root (#983).

    :param path: File path.
    :param relative_to: Root to relativise against, or None for the path as is.
    :return: The name to fold in.
    """
    if relative_to is not None:
        try:
            return path.resolve().relative_to(relative_to.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _hash_files(paths: Iterable[Path], relative_to: Optional[Path] = None) -> str:
    """
    Hash a set of files by name and content, order-independently.

    The name is folded in as well as the bytes, so renaming a file — which
    changes what runs without changing any content — is a different
    fingerprint. Missing files are folded in as such rather than skipped: a
    deleted curation file is a change, and skipping it would read as no change.

    :param paths: Files to fingerprint.
    :param relative_to: Fold repo-relative names rather than absolute paths.
    :return: Hex digest.
    """
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.as_posix()):
        digest.update(_folded_name(path, relative_to).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            digest.update(b"<absent>")
        digest.update(b"\0")
    return digest.hexdigest()


def _behaviour_digest(path: Path) -> bytes:
    """
    Digest a Python file by what it *does*, not how it is laid out.

    Hashing raw bytes cannot tell "this transform will produce different
    output" from "someone ran the formatter". #875 reformatted 98 files —
    removing one blank line before each class docstring — and every transform's
    fingerprint moved, so the freshness check indicated a full rebuild when no
    behaviour had changed (#879). A signal that fires on whitespace gets
    overridden, and then it is absent when behaviour really does change.

    The AST is insensitive to formatting and comments, and sensitive to
    everything that can alter output — docstrings included, since they appear
    in it. A file that will not parse falls back to its bytes: a syntax error
    must not read as "no change".

    :param path: Python file.
    :return: Digest bytes.
    """
    try:
        source = path.read_bytes()
    except OSError:
        return b"<absent>"
    try:
        return hashlib.sha256(ast.dump(ast.parse(source.decode("utf-8"))).encode("utf-8")).digest()
    except (SyntaxError, UnicodeDecodeError):
        return hashlib.sha256(source).digest()


def _behaviour_tree_digest(paths: Iterable[Path], relative_to: Optional[Path]) -> str:
    """
    Digest Python files by behaviour, keyed by repo-relative name.

    :param paths: Python files.
    :param relative_to: Root the names are relative to.
    :return: Hex digest.
    """
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.as_posix()):
        digest.update(_folded_name(path, relative_to).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_behaviour_digest(path))
        digest.update(b"\0")
    return digest.hexdigest()


def code_fingerprint(code_dir: Path, repo_root: Optional[Path] = None) -> str:
    """
    Fingerprint every Python file in a transform's package directory.

    Directory rather than the single module, matching what the freshness check
    already treats as "this transform's code": several transforms are split
    across helper modules in the same package, and a change to one of those
    changes the output just as much.

    Names are folded in repo-relative, so the same package under two
    checkouts is one fingerprint (#983).

    :param code_dir: e.g. ``kg_microbe/transform_utils/gold``.
    :param repo_root: Repository root; inferred from this module when omitted.
    :return: Hex digest, or the digest of nothing when the directory is absent.
    """
    if not code_dir.is_dir():
        return hashlib.sha256(b"").hexdigest()
    return _behaviour_tree_digest(code_dir.rglob("*.py"), repo_root or _repo_root())


def shared_code_fingerprint(repo_root: Optional[Path] = None) -> str:
    """
    Fingerprint the first-party code every transform shares.

    ``code_fingerprint`` sees only the transform's own package, so a change in
    ``kg_microbe/utils/`` -- the mapping loaders, the ontology adapters, the
    chemical-mapping utils -- or in ``constants.py`` marked nothing stale:
    #999 changed three transforms' predicates and the freshness table stayed
    FRESH (#1002). Blunt by design: an edit here reads as "every output may
    differ", which is the honest answer.

    :param repo_root: Repository root; inferred from this module when omitted.
    :return: Hex digest.
    """
    root = repo_root or _repo_root()
    paths = []
    for rel in SHARED_CODE:
        target = root / rel
        if target.is_dir():
            paths.extend(target.rglob("*.py"))
        elif target.is_file():
            paths.append(target)
    return _behaviour_tree_digest(paths, root)


def upstream_fingerprint(output_base_dir: Path, transform_inputs: Iterable[str]) -> str:
    """
    Fingerprint the recorded state of every upstream transform.

    Folds in each upstream's own marker rather than its output TSVs, which can
    be hundreds of megabytes. If an upstream re-runs, its marker changes and
    every downstream goes stale — which is the point (#845).

    An upstream with no marker folds in as absent, so a downstream goes stale
    exactly once when that upstream first records one. That is the correct
    direction to fail: it prompts a re-run rather than asserting currency that
    was never established.

    :param output_base_dir: ``data/transformed``.
    :param transform_inputs: Registered source names read by this transform.
    :return: Hex digest.
    """
    digest = hashlib.sha256()
    for name in sorted(set(transform_inputs)):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        recorded = read_fingerprint(output_base_dir / name)
        digest.update(json.dumps(recorded, sort_keys=True).encode("utf-8") if recorded else b"<absent>")
        digest.update(b"\0")
    return digest.hexdigest()


def data_fingerprint(repo_root: Path, data_inputs: Iterable[str]) -> str:
    """
    Fingerprint a transform's declared curation inputs.

    :param repo_root: Repository root, which ``DATA_INPUTS`` are relative to.
    :param data_inputs: Repo-relative paths from ``Transform.DATA_INPUTS``.
    :return: Hex digest.
    """
    return _hash_files((repo_root / rel for rel in data_inputs), relative_to=repo_root)


#: The pinned Biolink schema every transform validates against, relative to
#: the repository root. All three move together (see CLAUDE.md).
SCHEMA_FILES = (
    Path("data") / "raw" / "biolink-model.yaml",
    Path("data") / "raw" / "attributes.yaml",
    Path("data") / "raw" / "predicate_mapping.yaml",
)

_SCHEMA_VERSION_LINE = re.compile(r"^version:\s*['\"]?([^'\"\s]+)")


def schema_fingerprint(repo_root: Path) -> Optional[dict]:
    """
    Identify the Biolink schema a transform ran against.

    The pinned model is a real pipeline input -- ``prepare_kgx`` makes it the
    default schema for every KGX ``Toolkit`` -- but no transform declares it,
    so swapping it (as #941 did, 4.3.6 -> 4.4.2) marked nothing stale and a
    partial rerun could mix schema versions in one merged graph (#943). Record
    it in the marker so the artifact says which schema produced it.

    :param repo_root: Repository root.
    :return: ``{"version": ..., "digest": ...}``, or None when no schema file
        is on disk -- unknown provenance is recorded as unknown, not invented.
    """
    present = [rel for rel in SCHEMA_FILES if (repo_root / rel).is_file()]
    if not present:
        return None
    version = "unknown"
    model = repo_root / SCHEMA_FILES[0]
    if model.is_file():
        with model.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = _SCHEMA_VERSION_LINE.match(line)
                if match:
                    version = match.group(1)
                    break
    # Folded in by repo-relative name, not by absolute path: the same schema
    # in a different checkout is the same schema, and a marker carried to
    # another machine must not read as a schema change.
    digest = hashlib.sha256()
    for rel in present:
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256((repo_root / rel).read_bytes()).digest())
        digest.update(b"\0")
    return {"version": version, "digest": digest.hexdigest()}


def write_fingerprint(
    output_dir: Path,
    code_dir: Path,
    repo_root: Path,
    data_inputs: Iterable[str],
    transform_inputs: Iterable[str] = (),
) -> dict:
    """
    Record the fingerprint of a completed run.

    Call **after** the outputs are written, so a run that dies partway leaves
    no marker claiming its output matches the current inputs. Written through
    ``atomic_write`` for the same reason a torn marker would be worse than none.

    :param output_dir: Where the transform wrote its TSVs.
    :param code_dir: The transform's package directory.
    :param repo_root: Repository root.
    :param data_inputs: Repo-relative curation paths.
    :param transform_inputs: Registered sources whose output this one reads.
    :return: The recorded payload.
    """
    payload = {
        "version": FINGERPRINT_VERSION,
        "code": code_fingerprint(code_dir, repo_root),
        # Shared first-party code, recorded apart from the package so the
        # report can say which of the two moved (#1002).
        "shared": shared_code_fingerprint(repo_root),
        "data": data_fingerprint(repo_root, data_inputs),
        # Recorded separately so a stale output says which of the three moved:
        # its code, its curation data, or something it reads (#845).
        "upstream": upstream_fingerprint(output_dir.parent, transform_inputs),
        # Which Biolink schema this output was validated against (#943).
        "schema": schema_fingerprint(repo_root),
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


# ---------------------------------------------------------------------------
# Migration from scheme 2
# ---------------------------------------------------------------------------
# Scheme 2 folded absolute paths into every digest and did not see shared code.
# Bumping the version makes every existing marker read as absent, which would
# send a freshly rebuilt tree back to timestamp comparison until each source
# ran again. A marker whose scheme-2 digests still match its inputs vouches
# for the same output under scheme 3; rewrite those, leave the rest alone.


def _read_marker_any_version(output_dir: Path) -> Optional[dict]:
    """
    Read a marker regardless of scheme version.

    :param output_dir: Directory holding the marker.
    :return: The payload, or None.
    """
    try:
        payload = json.loads((output_dir / FINGERPRINT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _v2_hash_files(paths: Iterable[Path]) -> str:
    """Scheme-2 file digest: absolute paths folded in."""
    return _hash_files(paths, relative_to=None)


def _v2_code_fingerprint(code_dir: Path) -> str:
    """Scheme-2 package digest: absolute paths folded in."""
    if not code_dir.is_dir():
        return hashlib.sha256(b"").hexdigest()
    return _behaviour_tree_digest(code_dir.rglob("*.py"), None)


def _v2_upstream_fingerprint(output_base_dir: Path, transform_inputs: Iterable[str]) -> str:
    """Scheme-2 upstream digest, read from the markers as they were before migration."""
    digest = hashlib.sha256()
    for name in sorted(set(transform_inputs)):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        recorded = _read_marker_any_version(output_base_dir / name)
        if recorded is not None and recorded.get("version") != 2:
            recorded = None
        digest.update(json.dumps(recorded, sort_keys=True).encode("utf-8") if recorded else b"<absent>")
        digest.update(b"\0")
    return digest.hexdigest()


def migrate_markers(transformed_dir: Path, repo_root: Path, sources: Iterable[dict]) -> Dict[str, str]:
    """
    Rewrite scheme-2 markers that still vouch for their output as scheme 3.

    Two phases, because upstream digests read other markers: first judge every
    scheme-2 marker against its inputs under scheme 2, while all markers are
    still scheme 2; then rewrite the ones that were FRESH, in dependency order,
    so each downstream's new upstream digest sees its upstreams' new markers.

    :param transformed_dir: ``data/transformed``.
    :param repo_root: Repository root.
    :param sources: One dict per registered source: ``name``, ``output_dir``
        (the directory under ``transformed_dir``), ``code_dir``,
        ``data_inputs``, ``transform_inputs``.
    :return: ``{source name: "migrated" | "left: <reason>"}``.
    """
    sources = list(sources)
    by_name = {src["name"]: src for src in sources}

    # Phase 1: verdicts under scheme 2, before anything is rewritten.
    fresh_v2: Dict[str, bool] = {}
    reasons: Dict[str, str] = {}
    for src in sources:
        out = transformed_dir / src["output_dir"]
        marker = _read_marker_any_version(out)
        if marker is None:
            reasons[src["name"]] = "left: no marker"
            continue
        if marker.get("version") == FINGERPRINT_VERSION:
            reasons[src["name"]] = "left: already current"
            continue
        if marker.get("version") != 2:
            reasons[src["name"]] = f"left: unknown scheme {marker.get('version')!r}"
            continue
        ok = (
            marker.get("code") == _v2_code_fingerprint(src["code_dir"])
            and marker.get("data") == _v2_hash_files(repo_root / rel for rel in src["data_inputs"])
            and marker.get("upstream") == _v2_upstream_fingerprint(transformed_dir, src["transform_inputs"])
        )
        fresh_v2[src["name"]] = ok
        if not ok:
            reasons[src["name"]] = "left: stale under scheme 2; rerun the transform"

    # Phase 2: rewrite in dependency order.
    done: set = set()
    order = []
    remaining = [name for name, ok in fresh_v2.items() if ok]
    while remaining:
        progressed = False
        for name in list(remaining):
            deps = [d for d in by_name[name]["transform_inputs"] if d in fresh_v2 and fresh_v2[d]]
            if all(d in done for d in deps):
                order.append(name)
                done.add(name)
                remaining.remove(name)
                progressed = True
        if not progressed:  # a cycle; write the rest in registration order
            order.extend(remaining)
            remaining = []
    for name in order:
        src = by_name[name]
        write_fingerprint(
            output_dir=transformed_dir / src["output_dir"],
            code_dir=src["code_dir"],
            repo_root=repo_root,
            data_inputs=src["data_inputs"],
            transform_inputs=src["transform_inputs"],
        )
        reasons[name] = "migrated"
    return reasons
