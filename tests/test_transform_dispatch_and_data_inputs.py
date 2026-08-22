"""Tests for loud transform dispatch (#813) and declared data inputs (#812)."""

import importlib.util
import sys
from pathlib import Path
from unittest import TestCase, mock

import pytest

from kg_microbe.transform import DATA_SOURCES, LazyTransform, transform
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
    """The freshness check must report data staleness, not just code staleness."""

    def setUp(self):
        """Import the standalone freshness script."""
        spec = importlib.util.spec_from_file_location(
            "kgm_freshness_check",
            REPO_ROOT / ".claude" / "skills" / "kgm-freshness-check" / "kgm_freshness_check.py",
        )
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["kgm_freshness_check"] = self.mod
        spec.loader.exec_module(self.mod)

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
