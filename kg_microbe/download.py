"""Download resources from YAML file."""

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
