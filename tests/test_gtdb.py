"""Test GTDB transform."""

import tempfile
import unittest
from pathlib import Path

from kg_microbe.transform_utils.gtdb.gtdb import GTDBTransform
from kg_microbe.transform_utils.gtdb.utils import (
    clean_taxon_name,
    extract_accession_type,
    parse_taxonomy_string,
)


class TestGTDBUtils(unittest.TestCase):

    """Test GTDB utility functions."""

    def test_parse_taxonomy_string(self):
        """Test parsing GTDB taxonomy string."""
        taxonomy_str = (
            "d__Bacteria;p__Proteobacteria;c__Gammaproteobacteria;"
            "o__Enterobacterales;f__Enterobacteriaceae;g__Escherichia;s__Escherichia coli"
        )
        taxa = parse_taxonomy_string(taxonomy_str)

        self.assertEqual(len(taxa), 7)
        self.assertEqual(taxa[0], "d__Bacteria")
        self.assertEqual(taxa[1], "p__Proteobacteria")
        self.assertEqual(taxa[-1], "s__Escherichia coli")

    def test_parse_taxonomy_string_empty(self):
        """Test parsing empty taxonomy string."""
        taxa = parse_taxonomy_string("")
        self.assertEqual(len(taxa), 0)

    def test_extract_accession_type_gcf(self):
        """Test extracting GCF accession."""
        base, version = extract_accession_type("GCF_000005845.2")
        self.assertEqual(base, "GCF_000005845")
        self.assertEqual(version, "2")

    def test_extract_accession_type_gca(self):
        """Test extracting GCA accession."""
        base, version = extract_accession_type("GCA_000008865.2")
        self.assertEqual(base, "GCA_000008865")
        self.assertEqual(version, "2")

    def test_extract_accession_type_no_version(self):
        """Test extracting accession without version."""
        base, version = extract_accession_type("GCF_000005845")
        self.assertEqual(base, "GCF_000005845")
        self.assertEqual(version, "1")

    def test_extract_accession_type_rs_prefix(self):
        """Test extracting accession with RS_ prefix."""
        base, version = extract_accession_type("RS_GCF_000005845.2")
        self.assertEqual(base, "GCF_000005845")
        self.assertEqual(version, "2")

    def test_extract_accession_type_gb_prefix(self):
        """Test extracting accession with GB_ prefix."""
        base, version = extract_accession_type("GB_GCA_000008865.2")
        self.assertEqual(base, "GCA_000008865")
        self.assertEqual(version, "2")

    def test_clean_taxon_name(self):
        """Test cleaning taxon name."""
        self.assertEqual(clean_taxon_name("s__Escherichia coli"), "s__Escherichia_coli")
        self.assertEqual(clean_taxon_name("d__Bacteria"), "d__Bacteria")
        self.assertEqual(
            clean_taxon_name("s__Bacillus subtilis subsp. subtilis"),
            "s__Bacillus_subtilis_subsp._subtilis",
        )


class TestGTDBTransform(unittest.TestCase):

    """Test GTDBTransform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.output_dir = tempfile.mkdtemp()
        self.test_input_dir = Path("tests/resources")
        self.transform = GTDBTransform(input_dir=str(self.test_input_dir), output_dir=self.output_dir)

    def test_init(self):
        """Test GTDBTransform initialization."""
        self.assertEqual(self.transform.source_name, "gtdb")
        self.assertEqual(self.transform.knowledge_source, "infores:gtdb")
        self.assertEqual(len(self.transform.nodes), 0)
        self.assertEqual(len(self.transform.edges), 0)
        self.assertEqual(len(self.transform.taxon_to_id), 0)
        # CURIE allocation is deterministic; no counter to assert on.
        self.assertFalse(hasattr(self.transform, "taxon_id_counter"))

    def test_parse_taxonomy_file(self):
        """Test parsing taxonomy file."""
        taxa_list = self.transform._parse_taxonomy_file("bac120_taxonomy.tsv")

        self.assertEqual(len(taxa_list), 3)

        # Check first entry
        accession, taxa = taxa_list[0]
        self.assertEqual(accession, "GCF_000005845.2")
        self.assertEqual(len(taxa), 7)
        self.assertEqual(taxa[0], "d__Bacteria")
        self.assertEqual(taxa[-1], "s__Escherichia coli")

    def test_parse_taxonomy_file_missing(self):
        """Test parsing missing taxonomy file raises error."""
        with self.assertRaises(FileNotFoundError) as context:
            self.transform._parse_taxonomy_file("nonexistent.tsv")

        self.assertIn("GTDB taxonomy file not found", str(context.exception))
        self.assertIn("Please run the GTDB downloader", str(context.exception))

    def test_get_or_create_taxon_id(self):
        """Test creating taxon CURIEs from taxon strings."""
        # First call creates new node + CURIE derived from the taxon string.
        taxon_id1 = self.transform._get_or_create_taxon_id("d__Bacteria")
        self.assertEqual(taxon_id1, "GTDB:d__Bacteria")
        self.assertIn("d__Bacteria", self.transform.taxon_to_id)
        self.assertEqual(len(self.transform.nodes), 1)

        # Second call returns same ID, no duplicate node.
        taxon_id2 = self.transform._get_or_create_taxon_id("d__Bacteria")
        self.assertEqual(taxon_id2, "GTDB:d__Bacteria")
        self.assertEqual(len(self.transform.nodes), 1)

        # Different taxon gets its own deterministic CURIE.
        taxon_id3 = self.transform._get_or_create_taxon_id("d__Archaea")
        self.assertEqual(taxon_id3, "GTDB:d__Archaea")
        self.assertEqual(len(self.transform.nodes), 2)

        # Raw taxon strings with spaces are cleaned idempotently.
        taxon_id4 = self.transform._get_or_create_taxon_id("s__Escherichia coli")
        self.assertEqual(taxon_id4, "GTDB:s__Escherichia_coli")

    def test_get_or_create_taxon_id_deterministic(self):
        """Two transform instances mint identical CURIEs for the same taxa."""
        transform1 = GTDBTransform(input_dir=str(self.test_input_dir), output_dir=self.output_dir)
        transform2 = GTDBTransform(input_dir=str(self.test_input_dir), output_dir=self.output_dir)

        # Insertion order differs between the two instances; CURIEs must not.
        a1 = transform1._get_or_create_taxon_id("s__Escherichia_coli")
        b1 = transform1._get_or_create_taxon_id("d__Bacteria")
        c1 = transform1._get_or_create_taxon_id("p__Pseudomonadota")

        c2 = transform2._get_or_create_taxon_id("p__Pseudomonadota")
        a2 = transform2._get_or_create_taxon_id("s__Escherichia_coli")
        b2 = transform2._get_or_create_taxon_id("d__Bacteria")

        self.assertEqual(a1, "GTDB:s__Escherichia_coli")
        self.assertEqual(b1, "GTDB:d__Bacteria")
        self.assertEqual(c1, "GTDB:p__Pseudomonadota")
        self.assertEqual(a1, a2)
        self.assertEqual(b1, b2)
        self.assertEqual(c1, c2)

    def test_add_node(self):
        """Test adding node."""
        self.transform._add_node(
            node_id="GTDB:1",
            category="biolink:OrganismTaxon",
            name="d__Bacteria",
            description="GTDB domain Bacteria",
        )

        self.assertEqual(len(self.transform.nodes), 1)
        node = self.transform.nodes[0]
        self.assertEqual(node["id"], "GTDB:1")
        self.assertEqual(node["category"], "biolink:OrganismTaxon")
        self.assertEqual(node["name"], "d__Bacteria")
        self.assertEqual(node["provided_by"], "infores:gtdb")

    def test_add_node_dedup(self):
        """Test adding duplicate node is prevented."""
        self.transform._add_node(
            node_id="GTDB:1",
            category="biolink:OrganismTaxon",
            name="d__Bacteria",
        )
        self.transform._add_node(
            node_id="GTDB:1",
            category="biolink:OrganismTaxon",
            name="d__Bacteria",
        )

        self.assertEqual(len(self.transform.nodes), 1)

    def test_add_edge(self):
        """Test adding edge."""
        self.transform._add_edge(
            subject="GTDB:100",
            predicate="biolink:subclass_of",
            obj="GTDB:50",
            relation="rdfs:subClassOf",
        )

        self.assertEqual(len(self.transform.edges), 1)
        edge = self.transform.edges[0]
        self.assertEqual(edge["subject"], "GTDB:100")
        self.assertEqual(edge["predicate"], "biolink:subclass_of")
        self.assertEqual(edge["object"], "GTDB:50")
        self.assertEqual(edge["relation"], "rdfs:subClassOf")
        self.assertEqual(edge["primary_knowledge_source"], "infores:gtdb")

    def test_create_genome_node(self):
        """Test creating genome node with edges."""
        # First create the taxon
        self.transform._get_or_create_taxon_id("s__Escherichia_coli")

        # Create genome node
        self.transform._create_genome_node(
            accession="GCF_000005845.2",
            gtdb_taxon="s__Escherichia_coli",
            ncbi_taxid="562",
        )

        # Should have 2 nodes: taxon + genome
        self.assertEqual(len(self.transform.nodes), 2)
        genome_node = [n for n in self.transform.nodes if n["id"].startswith("GenBank:")][0]
        self.assertEqual(genome_node["id"], "GenBank:GCF_000005845")
        self.assertEqual(genome_node["category"], "biolink:Genome")
        self.assertEqual(genome_node["name"], "GCF_000005845.2")

        # Should have 2 edges: genome->taxon and taxon->NCBITaxon
        self.assertEqual(len(self.transform.edges), 2)

        # Check genome->taxon edge
        genome_edge = [e for e in self.transform.edges if e["subject"].startswith("GenBank:")][0]
        self.assertEqual(genome_edge["predicate"], "biolink:subclass_of")
        self.assertEqual(genome_edge["object"], "GTDB:s__Escherichia_coli")

        # Check taxon->NCBI edge
        ncbi_edge = [e for e in self.transform.edges if e["object"].startswith("NCBITaxon:")][0]
        self.assertEqual(ncbi_edge["predicate"], "biolink:close_match")
        self.assertEqual(ncbi_edge["object"], "NCBITaxon:562")
        self.assertEqual(ncbi_edge["relation"], "skos:closeMatch")

    def test_create_genome_node_no_ncbi(self):
        """Test creating genome node without NCBI mapping."""
        self.transform._get_or_create_taxon_id("s__Escherichia_coli")

        self.transform._create_genome_node(
            accession="GCF_000005845.2",
            gtdb_taxon="s__Escherichia_coli",
            ncbi_taxid=None,
        )

        # Should only have 1 edge: genome->taxon (no NCBI mapping)
        self.assertEqual(len(self.transform.edges), 1)
        self.assertEqual(self.transform.edges[0]["predicate"], "biolink:subclass_of")

    def test_build_taxonomy_hierarchy(self):
        """Test building taxonomy hierarchy."""
        taxa_list = [
            ("GCF_000005845.2", ["d__Bacteria", "p__Pseudomonadota", "c__Gammaproteobacteria"]),
            ("GCA_000008865.2", ["d__Bacteria", "p__Bacillota", "c__Bacilli"]),
        ]

        self.transform._build_taxonomy_hierarchy(taxa_list)

        # Should create nodes for: Bacteria, Pseudomonadota, Gammaproteobacteria, Bacillota, Bacilli = 5
        self.assertEqual(len(self.transform.nodes), 5)

        # Should create hierarchy edges: 4 (Pseudomonadota->Bacteria, Gammaproteobacteria->Pseudomonadota,
        # Bacillota->Bacteria, Bacilli->Bacillota)
        self.assertEqual(len(self.transform.edges), 4)

        # All edges should be subclass_of
        for edge in self.transform.edges:
            self.assertEqual(edge["predicate"], "biolink:subclass_of")
            self.assertEqual(edge["relation"], "rdfs:subClassOf")


if __name__ == "__main__":
    unittest.main()
