"""Test Bakta transform."""

import tempfile
import unittest
from pathlib import Path

from kg_microbe.transform_utils.bakta.bakta import BaktaTransform
from kg_microbe.transform_utils.bakta.utils import (
    create_gene_id,
    get_biolink_category_for_go,
    get_biolink_predicate_for_go,
    get_protein_id,
    parse_bakta_tsv,
    parse_dbxrefs,
)


class TestBaktaUtils(unittest.TestCase):

    """Test Bakta utility functions."""

    def test_parse_dbxrefs(self):
        """Test parsing DbXrefs column."""
        dbxref_string = (
            "COG:COG0178, EC:3.1.25.-, GO:0003677, GO:0005524, KEGG:K19746, "
            "RefSeq:WP_016449348.1, UniRef:UniRef50_Q8EUL1"
        )
        annotations = parse_dbxrefs(dbxref_string)

        self.assertIn("GO:0003677", annotations["go"])
        self.assertIn("GO:0005524", annotations["go"])
        self.assertIn("EC:3.1.25.-", annotations["ec"])
        self.assertIn("COG:COG0178", annotations["cog"])
        self.assertIn("KEGG:K19746", annotations["kegg"])
        self.assertIn("WP_016449348.1", annotations["refseq"])
        self.assertIn("UniRef50_Q8EUL1", annotations["uniref"])

    def test_parse_dbxrefs_empty(self):
        """Test parsing empty DbXrefs."""
        annotations = parse_dbxrefs("")
        self.assertEqual(len(annotations["go"]), 0)
        self.assertEqual(len(annotations["ec"]), 0)

    def test_create_gene_id(self):
        """Test creating composite gene ID."""
        gene_id = create_gene_id("SAMN00139461", "JEECHJ_00005")
        self.assertEqual(gene_id, "SAMN00139461:JEECHJ_00005")

    def test_get_protein_id_refseq(self):
        """Test getting protein ID preferring RefSeq."""
        annotations = {
            "refseq": ["WP_016449348.1"],
            "uniref": ["UniRef50_Q8EUL1", "UniRef90_A0A031HEP6"],
        }
        protein_id = get_protein_id(annotations, prefer_refseq=True)
        self.assertEqual(protein_id, "RefSeq:WP_016449348.1")

    def test_get_protein_id_uniref_fallback(self):
        """Test getting protein ID falling back to UniRef."""
        annotations = {
            "refseq": [],
            "uniref": ["UniRef50_Q8EUL1", "UniRef90_A0A031HEP6"],
        }
        protein_id = get_protein_id(annotations, prefer_refseq=True)
        self.assertEqual(protein_id, "UniRef:UniRef50_Q8EUL1")

    def test_get_protein_id_none(self):
        """Test getting protein ID when none available."""
        annotations = {"refseq": [], "uniref": []}
        protein_id = get_protein_id(annotations)
        self.assertIsNone(protein_id)

    def test_get_biolink_category_for_go(self):
        """Test mapping GO aspect to Biolink category."""
        self.assertEqual(
            get_biolink_category_for_go("molecular_function"),
            "biolink:MolecularActivity",
        )
        self.assertEqual(
            get_biolink_category_for_go("biological_process"),
            "biolink:BiologicalProcess",
        )
        self.assertEqual(
            get_biolink_category_for_go("cellular_component"),
            "biolink:CellularComponent",
        )

    def test_get_biolink_predicate_for_go(self):
        """Test mapping GO aspect to Biolink predicate."""
        predicate, relation = get_biolink_predicate_for_go("molecular_function")
        self.assertEqual(predicate, "biolink:enables")
        self.assertEqual(relation, "RO:0002327")

        predicate, relation = get_biolink_predicate_for_go("biological_process")
        self.assertEqual(predicate, "biolink:involved_in")
        self.assertEqual(relation, "RO:0002331")

        predicate, relation = get_biolink_predicate_for_go("cellular_component")
        self.assertEqual(predicate, "biolink:located_in")
        self.assertEqual(relation, "RO:0001025")

    def test_parse_bakta_tsv(self):
        """Test parsing Bakta TSV file."""
        test_file = Path("tests/resources/bakta/SAMN_test.bakta.tsv")

        if not test_file.exists():
            self.skipTest(f"Test file not found: {test_file}")

        genes = parse_bakta_tsv(test_file, feature_types={"cds"})

        # Should have 4 CDS features in the test file
        self.assertEqual(len(genes), 4)

        # Check first gene
        first_gene = genes[0]
        self.assertEqual(first_gene["Locus Tag"], "TEST_00001")
        self.assertEqual(first_gene["Gene"], "tatA")
        self.assertIn("GO:0006605", first_gene["DbXrefs"])


class TestBaktaTransform(unittest.TestCase):

    """Test BaktaTransform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.output_dir = tempfile.mkdtemp()
        self.transform = BaktaTransform(input_dir="tests/resources", output_dir=self.output_dir)

    def test_init(self):
        """Test BaktaTransform initialization."""
        self.assertEqual(self.transform.source_name, "bakta")
        self.assertIsNotNone(self.transform.go_adapter)
        self.assertIsNotNone(self.transform.samn_to_ncbitaxon)

    def test_get_organism_id_fallback(self):
        """Test getting organism ID with SAMN fallback."""
        organism_id = self.transform.get_organism_id("SAMN00139461")

        # Without mapping, should fall back to SAMN ID
        if "SAMN00139461" not in self.transform.samn_to_ncbitaxon:
            self.assertEqual(organism_id, "SAMN:00139461")

    def test_add_gene_node(self):
        """Test adding gene node."""
        annotations = {"refseq": ["WP_016449348.1"], "uniparc": ["UPI0002D4BAF4"]}

        self.transform.add_gene_node(
            "SAMN00139461:TEST_00001", "uvrA", "Excinuclease ABC subunit UvrA", annotations
        )

        self.assertEqual(len(self.transform.nodes), 1)
        node = self.transform.nodes[0]
        self.assertEqual(node["id"], "SAMN00139461:TEST_00001")
        self.assertEqual(node["category"], "biolink:Gene")
        self.assertEqual(node["name"], "uvrA")

    def test_add_protein_node(self):
        """Test adding protein node."""
        annotations = {
            "refseq": ["WP_016449348.1"],
            "uniref": ["UniRef50_Q8EUL1", "UniRef90_A0A031HEP6"],
        }

        self.transform.add_protein_node(
            "RefSeq:WP_016449348.1", "Excinuclease ABC subunit UvrA", annotations
        )

        self.assertEqual(len(self.transform.nodes), 1)
        node = self.transform.nodes[0]
        self.assertEqual(node["id"], "RefSeq:WP_016449348.1")
        self.assertEqual(node["category"], "biolink:Protein")

    def test_add_edge(self):
        """Test adding edge."""
        self.transform.add_edge(
            "SAMN00139461:TEST_00001",
            "biolink:has_gene_product",
            "RefSeq:WP_016449348.1",
            "RO:0002205",
        )

        self.assertEqual(len(self.transform.edges), 1)
        edge = self.transform.edges[0]
        self.assertEqual(edge["subject"], "SAMN00139461:TEST_00001")
        self.assertEqual(edge["predicate"], "biolink:has_gene_product")
        self.assertEqual(edge["object"], "RefSeq:WP_016449348.1")
        self.assertEqual(edge["relation"], "RO:0002205")


if __name__ == "__main__":
    unittest.main()
