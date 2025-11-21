"""Test KEGG transform."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kg_microbe.transform_utils.kegg.kegg import KEGGTransform
from kg_microbe.transform_utils.kegg.utils import (
    get_kegg_ko_details,
    get_kegg_ko_list,
    parse_kegg_entry,
    parse_kegg_ko_list_file,
)


class TestKEGGUtils(unittest.TestCase):

    """Test KEGG utility functions."""

    @patch("kg_microbe.transform_utils.kegg.utils.requests.get")
    def test_get_kegg_ko_list(self, mock_get):
        """Test fetching KEGG KO list from API."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.text = (
            "ko:K00001\talcohol dehydrogenase [EC:1.1.1.1]\n"
            "ko:K00002\talcohol dehydrogenase (NADP+) [EC:1.1.1.2]\n"
            "ko:K00003\thomoserine dehydrogenase [EC:1.1.1.3]\n"
        )
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        ko_dict = get_kegg_ko_list()

        # Check results
        self.assertEqual(len(ko_dict), 3)
        self.assertIn("K00001", ko_dict)
        self.assertEqual(ko_dict["K00001"], "alcohol dehydrogenase [EC:1.1.1.1]")
        self.assertIn("K00002", ko_dict)
        self.assertIn("K00003", ko_dict)

    def test_parse_kegg_entry_basic(self):
        """Test parsing basic KEGG entry."""
        entry_text = """ENTRY       K00001                      KO
NAME        E1.1.1.1, adh
DEFINITION  alcohol dehydrogenase [EC:1.1.1.1]
///
"""
        details = parse_kegg_entry(entry_text)

        self.assertEqual(details["entry"], "K00001")
        self.assertEqual(details["name"], "E1.1.1.1, adh")
        self.assertEqual(details["definition"], "alcohol dehydrogenase [EC:1.1.1.1]")

    def test_parse_kegg_entry_with_pathways(self):
        """Test parsing KEGG entry with pathways."""
        entry_text = """ENTRY       K00001                      KO
NAME        E1.1.1.1, adh
DEFINITION  alcohol dehydrogenase [EC:1.1.1.1]
PATHWAY     ko00010  Glycolysis / Gluconeogenesis
            ko00071  Fatty acid degradation
            ko00350  Tyrosine metabolism
MODULE      M00001  Glycolysis (Embden-Meyerhof pathway), glucose => pyruvate
            M00002  Glycolysis, core module involving three-carbon compounds
///
"""
        details = parse_kegg_entry(entry_text)

        self.assertEqual(details["entry"], "K00001")
        self.assertEqual(len(details["pathways"]), 3)
        self.assertEqual(details["pathways"][0]["id"], "ko00010")
        self.assertEqual(details["pathways"][0]["name"], "Glycolysis / Gluconeogenesis")

        self.assertEqual(len(details["modules"]), 2)
        self.assertEqual(details["modules"][0]["id"], "M00001")

    def test_parse_kegg_entry_multiline_definition(self):
        """Test parsing KEGG entry with multiline definition."""
        entry_text = """ENTRY       K00003                      KO
NAME        hom, thrA
DEFINITION  homoserine dehydrogenase
            [EC:1.1.1.3]
///
"""
        details = parse_kegg_entry(entry_text)

        self.assertEqual(details["entry"], "K00003")
        self.assertIn("homoserine dehydrogenase", details["definition"])
        self.assertIn("[EC:1.1.1.3]", details["definition"])

    @patch("kg_microbe.transform_utils.kegg.utils.requests.get")
    @patch("kg_microbe.transform_utils.kegg.utils.time.sleep")  # Mock sleep to speed up tests
    def test_get_kegg_ko_details(self, mock_sleep, mock_get):
        """Test fetching KO details from API."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.text = """ENTRY       K00001                      KO
NAME        E1.1.1.1, adh
DEFINITION  alcohol dehydrogenase [EC:1.1.1.1]
///
"""
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        details = get_kegg_ko_details("K00001")

        # Check results
        self.assertIsNotNone(details)
        self.assertEqual(details["entry"], "K00001")
        self.assertEqual(details["name"], "E1.1.1.1, adh")

        # Verify sleep was called for rate limiting
        mock_sleep.assert_called()


class TestKEGGTransform(unittest.TestCase):

    """Test KEGG transform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_output_dir = tempfile.mkdtemp()

    def test_transform_initialization(self):
        """Test KEGGTransform initialization."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        self.assertEqual(transform.source_name, "kegg")
        self.assertEqual(transform.knowledge_source, "infores:kegg")
        self.assertEqual(len(transform.nodes), 0)
        self.assertEqual(len(transform.edges), 0)

    def test_add_ko_node(self):
        """Test adding KEGG KO node."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_ko_node("K00001", "alcohol dehydrogenase [EC:1.1.1.1]")

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "KEGG:K00001")
        self.assertEqual(node["category"], "biolink:GeneFamily")
        self.assertEqual(node["name"], "alcohol dehydrogenase [EC:1.1.1.1]")
        self.assertEqual(node["description"], "alcohol dehydrogenase [EC:1.1.1.1]")

    def test_add_ko_node_with_semicolon_parsing(self):
        """Test adding KEGG KO node with semicolon parsing."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_ko_node(
            "K00002",
            "alcohol dehydrogenase (NADP+); some additional details",
        )

        # Check node was added with parsed name
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "KEGG:K00002")
        self.assertEqual(node["name"], "alcohol dehydrogenase (NADP+)")

    def test_add_ko_node_deduplicate(self):
        """Test that duplicate KO nodes are not added."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add same KO twice
        transform.add_ko_node("K00001", "alcohol dehydrogenase [EC:1.1.1.1]")
        transform.add_ko_node("K00001", "alcohol dehydrogenase [EC:1.1.1.1]")

        # Should only have one node
        self.assertEqual(len(transform.nodes), 1)

    def test_add_pathway_node(self):
        """Test adding KEGG pathway node."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_pathway_node("ko00010", "Glycolysis / Gluconeogenesis")

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "KEGG:ko00010")
        self.assertEqual(node["category"], "biolink:Pathway")
        self.assertEqual(node["name"], "Glycolysis / Gluconeogenesis")

    def test_add_edge(self):
        """Test adding edge."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_edge(
            "KEGG:K00001",
            "biolink:participates_in",
            "KEGG:ko00010",
            "RO:0000056",
        )

        # Check edge was added
        self.assertEqual(len(transform.edges), 1)
        edge = transform.edges[0]

        self.assertEqual(edge["subject"], "KEGG:K00001")
        self.assertEqual(edge["predicate"], "biolink:participates_in")
        self.assertEqual(edge["object"], "KEGG:ko00010")
        self.assertEqual(edge["relation"], "RO:0000056")
        self.assertEqual(edge["primary_knowledge_source"], "infores:kegg")

    def test_add_module_node(self):
        """Test adding KEGG module node."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_module_node("M00001", "Glycolysis (Embden-Meyerhof pathway)")

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "KEGG:M00001")
        self.assertEqual(node["category"], "biolink:Pathway")
        self.assertEqual(node["name"], "Glycolysis (Embden-Meyerhof pathway)")

    def test_add_module_node_deduplicate(self):
        """Test that duplicate module nodes are not added."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add same module twice
        transform.add_module_node("M00001", "Glycolysis (Embden-Meyerhof pathway)")
        transform.add_module_node("M00001", "Glycolysis (Embden-Meyerhof pathway)")

        # Should only have one node
        self.assertEqual(len(transform.nodes), 1)

    def test_ko_to_pathway_edge(self):
        """Test creating KO→Pathway edge."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add nodes
        transform.add_ko_node("K00001", "alcohol dehydrogenase")
        transform.add_pathway_node("ko00010", "Glycolysis / Gluconeogenesis")

        # Add edge
        transform.add_edge(
            "KEGG:K00001",
            "biolink:participates_in",
            "KEGG:ko00010",
            "RO:0000056",
        )

        # Verify
        self.assertEqual(len(transform.nodes), 2)
        self.assertEqual(len(transform.edges), 1)

        edge = transform.edges[0]
        self.assertEqual(edge["subject"], "KEGG:K00001")
        self.assertEqual(edge["object"], "KEGG:ko00010")
        self.assertEqual(edge["predicate"], "biolink:participates_in")

    def test_ko_to_module_edge(self):
        """Test creating KO→Module edge."""
        transform = KEGGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add nodes
        transform.add_ko_node("K00001", "alcohol dehydrogenase")
        transform.add_module_node("M00001", "Glycolysis")

        # Add edge
        transform.add_edge(
            "KEGG:K00001",
            "biolink:participates_in",
            "KEGG:M00001",
            "RO:0000056",
        )

        # Verify
        self.assertEqual(len(transform.nodes), 2)
        self.assertEqual(len(transform.edges), 1)

        edge = transform.edges[0]
        self.assertEqual(edge["subject"], "KEGG:K00001")
        self.assertEqual(edge["object"], "KEGG:M00001")
        self.assertEqual(edge["predicate"], "biolink:participates_in")

    def test_parse_kegg_ko_list_file(self):
        """Test parsing KEGG KO list from file."""
        # Create temporary test file
        test_file = Path(self.temp_output_dir) / "test_ko_list.txt"
        with open(test_file, "w") as f:
            f.write("ko:K00001\talcohol dehydrogenase [EC:1.1.1.1]\n")
            f.write("ko:K00002\talcohol dehydrogenase (NADP+) [EC:1.1.1.2]\n")
            f.write("ko:K00003\thomoserine dehydrogenase [EC:1.1.1.3]\n")

        ko_dict = parse_kegg_ko_list_file(test_file)

        # Check results
        self.assertEqual(len(ko_dict), 3)
        self.assertIn("K00001", ko_dict)
        self.assertEqual(ko_dict["K00001"], "alcohol dehydrogenase [EC:1.1.1.1]")
        self.assertIn("K00002", ko_dict)
        self.assertIn("K00003", ko_dict)


if __name__ == "__main__":
    unittest.main()
