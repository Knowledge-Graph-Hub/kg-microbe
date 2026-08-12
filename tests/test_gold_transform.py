"""Tests for the GOLD validating passthrough transform."""

import csv
import os
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.gold.gold import GOLDTransform

NODE_ROWS = [
    # id, category, name, provided_by, xref
    ("gold:Ga1", "biolink:IndividualOrganism", "microbe org", "infores:gold", "x1"),
    ("gold:Ga2", "biolink:IndividualOrganism", "virus org", "infores:gold", "x2"),
    ("NCBITaxon:1", "biolink:OrganismTaxon", "a microbe", "infores:gold", ""),
    ("NCBITaxon:99", "biolink:OrganismTaxon", "a virus", "infores:gold", ""),
    ("gold:Gs1", "biolink:Study", "study with a microbe", "infores:gold", ""),
    ("gold:Gs2", "biolink:Study", "study with only a virus", "infores:gold", ""),
    ("gold.ecosystem:E1", "biolink:EnvironmentalFeature", "soil", "infores:gold", ""),
    ("gold.ecosystem:E2", "biolink:EnvironmentalFeature", "terrestrial", "infores:gold", ""),
    ("gold:Gm1", "biolink:MaterialSample", "orphan sample", "infores:gold", ""),
]
EDGE_ROWS = [
    # id, subject, predicate, object, relation, primary_knowledge_source
    ("e1", "gold:Ga1", "biolink:in_taxon", "NCBITaxon:1", "RO:0002162", "infores:gold"),
    ("e2", "gold:Ga2", "biolink:in_taxon", "NCBITaxon:99", "RO:0002162", "infores:gold"),
    ("e3", "gold:Ga1", "biolink:related_to", "gold:Gs1", "RO:0002324", "infores:gold"),
    ("e4", "gold:Ga2", "biolink:related_to", "gold:Gs2", "RO:0002324", "infores:gold"),
    ("e5", "gold:Ga1", "biolink:occurs_in", "gold.ecosystem:E1", "RO:0002231", "infores:gold"),
    ("e6", "gold.ecosystem:E1", "biolink:subclass_of", "gold.ecosystem:E2", "rdfs:subClassOf", "infores:gold"),
]


def _write(path, header, rows):
    """Write a TSV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def _read(path):
    """Read a TSV into dicts."""
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class GoldTransformTest(TestCase):

    """GOLD arrives KGX-shaped; the transform conforms it and applies our trim."""

    def setUp(self):
        """Build a raw GOLD payload and a trimmed NCBITaxon output."""
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        _write(
            self.tmp / "raw" / "gold" / "GOLD_nodes.tsv", ["id", "category", "name", "provided_by", "xref"], NODE_ROWS
        )
        _write(
            self.tmp / "raw" / "gold" / "GOLD_edges.tsv",
            ["id", "subject", "predicate", "object", "relation", "primary_knowledge_source"],
            EDGE_ROWS,
        )
        # NCBITaxon:99 is absent — it stands for the excluded branches (viruses,
        # plants, metazoa) that exclusion_branches.tsv removes.
        _write(
            self.tmp / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv",
            ["id", "category", "name"],
            [("NCBITaxon:1", "biolink:OrganismTaxon", "a microbe")],
        )
        self.transform = GOLDTransform(input_dir=self.tmp / "raw", output_dir=self.tmp / "transformed")

    def _run(self):
        """Run the transform and return (nodes, edges)."""
        self.transform.run()
        return _read(self.transform.output_node_file), _read(self.transform.output_edge_file)

    def test_excluded_branch_taxa_and_their_organisms_are_dropped(self):
        """
        GOLD covers all of life; KG-Microbe is microbial.

        Ingesting it unfiltered reintroduced 23,695 taxa the ontologies transform
        had removed, plus the 76,034 organisms typed to them — silently undoing
        the trim.
        """
        nodes, edges = self._run()
        ids = {n["id"] for n in nodes}

        self.assertNotIn("NCBITaxon:99", ids, "an excluded taxon must not survive")
        self.assertNotIn("gold:Ga2", ids, "nor an organism typed to it")
        self.assertIn("NCBITaxon:1", ids)
        self.assertIn("gold:Ga1", ids)
        self.assertNotIn("e2", {e.get("id") for e in edges})
        for edge in edges:
            self.assertNotIn("NCBITaxon:99", (edge["subject"], edge["object"]))

    def test_nodes_orphaned_by_the_trim_are_cleaned_up(self):
        """
        A study holding only excluded organisms asserts nothing.

        That orphaning is caused by our filter, so we clean it; upstream orphans
        are a modelling question for GOLD and are kept.
        """
        nodes, _ = self._run()
        ids = {n["id"] for n in nodes}

        self.assertNotIn("gold:Gs2", ids, "a study left empty by the trim should go")
        self.assertIn("gold:Gs1", ids, "a study that still has a microbe stays")
        self.assertIn("gold:Gm1", ids, "an upstream orphan is reported, not dropped")

    def test_no_dangling_endpoints_survive(self):
        """Every surviving edge must resolve to a surviving node."""
        nodes, edges = self._run()
        ids = {n["id"] for n in nodes}
        for edge in edges:
            self.assertIn(edge["subject"], ids)
            self.assertIn(edge["object"], ids)

    def test_schema_is_conformed(self):
        """Upstream lacks the knowledge columns and carries an edge id we drop."""
        nodes, edges = self._run()
        self.assertEqual(list(nodes[0].keys()), self.transform.node_header)
        self.assertEqual(list(edges[0].keys()), self.transform.edge_header)
        self.assertNotIn("id", edges[0])
        self.assertTrue(all(e["knowledge_level"] == "knowledge_assertion" for e in edges))
        self.assertTrue(all(e["agent_type"] == "manual_agent" for e in edges))

    def test_ecosystem_nodes_become_ontology_classes(self):
        """`subclass_of` requires OntologyClass on both ends, or it violates Biolink."""
        nodes, _ = self._run()
        eco = [n for n in nodes if n["id"].startswith("gold.ecosystem:")]
        self.assertTrue(eco)
        for node in eco:
            self.assertIn("biolink:OntologyClass", node["category"])

    def test_the_trim_can_be_disabled_but_never_skipped_silently(self):
        """
        Opting out is explicit; a missing ontologies output is fatal.

        Skipping the trim because the input happened to be absent would
        reintroduce every excluded branch with nothing to show it had happened.
        """
        os.environ["GOLD_APPLY_TAXON_TRIM"] = "false"
        try:
            nodes, _ = self._run()
            self.assertIn("NCBITaxon:99", {n["id"] for n in nodes}, "opt-out must emit unfiltered")
        finally:
            del os.environ["GOLD_APPLY_TAXON_TRIM"]

        (self.tmp / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv").unlink()
        with self.assertRaises(FileNotFoundError):
            self.transform.run()

    def test_an_empty_trim_source_is_refused_rather_than_emptying_the_graph(self):
        """
        An empty permitted set is a broken input, not a configuration.

        It makes every GOLD taxon "excluded", drops every organism typed to one,
        and cascades to an empty graph reported as a successful run. Measured on a
        3-taxon fixture before the guard: 6 nodes / 3 edges became 0 / 0, exit 0.

        Header-only derived files are a known failure mode here — atomic_io exists
        for it — and the ontologies output predates that work, so it carries no
        completion marker to check.
        """
        (self.tmp / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv").write_text("id\tcategory\tname\n")
        with self.assertRaises(ValueError) as ctx:
            GOLDTransform(input_dir=self.tmp / "raw", output_dir=self.tmp / "transformed").run()
        self.assertIn("NCBITaxon:", str(ctx.exception))

    def test_a_trim_source_with_rows_but_no_taxa_is_also_refused(self):
        """
        Non-empty is not enough — the rows have to be taxa.

        A truncation leaving some other prefix behind, or the wrong ontology's
        node file at that path, would pass a bare emptiness check and still
        exclude every GOLD taxon.
        """
        _write(
            self.tmp / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv",
            ["id", "category", "name"],
            [("CHEBI:15377", "biolink:SmallMolecule", "water")],
        )
        with self.assertRaises(ValueError) as ctx:
            GOLDTransform(input_dir=self.tmp / "raw", output_dir=self.tmp / "transformed").run()
        self.assertIn("NCBITaxon:", str(ctx.exception))

    def test_a_populated_trim_source_still_works(self):
        """The guard must not reject the ordinary case it was added to protect."""
        transform = GOLDTransform(input_dir=self.tmp / "raw", output_dir=self.tmp / "transformed")
        transform.run()
        nodes = {row["id"] for row in _read(transform.output_node_file)}
        self.assertIn("NCBITaxon:1", nodes)
        self.assertNotIn("NCBITaxon:99", nodes, "the excluded branch must still be trimmed")
