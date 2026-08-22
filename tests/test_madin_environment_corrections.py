"""Corrections to Madin et al's downloaded environments.csv (#796)."""

from pathlib import Path
from unittest import TestCase

import pandas as pd

from kg_microbe.transform_utils.constants import ENVO_ID_COLUMN, ENVO_TERMS_COLUMN, TYPE_COLUMN
from kg_microbe.transform_utils.madin_etal.madin_etal import (
    ENVIRONMENT_ID_CORRECTIONS_FILE,
    _apply_environment_id_corrections,
)
from kg_microbe.utils.stub_curie_collection import DEFAULT_MAPPING_PATHS, collect_stub_curies

REPO_ROOT = Path(__file__).resolve().parents[1]


def _frame(rows):
    """Build a minimal environments.csv frame."""
    return pd.DataFrame(
        {
            TYPE_COLUMN: [r[0] for r in rows],
            ENVO_TERMS_COLUMN: [r[1] for r in rows],
            ENVO_ID_COLUMN: [r[2] for r in rows],
        }
    )


class EnvironmentCorrectionTest(TestCase):
    """The two upstream rows that name the wrong term."""

    def test_the_taxonomy_root_is_replaced_by_the_plant_root(self):
        """
        `NCBITaxon:1` is the root of the tree of life, matched on the label "root".

        It produced 628 merged edges asserting the root of all life is the
        `location_of` an organism. HabitatMech dropped these by refusing taxa as
        habitats; kg-microbe applied no such filter and asserted them.
        """
        out = _apply_environment_id_corrections(_frame([("host_plant_root-associated", "root", "NCBITaxon:1")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "PO:0009005")
        self.assertEqual(out.iloc[0][ENVO_TERMS_COLUMN], "root")

    def test_the_whole_respiratory_tract_is_narrowed_to_the_nasopharynx(self):
        """Nasopharyngeal measurements must not be asserted about trachea and alveoli."""
        out = _apply_environment_id_corrections(
            _frame([("host_animal_endotherm_nasopharyngeal", "respiratory tract", "UBERON:0000065")])
        )
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "UBERON:0001728")
        self.assertEqual(out.iloc[0][ENVO_TERMS_COLUMN], "nasopharynx")

    def test_unrelated_rows_are_untouched(self):
        """A correction table that rewrites more than it names is worse than none."""
        out = _apply_environment_id_corrections(_frame([("soil", "soil", "ENVO:00001998")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "ENVO:00001998")

    def test_a_correction_does_not_fire_once_upstream_fixes_the_row(self):
        """
        Match on the exact wrong value, not just the row key.

        Otherwise a stale correction would overwrite a *newer* upstream value
        with an older one — turning the fix into the next bug.
        """
        out = _apply_environment_id_corrections(_frame([("host_plant_root-associated", "root", "PO:0009005")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "PO:0009005")

    def test_an_unapplied_correction_is_reported(self):
        """A table that silently stops matching is a table nobody will ever clean up."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            _apply_environment_id_corrections(_frame([("soil", "soil", "ENVO:00001998")]))
        self.assertIn("not applied", buf.getvalue())


class StubRegistrationTest(TestCase):
    """The corrected targets must resolve to real nodes."""

    def test_the_corrections_file_is_scanned_for_stub_curies(self):
        """
        Registration is what makes the fix safe.

        `PO:0009005` is carried by no loaded ontology, so a correction written
        outside a scanned mapping file would swap the taxonomy-root phantom for
        a PO phantom — the defect fixed for NCBITaxon in #815.
        """
        self.assertIn(ENVIRONMENT_ID_CORRECTIONS_FILE, DEFAULT_MAPPING_PATHS)

    def test_the_plant_root_target_is_collected_for_stub_emission(self):
        """End-to-end: the id reaches the set ontologies_stubs builds nodes from."""
        self.assertIn("PO:0009005", collect_stub_curies(["PO"])["PO"])
