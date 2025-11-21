"""Test COG transform."""

import tempfile
import unittest
from pathlib import Path

from kg_microbe.transform_utils.cog.cog import COGTransform
from kg_microbe.transform_utils.cog.utils import (
    get_category_group_name,
    parse_cog_definitions,
    parse_functional_categories,
    split_functional_categories,
)


class TestCOGUtils(unittest.TestCase):

    """Test COG utility functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_resources_dir = Path(__file__).parent / "resources" / "cog"
        self.cog_def_file = self.test_resources_dir / "cog-24.def.tab"
        self.cog_fun_file = self.test_resources_dir / "cog-24.fun.tab"

    def test_parse_cog_definitions(self):
        """Test parsing COG definitions file."""
        cog_defs = parse_cog_definitions(self.cog_def_file)

        # Check that we parsed entries
        self.assertGreater(len(cog_defs), 0)

        # Check specific COG entry
        self.assertIn("COG0001", cog_defs)
        cog0001 = cog_defs["COG0001"]

        self.assertEqual(cog0001["functional_category"], "H")
        self.assertEqual(cog0001["name"], "Glutamate-1-semialdehyde aminotransferase")
        self.assertEqual(cog0001["gene_name"], "hemL")
        self.assertEqual(cog0001["pathway"], "Tetrapyrrole biosynthesis")
        self.assertEqual(cog0001["pmid"], "10026276")
        self.assertEqual(cog0001["pdb"], "3CPM")

    def test_parse_cog_definitions_multi_category(self):
        """Test parsing COG with multiple functional categories."""
        cog_defs = parse_cog_definitions(self.cog_def_file)

        # COG0004 has functional category "CP" (both C and P)
        self.assertIn("COG0004", cog_defs)
        cog0004 = cog_defs["COG0004"]
        self.assertEqual(cog0004["functional_category"], "CP")

    def test_parse_functional_categories(self):
        """Test parsing functional categories file."""
        func_cats = parse_functional_categories(self.cog_fun_file)

        # Check that we parsed categories
        self.assertGreater(len(func_cats), 0)

        # Check specific category
        self.assertIn("C", func_cats)
        cat_c = func_cats["C"]

        self.assertEqual(cat_c["group"], "2")
        self.assertEqual(cat_c["color"], "#FF6666")
        self.assertEqual(cat_c["description"], "Energy production and conversion")

    def test_get_category_group_name(self):
        """Test mapping group IDs to names."""
        self.assertEqual(get_category_group_name("1"), "Information Storage and Processing")
        self.assertEqual(get_category_group_name("2"), "Cellular Processes and Signaling")
        self.assertEqual(get_category_group_name("3"), "Metabolism")
        self.assertEqual(get_category_group_name("4"), "Poorly Characterized")
        self.assertEqual(get_category_group_name("99"), "Unknown")

    def test_split_functional_categories_single(self):
        """Test splitting single category."""
        categories = split_functional_categories("H")
        self.assertEqual(categories, ["H"])

    def test_split_functional_categories_multiple(self):
        """Test splitting multiple categories."""
        categories = split_functional_categories("CP")
        self.assertEqual(categories, ["C", "P"])

        categories = split_functional_categories("PTM")
        self.assertEqual(categories, ["P", "T", "M"])

    def test_split_functional_categories_empty(self):
        """Test splitting empty category string."""
        categories = split_functional_categories("")
        self.assertEqual(categories, [])


class TestCOGTransform(unittest.TestCase):

    """Test COG transform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_resources_dir = Path(__file__).parent / "resources" / "cog"
        self.temp_output_dir = tempfile.mkdtemp()

    def test_transform_initialization(self):
        """Test COGTransform initialization."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        self.assertEqual(transform.source_name, "cog")
        self.assertEqual(transform.knowledge_source, "infores:cog")
        self.assertEqual(len(transform.nodes), 0)
        self.assertEqual(len(transform.edges), 0)

    def test_add_functional_category_node(self):
        """Test adding functional category node."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        cat_data = {
            "group": "2",
            "color": "#FF6666",
            "description": "Energy production and conversion",
        }

        transform.add_functional_category_node("C", cat_data)

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "COG_CAT:C")
        self.assertEqual(node["category"], "biolink:OntologyClass")
        self.assertEqual(node["name"], "Energy production and conversion")
        self.assertIn("Cellular Processes and Signaling", node["description"])

        # Check seen_nodes tracking
        self.assertIn("COG_CAT:C", transform.seen_nodes)

    def test_add_functional_category_node_deduplicate(self):
        """Test that duplicate category nodes are not added."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        cat_data = {
            "group": "2",
            "color": "#FF6666",
            "description": "Energy production and conversion",
        }

        # Add same category twice
        transform.add_functional_category_node("C", cat_data)
        transform.add_functional_category_node("C", cat_data)

        # Should only have one node
        self.assertEqual(len(transform.nodes), 1)

    def test_add_cog_node(self):
        """Test adding COG node."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        cog_data = {
            "name": "Glutamate-1-semialdehyde aminotransferase",
            "gene_name": "hemL",
            "pathway": "Tetrapyrrole biosynthesis",
            "functional_category": "H",
        }

        transform.add_cog_node("COG0001", cog_data)

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "COG:COG0001")
        self.assertEqual(node["category"], "biolink:GeneFamily")
        self.assertEqual(node["name"], "Glutamate-1-semialdehyde aminotransferase")
        self.assertIn("hemL", node["description"])
        self.assertIn("Tetrapyrrole biosynthesis", node["description"])

    def test_add_cog_node_deduplicate(self):
        """Test that duplicate COG nodes are not added."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        cog_data = {
            "name": "Glutamate-1-semialdehyde aminotransferase",
            "gene_name": "hemL",
            "pathway": "Tetrapyrrole biosynthesis",
            "functional_category": "H",
        }

        # Add same COG twice
        transform.add_cog_node("COG0001", cog_data)
        transform.add_cog_node("COG0001", cog_data)

        # Should only have one node
        self.assertEqual(len(transform.nodes), 1)

    def test_add_edge(self):
        """Test adding edge."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_edge(
            "COG:COG0001",
            "biolink:has_attribute",
            "COG_CAT:H",
            "RO:0002200",
        )

        # Check edge was added
        self.assertEqual(len(transform.edges), 1)
        edge = transform.edges[0]

        self.assertEqual(edge["subject"], "COG:COG0001")
        self.assertEqual(edge["predicate"], "biolink:has_attribute")
        self.assertEqual(edge["object"], "COG_CAT:H")
        self.assertEqual(edge["relation"], "RO:0002200")
        self.assertEqual(edge["primary_knowledge_source"], "infores:cog")

    def test_add_group_node(self):
        """Test adding group node."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        transform.add_group_node("1")

        # Check node was added
        self.assertEqual(len(transform.nodes), 1)
        node = transform.nodes[0]

        self.assertEqual(node["id"], "COG_GROUP:1")
        self.assertEqual(node["category"], "biolink:OntologyClass")
        self.assertEqual(node["name"], "Information Storage and Processing")
        self.assertIn("Information Storage and Processing", node["description"])

        # Check seen_nodes tracking
        self.assertIn("COG_GROUP:1", transform.seen_nodes)

    def test_add_group_node_deduplicate(self):
        """Test that duplicate group nodes are not added."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add same group twice
        transform.add_group_node("1")
        transform.add_group_node("1")

        # Should only have one node
        self.assertEqual(len(transform.nodes), 1)

    def test_add_group_node_all_groups(self):
        """Test adding all 4 group nodes."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add all 4 groups
        for group_id in ["1", "2", "3", "4"]:
            transform.add_group_node(group_id)

        # Should have 4 nodes
        self.assertEqual(len(transform.nodes), 4)

        # Check node IDs
        node_ids = {node["id"] for node in transform.nodes}
        expected_ids = {"COG_GROUP:1", "COG_GROUP:2", "COG_GROUP:3", "COG_GROUP:4"}
        self.assertEqual(node_ids, expected_ids)

    def test_hierarchy_edge_creation(self):
        """Test that category→group hierarchy edges are created correctly."""
        transform = COGTransform(
            input_dir=Path("data/raw"),
            output_dir=Path(self.temp_output_dir),
        )

        # Add a group node
        transform.add_group_node("2")

        # Add a category that belongs to this group
        cat_data = {
            "group": "2",
            "color": "#FF6666",
            "description": "Energy production and conversion",
        }
        transform.add_functional_category_node("C", cat_data)

        # Add hierarchy edge
        transform.add_edge(
            "COG_CAT:C",
            "biolink:subclass_of",
            "COG_GROUP:2",
            "rdfs:subClassOf",
        )

        # Check edge was added
        self.assertEqual(len(transform.edges), 1)
        edge = transform.edges[0]

        self.assertEqual(edge["subject"], "COG_CAT:C")
        self.assertEqual(edge["predicate"], "biolink:subclass_of")
        self.assertEqual(edge["object"], "COG_GROUP:2")
        self.assertEqual(edge["relation"], "rdfs:subClassOf")
        self.assertEqual(edge["primary_knowledge_source"], "infores:cog")


if __name__ == "__main__":
    unittest.main()
