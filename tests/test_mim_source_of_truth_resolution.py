"""The consolidator must not regenerate artifacts from stale input (#947).

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
        with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: "/somewhere/else/MIM"}):
            self.assertEqual(ccm._mim_root(Path("/repo")), Path("/somewhere/else/MIM"))

    def test_sibling_is_the_default(self):
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
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            vendored = self._vendored(tmp)
            with mock.patch.dict("os.environ", {ccm._MIM_ROOT_ENV: str(tmp / "absent")}):
                got = ccm.sync_mim_sssom(tmp, allow_stale_vendored=True)
        self.assertEqual(got, vendored.resolve())

    def test_reviewed_ingredients_follows_the_same_contract(self):
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
    def test_flag_defaults_off(self):
        self.assertFalse(ccm._parse_args([]).allow_stale_vendored)

    def test_flag_parses(self):
        self.assertTrue(ccm._parse_args(["--allow-stale-vendored"]).allow_stale_vendored)


if __name__ == "__main__":
    unittest.main()
