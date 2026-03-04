"""Test Metatraits transform."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kg_microbe.transform_utils.metatraits.metatraits import MetatraitsTransform


class TestMetatraitsTransform(unittest.TestCase):

    """Test MetatraitsTransform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_resources_dir = Path(__file__).parent / "resources"
        self.temp_output_dir = Path(tempfile.mkdtemp())
        self.fixture_file = self.test_resources_dir / "metatraits_fixture.jsonl"

    def test_transform_initialization(self):
        """Test MetatraitsTransform initialization."""
        transform = MetatraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        self.assertEqual(transform.source_name, "metatraits")
        self.assertEqual(transform.knowledge_source, "infores:metatraits")
        self.assertIsNotNone(transform.trait_mapping)
        self.assertIsNotNone(transform.ncbitaxon_name_to_id)

    def test_create_node_row(self):
        """Test _create_node_row produces correct structure."""
        transform = MetatraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        row = transform._create_node_row(
            "NCBITaxon:562",
            "biolink:OrganismTaxon",
            "Escherichia coli",
        )
        self.assertEqual(len(row), len(transform.node_header))
        self.assertEqual(row[0], "NCBITaxon:562")
        self.assertEqual(row[1], "biolink:OrganismTaxon")
        self.assertEqual(row[2], "Escherichia coli")
        self.assertEqual(row[5], "infores:metatraits")

    def test_get_relation_for_predicate(self):
        """Test _get_relation_for_predicate returns correct RO terms."""
        transform = MetatraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        from kg_microbe.transform_utils.constants import (
            BIOLOGICAL_PROCESS,
            CAPABLE_OF_PREDICATE,
            HAS_PHENOTYPE,
        )

        self.assertEqual(
            transform._get_relation_for_predicate(CAPABLE_OF_PREDICATE),
            BIOLOGICAL_PROCESS,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("biolink:has_phenotype"),
            HAS_PHENOTYPE,
        )

    @patch.object(MetatraitsTransform, "_search_ncbitaxon_by_label")
    def test_run_with_fixture(self, mock_search):
        """Test run() with fixture produces nodes and edges."""
        mock_search.return_value = "NCBITaxon:562"

        # Copy fixture to expected input filename (plain JSONL)
        import shutil

        fixture_path = self.test_resources_dir / "ncbi_species_summary.jsonl"
        shutil.copy(self.fixture_file, fixture_path)

        try:
            transform = MetatraitsTransform(
                input_dir=self.test_resources_dir,
                output_dir=self.temp_output_dir,
            )
            transform._search_ncbitaxon_by_label = mock_search

            transform.run(show_status=False)

            self.assertTrue(transform.output_node_file.exists())
            self.assertTrue(transform.output_edge_file.exists())
            self.assertTrue(transform.unmapped_traits_file.exists())
            self.assertTrue(transform.unresolved_taxa_file.exists())

            nodes = list(transform.output_node_file.read_text().strip().split("\n"))
            edges = list(transform.output_edge_file.read_text().strip().split("\n"))
            self.assertGreater(len(nodes), 1)  # header + at least 1 node
            self.assertGreater(len(edges), 1)  # header + at least 1 edge

            # Check node header
            self.assertIn("id", nodes[0])
            self.assertIn("category", nodes[0])
            self.assertIn("name", nodes[0])

            # Check edge header
            self.assertIn("subject", edges[0])
            self.assertIn("predicate", edges[0])
            self.assertIn("object", edges[0])
        finally:
            if fixture_path.exists():
                fixture_path.unlink()

    def test_run_without_input_files_raises(self):
        """Test run() raises FileNotFoundError when no input files exist."""
        empty_dir = Path(tempfile.mkdtemp())
        transform = MetatraitsTransform(
            input_dir=empty_dir,
            output_dir=self.temp_output_dir,
        )
        with self.assertRaises(FileNotFoundError) as ctx:
            transform.run(show_status=False)
        self.assertIn("No metatraits JSONL files found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
