"""Test negative lookup cache for chemical mappings."""

import unittest

from kg_microbe.utils.chemical_mapping_utils import (
    _NEGATIVE_LOOKUP_CACHE,
    find_chebi_by_name,
)


class TestNegativeLookupCache(unittest.TestCase):

    """Test negative lookup cache functionality."""

    def test_negative_cache_populated_on_failed_lookup(self):
        """Test that failed lookups are added to negative cache."""
        # Clear cache before test
        _NEGATIVE_LOOKUP_CACHE.clear()

        # Try to lookup a non-existent chemical
        fake_chemical = "definitely_not_a_real_chemical_name_xyz123"
        result = find_chebi_by_name(fake_chemical)

        self.assertIsNone(result, "Should return None for non-existent chemical")
        self.assertGreater(
            len(_NEGATIVE_LOOKUP_CACHE),
            0,
            "Negative cache should be populated after failed lookup",
        )

    def test_negative_cache_prevents_repeated_lookups(self):
        """Test that negative cache prevents repeated failed lookups."""
        # Clear cache before test
        _NEGATIVE_LOOKUP_CACHE.clear()

        # First lookup - should fail and populate cache
        fake_chemical = "another_fake_chemical_xyz456"
        result1 = find_chebi_by_name(fake_chemical)
        cache_size_after_first = len(_NEGATIVE_LOOKUP_CACHE)

        # Second lookup - should use cache (not add new entry)
        result2 = find_chebi_by_name(fake_chemical)
        cache_size_after_second = len(_NEGATIVE_LOOKUP_CACHE)

        self.assertIsNone(result1)
        self.assertIsNone(result2)
        self.assertEqual(
            cache_size_after_first,
            cache_size_after_second,
            "Cache size should not increase for repeated failed lookup",
        )

    def test_successful_lookup_not_cached_as_negative(self):
        """Test that successful lookups are not added to negative cache."""
        # Clear cache before test
        _NEGATIVE_LOOKUP_CACHE.clear()

        # Try to lookup a real chemical (water)
        # Note: This assumes kgmicrobe_unified_entity_mappings.sssom.tsv.gz contains water/H2O
        result = find_chebi_by_name("water")

        # If water is in the mappings, it should not be in negative cache
        if result is not None:
            # Check that the normalized name is not in negative cache keys
            cache_keys_str = str(_NEGATIVE_LOOKUP_CACHE)
            self.assertNotIn(
                "water",
                cache_keys_str.lower(),
                "Successful lookup should not be in negative cache",
            )


if __name__ == "__main__":
    unittest.main()
