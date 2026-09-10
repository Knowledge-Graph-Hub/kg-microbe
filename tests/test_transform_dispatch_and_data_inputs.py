"""Tests for loud transform dispatch (#813) and declared data inputs (#812)."""

import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock

import pytest

from kg_microbe.transform import DATA_SOURCES, LazyTransform, TransformBatchError, transform
from kg_microbe.transform_utils.transform import Transform

REPO_ROOT = Path(__file__).resolve().parents[1]
ISO = "mappings/isolation_source_to_ontology.tsv"
SSSOM = "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"


class UnknownSourceTest(TestCase):
    """A typo'd source must fail, not silently succeed."""

    def test_an_unknown_source_raises_rather_than_being_skipped(self):
        """
        The bug: `if source in DATA_SOURCES:` with no else.

        `kg transform -s bacdiv` exited 0 having done nothing, which is
        indistinguishable from a successful run and from a transform that died
        early — the exact ambiguity that stalled a diagnosis on 2026-08-16.
        """
        with pytest.raises(ValueError) as excinfo:
            transform(None, None, sources=["bacdiv"])
        message = str(excinfo.value)
        self.assertIn("bacdiv", message)
        self.assertIn("bacdive", message, "the error should list valid sources so the typo is obvious")

    def test_one_unknown_source_stops_the_whole_batch(self):
        """
        Refuse before running anything, so a batch cannot half-complete.

        Running the good sources and quietly dropping the bad one is how a
        partial rebuild gets mistaken for a full one.
        """
        with mock.patch.dict(DATA_SOURCES, {}, clear=False):
            with pytest.raises(ValueError):
                transform(None, None, sources=["bacdive", "definitely-not-a-source"])


class LazyTransformTest(TestCase):
    """Registry metadata inspection must survive unavailable optional modules."""

    def test_missing_module_uses_getattr_default_for_metadata(self):
        """Registry metadata reads use the caller's default when import fails."""
        proxy = LazyTransform("kg_microbe.not_installed.MissingTransform")
        self.assertEqual(getattr(proxy, "DATA_INPUTS", ()), ())

    def test_missing_module_still_fails_when_transform_is_run(self):
        """Actually running an unavailable transform preserves the import error."""
        proxy = LazyTransform("kg_microbe.not_installed.MissingTransform")
        with self.assertRaises(ModuleNotFoundError):
            proxy()

    def test_freshness_helper_degrades_when_registered_module_is_unavailable(self):
        """Freshness inspection continues when one optional transform cannot import."""
        spec = importlib.util.spec_from_file_location(
            "kgm_freshness_check_lazy",
            REPO_ROOT / ".claude" / "skills" / "kgm-freshness-check" / "kgm_freshness_check.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["kgm_freshness_check_lazy"] = module
        spec.loader.exec_module(module)
        with mock.patch.dict(DATA_SOURCES, {"missing": LazyTransform("kg_microbe.not_installed.Missing")}, clear=False):
            self.assertEqual(module._declared_data_inputs("missing"), ())


class DataInputsTest(TestCase):
    """Transforms declare the curation files they read, so staleness is visible."""

    def test_the_base_class_defaults_to_no_declared_inputs(self):
        """Most transforms read only their own download; the default must be empty."""
        self.assertEqual(Transform.DATA_INPUTS, ())

    def test_bacdive_declares_both_files_it_reads(self):
        """
        Bacdive consumes the isolation-source map and the unified chemical SSSOM.

        #778 corrected 16 ids in the former and #786 rewrote the latter, and the
        merged KG built afterwards still asserted 75 organisms isolated from a
        "Cell Line" because nothing re-ran this transform.
        """
        declared = DATA_SOURCES["bacdive"].DATA_INPUTS
        self.assertIn(ISO, declared)
        self.assertIn(SSSOM, declared)

    def test_every_declared_input_exists_on_disk(self):
        """A declaration naming a moved or deleted file silently checks nothing."""
        for name, cls in DATA_SOURCES.items():
            for rel in getattr(cls, "DATA_INPUTS", ()):
                self.assertTrue(
                    (REPO_ROOT / rel).exists(),
                    f"{name} declares DATA_INPUTS {rel!r}, which does not exist",
                )

    def test_metatraits_gtdb_inherits_rather_than_redeclaring(self):
        """Subclasses must not need their own copy — a second list is a second thing to forget."""
        self.assertEqual(
            DATA_SOURCES["metatraits_gtdb"].DATA_INPUTS,
            DATA_SOURCES["metatraits"].DATA_INPUTS,
        )

    def test_every_sssom_consumer_declares_it(self):
        """
        Guard against the next consumer forgetting.

        Anything importing `chemical_mapping_utils` reads the unified SSSOM, so
        the two sets must agree or the freshness check under-reports.
        """
        transform_root = REPO_ROOT / "kg_microbe" / "transform_utils"
        consumers = set()
        for py in transform_root.glob("*/[a-z]*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            if "chemical_mapping_utils" in text:
                consumers.add(py.parent.name)
        for source in sorted(consumers):
            cls = DATA_SOURCES.get(source)
            if cls is None:
                continue  # not a registered transform (helper package)
            self.assertIn(
                SSSOM,
                getattr(cls, "DATA_INPUTS", ()),
                f"{source} reads the unified chemical SSSOM but does not declare it in DATA_INPUTS",
            )


class FreshnessDataStalenessTest(TestCase):
    """
    The freshness check must report data staleness, not just code staleness.

    These tests drive the *timestamp* path. ``check_source`` consults the
    content fingerprint first, and on a checkout where the transform has run
    the real ``data/transformed/<source>/source_fingerprint.json`` decided the
    verdict and the mocks below never mattered -- two tests failed locally and
    passed in CI, which has no output (#1001). The fingerprint verdict is
    stubbed to "no marker" here; the content path has its own tests below.
    """

    def setUp(self):
        """Import the standalone freshness script and take the marker out of play."""
        spec = importlib.util.spec_from_file_location(
            "kgm_freshness_check",
            REPO_ROOT / ".claude" / "skills" / "kgm-freshness-check" / "kgm_freshness_check.py",
        )
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["kgm_freshness_check"] = self.mod
        spec.loader.exec_module(self.mod)
        no_marker = mock.patch.object(self.mod, "_fingerprint_verdict", return_value=None)
        no_marker.start()
        self.addCleanup(no_marker.stop)

    def test_a_content_verdict_wins_over_stale_timestamps(self):
        """
        #1001: this is why the marker had to be stubbed for the tests below.

        With a marker that verifies, ``check_source`` reports FRESH whatever the
        timestamps say -- correct for the tool, and exactly what made the
        timestamp-path tests depend on the developer having run the pipeline.
        """
        with (
            mock.patch.object(self.mod, "_fingerprint_verdict", return_value=("FRESH", "verified by content")),
            mock.patch.object(self.mod, "_latest_commit", return_value=(3000, "deadbee")),
            mock.patch.object(self.mod, "_has_local_diff", return_value=False),
            mock.patch.object(self.mod, "_output_mtime", return_value=2000),
            mock.patch.object(self.mod, "_latest_data_input_commit", return_value=(4000, f"{ISO} @ abc1234")),
        ):
            report = self.mod.check_source("bacdive", "origin/master")
        self.assertEqual(report.status, "FRESH")
        self.assertIn("verified by content", report.note)

    def test_it_reads_declared_inputs_from_the_transform_classes(self):
        """
        Derived from code, not a second hard-coded table in the skill.

        A table here would drift from the transforms it describes, and a stale
        declaration is indistinguishable from a fresh one.
        """
        self.assertIn(ISO, self.mod._declared_data_inputs("bacdive"))
        self.assertEqual(self.mod._declared_data_inputs("bactotraits"), ())

    def test_an_output_older_than_its_data_input_is_stale(self):
        """
        The #812 case: code untouched, mapping changed, output not rebuilt.

        Previously reported FRESH, which is why a re-merge shipped groundings
        two merged PRs had already corrected.
        """
        with (
            mock.patch.object(self.mod, "_latest_commit", return_value=(1000, "deadbee")),
            mock.patch.object(self.mod, "_has_local_diff", return_value=False),
            mock.patch.object(self.mod, "_output_mtime", return_value=2000),
            mock.patch.object(self.mod, "_declared_data_inputs", return_value=(ISO,)),
            mock.patch.object(self.mod, "_latest_data_input_commit", return_value=(3000, f"{ISO} @ abc1234")),
        ):
            report = self.mod.check_source("bacdive", "origin/master")
        self.assertEqual(report.status, "STALE_VS_DATA")
        self.assertIn(ISO, report.note)

    def test_a_source_with_no_declared_inputs_is_unaffected(self):
        """The check must not invent staleness for transforms that read no curation files."""
        with (
            mock.patch.object(self.mod, "_latest_commit", return_value=(1000, "deadbee")),
            mock.patch.object(self.mod, "_has_local_diff", return_value=False),
            mock.patch.object(self.mod, "_output_mtime", return_value=2000),
            mock.patch.object(self.mod, "_latest_data_input_commit", return_value=(None, None)),
        ):
            report = self.mod.check_source("bactotraits", "origin/master")
        self.assertEqual(report.status, "FRESH")

    def test_stale_code_and_stale_data_are_reported_together(self):
        """Fixing only the one you were told about would leave the other in place."""
        with (
            mock.patch.object(self.mod, "_latest_commit", return_value=(3000, "deadbee")),
            mock.patch.object(self.mod, "_has_local_diff", return_value=False),
            mock.patch.object(self.mod, "_output_mtime", return_value=2000),
            mock.patch.object(self.mod, "_latest_data_input_commit", return_value=(4000, f"{ISO} @ abc1234")),
        ):
            report = self.mod.check_source("bacdive", "origin/master")
        self.assertEqual(report.status, "STALE_VS_CODE_AND_DATA")


class FreshnessSchemaTest(TestCase):
    """A schema change must mark output stale, once the marker records one (#943)."""

    def setUp(self):
        """Import the standalone freshness script."""
        spec = importlib.util.spec_from_file_location(
            "kgm_freshness_check",
            REPO_ROOT / ".claude" / "skills" / "kgm-freshness-check" / "kgm_freshness_check.py",
        )
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["kgm_freshness_check"] = self.mod
        spec.loader.exec_module(self.mod)

    def test_a_shared_code_change_is_stale_and_says_so(self):
        """
        #1002: a change under kg_microbe/utils/ must not read FRESH.

        Recorded apart from the package digest, so the note can name which moved.
        """
        import kg_microbe.utils.transform_fingerprint as fp

        marker = {"version": fp.FINGERPRINT_VERSION, "code": "c", "shared": "old", "data": "d", "upstream": "u"}
        with (
            mock.patch.object(fp, "read_fingerprint", return_value=marker),
            mock.patch.object(fp, "code_fingerprint", return_value="c"),
            mock.patch.object(fp, "shared_code_fingerprint", return_value="new"),
            mock.patch.object(fp, "data_fingerprint", return_value="d"),
            mock.patch.object(fp, "upstream_fingerprint", return_value="u"),
            mock.patch.object(fp, "schema_fingerprint", return_value=None),
        ):
            code_dir = REPO_ROOT / "kg_microbe" / "transform_utils" / "bactotraits"
            status, note = self.mod._fingerprint_verdict("bactotraits", code_dir)
        self.assertEqual(status, "STALE_VS_CODE")
        self.assertIn("shared code", note)

    def _verdict(self, recorded_schema):
        """
        Run ``_fingerprint_verdict`` over a marker whose other fields all match.

        :param recorded_schema: The ``schema`` value in the marker.
        :return: ``(status, note)``.
        """
        import kg_microbe.utils.transform_fingerprint as fp

        marker = {"version": fp.FINGERPRINT_VERSION, "code": "c", "shared": "s", "data": "d", "upstream": "u"}
        if recorded_schema is not None:
            marker["schema"] = recorded_schema
        with (
            mock.patch.object(fp, "read_fingerprint", return_value=marker),
            mock.patch.object(fp, "code_fingerprint", return_value="c"),
            mock.patch.object(fp, "shared_code_fingerprint", return_value="s"),
            mock.patch.object(fp, "data_fingerprint", return_value="d"),
            mock.patch.object(fp, "upstream_fingerprint", return_value="u"),
            mock.patch.object(fp, "schema_fingerprint", return_value={"version": "4.4.2", "digest": "new"}),
        ):
            code_dir = REPO_ROOT / "kg_microbe" / "transform_utils" / "bactotraits"
            return self.mod._fingerprint_verdict("bactotraits", code_dir)

    def test_a_recorded_schema_that_moved_is_stale(self):
        """The #941 case: pin moved 4.3.6 -> 4.4.2, code and data untouched."""
        status, note = self._verdict({"version": "4.3.6", "digest": "old"})
        self.assertEqual(status, "STALE_VS_SCHEMA")
        self.assertIn("4.3.6", note)
        self.assertIn("4.4.2", note)

    def test_a_matching_schema_is_fresh(self):
        """Recording the schema must not invent staleness."""
        self.assertEqual(self._verdict({"version": "4.4.2", "digest": "new"})[0], "FRESH")

    def test_a_marker_without_a_schema_is_not_judged_on_it(self):
        """Unknown provenance is not wrong provenance (#911)."""
        self.assertEqual(self._verdict(None)[0], "FRESH")


def _fake_source(name: str, log: list, base: Path, raises=None, inputs=()):
    """Build a registry entry that records its run and optionally fails."""

    class Fake:
        DATA_INPUTS = ()
        TRANSFORM_INPUTS = inputs

        def __init__(self, input_dir, output_dir):
            self.output_dir = base / name
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def run(self, show_status=True):
            log.append(name)
            if raises is not None:
                raise raises

    return Fake


class BatchIsolationTest(TestCase):
    """#685: one source failing must not take the rest of the batch with it."""

    def setUp(self):
        """Make a scratch output root and an empty run log."""
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.log = []

    def tearDown(self):
        """Drop the scratch root."""
        self._tmp.cleanup()

    def test_a_failure_is_isolated_and_reported_at_the_end(self):
        """
        `mediadive` raising mid-batch used to abort seven sources behind it.

        Now the later sources run, and the batch ends non-zero with a summary
        naming what failed.
        """
        registry = {
            "a": _fake_source("a", self.log, self.base, raises=RuntimeError("bulk data missing")),
            "b": _fake_source("b", self.log, self.base),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=["a", "b"])
        self.assertEqual(self.log, ["a", "b"])
        self.assertEqual(list(excinfo.value.failed), ["a"])
        self.assertIn("a: RuntimeError: bulk data missing", str(excinfo.value))

    def test_a_dependent_of_a_failed_source_is_skipped_not_built_on_stale_output(self):
        """A source that declares the failed one in TRANSFORM_INPUTS must not run against its stale output."""
        registry = {
            "gtdb": _fake_source("gtdb", self.log, self.base, raises=RuntimeError("boom")),
            "lpsn": _fake_source("lpsn", self.log, self.base, inputs=("gtdb",)),
            "lpsn_api": _fake_source("lpsn_api", self.log, self.base, inputs=("lpsn",)),
            "gold": _fake_source("gold", self.log, self.base),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=["gtdb", "lpsn", "lpsn_api", "gold"])
        self.assertEqual(self.log, ["gtdb", "gold"])
        self.assertEqual(excinfo.value.skipped, {"lpsn": ["gtdb"], "lpsn_api": ["lpsn"]})
        self.assertIn("skipped: lpsn_api: upstream lpsn did not complete", str(excinfo.value))

    def test_a_base_exception_still_aborts_the_batch(self):
        """FatalOntologyError subclasses BaseException on purpose; isolation must not swallow it."""

        class Fatal(BaseException):
            pass

        registry = {
            "a": _fake_source("a", self.log, self.base, raises=Fatal()),
            "b": _fake_source("b", self.log, self.base),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(Fatal):
                transform(None, None, sources=["a", "b"])
        self.assertEqual(self.log, ["a"])

    def test_a_clean_batch_raises_nothing(self):
        """No failure, no exception: the old contract for the good path is unchanged."""
        registry = {"a": _fake_source("a", self.log, self.base), "b": _fake_source("b", self.log, self.base)}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=["a", "b"])
        self.assertEqual(self.log, ["a", "b"])

    def test_a_missing_declared_input_fails_before_anything_runs(self):
        """A missing curation file is known in seconds; do not spend hours finding out."""
        fake = _fake_source("a", self.log, self.base)
        fake.DATA_INPUTS = ("mappings/this-file-does-not-exist.tsv",)
        registry = {"early": _fake_source("early", self.log, self.base), "a": fake}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(FileNotFoundError) as excinfo:
                transform(None, None, sources=["early", "a"])
        self.assertEqual(self.log, [])
        self.assertIn("a: mappings/this-file-does-not-exist.tsv", str(excinfo.value))


class SingleOntologySourceTest(TestCase):
    """#690: `-s ec` runs one ontology; the branch meant to do this was unreachable."""

    def setUp(self):
        """Scratch output root."""
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        """Drop it."""
        self._tmp.cleanup()

    def _ontologies_fake(self, calls: list):
        base = self.base

        class FakeOntologies:
            DATA_INPUTS = ()
            TRANSFORM_INPUTS = ()

            def __init__(self, input_dir, output_dir):
                self.output_dir = base / "ontologies"
                self.output_dir.mkdir(parents=True, exist_ok=True)

            def run(self, data_file=None, show_status=True):
                calls.append(data_file)
                (self.output_dir / "ec_nodes.tsv").write_text("id\tname\nEC:1.1.1.1\tx\n")
                (self.output_dir / "chebi_nodes.tsv").write_text("id\tname\nCHEBI:1\ty\nCHEBI:2\tz\n")

        return FakeOntologies

    def test_an_ontology_name_runs_only_that_ontology_and_leaves_the_fingerprint_alone(self):
        """One ontology's file is refreshed; the directory-wide marker is not rewritten to claim the rest are."""
        calls = []
        with (
            mock.patch.dict(DATA_SOURCES, {"ontologies": self._ontologies_fake(calls)}, clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json", "chebi": "chebi.json"}),
        ):
            transform(None, None, sources=["ec"])
        self.assertEqual(calls, ["ec.json"])
        self.assertFalse((self.base / "ontologies" / "source_fingerprint.json").exists())

    def test_the_completion_line_counts_only_that_ontology(self):
        """A single-ontology run must not report the whole directory as what it wrote."""
        calls = []
        with (
            mock.patch.dict(DATA_SOURCES, {"ontologies": self._ontologies_fake(calls)}, clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
            mock.patch("builtins.print") as printed,
        ):
            transform(None, None, sources=["ec"])
        done = [str(c.args[0]) for c in printed.call_args_list if "done" in str(c.args[0])]
        self.assertEqual(len(done), 1)
        self.assertIn("ec_nodes.tsv: 1 rows", done[0])
        self.assertNotIn("chebi", done[0])

    def test_a_failed_single_ontology_skips_what_depends_on_ontologies(self):
        """A dependent declares `ontologies`, not `ec`; a failed `-s ec` must still keep it from running."""
        calls = []
        fake = self._ontologies_fake(calls)
        original_run = fake.run

        def failing_run(self_, data_file=None, show_status=True):
            original_run(self_, data_file, show_status)
            raise RuntimeError("robot died")

        fake.run = failing_run
        log = []
        registry = {"ontologies": fake, "gold": _fake_source("gold", log, self.base, inputs=("ontologies",))}
        with (
            mock.patch.dict(DATA_SOURCES, registry, clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=["ec", "gold"])
        self.assertEqual(log, [])
        self.assertEqual(excinfo.value.skipped, {"gold": ["ontologies"]})

    def test_an_unknown_name_lists_the_ontologies_too(self):
        """The error names both kinds of accepted source, so `-s EC` is an obvious typo."""
        with (
            mock.patch.dict(DATA_SOURCES, {"ontologies": self._ontologies_fake([])}, clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(ValueError) as excinfo:
                transform(None, None, sources=["EC"])
        self.assertIn("single ontologies: ec", str(excinfo.value))
