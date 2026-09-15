"""Test the assay node and edge generation functions."""

import csv
import unittest

from parameterized import parameterized

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    ASSAY_CATEGORY,
    ASSAY_HAS_INPUT_PREDICATE,
    ASSAY_HAS_OUTPUT_PREDICATE,
    ASSAY_INPUT_RELATION,
    ASSAY_OUTPUT_RELATION,
    ASSAY_PREFIX,
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.utils.mapping_file_utils import (
    generate_assay_entity_edges,
    generate_assay_nodes,
)


class TestAssayGeneration(unittest.TestCase):
    """Tests for assay node and edge generation functions."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Define node and edge headers matching Transform class
        self.node_header = [
            ID_COLUMN,
            CATEGORY_COLUMN,
            NAME_COLUMN,
            DESCRIPTION_COLUMN,
            XREF_COLUMN,
            PROVIDED_BY_COLUMN,
            SYNONYM_COLUMN,
            SAME_AS_COLUMN,
        ]

        self.edge_header = [
            SUBJECT_COLUMN,
            PREDICATE_COLUMN,
            OBJECT_COLUMN,
            RELATION_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
            KNOWLEDGE_LEVEL_COLUMN,
            AGENT_TYPE_COLUMN,
        ]
        from kg_microbe.utils.go_authority import GoAuthority, GoTerm

        self.go_authority = GoAuthority(
            {
                curie: GoTerm(curie, "Fixture molecular function", "molecular_function")
                for curie in ("GO:0004565", "GO:0004032")
            }
        )

        # Mock assay data matching assay_kits_simple.json structure
        self.mock_assay_data = {
            "api_kits": [
                {
                    "kit_name": "API 20E",
                    "predicates": {
                        "positive": "METPO:2000001",
                        "negative": "METPO:2000002",
                    },
                    "wells": [
                        {
                            "name": "ONPG",
                            "label": ["ONPG"],
                            "type": ["enzyme"],
                            "go_terms": ["GO:0004565"],
                            "ec_number": ["3.2.1.23"],
                            "chebi_id": [],
                            "description": ["Beta-galactosidase test"],
                        },
                        {
                            "name": "ADH",
                            "label": ["ADH"],
                            "type": ["enzyme"],
                            "go_terms": ["GO:0004032"],
                            "ec_number": ["1.1.1.1"],
                            "chebi_id": [],
                            "description": ["Alcohol dehydrogenase test"],
                        },
                        {
                            "name": "GLU",
                            "label": ["GLU"],
                            "type": ["chemical"],
                            "go_terms": [],
                            "ec_number": [],
                            "chebi_id": ["CHEBI:17634"],
                            "description": ["Glucose fermentation test"],
                        },
                    ],
                },
                {
                    "kit_name": "API 50CH",
                    "predicates": {
                        "positive": "METPO:2000003",
                        "negative": "METPO:2000004",
                    },
                    "wells": [
                        {
                            "name": "GLC",
                            "label": ["GLC"],
                            "type": ["chemical"],
                            "go_terms": [],
                            "ec_number": [],
                            "chebi_id": ["CHEBI:17234"],
                            "description": ["Glucose assimilation test"],
                        },
                        {
                            "name": "FRU",
                            "label": ["FRU"],
                            "type": ["chemical"],
                            "go_terms": [],
                            "ec_number": [],
                            "chebi_id": ["CHEBI:28757"],
                            "description": ["Fructose assimilation test"],
                        },
                    ],
                },
            ]
        }

    def test_generate_assay_nodes_count(self):
        """Test that generate_assay_nodes creates correct number of nodes."""
        nodes = generate_assay_nodes(self.mock_assay_data, self.node_header)

        # Should create 5 nodes total (3 from API_20E + 2 from API_50CH)
        self.assertEqual(len(nodes), 5)

    def test_generate_assay_nodes_structure(self):
        """Test that generated assay nodes have correct structure."""
        nodes = generate_assay_nodes(self.mock_assay_data, self.node_header)

        # Check first node structure
        first_node = nodes[0]

        # Should have same length as header
        self.assertEqual(len(first_node), len(self.node_header))

        # Check that ID starts with assay prefix
        node_dict = dict(zip(self.node_header, first_node, strict=False))
        self.assertTrue(node_dict[ID_COLUMN].startswith(ASSAY_PREFIX))

        # Check category is correct
        self.assertEqual(node_dict[CATEGORY_COLUMN], ASSAY_CATEGORY)

        # Check that description field exists and is populated
        self.assertIsNotNone(node_dict[DESCRIPTION_COLUMN])
        self.assertGreater(len(node_dict[DESCRIPTION_COLUMN]), 0)

    @parameterized.expand(
        [
            ("API_20E_ONPG", "API 20E", "ONPG", "enzyme"),
            ("API_20E_GLU", "API 20E", "GLU", "chemical"),
            ("API_50CH_GLC", "API 50CH", "GLC", "chemical"),
        ]
    )
    def test_generate_assay_nodes_description_metadata(self, node_id, expected_kit, expected_well, expected_type):
        """Test that assay node description contains kit, well, and test type metadata."""
        nodes = generate_assay_nodes(self.mock_assay_data, self.node_header)

        # Find the specific node by ID
        target_node = None
        for node in nodes:
            node_dict = dict(zip(self.node_header, node, strict=False))
            if node_dict[ID_COLUMN] == f"{ASSAY_PREFIX}{node_id}":
                target_node = node_dict
                break

        self.assertIsNotNone(target_node, f"Node {node_id} not found")

        # Check that description contains all metadata
        description = target_node[DESCRIPTION_COLUMN]
        self.assertIn(f"Kit: {expected_kit}", description)
        self.assertIn(f"Well: {expected_well}", description)
        self.assertIn(f"Type: {expected_type}", description)

    def test_generate_assay_entity_edges_count(self):
        """Test that generate_assay_entity_edges creates correct number of edges."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # Expected edges:
        # API_20E/ONPG: 1 GO + 1 EC = 2 edges
        # API_20E/ADH: 1 GO + 1 EC = 2 edges
        # API_20E/GLU: 1 ChEBI = 1 edge
        # API_50CH/GLC: 1 ChEBI = 1 edge
        # API_50CH/FRU: 1 ChEBI = 1 edge
        # Total: 7 edges
        self.assertEqual(len(edges), 7)

    def test_generate_assay_entity_edges_structure(self):
        """Test that generated edges have correct structure."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # Check first edge structure
        first_edge = edges[0]

        # Should have same length as header
        self.assertEqual(len(first_edge), len(self.edge_header))

        # Check that subject starts with assay prefix
        edge_dict = dict(zip(self.edge_header, first_edge, strict=False))
        self.assertTrue(edge_dict[SUBJECT_COLUMN].startswith(ASSAY_PREFIX))

    def test_generate_assay_entity_edges_enzyme_predicates(self):
        """Test that enzyme test edges use correct predicates."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # Find edges from enzyme tests (ONPG and ADH)
        enzyme_edges = []
        for edge in edges:
            edge_dict = dict(zip(self.edge_header, edge, strict=False))
            # Check if object is GO or EC
            if edge_dict[OBJECT_COLUMN].startswith("GO:") or edge_dict[OBJECT_COLUMN].startswith("EC:"):
                enzyme_edges.append(edge_dict)

        # Should have 4 enzyme edges (2 from ONPG + 2 from ADH)
        self.assertEqual(len(enzyme_edges), 4)

        # All enzyme edges should use has_output predicate
        for edge in enzyme_edges:
            self.assertEqual(edge[PREDICATE_COLUMN], ASSAY_HAS_OUTPUT_PREDICATE)
            self.assertEqual(edge[RELATION_COLUMN], ASSAY_OUTPUT_RELATION)

    def test_generate_assay_entity_edges_chemical_predicates(self):
        """Test that chemical test edges use correct predicates."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # Find edges from chemical tests (GLU, GLC, FRU)
        chemical_edges = []
        for edge in edges:
            edge_dict = dict(zip(self.edge_header, edge, strict=False))
            # Check if object is ChEBI
            if edge_dict[OBJECT_COLUMN].startswith("CHEBI:"):
                chemical_edges.append(edge_dict)

        # Should have 3 chemical edges
        self.assertEqual(len(chemical_edges), 3)

        # All chemical edges should use has_input predicate
        for edge in chemical_edges:
            self.assertEqual(edge[PREDICATE_COLUMN], ASSAY_HAS_INPUT_PREDICATE)
            self.assertEqual(edge[RELATION_COLUMN], ASSAY_INPUT_RELATION)

    def test_generate_assay_entity_edges_knowledge_source(self):
        """Test that edges have correct knowledge source attribution."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # All edges should have infores:assay-metadata as primary knowledge source
        for edge in edges:
            edge_dict = dict(zip(self.edge_header, edge, strict=False))
            self.assertEqual(edge_dict[PRIMARY_KNOWLEDGE_SOURCE_COLUMN], "infores:assay-metadata")
            self.assertEqual(edge_dict[KNOWLEDGE_LEVEL_COLUMN], "knowledge_assertion")
            self.assertEqual(edge_dict[AGENT_TYPE_COLUMN], "manual_agent")

    @parameterized.expand(
        [
            ("API_20E_ONPG", ["GO:0004565", "EC:3.2.1.23"]),
            ("API_20E_ADH", ["GO:0004032", "EC:1.1.1.1"]),
            ("API_20E_GLU", ["CHEBI:17634"]),
            ("API_50CH_GLC", ["CHEBI:17234"]),
            ("API_50CH_FRU", ["CHEBI:28757"]),
        ]
    )
    def test_generate_assay_entity_edges_correct_targets(self, assay_id, expected_objects):
        """Test that edges connect to correct entity IDs."""
        edges = generate_assay_entity_edges(self.mock_assay_data, self.edge_header, go_authority=self.go_authority)

        # Find edges from this assay
        assay_edges = []
        for edge in edges:
            edge_dict = dict(zip(self.edge_header, edge, strict=False))
            if edge_dict[SUBJECT_COLUMN] == f"{ASSAY_PREFIX}{assay_id}":
                assay_edges.append(edge_dict[OBJECT_COLUMN])

        # Check that all expected objects are present
        self.assertEqual(set(assay_edges), set(expected_objects))

    def test_generate_assay_nodes_empty_data(self):
        """Test that functions handle empty data gracefully."""
        empty_data = {}
        nodes = generate_assay_nodes(empty_data, self.node_header)
        edges = generate_assay_entity_edges(empty_data, self.edge_header)

        self.assertEqual(len(nodes), 0)
        self.assertEqual(len(edges), 0)

    def test_generate_assay_nodes_id_format(self):
        """Test that assay node IDs follow correct format."""
        nodes = generate_assay_nodes(self.mock_assay_data, self.node_header)

        for node in nodes:
            node_dict = dict(zip(self.node_header, node, strict=False))
            node_id = node_dict[ID_COLUMN]

            # Should match pattern: {ASSAY_PREFIX}{kit_name}_{well_name}
            self.assertTrue(node_id.startswith(ASSAY_PREFIX))

            # Should contain underscore separator
            id_parts = node_id.replace(ASSAY_PREFIX, "").split("_")
            self.assertGreaterEqual(len(id_parts), 2)

    def test_generate_assay_nodes_name_format(self):
        """Test that assay node names are human-readable."""
        nodes = generate_assay_nodes(self.mock_assay_data, self.node_header)

        for node in nodes:
            node_dict = dict(zip(self.node_header, node, strict=False))
            name = node_dict[NAME_COLUMN]

            # Name should contain kit name and dash separator
            self.assertIn(" - ", name)

            # Name should be non-empty
            self.assertTrue(len(name) > 0)


class TestECSubstrateEdges(unittest.TestCase):
    """Exercise the production BacDive enzyme-substrate emitter, not a copied loop."""

    def setUp(self) -> None:
        """Use a tiny immutable mapping fixture and the real transform methods."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
        from kg_microbe.transform_utils.transform import Transform

        self.transform = BacDiveTransform.__new__(BacDiveTransform)
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        Transform.__init__(self.transform, "bacdive", input_dir=root / "raw", output_dir=root / "out")
        self.transform.knowledge_source = "infores:bacdive"
        self.transform.chebi_categories = {}
        fixture = Path(__file__).parent / "resources" / "assay_reference_repairs" / "ec_substrates.tsv"
        with fixture.open(newline="", encoding="utf-8") as stream:
            self.mappings = list(csv.DictReader(stream, delimiter="\t"))

    def test_real_ec_substrate_predicates_and_metadata(self):
        """Changing assay constants must not turn enzymes into assay procedure subjects."""
        edges, nodes = self.transform._generate_ec_substrate_rows(self.mappings)
        self.assertEqual(len(edges), 3)
        self.assertEqual(len(nodes), 3)
        rows = [dict(zip(self.transform.edge_header, row, strict=True)) for row in edges]
        self.assertEqual(
            {(row[SUBJECT_COLUMN], row[OBJECT_COLUMN]) for row in rows},
            {("EC:4.1.99.1", "CHEBI:16828"), ("EC:3.5.1.5", "CHEBI:16199"), ("EC:3.2.1.21", "CHEBI:4853")},
        )
        for row in rows:
            self.assertEqual(row[PREDICATE_COLUMN], "biolink:has_input")
            self.assertEqual(row[RELATION_COLUMN], "RO:0002233")
            self.assertNotEqual(row[PREDICATE_COLUMN], ASSAY_HAS_INPUT_PREDICATE)
            self.assertEqual(row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN], "infores:bacdive")
            self.assertEqual(row[KNOWLEDGE_LEVEL_COLUMN], "knowledge_assertion")
            self.assertEqual(row[AGENT_TYPE_COLUMN], "manual_agent")

    def test_real_emitter_projects_extended_and_reordered_headers(self):
        """All fields follow the caller's header, including empty observation extensions."""
        self.transform.edge_header = [
            "value",
            OBJECT_COLUMN,
            SUBJECT_COLUMN,
            "original_object",
            PREDICATE_COLUMN,
            RELATION_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
            KNOWLEDGE_LEVEL_COLUMN,
            AGENT_TYPE_COLUMN,
        ]
        edges, _ = self.transform._generate_ec_substrate_rows(self.mappings)
        self.assertTrue(all(len(row) == len(self.transform.edge_header) for row in edges))
        row = dict(zip(self.transform.edge_header, edges[0], strict=True))
        self.assertEqual(row[SUBJECT_COLUMN], "EC:4.1.99.1")
        self.assertEqual(row[OBJECT_COLUMN], "CHEBI:16828")
        self.assertEqual(row["value"], "")
        self.assertEqual(row["original_object"], "")

    def test_repeated_substrates_do_not_duplicate_stub_nodes(self):
        """References retain their assertions while target declarations are emitted once."""
        edges, nodes = self.transform._generate_ec_substrate_rows(self.mappings + self.mappings)
        self.assertEqual(len(edges), 6)
        self.assertEqual(len(nodes), 3)
