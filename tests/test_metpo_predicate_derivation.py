"""A METPO term's Biolink predicate must come from the properties template, not a default (#568)."""

import os
import unittest
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

mfu = import_module("kg_microbe.utils.mapping_file_utils")

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A classes tab shaped like the pinned 2026-06-12 template: no `biolink
#: equivalent` column, categories in `biolink close match`, a ROBOT row second.
SHEET = "\t".join(
    ["ID", "label", "parent classes (one strongly preferred)", "metatraits synonym", "biolink close match"]
) + "\n" + "\t".join(["ID", "LABEL", "SC %", "A oboInOwl:hasRelatedSynonym", "AI skos:closeMatch"]) + "\n" + "\n".join(
    [
        "METPO:1\tphenotype\t\t\thttps://biolink.github.io/biolink-model/PhenotypicQuality",
        "METPO:2\tbiological process\t\t\t",
        "METPO:3\tquality\t\t\t",
        "METPO:4\tmotility\tphenotype\tmotile\t",
        "METPO:5\tnitrogen fixation\tbiological process\tnitrogen fixer\t",
        "METPO:6\tsalt tolerance\tquality\thalotolerant\t",
        "METPO:7\tunplaced trait\t\torphan\t",
    ]
) + "\n"

PROPERTIES = "\t".join(["ID", "label", "RANGE", "parent property", "biolink equivalent"]) + "\n" + "\t".join(
    ["ID", "LABEL", "RANGE", "SP %", "AI skos:exactMatch"]
) + "\n" + "\n".join(
    [
        "METPO:2000101\thas quality\tquality\t\t",
        "METPO:2000067\tisolated from host with quality\tquality\t\t",
        "METPO:2000102\thas phenotype\tphenotype\thas quality\thttps://biolink.github.io/biolink-model/has_phenotype",
        "METPO:2000103\tcapable of\tbiological process\t\thttps://biolink.github.io/biolink-model/capable_of",
    ]
) + "\n"


class _Templates:
    """Point the loaders at a throwaway template directory for one test."""

    def __init__(self, sheet=SHEET, properties=PROPERTIES):
        self.sheet, self.properties = sheet, properties

    def __enter__(self):
        self._td = TemporaryDirectory()
        root = Path(self._td.name)
        (root / "metpo_sheet.tsv").write_text(self.sheet, encoding="utf-8")
        (root / "metpo-properties.tsv").write_text(self.properties, encoding="utf-8")
        self._old = os.environ.get("KG_MICROBE_METPO_TEMPLATE_DIR")
        os.environ["KG_MICROBE_METPO_TEMPLATE_DIR"] = str(root)
        return mfu.load_metpo_mappings("metatraits synonym")

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("KG_MICROBE_METPO_TEMPLATE_DIR", None)
        else:
            os.environ["KG_MICROBE_METPO_TEMPLATE_DIR"] = self._old
        self._td.cleanup()


class PredicateDerivationTests(unittest.TestCase):
    """The RANGE walk, on a sheet with no class-level `biolink equivalent`."""

    def test_a_process_is_asserted_with_capable_of(self):
        """
        The #568 no-op.

        Requiring a class-level `biolink equivalent` before consulting the
        RANGE table meant this walked to the root and fell to `has phenotype`.
        """
        with _Templates() as m:
            self.assertEqual(m["nitrogen fixer"]["predicate"], "capable of")
            self.assertTrue(m["nitrogen fixer"]["predicate_biolink_equivalent"].endswith("/capable_of"))

    def test_a_phenotype_keeps_has_phenotype(self):
        """The common case is unchanged, and now reached on purpose."""
        with _Templates() as m:
            self.assertEqual(m["motile"]["predicate"], "has phenotype")
            self.assertTrue(m["motile"]["predicate_biolink_equivalent"].endswith("/has_phenotype"))

    def test_a_quality_gets_the_generic_property_not_a_colliding_one(self):
        """
        Three properties share RANGE `quality`; last-row-wins picked an isolation one.

        The generic `has <RANGE>` property wins, and its Biolink predicate
        comes from the shared METPO -> Biolink map when the template has none.
        """
        with _Templates() as m:
            self.assertEqual(m["halotolerant"]["predicate"], "has quality")
            self.assertEqual(m["halotolerant"]["predicate_biolink_equivalent"], "biolink:has_attribute")

    def test_the_category_comes_from_the_close_match_column(self):
        """The classes tab lost `biolink equivalent`; `biolink close match` carries the URI now."""
        with _Templates() as m:
            # A URI here; the transforms compress it with uri_to_curie at emit time.
            self.assertTrue(m["motile"]["inferred_category"].endswith("/PhenotypicQuality"))

    def test_a_term_with_no_range_ancestor_falls_to_the_default(self):
        """Unplaced is still unplaced; the default is a fallback, not the rule."""
        with _Templates() as m:
            self.assertEqual(m["orphan"]["predicate"], "has phenotype")
            self.assertEqual(m["orphan"]["predicate_biolink_equivalent"], "")

    def test_the_robot_template_row_is_not_read_as_a_category(self):
        """`AI skos:closeMatch` is a ROBOT directive, not a URI."""
        row = {"biolink close match": "AI skos:closeMatch", "biolink broad match": ""}
        self.assertEqual(mfu._class_biolink_category(row), "")


PINNED_SHEET = REPO_ROOT / "data" / "raw" / "metpo_sheet.tsv"


@unittest.skipUnless(PINNED_SHEET.is_file(), "pinned METPO templates not downloaded")
class PinnedSheetTests(unittest.TestCase):
    """On the real pinned templates, the derivation must not be a no-op."""

    def test_at_least_one_metatraits_term_is_not_has_phenotype(self):
        """Before #568 all 102 metatraits synonyms resolved to `has phenotype`."""
        old = os.environ.get("KG_MICROBE_METPO_TEMPLATE_DIR")
        os.environ["KG_MICROBE_METPO_TEMPLATE_DIR"] = str(REPO_ROOT / "data" / "raw")
        try:
            m = mfu.load_metpo_mappings("metatraits synonym")
        finally:
            if old is None:
                os.environ.pop("KG_MICROBE_METPO_TEMPLATE_DIR", None)
            else:
                os.environ["KG_MICROBE_METPO_TEMPLATE_DIR"] = old
        predicates = {v["predicate"] for v in m.values()}
        self.assertIn("capable of", predicates, sorted(predicates))


if __name__ == "__main__":
    unittest.main()
