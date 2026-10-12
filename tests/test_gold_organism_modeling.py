"""GOLD's organism layer uses the graph's own conventions, and earns its nodes."""

import csv
import io
import os
import tarfile
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.gold.gold import GOLDTransform

# Three organisms under two taxa, covering the cases that decide the fold:
#  - `strain` carries a strain designation the taxon cannot -> keeps its node
#  - `same` is named exactly as its taxon -> folds into it
#  - `bare` is named as its taxon too, and carries no environment -> folds, and
#    leaves the taxon with nothing, so GOLD stops emitting a row for it
NODES = [
    ["id", "category", "name"],
    ["gold:strain", "biolink:IndividualOrganism", "Methanococcoides sp. FTZ1"],
    ["gold:same", "biolink:IndividualOrganism", "Methanococcoides"],
    ["gold:bare", "biolink:IndividualOrganism", "Solitary taxon"],
    ["gold:nameless", "biolink:IndividualOrganism", ""],
    ["NCBITaxon:2225", "biolink:OrganismTaxon", "Methanococcoides"],
    ["NCBITaxon:999", "biolink:OrganismTaxon", "Solitary taxon"],
    ["gold.ecosystem:soil", "biolink:EnvironmentalFeature", "Soil"],
]
EDGES = [
    ["subject", "predicate", "object", "relation"],
    ["gold:strain", "biolink:in_taxon", "NCBITaxon:2225", "gold:organism_v2.ncbi_taxonomy_id"],
    ["gold:same", "biolink:in_taxon", "NCBITaxon:2225", "gold:organism_v2.ncbi_taxonomy_id"],
    ["gold:bare", "biolink:in_taxon", "NCBITaxon:999", "gold:organism_v2.ncbi_taxonomy_id"],
    ["gold:nameless", "biolink:in_taxon", "NCBITaxon:2225", "gold:organism_v2.ncbi_taxonomy_id"],
    ["gold:strain", "biolink:occurs_in", "gold.ecosystem:soil", "RO:0002451"],
    ["gold:same", "biolink:occurs_in", "gold.ecosystem:soil", "RO:0002451"],
]


def _run(nodes=None, edges=None):
    """
    Run the transform over a fixture and return its nodes and edges.

    :param nodes: Node rows, defaulting to the module fixture.
    :param edges: Edge rows, defaulting to the module fixture.
    :return: ``(node dicts, edge dicts)``.
    """
    tmp = Path(tempfile.mkdtemp())
    raw, out = tmp / "raw", tmp / "transformed"
    (raw / "gold").mkdir(parents=True)
    out.mkdir()
    for name, rows in (("GOLD_nodes.tsv", nodes or NODES), ("GOLD_edges.tsv", edges or EDGES)):
        with (raw / "gold" / name).open("w", newline="") as fh:
            csv.writer(fh, delimiter="\t").writerows(rows)
    data = b"1\t|\t1\t|\n"
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as tar:
        info = tarfile.TarInfo("merged.dmp")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    previous = os.environ.get("GOLD_APPLY_TAXON_TRIM")
    os.environ["GOLD_APPLY_TAXON_TRIM"] = "false"
    try:
        GOLDTransform(input_dir=raw, output_dir=out).run()
    finally:
        if previous is None:
            os.environ.pop("GOLD_APPLY_TAXON_TRIM", None)
        else:
            os.environ["GOLD_APPLY_TAXON_TRIM"] = previous
    with (out / "gold" / "nodes.tsv").open() as fh:
        node_rows = list(csv.DictReader(fh, delimiter="\t"))
    with (out / "gold" / "edges.tsv").open() as fh:
        edge_rows = list(csv.DictReader(fh, delimiter="\t"))
    return node_rows, edge_rows


class UnverifiedReferentTest(TestCase):
    """A plausible strain-like label is not independent native strain evidence."""

    def setUp(self):
        """Run the fixture once."""
        self.nodes, self.edges = _run()

    def test_the_taxon_link_is_related_to_without_class_inheritance(self):
        """The source taxonomy field cannot establish universal taxon-class inheritance."""
        taxon_edges = [e for e in self.edges if e["object"].startswith("NCBITaxon:")]
        self.assertTrue(taxon_edges)
        self.assertEqual({e["predicate"] for e in taxon_edges}, {"biolink:related_to"})
        self.assertEqual({e["relation"] for e in taxon_edges}, {"gold:organism_v2.ncbi_taxonomy_id"})

    def test_no_in_taxon_edge_survives(self):
        """The upstream predicate must not leak through any path."""
        self.assertEqual([e for e in self.edges if e["predicate"] == "biolink:in_taxon"], [])

    def test_organism_nodes_are_retyped_to_match(self):
        """A strain-like name is not independently verified strain evidence."""
        strain = next(n for n in self.nodes if n["id"] == "gold:strain")
        self.assertEqual(strain["category"], "biolink:NamedThing")
        self.assertNotIn("biolink:IndividualOrganism", {n["category"] for n in self.nodes})


class OrganismFoldTest(TestCase):
    """Retain source records and observations despite historical lexical equality."""

    def setUp(self):
        """Run the fixture once."""
        self.nodes, self.edges = _run()
        self.ids = {n["id"] for n in self.nodes}

    def test_an_organism_naming_a_strain_keeps_its_node(self):
        """A differing literal source name remains without asserting strain identity."""
        self.assertIn("gold:strain", self.ids)

    def test_an_organism_named_as_its_taxon_keeps_its_source_id(self):
        """Equal labels do not establish source referent identity."""
        self.assertIn("gold:same", self.ids)

    def test_original_source_referent_owns_its_environment(self):
        """The record's native observation does not become a general taxon-level statement."""
        located = [e for e in self.edges if e["predicate"] == "biolink:located_in"]
        self.assertIn(("gold:same", "gold.ecosystem:soil"), {(e["subject"], e["object"]) for e in located})
        self.assertNotIn(("NCBITaxon:2225", "gold.ecosystem:soil"), {(e["subject"], e["object"]) for e in located})

    def test_folding_creates_no_self_referential_edge(self):
        """Keeping source identifiers distinct does not create identity self-edges."""
        self.assertEqual([e for e in self.edges if e["subject"] == e["object"]], [])

    def test_re_pointing_does_not_duplicate_a_triple(self):
        """Distinct source IDs conserve observations without producing duplicate triples."""
        triples = [(e["subject"], e["predicate"], e["object"]) for e in self.edges]
        self.assertEqual(len(triples), len(set(triples)))

    def test_a_nameless_organism_is_not_folded(self):
        """
        Absence of a name is not evidence of redundancy.

        We cannot tell whether it duplicates the taxon, so it keeps its node —
        the same fail-closed reasoning the rest of this repo applies to
        unresolvable rows.
        """
        self.assertIn("gold:nameless", self.ids)

    def test_restored_source_association_keeps_its_native_taxon_endpoint(self):
        """A record with no habitat still carries a native taxon association requiring closure."""
        self.assertIn("NCBITaxon:999", self.ids)
        self.assertIn("NCBITaxon:2225", self.ids)

    def test_neither_name_nor_rank_proves_identity(self):
        """A genus-like source label is still not evidence that the source ID is the taxon."""
        self.assertIn("gold:same", self.ids)
        self.assertIn("gold:strain", self.ids)

    def test_case_and_whitespace_do_not_authorize_a_fold(self):
        """Lexical normalization cannot establish semantic identity."""
        nodes = [r[:] for r in NODES]
        nodes[2] = ["gold:same", "biolink:IndividualOrganism", "  methanococcoides "]
        ids = {n["id"] for n in _run(nodes=nodes)[0]}
        self.assertIn("gold:same", ids)


class MultiTaxonGuardTest(TestCase):
    """An organism claimed by two taxa must not be folded (#833)."""

    def setUp(self):
        """Give one organism two taxa, both matching its name."""
        self.nodes = [r[:] for r in NODES] + [
            ["NCBITaxon:777", "biolink:OrganismTaxon", "Methanococcoides"],
        ]
        self.edges = [r[:] for r in EDGES] + [
            ["gold:same", "biolink:in_taxon", "NCBITaxon:777", "gold:organism_v2.ncbi_taxonomy_id"],
        ]

    def test_no_taxon_to_taxon_subclass_of_is_invented(self):
        """
        The failure this guards is silent and lands in the backbone.

        Folding `gold:same` onto `NCBITaxon:2225` would rewrite its *other*
        taxon edge to `NCBITaxon:2225 subclass_of NCBITaxon:777` — an assertion
        GOLD never made, indistinguishable from the 925,219 real hierarchy
        edges once merged.
        """
        _, edges = _run(nodes=self.nodes, edges=self.edges)
        invented = [
            e
            for e in edges
            if e["subject"].startswith("NCBITaxon:")
            and e["object"].startswith("NCBITaxon:")
            and e["predicate"] == "biolink:subclass_of"
        ]
        self.assertEqual(invented, [])

    def test_the_multi_taxon_organism_keeps_its_node(self):
        """
        Skipping is the honest outcome, not merely the safe one.

        Two taxa for one organism is exactly the case where the organism layer
        carries something neither taxon does.
        """
        nodes, _ = _run(nodes=self.nodes, edges=self.edges)
        self.assertIn("gold:same", {n["id"] for n in nodes})
