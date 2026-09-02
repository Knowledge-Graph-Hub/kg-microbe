"""Every METPO artifact must be pinned, and pinned to the same release (#900)."""

import re
from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    METPO_CLASSES_ROBOT_TEMPLATE_URL,
    METPO_JSON_URL,
    METPO_OWL_URL,
    METPO_PROPERTIES_ROBOT_TEMPLATE_URL,
    METPO_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"


def _metpo_urls():
    """
    Every berkeleybop/metpo URL in download.yaml.

    :return: List of URL strings.
    """
    entries = yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8"))
    return [e["url"] for e in entries if isinstance(e, dict) and "berkeleybop/metpo" in str(e.get("url", ""))]


def test_download_yaml_pins_every_metpo_artifact_to_a_tag():
    """
    An unpinned fetch changes what the pipeline sees with no record that it did.

    `metpo.owl` and `metpo.json` were pulled from `refs/heads/main`, so an upstream
    obsoletion arrived with a download and altered nothing observable — which is how
    706,765 edges came to use a deprecated predicate (#909).
    """
    urls = _metpo_urls()
    assert urls, "download.yaml no longer fetches METPO; this guard needs rewriting"
    unpinned = [u for u in urls if "refs/tags/" not in u]
    assert not unpinned, f"METPO must be fetched from a tag, not a branch: {unpinned}"


def test_every_metpo_artifact_is_pinned_to_the_same_release():
    """
    The ontology and the templates built from it must move together.

    They drifted three releases apart — the ontology tracking `main` while the
    templates sat on `2026-03-24` — and the mismatch is what hid #909.
    """
    tags = {re.search(r"refs/tags/([^/]+)/", u).group(1) for u in _metpo_urls()}
    assert tags == {METPO_VERSION}, f"download.yaml pins {sorted(tags)}, constants says {METPO_VERSION}"


def test_the_code_and_download_yaml_agree_on_the_version():
    """
    `download.yaml` cannot import the constant, so the two are checked against each other.

    `mapping_file_utils` used to carry its own copy of the tag, which is how one of
    them fell behind without the other noticing.
    """
    urls = set(_metpo_urls())
    for url in (METPO_OWL_URL, METPO_JSON_URL, METPO_CLASSES_ROBOT_TEMPLATE_URL, METPO_PROPERTIES_ROBOT_TEMPLATE_URL):
        assert url in urls, f"{url} is used by the code but not fetched by download.yaml"


def test_mapping_file_utils_does_not_keep_its_own_copy_of_the_pin():
    """One version, one place. A second literal is what drifted last time."""
    source = (REPO_ROOT / "kg_microbe" / "utils" / "mapping_file_utils.py").read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/berkeleybop/metpo" not in source
