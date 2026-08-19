"""GOLD's merge wiring: prefixes, taxon overlap, and name-conflict resolution."""

import csv
from pathlib import Path
from unittest import TestCase

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_WITH_GOLD = (
    "merge.yaml",
    "merge.noprego.yaml",
    "merge.prego-full.yaml",
    "merge_bakta.yaml",
)


def _sources(name):
    """Source keys of a merge config."""
    with (REPO_ROOT / name).open() as handle:
        return set((yaml.safe_load(handle)["merged_graph"]["source"] or {}))


class GoldMergeWiringTest(TestCase):

    """GOLD ran on every transform and reached no merge config until now."""

    def test_gold_is_in_every_config_that_carries_the_standard_graph(self):
        """
        Four configs, not one.

        `test_merge_configs.py` requires merge_bakta to be merge.yaml plus the
        annotation cluster, and the PREGO variants to differ only by PREGO — so
        adding a source to one config alone breaks those invariants.
        """
        for name in CONFIGS_WITH_GOLD:
            self.assertIn("gold", _sources(name), f"{name} is missing gold")

    def test_the_minimal_config_is_deliberately_excluded(self):
        """`merge.minimal.yaml` is a 3-source config; adding to it defeats its purpose."""
        self.assertNotIn("gold", _sources("merge.minimal.yaml"))


class TaxonOverlapTest(TestCase):

    """GOLD re-states NCBITaxon nodes the ontologies transform already supplies."""

    def setUp(self):
        """Load both node sets, skipping when the outputs are not built."""
        onto_path = REPO_ROOT / "data" / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv"
        gold_path = REPO_ROOT / "data" / "transformed" / "gold" / "nodes.tsv"
        if not (onto_path.is_file() and gold_path.is_file()):
            self.skipTest("transform outputs not built")
        self.onto, self.gold = {}, {}
        for path, target in ((onto_path, self.onto), (gold_path, self.gold)):
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle, delimiter="\t")
                next(reader)
                for row in reader:
                    if row and row[0].startswith("NCBITaxon:") and len(row) > 2:
                        target[row[0]] = (row[1], row[2])

    def test_gold_introduces_no_taxon_the_ontologies_transform_lacks(self):
        """
        A GOLD-only taxon would be a node with no ontology backing.

        The transform's trim is what guarantees this; if it ever regresses, the
        graph gains untyped taxa rather than failing.
        """
        self.assertEqual(sorted(set(self.gold) - set(self.onto)), [])

    def test_categories_never_conflict(self):
        """A category conflict would make the merged node's type ambiguous."""
        clashes = [i for i in set(self.gold) & set(self.onto) if self.gold[i][0] != self.onto[i][0]]
        self.assertEqual(clashes, [])


class NameConflictTest(TestCase):

    """78 taxon names disagree between GOLD and the ontologies output."""

    def test_the_first_source_wins_a_name_conflict(self):
        """
        Pins the behaviour the wiring depends on.

        KGX's `prepare_data_dict` docstring says a conflicting single-valued key
        is "converted to a list and the new value appended", which would give 78
        nodes a list-valued name. Measured, it does not: the first value wins
        under either `preserve` setting. `ontologies` is listed before `gold` in
        every config, so the OBO-canonical name is kept and GOLD's older label
        is discarded — `Saccharomyces x bayanus CBS 1502` keeps its hybrid
        marker rather than becoming `Saccharomyces bayanus CBS 1502`.

        If a KGX upgrade changes this, 78 names silently degrade, so it is
        asserted rather than assumed.
        """
        from kgx.utils.kgx_utils import prepare_data_dict

        first = {"id": "NCBITaxon:1387704", "name": "Saccharomyces x bayanus CBS 1502"}
        second = {"id": "NCBITaxon:1387704", "name": "Saccharomyces bayanus CBS 1502"}
        for preserve in (True, False):
            merged = prepare_data_dict(dict(first), dict(second), preserve=preserve)
            self.assertEqual(merged["name"], first["name"], f"preserve={preserve}")
