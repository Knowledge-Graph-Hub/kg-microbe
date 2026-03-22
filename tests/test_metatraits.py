"""Test Metatraits transform."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parameterized import parameterized

from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings

# Truth table from microbial-trait-mappings test_round_trip.py
EXPECTED_EDGES = [
    ("produces: ethanol", "biolink:produces", "CHEBI:16236", "biolink:ChemicalEntity"),
    ("produces: hydrogen sulfide", "biolink:produces", "CHEBI:16136", "biolink:ChemicalEntity"),
    ("produces: indole", "biolink:produces", "CHEBI:16881", "biolink:ChemicalEntity"),
    ("carbon source: acetate", "biolink:capable_of", "CHEBI:30089", "biolink:ChemicalEntity"),
    (
        "enzyme activity: catalase (EC1.11.1.6)",
        "biolink:capable_of",
        "EC:1.11.1.6",
        "biolink:MolecularActivity",
    ),
    (
        "enzyme activity: urease (EC3.5.1.5)",
        "biolink:capable_of",
        "EC:3.5.1.5",
        "biolink:MolecularActivity",
    ),
    (
        "enzyme activity: oxidase",
        "biolink:capable_of",
        "GO:0016491",
        "biolink:MolecularActivity",
    ),
    ("fermentation", "biolink:capable_of", "GO:0006113", "biolink:BiologicalProcess"),
    ("nitrogen fixation", "biolink:capable_of", "GO:0009399", "biolink:BiologicalProcess"),
    ("gram positive", "biolink:has_phenotype", "METPO:1000606", "biolink:PhenotypicFeature"),
    ("obligate aerobic", "biolink:has_phenotype", "METPO:1000616", "biolink:PhenotypicFeature"),
    ("thermophilic", "biolink:has_phenotype", "METPO:1000656", "biolink:PhenotypicFeature"),
]


@patch("kg_microbe.transform_utils.metatraits.metatraits._get_ncbitaxon_adapter")
class TestMetaTraitsTransform(unittest.TestCase):

    """Test MetaTraitsTransform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_resources_dir = Path(__file__).parent / "resources"
        self.temp_input_dir = Path(tempfile.mkdtemp())
        self.temp_output_dir = Path(tempfile.mkdtemp())
        self.fixture_file = self.test_resources_dir / "metatraits_fixture.jsonl"

    def test_transform_initialization(self, mock_adapter):
        """Test MetaTraitsTransform initialization."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        self.assertEqual(transform.source_name, "metatraits")
        self.assertEqual(transform.knowledge_source, "infores:metatraits")
        self.assertIsNotNone(transform.trait_mapping)
        self.assertIsNotNone(transform.ncbitaxon_name_to_id)

    def test_create_node_row(self, mock_adapter):
        """Test _create_node_row produces correct structure."""
        transform = MetaTraitsTransform(
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

    def test_get_relation_for_predicate(self, mock_adapter):
        """Test _get_relation_for_predicate returns correct RO terms."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        from kg_microbe.transform_utils.constants import (
            BIOLOGICAL_PROCESS,
            CAPABLE_OF_PREDICATE,
            HAS_PHENOTYPE,
            PRODUCES_RELATION,
        )

        self.assertEqual(
            transform._get_relation_for_predicate(CAPABLE_OF_PREDICATE),
            BIOLOGICAL_PROCESS,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("biolink:has_phenotype"),
            HAS_PHENOTYPE,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("biolink:produces"),
            PRODUCES_RELATION,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("METPO:2000202"),
            PRODUCES_RELATION,
        )

    def test_to_biolink_predicate(self, mock_adapter):
        """Test _to_biolink_predicate maps METPO to biolink."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        self.assertEqual(
            transform._to_biolink_predicate("METPO:2000202"),
            "biolink:produces",
        )
        self.assertEqual(
            transform._to_biolink_predicate("METPO:2000103"),
            "biolink:capable_of",
        )
        self.assertEqual(
            transform._to_biolink_predicate("biolink:has_phenotype"),
            "biolink:has_phenotype",
        )

    def test_produces_ethanol_is_not_has_phenotype(self, mock_adapter):
        """Test produces: ethanol resolves to biolink:produces, not has_phenotype."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        match = mappings.get("produces: ethanol") or mappings.get("produces: ethanol".lower())
        self.assertIsNotNone(match, "'produces: ethanol' should be in microbial mappings")
        self.assertEqual(
            match["biolink_predicate"],
            "biolink:produces",
            "'produces: ethanol' must NOT resolve to has_phenotype",
        )

    def test_collapse_detection(self, mock_adapter):
        """Test that not all predicates resolve to has_phenotype."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        predicates = {m["biolink_predicate"] for m in mappings.values()}
        self.assertGreater(len(predicates), 1, "Multiple predicate types required")
        self.assertIn("biolink:produces", predicates)
        self.assertIn("biolink:capable_of", predicates)
        self.assertIn("biolink:has_phenotype", predicates)

    @parameterized.expand(EXPECTED_EDGES)
    def test_edge_resolution_round_trip(
        self, mock_adapter, subject_label, expected_pred, expected_obj, expected_cat
    ):
        """Verify each trait resolves to correct (predicate, object_id, object_category)."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        match = mappings.get(subject_label) or mappings.get(subject_label.lower())
        self.assertIsNotNone(match, f"No mapping for '{subject_label}'")
        self.assertEqual(match["object_id"], expected_obj)
        self.assertEqual(match["biolink_predicate"], expected_pred)
        self.assertEqual(match["object_category"], expected_cat)

    @patch.object(MetaTraitsTransform, "_search_ncbitaxon_by_label")
    def test_run_with_fixture(self, mock_search, mock_adapter):
        """Test run() with fixture produces nodes and edges."""
        mock_search.return_value = "NCBITaxon:562"

        # Copy fixture to temporary input directory with expected filename
        import shutil

        metatraits_subdir = self.temp_input_dir / "metatraits"
        metatraits_subdir.mkdir(exist_ok=True)
        fixture_path = metatraits_subdir / "ncbi_species_summary.jsonl"
        shutil.copy(self.fixture_file, fixture_path)

        try:
            transform = MetaTraitsTransform(
                input_dir=self.temp_input_dir,
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
            self.assertIn("has_percentage", edges[0])

            # Verify that a 0% pct_true trait (gram positive) is included in edges
            # Parse TSV to check exact has_percentage value for gram positive trait
            header = edges[0].split("\t")
            pct_col_idx = header.index("has_percentage")
            obj_col_idx = header.index("object")

            found_zero_pct = False
            for edge_line in edges[1:]:
                cols = edge_line.split("\t")
                if len(cols) > max(pct_col_idx, obj_col_idx):
                    # Look for gram positive trait (METPO:1000606)
                    if "METPO:1000606" in cols[obj_col_idx]:
                        pct_value = cols[pct_col_idx]
                        self.assertEqual(pct_value, "0.0", "Gram positive trait should have 0.0 percentage")
                        found_zero_pct = True
                        break

            self.assertTrue(found_zero_pct, "0% pct_true trait (gram positive) should be included in edges")
        finally:
            # Cleanup temporary input directory
            import shutil

            if self.temp_input_dir.exists():
                shutil.rmtree(self.temp_input_dir)

    def test_run_without_input_files_raises(self, mock_adapter):
        """Test run() raises FileNotFoundError when no input files exist."""
        empty_dir = Path(tempfile.mkdtemp())
        transform = MetaTraitsTransform(
            input_dir=empty_dir,
            output_dir=self.temp_output_dir,
        )
        with self.assertRaises(FileNotFoundError) as ctx:
            transform.run(show_status=False)
        self.assertIn("No metatraits JSONL files found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
