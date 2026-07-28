"""
Tests for building chebi.db from the chebi.owl we ship, and gating its release.

Third application of the GO single-source rule (#604), after GO and NCBITaxon.
ChEBI is the awkward case: it versions by an incrementing integer
(``versionIRI .../obo/chebi/253/chebi.owl``) rather than an OBO ``YYYY-MM-DD``
stamp, so the shared date-based reader returns None for it and any gate built on
that reader silently passes. These tests pin the ChEBI-specific reader, the
builder, and the gate.

No test runs a real `semsql make`: the build is mocked and size thresholds
shrunk.
"""

import sqlite3
import subprocess
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou
from tests.db_helpers import valid_db_bytes

OWL_VERSION_IRI = '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/chebi/{v}/chebi.owl"/>\n'
OWL_VERSION_INFO = "<owl:versionInfo>{v}</owl:versionInfo>\n"


def _write_owl(tmp_path, monkeypatch, body):
    """Write a chebi.owl with `body` and point CHEBI_SOURCE at it."""
    path = tmp_path / "chebi.owl"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", path)
    return path


def _make_db(tmp_path, release, *, subject="obo:chebi.owl", name="chebi.db"):
    """Build a minimal SemSQL-shaped DB stamped with `release`."""
    path = str(tmp_path / name)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
    conn.execute("INSERT INTO statements VALUES (?, 'owl:versionInfo', NULL, ?)", (subject, str(release)))
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _clear_adapter_cache():
    """Drop the memoized ChEBI adapter so tests can't see each other's."""
    ou.get_chebi_adapter.cache_clear()
    yield
    ou.get_chebi_adapter.cache_clear()


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


class TestChebiReleaseReader:

    """ChEBI's integer stamp must be read where the date reader cannot."""

    def test_reads_version_iri(self, tmp_path):
        """The release comes out of the versionIRI path segment."""
        path = tmp_path / "chebi.owl"
        path.write_text(OWL_VERSION_IRI.format(v=253), encoding="utf-8")
        assert ou._chebi_release_from_owl(path) == "253"

    def test_reads_version_info(self, tmp_path):
        """Falls back to owl:versionInfo when there is no versionIRI."""
        path = tmp_path / "chebi.owl"
        path.write_text(OWL_VERSION_INFO.format(v=251), encoding="utf-8")
        assert ou._chebi_release_from_owl(path) == "251"

    def test_date_reader_cannot_see_it(self, tmp_path):
        """Regression note: this is why a date-based gate silently no-ops."""
        path = tmp_path / "chebi.owl"
        path.write_text(OWL_VERSION_IRI.format(v=253), encoding="utf-8")
        assert ou._obo_release_from_head(path) is None
        assert ou._chebi_release_from_owl(path) == "253"

    def test_unstamped_returns_none(self, tmp_path):
        """No stamp means None, which makes the gate and builder conservative."""
        path = tmp_path / "chebi.owl"
        path.write_text("no version here", encoding="utf-8")
        assert ou._chebi_release_from_owl(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        """An absent OWL is not an error for the reader."""
        assert ou._chebi_release_from_owl(tmp_path / "absent.owl") is None

    def test_db_release_read(self, tmp_path):
        """_chebi_db_release reads the stamp off the ontology subject."""
        assert ou._chebi_db_release(_make_db(tmp_path, 253)) == "253"

    def test_db_release_ignores_term_subject(self, tmp_path):
        """A version-shaped value on a CHEBI: term must not be mistaken for the release."""
        path = str(tmp_path / "chebi.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
        conn.execute("INSERT INTO statements VALUES ('CHEBI:16828', 'owl:versionInfo', NULL, '999')")
        conn.execute("INSERT INTO statements VALUES ('obo:chebi.owl', 'owl:versionInfo', NULL, '253')")
        conn.commit()
        conn.close()
        assert ou._chebi_db_release(path) == "253"

    def test_db_release_none_on_garbage(self, tmp_path):
        """A non-SQLite file yields None rather than raising."""
        path = tmp_path / "chebi.db"
        path.write_text("not a database", encoding="utf-8")
        assert ou._chebi_db_release(str(path)) is None


class TestChebiGate:

    """The gate must fire on drift and stay quiet otherwise."""

    def test_aligned_is_silent(self, tmp_path, monkeypatch, capsys):
        """Matching releases produce no output."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        ou.assert_chebi_version_alignment(_make_db(tmp_path, 253))
        assert capsys.readouterr().out == ""

    def test_mismatch_warns_by_default(self, tmp_path, monkeypatch, capsys):
        """Default is warn, so a fallback DB of another release can't abort a build."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        ou.assert_chebi_version_alignment(_make_db(tmp_path, 251))
        out = capsys.readouterr().out
        assert "WARNING" in out and "chebi.owl=253" in out and "chebi.db=251" in out

    def test_mismatch_raises_in_strict_mode(self, tmp_path, monkeypatch):
        """Explicit strict escalates the same mismatch to a failure."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        with pytest.raises(ou.OntologyVersionMismatchError, match="ChEBI source version mismatch"):
            ou.assert_chebi_version_alignment(_make_db(tmp_path, 251), strict=True)

    def test_env_var_escalates(self, tmp_path, monkeypatch):
        """KG_CHEBI_VERSION_CHECK=strict flips the default."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        monkeypatch.setenv("KG_CHEBI_VERSION_CHECK", "strict")
        with pytest.raises(ou.OntologyVersionMismatchError):
            ou.assert_chebi_version_alignment(_make_db(tmp_path, 251))

    def test_unreadable_stamp_is_a_noop(self, tmp_path, monkeypatch, capsys):
        """An unstamped OWL must not warn (nothing to compare)."""
        _write_owl(tmp_path, monkeypatch, "no version here")
        ou.assert_chebi_version_alignment(_make_db(tmp_path, 251))
        assert capsys.readouterr().out == ""


class TestChebiBuild:

    """Build behaviour mirrors _ensure_go_db / _ensure_ncbitaxon_db."""

    def test_aligned_db_is_reused(self, tmp_path, monkeypatch):
        """No rebuild when the DB already matches the OWL."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _make_db(tmp_path, 253)
        calls = _fake_build(monkeypatch, db)
        assert ou._ensure_chebi_db(str(db))
        assert calls == []

    def test_drifted_db_is_rebuilt(self, tmp_path, monkeypatch, capsys):
        """A DB at a different ChEBI release is rebuilt from the OWL."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        source = _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _make_db(tmp_path, 251)
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_chebi_db(str(db))
        assert calls == [(["semsql", "make", "chebi.db"], str(source.parent))]
        assert "drifted" in capsys.readouterr().out

    def test_decompresses_archive_when_owl_absent(self, tmp_path, monkeypatch):
        """Semsql needs chebi.owl; the download only ships chebi.owl.gz."""
        import gzip as gz

        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        owl = tmp_path / "chebi.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        with gz.open(tmp_path / "chebi.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_VERSION_IRI.format(v=253))

        db = tmp_path / "chebi.db"
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_chebi_db(str(db))
        assert owl.exists(), "chebi.owl.gz should have been decompressed"
        assert "253" in owl.read_text(encoding="utf-8")
        assert len(calls) == 1

    def test_dangling_symlink_target_is_cleared(self, tmp_path, monkeypatch):
        """A broken symlink must not redirect the build to the link's target (#1)."""
        import pathlib

        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        db = tmp_path / "chebi.db"
        db.symlink_to(elsewhere / "chebi.db")

        def run(cmd, **kwargs):
            """Write to the target name the way semsql does, following any symlink."""
            with open(pathlib.Path(kwargs["cwd"]) / "chebi.db", "wb") as f:
                f.write(valid_db_bytes(pad=32))

        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        monkeypatch.setattr(ou.subprocess, "run", run)

        assert ou._ensure_chebi_db(str(db))
        assert not db.is_symlink()
        assert list(elsewhere.iterdir()) == [], "nothing should reach the link target"

    def test_truncated_archive_degrades_gracefully(self, tmp_path, monkeypatch):
        """A truncated chebi.owl.gz raises EOFError, which must still be caught (#2)."""
        import gzip as gz

        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        owl = tmp_path / "chebi.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        archive = tmp_path / "chebi.owl.gz"
        with gz.open(archive, "wt", encoding="utf-8") as f:
            f.write(OWL_VERSION_IRI.format(v=253) * 500)
        archive.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

        assert not ou._ensure_chebi_db(str(tmp_path / "chebi.db"))
        assert not owl.exists()
        assert not (tmp_path / "chebi.owl.partial").exists()

    def test_stub_db_is_not_reported_usable(self, tmp_path, monkeypatch):
        """
        A 0-byte chebi.db must not pass as usable on the no-build paths (F1).

        os.path.exists is True for a stub, so the min-size guard used to apply
        only to a freshly built result. A stub yields an adapter with no
        entailed_edge table and collapses every ChEBI term to the default
        category — the failure _GO_DB_MIN_SIZE exists to prevent.
        """
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        db.write_bytes(b"")  # threshold left at the real 100 MB
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)
        assert not ou._ensure_chebi_db(str(db))

    def test_stub_db_rejected_under_opt_out(self, tmp_path, monkeypatch):
        """The KG_SEMSQL_BUILD=off path must apply the same size guard."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        db.write_bytes(b"")
        monkeypatch.setenv("KG_SEMSQL_BUILD", "off")
        assert not ou._ensure_chebi_db(str(db))

    def test_reuse_check_reads_release_from_the_archive(self, tmp_path, monkeypatch):
        """
        Drift must be detected when only chebi.owl.gz is on disk (F2).

        The reuse branch reads chebi.owl, which a fresh checkout does not have —
        so the release came back None, the drift check short-circuited, and the
        stale DB was kept with the gate silently no-oping.
        """
        import gzip as gz

        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        owl = tmp_path / "chebi.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        with gz.open(tmp_path / "chebi.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _make_db(tmp_path, 251)  # older release, DB large enough to be "reusable"
        calls = _fake_build(monkeypatch, db)

        assert ou._ensure_chebi_db(str(db))
        assert len(calls) == 1, "drift against the .gz release should trigger a rebuild"

    def test_gate_reads_release_from_the_archive(self, tmp_path, monkeypatch, capsys):
        """The version gate must also see the release when only the .gz exists (F2)."""
        import gzip as gz

        owl = tmp_path / "chebi.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        with gz.open(tmp_path / "chebi.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_VERSION_IRI.format(v=253))

        ou.assert_chebi_version_alignment(_make_db(tmp_path, 251))
        assert "chebi.owl=253" in capsys.readouterr().out

    def test_failed_build_restores_the_previous_db(self, tmp_path, monkeypatch):
        """A build that dies must not leave the caller with nothing (F3)."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db_path = _make_db(tmp_path, 251)  # drifted but working
        db = Path(db_path)
        original = db.read_bytes()
        _fake_build(monkeypatch, db, fail=True)

        result = ou._ensure_chebi_db(db_path)
        assert db.exists(), "the working DB must be restored after a failed build"
        assert db.read_bytes() == original
        assert result, "the restored DB is still usable"
        assert not Path(f"{db_path}.prev").exists(), "the keep-aside copy should be gone"

    def test_failed_build_restores_a_symlinked_prebuilt_db(self, tmp_path, monkeypatch):
        """
        A failed rebuild must not destroy a symlinked prebuilt DB (F1).

        Supplying one by symlink is supported — get_chebi_adapter's own error text
        recommends it — but _clear_build_target used to unlink it with no record,
        so the failure path left the user with nothing and an error telling them
        to supply the prebuilt DB they had just lost.
        """
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        prebuilt = tmp_path / "prebuilt.db"
        prebuilt.write_bytes(valid_db_bytes(pad=64))
        db = tmp_path / "chebi.db"
        db.symlink_to(prebuilt)
        monkeypatch.setattr(ou, "_chebi_db_release", lambda _: "251")  # drift → rebuild
        _fake_build(monkeypatch, db, fail=True)

        result = ou._ensure_chebi_db(str(db))

        assert db.is_symlink(), "the symlink must be restored"
        assert db.resolve() == prebuilt.resolve()
        assert result and not result.built

    def test_strict_version_gate_is_not_swallowed(self, tmp_path, monkeypatch):
        """KG_CHEBI_VERSION_CHECK=strict must abort, not degrade to a default (F6)."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db_path = _make_db(tmp_path, 251)
        monkeypatch.setattr(ou, "_ensure_chebi_db", lambda _: ou.DbEnsureResult(True))
        monkeypatch.setenv("KG_CHEBI_VERSION_CHECK", "strict")

        with pytest.raises(ou.OntologyVersionMismatchError, match="ChEBI source version mismatch"):
            ou.get_chebi_category("CHEBI:16828")
        assert Path(db_path).exists()

    def test_strict_gate_is_not_swallowed_on_the_bulk_path_either(self, tmp_path, monkeypatch):
        """
        The production path supplies an adapter, which the test above never did.

        _fix_node_categories passes get_chebi_adapter() into get_chebi_category
        for every row. Once that became a lazy proxy, resolution moved inside the
        broad `except Exception` around the lookups, so the strict abort was
        swallowed per-row and every ChEBI node took the default category — while
        the adapter=None test above stayed green throughout.
        """
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        _make_db(tmp_path, 251)
        monkeypatch.setattr(ou, "_ensure_chebi_db", lambda _: ou.DbEnsureResult(True))
        monkeypatch.setenv("KG_CHEBI_VERSION_CHECK", "strict")
        ou.get_ontology_adapter.cache_clear()

        try:
            adapter = ou.get_chebi_adapter()  # unresolved proxy, as production has
            with pytest.raises(ou.OntologyVersionMismatchError, match="ChEBI source version mismatch"):
                ou.get_chebi_category("CHEBI:16828", adapter)
        finally:
            ou.get_ontology_adapter.cache_clear()

    def test_missing_semsql_keeps_existing_db(self, tmp_path, monkeypatch, capsys):
        """Without semsql, keep whatever DB is present instead of deleting it."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db_path = _make_db(tmp_path, 251)
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)

        assert ou._ensure_chebi_db(db_path)
        assert "semsql" in capsys.readouterr().out

    def test_missing_owl_and_archive_warns(self, tmp_path, monkeypatch, capsys):
        """Neither OWL nor archive means no build; report it."""
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", tmp_path / "chebi.owl")
        assert not ou._ensure_chebi_db(str(tmp_path / "chebi.db"))
        assert "missing" in capsys.readouterr().out

    def test_failed_build_returns_false(self, tmp_path, monkeypatch, capsys):
        """A semsql crash is reported, not raised."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _fake_build(monkeypatch, db, fail=True)
        assert not ou._ensure_chebi_db(str(db))
        assert "failed to build" in capsys.readouterr().out

    def test_undersized_result_is_rejected(self, tmp_path, monkeypatch):
        """A stub-sized build result is not reported as usable."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _fake_build(monkeypatch, db, size=16)  # threshold stays at 100 MB
        assert not ou._ensure_chebi_db(str(db))

    def test_opt_out_skips_the_build(self, tmp_path, monkeypatch, capsys):
        """KG_SEMSQL_BUILD=off must not start a 30-minute build (#613)."""
        monkeypatch.setattr(ou, "_CHEBI_DB_MIN_SIZE", 8)
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        db = tmp_path / "chebi.db"
        _make_db(tmp_path, 251)  # drifted, so a build would otherwise run
        calls = _fake_build(monkeypatch, db)
        monkeypatch.setenv("KG_SEMSQL_BUILD", "off")

        assert ou._ensure_chebi_db(str(db))
        assert calls == [], "opt-out must skip semsql entirely"
        assert "opt-out" in capsys.readouterr().out

    def test_decompression_is_atomic(self, tmp_path, monkeypatch):
        """An interrupted decompression must not leave a truncated OWL (#615)."""
        import gzip as gz

        owl = tmp_path / "chebi.owl"
        monkeypatch.setattr("kg_microbe.transform_utils.constants.CHEBI_SOURCE", owl)
        with gz.open(tmp_path / "chebi.owl.gz", "wt", encoding="utf-8") as f:
            f.write(OWL_VERSION_IRI.format(v=253))

        def boom(src, dst, *a, **k):
            """Fail part-way through the copy, as a full disk or Ctrl-C would."""
            dst.write(b"<owl:versionIRI rdf:resource=")
            raise OSError("no space left on device")

        monkeypatch.setattr(ou.shutil, "copyfileobj", boom)
        assert not ou._ensure_chebi_db(str(tmp_path / "chebi.db"))
        assert not owl.exists(), "a partial decompression must not appear at the real path"
        assert not (tmp_path / "chebi.owl.partial").exists(), "temp file should be cleaned up"


class TestAdapterEntryPoint:

    """Both category-fixing paths must go through one ensured adapter."""

    def test_get_chebi_adapter_ensures_and_gates(self, tmp_path, monkeypatch):
        """get_chebi_adapter builds/realigns, runs the gate, then opens the DB."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        seen = {}

        monkeypatch.setattr(ou, "_ensure_chebi_db", lambda p: seen.setdefault("ensured", p) or True)
        monkeypatch.setattr(ou, "assert_chebi_version_alignment", lambda p: seen.setdefault("gated", p))
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: seen.setdefault("adapter", spec))

        ou.get_ontology_adapter("chebi")

        expected = str(tmp_path / "chebi.db")
        assert seen["ensured"] == expected
        assert seen["gated"] == expected
        assert seen["adapter"] == f"sqlite:{expected}"

    def test_failed_ensure_raises_actionable_error(self, tmp_path, monkeypatch):
        """An unbuildable DB must not be handed to OAK as a missing path (#616)."""
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        monkeypatch.setattr(ou, "_ensure_chebi_db", lambda _: False)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: pytest.fail("must not open a missing DB"))
        with pytest.raises(ou.OntologyDbUnavailableError, match="No usable chebi SemSQL DB"):
            ou.get_ontology_adapter("chebi")

    def test_standalone_category_lookup_degrades_instead_of_raising(self, tmp_path, monkeypatch):
        """
        get_chebi_category() with no adapter must not abort the caller (#7).

        The bulk transform builds its adapter up front, so a missing DB fails
        loudly there. But this helper's contract is "return a category", and
        before the adapter was centralised it degraded to the default. Keep that.
        """
        from kg_microbe.transform_utils.constants import SMALL_MOLECULE_CATEGORY

        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        monkeypatch.setattr(ou, "_ensure_chebi_db", lambda _: False)
        assert ou.get_chebi_category("CHEBI:16828") == SMALL_MOLECULE_CATEGORY

    def test_adapter_work_happens_once(self, tmp_path, monkeypatch):
        """
        Repeat calls reuse the memoized adapter rather than re-ensuring (#618).

        Uses the eager entry point: get_chebi_adapter() now returns a lazy proxy,
        and two proxies are distinct objects even though they share one cached
        adapter underneath.
        """
        _write_owl(tmp_path, monkeypatch, OWL_VERSION_IRI.format(v=253))
        counts = {"ensure": 0, "gate": 0, "adapter": 0}

        def ensure(_):
            """Count ensure invocations."""
            counts["ensure"] += 1
            return True

        def gate(_):
            """Count gate invocations."""
            counts["gate"] += 1

        def adapter(_):
            """Count adapter constructions."""
            counts["adapter"] += 1
            return object()

        monkeypatch.setattr(ou, "_ensure_chebi_db", ensure)
        monkeypatch.setattr(ou, "assert_chebi_version_alignment", gate)
        monkeypatch.setattr("oaklib.get_adapter", adapter)

        first = ou.get_ontology_adapter("chebi")
        second = ou.get_ontology_adapter("chebi")

        assert first is second
        assert counts == {"ensure": 1, "gate": 1, "adapter": 1}
