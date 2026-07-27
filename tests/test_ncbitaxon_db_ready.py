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

import pytest

from kg_microbe.transform_utils.metatraits import metatraits as mt


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
        """The happy path returns without touching anything."""
        local, _ = paths
        local.write_bytes(b"db")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(local): (True, "")}))
        mt._ensure_ncbitaxon_db_ready()
        assert not local.is_symlink()

    def test_invalid_local_db_falls_back_to_the_cache(self, paths, monkeypatch):
        """
        A pre-existing DB that fails validation is replaced by the OAK symlink.

        This is the self-healing case; the round-5 regression turned it into a
        silent success with the corrupt DB left in place.
        """
        local, cache = paths
        local.write_bytes(b"corrupt but large")
        cache.write_bytes(b"good")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({str(cache): (True, "")}))
        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", lambda _: True)

        mt._ensure_ncbitaxon_db_ready()

        assert local.is_symlink() and local.resolve() == cache.resolve()

    def test_no_valid_db_anywhere_raises(self, paths, monkeypatch):
        """With nothing usable it must raise, not return — workers fork after this."""
        local, _ = paths
        local.write_bytes(b"corrupt")
        monkeypatch.setattr(mt, "_validate_ncbitaxon_db", _validation({}))
        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", lambda _: True)

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
            """Produce a new DB where there was none."""
            local.write_bytes(b"freshly built but broken")
            return True

        monkeypatch.setattr("kg_microbe.utils.ontology_utils._ensure_ncbitaxon_db", build)

        with pytest.raises(RuntimeError, match="failed validation"):
            mt._ensure_ncbitaxon_db_ready()
        assert local.exists() and not local.is_symlink(), "the fresh build must survive"


class TestFingerprint:

    """The built-here test must distinguish a new DB from a pre-existing one."""

    def test_absent_file_has_no_fingerprint(self, tmp_path):
        """A missing DB fingerprints as None."""
        assert mt._db_fingerprint(tmp_path / "absent.db") is None

    def test_rewrite_changes_the_fingerprint(self, tmp_path):
        """Different content yields a different fingerprint."""
        path = tmp_path / "x.db"
        path.write_bytes(b"one")
        before = mt._db_fingerprint(path)
        path.write_bytes(b"a different length")
        assert mt._db_fingerprint(path) != before

    def test_untouched_file_keeps_its_fingerprint(self, tmp_path):
        """An unmodified DB must not look like a fresh build."""
        path = tmp_path / "x.db"
        path.write_bytes(b"one")
        assert mt._db_fingerprint(path) == mt._db_fingerprint(path)
