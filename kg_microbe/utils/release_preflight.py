"""
Check the reviewed upstream inputs before a long ontology run starts (#1420).

The ontology policies bind raw upstream release files by SHA-256: the OWL each
converted JSON is built from, the JSON releases read directly and the ``go.owl``
behind ``go.db``; the NCIT and MeSH policies pin the Biolink model. Each policy
checks its pins only when its source finalizes, so a stale or rewritten download
used to fail after hours of NCBITaxon and ChEBI work. This module collects those
pins from the policies themselves and compares them with the raw directory before
the ontologies source, or a single ontology, runs. It also checks two things a run
would otherwise discover late: that the raw directory holds ``ncit.db`` with a SQLite
header and, with ``ncit.db.gz`` beside it, the archive's unpacked size and CRC-32, or else an
archive that unpacks to a SQLite database; and that an existing ``upa.json`` is the
pinned conversion. It reads the policies' pins and never replaces them.
``ontologies_stubs`` and MediaDive, which also read ``ncit.db``, run the NCIT check
too. Other sources' pins (Rhea, MicrobeDecoder) are checked when those sources run.

Run ``python -m kg_microbe.utils.release_preflight [RAW_DIR]`` to check without
starting a run.
"""

import functools
import gzip
import hashlib
import json
import os
import re
import zlib
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import yaml

from kg_microbe.utils.atomic_io import SQLITE_HEADER

REPO_ROOT = Path(__file__).resolve().parents[2]
_FILE = re.compile(r"[a-z_-]+\.(json|owl|yaml)")
_HEX = re.compile(r"[0-9a-f]{64}")


def _sources(entries: Iterable[dict]) -> List[Tuple[str, str]]:
    """Return ``(file, sha256)`` for each ``{"file": ..., "sha256": ...}`` release binding."""
    return [(entry["file"], entry["sha256"]) for entry in entries]


def _authority_sources(policy: dict) -> List[Tuple[str, str]]:
    return _sources(authority["source"] for authority in policy["authorities"].values())


def _uberon_temporal(policy: dict) -> List[Tuple[str, str]]:
    return _sources([policy["native_source"]])


def _finite_envo_po(policy: dict) -> List[Tuple[str, str]]:
    return [(name, authority["sha256"]) for name, authority in policy["authorities"].items()]


def _go_restrictions(policy: dict) -> List[Tuple[str, str]]:
    sources = policy["sources"]
    return [("pato.owl", sources["pato.owl"]["sha256"]), *_sources([sources["go.db"]["source"]])]


def _upa_routes(policy: dict) -> List[Tuple[str, str]]:
    sources = policy["sources"]
    return [("upa.owl", sources["upa.owl"]), *_sources([sources["go.db"]["source"]])]


def _biolink_model(policy: dict) -> List[Tuple[str, str]]:
    return [(policy["model_file"], policy["model_sha256"])]


def _upa_json(policy: dict) -> List[Tuple[str, str]]:
    return [("upa.json", policy["sources"]["upa.json"]["sha256"])]


# The ontology policies that pin a raw upstream release file by its bytes, plus the
# NCIT and MeSH policies, which bind their native exports by content but pin the
# Biolink model. Rhea's and MicrobeDecoder's pins are checked when those sources run.
PINNING_POLICIES: Tuple[Tuple[str, Callable[[dict], List[Tuple[str, str]]]], ...] = (
    ("mappings/native_ro_predicate_dispositions.json", _authority_sources),
    ("mappings/finite_import_category_dispositions.json", _authority_sources),
    ("mappings/uberon_temporal_category_dispositions.json", _uberon_temporal),
    ("mappings/finite_envo_po_category_dispositions.json", _finite_envo_po),
    ("mappings/go_imported_subject_restrictions.json", _go_restrictions),
    ("mappings/upa_reaction_projection_dispositions.json", _upa_routes),
    ("mappings/ncit_eight_categories.json", _biolink_model),
    ("mappings/mesh_finite_category_dispositions.json", _biolink_model),
)

# Files a run derives from a pinned release and then binds by bytes. A fresh raw
# directory does not have them yet, so only one that is present is checked.
DERIVED_PINS: Tuple[Tuple[str, Callable[[dict], List[Tuple[str, str]]]], ...] = (
    ("mappings/upa_reaction_projection_dispositions.json", _upa_json),
)


def reviewed_release_pins(repo_root: Path = REPO_ROOT, *, policies=None) -> Dict[str, Dict[str, List[str]]]:
    """
    Collect the raw files the reviewed policies pin.

    :param repo_root: Repository root holding ``mappings/``.
    :param policies: The ``(policy, selector)`` pairs to read; the byte-pinning policies by default.
    :return: ``{file: {sha256: [policy, ...]}}``. More than one digest for a file
        means the policies disagree on its release.
    :raises ValueError: When a policy does not hold a well-formed pin where expected.
    """
    pins: Dict[str, Dict[str, List[str]]] = {}
    for relative, select in PINNING_POLICIES if policies is None else policies:
        policy = json.loads((repo_root / relative).read_text(encoding="utf-8"))
        try:
            selected = select(policy)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"Cannot read the release pins of {relative}: {exc!r}") from exc
        for name, sha256 in selected:
            if not isinstance(name, str) or not _FILE.fullmatch(name) or not isinstance(sha256, str):
                raise ValueError(f"Malformed release pin in {relative}: {name!r}")
            if not _HEX.fullmatch(sha256):
                raise ValueError(f"Malformed release pin in {relative}: {name}")
            claimants = pins.setdefault(name, {}).setdefault(sha256, [])
            if relative not in claimants:
                claimants.append(relative)
    return pins


# The pinned files each single-ontology run (`kg transform -s <name>`) reads, so it is
# checked for those only (#1534); the whole ontologies source checks every file. "ncit.db"
# stands for the NCIT check. Besides its own release, a run reads:
# - ro.owl, for native RO, in each supplier's run (pato, uberon, envo, mondo);
# - uberon.owl, where it declares a reviewed UBERON temporal class (pato, mondo, foodon);
# - po.owl, where it declares the reviewed PO class (envo, foodon);
# - go.owl, behind go.db, for GO-imported subjects (pato) and UPA's routes (upa);
# - the Biolink model and ncit.db, for FOODON's NCIT category classes (#1543).
# Native RO suppliers also read ro.json, and readers of UBERON temporal classes
# uberon.json, which the ro and uberon runs convert; this check does not cover them.
SINGLE_ONTOLOGY_INPUTS: Dict[str, frozenset] = {
    "envo": frozenset({"envo.json", "ro.owl", "po.owl"}),
    "foodon": frozenset({"foodon.owl", "uberon.owl", "po.owl", "biolink-model.yaml", "ncit.db"}),
    "go": frozenset({"go.owl"}),
    "mondo": frozenset({"mondo.json", "ro.owl", "uberon.owl"}),
    "pato": frozenset({"pato.owl", "go.owl", "ro.owl", "uberon.owl"}),
    "ro": frozenset({"ro.owl"}),
    "uberon": frozenset({"uberon.owl", "ro.owl"}),
    "upa": frozenset({"upa.owl", "go.owl", "upa.json"}),
}


def _download_tags(repo_root: Path) -> Dict[str, str]:
    """Map each ``download.yaml`` local name to its tag, so a message names the right command."""
    entries = yaml.safe_load((repo_root / "download.yaml").read_text(encoding="utf-8")) or []
    return {
        entry["local_name"]: entry.get("tag", "")
        for entry in entries
        if isinstance(entry, dict) and entry.get("local_name")
    }


def _sha256(path: Path) -> str:
    """Hash a file in blocks; release files run to hundreds of megabytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mismatched_release_files(
    raw_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    pins: Optional[Dict[str, Dict[str, List[str]]]] = None,
) -> List[str]:
    """
    Report each pinned release file that is missing from ``raw_dir`` or is not the reviewed release.

    :param raw_dir: The raw input directory a run will read.
    :param repo_root: Repository root holding ``mappings/`` and ``download.yaml``.
    :param pins: The pins to check; every reviewed policy's by default.
    :return: One message per problem; empty when every pinned file matches.
    """
    pins = reviewed_release_pins(repo_root) if pins is None else pins
    tags = _download_tags(repo_root)
    problems = []
    for name in sorted(pins):
        expected = pins[name]
        if len(expected) != 1:
            claims = "; ".join(f"{', '.join(policies)} pin {sha[:12]}" for sha, policies in sorted(expected.items()))
            problems.append(f"{name}: the reviewed policies disagree on its release ({claims})")
            continue
        sha256, policies = next(iter(expected.items()))
        path = Path(raw_dir) / name
        fetch = f"kg download -t {tags[name]}" if tags.get(name) else "the download.yaml entry for it"
        pinned = f"the reviewed release pinned by {', '.join(policies)} (sha256 {sha256[:12]})"
        if not path.is_file():
            problems.append(f"{name} is missing from {raw_dir}; it must be {pinned}. Fetch it with `{fetch}`.")
        elif (actual := _sha256(path)) != sha256:
            problems.append(
                f"{name} in {raw_dir} (sha256 {actual[:12]}) is not {pinned}. Move it aside and run "
                f"`{fetch}` to fetch the pinned release; see docs/runbooks/reviewed-release-inputs.md."
            )
    return problems


def stale_derived_files(raw_dir: Path, *, repo_root: Path = REPO_ROOT, names=None) -> List[str]:
    """
    Report each derived, byte-pinned file that is present in ``raw_dir`` but is not the pinned one.

    A run reuses such a file rather than deriving it again, then fails its pin hours
    later. An absent file is not reported: the run derives it from the pinned release.

    :param raw_dir: The raw input directory a run will read.
    :param repo_root: Repository root holding ``mappings/``.
    :param names: Only these files, when given.
    :return: One message per stale file.
    """
    problems = []
    for name, expected in sorted(reviewed_release_pins(repo_root, policies=DERIVED_PINS).items()):
        path = Path(raw_dir) / name
        if (names is not None and name not in names) or not path.is_file():
            continue
        sha256, policies = next(iter(expected.items()))
        if len(expected) != 1:
            problems.append(f"{name}: the reviewed policies disagree on its pinned bytes")
        elif (actual := _sha256(path)) != sha256:
            problems.append(
                f"{name} in {raw_dir} (sha256 {actual[:12]}) is not the conversion pinned by "
                f"{', '.join(policies)} (sha256 {sha256[:12]}). Move it aside so the run derives it "
                "again from its pinned release."
            )
    return problems


def _gzip_trailer(archive: Path) -> Tuple[int, int]:
    """
    Return the CRC-32 and the uncompressed size, modulo 2**32, that a gzip archive's trailer records.

    They describe the whole data only for a single-member archive, so a mismatch is
    confirmed by unpacking before it is reported.

    :raises ValueError: When the file cannot be read, or is too short or does not start like gzip.
    """
    try:
        with archive.open("rb") as stream:
            magic = stream.read(2)
            if magic != b"\x1f\x8b" or stream.seek(0, os.SEEK_END) < 18:
                raise ValueError(f"{archive} is not a gzip archive")
            stream.seek(-8, os.SEEK_END)
            trailer = stream.read(8)
            return int.from_bytes(trailer[:4], "little"), int.from_bytes(trailer[4:], "little")
    except OSError as exc:
        raise ValueError(f"{archive} cannot be read ({exc})") from exc


def _identity(path: Path) -> Tuple[int, ...]:
    """
    Return what tells one file from another at ``path``: device, inode, size, modification and change times.

    :raises ValueError: When the file cannot be read.
    """
    try:
        status = path.stat()
    except OSError as exc:
        raise ValueError(f"{path} cannot be read ({exc})") from exc
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns


@functools.lru_cache(maxsize=4)
def _read_crc32(path: str, identity: Tuple[int, ...]) -> int:
    """
    Return the CRC-32 of a file, cached by its identity like the archive reads.

    :raises ValueError: When the file cannot be read.
    """
    crc = 0
    try:
        with open(path, "rb") as stream:
            while block := stream.read(16 * 1024 * 1024):
                crc = zlib.crc32(block, crc)
    except OSError as exc:
        raise ValueError(f"{path} cannot be read ({exc})") from exc
    return crc


def _crc32(path: Path) -> int:
    """Return the CRC-32 of ``path`` through the cache, keyed by its current identity."""
    return _read_crc32(str(path), _identity(path))


@functools.lru_cache(maxsize=4)
def _read_archive(archive: str, identity: Tuple[int, ...]) -> Tuple[int, bytes, int]:
    """
    Read a gzip archive to its end; return its unpacked size, first 16 bytes and CRC-32.

    Keyed by the file's identity too (device, inode, size, modification and change
    times), so the checks of one batch read a 550 MB archive once, and a replaced
    archive is read again even when its size and modification time were kept (#1560).

    :raises ValueError: When the archive is damaged, truncated or unreadable.
    """
    total, head, crc = 0, b"", 0
    try:
        with gzip.open(archive, "rb") as stream:
            while block := stream.read(16 * 1024 * 1024):
                head = head or block[: len(SQLITE_HEADER)]
                total += len(block)
                crc = zlib.crc32(block, crc)
    except (EOFError, OSError, zlib.error) as exc:
        raise ValueError(f"{archive} cannot be unpacked ({exc})") from exc
    return total, head, crc


def _unpack(archive: Path) -> Tuple[int, bytes, int]:
    """Read ``archive`` through the cache, keyed by its current identity."""
    return _read_archive(str(archive), _identity(archive))


def ncit_authority_problems(raw_dir: Path, *, repo_root: Path = REPO_ROOT) -> List[str]:
    """
    Report an ``ncit.db`` a run could not read from ``raw_dir``, or should not.

    The NCIT category policy reads ``ncit.db`` whenever a source declares one of its
    classes, and FOODON does, so the ontologies source needs it when it finalizes
    (#1526); ``ontologies_stubs`` and MediaDive read it too (#1557). A run unpacks ``ncit.db.gz`` only when
    ``ncit.db`` is missing and never replaces an existing copy. So an existing
    ``ncit.db`` must start as a SQLite database and, with the archive beside it, have
    the size and CRC-32 of the archive unpacked: otherwise a newer download would be
    read silently in its place (#1536). The CRC-32 tells apart two releases of one size
    (#1563); for a single-member archive it is read from the trailer and compared with
    one read of ``ncit.db``, cached by file identity. The run's receipt records the
    release it read. Without ``ncit.db``, the archive is read to its
    end, so a truncated or empty download fails here rather than hours in (#1535,
    #1544). Both files must resolve inside ``raw_dir``.

    :param raw_dir: The raw input directory a run will read.
    :param repo_root: Repository root holding ``download.yaml``.
    :return: A message when ``ncit.db`` would be unavailable or stale, otherwise nothing.
    """
    raw_dir = Path(raw_dir)
    database, archive = raw_dir / "ncit.db", raw_dir / "ncit.db.gz"
    tag = _download_tags(repo_root).get("ncit.db.gz")
    fetch = f"kg download -t {tag}" if tag else "the download.yaml entry for ncit.db.gz"
    for candidate in (database, archive):
        try:
            present = candidate.exists() or candidate.is_symlink()
            if present and not candidate.resolve().is_relative_to(raw_dir.resolve()):
                return [
                    f"{candidate} resolves outside {raw_dir}; the NCIT category policy reads only files "
                    "inside the selected raw directory. Put the file itself there."
                ]
        except (OSError, RuntimeError) as exc:  # RuntimeError: a symlink loop
            return [f"{candidate} cannot be resolved ({exc}). Put the file itself in {raw_dir}."]
    if database.is_file():
        try:
            with database.open("rb") as stream:
                header = stream.read(len(SQLITE_HEADER))
        except OSError as exc:
            return [f"{database} cannot be read ({exc})."]
        if header != SQLITE_HEADER:
            return [f"{database} is not a SQLite database. Delete it; the run then unpacks ncit.db.gz (`{fetch}`)."]
        if not archive.is_file():
            return []
        size = database.stat().st_size
        unusable = (
            "The run would read the existing ncit.db instead; fetch the archive again with "
            f"`{fetch} -i`, or move it aside to keep the database."
        )
        try:
            crc, isize = _gzip_trailer(archive)
        except ValueError as exc:
            return [f"{exc}. {unusable}"]
        try:
            # Only a matching size is worth reading 2.7 GB for.
            database_crc = _crc32(database) if isize == size % 2**32 else None
        except ValueError as exc:
            return [f"{exc}."]
        if database_crc == crc:
            return []
        try:
            unpacked, head, unpacked_crc = _unpack(archive)
        except ValueError as exc:
            return [f"{exc}. {unusable}"]
        if unpacked == size and database_crc is None:  # a multi-member archive
            try:
                database_crc = _crc32(database)
            except ValueError as exc:
                return [f"{exc}."]
        if unpacked == size and unpacked_crc == database_crc:
            return []
        if head != SQLITE_HEADER:
            # Deleting the database for this archive would leave no working copy (#1559).
            return [f"{archive} does not unpack to a SQLite database ({unpacked:,} bytes unpacked). {unusable}"]
        if unpacked == size:
            return [
                f"{database} has the size of the ncit.db.gz beside it ({size:,} bytes) but not its content "
                f"(CRC-32 {database_crc:08x}; the archive unpacks to {unpacked_crc:08x}), so it is another "
                "release. The run reads an existing ncit.db and never replaces it: delete it to use the "
                "archive, or move the archive aside to keep the database."
            ]
        return [
            f"{database} ({size:,} bytes) is not the copy of the ncit.db.gz beside it, which unpacks to "
            f"{unpacked:,} bytes. The run reads an existing ncit.db and never replaces it: delete it to use "
            "the archive, or move the archive aside to keep the database."
        ]
    if archive.is_file():
        try:
            unpacked, head, _ = _unpack(archive)
        except ValueError as exc:
            return [f"{exc}. Fetch it again with `{fetch} -i`."]
        if head != SQLITE_HEADER:
            return [
                f"{archive} does not unpack to a SQLite database ({unpacked:,} bytes unpacked). "
                f"Fetch it again with `{fetch} -i`."
            ]
        return []
    return [
        f"Neither ncit.db nor ncit.db.gz is in {raw_dir}; ontologies_stubs reads ncit.db, and so does the "
        f"NCIT category policy when FOODON and other sources finalize. Fetch it with `{fetch}`."
    ]


def release_input_problems(raw_dir: Path, *, repo_root: Path = REPO_ROOT, ontology: Optional[str] = None) -> List[str]:
    """
    Run the checks in this module against ``raw_dir``.

    :param raw_dir: The raw input directory a run will read.
    :param repo_root: Repository root holding ``mappings/`` and ``download.yaml``.
    :param ontology: A single ontology to check only the files its run reads (#1534);
        every file when omitted.
    :return: One message per problem; empty when the inputs are ready.
    """
    names = None if ontology is None else SINGLE_ONTOLOGY_INPUTS.get(ontology, frozenset())
    pins = reviewed_release_pins(repo_root)
    if names is not None:
        pins = {name: digests for name, digests in pins.items() if name in names}
    return [
        *mismatched_release_files(raw_dir, repo_root=repo_root, pins=pins),
        *stale_derived_files(raw_dir, repo_root=repo_root, names=names),
        *(ncit_authority_problems(raw_dir, repo_root=repo_root) if names is None or "ncit.db" in names else []),
    ]


def main(argv: Optional[List[str]] = None) -> int:
    """
    Check a raw directory without starting a run.

    :param argv: ``[RAW_DIR]``; ``data/raw`` under the repository by default.
    :return: 0 when the inputs are ready, 1 when there are problems.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Check the reviewed upstream inputs in a raw directory (#1420).")
    parser.add_argument("raw_dir", nargs="?", type=Path, default=REPO_ROOT / "data" / "raw")
    args = parser.parse_args(argv)
    problems = release_input_problems(args.raw_dir)
    for problem in problems:
        print(f"- {problem}")
    if not problems:
        print(f"Every reviewed upstream input in {args.raw_dir} is ready.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
