"""The completion line must describe what a transform actually wrote (#813, #949)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from kg_microbe.transform import _describe_output


def _write(path: Path, rows: int) -> None:
    """
    Write a header plus ``rows`` data lines.

    :param path: File to write.
    :param rows: Number of data rows.
    :return: None.
    """
    path.write_text("a\tb\n" + "".join(f"{i}\tx\n" for i in range(rows)), encoding="utf-8")


class DescribeOutputTests(unittest.TestCase):
    """A run that produced nothing must be told apart from one that did."""

    def test_the_plain_pair_is_reported_by_name(self):
        """The common case keeps its familiar shape."""
        with TemporaryDirectory() as td:
            _write(Path(td) / "nodes.tsv", 3)
            _write(Path(td) / "edges.tsv", 5)
            line = _describe_output(SimpleNamespace(output_dir=Path(td)), "x")
        self.assertEqual(line, "nodes.tsv: 3 rows; edges.tsv: 5 rows")

    def test_per_ontology_files_are_counted_not_ignored(self):
        """
        The #949 inversion.

        The ontologies transform writes ``<ontology>_nodes.tsv`` per ontology.
        The literal-name check saw none of them and printed "wrote no
        nodes.tsv/edges.tsv" after a successful 415 MB run.
        """
        with TemporaryDirectory() as td:
            for name, rows in (("chebi_nodes.tsv", 10), ("ncbitaxon_nodes.tsv", 20), ("chebi_edges.tsv", 7)):
                _write(Path(td) / name, rows)
            line = _describe_output(SimpleNamespace(output_dir=Path(td)), "ontologies")
        self.assertEqual(line, "2 nodes files: 30 rows; chebi_edges.tsv: 7 rows")

    def test_nothing_written_still_says_so(self):
        """The guard the function exists for has to keep firing."""
        with TemporaryDirectory() as td:
            (Path(td) / "unrelated.txt").write_text("x", encoding="utf-8")
            line = _describe_output(SimpleNamespace(output_dir=Path(td)), "x")
        self.assertTrue(line.startswith("wrote no *nodes.tsv/*edges.tsv"))

    def test_a_header_only_file_counts_as_zero_rows(self):
        """Zero rows is the signal, not an absent file."""
        with TemporaryDirectory() as td:
            _write(Path(td) / "nodes.tsv", 0)
            line = _describe_output(SimpleNamespace(output_dir=Path(td)), "x")
        self.assertEqual(line, "nodes.tsv: 0 rows")


if __name__ == "__main__":
    unittest.main()
