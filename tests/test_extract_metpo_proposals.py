"""
Regression tests for the METPO proposal extractor.

The CI gate enforces that committed proposal artifacts equal the extractor's
fresh output: re-running the script must not produce a diff against
mappings/metpo_proposal_*.tsv, mappings/metpo_existing_aliases.tsv, or
mappings/canonical/metpo_alias_mappings.tsv.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from difflib import unified_diff
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "extract_metpo_proposals.py"
COMMITTED_MAPPINGS = REPO_ROOT / "mappings"
COMMITTED_METATRAITS = REPO_ROOT / "mappings" / "canonical"
PROPOSAL_FILES = (
    "metpo_proposal_quantitative.tsv",
    "metpo_proposal_categorical.tsv",
    "metpo_existing_aliases.tsv",
    "metpo_label_corrections.tsv",
    "metpo_proposal_classes_robot.tsv",
    "metpo_proposal_properties_robot.tsv",
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("extract_metpo_proposals", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _diff(actual: Path, expected: Path) -> str:
    if not expected.exists():
        return f"committed {expected} is missing"
    a = actual.read_text().splitlines()
    b = expected.read_text().splitlines()
    diff = "\n".join(unified_diff(b, a, fromfile=str(expected), tofile=str(actual), lineterm=""))
    return diff


class TestProposalOutputsMatchCommitted(unittest.TestCase):

    """Re-run the extractor and assert it reproduces every committed artifact byte-for-byte."""

    def test_outputs_match_committed(self):
        """Run extract_metpo_proposals.main(tmp dirs) and diff every output."""
        if not (REPO_ROOT / "data" / "transformed" / "ontologies" / "metpo_nodes.tsv").exists():
            self.skipTest("METPO snapshot absent — run ontologies transform first")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mappings_out = tmp_path / "mappings"
            metatraits_out = tmp_path / "metatraits_mappings"

            cwd = Path.cwd()
            module = _load_script_module()
            try:
                # Script reads data/raw/bacdive_strains.json + data/transformed/ontologies
                # via repo-relative paths, so cwd must be the repo root.
                import os

                os.chdir(REPO_ROOT)
                module.main(output_dir=mappings_out, metatraits_dir=metatraits_out)
            finally:
                import os

                os.chdir(cwd)

            for name in PROPOSAL_FILES:
                actual = mappings_out / name
                expected = COMMITTED_MAPPINGS / name
                self.assertTrue(actual.exists(), f"extractor did not write {actual}")
                diff = _diff(actual, expected)
                self.assertEqual(diff, "", f"{name} drift:\n{diff}")

            actual_alias = metatraits_out / "metpo_alias_mappings.tsv"
            expected_alias = COMMITTED_METATRAITS / "metpo_alias_mappings.tsv"
            self.assertTrue(actual_alias.exists(), "extractor did not write metpo_alias_mappings.tsv")
            diff = _diff(actual_alias, expected_alias)
            self.assertEqual(diff, "", f"metpo_alias_mappings.tsv drift:\n{diff}")


if __name__ == "__main__":
    unittest.main()
