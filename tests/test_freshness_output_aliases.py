"""Tests that the freshness check follows a source's real output directory."""

import importlib.util
import sys
import time
from pathlib import Path
from unittest import TestCase

_SPEC = importlib.util.spec_from_file_location(
    "kgm_freshness_check",
    Path(__file__).parent.parent / ".claude" / "skills" / "kgm-freshness-check" / "kgm_freshness_check.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["kgm_freshness_check"] = _MODULE
_SPEC.loader.exec_module(_MODULE)


class FreshnessOutputAliasTest(TestCase):
    """PREGO writes prego_habitat/ by default, prego/ only under PREGO_SHAPES=all."""

    def setUp(self):
        """Point the module at a scratch data/transformed tree."""
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self._orig = _MODULE.TRANSFORMED_DIR
        _MODULE.TRANSFORMED_DIR = self.tmp

    def tearDown(self):
        """Restore the module-level path."""
        _MODULE.TRANSFORMED_DIR = self._orig

    def _write(self, name, age_seconds):
        """Create a transform output dir with a controlled mtime."""
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        f = d / "edges.tsv"
        f.write_text("subject\tpredicate\tobject\n")
        stamp = time.time() - age_seconds
        import os

        os.utime(f, (stamp, stamp))
        return f

    def test_a_fresh_variant_dir_clears_the_source(self):
        """
        The default output must be able to clear the flag.

        Watching only `prego/` left the source permanently STALE_VS_CODE after
        #766 made `habitat` the default: no default invocation writes that
        directory, so re-running the transform changed nothing in the report.
        """
        self._write("prego", age_seconds=86400)
        newest = self._write("prego_habitat", age_seconds=10)

        mtime = _MODULE._output_mtime("prego")
        self.assertAlmostEqual(mtime, newest.stat().st_mtime, places=3)

    def test_the_legacy_dir_alone_still_counts(self):
        """`PREGO_SHAPES=all` writes prego/, which must not become invisible."""
        only = self._write("prego", age_seconds=10)
        self.assertAlmostEqual(_MODULE._output_mtime("prego"), only.stat().st_mtime, places=3)

    def test_a_source_with_no_alias_is_unchanged(self):
        """The aliasing must not disturb the ordinary one-dir case."""
        f = self._write("bacdive", age_seconds=10)
        self.assertAlmostEqual(_MODULE._output_mtime("bacdive"), f.stat().st_mtime, places=3)

    def test_missing_output_is_still_missing(self):
        """A source with neither directory present must report nothing."""
        self.assertIsNone(_MODULE._output_mtime("prego"))
        self.assertIsNone(_MODULE._output_mtime("bacdive"))

    def test_the_dir_the_merge_reads_wins_over_the_newest(self):
        """
        A pre-flight must measure what will be merged, not whatever is newest.

        The first fix took the newest across aliases, which inverted the bug: a
        fresh `prego/` from `PREGO_SHAPES=all` beside a stale `prego_habitat/`
        reported FRESH while the standard merge consumed the stale build.
        """
        self._write("prego", age_seconds=10)
        stale = self._write("prego_habitat", age_seconds=999999)

        # merge.yaml in the real repo references prego_habitat/, so that must win
        # despite prego/ being far newer.
        self.assertEqual([d.name for d in _MODULE._output_dirs("prego")], ["prego_habitat"])
        self.assertAlmostEqual(_MODULE._output_mtime("prego"), stale.stat().st_mtime, places=3)

    def test_the_merge_config_is_actually_parsed(self):
        """A silently empty reference set would make the preference a no-op."""
        referenced = _MODULE._dirs_referenced_by_merge_config()
        self.assertIn("prego_habitat", referenced)
        self.assertIn("bacdive", referenced)
        self.assertNotIn("prego", referenced, "merge.yaml takes habitat-only PREGO since #766")
