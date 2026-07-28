"""
Tests for atomic derived-cache writes.

Several caches in this repo are generated once and then guarded by a bare
``path.exists()``. Writing them in place makes any mid-write failure permanent:
the header lands, the generator raises, and every later run sees a file that
exists and skips regeneration. These tests pin the fix.
"""

import csv
import os
import time
from pathlib import Path
from unittest import mock

import pytest

from kg_microbe.utils import ontology_utils as ou
from kg_microbe.utils import uniprot_utils as uu
from kg_microbe.utils.atomic_io import atomic_write, cache_is_complete, has_data_rows


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


class TestAllPoisonedCachesHeal:

    """
    Every .exists()-guarded cache must reject a header-only file, not just GO's.

    The first pass fixed only go_category_trees.tsv, which was the one with a
    demonstrated consequence — leaving BactoTraits, Wallen and the Madin NER
    outputs able to keep an existing poisoned file forever.
    """

    @pytest.mark.parametrize(
        "header",
        [
            "GO_Category\tGO_Term\n",
            "Bacdive_ID\tculture_collection_number\tncbitaxon_id\n",
            "orig_node\tentity_uri\n",
            "object_id\tobject_label\tsubject_label\n",
        ],
    )
    def test_header_only_files_are_not_complete(self, tmp_path, header):
        """A header with no data rows must read as incomplete for every cache."""
        target = tmp_path / "cache.tsv"
        target.write_text(header)
        assert not has_data_rows(target)

    def test_one_data_row_is_enough(self, tmp_path):
        """A cache with content must not be needlessly regenerated."""
        target = tmp_path / "cache.tsv"
        target.write_text("a\tb\nx\ty\n")
        assert has_data_rows(target)

    def test_unreadable_file_is_conservative(self, tmp_path):
        """An unreadable cache regenerates rather than being trusted blindly."""
        target = tmp_path / "nested" / "cache.tsv"
        assert not has_data_rows(target)


class TestCallSitesUseTheGuardedHelpers:

    """
    Behavioural, not textual.

    The first version of these asserted that certain strings appeared in the
    source. Codex reverted all four call sites to `.exists()` while leaving the
    expected strings behind in comments, and every one still passed. A test that
    greps for its own fix is not a test.
    """

    def test_annotate_marks_its_outputs_complete(self, tmp_path, monkeypatch):
        """A finished NER run must record completion, even producing no rows."""
        import pandas as pd

        from kg_microbe.utils import ner_utils

        class FakeAdapter:

            """Annotates nothing, as a run over an unmatched input would."""

            def annotate_text(self, text, configuration):
                """Return no annotations."""
                return []

        monkeypatch.setattr(ner_utils, "get_ontology_adapter", lambda _: FakeAdapter())
        outfile = tmp_path / "chebi_result.tsv"
        ner_utils.annotate(pd.DataFrame({"terms": ["nothing-matches"]}), "CHEBI:", [], outfile)

        assert outfile.exists()
        assert cache_is_complete(outfile), "a correctly-empty result must count as complete"
        assert not has_data_rows(outfile), "and it genuinely has no data rows"

    def test_a_correctly_empty_cache_is_not_regenerated_forever(self, tmp_path):
        """
        The regression the completion marker exists to prevent.

        Judging on row count alone, a run that correctly produced zero rows was
        indistinguishable from a truncated one, so it regenerated on every run.
        """
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\n")
        assert cache_is_complete(target)

    def test_a_legacy_header_only_cache_still_heals(self, tmp_path):
        """Written by the pre-marker code, so no marker: must regenerate once."""
        target = tmp_path / "cache.tsv"
        target.write_text("a\tb\n")
        assert not cache_is_complete(target)

    def test_a_truncated_write_leaves_neither_file_nor_marker(self, tmp_path):
        """An interrupted write must not publish a marker for a missing file."""
        target = tmp_path / "cache.tsv"
        with pytest.raises(ValueError):
            with atomic_write(target, mark_complete=True) as handle:
                handle.write("a\tb\n")
                raise ValueError("boom")
        assert not target.exists()
        assert not Path(f"{target}.complete").exists()

    def test_stale_partials_are_swept_but_live_ones_are_not(self, tmp_path):
        """A SIGKILLed writer's temp must not accumulate; a live one must survive."""
        target = tmp_path / "cache.tsv"
        stale = tmp_path / "cache.tsv.999.0.partial"
        stale.write_text("orphaned")
        os.utime(stale, (0, 0))  # long dead
        fresh = tmp_path / "cache.tsv.998.0.partial"
        fresh.write_text("another writer, still going")

        with atomic_write(target) as handle:
            handle.write("done\n")

        assert not stale.exists(), "a day-old partial must be swept"
        assert fresh.exists(), "a concurrent writer's temp must be left alone"


class TestMarkerAndSweeperAdversarial:

    """Round-4: the completion marker and the stale-partial sweeper."""

    def test_marker_does_not_certify_a_replaced_file(self, tmp_path):
        """
        An empty marker vouched for whatever later occupied the path.

        So a header-only file dropped in after a complete run was re-certified
        as complete — the poisoning the marker exists to prevent, reintroduced
        by the marker itself.
        """
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\nx\ty\n")
        assert cache_is_complete(target)

        target.write_text("a\tb\n")  # replaced out of band, header only
        assert not cache_is_complete(target), "the marker must not vouch for a different file"

    def test_marker_survives_an_ordinary_reread(self, tmp_path):
        """Validation must not be so strict that a normal cache re-reads as incomplete."""
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\n")  # legitimately empty result
        assert cache_is_complete(target)
        assert cache_is_complete(target), "repeated checks must be stable"

    @pytest.mark.parametrize("skew_days", [2, -2])
    def test_sweeper_ignores_target_mtime_skew(self, tmp_path, skew_days):
        """
        The cutoff derives from wall clock, not the target's mtime.

        Deriving it from the target meant a future timestamp swept a live
        writer's temp, and an old one left stranded partials forever.
        """
        target = tmp_path / "cache.tsv"
        target.write_text("seed\n")
        live = tmp_path / "cache.tsv.999.0.partial"
        live.write_text("another writer, still going")
        orphan = tmp_path / "cache.tsv.998.0.partial"
        orphan.write_text("stranded by a SIGKILL")
        os.utime(orphan, (0, 0))

        skew = time.time() + skew_days * 86400
        os.utime(target, (skew, skew))
        with atomic_write(target) as handle:
            handle.write("done\n")

        assert live.exists(), "a concurrent writer's temp must never be swept"
        assert not orphan.exists(), "a long-dead partial must be swept regardless of skew"
