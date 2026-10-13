"""Where kghub-downloader writes a download.yaml entry, for tests that compare entries."""

import posixpath
from urllib.parse import urlparse


def download_destination(entry: dict) -> str:
    """
    Return the file an entry is saved to, spelled one way.

    kghub-downloader saves to ``output_dir / (local_name or the URL's last path
    segment)``, so ``./a`` and ``a`` name one file, and on a case-insensitive
    file system (macOS) so do ``A`` and ``a``. Comparing raw ``local_name``
    strings would treat each spelling as a different file.

    :param entry: One download.yaml entry.
    :return: The normalised, case-folded relative path; empty if the entry names none.
    """
    name = entry.get("local_name") or posixpath.basename(urlparse(str(entry.get("url") or "")).path)
    return posixpath.normpath(name).casefold() if name else ""
