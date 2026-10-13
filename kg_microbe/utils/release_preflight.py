"""
Check the reviewed upstream inputs before a long ontology run starts (#1420).

The ontology policies bind raw upstream release files by SHA-256: the OWL each
converted JSON is built from, the JSON releases read directly and the ``go.owl``
behind ``go.db``; the NCIT and MeSH policies pin the Biolink model. Each policy
checks its pins only when its source finalizes, so a stale or rewritten download
used to fail after hours of NCBITaxon and ChEBI work. This module collects those
pins from the policies themselves and compares them with the raw directory before
the ontologies source, or a single ontology, runs. It also checks two things a run
would otherwise discover late: that ``ncit.db`` (or a sound archive to unpack it
from) is inside the raw directory, and that an existing ``upa.json`` is the pinned
conversion. It reads the policies' pins and never replaces them. Other sources'
pins (Rhea, MicrobeDecoder) are checked when those sources run.

Run ``python -m kg_microbe.utils.release_preflight [RAW_DIR]`` to check without
starting a run.
"""

import gzip
import hashlib
import json
import re
import zlib
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import yaml

from kg_microbe.utils.atomic_io import gzip_isize

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


# The files each single-ontology run (`kg transform -s <name>`) reads, so it is checked
# for those only (#1534); the whole ontologies source checks every file. "ncit.db" stands
# for the NCIT check: FOODON declares NCIT category classes. A category policy reads its
# file only when a source declares one of its reviewed classes, and no single ontology
# declares the PO class, so po.owl is checked only for the whole ontologies source.
SINGLE_ONTOLOGY_INPUTS: Dict[str, frozenset] = {
    "envo": frozenset({"envo.json"}),
    "foodon": frozenset({"foodon.owl", "biolink-model.yaml", "ncit.db"}),
    "go": frozenset({"go.owl"}),
    "mondo": frozenset({"mondo.json"}),
    "pato": frozenset({"pato.owl", "go.owl"}),
    "ro": frozenset({"ro.owl"}),
    "uberon": frozenset({"uberon.owl"}),
    "upa": frozenset({"upa.owl", "go.owl", "upa.json"}),
}
WHOLE_RUN_ONLY = frozenset({"po.owl"})


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
    :param pins: Pins to check instead of the reviewed policies' (tests only).
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


def ncit_authority_problems(raw_dir: Path, *, repo_root: Path = REPO_ROOT) -> List[str]:
    """
    Report an ``ncit.db`` the NCIT category policy could not read from ``raw_dir``.

    The policy reads ``ncit.db`` whenever a source declares one of its classes, and
    FOODON does, so the ontologies source needs it when it finalizes (#1526). The run
    unpacks it from ``ncit.db.gz`` when it is missing or older than the archive
    (#1536), so then the archive is read to its end here: a truncated download would
    otherwise fail only hours in (#1535). Both files must resolve inside ``raw_dir``.

    :param raw_dir: The raw input directory a run will read.
    :param repo_root: Repository root holding ``download.yaml``.
    :return: A message when ``ncit.db`` would be unavailable, otherwise nothing.
    """
    raw_dir = Path(raw_dir)
    database, archive = raw_dir / "ncit.db", raw_dir / "ncit.db.gz"
    tag = _download_tags(repo_root).get("ncit.db.gz")
    fetch = f"kg download -t {tag}" if tag else "the download.yaml entry for ncit.db.gz"
    for candidate in (database, archive):
        if (candidate.exists() or candidate.is_symlink()) and not candidate.resolve().is_relative_to(raw_dir.resolve()):
            return [
                f"{candidate} resolves outside {raw_dir}; the NCIT category policy reads only files "
                "inside the selected raw directory. Put the file itself there."
            ]
    if archive.is_file():
        if database.is_file() and database.stat().st_size % 2**32 == gzip_isize(archive):
            return []
        try:
            with gzip.open(archive, "rb") as stream:
                while stream.read(16 * 1024 * 1024):
                    pass
        except (EOFError, gzip.BadGzipFile, zlib.error, OSError) as exc:
            return [f"{archive} cannot be unpacked ({exc}). Fetch it again with `{fetch} -i`."]
        return []
    if database.is_file():
        return []
    return [
        f"Neither ncit.db nor ncit.db.gz is in {raw_dir}; the NCIT category policy reads ncit.db "
        f"when FOODON and other sources finalize. Fetch it with `{fetch}`."
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
