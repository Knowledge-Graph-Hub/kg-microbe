"""Explicit MediaDive helpers use owned uncached HTTP, never legacy persistence (#681, #624)."""

import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform

FIXTURES = Path(__file__).parent / "resources/mediadive_uncached"


def _bare_transform(tmp_path: Path) -> MediaDiveTransform:
    """Build only the explicit helper surface, with no production input reads."""
    xform = MediaDiveTransform.__new__(MediaDiveTransform)
    xform._http = None
    xform.bulk_data_dir = tmp_path / "raw" / "mediadive"
    xform.using_bulk_data = False
    xform.api_calls_made = xform.api_calls_avoided = 0
    xform.translation_table = str.maketrans(mod.TRANSLATION_TABLE_FOR_LABELS)
    xform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda name: None)
    xform.compound_mappings = {}
    return xform


def _response(payload):
    """Provide the requests response interface without using a network."""
    response = mock.Mock()
    response.json.return_value = payload
    return response


@pytest.fixture
def legacy_files(tmp_path, monkeypatch):
    """Create contradictory YAML and two real SQLite files from immutable fixtures."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "P11.yaml"
    shutil.copyfile(FIXTURES / "legacy.yaml", yaml_path)
    paths = [
        yaml_path,
        tmp_path / "mediadive_cache.sqlite",
        tmp_path / "raw/mediadive/mediadive_transform_cache.sqlite",
    ]
    for path in paths[1:]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.executescript((FIXTURES / "legacy-cache.sql").read_text())
    before = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in paths}
    return paths, before


def test_constructing_the_transform_leaves_requests_session_alone(tmp_path, monkeypatch):
    """The #624 fix must not regress into a process-wide requests patch."""
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
    with requests.Session() as session:
        assert type(session) is before and not hasattr(session, "cache")
    assert xform._http is None


def test_session_is_owned_uncached_and_never_adopts_old_sqlite(tmp_path, legacy_files):
    """Opening an explicit session never opens, moves or replaces either old cache."""
    paths, before = legacy_files
    xform = _bare_transform(tmp_path)
    with mock.patch.object(sqlite3, "connect", side_effect=AssertionError("SQLite cache opened")):
        session = xform._http_session()
        try:
            assert type(session) is requests.Session and not hasattr(session, "cache")
            assert xform._http_session() is session
        finally:
            xform._close_http()
    assert xform._http is None
    assert {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in paths} == before


def test_new_session_does_not_create_cache_directories(tmp_path, monkeypatch):
    """No persistent-cache directory is needed for an owned plain session."""
    monkeypatch.chdir(tmp_path)
    xform = _bare_transform(tmp_path)
    session = xform._http_session()
    try:
        assert type(session) is requests.Session and not xform.bulk_data_dir.exists()
    finally:
        xform._close_http()


@pytest.mark.parametrize("kind", ["medium", "strains", "solution", "solution_compat"])
def test_repeated_explicit_helpers_fetch_fresh_payloads_and_leave_caches_untouched(
    tmp_path, monkeypatch, legacy_files, kind
):
    """Every deliberate lookup uses the owned session, even with contradictory old YAML."""
    paths, before = legacy_files
    payloads = json.loads((FIXTURES / "responses.json").read_text())
    key = "solution" if kind == "solution_compat" else kind
    session = mock.Mock()
    session.get.side_effect = [_response(p) for p in payloads[key]]
    factory = mock.Mock(return_value=session)
    monkeypatch.setattr(mod.requests, "Session", factory)
    monkeypatch.setattr(mod.requests, "get", mock.Mock(side_effect=AssertionError("global HTTP used")))
    xform = _bare_transform(tmp_path)
    if kind in {"medium", "strains"}:
        endpoint = (mod.MEDIUM if kind == "medium" else mod.MEDIUM_STRAINS) + "P11"
        actual = [xform.get_json_object(paths[0], endpoint, tmp_path) for _ in range(2)]
        assert actual == [p[mod.DATA_KEY] for p in payloads[key]]
    else:
        method = xform.get_solution_recipe_occurrences if kind == "solution" else xform.get_compounds_of_solution
        actual = [method("1") for _ in range(2)]
        rows = actual if kind == "solution" else [list(value.values()) for value in actual]
        assert [value[0][mod.ID_COLUMN] for value in rows] == ["mediadive.solution:71", "mediadive.solution:72"]
        endpoint = mod.SOLUTION + "1"
    factory.assert_called_once_with()
    assert session.get.call_args_list == [mock.call(mod.MEDIADIVE_REST_API_BASE_URL + endpoint, timeout=30)] * 2
    assert xform.api_calls_made == 2 and xform.api_calls_avoided == 0
    assert {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in paths} == before
    xform._close_http()
    session.close.assert_called_once_with()


@pytest.mark.parametrize("target_exists", [True, False])
def test_legacy_download_signature_never_writes_yaml(tmp_path, monkeypatch, target_exists):
    """The historical download method still returns data but ignores its cache path."""
    target = tmp_path / "ignored-yaml-directory"
    if target_exists:
        target.mkdir()
    session = mock.Mock()
    payload = json.loads((FIXTURES / "responses.json").read_text())["medium"][0]
    session.get.return_value = _response(payload)
    monkeypatch.setattr(mod.requests, "Session", mock.Mock(return_value=session))
    xform = _bare_transform(tmp_path)
    assert xform.download_yaml_and_get_json("https://example.invalid/medium/P11", target) == payload[mod.DATA_KEY]
    assert target.exists() is target_exists and not (target / "P11.yaml").exists()
    xform._close_http()


def test_network_errors_never_use_cache_and_close_each_failed_session(tmp_path, monkeypatch, legacy_files):
    """Exhausted retries retain the existing empty-result contract, not stale fallback."""
    paths, before = legacy_files
    sessions = [mock.Mock() for _ in range(3)]
    for session in sessions:
        session.get.side_effect = requests.exceptions.Timeout("offline fixture")
    factory = mock.Mock(side_effect=sessions)
    monkeypatch.setattr(mod.requests, "Session", factory)
    monkeypatch.setattr(mod.time, "sleep", lambda delay: None)
    xform = _bare_transform(tmp_path)
    assert xform.get_json_object(paths[0], mod.MEDIUM + "P11", tmp_path) == {}
    assert factory.call_count == 3 and xform._http is None
    for session in sessions:
        session.close.assert_called_once_with()
    assert {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in paths} == before


@pytest.mark.parametrize("error", [ValueError("bad payload"), KeyboardInterrupt("interrupted")])
def test_parser_or_interruption_closes_session_and_propagates(tmp_path, monkeypatch, error):
    """Unexpected helper failures cannot leave an owned session open."""
    session = mock.Mock()
    session.get.return_value.json.side_effect = error
    monkeypatch.setattr(mod.requests, "Session", mock.Mock(return_value=session))
    xform = _bare_transform(tmp_path)
    with pytest.raises(type(error)):
        xform._get_mediadive_json("https://example.invalid/medium/P11")
    session.close.assert_called_once_with()
    assert xform._http is None


def test_run_closes_the_session_even_when_the_transform_fails(tmp_path, monkeypatch):
    """A producer failure must still close any explicitly opened diagnostic session."""
    monkeypatch.chdir(tmp_path)
    xform = _bare_transform(tmp_path)
    session = xform._http = mock.Mock()
    with mock.patch.object(MediaDiveTransform, "_run", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            xform.run()
    session.close.assert_called_once_with()
    assert xform._http is None
