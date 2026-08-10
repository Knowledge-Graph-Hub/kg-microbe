"""Tests for the MediaDive recipe-coverage guard."""

import importlib.util
import sys
from pathlib import Path
from unittest import TestCase

_SPEC = importlib.util.spec_from_file_location(
    "mediadive_coverage_check", Path(__file__).parent.parent / "scripts" / "mediadive_coverage_check.py"
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["mediadive_coverage_check"] = _MODULE
_SPEC.loader.exec_module(_MODULE)

HEADER = "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"


def _edges(tmp_path, rows):
    """
    Write a minimal mediadive edges.tsv.

    :param tmp_path: Directory to write into.
    :param rows: Iterable of (subject, predicate, object) triples.
    :return: Path to the written file.
    """
    path = Path(tmp_path) / "edges.tsv"
    with path.open("w") as handle:
        handle.write(HEADER)
        for subject, predicate, obj in rows:
            handle.write(f"{subject}\t{predicate}\t{obj}\tBFO:0000051\tinfores:mediadive\n")
    return path


class MediaDiveCoverageCheckTest(TestCase):

    """The counting rules the guard depends on."""

    def setUp(self):
        """Create a scratch directory."""
        import tempfile

        self.tmp = tempfile.mkdtemp()

    def test_the_curie_prefix_change_does_not_look_like_churn(self):
        """
        Solution CURIEs gained a `mediadive.` prefix between builds.

        Comparing raw subjects would report every solution as simultaneously
        removed and added, drowning the real signal in 5,000 false deltas.
        """
        old = _edges(self.tmp, [("solution:1", "biolink:has_part", "CHEBI:1")])
        new_dir = Path(self.tmp) / "new"
        new_dir.mkdir()
        new = _edges(new_dir, [("mediadive.solution:1", "biolink:has_part", "CHEBI:1")])

        self.assertEqual(_MODULE.ingredient_counts(old), {"solution:1": 1})
        self.assertEqual(_MODULE.ingredient_counts(new), {"solution:1": 1})

    def test_nested_solutions_are_not_counted_as_ingredients(self):
        """
        Nested references are structure, not composition.

        Counting them would let a solution that merely gained a nested reference
        mask the loss of real compounds — the exact failure being guarded against.
        """
        path = _edges(
            self.tmp,
            [
                ("solution:1", "biolink:has_part", "CHEBI:1"),
                ("solution:1", "biolink:has_part", "CHEBI:2"),
                ("solution:1", "biolink:has_part", "mediadive.solution:99"),
            ],
        )
        self.assertEqual(_MODULE.ingredient_counts(path), {"solution:1": 2})

    def test_non_has_part_edges_are_ignored(self):
        """Only composition counts; typing and subclass edges must not inflate it."""
        path = _edges(
            self.tmp,
            [
                ("solution:1", "biolink:has_part", "CHEBI:1"),
                ("solution:1", "biolink:subclass_of", "CHEBI:24431"),
                ("mediadive.medium:5", "biolink:has_part", "solution:1"),
            ],
        )
        self.assertEqual(_MODULE.ingredient_counts(path), {"solution:1": 1})

    def test_an_empty_comparison_is_refused_rather_than_reported(self):
        """
        Zero edges is never a real result and must not read as "no change".

        A layout or prefix change that matched nothing would otherwise report a
        clean bill of health on a file it could not parse.
        """
        path = _edges(self.tmp, [("mediadive.medium:5", "biolink:has_part", "solution:1")])
        with self.assertRaises(SystemExit):
            _MODULE.ingredient_counts(path)

    def test_a_missing_file_is_refused(self):
        """A path typo must not be indistinguishable from an empty source."""
        with self.assertRaises(SystemExit):
            _MODULE.ingredient_counts(Path(self.tmp) / "absent.tsv")
