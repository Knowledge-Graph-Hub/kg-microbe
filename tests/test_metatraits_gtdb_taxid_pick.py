"""The NCBITaxon id chosen for a GTDB name must not depend on iteration order (#1006)."""

import ast
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform

SOURCE = Path(MetaTraitsGTDBTransform.__module__.replace(".", "/") + ".py")


class TaxidPickTests(unittest.TestCase):
    """A fifth of GTDB species carry several taxids; the pick has to be a rule."""

    def test_the_taxid_most_genomes_carry_wins(self):
        """Streptococcus phocae: 119224 is the species record, 1000562 a subspecies with one genome."""
        counts = Counter({"NCBITaxon:1000562": 1, "NCBITaxon:119224": 3})
        self.assertEqual(MetaTraitsGTDBTransform._pick_ncbi_id(counts), "NCBITaxon:119224")

    def test_a_tie_goes_to_the_lowest_id_not_to_iteration_order(self):
        """Two insertion orders, one answer."""
        a = Counter({"NCBITaxon:1962118": 1, "NCBITaxon:1001739": 1})
        b = Counter({"NCBITaxon:1001739": 1, "NCBITaxon:1962118": 1})
        self.assertEqual(MetaTraitsGTDBTransform._pick_ncbi_id(a), "NCBITaxon:1001739")
        self.assertEqual(MetaTraitsGTDBTransform._pick_ncbi_id(b), "NCBITaxon:1001739")

    def test_the_resolver_uses_the_rule(self):
        """The consumer at the lookup site, driven without constructing the whole transform."""
        transform = object.__new__(MetaTraitsGTDBTransform)
        counts = Counter({"NCBITaxon:1000562": 1, "NCBITaxon:119224": 4})
        transform.gtdb_to_ncbi = defaultdict(Counter, {"Streptococcus phocae": counts})
        transform.accession_to_ncbi = {}
        transform.accession_to_gtdb_species = {}
        transform.synthetic_nodes_metadata = {}
        self.assertEqual(transform._search_ncbitaxon_by_label("Streptococcus phocae"), "NCBITaxon:119224")

    def test_no_first_of_an_unordered_collection_remains(self):
        """The defect was `list(ncbi_ids)[0]`; guard against it coming back in any spelling."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "list":
                    offenders.append(node.lineno)
        self.assertEqual(offenders, [], f"list(...)[i] over a possibly unordered collection at lines {offenders}")


if __name__ == "__main__":
    unittest.main()
