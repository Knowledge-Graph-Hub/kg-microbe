"""Test validation utilities."""

import tempfile
import unittest
from pathlib import Path

from kg_microbe.utils.validation_utils import (
    get_curie_id,
    get_curie_prefix,
    load_valid_kgm_terms,
    validate_curie,
    validate_curie_prefix,
    validate_kgm_term,
)


class TestCURIEValidation(unittest.TestCase):

    """Test CURIE format validation."""

    def test_validate_curie_valid(self):
        """Test valid CURIE formats."""
        valid_curies = [
            "CHEBI:12345",
            "GO:0006113",
            "METPO:1000698",
            "NCBITaxon:9606",
            "EC:1.11.1.6",
            "kgmicrobe.trait:voges_proskauer_test_positive",
            "biolink:ChemicalSubstance",
            "RO:0002200",
            "A:1",  # Minimal valid CURIE
        ]
        for curie in valid_curies:
            with self.subTest(curie=curie):
                self.assertTrue(validate_curie(curie), f"Should be valid: {curie}")

    def test_validate_curie_invalid(self):
        """Test invalid CURIE formats."""
        invalid_curies = [
            "",  # Empty
            "CHEBI",  # No ID
            "CHEBI:",  # Empty ID
            ":12345",  # No prefix
            "123:456",  # Prefix starts with number
            "CHE BI:123",  # Space in prefix
            "CHEBI 123",  # No colon
            "CHEBI: 123",  # Space after colon
            "_PREFIX:123",  # Prefix starts with underscore
            "PREFIX:ID with spaces",  # Space in ID
            None,  # None
            123,  # Not a string
        ]
        for curie in invalid_curies:
            with self.subTest(curie=curie):
                self.assertFalse(validate_curie(curie), f"Should be invalid: {curie}")

    def test_get_curie_prefix(self):
        """Test extracting prefix from CURIE."""
        self.assertEqual(get_curie_prefix("CHEBI:12345"), "CHEBI")
        self.assertEqual(get_curie_prefix("GO:0006113"), "GO")
        self.assertEqual(get_curie_prefix("A:1"), "A")
        self.assertIsNone(get_curie_prefix("invalid"))
        self.assertIsNone(get_curie_prefix(""))

    def test_get_curie_id(self):
        """Test extracting ID from CURIE."""
        self.assertEqual(get_curie_id("CHEBI:12345"), "12345")
        self.assertEqual(get_curie_id("GO:0006113"), "0006113")
        self.assertEqual(get_curie_id("kgmicrobe.trait:voges_proskauer_test_positive"), "voges_proskauer_test_positive")
        self.assertEqual(get_curie_id("A:1"), "1")
        self.assertIsNone(get_curie_id("invalid"))

    def test_validate_curie_prefix(self):
        """Test prefix allowlist validation."""
        allowed = {"CHEBI", "GO", "METPO"}

        self.assertTrue(validate_curie_prefix("CHEBI:12345", allowed))
        self.assertTrue(validate_curie_prefix("GO:0006113", allowed))
        self.assertTrue(validate_curie_prefix("METPO:1000698", allowed))
        self.assertFalse(validate_curie_prefix("EC:1.11.1.6", allowed))
        self.assertFalse(validate_curie_prefix("NCBITaxon:9606", allowed))
        self.assertFalse(validate_curie_prefix("invalid", allowed))


class TestKGMTermValidation(unittest.TestCase):

    """Test KGM custom term validation."""

    def test_load_valid_kgm_terms(self):
        """Test loading KGM terms from custom_curies.yaml."""
        # Test with actual custom_curies.yaml file
        kgm_terms = load_valid_kgm_terms()
        # Should load at least some KGM terms if file exists
        # File may not exist in test environment, so check type
        self.assertIsInstance(kgm_terms, set)

    def test_load_kgm_terms_from_custom_file(self):
        """Test loading KGM terms from a custom YAML file."""
        # Create temporary YAML file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                """
KGM:
  voges_proskauer_test_positive:
    label: "Voges-Proskauer test positive"
    description: "Test result positive"
  citrate_utilization_positive:
    label: "Citrate utilization positive"
    description: "Can utilize citrate"
"""
            )
            temp_path = Path(f.name)

        try:
            kgm_terms = load_valid_kgm_terms(temp_path)
            self.assertEqual(len(kgm_terms), 2)
            self.assertIn("kgmicrobe.trait:voges_proskauer_test_positive", kgm_terms)
            self.assertIn("KGM:citrate_utilization_positive", kgm_terms)
        finally:
            temp_path.unlink()

    def test_validate_kgm_term(self):
        """Test KGM term validation."""
        # Create a small set of valid terms
        valid_terms = {"kgmicrobe.trait:voges_proskauer_test_positive", "KGM:citrate_utilization_positive"}

        self.assertTrue(validate_kgm_term("kgmicrobe.trait:voges_proskauer_test_positive", valid_terms))
        self.assertTrue(validate_kgm_term("KGM:citrate_utilization_positive", valid_terms))
        self.assertFalse(validate_kgm_term("KGM:unknown_term", valid_terms))
        self.assertFalse(validate_kgm_term("CHEBI:12345", valid_terms))
        self.assertFalse(validate_kgm_term("", valid_terms))
        self.assertFalse(validate_kgm_term(None, valid_terms))


if __name__ == "__main__":
    unittest.main()
