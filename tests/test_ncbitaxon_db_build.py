"""
Tests for building ncbitaxon.db from the ncbitaxon.owl we ship.

Applies the GO single-source rule (#604) to NCBITaxon. OAK's prebuilt SemSQL
cannot be kept aligned — upstream CDN builds lag the OBO release train by
months — so the lookup DB is built from the same OWL the transform emits nodes
from, making the two releases equal by construction.

None of these tests run a real `semsql make`: the build is mocked and the
size threshold shrunk, so they stay fast.
"""

import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou
from tests.db_helpers import (
    SEMSQL_DDL,
    valid_db_bytes,
    write_semsql_db,
    write_single_ontology_db,
)

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


def _write_real_db(path: Path, pad: int = 16) -> Path:
    """
    Write a genuinely openable SQLite file at ``path``.

    The reuse fast-path probes that a DB actually opens, so filler bytes no
    longer stand in for a healthy DB: a large-but-corrupt file must be rebuilt,
    not handed to OAK to fail silently against. Tests that assert *reuse* have
    to supply something SQLite can read.
    """
    path.write_bytes(valid_db_bytes(pad=pad))
    return path


def _fake_build(monkeypatch, db_path, *, size=16, fail=False):
    """Stand in for `semsql make`, recording the call and writing a fake DB."""
    calls = []

    def run(cmd, **kwargs):
        """Record the invocation, then emit a fake DB (or fail)."""
        calls.append((cmd, kwargs.get("cwd")))
        if fail:
            raise subprocess.CalledProcessError(1, cmd)
        db_path.write_bytes(valid_db_bytes(pad=size))

    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
    monkeypatch.setattr(ou.subprocess, "run", run)
    return calls


class TestSkipsUnnecessaryBuilds:

    """A 13 GB build must only run when it is actually needed."""

    def test_valid_aligned_db_is_reused(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """Matching releases must not trigger a rebuild."""
        owl("2026-07-12")
        db = _write_real_db(tmp_path / "ncbitaxon.db")
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-07-12")
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_ncbitaxon_db(str(db))
        assert calls == [], "no build should run for an aligned DB"

    def test_unreadable_release_does_not_force_rebuild(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """An unreadable stamp must not cause a spurious multi-hour rebuild."""
        owl("2026-07-12")
        db = _write_real_db(tmp_path / "ncbitaxon.db")
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: None)
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_ncbitaxon_db(str(db))
        assert calls == []


class TestRebuildsOnDrift:

    """The whole point: a refreshed OWL must produce a matching DB."""

    def test_drifted_db_is_rebuilt(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """A DB at an older release than the OWL is rebuilt from that OWL."""
        source = owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db))
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
        assert ou._ensure_ncbitaxon_db(str(db))
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
            db.write_bytes(valid_db_bytes(pad=16))

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_ncbitaxon_db(str(db))
        assert seen["existed_at_build_time"] is False


class TestDegradesGracefully:

    """A machine without the build toolchain must not be left broken."""

    def test_missing_semsql_keeps_existing_db(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """Without semsql, report whatever DB is already present rather than deleting it."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)

        assert ou._ensure_ncbitaxon_db(str(db))
        assert db.exists(), "an unbuildable DB must not be destroyed"
        assert "semsql" in capsys.readouterr().out

    def test_stub_db_is_not_reported_usable(self, tmp_path, owl, monkeypatch):
        """A truncated DB must not pass as usable on the no-build paths (F1)."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"stub")  # threshold left at the real 1 GB
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)
        assert not ou._ensure_ncbitaxon_db(str(db))

    def test_failed_build_restores_the_previous_db(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """A failed build must not leave the caller without the 13 GB DB (F3)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        original = db.read_bytes()
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")  # drift → rebuild
        _fake_build(monkeypatch, db, fail=True)

        result = ou._ensure_ncbitaxon_db(str(db))
        assert db.exists(), "the previous DB must be restored"
        assert db.read_bytes() == original
        assert result and not result.built, "a restore is not a build"
        assert not (tmp_path / "ncbitaxon.db.prev").exists()

    def test_successful_build_discards_the_keep_aside_copy(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        On success the moved-aside DB is removed, not left doubling disk use.

        Asserts the .prev existed *during* the build and is gone after — checking
        only the end state passes trivially with the keep-aside reverted, since
        then no .prev is ever created.
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        prev = tmp_path / "ncbitaxon.db.prev"
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")
        seen = {}

        def run(cmd, **kwargs):
            """Record whether the old DB was preserved while the build ran."""
            seen["prev_during_build"] = prev.exists()
            db.write_bytes(valid_db_bytes(pad=16))

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_ncbitaxon_db(str(db))
        assert seen["prev_during_build"] is True, "the old DB must be kept during the build"
        assert not prev.exists(), "and discarded once the build verifies"

    def test_interrupt_restores_the_db_and_leaves_no_orphan(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """Ctrl-C during a build must not strand a 14 GB .prev with the DB gone (F3)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        original = db.read_bytes()
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")

        def run(cmd, **kwargs):
            """Die the way a Ctrl-C or an OOM kill does."""
            raise KeyboardInterrupt

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        with pytest.raises(KeyboardInterrupt):
            ou._ensure_ncbitaxon_db(str(db))
        assert db.exists() and db.read_bytes() == original, "the DB must be restored"
        assert not (tmp_path / "ncbitaxon.db.prev").exists(), "no orphaned .prev"

    def test_partial_output_never_destroys_a_good_prev(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        A killed build leaves a partial file; the good .prev must survive (#634).

        os.remove(kept) used to run before the move-aside, destroying the good DB
        and then reporting "Restored the previous ... after the failed build".
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"P" * 4)  # partial, below the threshold
        prev = tmp_path / "ncbitaxon.db.prev"
        prev.write_bytes(valid_db_bytes(b"G", 64))  # the good DB
        _fake_build(monkeypatch, db, fail=True)

        ou._ensure_ncbitaxon_db(str(db))

        assert db.exists() and db.read_bytes() == valid_db_bytes(b"G", 64), "the good DB must be what remains"

    def test_dangling_symlink_over_a_good_prev_never_loses_the_db(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        A dangling symlink at the target must not cost the user the good .prev.

        Third recurrence of #634. _clear_build_target recovers the .prev onto the
        target, but the symlink branch used to `return` before the fall-through
        that moves the recovered DB aside — so `semsql make` wrote straight over
        the 13 GB copy, and because the result recorded only the link, a failed
        build put the *dangling symlink* back and the DB was gone for good.
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        prev = tmp_path / "ncbitaxon.db.prev"
        prev.write_bytes(valid_db_bytes(b"G", 64))  # the only usable copy
        db.symlink_to(tmp_path / "gone" / "cache.db")  # dangling
        _fake_build(monkeypatch, db, fail=True)

        ou._ensure_ncbitaxon_db(str(db))

        assert not db.is_symlink(), "the dangling link must not be restored over the good DB"
        assert db.exists() and db.read_bytes() == valid_db_bytes(b"G", 64), "the good DB must survive"

    def test_corrupt_but_large_db_is_rebuilt_not_reused(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        A DB that clears the size floor but is not SQLite must be rebuilt.

        Every release reader turns the resulting sqlite3.Error into None, which
        the reuse fast-path reads as "no stamp, do not rebuild" — so the corrupt
        file was handed to OAK, whose queries then failed inside broad handlers
        and collapsed every term to a default category (#625, same shape).
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(b"not a database" * 8)  # well above the shrunken floor
        calls = _fake_build(monkeypatch, db)

        ou._ensure_ncbitaxon_db(str(db))

        assert calls, "an unopenable DB must trigger a rebuild rather than be reused"

    def test_leftover_prev_is_reported_when_the_db_is_reused(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """
        A .prev left by an interrupted build must not sit unnoticed (#634).

        When the current DB is reused, _clear_build_target never runs, so nothing
        consults .prev — 14 GB unreferenced for NCBITaxon. A partial that clears
        the size floor is indistinguishable from a complete DB, so the honest
        behaviour is to report the orphan rather than guess.
        """
        owl("2026-07-12")
        db = _write_real_db(tmp_path / "ncbitaxon.db", pad=32)
        prev = tmp_path / "ncbitaxon.db.prev"
        prev.write_bytes(valid_db_bytes(b"G", 64))
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-07-12")  # aligned → reuse
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db))

        assert calls == [], "an aligned DB is reused"
        assert prev.read_bytes() == valid_db_bytes(b"G", 64), "the leftover must not be destroyed"
        assert "left over from an interrupted build" in capsys.readouterr().out

    def test_orphaned_prev_from_an_earlier_kill_is_recovered(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """A .prev left by a previously killed run is adopted, not stranded forever."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        prev = tmp_path / "ncbitaxon.db.prev"
        prev.write_bytes(valid_db_bytes(pad=16))  # DB missing, .prev orphaned
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_ncbitaxon_db(str(db))
        assert len(calls) == 1
        assert not prev.exists(), "the orphan must not survive another run"

    def test_short_build_result_restores_and_reports_the_restored_db(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """Semsql can exit 0 with a stub; report on what is on disk after restoring (F2)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        original = db.read_bytes()
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")

        def run(cmd, **kwargs):
            """Exit 0 but leave an under-threshold file."""
            db.write_bytes(b"x")

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        result = ou._ensure_ncbitaxon_db(str(db))
        assert db.read_bytes() == original, "the working DB must be restored"
        assert result, "and reported usable, since it is"

    def test_symlinked_prebuilt_db_is_accepted_when_no_build_is_possible(
        self, tmp_path, owl, tiny_threshold, monkeypatch
    ):
        """
        Pointing at a prebuilt DB with a symlink is supported (F4).

        The release is drifted on purpose so the reuse fast-path is skipped and
        execution actually reaches the no-build exit this test is about — without
        that, the `which -> None` stub was never consulted and the test passed
        with the symlink rejection reinstated (#637).
        """
        owl("2026-07-12")
        real = tmp_path / "prebuilt.db"
        real.write_bytes(valid_db_bytes(pad=16))
        db = tmp_path / "ncbitaxon.db"
        db.symlink_to(real)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")  # drifted
        consulted = []
        monkeypatch.setattr(ou.shutil, "which", lambda n: consulted.append(n) or None)

        assert ou._ensure_ncbitaxon_db(str(db)), "a symlinked prebuilt DB is usable"
        assert consulted, "must reach the no-build exit, not the reuse fast-path"
        assert db.is_symlink(), "and the symlink must survive"

    def test_missing_owl_warns(self, tmp_path, monkeypatch, capsys):
        """No OWL source means no build; say so rather than failing obscurely."""
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", tmp_path / "absent.owl")
        assert not ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db"))
        assert "missing" in capsys.readouterr().out

    def test_failed_build_returns_false(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """A semsql crash is reported, not raised."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        _fake_build(monkeypatch, db, fail=True)
        assert not ou._ensure_ncbitaxon_db(str(db))
        assert "failed to build" in capsys.readouterr().out

    def test_undersized_result_is_rejected(self, tmp_path, owl, monkeypatch):
        """A build that produced a stub must not be reported as usable."""
        owl()
        db = tmp_path / "ncbitaxon.db"
        monkeypatch.setattr(ou, "_NCBITAXON_DB_MIN_SIZE", 1_000_000)
        _fake_build(monkeypatch, db, size=16)
        assert not ou._ensure_ncbitaxon_db(str(db))

    def test_opt_out_skips_the_build(self, tmp_path, owl, tiny_threshold, monkeypatch, capsys):
        """KG_SEMSQL_BUILD=off must not start a multi-hour build (#613)."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        db.write_bytes(valid_db_bytes(pad=16))
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-05-13")  # drifted
        calls = _fake_build(monkeypatch, db)
        monkeypatch.setenv("KG_SEMSQL_BUILD", "off")

        assert ou._ensure_ncbitaxon_db(str(db))
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

        assert ou._ensure_ncbitaxon_db(str(db))
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
        assert not ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db"))
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
                f.write(valid_db_bytes(pad=32))

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_ncbitaxon_db(str(db))
        assert not db.is_symlink(), "the dangling link should have been removed"
        assert db.stat().st_size == len(valid_db_bytes(pad=32)), "the build must land at the real path"
        assert list(elsewhere.iterdir()) == [], "nothing should have been written to the link target"
        assert source.exists()

    def test_symlinked_result_is_rejected(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """If a build somehow leaves a symlink behind, don't report success."""
        owl()
        elsewhere = tmp_path / "elsewhere.db"
        elsewhere.write_bytes(valid_db_bytes(pad=32))
        db = tmp_path / "ncbitaxon.db"

        def run(cmd, **kwargs):
            """Leave a symlink rather than a real DB at the target."""
            db.symlink_to(elsewhere)

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)
        assert not ou._ensure_ncbitaxon_db(str(db))

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
        assert not ou._ensure_ncbitaxon_db(str(tmp_path / "ncbitaxon.db"))
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
        assert ou._ensure_ncbitaxon_db(str(db))
        assert len(calls) == 1


class TestLockedDatabasesAreNotDestroyed:

    """
    A database another process holds open is not damaged (round-4 findings).

    BUSY was handled correctly on the shallow path and then treated as failure
    at both deep-check sites, so `PRAGMA quick_check` on a locked DB returned
    BUSY, every caller compared `!= DB_OK`, and a live database was unlinked
    while a healthy fresh build was thrown away. "Cannot verify" is not
    "worthless".
    """

    @staticmethod
    def _real_db(path, rows=200, tag="x"):
        """Write a genuinely usable SemSQL DB with distinguishable contents."""
        write_semsql_db(
            path,
            extra_statements=[
                (
                    "INSERT INTO statements (subject, predicate, value) VALUES (?, ?, ?)",
                    (f"{tag}{i}", "rdfs:label", "v" * 100),
                )
                for i in range(rows)
            ],
        )
        return path

    @staticmethod
    def _hold_write_lock(path):
        """Open an exclusive transaction, as a concurrent writer would."""
        conn = sqlite3.connect(str(path))
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("INSERT INTO statements (subject, predicate, value) VALUES ('a','b','c')")
        return conn

    def test_deep_check_reports_busy_not_corrupt(self, tmp_path):
        """The distinction the fix rests on."""
        db = self._real_db(tmp_path / "n.db")
        conn = self._hold_write_lock(db)
        try:
            assert ou._classify_db(str(db), 8, deep=True) == ou.DB_BUSY
        finally:
            conn.rollback()
            conn.close()

    def test_a_locked_target_is_moved_aside_not_unlinked(self, tmp_path, tiny_threshold):
        """A live DB must be preserved, exactly as an unlocked one would be."""
        db = self._real_db(tmp_path / "ncbitaxon.db", tag="TARGET")
        self._real_db(tmp_path / "ncbitaxon.db.prev", rows=100, tag="PREV")
        original = db.read_bytes()
        conn = self._hold_write_lock(db)
        try:
            ou._clear_build_target(str(db), 8)
        finally:
            conn.rollback()
            conn.close()
        survived = [p for p in tmp_path.iterdir() if p.is_file() and p.read_bytes() == original]
        assert survived, "the live database's content must survive somewhere"

    def test_a_locked_fresh_build_is_not_discarded(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """A build that finished correctly must not be thrown away for being open."""
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        self._real_db(db, rows=100, tag="OLD")
        stale = db.read_bytes()
        holder = {}

        def build(cmd, **kwargs):
            """Produce a healthy build that another process immediately opens."""
            self._real_db(db, rows=400, tag="NEW")
            holder["conn"] = self._hold_write_lock(db)

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", build)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-01-01")  # drift → rebuild
        try:
            result = ou._ensure_ncbitaxon_db(str(db))
        finally:
            if "conn" in holder:
                holder["conn"].rollback()
                holder["conn"].close()

        assert result.built, "a completed build must be reported as built"
        assert db.read_bytes() != stale, "the new build must not be replaced by the old DB"

    def test_deep_corruption_still_cannot_displace_a_good_prev(self, tmp_path, tiny_threshold):
        """The round-3 protection must survive the round-4 fix."""
        db = self._real_db(tmp_path / "ncbitaxon.db")
        size = db.stat().st_size
        with open(db, "r+b") as handle:  # corrupt past the schema page
            handle.seek(size // 2)
            handle.write(b"\xff" * 8192)
        prev = self._real_db(tmp_path / "ncbitaxon.db.prev", rows=100, tag="GOOD")
        good = prev.read_bytes()

        kept = ou._clear_build_target(str(db), 8)
        ou._restore_build_target(str(db), kept)

        assert db.exists() and db.read_bytes() == good, "the good copy must be what remains"

    def test_a_structurally_valid_build_without_semsql_schema_is_rejected(
        self, tmp_path, owl, tiny_threshold, monkeypatch
    ):
        """
        File integrity is not usability (round-5 finding 1).

        `semsql make` can exit 0 having produced a well-formed SQLite file that
        passes quick_check yet carries none of the SemSQL schema. That was
        accepted as a successful build, and the previous — genuinely usable —
        database was discarded on the strength of it.
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"
        self._real_db(db, tag="GOOD")
        good = db.read_bytes()

        def build(cmd, **kwargs):
            """Exit 0 with valid SQLite that has no statements table."""
            db.unlink()
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE unrelated (a TEXT, b TEXT)")
            conn.executemany("INSERT INTO unrelated VALUES (?,?)", [(f"x{i}", "y" * 100) for i in range(200)])
            conn.commit()
            conn.close()

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", build)
        monkeypatch.setattr(ou, "_ncbitaxon_db_release", lambda _: "2026-01-01")  # drift → rebuild

        result = ou._ensure_ncbitaxon_db(str(db))

        assert not result.built, "a build with no SemSQL schema is not a successful build"
        assert db.exists() and db.read_bytes() == good, "the previous usable DB must survive"

    def test_an_empty_statements_table_is_not_a_usable_build(self, tmp_path):
        """Schema present but nothing loaded is not a database anyone can use."""
        db = tmp_path / "ncbitaxon.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, value TEXT)")
        conn.commit()
        conn.close()
        assert ou._has_semsql_schema(str(db)) is False

    def test_a_locked_db_reports_unknown_schema_rather_than_absent(self, tmp_path):
        """
        None, not False: "could not establish" must not read as "no schema".

        Reporting False for a locked database would discard a healthy build.
        """
        db = self._real_db(tmp_path / "ncbitaxon.db")
        conn = self._hold_write_lock(db)
        try:
            assert ou._has_semsql_schema(str(db)) is None
        finally:
            conn.rollback()
            conn.close()

    def test_a_schema_shaped_but_wrong_columned_db_is_rejected(self, tmp_path):
        """
        `SELECT *` compiled fine against a table with the wrong columns.

        A DB declaring `statements(predicate)` alone passed the probe while every
        consumer query failed with `no such column`, so the probes name the exact
        columns our queries select.
        """
        db = tmp_path / "ncbitaxon.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE statements (predicate TEXT)")
        conn.execute("CREATE TABLE entailed_edge (x TEXT)")
        conn.execute("CREATE VIEW edge AS SELECT * FROM entailed_edge")
        conn.execute("CREATE VIEW rdfs_label_statement AS SELECT * FROM statements")
        conn.execute("INSERT INTO statements VALUES ('rdfs:label')")
        conn.execute("INSERT INTO entailed_edge VALUES ('a')")
        conn.commit()
        conn.close()
        assert ou._has_semsql_schema(str(db)) is False

    def test_content_requirements_are_opt_in(self, tmp_path):
        """
        Structure is universal; content is not.

        Demanding a label row and a hierarchy row is right for the four sources
        shipped here, but as a general invariant it would reject a legitimately
        flat or property-only ontology on every run, restore the previous copy,
        and rebuild again forever.
        """
        db = tmp_path / "flat.db"
        conn = sqlite3.connect(str(db))
        for ddl in SEMSQL_DDL:  # full structure...
            conn.execute(ddl)
        conn.commit()  # ...and deliberately no rows
        conn.close()

        assert ou._has_semsql_schema(str(db), require_content=False) is True
        assert ou._has_semsql_schema(str(db), require_content=True) is False

    def test_a_rejected_build_is_not_adopted_by_a_later_run(self, tmp_path, owl, tiny_threshold, monkeypatch):
        """
        The artifact stays for diagnosis, but must never be reported usable.

        Deleting it was the first attempt and turned metatraits' hard error on a
        freshly built invalid DB into a silent fallback to the OAK cache, so the
        refusal belongs at every exit that reports usability instead.
        """
        owl("2026-07-12")
        db = tmp_path / "ncbitaxon.db"

        def build(cmd, **kwargs):
            """Exit 0 with valid SQLite carrying none of the SemSQL schema."""
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE unrelated (a TEXT)")
            conn.executemany("INSERT INTO unrelated VALUES (?)", [("y" * 200,) for _ in range(200)])
            conn.commit()
            conn.close()

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", build)
        assert not ou._ensure_ncbitaxon_db(str(db))

        # A later run must not adopt it, whichever exit it reaches.
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)
        assert not ou._ensure_ncbitaxon_db(str(db)), "the no-semsql fallback must refuse it too"
        monkeypatch.setenv("KG_SEMSQL_BUILD", "off")
        assert not ou._ensure_ncbitaxon_db(str(db)), "the opt-out path must refuse it too"

    def test_a_partial_schema_is_rejected_however_plausible(self, tmp_path):
        """
        Object presence is compared against a real build, not a remembered list.

        Three consecutive reviews found another view some OAK path needed —
        node_to_value_statement most damagingly, whose absence filed every
        molecular-function GO term as BiologicalProcess. A DB carrying only the
        handful of objects previously probed must now be rejected.
        """
        db = tmp_path / "ncbitaxon.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE statements (stanza TEXT, subject TEXT, predicate TEXT, object TEXT, "
            "value TEXT, datatype TEXT, language TEXT, graph TEXT)"
        )
        conn.execute("CREATE TABLE entailed_edge (subject TEXT, predicate TEXT, object TEXT)")
        conn.execute("CREATE VIEW edge AS SELECT subject, predicate, object FROM statements")
        conn.commit()
        conn.close()
        assert ou._has_semsql_schema(str(db)) is False

    def test_the_fixture_satisfies_the_production_gate(self, tmp_path):
        """
        The fixture and the gate must not drift apart, in either direction.

        Asserting only that the fixture passes is one-way: the gate could grow a
        requirement the fixture happens to satisfy, or the fixture could be
        regenerated with objects the gate never checks, and neither shows up.
        This also asserts every contract object and column is genuinely present
        in the fixture, so a contract entry naming something a real build does
        not produce fails here rather than in production.
        """
        db = write_semsql_db(tmp_path / "fixture.db")
        assert ou._has_semsql_schema(str(db), require_content=True) is True

        conn = sqlite3.connect(str(db))
        try:
            for table, columns in ou._SEMSQL_CAPABILITY_CONTRACT.items():
                present = {
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
                }
                assert present, f"contract names {table}, which the captured schema does not create"
                missing = set(columns) - present
                assert not missing, f"{table} in the fixture lacks contract columns {sorted(missing)}"
        finally:
            conn.close()

    def test_every_contract_object_exists_in_a_real_database(self):
        """
        The contract must describe real builds, not an idealised schema.

        It was derived by tracing consumer queries against a shipped database;
        this keeps it honest if someone edits it by hand later. Skipped when the
        real databases are absent, as they are in CI.
        """
        real = Path("data/raw/ec.db")
        if not real.exists():
            pytest.skip("data/raw/ec.db is not present")
        conn = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
        try:
            for table, columns in ou._SEMSQL_CAPABILITY_CONTRACT.items():
                present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608
                assert present, f"contract names {table}, absent from a real build"
                assert not set(columns) - present, f"{table} lacks {sorted(set(columns) - present)}"
        finally:
            conn.close()

    def test_content_policy_is_explicit_not_inferred(self, tmp_path):
        """
        Policy is passed by the caller, not read off a display label.

        Deriving it from `label` failed open — "ChEBI" enabled content
        validation and "ChEBI ontology" silently disabled it — so a typo would
        have weakened the check invisibly.
        """
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        for ddl in SEMSQL_DDL:
            conn.execute(ddl)
        conn.commit()
        conn.close()

        assert ou._has_semsql_schema(str(db), require_content=False) is True
        assert ou._has_semsql_schema(str(db), require_content=True) is False
        assert not hasattr(ou, "_requires_content"), "label-derived policy must not return"

    def test_the_annotation_path_objects_are_in_the_contract(self):
        """
        The NER fallback reads objects the first trace never saw.

        ner_utils.annotate switches to annotate_text(matches_whole_text=False)
        when a term has no whole-text match, and that lazy branch builds a
        lexical index over `node`, `deprecated_node` and the synonym views.
        None appeared in the contract until the fallback was exercised.
        """
        required = {
            "node",
            "deprecated_node",
            "has_exact_synonym_statement",
            "has_broad_synonym_statement",
            "has_narrow_synonym_statement",
            "has_related_synonym_statement",
            "has_synonym_statement",
        }
        assert required <= set(ou._SEMSQL_CAPABILITY_CONTRACT)

    def test_an_unexpected_probe_error_is_not_a_schema_verdict(self, tmp_path, monkeypatch):
        """
        Only missing tables and columns prove a schema is bad.

        Any other OperationalError — a disk error, say — means the probe could
        not establish anything, and reporting False would send a healthy
        database off to be rebuilt.
        """
        db = write_semsql_db(tmp_path / "ncbitaxon.db")
        real_connect = sqlite3.connect

        class Failing:

            """Answers the first probe, then fails for an unrelated reason."""

            def __init__(self, conn):
                """Wrap a real connection and count statements."""
                self.conn = conn
                self.calls = 0

            def execute(self, sql, *args):
                """Fail after the first statement."""
                self.calls += 1
                if self.calls > 1:
                    raise sqlite3.OperationalError("disk I/O error")
                return self.conn.execute(sql, *args)

            def close(self):
                """Close the wrapped connection."""
                self.conn.close()

        monkeypatch.setattr(ou.sqlite3, "connect", lambda *a, **k: Failing(real_connect(*a, **k)))
        assert ou._has_semsql_schema(str(db)) is None, "an unrelated error is not a schema failure"

    @pytest.mark.parametrize(
        "statements_before_failure, where",
        [(2, "during a structural probe"), (22, "after the structural probes"), (23, "during a content probe")],
    )
    def test_an_unexpected_error_is_never_a_schema_verdict(
        self, tmp_path, monkeypatch, statements_before_failure, where
    ):
        """
        The same error must mean the same thing wherever it lands.

        The classifier was first applied to the structural probe loop only, so an
        identical disk error read as "cannot tell" there and as "schema is bad"
        during content probing or connect() — and the latter would send a healthy
        multi-gigabyte database off to a multi-hour rebuild.
        """
        db = write_semsql_db(tmp_path / "ncbitaxon.db")
        real_connect = sqlite3.connect

        class Failing:

            """Answers a set number of statements, then fails unrelatedly."""

            def __init__(self, conn):
                """Wrap a real connection and count statements."""
                self.conn = conn
                self.calls = 0

            def execute(self, sql, *args):
                """Fail once the configured number of statements has passed."""
                self.calls += 1
                if self.calls > statements_before_failure:
                    raise sqlite3.OperationalError("disk I/O error")
                return self.conn.execute(sql, *args)

            def close(self):
                """Close the wrapped connection."""
                self.conn.close()

        monkeypatch.setattr(ou.sqlite3, "connect", lambda *a, **k: Failing(real_connect(*a, **k)))
        verdict = ou._has_semsql_schema(str(db), require_content=True)
        assert verdict is None, f"a disk error {where} must not be reported as a schema failure"

    def test_a_connect_failure_is_not_a_schema_verdict(self, tmp_path, monkeypatch):
        """connect() failing for an unrelated reason establishes nothing either."""
        db = write_semsql_db(tmp_path / "ncbitaxon.db")

        def boom(*args, **kwargs):
            """Fail the connection itself."""
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(ou.sqlite3, "connect", boom)
        assert ou._has_semsql_schema(str(db)) is None

    def test_a_non_sqlite_file_is_still_a_definitive_failure(self, tmp_path):
        """Widening the unknown cases must not soften the evidential ones."""
        db = tmp_path / "junk.db"
        db.write_bytes(b"NOT A DATABASE" * 500)
        assert ou._has_semsql_schema(str(db)) is False


class TestOntologyIdentityAndServing:

    """Round-13: a generic SemSQL database is not evidence of the right ontology."""

    def test_the_wrong_ontology_is_refused(self):
        """
        Everything about a SemSQL DB is generic except which terms it holds.

        `ncbitaxon.db` pointing at a copy of `chebi.db` passed schema, content,
        size and metatraits' own validation, while taxon lookups returned nothing
        and the transform quietly accumulated unresolved taxa.
        """
        if not Path("data/raw/chebi.db").exists():
            pytest.skip("data/raw/chebi.db is not present")
        assert ou._db_is_for_ontology("data/raw/chebi.db", "ncbitaxon") is False
        assert ou._db_is_for_ontology("data/raw/chebi.db", "chebi") is True

    def test_cross_references_do_not_count_as_identity(self):
        """
        ec.db contains thousands of GO subjects as cross-references.

        A prefix-existence check would have accepted it as GO; matching the
        ontology's own release row does not.
        """
        if not Path("data/raw/ec.db").exists():
            pytest.skip("data/raw/ec.db is not present")
        assert ou._db_is_for_ontology("data/raw/ec.db", "go") is False
        assert ou._db_is_for_ontology("data/raw/ec.db", "ec") is True

    def test_preserving_and_serving_are_different_questions(self, tmp_path):
        """
        A locked database may be kept but must not answer queries.

        Reporting it usable meant every per-term query failed inside bakta's
        broad handler, defaulting biological-process terms to molecular_function.
        Declining to rebuild is right; authorising queries is not.
        """
        db = write_semsql_db(tmp_path / "go.db")
        with db.open("ab") as handle:
            handle.write(b"\0" * 20000)
        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("INSERT INTO statements (subject, predicate, value) VALUES ('a', 'b', 'c')")
        try:
            assert ou._reusable_db(str(db), 8) is True, "a locked DB must not be destroyed"
            assert ou._servable_db(str(db), 8, "go") is False, "a locked DB must not serve queries"
        finally:
            holder.rollback()
            holder.close()

    def test_go_namespace_map_refuses_to_guess(self, tmp_path, monkeypatch):
        """
        A failed ensure must abort, not yield an empty map.

        The result was discarded, so a missing go.db fell through to a plain
        sqlite3.connect() — which *creates* the file — and the failed query was
        cached as an empty map. Every GO term then became BiologicalProcess: the
        exact failure this work exists to prevent, through the one path that
        never checked.
        """
        monkeypatch.setattr(ou, "_GO_NAMESPACE_CACHE", None)
        monkeypatch.setattr(ou, "_GO_NAMESPACE_LOAD_FAILED", False)
        monkeypatch.setattr(ou, "_ensure_go_db", lambda _: ou.DbEnsureResult(False))
        target = tmp_path / "go.db"

        with pytest.raises(ou.FatalOntologyError):
            ou._load_go_namespace_map(str(target))

        assert not target.exists(), "the loader must not create an empty database"

    def test_a_wrong_ontology_target_cannot_displace_the_correct_prev(self, tmp_path, monkeypatch):
        """
        Ranking was ontology-blind, so it could delete the only correct copy.

        A GO database sitting at chebi.db ranked equal to a genuine ChEBI .prev,
        displaced it, and a failed build then restored the GO one — leaving no
        copy of the ontology that was asked for.
        """
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 3000)
        owl = tmp_path / "chebi.owl"
        owl.write_text("<owl/>", encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        db = write_single_ontology_db(tmp_path / "chebi.db", "go")
        prev = write_single_ontology_db(tmp_path / "chebi.db.prev", "chebi")
        correct = prev.read_bytes()

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", lambda *a, **k: None)
        ou._build_semsql_db(owl, str(db), 3000, "ChEBI", "n", ontology="chebi")

        survivors = [p for p in tmp_path.iterdir() if p.is_file() and p.read_bytes() == correct]
        assert survivors, "the copy holding the requested ontology must survive"

    @pytest.mark.parametrize("scenario", ["no-semsql", "opt-out"])
    def test_a_wrong_ontology_is_refused_on_the_no_build_paths(self, tmp_path, monkeypatch, scenario):
        """
        Identity was checked on the serving path only.

        The fallback and opt-out exits re-authorised a database the identity
        probe had just rejected.
        """
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 3000)
        owl = tmp_path / "chebi.owl"
        owl.write_text("<owl/>", encoding="utf-8")
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        db = write_single_ontology_db(tmp_path / "chebi.db", "go")

        if scenario == "no-semsql":
            monkeypatch.setattr(ou.shutil, "which", lambda _: None)
        else:
            monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
            monkeypatch.setenv("KG_SEMSQL_BUILD", "off")

        assert not ou._ensure_chebi_db(str(db)), f"{scenario} must not serve the wrong ontology"

    def test_a_build_producing_the_wrong_ontology_is_not_a_success(self, tmp_path, monkeypatch):
        """Post-build acceptance was identity-blind too."""
        monkeypatch.setattr(ou, "_GO_DB_MIN_SIZE", 3000)
        owl = tmp_path / "go.owl"
        owl.write_text("<owl/>", encoding="utf-8")
        db = tmp_path / "go.db"

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", lambda *a, **k: write_single_ontology_db(db, "chebi"))
        result = ou._build_semsql_db(owl, str(db), 3000, "GO", "n", ontology="go")
        assert not result.built, "a build producing another ontology is not a successful build"
