"""Tests for loud transform dispatch (#813) and declared data inputs (#812)."""

import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock

import pytest

from kg_microbe.transform import DATA_SOURCES, LazyTransform, TransformBatchError, transform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

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
        """Curated declarations must exist; declared raw downloads may be absent from an offline checkout."""
        for name, cls in DATA_SOURCES.items():
            for rel in getattr(cls, "DATA_INPUTS", ()):
                if Path(rel).parts[:2] == ("data", "raw"):
                    continue
                self.assertTrue(
                    (REPO_ROOT / rel).exists(),
                    f"{name} declares DATA_INPUTS {rel!r}, which does not exist",
                )

    def test_metatraits_gtdb_inherits_rather_than_redeclaring(self):
        """Subclasses must not need their own copy — a second list is a second thing to forget."""
        inherited = DATA_SOURCES["metatraits"].DATA_INPUTS
        combined = DATA_SOURCES["metatraits_gtdb"].DATA_INPUTS
        self.assertEqual(combined[: len(inherited)], inherited)
        self.assertEqual(combined[len(inherited) :], ("data/raw/taxdump.tar.gz",))

    def test_every_sssom_consumer_declares_it(self):
        """
        Guard against the next consumer forgetting.

        Consumers must declare either the repository unified SSSOM or their
        explicitly selected generated SSSOM as a required consumed input.
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
            selected = getattr(cls, "SSSOM_CONSUMED_INPUT", None)
            if selected:
                self.assertIn(selected, getattr(cls, "REQUIRED_CONSUMED_INPUTS", ()))
                continue
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
        """Do not invent data staleness, but timestamps cannot prove a completed build."""
        with (
            mock.patch.object(self.mod, "_latest_commit", return_value=(1000, "deadbee")),
            mock.patch.object(self.mod, "_has_local_diff", return_value=False),
            mock.patch.object(self.mod, "_output_mtime", return_value=2000),
            mock.patch.object(self.mod, "_latest_data_input_commit", return_value=(None, None)),
        ):
            report = self.mod.check_source("bactotraits", "origin/master")
        self.assertEqual(report.status, "UNVERIFIED_BUILD")

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
        """Provide a configurable transform for dispatch tests."""

        DATA_INPUTS = ()
        TRANSFORM_INPUTS = inputs

        def __init__(self, input_dir, output_dir):
            """Create isolated output for this fake source."""
            self.output_dir = base / name
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def run(self, show_status=True):
            """Record dispatch and optionally simulate a source failure."""
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
            """Represent a nonrecoverable ontology infrastructure failure."""

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

    def _optional_without_input(self, name, **kwargs):
        """Build a fake optional source that reports it has nothing to transform."""
        fake = _fake_source(name, self.log, self.base, **kwargs)
        fake.missing_optional_input = classmethod(lambda cls, input_dir=None: "data/raw/opt does not exist")
        return fake

    def test_an_optional_source_without_input_is_skipped_in_the_default_batch(self):
        """Bakta without data used to fail finalization and turn a clean full run into exit 1."""
        registry = {
            "a": _fake_source("a", self.log, self.base),
            "opt": self._optional_without_input("opt"),
            "b": _fake_source("b", self.log, self.base),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["a", "b"])

    def test_a_dependent_of_a_skipped_optional_source_does_not_run(self):
        """Nothing may be built on an optional source's absent (or stale) output."""
        registry = {
            "opt": self._optional_without_input("opt"),
            "uses_opt": _fake_source("uses_opt", self.log, self.base, inputs=("opt",)),
            "b": _fake_source("b", self.log, self.base),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["b"])

    def test_a_skipped_optional_dependency_is_not_reported_as_a_failure(self):
        """
        `skipped` means an upstream failed; an optional skip must not borrow that wording.

        With another source failing, the summary used to say the dependent's
        upstream "did not complete" although nothing it needed had failed.
        """
        registry = {
            "opt": self._optional_without_input("opt"),
            "uses_opt": _fake_source("uses_opt", self.log, self.base, inputs=("opt",)),
            "bad": _fake_source("bad", self.log, self.base, raises=RuntimeError("boom")),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True), mock.patch("builtins.print") as printed:
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=None)
        self.assertEqual(list(excinfo.value.failed), ["bad"])
        self.assertEqual(excinfo.value.skipped, {})
        lines = [" ".join(map(str, call.args)) for call in printed.call_args_list]
        self.assertIn("[transform] uses_opt: skipped — needs opt; optional opt has no input", lines)

    def _marker(self, out, source):
        """Plant an earlier run's success marker for ``source`` under ``out``."""
        from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

        marker = out / source / FINGERPRINT_FILE
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        return marker

    def test_an_explicit_request_without_input_withdraws_the_earlier_marker(self):
        """
        `-s bakta` used to leave the old marker while failing preflight.

        On master the run removed it before failing, so `merge_bakta.yaml`
        refused the stale output; the preflight failure must keep that.
        """
        out = self.base / "out"
        marker = self._marker(out, "opt")
        with mock.patch.dict(DATA_SOURCES, {"opt": self._optional_without_input("opt")}, clear=True):
            with pytest.raises(FileNotFoundError):
                transform(None, out, sources=["opt"])
        self.assertFalse(marker.exists())

    def test_an_unreadable_optional_input_runs_the_source_in_isolation(self):
        """An input check that cannot list the raw directory must not stop the whole batch at preflight."""

        def unreadable(cls, input_dir=None):
            """Fail the way an unreadable data/raw/bakta does."""
            raise PermissionError("data/raw/bakta")

        fake = _fake_source("opt", self.log, self.base)
        fake.missing_optional_input = classmethod(unreadable)
        registry = {"opt": fake, "b": _fake_source("b", self.log, self.base)}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["opt", "b"])

    def test_a_marker_that_cannot_be_withdrawn_fails_only_that_source(self):
        """An unwritable output directory used to abort the batch with a bare traceback."""
        registry = {"opt": self._optional_without_input("opt"), "b": _fake_source("b", self.log, self.base)}
        with (
            mock.patch.dict(DATA_SOURCES, registry, clear=True),
            mock.patch("kg_microbe.transform._withdraw_success_claim", side_effect=PermissionError("read-only")),
        ):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=None)
        self.assertEqual(list(excinfo.value.failed), ["opt"])
        self.assertEqual(self.log, ["b"])

    def test_a_dependent_listed_before_its_optional_upstream_is_skipped_and_not_held_to_its_inputs(self):
        """The skip set is computed before preflight, so registry order and DATA_INPUTS cannot defeat it."""
        dep = _fake_source("dep", self.log, self.base, inputs=("opt",))
        dep.DATA_INPUTS = ("mappings/this-file-does-not-exist.tsv",)
        registry = {"dep": dep, "opt": self._optional_without_input("opt"), "b": _fake_source("b", self.log, self.base)}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["b"])

    def test_a_chain_names_the_optional_root(self):
        """dep2 is skipped because opt has no input; dep1 is neither optional nor missing input."""
        registry = {
            "opt": self._optional_without_input("opt"),
            "dep1": _fake_source("dep1", self.log, self.base, inputs=("opt",)),
            "dep2": _fake_source("dep2", self.log, self.base, inputs=("dep1",)),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True), mock.patch("builtins.print") as printed:
            transform(None, None, sources=None)
        lines = [" ".join(map(str, call.args)) for call in printed.call_args_list]
        self.assertIn("[transform] dep2: skipped — needs dep1; optional opt has no input", lines)
        self.assertEqual(self.log, [])

    def test_mixed_upstreams_report_only_the_real_failure(self):
        """A dependent of both an optional skip and a failure is not built, and only the failure is reported."""
        registry = {
            "opt": self._optional_without_input("opt"),
            "bad": _fake_source("bad", self.log, self.base, raises=RuntimeError("boom")),
            "dep": _fake_source("dep", self.log, self.base, inputs=("opt", "bad")),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=None)
        self.assertEqual(list(excinfo.value.failed), ["bad"])
        self.assertEqual(excinfo.value.skipped, {})
        self.assertNotIn("dep", self.log)

    def test_dependents_markers_are_withdrawn_too(self):
        """A dependent skipped for want of its optional upstream has no current output either."""
        out = self.base / "out"
        markers = [self._marker(out, "opt"), self._marker(out, "dep")]
        registry = {
            "opt": self._optional_without_input("opt"),
            "dep": _fake_source("dep", self.log, self.base, inputs=("opt",)),
        }
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, out, sources=None)
        self.assertEqual([m.exists() for m in markers], [False, False])

    def test_the_default_output_directory_is_used_without_an_explicit_one(self):
        """With no output directory given, the marker is found where the transform writes by default."""
        fake = self._optional_without_input("opt")
        fake.DEFAULT_OUTPUT_DIR = self.base / "defaults"
        marker = self._marker(fake.DEFAULT_OUTPUT_DIR, "opt")
        with mock.patch.dict(DATA_SOURCES, {"opt": fake}, clear=True):
            transform(None, None, sources=None)
        self.assertFalse(marker.exists())

    def test_a_skip_withdraws_an_earlier_success_marker(self):
        """
        A run removes the marker before producing; a skip must too.

        Otherwise Bakta output built from raw data that has since gone keeps a
        current fingerprint, and `merge_bakta.yaml` admits it without a word.
        """
        from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

        out = self.base / "out"
        marker = out / "opt" / FINGERPRINT_FILE
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        with mock.patch.dict(DATA_SOURCES, {"opt": self._optional_without_input("opt")}, clear=True):
            transform(None, out, sources=None)
        self.assertFalse(marker.exists())

    def test_a_skipped_optional_source_is_not_held_to_its_declared_inputs(self):
        """It reads nothing this run, so a missing declaration must not stop the whole batch."""
        fake = self._optional_without_input("opt")
        fake.DATA_INPUTS = ("mappings/this-file-does-not-exist.tsv",)
        registry = {"opt": fake, "b": _fake_source("b", self.log, self.base)}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["b"])

    def test_the_registered_bakta_is_skipped_without_input(self):
        """Drive the real LazyTransform -> BaktaTransform.missing_optional_input path, not a fake."""
        raw = self.base / "raw"
        raw.mkdir()
        ran = []
        with (
            mock.patch.dict(DATA_SOURCES, {"bakta": DATA_SOURCES["bakta"]}, clear=True),
            mock.patch("kg_microbe.transform._run_one", lambda source, *args: ran.append(source)),
        ):
            transform(raw, self.base / "out", sources=None)
        self.assertEqual(ran, [])
        self.assertFalse((self.base / "out" / "bakta").exists(), "a skip must not create the output directory")

    def test_an_explicitly_requested_optional_source_without_input_fails_before_anything_runs(self):
        """`-s bakta` with no data asked for output that cannot be created: fail early and say why."""
        registry = {"early": _fake_source("early", self.log, self.base), "opt": self._optional_without_input("opt")}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(FileNotFoundError) as excinfo:
                transform(None, None, sources=["early", "opt"])
        self.assertEqual(self.log, [])
        self.assertIn("opt: data/raw/opt does not exist", str(excinfo.value))

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

    def test_a_missing_prerequisite_tool_fails_before_anything_runs(self):
        """ROBOT absent used to fail ontologies_stubs after hours of ontologies work."""
        fake = _fake_source("a", self.log, self.base)
        fake.missing_prerequisites = classmethod(lambda cls, input_dir=None: ["ROBOT binary not on PATH"])
        registry = {"early": _fake_source("early", self.log, self.base), "a": fake}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(FileNotFoundError) as excinfo:
                transform(None, None, sources=["early", "a"])
        self.assertEqual(self.log, [])
        self.assertIn("a: ROBOT binary not on PATH", str(excinfo.value))

    def test_a_skipped_optional_source_is_not_held_to_its_prerequisites(self):
        """It runs nothing, so a tool it would need must not stop the whole default batch."""
        fake = self._optional_without_input("opt")
        fake.missing_prerequisites = classmethod(lambda cls, input_dir=None: ["needs a tool"])
        registry = {"opt": fake, "b": _fake_source("b", self.log, self.base)}
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            transform(None, None, sources=None)
        self.assertEqual(self.log, ["b"])

    def test_the_prerequisite_hook_checks_the_cli_input_directory(self):
        """`-i` moves the raw directory, and with it the pinned ROBOT the hook must look for."""
        seen = []
        fake = _fake_source("a", self.log, self.base)
        fake.missing_prerequisites = classmethod(lambda cls, input_dir=None: seen.append(input_dir) or [])
        raw = self.base / "alternate-raw"
        with mock.patch.dict(DATA_SOURCES, {"a": fake}, clear=True):
            transform(raw, None, sources=["a"])
        self.assertEqual(seen, [raw])

    def test_prerequisite_messages_may_come_as_any_iterable_but_not_a_string(self):
        """A tuple must count; a bare string would be reported one character at a time."""
        from kg_microbe.transform import _missing_prerequisites

        fake = _fake_source("a", self.log, self.base)
        fake.missing_prerequisites = classmethod(lambda cls, input_dir=None: ("needs a tool",))
        with mock.patch.dict(DATA_SOURCES, {"a": fake}, clear=True):
            self.assertEqual(_missing_prerequisites(["a"]), ["a: needs a tool"])
            fake.missing_prerequisites = classmethod(lambda cls, input_dir=None: "needs a tool")
            with pytest.raises(TypeError):
                _missing_prerequisites(["a"])

    def _upstream_and_dependent(self):
        """Register a source and one that declares it in TRANSFORM_INPUTS."""
        return {
            "up": _fake_source("up", self.log, self.base),
            "dep": _fake_source("dep", self.log, self.base, inputs=("up",)),
        }

    def test_a_declared_upstream_with_no_completed_output_fails_before_anything_runs(self):
        """Without it the source would build on nothing and claim success (#1511)."""
        with mock.patch.dict(DATA_SOURCES, self._upstream_and_dependent(), clear=True):
            with pytest.raises(FileNotFoundError) as excinfo:
                transform(None, self.base / "out", sources=["dep"])
        self.assertEqual(self.log, [])
        self.assertIn("dep: needs a completed up output", str(excinfo.value))
        self.assertIn("kg transform -s up", str(excinfo.value))

    def test_the_upstream_check_looks_beside_the_dependents_own_output(self):
        """With no -o, finalization and the merge read the upstream beside the dependent's output."""
        registry = self._upstream_and_dependent()
        registry["dep"].DEFAULT_OUTPUT_DIR = self.base / "default"
        with mock.patch.dict(DATA_SOURCES, registry, clear=True):
            with pytest.raises(FileNotFoundError, match="default/up/source_fingerprint.json"):
                transform(None, None, sources=["dep"])
        self.assertEqual(self.log, [])

    def test_a_completed_upstream_lets_its_dependent_run_alone(self):
        """The completion marker is the evidence the check asks for, as freshness and the merge do."""
        marker = self.base / "up" / FINGERPRINT_FILE
        marker.parent.mkdir(parents=True)
        marker.write_text("{}")
        with mock.patch.dict(DATA_SOURCES, self._upstream_and_dependent(), clear=True):
            transform(None, self.base, sources=["dep"])
        self.assertEqual(self.log, ["dep"])

    def test_explicit_selections_run_upstream_first_whatever_order_they_were_named_in(self):
        """`-s dep -s up` must not build dep against up's previous output (#1554)."""
        with mock.patch.dict(DATA_SOURCES, self._upstream_and_dependent(), clear=True):
            transform(None, self.base, sources=["dep", "up"])
        self.assertEqual(self.log, ["up", "dep"])

    def test_an_upstream_built_in_the_same_run_needs_no_earlier_output(self):
        """Selected together, the upstream runs first and its new marker is what the dependent finds."""
        with mock.patch.dict(DATA_SOURCES, self._upstream_and_dependent(), clear=True):
            transform(None, self.base, sources=["up", "dep"])
        self.assertEqual(self.log, ["up", "dep"])

    def test_an_upstream_that_finishes_without_its_marker_stops_the_dependent_before_it_runs(self):
        """The marker is written best-effort; without it the dependent fails now, not after its producer."""
        import kg_microbe.transform as dispatcher

        record = dispatcher._record_fingerprint

        def record_all_but_up(transform_obj, source):
            """Fail to record only the upstream's marker, as a full disk would."""
            if source != "up":
                record(transform_obj, source)

        with mock.patch.dict(DATA_SOURCES, self._upstream_and_dependent(), clear=True):
            with mock.patch.object(dispatcher, "_record_fingerprint", record_all_but_up):
                with pytest.raises(TransformBatchError) as excinfo:
                    transform(None, self.base, sources=["up", "dep"])
        self.assertEqual(self.log, ["up"])
        self.assertIn("dep: needs a completed up output", str(excinfo.value))

    def _ontologies_and_dependent(self):
        """Register an ontologies stand-in that can also run one ontology, and a source that declares it."""
        log, base = self.log, self.base

        class FakeOntologies:
            """Record whole and single-ontology runs into its own output directory."""

            DATA_INPUTS = ()
            TRANSFORM_INPUTS = ()

            def __init__(self, input_dir, output_dir):
                """Create isolated output for the stand-in."""
                self.output_dir = base / "ontologies"
                self.output_dir.mkdir(parents=True, exist_ok=True)

            def run(self, data_file=None, show_status=True):
                """Record which run this was."""
                log.append("ontologies" if data_file is None else "single ontology")

        return {"ontologies": FakeOntologies, "dep": _fake_source("dep", log, base, inputs=("ontologies",))}

    def test_a_single_ontology_with_a_dependent_and_no_full_rebuild_is_refused_before_it_runs(self):
        """`-s ec -s dep` would remove the marker dep needs, then build dep on part of it (#1564)."""
        marker = self.base / "ontologies" / FINGERPRINT_FILE
        marker.parent.mkdir(parents=True)
        marker.write_text("{}")
        with mock.patch.dict(DATA_SOURCES, self._ontologies_and_dependent(), clear=True):
            with pytest.raises(FileNotFoundError, match="dep: .*single ontology selected in this run"):
                transform(None, self.base, sources=["dep", "ec"])
        self.assertEqual(self.log, [])
        self.assertTrue(marker.is_file(), "a refused run must not remove the marker")

    def test_a_single_ontology_runs_before_the_ontologies_rebuild_that_its_dependents_read(self):
        """With ontologies selected too, the single ontology goes first and the rebuild restores the marker."""
        with mock.patch.dict(DATA_SOURCES, self._ontologies_and_dependent(), clear=True):
            transform(None, self.base, sources=["dep", "ontologies", "ec"])
        self.assertEqual(self.log, ["single ontology", "ontologies", "dep"])

    def test_alternate_raw_declaration_does_not_require_repository_default(self):
        """CLI -i determines the raw authority preflight path, not an unrelated repo file."""
        from kg_microbe.transform import _missing_declared_inputs

        raw_dir = self.base / "alternate-raw"
        raw_dir.mkdir()
        (raw_dir / "taxdump.tar.gz").write_bytes(b"explicit alternate authority")
        fake = _fake_source("a", self.log, self.base)
        fake.DATA_INPUTS = ("data/raw/taxdump.tar.gz",)
        fake_repo = self.base / "repo-with-no-default-raw"
        with mock.patch.dict(DATA_SOURCES, {"a": fake}, clear=True):
            self.assertEqual(_missing_declared_inputs(["a"], fake_repo, raw_dir), [])
            self.assertEqual(_missing_declared_inputs(["a"], fake_repo), ["a: data/raw/taxdump.tar.gz"])

    def test_dispatch_and_recording_use_effective_raw_directory(self):
        """An alternate-only declared file passes preflight and the marker records its consumed bytes."""
        from kg_microbe.utils.transform_fingerprint import data_fingerprint, read_fingerprint

        raw_dir = self.base / "alternate-raw"
        raw_dir.mkdir()
        filename = "offline-test-alternate-authority.tsv"
        (raw_dir / filename).write_text("explicit alternate authority")

        class Alternate(_fake_source("a", self.log, self.base)):
            """A source whose declared raw authority exists only under the supplied input root."""

            DATA_INPUTS = (f"data/raw/{filename}",)

            def __init__(self, input_dir, output_dir):
                """Remember the same effective input directory a real Transform consumes."""
                super().__init__(input_dir, output_dir)
                self.input_base_dir = input_dir

        with mock.patch.dict(DATA_SOURCES, {"a": Alternate}, clear=True):
            transform(raw_dir, self.base, sources=["a"])
        self.assertEqual(self.log, ["a"])
        marker = read_fingerprint(self.base / "a")
        self.assertEqual(marker["data"], data_fingerprint(REPO_ROOT, Alternate.DATA_INPUTS, input_dir=raw_dir))
        self.assertNotEqual(marker["data"], data_fingerprint(REPO_ROOT, Alternate.DATA_INPUTS))


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
            """Provide ontology outputs without invoking external tooling."""

            DATA_INPUTS = ()
            TRANSFORM_INPUTS = ()

            def __init__(self, input_dir, output_dir):
                """Create isolated ontology output for this test."""
                self.output_dir = base / "ontologies"
                self.output_dir.mkdir(parents=True, exist_ok=True)

            def run(self, data_file=None, show_status=True):
                """Write fixture outputs and record the requested ontology."""
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

    def _single_ontology_registry(self, calls, log, fail_whole):
        """Register a stand-in whose single-ontology run fails, and gold, which declares ontologies."""
        fake = self._ontologies_fake(calls)
        original_run = fake.run

        def failing_run(self_, data_file=None, show_status=True):
            """Fail after writing outputs, for a single ontology and optionally for the whole run."""
            original_run(self_, data_file, show_status)
            if data_file is not None or fail_whole:
                raise RuntimeError("robot died")

        fake.run = failing_run
        return {"ontologies": fake, "gold": _fake_source("gold", log, self.base, inputs=("ontologies",))}

    def test_a_single_ontology_with_a_dependent_is_refused_before_anything_runs(self):
        """`-s ec -s gold` would build gold on one refreshed ontology and no marker (#1564)."""
        calls, log = [], []
        with (
            mock.patch.dict(DATA_SOURCES, self._single_ontology_registry(calls, log, False), clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(FileNotFoundError, match="gold: .*single ontology selected in this run"):
                transform(None, None, sources=["ec", "gold"])
        self.assertEqual((calls, log), ([], []))

    def test_a_failed_single_ontology_skips_what_depends_on_ontologies(self):
        """A dependent declares `ontologies`, not `ec`; with both failing it must not run."""
        calls, log = [], []
        with (
            mock.patch.dict(DATA_SOURCES, self._single_ontology_registry(calls, log, True), clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=["gold", "ontologies", "ec"])
        self.assertEqual(calls, ["ec.json", None])
        self.assertEqual(log, [])
        self.assertEqual(excinfo.value.skipped, {"gold": ["ontologies"]})

    def test_an_ontologies_rebuild_after_a_failed_single_ontology_lets_dependents_run(self):
        """The rebuild that follows in the same run restores what the single ontology took away."""
        calls, log = [], []
        with (
            mock.patch.dict(DATA_SOURCES, self._single_ontology_registry(calls, log, False), clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(TransformBatchError) as excinfo:
                transform(None, None, sources=["gold", "ontologies", "ec"])
        self.assertEqual(calls, ["ec.json", None])
        self.assertEqual(log, ["gold"])
        self.assertEqual(set(excinfo.value.failed), {"ec"})

    def test_an_unknown_name_lists_the_ontologies_too(self):
        """The error names both kinds of accepted source, so `-s EC` is an obvious typo."""
        with (
            mock.patch.dict(DATA_SOURCES, {"ontologies": self._ontologies_fake([])}, clear=True),
            mock.patch("kg_microbe.transform._ontology_map", return_value={"ec": "ec.json"}),
        ):
            with pytest.raises(ValueError) as excinfo:
                transform(None, None, sources=["EC"])
        self.assertIn("single ontologies: ec", str(excinfo.value))
