"""Download resources from YAML file."""

from pathlib import Path

from kghub_downloader.download_utils import download_from_yaml


def download(
    yaml_file: str, output_dir: str, snippet_only: bool, ignore_cache: bool = False
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
    :return: None.
    """
    download_from_yaml(
        yaml_file=yaml_file,
        output_dir=output_dir,
        snippet_only=snippet_only,
        ignore_cache=ignore_cache,
    )

    # Post-download: Trigger MediaDive bulk download if mediadive.json was downloaded
    if not snippet_only:  # Skip bulk download in snippet mode
        _post_download_mediadive_bulk(output_dir, ignore_cache)


def _post_download_mediadive_bulk(output_dir: str, ignore_cache: bool = False) -> None:
    """
    Download bulk MediaDive data after basic mediadive.json is downloaded.

    This function checks if mediadive.json exists and if so, downloads all
    detailed MediaDive data (recipes, strains, solutions, compounds) to avoid
    API calls during transform.

    :param output_dir: Output directory where data is downloaded
    :param ignore_cache: If True, re-download even if bulk files exist
    """
    from kg_microbe.utils.mediadive_bulk_download import download_mediadive_bulk

    mediadive_basic_file = Path(output_dir) / "mediadive.json"
    mediadive_bulk_dir = Path(output_dir) / "mediadive"

    # Check if basic mediadive.json was downloaded
    if not mediadive_basic_file.exists():
        return  # MediaDive not being downloaded, skip bulk download

    # Check if bulk data already exists (unless ignore_cache is True)
    if not ignore_cache and mediadive_bulk_dir.exists():
        required_files = [
            "media_detailed.json",
            "media_strains.json",
            "solutions.json",
            "compounds.json",
        ]
        all_exist = all((mediadive_bulk_dir / f).exists() for f in required_files)
        if all_exist:
            print(f"MediaDive bulk data already exists in {mediadive_bulk_dir}/")
            print("  Skipping bulk download (use --ignore-cache to force re-download)")
            return

    # Run bulk download
    print("\n" + "=" * 80)
    print("Starting MediaDive bulk download...")
    print("=" * 80)
    download_mediadive_bulk(str(mediadive_basic_file), str(mediadive_bulk_dir))
    print("=" * 80)
    print("MediaDive bulk download complete!")
    print("=" * 80 + "\n")
