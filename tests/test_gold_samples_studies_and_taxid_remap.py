"""GOLD: drop samples/studies, keep organism→environment, remap retired taxids."""

import csv
import io
import os
import tarfile
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.gold.gold import GOLDTransform

NODES = [
    ["id", "category", "name"],
    ["gold.organism:1", "biolink:IndividualOrganism", "Org 1"],
    # Retired row deliberately first: a naive first-wins dedup would emit
    # NCBITaxon:4914 carrying this row's stale name.
    ["NCBITaxon:262981", "biolink:OrganismTaxon", "stale retired name"],
    ["NCBITaxon:4914", "biolink:OrganismTaxon", "Lachancea waltii"],
    ["gold.sample:1", "biolink:MaterialSample", "Sample 1"],
    ["gold.study:1", "biolink:Study", "Study 1"],
    ["gold.ecosystem:1", "biolink:EnvironmentalFeature", "Soil"],
]
EDGES = [
    ["subject", "predicate", "object", "relation"],
    ["gold.organism:1", "biolink:in_taxon", "NCBITaxon:262981", "RO:0002162"],
    ["gold.organism:1", "biolink:occurs_in", "gold.ecosystem:1", "RO:0002451"],
    ["gold.organism:1", "biolink:related_to", "gold.study:1", "RO:0002610"],
    ["gold.organism:1", "biolink:derives_from", "gold.sample:1", "RO:0001000"],
]


def _build(merges="262981\t|\t4914\t|\n"):
    """Lay out a scratch raw/ tree and run the transform over it."""
    tmp = Path(tempfile.mkdtemp())
    raw, out = tmp / "raw", tmp / "transformed"
    (raw / "gold").mkdir(parents=True)
    out.mkdir()
    for name, rows in (("GOLD_nodes.tsv", NODES), ("GOLD_edges.tsv", EDGES)):
        with (raw / "gold" / name).open("w", newline="") as fh:
            csv.writer(fh, delimiter="\t").writerows(rows)
    if merges is not None:
        data = merges.encode()
        with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as tar:
            info = tarfile.TarInfo("merged.dmp")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    # Restore rather than leak: setting this unconditionally turned the trim off
    # for every later test in the session, failing five unrelated GOLD tests that
    # only pass with it on.
    previous = os.environ.get("GOLD_APPLY_TAXON_TRIM")
    os.environ["GOLD_APPLY_TAXON_TRIM"] = "false"
    try:
        GOLDTransform(input_dir=raw, output_dir=out).run()
    finally:
        if previous is None:
            os.environ.pop("GOLD_APPLY_TAXON_TRIM", None)
        else:
            os.environ["GOLD_APPLY_TAXON_TRIM"] = previous
    return out / "gold"


def _rows(path):
    """Read a written TSV as a list of rows."""
    with path.open() as fh:
        return list(csv.reader(fh, delimiter="\t"))[1:]


class DropSamplesAndStudiesTest(TestCase):

    """KG-Microbe wants neither samples nor studies — but does want environments."""

    def test_sample_and_study_nodes_are_not_emitted(self):
        """
        279,428 of GOLD's 279,670 MaterialSample nodes have no incident edge.

        Study nodes are only reachable via `related_to`, which asserts nothing
        usable.
        """
        ids = {r[0] for r in _rows(_build() / "nodes.tsv")}
        self.assertNotIn("gold.sample:1", ids)
        self.assertNotIn("gold.study:1", ids)

    def test_edges_touching_them_go_too(self):
        """Dropping the node while keeping the edge would create a dangling reference."""
        preds = {r[1] for r in _rows(_build() / "edges.tsv")}
        self.assertNotIn("biolink:related_to", preds)
        self.assertNotIn("biolink:derives_from", preds)

    def test_the_organism_to_environment_edge_survives(self):
        """
        Keep the edge the ingest exists for.

        The environment link is untouched by the sample/study removal. It is
        emitted as `located_in`, not the upstream `occurs_in`: Biolink defines
        `occurs in` for a process, and the subject here is an organism.
        """
        rows = _rows(_build() / "edges.tsv")
        env = [r for r in rows if r[1] == "biolink:located_in"]
        self.assertEqual(len(env), 1)
        self.assertEqual(env[0][2], "gold.ecosystem:1")
        self.assertFalse([r for r in rows if r[1] == "biolink:occurs_in"])

    def test_the_ecosystem_node_keeps_its_ontology_class_category(self):
        """Environment nodes still anchor a subclass_of hierarchy."""
        rows = {r[0]: r[1] for r in _rows(_build() / "nodes.tsv")}
        self.assertIn("biolink:OntologyClass", rows["gold.ecosystem:1"])


class TaxidRemapTest(TestCase):

    """NCBI merged ~950 of GOLD's taxids; judging them on the retired id loses them."""

    def test_a_retired_taxid_is_rewritten_on_the_edge(self):
        """
        `262981` was merged into `4914` (Lachancea waltii).

        The organism-to-taxon edge is emitted as `subclass_of`, not the
        upstream `in_taxon` — see `_SUBCLASS_OF` in gold.py. What this test
        pins is the remap, which the re-predication did not change.
        """
        rows = _rows(_build() / "edges.tsv")
        taxon_edges = [r for r in rows if r[2].startswith("NCBITaxon:")]
        self.assertEqual([r[1] for r in taxon_edges], ["biolink:subclass_of"])
        self.assertEqual(taxon_edges[0][2], "NCBITaxon:4914")

    def test_the_retired_node_collapses_onto_its_replacement(self):
        """Both ids are present upstream; after the remap they are one node."""
        ids = [r[0] for r in _rows(_build() / "nodes.tsv")]
        self.assertNotIn("NCBITaxon:262981", ids)
        self.assertEqual(ids.count("NCBITaxon:4914"), 1)

    def test_a_missing_taxdump_degrades_rather_than_failing(self):
        """
        The remap is an improvement, not a precondition.

        Without it the affected taxa are dropped as before — the pre-existing
        behaviour, not a new failure mode.
        """
        rows = _rows(_build(merges=None) / "edges.tsv")
        taxon_edges = [r for r in rows if r[2].startswith("NCBITaxon:")]
        self.assertEqual(taxon_edges[0][2], "NCBITaxon:262981")

    def test_non_taxon_ids_pass_through_untouched(self):
        """A merge table keyed on bare integers must not collide with other prefixes."""
        rows = _rows(_build() / "edges.tsv")
        self.assertTrue(any(r[0] == "gold.organism:1" for r in rows))

    def test_the_surviving_node_keeps_the_current_name_not_the_retired_one(self):
        """
        On collision the replacement's own row must win, not whichever came first.

        The retired row appears first in the fixture, so a naive dedup emits
        `NCBITaxon:4914` labelled with the merged-away taxon's name. Measured on
        the real GOLD payload before the fix: 232 of 420 collisions did exactly
        that — `NCBITaxon:296995` came out as "Exiguobacterium enclense" instead
        of "Exiguobacterium indicum".
        """
        names = {r[0]: r[2] for r in _rows(_build() / "nodes.tsv")}
        self.assertEqual(names["NCBITaxon:4914"], "Lachancea waltii")
        self.assertNotIn("stale", names["NCBITaxon:4914"])
