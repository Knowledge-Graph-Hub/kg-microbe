"""
Check every byte-pinned upstream release before a long run starts (#1420).

Reviewed policies bind the upstream release files their content comes from by
SHA-256: the OWL each converted JSON is built from, the JSON releases read
directly, and the ``go.owl`` behind ``go.db``. Each policy checks its pins only
when its source finalizes, so a stale or rewritten download used to fail after
hours of NCBITaxon and ChEBI work. This module collects those pins from the
policies themselves and compares them with the raw directory before any source
runs. It reads the policies' pins and never replaces them.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_FILE = re.compile(r"[a-z_]+\.(json|owl)")
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


# Every reviewed policy that pins a raw upstream release file by its bytes. A
# policy bound only by content (MeSH, NCIT, the LPSN GSS) has no entry here.
PINNING_POLICIES: Tuple[Tuple[str, Callable[[dict], List[Tuple[str, str]]]], ...] = (
    ("mappings/native_ro_predicate_dispositions.json", _authority_sources),
    ("mappings/finite_import_category_dispositions.json", _authority_sources),
    ("mappings/uberon_temporal_category_dispositions.json", _uberon_temporal),
    ("mappings/finite_envo_po_category_dispositions.json", _finite_envo_po),
    ("mappings/go_imported_subject_restrictions.json", _go_restrictions),
    ("mappings/upa_reaction_projection_dispositions.json", _upa_routes),
)


def reviewed_release_pins(repo_root: Path = REPO_ROOT) -> Dict[str, Dict[str, List[str]]]:
    """
    Collect the release files the reviewed policies pin.

    :param repo_root: Repository root holding ``mappings/``.
    :return: ``{file: {sha256: [policy, ...]}}``. More than one digest for a file
        means the policies disagree on its release.
    :raises ValueError: When a policy does not hold a well-formed pin where expected.
    """
    pins: Dict[str, Dict[str, List[str]]] = {}
    for relative, select in PINNING_POLICIES:
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
            policies = pins.setdefault(name, {}).setdefault(sha256, [])
            if relative not in policies:
                policies.append(relative)
    return pins


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
