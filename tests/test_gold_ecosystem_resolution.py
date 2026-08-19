"""Resolve uninformative GOLD ecosystems upward, drop root-only ones."""

import csv
import io
import os
import tarfile
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.gold.gold import GOLDTransform

# Mirrors the real shape: the biggest target is three "Unclassified" hops below
# "Mammals: Human", and 58,091 real edges point straight at the hierarchy root.
NODES = [
    ["id", "category", "name"],
    ["gold.organism:deep", "biolink:IndividualOrganism", "buried under Unclassified"],
    ["gold.organism:rootonly", "biolink:IndividualOrganism", "points at the root"],
    ["gold.organism:named", "biolink:IndividualOrganism", "already informative"],
    ["gold.ecosystem:4138", "biolink:EnvironmentalFeature", "Unclassified"],
    ["gold.ecosystem:3699", "biolink:EnvironmentalFeature", "Unclassified"],
    ["gold.ecosystem:3593", "biolink:EnvironmentalFeature", "Unclassified"],
    ["gold.ecosystem:3381", "biolink:EnvironmentalFeature", "Mammals: Human"],
    ["gold.ecosystem:4", "biolink:EnvironmentalFeature", "Host-associated"],
    ["gold.ecosystem:1", "biolink:EnvironmentalFeature", "root"],
    ["gold.ecosystem:soil", "biolink:EnvironmentalFeature", "Soil"],
]
EDGES = [
    ["subject", "predicate", "object", "relation"],
    ["gold.organism:deep", "biolink:occurs_in", "gold.ecosystem:4138", "RO:0002451"],
    ["gold.organism:rootonly", "biolink:occurs_in", "gold.ecosystem:1", "RO:0002451"],
    ["gold.organism:named", "biolink:occurs_in", "gold.ecosystem:soil", "RO:0002451"],
    ["gold.ecosystem:4138", "biolink:subclass_of", "gold.ecosystem:3699", "rdfs:subClassOf"],
    ["gold.ecosystem:3699", "biolink:subclass_of", "gold.ecosystem:3593", "rdfs:subClassOf"],
    ["gold.ecosystem:3593", "biolink:subclass_of", "gold.ecosystem:3381", "rdfs:subClassOf"],
    ["gold.ecosystem:3381", "biolink:subclass_of", "gold.ecosystem:4", "rdfs:subClassOf"],
    ["gold.ecosystem:4", "biolink:subclass_of", "gold.ecosystem:1", "rdfs:subClassOf"],
    ["gold.ecosystem:soil", "biolink:subclass_of", "gold.ecosystem:1", "rdfs:subClassOf"],
]


def _run():
    """Run the transform over the fixture and return its edge rows as dicts."""
    tmp = Path(tempfile.mkdtemp())
    raw, out = tmp / "raw", tmp / "transformed"
    (raw / "gold").mkdir(parents=True)
    out.mkdir()
    for name, rows in (("GOLD_nodes.tsv", NODES), ("GOLD_edges.tsv", EDGES)):
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
    with (out / "gold" / "edges.tsv").open() as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


class EcosystemResolutionTest(TestCase):

    """The meaning is in the hierarchy, so a one-hop query must still find it."""

    def setUp(self):
        """Run once and keep only the environment edges."""
        self.edges = _run()
        self.occurs = [e for e in self.edges if e["predicate"] == "biolink:occurs_in"]

    def test_a_buried_target_resolves_to_its_nearest_named_ancestor(self):
        """
        Three "Unclassified" hops below "Mammals: Human".

        On the real payload this single node carries 39,446 organisms. Left
        alone, every one of them says only "Unclassified"; resolved, they say
        the organism came from a human host — which is what GOLD knows.
        """
        deep = [e for e in self.occurs if e["subject"] == "gold.organism:deep"]
        self.assertEqual(len(deep), 1)
        self.assertEqual(deep[0]["object"], "gold.ecosystem:3381")

    def test_the_original_target_is_kept_as_provenance(self):
        """
        Rewriting the target silently would make the collapse unauditable.

        `original_object` is Biolink's slot for exactly this — what the source
        said before transformation — so the resolution is reversible.
        """
        deep = [e for e in self.occurs if e["subject"] == "gold.organism:deep"][0]
        self.assertEqual(deep["original_object"], "gold.ecosystem:4138")

    def test_an_edge_resolving_only_to_the_root_is_dropped(self):
        """
        `occurs_in root` asserts the organism lives somewhere.

        58,091 real edges say this. There is nothing above to recover, so the
        edge carries no information at any depth.
        """
        self.assertFalse([e for e in self.occurs if e["subject"] == "gold.organism:rootonly"])

    def test_an_already_named_target_is_untouched_and_unannotated(self):
        """Resolution must not disturb, or mark, edges that were already fine."""
        named = [e for e in self.occurs if e["subject"] == "gold.organism:named"][0]
        self.assertEqual(named["object"], "gold.ecosystem:soil")
        self.assertEqual(named["original_object"], "")

    def test_the_hierarchy_itself_is_not_rewritten(self):
        """
        Only `occurs_in` is resolved.

        Collapsing `subclass_of` would destroy the very structure the resolution
        depends on, and the hierarchy is what a future ENVO crosswalk will map.
        """
        subclass = [e for e in self.edges if e["predicate"] == "biolink:subclass_of"]
        pairs = {(e["subject"], e["object"]) for e in subclass}
        self.assertIn(("gold.ecosystem:4138", "gold.ecosystem:3699"), pairs)
        self.assertTrue(all(e["original_object"] == "" for e in subclass))

    def test_root_is_not_mistaken_for_a_plant_root(self):
        """
        `root` here is the hierarchy root, not anatomy.

        The same label put physicochemical bands on `NCBITaxon:1` in #796, so
        the guard is explicit rather than incidental.
        """
        from kg_microbe.transform_utils.gold.gold import _UNINFORMATIVE_ECOSYSTEM_LABELS

        self.assertIn("root", _UNINFORMATIVE_ECOSYSTEM_LABELS)


class EnvoCrosswalkTest(TestCase):

    """The GOLD ontology's curated ENVO mappings bridge the ecosystem island."""

    def test_the_crosswalk_is_gated_on_the_envo_node_existing(self):
        """
        7 of 210 real ENVO targets are absent from our ENVO extract.

        Emitting those would mint untyped `biolink:NamedThing` phantoms — the
        defect fixed for NCBITaxon in #815, LPSN in #817 and the taxid remap in
        #819. Refusing is the third repetition of the same lesson, so it is a
        guard rather than an accident.
        """
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "transformed"
        (out / "ontologies").mkdir(parents=True)
        with (out / "ontologies" / "envo_nodes.tsv").open("w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["id", "category", "name"])
            w.writerow(["ENVO:00002007", "biolink:NamedThing", "sediment"])
        t = GOLDTransform(output_dir=out)
        t.output_base_dir = out
        available = t._envo_nodes()
        self.assertIn("ENVO:00002007", available)
        self.assertNotIn("ENVO:02000145", available)

    def test_a_missing_ontology_degrades_to_no_crosswalk(self):
        """
        The crosswalk is an improvement, not a precondition.

        Without it the ecosystem vocabulary stays an island, which is the
        behaviour before this existed — not a new failure.
        """
        t = GOLDTransform(input_dir=Path(tempfile.mkdtemp()))
        self.assertEqual(t._envo_crosswalk(), {})
