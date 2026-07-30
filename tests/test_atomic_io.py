"""
Tests for atomic derived-cache writes.

Several caches in this repo are generated once and then guarded by a bare
``path.exists()``. Writing them in place makes any mid-write failure permanent:
the header lands, the generator raises, and every later run sees a file that
exists and skips regeneration. These tests pin the fix.
"""

import ast
import csv
import os
import re
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

    def test_only_a_marked_cache_counts_as_complete(self, tmp_path, monkeypatch):
        """
        Content cannot establish completion; only the marker can.

        Row count was the earlier rule, and it accepted a legacy cache
        interrupted after its first row — for the GO trees that means the
        molecular-function rows survive while biological-process and
        cellular-component are silently missing. An unmarked cache is therefore
        regenerated once, after which it carries a marker and never is again.
        """
        target = tmp_path / "go_category_trees.tsv"
        monkeypatch.setattr(uu, "GO_CATEGORY_TREES_FILE", target)
        assert not uu.go_category_trees_is_complete(), "absent"

        target.write_text("GO_Category\tGO_Term\nGO:0008150\tGO:0000001\n")
        assert not uu.go_category_trees_is_complete(), "unmarked legacy cache must regenerate once"

        with atomic_write(target, mark_complete=True) as handle:
            handle.write("GO_Category\tGO_Term\nGO:0008150\tGO:0000001\n")
        assert uu.go_category_trees_is_complete(), "a marked cache is complete"

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
    Each cache guard must *decide* regeneration, and each writer must be used.

    Three attempts precede this. Substrings were satisfied by comments.
    Behavioural tests of the helpers exercised no call site at all. Counting
    helper-shaped calls per module was satisfied by calling the helper and
    discarding the result, or by leaving an `atomic_write(...)` expression whose
    context manager is never entered.

    So the assertions below require the guard call to sit inside a conditional
    test, and the writer to appear as a `with` item — the two things that make
    them actually do their job.
    """

    # (module, expected count, substring the guarded argument must mention).
    # Naming the cache is what stops `cache_is_complete(unrelated_path)` beside
    # an unconditionally regenerated real cache from satisfying the assertion.
    GUARDS = [
        ("kg_microbe/transform_utils/bactotraits/bactotraits.py", 1, ("mapping_file",)),
        ("kg_microbe/transform_utils/wallen_etal/wallen_etal.py", 1, ("WALLEN_ETAL_TMP_FILEPATH",)),
        ("kg_microbe/transform_utils/madin_etal/madin_etal.py", 1, ("chebi_result_fn",)),
        ("kg_microbe/transform_utils/madin_etal/madin_etal.py", 1, ("go_result_fn",)),
        ("kg_microbe/transform_utils/uniprot_functional_microbes/uniprot_functional_microbes.py", 1, ()),
        ("kg_microbe/transform_utils/uniprot_human/uniprot_human.py", 1, ()),
    ]

    WRITERS = [
        ("kg_microbe/transform_utils/bactotraits/bactotraits.py", 1),
        ("kg_microbe/transform_utils/wallen_etal/wallen_etal.py", 1),
        ("kg_microbe/transform_utils/madin_etal/madin_etal.py", 2),
        ("kg_microbe/utils/ner_utils.py", 2),
        ("kg_microbe/utils/uniprot_utils.py", 1),
        ("kg_microbe/utils/pandas_utils.py", 1),
    ]

    GUARD_NAMES = {"cache_is_complete", "go_category_trees_is_complete"}

    @staticmethod
    def _tree(module_path):
        """Parse a module from the repository."""
        return ast.parse((Path(__file__).parent.parent / module_path).read_text(encoding="utf-8"))

    @classmethod
    def _deciding_guard_calls(cls, module_path, names_cache=""):
        """Count guard calls that control a branch and name the intended cache."""
        source = (Path(__file__).parent.parent / module_path).read_text(encoding="utf-8")
        found = 0
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.If, ast.IfExp)):
                continue
            for sub in ast.walk(node.test):
                if not isinstance(sub, ast.Call):
                    continue
                called = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                if called not in cls.GUARD_NAMES:
                    continue
                argument = " ".join(ast.get_source_segment(source, a) or "" for a in sub.args)
                # Token match, not substring: `not_mapping_file` used to satisfy
                # a `mapping_file` requirement.
                tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", argument))
                # Exact token, not substring: `not_mapping_file` satisfied a
                # `mapping_file` substring requirement while guarding nothing.
                if names_cache and not tokens & set(names_cache):
                    continue
                found += 1
        return found

    @classmethod
    def _context_managed_writes(cls, module_path):
        """Count atomic_write calls actually used as context managers."""
        found = 0
        for node in ast.walk(cls._tree(module_path)):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                expr = item.context_expr
                called = (
                    getattr(expr.func, "id", None) or getattr(expr.func, "attr", None)
                    if isinstance(expr, ast.Call)
                    else None
                )
                if called == "atomic_write":
                    found += 1
        return found

    @pytest.mark.parametrize("module_path, count, names_cache", GUARDS)
    def test_guard_result_controls_regeneration(self, module_path, count, names_cache):
        """
        Calling the guard is not enough; its answer must decide the branch.

        Reverting to `.exists()`, or calling the helper and ignoring what it
        returns, both fail here.
        """
        actual = self._deciding_guard_calls(module_path, names_cache)
        assert actual >= count, (
            f"{module_path}: expected >= {count} completeness check(s) controlling a branch "
            f"and naming one of {names_cache or ('the cache',)}, found {actual}"
        )

    @pytest.mark.parametrize("module_path, count", WRITERS)
    def test_writers_are_atomic_context_managers(self, module_path, count):
        """A bare `atomic_write(...)` that is never entered writes nothing."""
        actual = self._context_managed_writes(module_path)
        assert actual >= count, f"{module_path}: expected >= {count} atomic_write context manager(s), found {actual}"

    @pytest.mark.parametrize("module_path, _count, _names", GUARDS)
    def test_no_cache_path_is_guarded_by_bare_existence(self, module_path, _count, _names):
        """
        No branch may test a cache path's mere existence.

        Resolves aliases, so renaming the variable before calling `.exists()`
        does not hide it — that exact reversion previously went unnoticed.
        """
        tree = self._tree(module_path)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = node.value.id

        def _root(name, seen=None):
            """Follow an alias chain back to the name it ultimately refers to."""
            seen = seen or set()
            while name in aliases and name not in seen:
                seen.add(name)
                name = aliases[name]
            return name

        cache_hints = ("mapping_file", "TMP_FILEPATH", "result_fn", "TREES_FILE", "CATEGORY_TREES")
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp)):
                continue
            for sub in ast.walk(node.test):
                if not isinstance(sub, ast.Call):
                    continue
                attr = getattr(sub.func, "attr", None)
                if attr not in {"exists", "is_file"}:
                    continue
                # `os.path.exists(cache)` puts the cache in the arguments, while
                # `cache.exists()` puts it in the receiver. Only the receiver was
                # examined, so the function form went unnoticed.
                value = sub.args[0] if sub.args else sub.func.value
                names = {_root(n.id) for n in ast.walk(value) if isinstance(n, ast.Name)}
                names |= {getattr(n, "attr", "") for n in ast.walk(value) if isinstance(n, ast.Attribute)}
                if any(hint in name for name in names for hint in cache_hints):
                    offenders.append(f"{module_path}:{sub.lineno}")
        assert offenders == [], f"cache regeneration must not be guarded by bare existence: {offenders}"


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


class TestMarkerIdentity:

    """A marker must certify the file it was written for, and no other."""

    def test_same_size_replacement_is_not_certified(self, tmp_path):
        """
        Size alone let any equal-length file inherit the certificate.

        A cache replaced out of band by a different file of the same length was
        still reported complete.
        """
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\nx\ty\n")
        assert cache_is_complete(target)

        # Header-only, so the content fallback cannot vouch for it either — the
        # marker is the only thing that could, which is what this isolates.
        same_length = "q\tr\tuvw\n"
        assert len(same_length) == target.stat().st_size, "the replacement must match byte length"
        target.write_text(same_length)
        assert not cache_is_complete(target), "an equal-sized replacement must not be certified"

    def test_empty_legacy_marker_certifies_nothing(self, tmp_path):
        """
        The interim marker format was an empty file, which vouched for anything.

        A legacy marker beside a broken cache must fall through to the content
        check rather than declare it complete.
        """
        target = tmp_path / "cache.tsv"
        target.write_text("broken\n")
        Path(f"{target}.complete").write_text("")
        assert not cache_is_complete(target)

    def test_a_marked_empty_cache_is_still_complete(self, tmp_path):
        """The behaviour the marker exists for must survive the hardening."""
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\n")  # header only, legitimately
        assert cache_is_complete(target)
        assert not has_data_rows(target)


class TestMarkerIsConclusive:

    """Round-15: a digest mismatch must not be overridden by a row count."""

    def test_a_truncated_marked_cache_is_incomplete(self, tmp_path):
        """
        The content fallback undid the digest entirely.

        A marked three-row cache truncated to its header plus one row still
        reported complete, so UniProt skipped regeneration and the remaining
        category mappings stayed lost.
        """
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\nr1\tx\nr2\ty\nr3\tz\n")
        assert cache_is_complete(target)

        target.write_text("a\tb\nr1\tx\n")
        assert not cache_is_complete(target), "a digest mismatch is conclusive"

    def test_a_marked_empty_cache_is_still_complete(self, tmp_path):
        """The legitimately-empty case must survive the stricter rule."""
        target = tmp_path / "cache.tsv"
        with atomic_write(target, mark_complete=True) as handle:
            handle.write("a\tb\n")
        assert cache_is_complete(target)
        assert not has_data_rows(target)
