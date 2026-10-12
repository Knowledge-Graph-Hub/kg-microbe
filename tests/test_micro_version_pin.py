"""Every MicrO artifact must be pinned, and pinned to the same commit."""

from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    MICRO_COMMIT,
    MICRO_IMPORT_MODULES,
    MICRO_IMPORTS_DIR,
    MICRO_RAW_URL,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = REPO_ROOT / "download.yaml"


def _micro_entries():
    """
    Every carrineblank/MicrO entry in download.yaml.

    :return: List of download entries.
    """
    entries = yaml.safe_load(DOWNLOAD_YAML.read_text(encoding="utf-8"))
    return [e for e in entries if isinstance(e, dict) and "carrineblank/MicrO/" in str(e.get("url", ""))]


def test_download_yaml_pins_every_micro_artifact_to_the_commit():
    """
    MicrO has no releases, so a branch URL changes the stub hierarchy with no change here.

    The ontology came from `master`, and so did the 20 modules it imports, which
    ROBOT fetched live on every run.
    """
    urls = [e["url"] for e in _micro_entries()]
    assert urls, "download.yaml no longer fetches MicrO; this guard needs rewriting"
    unpinned = [u for u in urls if not u.startswith(f"{MICRO_RAW_URL}/")]
    assert not unpinned, f"MicrO must be fetched at {MICRO_COMMIT}, not a branch: {unpinned}"


def test_the_ontology_and_every_import_module_are_downloaded():
    """The catalog can only resolve modules that `kg download` actually fetched."""
    by_name = {e["local_name"]: e["url"] for e in _micro_entries()}
    expected = {"micro.owl": f"{MICRO_RAW_URL}/MicrO.owl"}
    expected.update({f"{MICRO_IMPORTS_DIR}/{name}": f"{MICRO_RAW_URL}/{name}" for name in MICRO_IMPORT_MODULES})
    assert by_name == expected
