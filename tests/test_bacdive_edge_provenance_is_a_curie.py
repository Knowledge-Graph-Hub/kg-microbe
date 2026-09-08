"""Every BacDive edge must name its knowledge source as a CURIE (#432)."""

import ast
import unittest
from pathlib import Path

BACDIVE = Path(__file__).resolve().parents[1] / "kg_microbe" / "transform_utils" / "bacdive" / "bacdive.py"


def _edge_row_literals(tree: ast.AST):
    """
    Yield the list literal of every ``edge_writer.writerow([...])`` call.

    :param tree: Parsed module.
    :return: Generator of ``ast.List`` nodes.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "writerow"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "edge_writer"):
            continue
        if node.args and isinstance(node.args[0], ast.List):
            yield node.args[0]


class BacdiveEdgeProvenanceTests(unittest.TestCase):
    """The transform has no fixture-driven end-to-end run, so guard the source."""

    def test_no_edge_row_carries_the_bare_source_name(self):
        """
        ``self.source_name`` is ``"bacdive"``; ``self.knowledge_source`` is ``infores:bacdive``.

        Two edge sites wrote the former into ``primary_knowledge_source`` and
        228,738 rebuilt edges (222,880 ``location_of``, 5,858 METPO quality
        edges) carried a value that is not a CURIE, while every other edge in
        the same file said ``infores:bacdive`` (#432).
        """
        tree = ast.parse(BACDIVE.read_text(encoding="utf-8"))
        offenders = []
        for row in _edge_row_literals(tree):
            for elt in row.elts:
                if isinstance(elt, ast.Attribute) and elt.attr == "source_name":
                    offenders.append(row.lineno)
        self.assertEqual(offenders, [], f"edge rows written with self.source_name at lines {offenders}")

    def test_the_guard_sees_the_edge_rows_it_guards(self):
        """A guard that matches nothing would pass on any file; pin that it finds rows."""
        tree = ast.parse(BACDIVE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(sum(1 for _ in _edge_row_literals(tree)), 2)


if __name__ == "__main__":
    unittest.main()
