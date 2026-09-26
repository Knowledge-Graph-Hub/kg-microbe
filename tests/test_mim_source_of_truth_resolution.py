"""
The consolidator must not regenerate artifacts from stale input (#947).

A run whose MediaIngredientMech checkout is unreachable used to print one
warning and exit 0, rewriting ~610k rows from a vendored copy that was three
weeks behind. Every downstream validation still passed, because the output is
internally consistent with whichever input it was given -- so nothing else in
the pipeline can catch this. These tests pin the contract at the only point
where it is observable.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("consolidate_chemical_mappings", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


ccm = _load_module()


class MimRootResolutionTests(unittest.TestCase):
    """``MEDIAINGREDIENTMECH_ROOT`` wins; the sibling is only the default."""

    def test_env_override_wins(self):
        """The env var is honoured verbatim, ignoring repo adjacency."""
        with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: "/somewhere/else/MIM"}):
            self.assertEqual(ccm._mim_root(Path("/repo")), Path("/somewhere/else/MIM"))

    def test_sibling_is_the_default(self):
        """With no override, MIM is expected beside the kg-microbe checkout."""
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                ccm._mim_root(Path("/repo")).resolve(),
                (Path("/repo") / ".." / "MediaIngredientMech").resolve(),
            )


class StaleVendoredFallbackTests(unittest.TestCase):
    """An unreachable source of truth is a failure, not a warning."""

    def _vendored(self, tmp: Path) -> Path:
        vendored = tmp / "mappings" / "ingredient_mappings.sssom.tsv"
        vendored.parent.mkdir(parents=True, exist_ok=True)
        vendored.write_text("subject_id\tobject_id\n", encoding="utf-8")
        return vendored

    def test_missing_source_raises_by_default(self):
        """An unreachable source of truth fails the run rather than warning."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._vendored(tmp)
            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "absent")}):
                with self.assertRaises(FileNotFoundError) as ctx:
                    ccm.sync_mim_sssom(tmp)
        # The message has to tell the operator how to fix it, or the failure
        # just relocates the confusion.
        self.assertIn(ccm._MIM_ROOT_ENV, str(ctx.exception))
        self.assertIn("--allow-stale-vendored", str(ctx.exception))

    def test_opt_in_allows_the_stale_copy(self):
        """--allow-stale-vendored is the only way to proceed on stale data."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            vendored = self._vendored(tmp)
            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "absent")}):
                got = ccm.sync_mim_sssom(tmp, allow_stale_vendored=True)
        self.assertEqual(got, vendored.resolve())

    def test_reviewed_ingredients_follows_the_same_contract(self):
        """Both synced artifacts fail closed, not just the SSSOM."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            vendored = tmp / "mappings" / "culturebotai_reviewed_ingredients.tsv"
            vendored.parent.mkdir(parents=True, exist_ok=True)
            vendored.write_text("name\tmapped\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "absent")}):
                with self.assertRaises(FileNotFoundError):
                    ccm.sync_culturebotai_reviewed(tmp)


class CliTests(unittest.TestCase):
    """The safe default has to survive contact with the command line."""

    def test_flag_defaults_off(self):
        """Failing closed is the default; nobody has to remember a flag."""
        self.assertFalse(ccm._parse_args([]).allow_stale_vendored)

    def test_flag_parses(self):
        """The opt-in flag is reachable from the command line."""
        self.assertTrue(ccm._parse_args(["--allow-stale-vendored"]).allow_stale_vendored)


class DryRunTests(unittest.TestCase):
    """--dry-run must preview without touching a single tracked byte."""

    def test_flag_defaults_off(self):
        """Writing is the default; the preview is opt-in."""
        self.assertFalse(ccm._parse_args([]).dry_run)

    def test_flag_parses(self):
        """The preview flag is reachable from the command line."""
        self.assertTrue(ccm._parse_args(["--dry-run"]).dry_run)

    def test_sync_does_not_copy_under_dry_run(self):
        """A diverging source of truth is reported, not copied over."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mim = tmp / "mim" / "mappings"
            mim.mkdir(parents=True)
            (mim / "ingredient_mappings.sssom.tsv").write_text("fresh\n", encoding="utf-8")

            vendored = tmp / "mappings" / "ingredient_mappings.sssom.tsv"
            vendored.parent.mkdir(parents=True)
            vendored.write_text("stale\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "mim")}):
                ccm.sync_mim_sssom(tmp, dry_run=True)

            # The whole point: the stale copy is still stale afterwards.
            self.assertEqual(vendored.read_text(encoding="utf-8"), "stale\n")

    def test_dry_run_returns_the_source_not_the_stale_vendored_copy(self):
        """
        The preview must read what the apply would install, not the old copy.

        Returning the vendored path under --dry-run made callers load
        pre-refresh content, so the preview reported the delta of doing nothing
        -- wrong in exactly the case a preview exists for (#951).
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mim = tmp / "mim" / "mappings"
            mim.mkdir(parents=True)
            source = mim / "ingredient_mappings.sssom.tsv"
            source.write_text("fresh\n", encoding="utf-8")

            vendored = tmp / "mappings" / "ingredient_mappings.sssom.tsv"
            vendored.parent.mkdir(parents=True)
            vendored.write_text("stale\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "mim")}):
                got = ccm.sync_mim_sssom(tmp, dry_run=True)

            self.assertEqual(got.resolve(), source.resolve())
            self.assertEqual(got.read_text(encoding="utf-8"), "fresh\n")
            # ...and still nothing written.
            self.assertEqual(vendored.read_text(encoding="utf-8"), "stale\n")

    def test_real_run_returns_the_vendored_copy(self):
        """A real run installs the content first, so the vendored path is right."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mim = tmp / "mim" / "mappings"
            mim.mkdir(parents=True)
            (mim / "ingredient_mappings.sssom.tsv").write_text("fresh\n", encoding="utf-8")

            vendored = tmp / "mappings" / "ingredient_mappings.sssom.tsv"
            vendored.parent.mkdir(parents=True)
            vendored.write_text("stale\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "mim")}):
                got = ccm.sync_mim_sssom(tmp)

            self.assertEqual(got.resolve(), vendored.resolve())
            self.assertEqual(got.read_text(encoding="utf-8"), "fresh\n")

    def test_sync_copies_when_not_dry_run(self):
        """The same divergence is actually synced on a real run."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mim = tmp / "mim" / "mappings"
            mim.mkdir(parents=True)
            (mim / "ingredient_mappings.sssom.tsv").write_text("fresh\n", encoding="utf-8")

            vendored = tmp / "mappings" / "ingredient_mappings.sssom.tsv"
            vendored.parent.mkdir(parents=True)
            vendored.write_text("stale\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "mim")}):
                ccm.sync_mim_sssom(tmp)

            self.assertEqual(vendored.read_text(encoding="utf-8"), "fresh\n")


class ExportDeltaTests(unittest.TestCase):
    """The preview has to report the shape of a change, not just its size."""

    @staticmethod
    def _write(path: Path, triples) -> None:
        header = "subject_id\tpredicate_id\tobject_id\n"
        body = "".join(f"{s}\t{p}\t{o}\n" for s, p, o in triples)
        path.write_text("# comment\n" + header + body, encoding="utf-8")

    def test_triples_skips_comments_and_header(self):
        """SSSOM metadata blocks must not be mistaken for mappings."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.tsv"
            self._write(f, [("A:1", "skos:exactMatch", "B:1")])
            self.assertEqual(ccm._sssom_triples(f), {("A:1", "skos:exactMatch", "B:1")})

    def test_delta_separates_added_from_removed(self):
        """A net count hides removals; +2091/-279 nets to +1812."""
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as td:
            published = Path(td) / "published.tsv"
            candidate = Path(td) / "candidate.tsv"
            self._write(published, [("A:1", "p", "B:1"), ("A:2", "p", "B:2")])
            self._write(candidate, [("A:1", "p", "B:1"), ("A:3", "p", "B:3")])
            buf = io.StringIO()
            with redirect_stdout(buf):
                ccm._report_export_delta(candidate, published)
        out = buf.getvalue()
        self.assertIn("added     1", out)
        self.assertIn("removed   1", out)
        self.assertIn("Nothing was written", out)

    def test_missing_published_artifact_is_reported(self):
        """A first run has nothing to diff against and must say so."""
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.tsv"
            self._write(candidate, [("A:1", "p", "B:1")])
            buf = io.StringIO()
            with redirect_stdout(buf):
                ccm._report_export_delta(candidate, Path(td) / "absent.tsv")
        self.assertIn("would create it", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
