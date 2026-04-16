"""Integration tests for transform category alignment."""

import csv

import pytest

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import CHEBI_NODES_FILE
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform


class TestTransformCategoryAlignment:

    """Test that transforms correctly align categories with ontologies transform."""

    @pytest.fixture
    def chebi_categories_from_ontologies(self):
        """Load CHEBI categories from ontologies transform for comparison."""
        categories = {}
        chebi_nodes_file = CHEBI_NODES_FILE

        if not chebi_nodes_file.exists():
            pytest.skip("CHEBI nodes file not found - ontologies transform not run")

        with open(chebi_nodes_file) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row["id"].startswith("CHEBI:"):
                    categories[row["id"]] = row["category"]

        return categories

    def test_bacdive_loads_chebi_categories(self):
        """Test that BacDive transform loads CHEBI categories from ontologies."""
        bacdive = BacDiveTransform()

        # Check that categories were loaded
        assert len(bacdive.chebi_categories) > 0, "BacDive should load CHEBI categories from ontologies transform"
        print(f"\n✓ BacDive loaded {len(bacdive.chebi_categories):,} CHEBI categories")

    def test_mediadive_loads_chebi_categories(self):
        """Test that MediaDive transform loads CHEBI categories from ontologies."""
        mediadive = MediaDiveTransform()

        # Check that categories were loaded
        assert len(mediadive.chebi_categories) > 0, "MediaDive should load CHEBI categories from ontologies transform"
        print(f"\n✓ MediaDive loaded {len(mediadive.chebi_categories):,} CHEBI categories")

    def test_bacdive_get_chebi_category_specific_examples(self):
        """Test that BacDive returns correct categories for specific CHEBI IDs."""
        bacdive = BacDiveTransform()

        # Test a few specific CHEBI IDs if they exist
        # CHEBI:16828 is 16-hydroxyhexadecanoic acid (should be SmallMolecule)
        if "CHEBI:16828" in bacdive.chebi_categories:
            category = bacdive._get_chebi_category("CHEBI:16828")
            print(f"\n✓ CHEBI:16828 category: {category}")
            assert category == bacdive.chebi_categories["CHEBI:16828"]
            assert category != "biolink:ChemicalEntity", "Should not fall back to generic ChemicalEntity"

    def test_mediadive_get_chebi_category_specific_examples(self):
        """Test that MediaDive returns correct categories for specific CHEBI IDs."""
        mediadive = MediaDiveTransform()

        # Test a few specific CHEBI IDs if they exist
        if "CHEBI:16828" in mediadive.chebi_categories:
            category = mediadive._get_chebi_category("CHEBI:16828")
            print(f"\n✓ CHEBI:16828 category: {category}")
            assert category == mediadive.chebi_categories["CHEBI:16828"]
            assert category != "biolink:ChemicalEntity", "Should not fall back to generic ChemicalEntity"

    def test_bacdive_category_matches_ontologies(self, chebi_categories_from_ontologies):
        """Test that BacDive categories match ontologies transform categories."""
        bacdive = BacDiveTransform()

        # Compare samples (not all 224k, just a sample)
        sample_ids = list(bacdive.chebi_categories.keys())[:100]
        mismatches = []

        for chebi_id in sample_ids:
            bacdive_cat = bacdive.chebi_categories[chebi_id]
            ontologies_cat = chebi_categories_from_ontologies.get(chebi_id)

            if ontologies_cat and bacdive_cat != ontologies_cat:
                mismatches.append((chebi_id, bacdive_cat, ontologies_cat))

        assert len(mismatches) == 0, f"Found {len(mismatches)} category mismatches between BacDive and ontologies"
        print(f"\n✓ Verified {len(sample_ids)} CHEBI categories match ontologies transform")

    def test_mediadive_category_matches_ontologies(self, chebi_categories_from_ontologies):
        """Test that MediaDive categories match ontologies transform categories."""
        mediadive = MediaDiveTransform()

        # Compare samples (not all 224k, just a sample)
        sample_ids = list(mediadive.chebi_categories.keys())[:100]
        mismatches = []

        for chebi_id in sample_ids:
            mediadive_cat = mediadive.chebi_categories[chebi_id]
            ontologies_cat = chebi_categories_from_ontologies.get(chebi_id)

            if ontologies_cat and mediadive_cat != ontologies_cat:
                mismatches.append((chebi_id, mediadive_cat, ontologies_cat))

        assert len(mismatches) == 0, f"Found {len(mismatches)} category mismatches between MediaDive and ontologies"
        print(f"\n✓ Verified {len(sample_ids)} CHEBI categories match ontologies transform")

    def test_bacdive_fallback_to_metabolite_category(self):
        """Test that BacDive falls back to METABOLITE_CATEGORY for unknown CHEBI IDs."""
        from kg_microbe.transform_utils.constants import METABOLITE_CATEGORY

        bacdive = BacDiveTransform()

        # Test with a CHEBI ID that definitely doesn't exist
        fake_chebi = "CHEBI:99999999"
        category = bacdive._get_chebi_category(fake_chebi)

        assert category == METABOLITE_CATEGORY
        print(f"\n✓ BacDive correctly falls back to {METABOLITE_CATEGORY} for unknown CHEBI IDs")

    def test_mediadive_fallback_to_ingredient_category(self):
        """Test that MediaDive falls back to INGREDIENT_CATEGORY for unknown CHEBI IDs."""
        from kg_microbe.transform_utils.constants import INGREDIENT_CATEGORY

        mediadive = MediaDiveTransform()

        # Test with a CHEBI ID that definitely doesn't exist
        fake_chebi = "CHEBI:99999999"
        category = mediadive._get_chebi_category(fake_chebi)

        assert category == INGREDIENT_CATEGORY
        print(f"\n✓ MediaDive correctly falls back to {INGREDIENT_CATEGORY} for unknown CHEBI IDs")

    def test_category_distribution(self, chebi_categories_from_ontologies):
        """Test distribution of CHEBI categories in ontologies transform."""
        from collections import Counter

        category_counts = Counter(chebi_categories_from_ontologies.values())

        print("\n✓ CHEBI category distribution in ontologies transform:")
        for category, count in category_counts.most_common(10):
            percentage = (count / len(chebi_categories_from_ontologies)) * 100
            print(f"  {category}: {count:,} ({percentage:.1f}%)")

        # Most CHEBI compounds are ChemicalSubstance (ontologies transform uses ChemicalSubstance;
        # SmallMolecule is the preferred Biolink v4 term but the OBO-derived ontologies output
        # has not been migrated yet)
        assert "biolink:ChemicalSubstance" in category_counts
        assert category_counts["biolink:ChemicalSubstance"] > 100000, "Most CHEBI compounds should be ChemicalSubstance"

    def test_mediadive_classify_ingredient_uses_chebi_category(self):
        """Test that MediaDive _classify_ingredient_category uses CHEBI categories for CHEBI IDs."""
        mediadive = MediaDiveTransform()

        # Test with a known CHEBI ID from ontologies
        test_chebi_ids = [cid for cid in list(mediadive.chebi_categories.keys())[:5] if cid.startswith("CHEBI:")]

        for chebi_id in test_chebi_ids:
            expected_category = mediadive.chebi_categories[chebi_id]
            actual_category = mediadive._classify_ingredient_category(chebi_id, "test compound")

            assert actual_category == expected_category, (
                f"MediaDive _classify_ingredient_category should use CHEBI category for {chebi_id}"
            )

        print("\n✓ MediaDive _classify_ingredient_category correctly uses CHEBI categories")
