"""Download resources from YAML file."""

import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import yaml
from kghub_downloader.download_utils import download_from_yaml

from kg_microbe.utils.mediadive_bulk_download import download_mediadive_bulk

# Tag (in download.yaml) of the entry that pulls the MediaDive media list. A
# tag-filtered run only does the follow-on bulk API download when MediaDive is
# among the requested tags — otherwise `kg download -t ontologies` would kick
# off an hour of MediaDive API calls just because mediadive.json is on disk
# from an earlier run.
MEDIADIVE_TAG = "mediadive"

# Marker for a source whose original URL is dead and whose replacement copy is
# not hosted yet (see the "pending hosting" note in download.yaml). Such entries
# are declared normally — so they carry a tag, appear in the config, and start
# working the moment a real URL is pasted in — but are skipped at download time.
# Without the skip, the placeholder URL would raise and abort the whole run.
PENDING_HOSTING_MARKER = "REPLACE_ME_"


def download(
    yaml_file: str,
    output_dir: str,
    snippet_only: bool,
    ignore_cache: bool = False,
    tags: Optional[Sequence[str]] = None,
) -> None:
    """
    Download data files from list of URLs.

    DL based on config (default: download.yaml)
    into data directory (default: data/).

    :param yaml_file: A string pointing to the yaml file
    :param utilized to facilitate the downloading of data.
    :param output_dir: A string pointing to the location to download data to.
    :param snippet_only: Downloads only the first 5 kB of the source,for testing and file checks.
    :param ignore_cache: Ignore cache and download files even if they exist [false]
    :param tags: Only download entries carrying one of these tags. None or empty
        means download everything.
    :return: None.
    """
    tags = list(tags) if tags else None
    if tags:
        _validate_tags(yaml_file, tags)

    effective_yaml, pending = _without_pending_hosting(yaml_file, tags)
    if pending:
        _report_pending(pending)

    try:
        download_from_yaml(
            yaml_file=effective_yaml,
            output_dir=output_dir,
            snippet_only=snippet_only,
            ignore_cache=ignore_cache,
            tags=tags,
        )
    finally:
        if effective_yaml != yaml_file:
            Path(effective_yaml).unlink(missing_ok=True)

    # Post-download: Trigger MediaDive bulk download if mediadive.json was downloaded
    if snippet_only:  # Skip bulk download in snippet mode
        return
    if tags and MEDIADIVE_TAG not in tags:
        return
    _post_download_mediadive_bulk(output_dir, ignore_cache)


def _without_pending_hosting(yaml_file: str, tags: Optional[Sequence[str]]) -> Tuple[str, List[dict]]:
    """
    Split off entries still carrying a hosting placeholder.

    kghub-downloader reads the config file itself and aborts the whole run on the
    first download error, so a placeholder URL cannot simply be left in place.
    When any is present we hand the downloader a filtered copy of the config
    instead.

    :param yaml_file: Path to the download config.
    :param tags: Tags the run is restricted to, or None for all.
    :return: (config path to use, list of skipped entries). The path is the
        original when nothing is pending; otherwise a temp file the caller must
        delete.
    """
    with open(yaml_file) as f:
        entries = yaml.safe_load(f) or []

    def is_pending(entry: dict) -> bool:
        """Report whether this entry's URL is still a hosting placeholder."""
        return PENDING_HOSTING_MARKER in entry.get("url", "")

    # Only entries this run would actually have attempted are worth reporting.
    selected = [e for e in entries if not tags or e.get("tag") in tags]
    pending = [e for e in selected if is_pending(e)]
    if not pending:
        return yaml_file, []

    ready = [e for e in entries if not is_pending(e)]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(ready, tmp, sort_keys=False)
        return tmp.name, pending


def _report_pending(pending: Sequence[dict]) -> None:
    """
    Tell the user which sources were skipped and why.

    A silent skip would look like a successful download of a file that never
    arrived — the same failure mode as an unknown tag.

    :param pending: Entries skipped because their URL is a placeholder.
    """
    print(f"\nSkipping {len(pending)} source(s) whose replacement copy is not hosted yet:")
    for entry in pending:
        print(f"  - {entry.get('local_name')} (tag: {entry.get('tag')})")
    print("  Copy these from a reference data/raw_* directory, or paste the real")
    print("  URL over the REPLACE_ME_ placeholder in download.yaml once hosted.\n")


def _validate_tags(yaml_file: str, tags: Sequence[str]) -> None:
    """
    Fail fast on a tag that matches nothing in the YAML.

    kghub-downloader silently downloads zero files for an unknown tag, which
    looks exactly like a successful no-op run.

    :param yaml_file: Path to the download config being filtered.
    :param tags: Tags requested on the command line.
    :raises ValueError: If any tag matches no entry.
    """
    with open(yaml_file) as f:
        entries = yaml.safe_load(f) or []
    known = {entry.get("tag") for entry in entries if entry.get("tag")}
    unknown = sorted(set(tags) - known)
    if unknown:
        raise ValueError(
            f"Unknown download tag(s): {', '.join(unknown)}. Available tags in {yaml_file}: {', '.join(sorted(known))}"
        )


def _post_download_mediadive_bulk(output_dir: str, ignore_cache: bool = False) -> None:
    """
    Download bulk MediaDive data after basic mediadive.json is downloaded.

    This function checks if mediadive.json exists and if so, downloads all
    detailed MediaDive data (recipes, strains, solutions, compounds) to avoid
    API calls during transform.

    :param output_dir: Output directory where data is downloaded
    :param ignore_cache: If True, re-download even if bulk files exist, and
        discard cached HTTP responses so the API is actually re-queried
    """
    mediadive_basic_file = Path(output_dir) / "mediadive.json"
    mediadive_bulk_dir = Path(output_dir) / "mediadive"

    # Check if basic mediadive.json was downloaded
    if not mediadive_basic_file.exists():
        return  # MediaDive not being downloaded, skip bulk download

    # Check if bulk data already exists (unless ignore_cache is True)
    # Also verify files are not empty (> 10 bytes to account for "{}" or "[]")
    if not ignore_cache and mediadive_bulk_dir.exists():
        required_files = [
            "media_detailed.json",
            "media_strains.json",
            "solutions.json",
            "compounds.json",
        ]
        all_valid = all(
            (mediadive_bulk_dir / f).exists() and (mediadive_bulk_dir / f).stat().st_size > 10 for f in required_files
        )
        if all_valid:
            print(f"MediaDive bulk data already exists in {mediadive_bulk_dir}/")
            print("  Skipping bulk download (use --ignore-cache to force re-download)")
            return

    # Run bulk download
    print("\n" + "=" * 80)
    print("Starting MediaDive bulk download...")
    print("=" * 80)
    download_mediadive_bulk(str(mediadive_basic_file), str(mediadive_bulk_dir), ignore_cache=ignore_cache)
    print("=" * 80)
    print("MediaDive bulk download complete!")
    print("=" * 80 + "\n")
