"""Test stereochemistry handling in chemical mapping utilities."""

import unittest

from kg_microbe.utils.chemical_mapping_utils import normalize_name


class TestStereochemistryHandling(unittest.TestCase):

    """Test stereochemistry prefix stripping."""

    def test_normalize_name_basic(self):
        """Test basic normalization without stereochemistry."""
        self.assertEqual(normalize_name("Glucose"), "glucose")
        self.assertEqual(normalize_name("  L-Lactate  "), "l-lactate")

    def test_normalize_name_strip_stereochemistry_false(self):
        """Test normalization without stereochemistry stripping (punctuation still removed)."""
        # D- and L- prefixes are kept (letters + dashes allowed in normalization)
        self.assertEqual(normalize_name("D-glucose", strip_stereochemistry=False), "d-glucose")
        self.assertEqual(normalize_name("L-lactate", strip_stereochemistry=False), "l-lactate")
        # Parentheses are removed by punctuation normalization, but R/S remain
        self.assertEqual(normalize_name("(R)-lactic acid", strip_stereochemistry=False), "r-lactic acid")
        self.assertEqual(normalize_name("(S)-malate", strip_stereochemistry=False), "s-malate")
        # (+) and (-) parentheses/plus/minus removed by punctuation normalization
        self.assertEqual(normalize_name("(+)-glucose", strip_stereochemistry=False), "-glucose")
        self.assertEqual(normalize_name("(-)-arabinose", strip_stereochemistry=False), "--arabinose")

    def test_normalize_name_strip_stereochemistry_true(self):
        """Test that stereochemistry prefixes are stripped when strip_stereochemistry=True."""
        # Test D- and L- prefixes
        self.assertEqual(normalize_name("D-glucose", strip_stereochemistry=True), "glucose")
        self.assertEqual(normalize_name("L-lactate", strip_stereochemistry=True), "lactate")

        # Test (R)- and (S)- prefixes
        self.assertEqual(normalize_name("(R)-lactic acid", strip_stereochemistry=True), "lactic acid")
        self.assertEqual(normalize_name("(S)-malate", strip_stereochemistry=True), "malate")

        # Test (+)- and (-)- prefixes
        self.assertEqual(normalize_name("(+)-glucose", strip_stereochemistry=True), "glucose")
        self.assertEqual(normalize_name("(-)-arabinose", strip_stereochemistry=True), "arabinose")

        # Test with spaces after prefix
        self.assertEqual(normalize_name("D- glucose", strip_stereochemistry=True), "glucose")
        self.assertEqual(normalize_name("(R)- lactic acid", strip_stereochemistry=True), "lactic acid")

    def test_normalize_name_no_stereochemistry(self):
        """Test that names without stereochemistry are unchanged."""
        self.assertEqual(
            normalize_name("acetate", strip_stereochemistry=True),
            normalize_name("acetate", strip_stereochemistry=False),
        )
        self.assertEqual(
            normalize_name("ethanol", strip_stereochemistry=True),
            normalize_name("ethanol", strip_stereochemistry=False),
        )


if __name__ == "__main__":
    unittest.main()
