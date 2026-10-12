"""Inputs bound by reviewed policies are fetched from immutable release URLs (#1420)."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"

# Each URL was downloaded on 2026-10-12 and was byte-identical to the input the
# reviewed policies were checked against. A rolling URL serves whatever is newest,
# and a newer release fails those policies' pins in a fresh checkout.
REVIEWED_RELEASE_URLS = {
    "envo.json": "http://purl.obolibrary.org/obo/envo/releases/2026-06-26/envo.json",
    "go.owl": "https://release.geneontology.org/2026-06-19/ontology/go.owl",
    "uberon.owl": "https://github.com/obophenotype/uberon/releases/download/v2026-06-23/uberon.owl",
    "foodon.owl": (
        "https://raw.githubusercontent.com/FoodOntology/foodon/68e46c14599d24b531fb4dac984659fb3c9fdb72/foodon.owl"
    ),
    "pato.owl": "http://purl.obolibrary.org/obo/pato/releases/2025-05-14/pato.owl",
    "upa.owl": (
        "https://raw.githubusercontent.com/geneontology/unipathway/2094080b928bd0af5346e37a4f0071c687bba7e2/upa.owl"
    ),
    "microbedecoder_database.zip": (
        "https://github.com/thackmann/MicrobeDecoder/raw/ff90e9aa63ae7c9c54b6e010feba3c0424d35a37/"
        "Shiny/MicrobeDecoder/data/database/database.zip"
    ),
    "ro.owl": "http://purl.obolibrary.org/obo/ro/releases/2025-12-17/ro.owl",
    "po.owl": "http://purl.obolibrary.org/obo/po/releases/2026-01-09/po.owl",
    "mondo.json": "http://purl.obolibrary.org/obo/mondo/releases/2026-07-06/mondo.json",
    # The archive itself is not pinned: its two members are, byte for byte, by
    # mappings/rhea_release.json, and stage_snapshot extracts only those.
    "rhea_download/142.tar.bz2": "https://ftp.expasy.org/databases/rhea/old_releases/142.tar.bz2",
}

# A dated release directory or tag, a 40-hex commit, or a numbered release
# archive identifies one release.
_IMMUTABLE = re.compile(r"/v?\d{4}-\d{2}-\d{2}/|/[0-9a-f]{40}/|/old_releases/\d+\.tar\.bz2$")


def _urls_by_local_name():
    """
    Map each download.yaml local name to the URLs that fetch it.

    :return: ``{local_name: [url, ...]}``.
    """
    urls = {}
    for entry in yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8")):
        if isinstance(entry, dict) and entry.get("local_name"):
            urls.setdefault(entry["local_name"], []).append(entry["url"])
    return urls


def test_reviewed_inputs_are_fetched_from_their_reviewed_release():
    """A fresh `kg download` must fetch exactly the release the policies were reviewed against."""
    urls = _urls_by_local_name()
    for name, expected in REVIEWED_RELEASE_URLS.items():
        assert urls.get(name) == [expected], f"{name}: {urls.get(name)}"


def test_reviewed_release_urls_name_one_release():
    """None of the pinned URLs may be a rolling alias such as a bare PURL, `master` or `main`."""
    for name, url in REVIEWED_RELEASE_URLS.items():
        assert _IMMUTABLE.search(url), f"{name} is not fetched from an immutable release URL: {url}"
        assert "/raw/main/" not in url and "/raw/master/" not in url, name
