"""Tests for the owl:deprecated term filter in the ontologies transform."""

import json
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform


def _make_obograph():
    """Build a tiny obograph with one active node, two deprecated nodes, and edges."""
    return {
        "graphs": [
            {
                "id": "https://w3id.org/metpo/test.json",
                "nodes": [
                    {"id": "https://w3id.org/metpo/1000001", "lbl": "active term", "type": "CLASS"},
                    {
                        "id": "https://w3id.org/metpo/0000001",
                        "lbl": "obsolete term (basicPropertyValues)",
                        "type": "CLASS",
                        "meta": {
                            "basicPropertyValues": [
                                {"pred": "http://www.w3.org/2002/07/owl#deprecated", "val": "true"}
                            ]
                        },
                    },
                    {
                        "id": "https://w3id.org/metpo/0000002",
                        "lbl": "obsolete term (meta.deprecated)",
                        "type": "CLASS",
                        "meta": {"deprecated": True},
                    },
                ],
                "edges": [
                    # edge between two active-ish nodes (subject active, object active) -> kept
                    {
                        "sub": "https://w3id.org/metpo/1000001",
                        "pred": "is_a",
                        "obj": "https://w3id.org/metpo/1000001",
                    },
                    # edge touching a deprecated node -> dropped
                    {
                        "sub": "https://w3id.org/metpo/1000001",
                        "pred": "is_a",
                        "obj": "https://w3id.org/metpo/0000001",
                    },
                ],
            }
        ]
    }


class TestDeprecatedFilter(TestCase):

    """Test owl:deprecated term removal from obograph JSON before KGX load."""

    def setUp(self):
        """Instantiate the transform without running __init__ side effects."""
        # The filter methods only rely on self._is_deprecated_node; bypass the
        # base Transform.__init__ (which sets up source dirs) to keep the test
        # isolated and side-effect free.
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def test_is_deprecated_node_detects_both_encodings(self):
        """Both basicPropertyValues and meta.deprecated encodings are detected."""
        graph = _make_obograph()["graphs"][0]
        active, dep_bpv, dep_meta = graph["nodes"]
        self.assertFalse(self.transform._is_deprecated_node(active))
        self.assertTrue(self.transform._is_deprecated_node(dep_bpv))
        self.assertTrue(self.transform._is_deprecated_node(dep_meta))

    def test_drop_deprecated_terms_removes_nodes_and_dangling_edges(self):
        """Deprecated nodes and any edges touching them are removed in place."""
        path = Path(self.tmp_json())
        self.transform._drop_deprecated_terms(path)

        result = json.loads(path.read_text())
        graph = result["graphs"][0]
        node_ids = {n["id"] for n in graph["nodes"]}

        # Only the active term survives.
        self.assertEqual(node_ids, {"https://w3id.org/metpo/1000001"})
        # No node flagged deprecated remains.
        self.assertFalse(any(self.transform._is_deprecated_node(n) for n in graph["nodes"]))
        # The edge touching a deprecated node is gone; the active-only edge stays.
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["obj"], "https://w3id.org/metpo/1000001")

    def test_active_only_graph_is_untouched(self):
        """A graph with no deprecated terms is left unchanged (no rewrite)."""
        data = {"graphs": [{"nodes": [{"id": "https://w3id.org/metpo/1000001", "lbl": "x"}], "edges": []}]}
        path = Path(self.tmp_json(data))
        before = path.read_text()
        self.transform._drop_deprecated_terms(path)
        self.assertEqual(path.read_text(), before)

    def tmp_json(self, data=None):
        """Write an obograph dict to a temp file and return its path."""
        import tempfile

        if data is None:
            data = _make_obograph()
        fd = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, fd)
        fd.close()
        return fd.name
