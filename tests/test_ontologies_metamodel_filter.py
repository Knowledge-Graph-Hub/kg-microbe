"""Tests for the ontology metamodel-edge filter in the ontologies transform."""

import tempfile
from pathlib import Path
from unittest import TestCase

import pandas as pd

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

_HEADER = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
_ROWS = [
    # Entity edges — kept.
    ["ENVO:00000015", "biolink:subclass_of", "ENVO:00000012", "rdfs:subClassOf", "envo.json"],
    ["ENVO:00000015", "biolink:related_to", "ENVO:00000020", "RO:0002131", "envo.json"],
    # Metamodel axiom edges — dropped.
    ["METPO:2000002", "rdfs:subPropertyOf", "METPO:2000001", "rdfs:subPropertyOf", "metpo.json"],
    ["RO:0002327", "owl:inverseOf", "RO:0002333", "owl:inverseOf", "envo.json"],
    ["WD_Entity:Q715269", "rdf:type", "ENVO:00000015", "rdf:type", "envo.json"],
]


class MetamodelEdgeFilterTest(TestCase):

    """Test that rdfs:subPropertyOf / owl:inverseOf / rdf:type edges are dropped."""

    def setUp(self):
        """Instantiate the transform without base __init__ side effects."""
        # _drop_metamodel_edges uses no instance state; bypass Transform.__init__
        # (which sets up source dirs) to keep the test isolated.
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def _write_edges(self, rows):
        """Write an edges TSV to a temp file and return its path."""
        tmp = Path(tempfile.mkdtemp()) / "x_edges.tsv"
        pd.DataFrame(rows, columns=_HEADER).to_csv(tmp, sep="\t", index=False)
        return tmp

    def test_drops_metamodel_keeps_entity_edges(self):
        """The three metamodel predicates are removed; entity edges survive."""
        path = self._write_edges(_ROWS)
        self.transform._drop_metamodel_edges(path)
        df = pd.read_csv(path, sep="\t")
        preds = set(df["predicate"])
        self.assertNotIn("rdfs:subPropertyOf", preds)
        self.assertNotIn("owl:inverseOf", preds)
        self.assertNotIn("rdf:type", preds)
        self.assertEqual(preds, {"biolink:subclass_of", "biolink:related_to"})
        self.assertEqual(len(df), 2)

    def test_no_metamodel_edges_is_a_noop(self):
        """An edge file with only entity edges is left unchanged."""
        entity_only = [r for r in _ROWS if r[1].startswith("biolink:")]
        path = self._write_edges(entity_only)
        before = path.read_text()
        self.transform._drop_metamodel_edges(path)
        self.assertEqual(path.read_text(), before)

    def test_idempotent(self):
        """Running the filter twice does not raise and leaves entity edges intact."""
        path = self._write_edges(_ROWS)
        self.transform._drop_metamodel_edges(path)
        self.transform._drop_metamodel_edges(path)
        df = pd.read_csv(path, sep="\t")
        self.assertEqual(len(df), 2)

    def test_missing_file_is_a_noop(self):
        """A non-existent edge file is a silent no-op (no raise)."""
        self.transform._drop_metamodel_edges(Path(tempfile.mkdtemp()) / "does_not_exist.tsv")
