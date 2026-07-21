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
        # The filter methods use no instance state; bypass Transform.__init__
        # (which sets up source dirs) to keep the test isolated.
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def _write_edges(self, rows):
        """Write an edges TSV to a temp file and return its path."""
        tmp = Path(tempfile.mkdtemp()) / "x_edges.tsv"
        pd.DataFrame(rows, columns=_HEADER).to_csv(tmp, sep="\t", index=False)
        return tmp

    # ---- DataFrame-level helper ----

    def test_drop_helper_removes_metamodel_keeps_entity(self):
        """_drop_metamodel_edges returns (filtered_df, count); entity edges survive."""
        df = pd.DataFrame(_ROWS, columns=_HEADER)
        out, dropped = self.transform._drop_metamodel_edges(df)
        self.assertEqual(dropped, 3)
        self.assertEqual(set(out["predicate"]), {"biolink:subclass_of", "biolink:related_to"})
        self.assertEqual(len(out), 2)

    def test_drop_helper_noop_when_none(self):
        """A frame with only entity edges is returned with a zero drop count."""
        df = pd.DataFrame([r for r in _ROWS if r[1].startswith("biolink:")], columns=_HEADER)
        out, dropped = self.transform._drop_metamodel_edges(df)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(out), 2)

    def test_drop_helper_missing_predicate_column(self):
        """No predicate column → frame returned unchanged, zero dropped."""
        df = pd.DataFrame([["a", "b"]], columns=["subject", "object"])
        out, dropped = self.transform._drop_metamodel_edges(df)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(out), 1)

    # ---- Integration through _normalize_schema (post biolink:->CURIE remap) ----

    def test_normalize_schema_remaps_then_drops_metamodel(self):
        """
        Remap KGX's biolink: meta-predicates in _normalize_schema, then drop them.

        KGX emits these axioms as ``biolink:subPropertyOf`` / ``biolink:inverseOf``
        / ``biolink:type``; _normalize_schema remaps to rdfs/owl/rdf CURIEs and
        only then can the drop match — so the drop must run there, not earlier.
        """
        header = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
        self.transform.edge_header = header
        rows = [
            # Entity edge — kept (biolink:subclass_of is not a meta-predicate).
            ["ENVO:00000015", "biolink:subclass_of", "ENVO:00000012", "rdfs:subClassOf", "envo.json"],
            # Metamodel edges in KGX's biolink: serialization — remapped then dropped.
            ["METPO:2000002", "biolink:subPropertyOf", "METPO:2000001", "subPropertyOf", "metpo.json"],
            ["RO:0002327", "biolink:inverseOf", "RO:0002333", "inverseOf", "envo.json"],
            ["WD_Entity:Q715269", "biolink:type", "ENVO:00000015", "type", "envo.json"],
        ]
        tmp = Path(tempfile.mkdtemp())
        edges = tmp / "x_edges.tsv"
        pd.DataFrame(rows, columns=header).to_csv(edges, sep="\t", index=False)
        # nodes_file absent → node branch is skipped by its is_file() guard.
        self.transform._normalize_schema(tmp / "x_nodes.tsv", edges)
        df = pd.read_csv(edges, sep="\t")
        self.assertEqual(set(df["predicate"]), {"biolink:subclass_of"})
        self.assertEqual(len(df), 1)
        # The surviving entity edge keeps its other columns intact.
        self.assertEqual(df.iloc[0]["relation"], "rdfs:subClassOf")
        self.assertEqual(df.iloc[0]["primary_knowledge_source"], "envo.json")
