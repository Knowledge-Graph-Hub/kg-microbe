"""The MediaDive transform's HTTP cache is a session it owns, not a process-wide patch (#624)."""

from pathlib import Path
from unittest import mock

import requests
from requests_cache import CachedSession

from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform


def _bare_transform(tmp_path: Path) -> MediaDiveTransform:
    """Build a transform with __init__ skipped: the cache must not need any of the heavy loading."""
    xform = MediaDiveTransform.__new__(MediaDiveTransform)
    xform._http = None
    xform.bulk_data_dir = tmp_path / "raw" / "mediadive"
    return xform


def test_constructing_the_transform_leaves_requests_session_alone(tmp_path, monkeypatch):
    """The bug: install_cache() in __init__ made every requests.Session in the process a CachedSession."""
    monkeypatch.chdir(tmp_path)
    before = requests.Session
    with (
        mock.patch.object(MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(MediaDiveTransform, "_load_micromediaparam_mappings"),
        mock.patch.object(MediaDiveTransform, "_load_bulk_data"),
        mock.patch.object(mod, "ChemicalMappingLoader"),
    ):
        xform = MediaDiveTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    assert requests.Session is before
    assert type(requests.Session()) is requests.Session
    assert not hasattr(requests.Session(), "cache")
    assert xform._http is None, "no session until the first API call"


def test_the_session_is_cached_beside_the_bulk_data_and_closed_after_run(tmp_path, monkeypatch):
    """One CachedSession per transform, backed by a file under the bulk data dir, closed by run()."""
    monkeypatch.chdir(tmp_path)
    xform = _bare_transform(tmp_path)
    session = xform._http_session()
    assert isinstance(session, CachedSession)
    assert xform._http_session() is session
    assert (tmp_path / "raw" / "mediadive" / mod.HTTP_CACHE_FILENAME).exists()
    assert type(requests.Session()) is requests.Session
    xform._close_http()
    assert xform._http is None


def test_the_api_helper_uses_the_owned_session(tmp_path, monkeypatch):
    """_get_mediadive_json goes through the transform's session, never module-level requests.get."""
    monkeypatch.chdir(tmp_path)
    xform = _bare_transform(tmp_path)
    fake = mock.Mock()
    fake.get.return_value.json.return_value = {mod.DATA_KEY: {"id": 1}}
    xform._http = fake
    with mock.patch.object(mod.requests, "get", side_effect=AssertionError("module-level requests.get used")):
        assert xform._get_mediadive_json("https://example/api") == {"id": 1}
    fake.get.assert_called_once_with("https://example/api", timeout=30)


def test_a_legacy_cache_in_the_working_directory_is_adopted(tmp_path, monkeypatch):
    """The old install_cache() file in the CWD is moved, so its responses are not re-downloaded."""
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / mod.LEGACY_HTTP_CACHE_FILENAME
    legacy.write_bytes(b"not really sqlite")
    xform = _bare_transform(tmp_path)
    path = xform._http_cache_path()
    assert path == tmp_path / "raw" / "mediadive" / mod.HTTP_CACHE_FILENAME
    assert path.read_bytes() == b"not really sqlite"
    assert not legacy.exists()


def test_run_closes_the_session_even_when_the_transform_fails(tmp_path, monkeypatch):
    """A crash mid-run must not leave the SQLite connection open."""
    monkeypatch.chdir(tmp_path)
    xform = _bare_transform(tmp_path)
    xform._http = mock.Mock()
    with mock.patch.object(MediaDiveTransform, "_run", side_effect=RuntimeError("boom")):
        try:
            xform.run()
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected the failure to propagate")
    assert xform._http is None
