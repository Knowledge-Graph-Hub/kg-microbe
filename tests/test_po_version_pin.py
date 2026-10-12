"""Every PO artifact must be pinned to one release commit: the release its reviewed category policy names."""

import json
import re
from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    PO_COMMIT,
    PO_IMPORT_MODULES,
    PO_IMPORTS_DIR,
    PO_RAW_URL,
    PO_VERSION_IRI,
)
from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import _declared_imports

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"
FINITE_PO_POLICY = REPO_ROOT / "mappings" / "finite_envo_po_category_dispositions.json"
# The head of the pinned po.owl, with its versionIRI and owl:imports.
PO_OWL_HEADER = REPO_ROOT / "tests" / "resources" / "po" / "po_owl_header.owl"
_PO_PURL = "http://purl.obolibrary.org/obo/po/"
# PO's own PURLs (`obo/po.owl`, `obo/po.json`, `obo/po/...`) and the GitHub repository they redirect to.
_PO_URL = re.compile(r"purl\.obolibrary\.org/obo/po[./_-]|Planteome/plant-ontology/")


def _po_entries():
    """
    Every download.yaml entry that saves a PO file or fetches from PO.

    :return: List of download entries.
    """
    entries = yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8"))
    return [
        e
        for e in entries
        if isinstance(e, dict)
        and (
            e.get("local_name") == "po.owl"
            or str(e.get("local_name", "")).startswith(f"{PO_IMPORTS_DIR}/")
            or _PO_URL.search(str(e.get("url", "")))
        )
    ]


def test_po_and_its_imports_are_downloaded_at_the_release_commit():
    """
    The unversioned PURL serves PO's master branch, so PO could change with no change here.

    po.owl also imports two modules by unversioned IRI, which ROBOT fetched
    from master on every run; the catalog can only resolve the copies
    `kg download` fetched. Any other PO download, unpinned, fails this too.
    """
    by_name = {e["local_name"]: e["url"] for e in _po_entries()}
    expected = {"po.owl": f"{PO_RAW_URL}/po.owl"}
    expected.update({f"{PO_IMPORTS_DIR}/{name}": f"{PO_RAW_URL}/imports/{name}" for name in PO_IMPORT_MODULES})
    assert by_name == expected


def test_the_pin_is_a_commit_not_a_tag_or_branch():
    """PO's release tags are lightweight and hand-named; only a full commit hash cannot move."""
    assert re.fullmatch(r"[0-9a-f]{40}", PO_COMMIT)
    assert PO_RAW_URL == f"https://raw.githubusercontent.com/Planteome/plant-ontology/{PO_COMMIT}"


def test_the_release_is_the_one_the_category_policy_was_reviewed_against():
    """
    The finite PO category decisions name a release and its sha256, and refuse any other bytes.

    With the download pinned elsewhere, `kg download` would fetch a po.owl
    the policy rejects; bumping the pin means re-reviewing the policy.
    """
    policy = json.loads(FINITE_PO_POLICY.read_text(encoding="utf-8"))
    assert policy["authorities"]["po.owl"]["version"] == PO_VERSION_IRI


def test_each_import_is_fetched_from_the_release_at_its_own_path():
    """
    po.owl imports `obo/po/imports/<name>`; the pin must fetch that same path from the release commit.

    The catalog matches a module by file name alone, so a module fetched from
    another path under the release would be accepted without complaint.
    """
    downloaded = {e["url"] for e in _po_entries()}
    declared = _declared_imports(PO_OWL_HEADER)
    assert len(declared) == len(PO_IMPORT_MODULES)
    for iri in declared:
        assert iri.startswith(_PO_PURL), iri
        assert f"{PO_RAW_URL}/{iri.removeprefix(_PO_PURL)}" in downloaded, iri
