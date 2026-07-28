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
    monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13"))
    db = _make_db(tmp_path, "2026-05-13")
    ou.assert_ncbitaxon_version_alignment(db, strict=True)  # must not raise


def test_default_is_warn_not_raise(tmp_path, monkeypatch, capsys):
    """Unlike GO, the NCBITaxon gate defaults to warn (owl/db drift is expected)."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13"))
    db = _make_db(tmp_path, "2026-01-01")
    ou.assert_ncbitaxon_version_alignment(db)  # strict=None → default warn → no raise
    assert "NCBITaxon source version mismatch" in capsys.readouterr().out


def test_mismatch_raises_when_strict(tmp_path, monkeypatch):
    """strict=True (or KG_NCBITAXON_VERSION_CHECK=strict) fails loudly."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13"))
    db = _make_db(tmp_path, "2026-01-01")
    with pytest.raises(ou.OntologyVersionMismatchError, match="NCBITaxon source version mismatch"):
        ou.assert_ncbitaxon_version_alignment(db, strict=True)


def test_env_var_strict_upgrades_to_raise(tmp_path, monkeypatch):
    """KG_NCBITAXON_VERSION_CHECK=strict upgrades the warn default to a raise."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13"))
    monkeypatch.setenv("KG_NCBITAXON_VERSION_CHECK", "strict")
    db = _make_db(tmp_path, "2026-01-01")
    with pytest.raises(ou.OntologyVersionMismatchError, match="NCBITaxon source version mismatch"):
        ou.assert_ncbitaxon_version_alignment(db)  # strict=None → env strict → raise


def test_versioninfo_query_targets_ontology_subject(tmp_path):
    """A decoy owl:versionInfo on a non-ontology subject is ignored (subject targeting)."""
    path = str(tmp_path / "ncbitaxon.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
    # Decoy first (a random entity annotated with a version-shaped date), then the ontology row.
    conn.execute("INSERT INTO statements VALUES ('SomeEntity:1', 'owl:versionInfo', NULL, '1999-12-31')")
    conn.execute("INSERT INTO statements VALUES ('obo:ncbitaxon.owl', 'owl:versionInfo', NULL, '2026-05-13')")
    conn.commit()
    conn.close()
    assert ou._ncbitaxon_db_release(path) == "2026-05-13"


def test_corrupt_db_yields_none(tmp_path):
    """A non-sqlite / corrupt file is handled (sqlite3.Error → None), not raised."""
    corrupt = tmp_path / "ncbitaxon.db"
    corrupt.write_text("this is not a sqlite database", encoding="utf-8")
    assert ou._ncbitaxon_db_release(str(corrupt)) is None


def test_missing_stamp_is_a_noop(tmp_path, monkeypatch):
    """When the db has no version stamp, the gate can't judge → no-op."""
    monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", _write_owl(tmp_path, "2026-05-13"))
    ou.assert_ncbitaxon_version_alignment(_make_db(tmp_path, None), strict=True)  # must not raise
