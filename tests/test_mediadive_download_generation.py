"""The public download boundary admits generation evidence, never old file-size heuristics."""

import importlib
import json
from unittest.mock import Mock

import pytest

from kg_microbe.transform_utils.mediadive import acquisition
from tests.mediadive_generation_fixtures import seal_fixture_raw

download = importlib.import_module("kg_microbe.download")


def _generation(tmp_path):
    """Build explicit native evidence through the real offline generation writer."""
    bulk = tmp_path / "mediadive"
    bulk.mkdir()
    catalogue = {"status": 200, "count": 1, "data": [{"id": 1, "name": "Synthetic medium"}]}
    (tmp_path / "mediadive.json").write_text(json.dumps(catalogue, indent=2) + "\n")
    for name, value in {
        "media_detailed.json": {"1": {"medium": {"id": 1}}},
        "media_strains.json": {},
        "solutions.json": {},
        "compounds.json": {},
    }.items():
        (bulk / name).write_text(json.dumps(value) + "\n")
    return seal_fixture_raw(tmp_path)


def test_public_hook_replays_sealed_explicit_empty_without_http(tmp_path, monkeypatch):
    """A valid explicit-empty response remains distinct and reusable without reacquisition."""
    view = _generation(tmp_path)
    network = Mock(side_effect=AssertionError("No HTTP during persisted admission"))
    monkeypatch.setattr(acquisition, "acquire_endpoints", network)
    download._post_download_mediadive_bulk(str(tmp_path))
    network.assert_not_called()
    assert view.endpoint_states["https://mediadive.dsmz.de/rest/medium-strains/1"] == "explicit_empty"
    assert view.qualification["association_coverage_complete"] is True


def test_public_hook_refuses_corrupt_generation_without_legacy_fallback(tmp_path, monkeypatch):
    """Large old files cannot hide changed outcomes or trigger automatic replacement acquisition."""
    view = _generation(tmp_path)
    (view.generation_dir / "endpoint-outcomes.json").write_text('{"changed": true}\n')
    network = Mock(side_effect=AssertionError("Corrupt evidence must fail before HTTP"))
    monkeypatch.setattr(acquisition, "acquire_endpoints", network)
    with pytest.raises(ValueError, match="Generation member changed"):
        download._post_download_mediadive_bulk(str(tmp_path))
    network.assert_not_called()


def test_large_legacy_files_do_not_bypass_production_acquisition(tmp_path, monkeypatch):
    """The former four-file greater-than-ten-byte condition is no longer source admission."""
    _generation(tmp_path)
    for name in ("media_detailed.json", "media_strains.json", "solutions.json", "compounds.json"):
        (tmp_path / "mediadive" / name).write_text('{"legacy": "unverified large file"}\n')
    boundary = Mock()
    monkeypatch.setattr(download, "download_mediadive_bulk", boundary)
    download._post_download_mediadive_bulk(str(tmp_path))
    boundary.assert_called_once_with(str(tmp_path / "mediadive.json"), str(tmp_path / "mediadive"), ignore_cache=False)
