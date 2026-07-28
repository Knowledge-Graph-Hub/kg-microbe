"""
Tests for atomic derived-cache writes.

Several caches in this repo are generated once and then guarded by a bare
``path.exists()``. Writing them in place makes any mid-write failure permanent:
the header lands, the generator raises, and every later run sees a file that
exists and skips regeneration. These tests pin the fix.
"""

import csv
from unittest import mock

import pytest

from kg_microbe.utils import ontology_utils as ou
from kg_microbe.utils import uniprot_utils as uu
from kg_microbe.utils.atomic_io import atomic_write


class TestAtomicWrite:

    """The helper itself."""

    def test_content_is_committed_on_success(self, tmp_path):
        """A clean run leaves the complete file and no temp."""
        target = tmp_path / "out.tsv"
        with atomic_write(target) as fh:
            fh.write("done\n")
        assert target.read_text() == "done\n"
        assert list(tmp_path.glob("*.partial")) == []

    def test_nothing_is_left_when_the_writer_raises(self, tmp_path):
        """A failed run must leave no file for an .exists() guard to accept."""
        target = tmp_path / "out.tsv"
        with pytest.raises(ValueError):
            with atomic_write(target) as fh:
                fh.write("header\n")
                raise ValueError("boom")
        assert not target.exists(), "a partial write must not be visible"
        assert list(tmp_path.glob("*.partial")) == [], "no temp file may be stranded"

    def test_base_exception_also_cleans_up(self, tmp_path):
        """
        The fatal ontology errors are BaseExceptions, not Exceptions.

        Cleanup lives in `finally` precisely so those unwind cleanly too — an
        `except Exception` would have missed exactly the case this exists for.
        """
        target = tmp_path / "out.tsv"
        with pytest.raises(ou.OntologyDbUnavailableError):
            with atomic_write(target) as fh:
                fh.write("header\n")
                raise ou.OntologyDbUnavailableError("no db")
        assert not target.exists()
        assert list(tmp_path.glob("*.partial")) == []

    def test_existing_file_survives_a_failed_rewrite(self, tmp_path):
        """The old copy is untouched until the rename, so a failure keeps it."""
        target = tmp_path / "out.tsv"
        target.write_text("previous\n")
        with pytest.raises(ValueError):
            with atomic_write(target) as fh:
                fh.write("replacement\n")
                raise ValueError("boom")
        assert target.read_text() == "previous\n"

    def test_parent_directory_is_created(self, tmp_path):
        """Callers should not have to makedirs first."""
        target = tmp_path / "nested" / "deeper" / "out.tsv"
        with atomic_write(target) as fh:
            fh.write("x\n")
        assert target.read_text() == "x\n"


class TestGoCategoryTreesIsNotPoisoned:

    """The concrete case: go_category_trees.tsv (Codex F2)."""

    class _Unavailable:

        """A lazy proxy whose resolution fails."""

        def __getattr__(self, name):
            """Fail on any public attribute, as a failed resolution would."""
            if name.startswith("_"):
                raise AttributeError(name)
            raise ou.OntologyDbUnavailableError("no usable go.db")

    class _Fake:

        """A working GO adapter."""

        def descendants(self, start_curies, predicates, reflexive):
            """Return two descendants per category root."""
            return [f"{start_curies}:child1", f"{start_curies}:child2"]

    @pytest.fixture
    def trees_file(self, tmp_path, monkeypatch):
        """Point the trees cache at a temp path."""
        target = tmp_path / "trees" / "go_category_trees.tsv"
        monkeypatch.setattr(uu, "GO_CATEGORY_TREES_FILE", target)
        monkeypatch.setattr(uu, "ONTOLOGIES_TREES_DIR", target.parent)
        return target

    def test_unusable_go_db_leaves_no_header_only_file(self, trees_file):
        """
        The failure that dropped every protein→GO edge, permanently.

        The old in-place write emitted the header, then resolved the adapter on
        the first descendants() call. A header-only file exists, so the
        `.exists()` guards in both UniProt transforms skipped regeneration
        forever, prepare_go_dictionary returned {}, and every GO term was logged
        as obsolete with a zero exit code.
        """
        with pytest.raises(ou.FatalOntologyError):
            uu.get_go_category_trees(self._Unavailable())
        assert not trees_file.exists(), "a poisoned cache must not be left behind"

    def test_next_run_regenerates_after_a_failure(self, trees_file):
        """Having failed once, a later run with a working DB must rebuild it."""
        with pytest.raises(ou.FatalOntologyError):
            uu.get_go_category_trees(self._Unavailable())

        uu.get_go_category_trees(self._Fake())

        with open(trees_file) as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        assert len(rows) == 6, "three category roots x two descendants"

    def test_a_complete_run_is_readable_by_prepare_go_dictionary(self, trees_file, monkeypatch):
        """The committed file must round-trip through the real consumer."""
        uu.get_go_category_trees(self._Fake())
        loaded = uu.prepare_go_dictionary()
        assert loaded, "a complete cache must not read as an empty dict"
        assert len(loaded) == 6

    def test_lazy_adapter_is_resolved_before_the_file_is_opened(self, trees_file, monkeypatch):
        """
        Surface the failure before any work starts.

        Atomicity already prevents the poisoning; resolving first means the run
        does not walk the ontology only to throw the result away, and the error
        names the real problem instead of surfacing mid-write. Uses a genuine
        _LazyOntologyAdapter — resolve_adapter is a no-op for anything else, so
        a hand-rolled stub would not exercise this path.
        """
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: False)
        ou.get_ontology_adapter.cache_clear()
        try:
            proxy = ou.get_go_adapter()
            with mock.patch.object(uu, "atomic_write", side_effect=AssertionError("opened too early")):
                with pytest.raises(ou.OntologyDbUnavailableError):
                    uu.get_go_category_trees(proxy)
        finally:
            ou.get_ontology_adapter.cache_clear()

        assert not trees_file.exists()


class TestExistingPoisonedCacheHeals:

    """Atomic writes stop new poisoning; an *existing* poisoned file must heal."""

    def test_header_only_cache_is_not_treated_as_complete(self, tmp_path, monkeypatch):
        """
        The migration case: a user upgrades with a poisoned file already on disk.

        The old in-place writer left header-only files, and the guard was a bare
        .exists() — so the fix alone would never have repaired them.
        """
        target = tmp_path / "go_category_trees.tsv"
        target.write_text("GO_Category\tGO_Term\n")
        monkeypatch.setattr(uu, "GO_CATEGORY_TREES_FILE", target)
        assert not uu.go_category_trees_is_complete(), "a header-only cache must count as absent"

    def test_absent_and_complete_caches_are_classified_correctly(self, tmp_path, monkeypatch):
        """A real cache is complete; a missing one is not."""
        target = tmp_path / "go_category_trees.tsv"
        monkeypatch.setattr(uu, "GO_CATEGORY_TREES_FILE", target)
        assert not uu.go_category_trees_is_complete()
        target.write_text("GO_Category\tGO_Term\nGO:0008150\tGO:0000001\n")
        assert uu.go_category_trees_is_complete()

    def test_concurrent_writers_do_not_share_a_temp_file(self, tmp_path):
        """
        A shared "<name>.partial" is not actually atomic across writers.

        B truncates the same inode A is mid-write on, renames it into place, and
        A keeps writing through a descriptor that now points at the published
        file.
        """
        target = tmp_path / "cache.tsv"
        seen = []
        with atomic_write(target) as a:
            a.write("A")
            with atomic_write(target) as b:
                b.write("B")
                seen = sorted(p.name for p in tmp_path.glob("*.partial"))
        assert len(seen) == 2, f"each writer needs its own temp file, saw {seen}"
        assert target.read_text() == "A", "the outer writer commits last and wins"
