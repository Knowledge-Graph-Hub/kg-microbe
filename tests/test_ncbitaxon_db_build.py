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
from pathlib import Path

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

    def test_stub_db_is_not_reported_usable(self, tmp_path, owl, monkeypatch):
        """A truncated DB must not pass as usable on the no-build paths (F1)."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"stub")  # threshold left at the real 1 GB
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)
        assert ou._ensure_ncbitaxon_db(str(db)) is False

    def test_failed_build_restores_the_previous_db(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """A failed build must not leave the caller without the 13 GB DB (F3)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        original = db.read_bytes()
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")  # drift → rebuild
        _fake_build(monkeypatch, db, fail=True)

        result = ou._ensure_ncbitaxon_db(str(db))
        assert db.exists(), "the previous DB must be restored"
        assert db.read_bytes() == original
        assert result is True
        assert not (tmp_path / "ncbitaxon.db.prev").exists()

    def test_successful_build_discards_the_keep_aside_copy(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """On success the moved-aside DB is removed, not left doubling disk use."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert not (tmp_path / "ncbitaxon.db.prev").exists()

    def test_missing_owl_warns(self, tmp_path, monkeypatch, capsys):
        """No OWL source means no build; say so rather than failing obscurely."""
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", tmp_path / "absent.owl")
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

    def test_opt_out_skips_the_build(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """KG_SEMSQL_BUILD=off must not start a multi-hour build (#613)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"0" * 16)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")  # drifted
        calls = _fake_build(monkeypatch, db)
        monkeypatch.setenv("KG_SEMSQL_BUILD", "off")

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert calls == [], "opt-out must skip semsql entirely"
        assert "opt-out" in capsys.readouterr().out

    @pytest.mark.parametrize("value", ["off", "false", "0", "no", "OFF"])
    def test_opt_out_accepts_common_spellings(self, tmp_path, owl, tiny_threshold, monkeypatch, value):
        """Any of the usual falsey spellings disables the build."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        calls = _fake_build(monkeypatch, db)
        monkeypatch.setenv("KG_SEMSQL_BUILD", value)
        ou._ensure_ncbitaxon_db(str(db))
        assert calls == []

    def test_decompresses_archive_when_owl_absent(self, tmp_path, tiny_threshold, monkeypatch):
        """A fresh checkout has only ncbitaxon.owl.gz; the build must still run (#620)."""
        import gzip as gz

        owl_path = tmp_path / "ncbitaxon.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", owl_path)
        with gz.open(tmp_path / "ncbitaxon.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_HEAD.format(d="2026-07-12"))

        db = tmp_path / "ncbitaxon.db"
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert owl_path.exists(), "ncbitaxon.owl.gz should have been decompressed"
        assert len(calls) == 1, "the build must not be skipped as 'OWL missing'"

    def test_partial_decompression_is_not_left_behind(self, tmp_path, tiny_threshold, monkeypatch):
        """An interrupted decompression must not leave a truncated OWL (#615/#620)."""
        import gzip as gz

        owl_path = tmp_path / "ncbitaxon.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", owl_path)
        with gz.open(tmp_path / "ncbitaxon.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_HEAD.format(d="2026-07-12"))

        def boom(src, dst, *a, **k):
            """Fail part-way through, as a full disk would."""
            dst.write(b"<owl:versionIRI")
            raise OSError("no space left on device")

        monkeypatch.setattr(ou.shutil, "copyfileobj", boom)
        assert ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db")) is False
        assert not owl_path.exists()
        assert not (tmp_path / "ncbitaxon.owl.partial").exists()

    def test_dangling_symlink_target_is_cleared(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        A broken symlink must not survive and redirect the build (#1).

        os.path.exists is False for a dangling link, so the old check skipped the
        removal; semsql then opened the target name for writing, followed the link
        and deposited the ~13 GB result at the link's target instead — while the
        size check, also following the link, reported success.
        """
        source = owl("2026-07-12")
        elsewhere = tmp_path / "oak"
        elsewhere.mkdir()
        db = tmp_path / "ncbitaxon.db"
        db.symlink_to(elsewhere / "ncbitaxon.db")  # target does not exist

        def run(cmd, **kwargs):
            """Write to the target name the way semsql does, following any symlink."""
            with open(Path(kwargs["cwd"]) / "ncbitaxon.db", "wb") as f:
                f.write(b"0" * 32)

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert not db.is_symlink(), "the dangling link should have been removed"
        assert db.stat().st_size == 32, "the build must land at the real path"
        assert list(elsewhere.iterdir()) == [], "nothing should have been written to the link target"
        assert source.exists()

    def test_symlinked_result_is_rejected(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """If a build somehow leaves a symlink behind, don't report success."""
        owl()
        elsewhere = tmp_path / "elsewhere.db"
        elsewhere.write_bytes(b"0" * 32)
        db = tmp_path / "ncbitaxon.db"

        def run(cmd, **kwargs):
            """Leave a symlink rather than a real DB at the target."""
            db.symlink_to(elsewhere)

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)
        assert ou._ensure_ncbitaxon_db(str(db)) is False

    def test_truncated_archive_degrades_gracefully(self, tmp_path, tiny_threshold, monkeypatch):
        """A truncated .gz raises EOFError, not OSError — it must still be caught (#2)."""
        import gzip as gz

        owl_path = tmp_path / "ncbitaxon.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", owl_path)
        archive = tmp_path / "ncbitaxon.owl.gz"
        with gz.open(archive, "wt", encoding="utf-8") as f:
            f.write(OWL_HEAD.format(d="2026-07-12") * 500)
        archive.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])  # truncate

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        # Must return False rather than propagating EOFError.
        assert ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db")) is False
        assert not owl_path.exists()
        assert not (tmp_path / "ncbitaxon.owl.partial").exists(), "orphaned .partial left behind"

    def test_semsql_checked_before_decompressing(self, tmp_path, tiny_threshold, monkeypatch):
        """Don't unpack ~2 GB only to discover semsql is absent (#10)."""
        import gzip as gz

        owl_path = tmp_path / "ncbitaxon.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", owl_path)
        with gz.open(tmp_path / "ncbitaxon.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_HEAD.format(d="2026-07-12"))
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)

        ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db"))
        assert not owl_path.exists(), "should not have decompressed without semsql"

    def test_build_runs_when_opt_out_unset(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """Default behaviour is unchanged: the build still runs."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        calls = _fake_build(monkeypatch, db)
        monkeypatch.delenv("KG_SEMSQL_BUILD", raising=False)
        assert ou._ensure_ncbitaxon_db(str(db)) is True
        assert len(calls) == 1
