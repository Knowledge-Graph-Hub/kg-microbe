"""Test the parent Transform class."""

from pathlib import Path
from unittest import TestCase

from parameterized import parameterized

from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.transform import Transform


class TestTransform(TestCase):

    """Tests for all transform child classes."""

    def setUp(self) -> None:
        """Set up the transform tests."""
        self.transform_instance = TransformChildClass()

    def test_reality(self):
        """Test the nature of reality."""
        self.assertEqual(1, 1)

    @parameterized.expand(
        [
            ("source_name", "test_transform"),
            (
                "node_header",
                [
                    "id",
                    "category",
                    "name",
                    "description",
                    "xref",
                    "provided_by",
                    "synonym",
                    "same_as",
                ],
            ),
            (
                "edge_header",
                [
                    "subject",
                    "predicate",
                    "object",
                    "relation",
                    "primary_knowledge_source",
                    "knowledge_level",
                    "agent_type",
                ],
            ),
        ]
    )
    def test_attributes(self, attr, default):
        """Test the attributes of a Transform instance."""
        self.assertTrue(hasattr(self.transform_instance, attr))
        self.assertEqual(getattr(self.transform_instance, attr), default)

    def test_default_dirs_exist(self):
        """Test that default directories are set and are Path objects."""
        self.assertIsNotNone(Transform.DEFAULT_INPUT_DIR)
        self.assertIsNotNone(Transform.DEFAULT_OUTPUT_DIR)
        self.assertIsInstance(Transform.DEFAULT_INPUT_DIR, Path)
        self.assertIsInstance(Transform.DEFAULT_OUTPUT_DIR, Path)

    def test_path_attributes(self):
        """Test that path attributes are set correctly."""
        t = self.transform_instance
        # Check that path attributes exist and are Path objects
        self.assertIsInstance(t.output_base_dir, Path)
        self.assertIsInstance(t.input_base_dir, Path)
        self.assertIsInstance(t.output_dir, Path)
        self.assertIsInstance(t.output_node_file, Path)
        self.assertIsInstance(t.output_edge_file, Path)
        self.assertIsInstance(t.output_json_file, Path)

        # Check that paths have expected structure
        self.assertTrue(str(t.output_node_file).endswith("nodes.tsv"))
        self.assertTrue(str(t.output_edge_file).endswith("edges.tsv"))
        self.assertTrue(str(t.output_json_file).endswith("nodes_edges.json"))

    @parameterized.expand(
        list(DATA_SOURCES.keys()),
    )
    def test_transform_child_classes(self, src_name):
        """
        Test whether Transform child classes work as expected.

        Make sure Transform child classes:
        - properly set default input_dir and output_dir
        - properly pass and set input_dir and output from constructor
        - implement run()
        :param src_name:
        :return: None
        """
        input_dir = Path("tests") / "resources"
        output_dir = Path("output")

        t = DATA_SOURCES[src_name](input_dir=input_dir, output_dir=output_dir)
        self.assertEqual(t.input_base_dir, input_dir)
        self.assertEqual(t.output_base_dir, output_dir)
        self.assertTrue(hasattr(t, "run"))
        # Check that class has default directories set
        self.assertIsNotNone(t.DEFAULT_INPUT_DIR)
        self.assertIsNotNone(t.DEFAULT_OUTPUT_DIR)
        self.assertIsInstance(t.DEFAULT_INPUT_DIR, Path)
        self.assertIsInstance(t.DEFAULT_OUTPUT_DIR, Path)


class TransformChildClass(Transform):

    """An example Transform class."""

    def __init__(self):
        """Initialize a Transform child class."""
        super().__init__(source_name="test_transform")
