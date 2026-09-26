"""
Record which URL produced each downloaded artifact, and re-fetch when it changes.

``kghub_downloader`` decides whether to download by asking whether the file
exists, and stores nothing about where it came from. So editing a pinned version
in ``download.yaml`` changes nothing on disk: the run reports success and the
pipeline keeps consuming the old artifact, with the declared pin and the cached
bytes silently disagreeing. That is how a METPO pin moved three releases while
``data/raw/metpo.json`` stayed on the version before it (#900, #911).

Existence is the wrong cache key. This module makes the URL part of it: a file
whose recorded URL no longer matches the declared one is removed before the
download runs, so the next ordinary ``kg download`` picks up the change.

A file with **no** record is left alone. Every artifact predates this manifest,
so treating "unknown" as "stale" would re-fetch the entire corpus on the first
run -- including an hour of MediaDive crawling -- to learn what is already known.
Records accumulate as things are downloaded.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)

#: Sits beside the artifacts it describes, under the gitignored data directory.
MANIFEST_NAME = ".download_manifest.json"


def manifest_path(output_dir: str) -> Path:
    """
    Return the manifest location for a download directory.

    :param output_dir: Directory downloads are written to.
    :return: Path to the manifest, which may not exist.
    """
    return Path(output_dir) / MANIFEST_NAME


def read_manifest(output_dir: str) -> Dict[str, str]:
    """
    Return the recorded ``local_name -> url`` map.

    :param output_dir: Directory downloads are written to.
    :return: Mapping, empty when absent or unreadable. A corrupt manifest is
        treated as no manifest: it must never be able to block a download.
    """
    path = manifest_path(output_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("[download] ignoring unreadable %s", path)
        return {}
    recorded = payload.get("artifacts")
    return recorded if isinstance(recorded, dict) else {}


def _selected_entries(yaml_file: str, tags: Optional[Sequence[str]]) -> List[dict]:
    with open(yaml_file) as handle:
        entries = yaml.safe_load(handle) or []
    return [e for e in entries if isinstance(e, dict) and (not tags or e.get("tag") in tags)]


def _local_name(entry: dict) -> Optional[str]:
    name = entry.get("local_name")
    if name:
        return str(name)
    url = entry.get("url") or ""
    return url.rsplit("/", 1)[-1] or None


def stale_by_url(yaml_file: str, output_dir: str, tags: Optional[Sequence[str]] = None) -> List[Path]:
    """
    Return downloaded files whose recorded URL no longer matches the config.

    :param yaml_file: Download config being applied.
    :param output_dir: Directory downloads are written to.
    :param tags: Tags this run is restricted to, or None for all.
    :return: Paths that exist on disk and came from a different URL.
    """
    recorded = read_manifest(output_dir)
    stale = []
    for entry in _selected_entries(yaml_file, tags):
        name = _local_name(entry)
        url = entry.get("url")
        if not name or not url:
            continue
        was = recorded.get(name)
        if was is None or was == url:
            # No record means unknown provenance, not wrong provenance.
            continue
        path = Path(output_dir) / name
        if path.exists():
            stale.append(path)
    return stale


def drop_stale(yaml_file: str, output_dir: str, tags: Optional[Sequence[str]] = None) -> List[Path]:
    """
    Remove artifacts whose declared URL has changed, so they are fetched again.

    :param yaml_file: Download config being applied.
    :param output_dir: Directory downloads are written to.
    :param tags: Tags this run is restricted to, or None for all.
    :return: Paths removed.
    """
    stale = stale_by_url(yaml_file, output_dir, tags)
    for path in stale:
        logger.info("[download] %s came from a different URL than download.yaml declares; re-fetching", path.name)
        print(f"[download] re-fetching {path.name}: its recorded URL differs from the one declared in the config")
        path.unlink(missing_ok=True)
    return stale


def record(
    yaml_file: str,
    output_dir: str,
    tags: Optional[Sequence[str]] = None,
    skip_names: Optional[Sequence[str]] = None,
) -> int:
    """
    Record the URL behind every artifact this run left on disk.

    Only files that exist are recorded, so a skipped or failed entry does not
    gain a provenance claim it has not earned. ``skip_names`` excludes entries
    the caller knows were never downloaded -- pending-hosting sources are
    satisfied by hand, so their artifact exists without having come from the
    placeholder URL in the config (#929).

    :param yaml_file: Download config that was applied.
    :param output_dir: Directory downloads were written to.
    :param tags: Tags this run was restricted to, or None for all.
    :param skip_names: Local names to leave unrecorded.
    :return: Number of artifacts recorded.
    """
    from kg_microbe.utils.atomic_io import atomic_write

    excluded = set(skip_names or ())
    recorded = dict(read_manifest(output_dir))
    for entry in _selected_entries(yaml_file, tags):
        name = _local_name(entry)
        url = entry.get("url")
        if name and name not in excluded and url and (Path(output_dir) / name).exists():
            recorded[name] = url
    destination = manifest_path(output_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(destination) as handle:
        json.dump({"artifacts": dict(sorted(recorded.items()))}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return len(recorded)
