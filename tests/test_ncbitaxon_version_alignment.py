"""Tests for the NCBITaxon .owl/.db version-alignment gate (#604 fix 4)."""

import sqlite3
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou

# NCBITaxon stamps its version as ``ncbitaxon/DATE/`` (no ``releases/`` segment).
_OWL = '<owl versionIRI rdf:resource="http://purl.obolibrary.org/obo/ncbitaxon/{d}/ncbitaxon.owl"/>'


def _write_owl(tmp_path: Path, release: str) -> Path:
    p = tmp_path / "ncbitaxon.owl"
    p.write_text(_OWL.format(d=release), encoding="utf-8")
    return p


def _make_db(tmp_path: Path, release, name: str = "ncbitaxon.db") -> str:
    """Write a minimal SemSQL-shaped sqlite with an owl:versionInfo row."""
    path = str(tmp_path / name)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
    if release is not None:
        conn.execute(
            "INSERT INTO statements (subject, predicate, object, value) "
            "VALUES ('obo:ncbitaxon.owl', 'owl:versionInfo', NULL, ?)",
            (release,),
        )
    conn.commit()
    conn.close()
    return path


def test_owl_release_parsed_from_ncbitaxon_versioniri(tmp_path):
    """The date is read from NCBITaxon's ``ncbitaxon/DATE/`` versionIRI (no releases/)."""
    assert ou._obo_release_from_head(_write_owl(tmp_path, "2026-05-13")) == "2026-05-13"


def test_db_release_read_from_versioninfo(tmp_path):
    """_ncbitaxon_db_release reads owl:versionInfo from the SemSQL statements table."""
    assert ou._ncbitaxon_db_release(_make_db(tmp_path, "2026-05-13")) == "2026-05-13"


def test_db_release_none_when_absent(tmp_path):
    """A db with no versionInfo row (or an unreadable path) yields None."""
    assert ou._ncbitaxon_db_release(_make_db(tmp_path, None)) is None
    assert ou._ncbitaxon_db_release(str(tmp_path / "missing.db")) is None


def test_aligned_does_not_raise(tmp_path, monkeypatch):
    """Matching ncbitaxon.owl and ncbitaxon.db releases pass silently."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13")
    )
    db = _make_db(tmp_path, "2026-05-13")
    ou.assert_ncbitaxon_version_alignment(db, strict=True)  # must not raise


def test_mismatch_raises_strict(tmp_path, monkeypatch):
    """Divergent .owl/.db releases fail loudly under strict."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13")
    )
    db = _make_db(tmp_path, "2026-01-01")
    with pytest.raises(RuntimeError, match="NCBITaxon source version mismatch"):
        ou.assert_ncbitaxon_version_alignment(db, strict=True)


def test_env_var_downgrades_to_warn(tmp_path, monkeypatch, capsys):
    """KG_NCBITAXON_VERSION_CHECK=warn downgrades the default gate to a warning."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13")
    )
    monkeypatch.setenv("KG_NCBITAXON_VERSION_CHECK", "warn")
    db = _make_db(tmp_path, "2026-01-01")
    ou.assert_ncbitaxon_version_alignment(db)  # strict=None → env warn → no raise
    assert "NCBITaxon source version mismatch" in capsys.readouterr().out


def test_missing_stamp_is_a_noop(tmp_path, monkeypatch):
    """When the db has no version stamp, the gate can't judge → no-op."""
    monkeypatch.setattr(
        "kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13")
    )
    ou.assert_ncbitaxon_version_alignment(_make_db(tmp_path, None), strict=True)  # must not raise
