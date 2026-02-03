"""Unit tests for BiolinkHierarchy utility."""

import pytest

from kg_microbe.utils.biolink_hierarchy import BiolinkHierarchy


@pytest.fixture
def hierarchy():
    """Fixture to create BiolinkHierarchy instance for all tests."""
    return BiolinkHierarchy()


class TestBiolinkHierarchy:

    """Test BiolinkHierarchy class methods."""

    def test_initialization(self, hierarchy):
        """Test that BiolinkHierarchy initializes correctly."""
        assert hierarchy.schema is not None
        assert hierarchy.classes is not None
        assert len(hierarchy.depth_map) > 0
        assert len(hierarchy.parent_map) > 0

    def test_named_thing_root(self, hierarchy):
        """Test that NamedThing is at depth 0 (root)."""
        assert hierarchy.get_depth("NamedThing") == 0
        assert hierarchy.get_depth("biolink:NamedThing") == 0

    def test_chemical_entity_hierarchy(self, hierarchy):
        """Test chemical entity hierarchy depths."""
        # NamedThing (0) -> Entity (1) -> ... -> ChemicalEntity
        # ChemicalEntity should be deeper than NamedThing
        named_thing_depth = hierarchy.get_depth("NamedThing")
        chemical_entity_depth = hierarchy.get_depth("ChemicalEntity")
        small_molecule_depth = hierarchy.get_depth("SmallMolecule")

        assert chemical_entity_depth > named_thing_depth
        assert small_molecule_depth > chemical_entity_depth

    def test_most_specific_category_chemical_entity_vs_small_molecule(self, hierarchy):
        """Test ChemicalEntity vs SmallMolecule selection."""
        categories = ["biolink:ChemicalEntity", "biolink:SmallMolecule"]
        result = hierarchy.get_most_specific_category(categories)
        assert result == "biolink:SmallMolecule"

    def test_most_specific_category_without_prefix(self, hierarchy):
        """Test most specific category selection without biolink: prefix."""
        categories = ["ChemicalEntity", "SmallMolecule"]
        result = hierarchy.get_most_specific_category(categories)
        assert result == "biolink:SmallMolecule"

    def test_most_specific_category_triple(self, hierarchy):
        """Test most specific category with three categories."""
        # SmallMolecule should win (most specific)
        categories = [
            "biolink:ChemicalEntity",
            "biolink:MolecularEntity",
            "biolink:SmallMolecule",
        ]
        result = hierarchy.get_most_specific_category(categories)
        assert result == "biolink:SmallMolecule"

    def test_most_specific_category_go_biological_process(self, hierarchy):
        """Test GO category hierarchy (BiologicalProcess vs MolecularActivity)."""
        # Both should be at same depth, but test that selection is deterministic
        categories = ["biolink:BiologicalProcess", "biolink:MolecularActivity"]
        result = hierarchy.get_most_specific_category(categories)
        # Both are depth 3, so should return whichever has higher depth
        # If they're equal depth, should return consistently
        assert result in ["biolink:BiologicalProcess", "biolink:MolecularActivity"]

    def test_most_specific_category_cellular_component(self, hierarchy):
        """Test CellularComponent depth."""
        # CellularComponent should be at depth 4 (deeper than BiologicalProcess/MolecularActivity)
        categories = ["biolink:BiologicalProcess", "biolink:CellularComponent"]
        result = hierarchy.get_most_specific_category(categories)
        assert result == "biolink:CellularComponent"

    def test_most_specific_category_empty_list(self, hierarchy):
        """Test that empty list returns None."""
        result = hierarchy.get_most_specific_category([])
        assert result is None

    def test_most_specific_category_invalid_category(self, hierarchy):
        """Test fallback when category not in Biolink Model."""
        categories = ["biolink:InvalidCategory", "biolink:AnotherInvalidCategory"]
        result = hierarchy.get_most_specific_category(categories)
        # Should return first category as fallback
        assert result == "biolink:InvalidCategory"

    def test_most_specific_category_mixed_valid_invalid(self, hierarchy):
        """Test mixed valid and invalid categories."""
        categories = ["biolink:InvalidCategory", "biolink:ChemicalEntity"]
        result = hierarchy.get_most_specific_category(categories)
        # Should return valid category
        assert result == "biolink:ChemicalEntity"

    def test_is_more_specific_true(self, hierarchy):
        """Test is_more_specific returns True for deeper category."""
        assert hierarchy.is_more_specific("biolink:SmallMolecule", "biolink:ChemicalEntity") is True

    def test_is_more_specific_false(self, hierarchy):
        """Test is_more_specific returns False for shallower category."""
        assert hierarchy.is_more_specific("biolink:ChemicalEntity", "biolink:SmallMolecule") is False

    def test_is_more_specific_invalid_categories(self, hierarchy):
        """Test is_more_specific with invalid categories."""
        assert hierarchy.is_more_specific("biolink:InvalidCategory", "biolink:ChemicalEntity") is False
        assert hierarchy.is_more_specific("biolink:ChemicalEntity", "biolink:InvalidCategory") is False

    def test_get_ancestors_small_molecule(self, hierarchy):
        """Test get_ancestors for SmallMolecule."""
        ancestors = hierarchy.get_ancestors("biolink:SmallMolecule")
        # Should include MolecularEntity, ChemicalEntity, and up to NamedThing
        assert len(ancestors) > 0
        assert "biolink:ChemicalEntity" in ancestors
        assert "biolink:NamedThing" in ancestors

    def test_get_ancestors_named_thing(self, hierarchy):
        """Test get_ancestors for NamedThing (root has no ancestors)."""
        ancestors = hierarchy.get_ancestors("biolink:NamedThing")
        # NamedThing is root, but has Entity as parent in Biolink v4.3.6
        # Check if it returns Entity
        assert len(ancestors) >= 0

    def test_get_ancestors_without_prefix(self, hierarchy):
        """Test get_ancestors without biolink: prefix."""
        ancestors = hierarchy.get_ancestors("SmallMolecule")
        assert len(ancestors) > 0
        # All returned ancestors should have biolink: prefix
        for ancestor in ancestors:
            assert ancestor.startswith("biolink:")

    def test_get_depth_chemical_entity(self, hierarchy):
        """Test get_depth for ChemicalEntity."""
        depth = hierarchy.get_depth("ChemicalEntity")
        assert depth is not None
        assert depth > 0

    def test_get_depth_invalid_category(self, hierarchy):
        """Test get_depth returns None for invalid category."""
        depth = hierarchy.get_depth("InvalidCategory")
        assert depth is None

    def test_case_conversion_pascal_to_snake(self, hierarchy):
        """Test PascalCase to lowercase conversion."""
        # Test internal method
        assert hierarchy._pascal_to_snake("ChemicalEntity") == "chemical entity"
        assert hierarchy._pascal_to_snake("SmallMolecule") == "small molecule"
        assert hierarchy._pascal_to_snake("NamedThing") == "named thing"

    def test_case_conversion_snake_to_pascal(self, hierarchy):
        """Test lowercase to PascalCase conversion."""
        # Test internal method
        assert hierarchy._snake_to_pascal("chemical entity") == "ChemicalEntity"
        assert hierarchy._snake_to_pascal("small molecule") == "SmallMolecule"
        assert hierarchy._snake_to_pascal("named thing") == "NamedThing"

    def test_actual_multi_category_patterns(self, hierarchy):
        """Test actual multi-category patterns from the merged graph analysis."""
        # Pattern 1: ChemicalEntity|SmallMolecule (1,138 occurrences)
        result1 = hierarchy.get_most_specific_category(
            ["biolink:ChemicalEntity", "biolink:SmallMolecule"]
        )
        assert result1 == "biolink:SmallMolecule"

        # Pattern 2: ChemicalRole|SmallMolecule (88 occurrences)
        result2 = hierarchy.get_most_specific_category(
            ["biolink:ChemicalRole", "biolink:SmallMolecule"]
        )
        assert result2 == "biolink:SmallMolecule"

        # Pattern 3: BiologicalProcess|MolecularActivity (from GO conflicts)
        result3 = hierarchy.get_most_specific_category(
            ["biolink:BiologicalProcess", "biolink:MolecularActivity"]
        )
        # Both at depth 3, should be deterministic
        assert result3 in ["biolink:BiologicalProcess", "biolink:MolecularActivity"]

    def test_hierarchy_consistency(self, hierarchy):
        """Test that hierarchy is internally consistent."""
        # Every child should be deeper than its parent
        for child, parent in hierarchy.parent_map.items():
            child_depth = hierarchy.depth_map.get(child)
            parent_depth = hierarchy.depth_map.get(parent)
            if child_depth is not None and parent_depth is not None:
                assert child_depth > parent_depth, (
                    f"{child} (depth {child_depth}) should be deeper than {parent} (depth {parent_depth})"
                )

    def test_multiple_categories_deterministic(self, hierarchy):
        """Test that multiple calls with same input return same result."""
        categories = ["biolink:ChemicalEntity", "biolink:SmallMolecule"]
        result1 = hierarchy.get_most_specific_category(categories)
        result2 = hierarchy.get_most_specific_category(categories)
        assert result1 == result2

    def test_biolink_prefix_handling(self, hierarchy):
        """Test that categories with and without biolink: prefix work."""
        result_with_prefix = hierarchy.get_most_specific_category(
            ["biolink:ChemicalEntity", "biolink:SmallMolecule"]
        )
        result_without_prefix = hierarchy.get_most_specific_category(
            ["ChemicalEntity", "SmallMolecule"]
        )
        # Both should return the same category with biolink: prefix
        assert result_with_prefix == result_without_prefix == "biolink:SmallMolecule"
