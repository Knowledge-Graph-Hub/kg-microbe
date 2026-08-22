"""Tests for surfacing corrections that lose a rank tie to a raw column (#723)."""

import importlib.util
import sys
from pathlib import Path
from unittest import TestCase

_SPEC = importlib.util.spec_from_file_location(
    "consolidate_chemical_mappings",
    Path(__file__).parent.parent / "scripts" / "consolidate_chemical_mappings.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["consolidate_chemical_mappings"] = _MODULE
_SPEC.loader.exec_module(_MODULE)


class CorrectedColumnDivergenceTest(TestCase):
    """`corrected_column_primary` must expose ties the production order hides."""

    def test_a_correction_that_loses_the_tie_is_visible(self):
        """
        The case the issue is about.

        A curator writes the corrected grounding to `mim_id`, a stale value
        survives in `chebi_id`, both rank 100, and production picks the stale one
        because it is passed first. The correction is demoted to an xref with no
        signal.
        """
        production = _MODULE.best_primary(["CHEBI:194474", "", "CHEBI:30753", "", ""])
        corrected = _MODULE.corrected_column_primary("", "CHEBI:30753", "CHEBI:194474", "", "")

        self.assertEqual(production, "CHEBI:194474", "production keeps grounding to the raw column")
        self.assertEqual(corrected, "CHEBI:30753", "the corrected column names a different CURIE")
        self.assertNotEqual(production, corrected, "which is precisely what must be reported")

    def test_agreement_is_not_reported(self):
        """Only genuine divergence should reach a curator; noise would bury it."""
        self.assertEqual(
            _MODULE.corrected_column_primary("", "CHEBI:30753", "CHEBI:30753", "", ""),
            _MODULE.best_primary(["CHEBI:30753", "", "CHEBI:30753", "", ""]),
        )

    def test_an_empty_corrected_column_does_not_divergence(self):
        """Most rows have no correction at all; they must stay silent."""
        self.assertEqual(
            _MODULE.corrected_column_primary("", "", "CHEBI:30753", "", ""),
            _MODULE.best_primary(["CHEBI:30753", "", "", "", ""]),
        )

    def test_ranking_still_beats_order(self):
        """
        Order only decides *within* a rank tier.

        A higher-ranked raw value must still win over a lower-ranked corrected
        one — this reports tie-breaks, it does not invert the ranking.
        """
        chebi_rank = _MODULE.prefix_rank("CHEBI:30753")
        cas_rank = _MODULE.prefix_rank("CAS-RN:50-00-0")
        if cas_rank >= chebi_rank:
            self.skipTest("CAS is not ranked below CHEBI in this config")
        self.assertEqual(_MODULE.corrected_column_primary("", "CAS-RN:50-00-0", "CHEBI:30753", "", ""), "CHEBI:30753")
