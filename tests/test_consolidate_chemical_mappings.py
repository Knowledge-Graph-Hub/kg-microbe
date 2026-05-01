r"""
Tests for the chemical mappings consolidator script.

Focused on ``extract_curie``: the prefix-preserving extractor introduced to
fix the regression where ``extract_chebi_id``'s ``re.search(r"(\d+)", v)``
silently rewrote FOODON / UBERON / PubChem / CAS-RN ids in the heterogeneous
``mapped`` column to ``CHEBI:<numeric_tail>`` (see
CultureBotHT/docs/AUDIT_TRAIL.md). Worst case is the colliding rewrite
``CAS-RN:51142-18-8`` -> ``CHEBI:51142``, which references a real but
unrelated ChEBI entity.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"


def _load_module():
    """Load the consolidator script as an importable module for tests."""
    spec = importlib.util.spec_from_file_location(
        "consolidate_chemical_mappings", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


class ExtractCurieTests(unittest.TestCase):

    """``extract_curie`` preserves accepted prefixes and rejects everything else."""

    @classmethod
    def setUpClass(cls):
        """Load the consolidator module once per test class."""
        cls.mod = _load_module()

    def test_preserves_ontology_prefixes(self):
        """Ontology CURIEs (FOODON/UBERON/ENVO/NCIT) pass through unchanged."""
        for raw in ("FOODON:03315426", "UBERON:0000178", "ENVO:00002007", "NCIT:C12345"):
            self.assertEqual(self.mod.extract_curie(raw), raw)

    def test_preserves_chebi(self):
        """CHEBI ids pass through unchanged."""
        self.assertEqual(self.mod.extract_curie("CHEBI:16236"), "CHEBI:16236")

    def test_normalises_pubchem_aliases(self):
        """PubChem spelling variants normalise to canonical pubchem.compound."""
        for raw in (
            "PubChem:167312541",
            "PUBCHEM:167312541",
            "PUBCHEM.COMPOUND:167312541",
            "Pubchem:167312541",
        ):
            self.assertEqual(
                self.mod.extract_curie(raw),
                "pubchem.compound:167312541",
                f"failed on {raw!r}",
            )

    def test_normalises_cas_aliases(self):
        """CAS-RN/CAS aliases normalise to canonical cas without numeric mangling."""
        # The colliding case: CAS-RN:51142-18-8 must NOT become CHEBI:51142.
        self.assertEqual(self.mod.extract_curie("CAS-RN:51142-18-8"), "cas:51142-18-8")
        self.assertEqual(self.mod.extract_curie("CAS:51142-18-8"), "cas:51142-18-8")

    def test_lowercase_ontology_prefix_normalised(self):
        """Lowercase ontology prefixes normalise to upper-case canonical form."""
        self.assertEqual(self.mod.extract_curie("chebi:16236"), "CHEBI:16236")
        self.assertEqual(self.mod.extract_curie("foodon:03315426"), "FOODON:03315426")

    def test_rejects_bare_digits(self):
        """Bare numeric strings are not reinterpreted as CHEBI."""
        # The mangling regex's input shape — a plain numeric string — must
        # NOT be reinterpreted as CHEBI here.
        self.assertEqual(self.mod.extract_curie("51142"), "")
        self.assertEqual(self.mod.extract_curie("51142-18-8"), "")

    def test_rejects_unknown_prefix(self):
        """CURIEs with unrecognised prefixes are rejected (return empty)."""
        self.assertEqual(self.mod.extract_curie("KEGG:C00031"), "")
        self.assertEqual(self.mod.extract_curie("FOO:bar"), "")

    def test_handles_empty_and_missing(self):
        """Empty / whitespace / NA / None inputs return empty without raising."""
        import pandas as pd

        self.assertEqual(self.mod.extract_curie(""), "")
        self.assertEqual(self.mod.extract_curie("   "), "")
        self.assertEqual(self.mod.extract_curie(pd.NA), "")
        self.assertEqual(self.mod.extract_curie(None), "")


class IsMangledChebiTests(unittest.TestCase):

    """``is_mangled_chebi_id`` recognises pre-fix mangler outputs."""

    @classmethod
    def setUpClass(cls):
        """Load the consolidator module once per test class."""
        cls.mod = _load_module()

    def test_leading_zero_is_mangled(self):
        """FOODON/UBERON values rewritten to CHEBI:0NNNN are mangled."""
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:03315426"))
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:0000178"))

    def test_pubchem_watermark_is_mangled(self):
        """CHEBI ids >= 1_000_000 are PubChem CIDs misrouted to CHEBI:."""
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:167312541"))
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:1000000"))
        # 999_999 is borderline; current threshold rejects only >=1M.
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:999999"))

    def test_blacklist_only_drops_with_safe_sources(self):
        """Blacklist hits are dropped only when sources are auto-mappers."""
        bl = {"CHEBI:8013", "CHEBI:51142"}
        # mediadive_compounds source → drop
        self.assertTrue(self.mod.is_mangled_chebi_id(
            "CHEBI:8013", "mediadive_compounds", bl,
        ))
        # mixed-with-curated → keep (small CHEBI ids may be legitimate)
        self.assertFalse(self.mod.is_mangled_chebi_id(
            "CHEBI:8013", "mediadive_compounds|mediaingredientmech_reviewed", bl,
        ))
        # not in blacklist, sources auto → keep
        self.assertFalse(self.mod.is_mangled_chebi_id(
            "CHEBI:99999", "mediadive_compounds", bl,
        ))

    def test_real_chebi_passes(self):
        """Real CHEBI ids in the 4-6 digit range with no blacklist hit pass."""
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:16236"))  # ethanol
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:26710"))  # NaCl
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:78020"))  # casamino acids

    def test_non_chebi_ignored(self):
        """Non-CHEBI ids are never flagged."""
        self.assertFalse(self.mod.is_mangled_chebi_id("FOODON:03315426"))
        self.assertFalse(self.mod.is_mangled_chebi_id("pubchem.compound:167312541"))
        self.assertFalse(self.mod.is_mangled_chebi_id("cas:8013-01-2"))


if __name__ == "__main__":
    unittest.main()
