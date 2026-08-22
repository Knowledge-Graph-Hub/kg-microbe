"""
Tests for the NCBITaxon pre-flight (_ensure_ncbitaxon_db_ready).

Its contract, from its own docstring: when it returns, workers calling
_get_ncbitaxon_adapter find a valid DB; when no valid DB can be found it raises.
The whole point is to fail *before* workers fork, because a failure inside a
worker surfaces as an unhandled exception per taxon instead of one clear error.

A round-5 review found the guard added for "don't discard a freshly built DB"
had broken both halves of that contract: it applied to any real file and it
returned instead of falling through to the raise. These tests pin the contract.
"""

import subprocess

import pytest

from kg_microbe.transform_utils.metatraits import metatraits as mt
from kg_microbe.utils.ontology_utils import DbEnsureResult
from tests.db_helpers import valid_db_bytes


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the module at a temp local DB and OAK cache."""
    local = tmp_path / "ncbitaxon.db"
    cache = tmp_path / "oak" / "ncbitaxon.db"
    cache.parent.mkdir()
    monkeypatch.setattr(mt, "_ncbitaxon_db_paths", lambda: (local, cache))
    return local, cache


def _validation(results):
    """Return a _validate_ncbitaxon_db stand-in driven by a {path: (ok, reason)} map."""

    def validate(path):
        """Look the verdict up by resolved path, defaulting to invalid."""
        return results.get(str(path), (False, "stubbed invalid"))

    return validate


class TestPreflightContract:
    """It must either leave a valid DB in place or raise."""

    def test_valid_local_db_is_accepted(self, paths, monkeypatch):
        """The happy path returns without replacing anything."""
        local, _ = paths
        local.write_bytes(b"db")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(local): (True, "")}))
        monkeypatch.setattr(
            "kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db",
            lambda _: DbEnsureResult(True),
        )
        mt._ensure_ncbitaxon_db_ready()
        assert not local.is_symlink()

    def test_builder_runs_even_when_the_db_would_validate(self, paths, monkeypatch):
        """
        The builder must not be gated behind validation (F3).

        Validation only asks whether the DB is readable, so a healthy DB at the
        wrong release passed it and the drift rebuild was unreachable — leaving
        the single-source rule advisory for NCBITaxon.
        """
        local, _ = paths
        local.write_bytes(b"db")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(local): (True, "")}))
        called = []
        monkeypatch.setattr(
            "kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db",
            lambda p: called.append(p) or DbEnsureResult(True),
        )

        mt._ensure_ncbitaxon_db_ready()

        assert called == [str(local)], "the builder must run before validation decides"

    def test_a_restore_is_not_reported_as_a_fresh_build(self, paths, monkeypatch):
        """
        A restored .prev must not trip the fresh-build guard (F2).

        The builder reports `built` itself now; inferring it from "a file appeared"
        misreported a restore as a build, printed a false message, and skipped the
        healthy OAK fallback.
        """
        local, cache = paths
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))

        def restore_only(_):
            """Put an old DB back without having built anything."""
            local.write_bytes(b"restored, still invalid")
            return DbEnsureResult(True, built=False)

        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", restore_only)

        # A restore is not a build, so the message must not claim one — and the
        # restored DB is still a real file, so it is kept rather than replaced.
        with pytest.raises(RuntimeError) as excinfo:
            mt._ensure_ncbitaxon_db_ready()
        assert "just built from the OWL" not in str(excinfo.value)
        assert local.exists() and not local.is_symlink()

    def test_a_real_but_invalid_local_db_is_never_silently_replaced(self, paths, monkeypatch):
        """
        A real local DB that fails validation must not be swapped for the cache.

        Deliberate trade: this used to self-heal by symlinking to OAK, but the
        pipeline cannot tell a corrupt leftover from a 13 GB build that took
        hours, and silently deleting the latter is far worse than asking for an
        explicit `rm`. Keying the protection on "did this call build it" instead
        lasted exactly one run (#635).
        """
        local, cache = paths
        local.write_bytes(b"corrupt but large")
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))
        monkeypatch.setattr(
            "kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db",
            lambda _: DbEnsureResult(True),
        )

        with pytest.raises(RuntimeError, match="failed validation"):
            mt._ensure_ncbitaxon_db_ready()
        assert local.exists() and not local.is_symlink(), "the local DB must survive"

    def test_protection_holds_on_a_second_run(self, paths, monkeypatch):
        """
        The guard must not evaporate once `built` is False (#635).

        Run 1 builds an invalid DB and raises. Run 2 reuses it, so the builder
        reports built=False — and the old guard let the fallback delete it.
        """
        local, cache = paths
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))

        def build_once(_):
            """Build on the first call, reuse on the second."""
            if not local.exists():
                local.write_bytes(b"freshly built but broken")
                return DbEnsureResult(True, built=True)
            return DbEnsureResult(True, built=False)

        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", build_once)

        for run in (1, 2):
            with pytest.raises(RuntimeError, match="failed validation"):
                mt._ensure_ncbitaxon_db_ready()
            assert local.exists() and not local.is_symlink(), f"run {run} deleted the build"

    def test_absent_local_db_still_falls_back_to_the_cache(self, paths, monkeypatch):
        """With no local DB at all, the OAK symlink is still the right repair."""
        local, cache = paths
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))
        monkeypatch.setattr(
            "kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db",
            lambda _: DbEnsureResult(False),
        )

        mt._ensure_ncbitaxon_db_ready()

        assert local.is_symlink() and local.resolve() == cache.resolve()

    def test_no_valid_db_anywhere_raises(self, paths, monkeypatch):
        """With nothing usable anywhere it must raise — workers fork after this."""
        local, _ = paths  # no local file, no valid cache
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({}))
        monkeypatch.setattr(
            "kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db",
            lambda _: DbEnsureResult(True),
        )

        with pytest.raises(RuntimeError, match="NCBITaxon OAK database is missing or corrupt"):
            mt._ensure_ncbitaxon_db_ready()

    def test_freshly_built_but_invalid_db_raises_rather_than_being_discarded(self, paths, monkeypatch):
        """
        A build that produced an unusable DB must fail loudly, keeping the artifact.

        Replacing it with the OAK symlink would throw away hours of work; returning
        silently would hand workers a broken adapter. Neither is acceptable.
        """
        local, cache = paths
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))

        def build(_):
            """Produce a new DB where there was none, and say so."""
            local.write_bytes(b"freshly built but broken")
            return DbEnsureResult(True, built=True)

        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", build)

        with pytest.raises(RuntimeError, match="failed validation"):
            mt._ensure_ncbitaxon_db_ready()
        assert local.exists() and not local.is_symlink(), "the fresh build must survive"


class TestRealBuilderIntegration:
    """
    Exercise the real _ensure_ncbitaxon_db through the pre-flight.

    Every other test here stubs the builder, which is exactly how a defect in
    their interaction (a restored .prev reported as a fresh build) survived a
    review round. Only `semsql` itself is mocked.
    """

    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        """Point both the pre-flight and the builder at a temp data/raw."""
        from kg_microbe.utils import ontology_utils as ou

        local = tmp_path / "ncbitaxon.db"
        cache = tmp_path / "oak" / "ncbitaxon.db"
        cache.parent.mkdir()
        owl = tmp_path / "ncbitaxon.owl"
        owl.write_text(
            '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/ncbitaxon/2026-07-12/ncbitaxon.owl"/>'
        )
        monkeypatch.setattr(mt, "_ncbitaxon_db_paths", lambda: (local, cache))
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", owl)
        monkeypatch.setattr(ou, "_NCBITAXON_DB_MIN_SIZE", 8)
        monkeypatch.setattr(mt, "_NCBITAXON_DB_MIN_SIZE", 8)
        monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")
        return local, cache, ou

    def test_restored_prev_after_a_failed_build_falls_back_to_the_cache(self, wired, monkeypatch):
        """The end-to-end shape of F2: orphan adopted, build fails, restore, fall back."""
        local, cache, ou = wired
        cache.write_bytes(b"good cache")
        (local.parent / "ncbitaxon.db.prev").write_bytes(valid_db_bytes(b"prev"))

        def boom(cmd, **kwargs):
            """Fail the way an OOM does."""
            raise subprocess.CalledProcessError(137, cmd)

        monkeypatch.setattr(ou.subprocess, "run", boom)
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))

        with pytest.raises(RuntimeError) as excinfo:
            mt._ensure_ncbitaxon_db_ready()

        # A restore is not a build, so the message must not claim one; and the
        # restored real DB is kept rather than swapped for the cache.
        assert "just built from the OWL" not in str(excinfo.value)
        assert local.exists() and not local.is_symlink(), "the restored DB must survive"
        assert not (local.parent / "ncbitaxon.db.prev").exists(), "no orphan left behind"

    def test_a_genuinely_fresh_but_invalid_build_raises(self, wired, monkeypatch):
        """The other side: a real build that fails validation keeps the artifact."""
        local, cache, ou = wired
        cache.write_bytes(b"good cache")

        def build(cmd, **kwargs):
            """Produce a new DB at the target."""
            local.write_bytes(b"0" * 32)

        monkeypatch.setattr(ou.subprocess, "run", build)
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))

        with pytest.raises(RuntimeError, match="failed validation"):
            mt._ensure_ncbitaxon_db_ready()
        assert local.exists() and not local.is_symlink(), "the fresh build must survive"
