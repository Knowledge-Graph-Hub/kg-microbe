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


class HouseConventionTest(TestCase):

    """One graph, one way of saying "this named entity sits under this taxon"."""

    def setUp(self):
        """Run the fixture once."""
        self.nodes, self.edges = _run()

    def test_the_taxon_link_is_subclass_of_not_in_taxon(self):
        """
        GOLD was the lone dialect: 531,324 `in_taxon` against 1,177,321 `subclass_of`.

        NCBITaxon's own hierarchy (925,219), bacdive's strains (251,916) and
        metatraits (186) all use `subclass_of`. A query walking `subclass_of`
        down from a species found bacdive's strains and silently missed every
        GOLD organism — the concrete cost of the split, and the reason this is
        a correctness fix rather than a cosmetic one.
        """
        taxon_edges = [e for e in self.edges if e["object"].startswith("NCBITaxon:")]
        self.assertTrue(taxon_edges)
        self.assertEqual({e["predicate"] for e in taxon_edges}, {"biolink:subclass_of"})
        self.assertEqual({e["relation"] for e in taxon_edges}, {"rdfs:subClassOf"})

    def test_no_in_taxon_edge_survives(self):
        """The upstream predicate must not leak through any path."""
        self.assertEqual([e for e in self.edges if e["predicate"] == "biolink:in_taxon"], [])

    def test_organism_nodes_are_retyped_to_match(self):
        """
        The category has to move with the predicate.

        `biolink:IndividualOrganism` is the honest type for an isolate read on
        its own, but an individual cannot be the subject of `subclass_of`
        without inventing a fourth dialect. bacdive types its 251,404 strains
        `biolink:OrganismTaxon` for the same reason.
        """
        strain = next(n for n in self.nodes if n["id"] == "gold:strain")
        self.assertEqual(strain["category"], "biolink:OrganismTaxon")
        self.assertNotIn("biolink:IndividualOrganism", {n["category"] for n in self.nodes})


class OrganismFoldTest(TestCase):

    """An organism node has to earn its place by carrying a name the taxon lacks."""

    def setUp(self):
        """Run the fixture once."""
        self.nodes, self.edges = _run()
        self.ids = {n["id"] for n in self.nodes}

    def test_an_organism_naming_a_strain_keeps_its_node(self):
        """
        88.8% of the real payload is this case, and it is the layer's whole value.

        "Methanococcoides sp. FTZ1" under the genus `NCBITaxon:2225` is
        strain-level identity the taxon cannot carry.
        """
        self.assertIn("gold:strain", self.ids)

    def test_an_organism_named_as_its_taxon_folds_into_it(self):
        """
        11.2% of the payload is a second identifier for a thing already present.

        It contributes an id and an edge and nothing a query can use.
        """
        self.assertNotIn("gold:same", self.ids)

    def test_the_folded_organism_donates_its_environment_to_the_taxon(self):
        """
        Folding must move the evidence, not discard it.

        This is the difference between the fold and a plain drop: GOLD observed
        that organism in soil, and after the fold the taxon says so.
        """
        located = [e for e in self.edges if e["predicate"] == "biolink:located_in"]
        self.assertIn(("NCBITaxon:2225", "gold.ecosystem:soil"), {(e["subject"], e["object"]) for e in located})

    def test_folding_creates_no_self_referential_edge(self):
        """`X subclass_of X` is what the organism's own taxon edge becomes."""
        self.assertEqual([e for e in self.edges if e["subject"] == e["object"]], [])

    def test_re_pointing_does_not_duplicate_a_triple(self):
        """
        Two isolates of one taxon in one environment collapse to one statement.

        The upstream export carries no duplicate triples at all, so any
        duplicate in the output would be ours — on the real payload the fold
        creates 604 and this removes them.
        """
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

    def test_a_taxon_left_with_nothing_to_say_stops_being_emitted(self):
        """
        Second-order effect, and a desirable one.

        `NCBITaxon:999`'s only tie to GOLD was a redundant organism carrying no
        environment. Once folded, GOLD asserts nothing about that taxon, so
        emitting a row for it duplicates what the ontologies transform already
        supplies. On the real payload this is 25,288 rows, none of which carried
        an xref, description or synonym, and all of which are in the trimmed
        NCBITaxon extract — so nothing is lost.
        """
        self.assertNotIn("NCBITaxon:999", self.ids)
        self.assertIn("NCBITaxon:2225", self.ids)

    def test_the_fold_is_decided_on_the_name_not_the_rank(self):
        """
        An organism named for its genus is as redundant as one named for a species.

        Keying on rank or id shape instead would keep `gold:same` — named
        exactly "Methanococcoides", a genus — while the name is the only thing
        the organism layer contributes.
        """
        self.assertNotIn("gold:same", self.ids)
        self.assertIn("gold:strain", self.ids)

    def test_case_and_whitespace_alone_do_not_block_the_fold(self):
        """A label differing only in spacing names the same thing."""
        nodes = [r[:] for r in NODES]
        nodes[2] = ["gold:same", "biolink:IndividualOrganism", "  methanococcoides "]
        ids = {n["id"] for n in _run(nodes=nodes)[0]}
        self.assertNotIn("gold:same", ids)


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
