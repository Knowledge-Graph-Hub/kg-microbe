"""
Tests for building ncbitaxon.db from the ncbitaxon.owl we ship.

Applies the GO single-source rule (#604) to NCBITaxon. OAK's prebuilt SemSQL
cannot be kept aligned — upstream CDN builds lag the OBO release train by
months — so the lookup DB is built from the same OWL the transform emits nodes
from, making the two releases equal by construction.

None of these tests run a real `semsql make`: the build is mocked and the
size threshold shrunk, so they stay fast.
"""

import subprocess

import pytest

from kg_microbe.utils import ontology_utils as ou

OWL_HEAD = '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/ncbitaxon/{d}/ncbitaxon.owl"/>\n'


@pytest.fixture
def owl(tmp_path, monkeypatch):
    """Write a stamped ncbitaxon.owl and point NCBITAXON_SOURCE at it."""

    def _make(release="2026-07-12"):
        path = tmp_path / "ncbitaxon.owl"
        path.write_text(OWL_HEAD.format(d=release), encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", path)
        return path

    return _make


@pytest.fixture
def tiny_threshold(monkeypatch):
    """Shrink the min-size gate so tests write bytes, not gigabytes."""
    monkeypatch.setattr(ou, "_NCBITAXON_DB_MIN_SIZE", 8)


def _fake_build(monkeypatch, db_path, *, size=16, fail=False):
    """Stand in for `semsql make`, recording the call and writing a fake DB."""
    calls = []

    def run(cmd, **kwargs):
        """Record the invocation, then emit a fake DB (or fail)."""
        calls.append((cmd, kwargs.get("cwd")))
        if fail:
            raise subprocess.CalledProcessError(1, cmd)
        db_path.write_bytes(b"0" * size)

    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    monkeypatch.setattr(ou.subprocess, "run", run)
    return calls


class TestSkipsUnnecessaryBuilds:

    """A 13 GB build must only run when it is actually needed."""

    def test_valid_aligned_db_is_reused(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """Matching releases must not trigger a rebuild."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-07-12")
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert calls == [], "no build should run for an aligned DB"

    def test_unreadable_release_does_not_force_rebuild(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """An unreadable stamp must not cause a spurious multi-hour rebuild."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: None)
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert calls == []


class TestRebuildsOnDrift:

    """The whole point: a refreshed OWL must produce a matching DB."""

    def test_drifted_db_is_rebuilt(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """A DB at an older release than the OWL is rebuilt from that OWL."""
        source = owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert len(calls) == 1
        cmd, cwd = calls[0]
        assert cmd == ["semsql", "make", "ncbitaxon.db"]
        assert cwd == str(source.parent), "semsql must run beside the OWL"
        assert "drifted" in capsys.readouterr().out

    def test_missing_db_is_built(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """No DB at all means build it."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert len(calls) == 1

    def test_partial_db_is_removed_before_build(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """A truncated DB must be deleted, else make treats it as up to date."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"partial")  # below the threshold

        seen = {}

        def run(cmd, **kwargs):
            """Note whether the stale DB was cleared before the build ran."""
            seen["existed_at_build_time"] = db.exists()
            db.write_bytes(b"0" * 16)

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert seen["existed_at_build_time"] is False


class TestDegradesGracefully:

    """A machine without the build toolchain must not be left broken."""

    def test_missing_semsql_keeps_existing_db(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """Without semsql, report whatever DB is already present rather than deleting it."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert db.exists(), "an unbuildable DB must not be destroyed"
        assert "semsql" in capsys.readouterr().out

    def test_missing_owl_warns(self, tmp_path, monkeypatch, capsys):
        """No OWL source means no build; say so rather than failing obscurely."""
        monkeypatch.setattr(
            "kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", tmp_path / "absent.owl"
        )
        assert ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db")) is False
        assert "missing" in capsys.readouterr().out

    def test_failed_build_returns_false(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """A semsql crash is reported, not raised."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        _fake_build(monkeypatch, db, fail=True)
        assert ou._ensure_ncbitaxon_db(str(db)) is False
        assert "failed to build" in capsys.readouterr().out

    def test_undersized_result_is_rejected(self, tmp_path, owl, monkeypatch):
        """A build that produced a stub must not be reported as usable."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        monkeypatch.setattr(ou, "_NCBITAXON_DB_MIN_SIZE", 1_000_000)
        _fake_build(monkeypatch, db, size=16)
        assert ou._ensure_ncbitaxon_db(str(db)) is False
