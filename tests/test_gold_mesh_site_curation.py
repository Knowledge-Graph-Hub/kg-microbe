"""MeSH is bridged per term, because a prefix cannot mean "is a site" (#823)."""

import csv
from pathlib import Path
from unittest import TestCase

REPO_ROOT = Path(__file__).resolve().parents[1]
CURATION = REPO_ROOT / "mappings" / "gold_ecosystem_mesh_sites.tsv"


def _rows():
    """Curated decisions, skipping the comment header."""
    with CURATION.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((ln for ln in handle if not ln.startswith("#")), delimiter="\t"))


class CurationFileTest(TestCase):
    """The file is the mechanism, so its shape is part of the contract."""

    def test_every_row_carries_a_decision_and_a_reason(self):
        """
        A row without a reason is a decision nobody can review or reverse.

        The whole point of listing REJECTED terms rather than deleting them is
        that the reasoning survives; an empty reason defeats that.
        """
        for row in _rows():
            self.assertIn(row["decision"], {"SITE", "REJECTED"}, row)
            self.assertTrue(row["reason"].strip(), f"no reason given for {row['mesh_id']}")

    def test_the_taxon_groups_and_the_chemical_class_are_rejected(self):
        """
        The four terms that made a prefix rule untenable.

        `Invertebrates` is the pointed one: it is the host-taxon case already
        excluded for NCBITaxon on the grounds that `located_in <taxon>` reads as
        classification, readmitted through a different prefix. `Bacteria` and
        `Cnidaria` were not named in #823 — found by enumerating every
        reachable term instead of trusting the two examples, which is why they
        are here.
        """
        rejected = {r["mesh_id"] for r in _rows() if r["decision"] == "REJECTED"}
        self.assertEqual(
            rejected,
            {"mesh:D007448", "mesh:D001419", "mesh:D003063", "mesh:D011084"},
        )

    def test_the_genuine_sites_are_allowed(self):
        """The 410 edges #821 gave up are recovered one term at a time."""
        sites = {r["mesh_id"] for r in _rows() if r["decision"] == "SITE"}
        self.assertEqual(
            sites,
            {"mesh:D000076624", "mesh:D062611", "mesh:D000038", "mesh:D004531", "mesh:D012623"},
        )

    def test_no_mesh_id_is_decided_twice(self):
        """Two rows for one term make the outcome depend on read order."""
        ids = [r["mesh_id"] for r in _rows()]
        self.assertEqual(sorted(ids), sorted(set(ids)))


class TransformGateTest(TestCase):
    """Unlisted means refused, so a new upstream label cannot readmit the error."""

    def test_the_loader_returns_only_site_rows(self):
        """A REJECTED row must never reach the allow-set."""
        from kg_microbe.transform_utils.gold.gold import GOLDTransform

        transform = GOLDTransform(
            input_dir=REPO_ROOT / "data" / "raw",
            output_dir=REPO_ROOT / "data" / "transformed",
        )
        allowed = transform._mesh_site_terms()
        self.assertIn("mesh:D000038", allowed)
        self.assertNotIn("mesh:D007448", allowed)

    def test_an_absent_curation_file_bridges_no_mesh(self):
        """
        Fail closed to the #821 behaviour.

        If the file goes missing, bridging every MeSH term would silently
        restore the defect; bridging none is the state #821 deliberately chose.
        """
        from kg_microbe.transform_utils.gold import gold as gold_module

        transform = gold_module.GOLDTransform(
            input_dir=REPO_ROOT / "data" / "raw",
            output_dir=REPO_ROOT / "data" / "transformed",
        )
        original = gold_module._MESH_SITE_FILE
        try:
            gold_module._MESH_SITE_FILE = "does_not_exist.tsv"
            transform._mesh_sites = None
            self.assertEqual(transform._mesh_site_terms(), set())
        finally:
            gold_module._MESH_SITE_FILE = original


class DeclaredInputTest(TestCase):
    """A curation file a transform reads must be declared, or staleness is invisible."""

    def test_the_curation_file_is_declared_as_a_data_input(self):
        """
        `kgm-freshness-check` reads `DATA_INPUTS` and nothing else.

        Undeclared, an edit to the MeSH decisions changes gold's output while
        every check reports it fresh, and a re-merge ships the old bridges.
        That is #812, then #839 for ontologies_stubs, and would have been this
        transform next (#876) — the declaration is opt-in and nothing fails
        when you forget it.
        """
        from kg_microbe.transform_utils.gold.gold import GOLDTransform

        self.assertIn("mappings/gold_ecosystem_mesh_sites.tsv", GOLDTransform.DATA_INPUTS)

    def test_the_declaration_is_derived_from_the_filename_constant(self):
        """Two hand-kept copies of one path drift; the constant is the single source."""
        import inspect

        from kg_microbe.transform_utils.gold.gold import GOLDTransform

        declaration = inspect.getsource(GOLDTransform).split("DATA_INPUTS = ")[1].split("\n")[0]
        self.assertIn("_MESH_SITE_FILE", declaration)

    def test_every_declared_input_exists_and_is_tracked(self):
        """
        An untracked path contributes no signal, so the declaration would be inert.

        Same reasoning as #843: the checker asks git, and `is_file()` is the
        wrong property to assert.
        """
        import subprocess

        from kg_microbe.transform_utils.gold.gold import GOLDTransform

        for declared in GOLDTransform.DATA_INPUTS:
            tracked = subprocess.run(  # noqa: S603 - fixed argv, path from our own constant
                ["/usr/bin/git", "ls-files", "--error-unmatch", declared],  # noqa: S607
                cwd=REPO_ROOT,
                capture_output=True,
            )
            self.assertEqual(tracked.returncode, 0, f"{declared} is not tracked in git")
