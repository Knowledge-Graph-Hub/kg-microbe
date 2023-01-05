"""Test the traits transform."""

import os
import unittest

import pandas as pd
from parameterized import parameterized

from kg_microbe.transform_utils.traits import TraitsTransform
from kg_microbe.transform_utils.traits.traits import parse_line
from kg_microbe.utils.transform_utils import parse_header


class TestTraits(unittest.TestCase):
    """Test the traits transformation."""

    def setUp(self) -> None:
        """Set up the transformation test."""
        self.resources = "tests/resources/"
        self.input_dir = os.path.join(self.resources, "traits/input/")
        self.output_dir = os.path.join(self.resources, "traits/output/")
        self.nlp_dir = os.path.join(self.resources, "traits/nlp/")
        self.nlp_input_dir = os.path.join(self.nlp_dir, "terms")
        self.nlp_output_dir = os.path.join(self.nlp_dir, "input")
        self.nlp_terms_dir = os.path.join(self.nlp_dir, "output")
        self.nlp_stopwords_dir = os.path.join(self.nlp_dir, "stopwords")
        self.test_file = "trait_test.tsv"
        self.trait_fh = open(os.path.join(self.input_dir, self.test_file), "rt")
        self.traits_output_dir = os.path.join(self.output_dir, "condensed_traits_NCBI/")
        self.traits = TraitsTransform(
            input_dir=self.input_dir, output_dir=self.output_dir
        )
        self.traits.nlp_dir = self.traits.nlp_dir
        self.traits.nlp_input_dir = self.traits.nlp_input_dir
        self.traits.nlp_output_dir = self.traits.nlp_output_dir
        self.traits.nlp_terms_dir = self.traits.nlp_terms_dir
        self.traits.nlp_stopwords_dir = self.traits.nlp_stopwords_dir

    @parameterized.expand(
        [
            ("species_tax_id", "256826"),
            ("data_source", "methanogen"),
            ("org_name", "Methanobacterium aarhusense"),
            ("species", "Methanobacterium aarhusense"),
            ("genus", "Methanobacterium"),
            ("family", "Methanobacteriaceae"),
            ("order", "Methanobacteriales"),
            ("class", "Methanobacteria"),
            ("phylum", "Euryarchaeota"),
            ("superkingdom", "Archaea"),
            ("gram_stain", "positive"),
            ("metabolism", "anaerobic"),
            ("pathways", "methanogenesis"),
            ("carbon_substrates", "H2_CO2"),
            ("sporulation", "NA"),
            ("motility", "no"),
            ("range_tmp", "NA"),
            ("range_salinity", "NA"),
            ("cell_shape", "bacillus"),
            ("isolation_source", "NA"),
            ("d1_lo", "0.7"),
            ("d1_up", "0.7"),
            ("d2_lo", "5"),
            ("d2_up", "18"),
            ("doubling_h", "NA"),
            ("genome_size", "NA"),
            ("gc_content", "NA"),
            ("coding_genes", "NA"),
            ("optimum_tmp", "45"),
            ("optimum_ph", "7.75"),
            ("growth_tmp", "NA"),
            ("rRNA16S_genes", "NA"),
            ("tRNA_genes", "NA"),
            ("ref_id", "19751"),
        ]
    )
    def test_parse_traits_line(self, key, value):
        """Test parsing traits line."""
        header = parse_header(self.trait_fh.readline())
        line = self.trait_fh.readline()
        parsed = parse_line(line, header, sep="\t")
        self.assertTrue(key in parsed)
        self.assertEqual(value, parsed[key])

    def test_run(self):
        """Test running the transformation."""
        self.assertTrue(isinstance(self.traits.run, object))
        self.traits.run(data_file=self.test_file)
        self.assertTrue(os.path.isdir(self.traits_output_dir))

    def test_nodes_file(self):
        """Test structure of the nodes file."""
        self.traits.run(data_file=self.test_file)
        node_file = os.path.join(self.traits_output_dir, "nodes.tsv")
        self.assertTrue(os.path.isfile(node_file))
        node_df = pd.read_csv(node_file, sep="\t", header=0)
        self.assertEqual((36, 3), node_df.shape)
        self.assertEqual(["id", "name", "category"], list(node_df.columns))

    def test_nodes_are_not_repeated(self):
        """Test that nodes are not repeated."""
        self.traits.run(data_file=self.test_file)
        node_file = os.path.join(self.traits_output_dir, "nodes.tsv")
        node_df = pd.read_csv(node_file, sep="\t", header=0)
        nodes = list(node_df.id)
        unique_nodes = list(set(nodes))
        self.assertCountEqual(nodes, unique_nodes)

    def test_edges_file(self, *args):
        """Test structure of the edges file."""
        self.traits.run(data_file=self.test_file)
        edge_file = os.path.join(self.traits_output_dir, "edges.tsv")
        self.assertTrue(os.path.isfile(edge_file))
        edge_df = pd.read_csv(edge_file, sep="\t", header=0)
        self.assertEqual((66, 4), edge_df.shape)
        self.assertEqual(
            ["subject", "predicate", "object", "relation"], list(edge_df.columns)
        )
