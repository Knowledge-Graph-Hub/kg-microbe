"""Tests for the evaluation framework."""

import pytest

from kg_microbe.eval.compare_transforms import categorize_differences, compare_dicts
from kg_microbe.eval.sample_taxa import (
    extract_bacdive_ids,
    get_raw_data_path,
    get_sample_file_path,
)


class TestSampleTaxa:
    """Tests for sample_taxa module."""

    def test_get_sample_file_path(self) -> None:
        """Test sample file path generation."""
        path = get_sample_file_path("bacdive")
        assert path.name == "bacdive_sample_taxa.json"
        assert "eval/samples" in str(path)

    def test_get_raw_data_path(self) -> None:
        """Test raw data path generation."""
        path = get_raw_data_path("bacdive")
        assert path.name == "bacdive_strains.json"
        assert "data/raw" in str(path)

    def test_extract_bacdive_ids(self) -> None:
        """Test BacDive ID extraction from records."""
        records = [
            {"General": {"BacDive-ID": 123}},
            {"General": {"BacDive-ID": 456}},
            {"General": {"BacDive-ID": 789}},
        ]

        ids = extract_bacdive_ids(records, sample_size=2)
        assert len(ids) == 2
        assert all(id in [123, 456, 789] for id in ids)

    def test_extract_bacdive_ids_missing_field(self) -> None:
        """Test ID extraction handles missing fields."""
        records = [
            {"General": {"BacDive-ID": 123}},
            {"General": {}},  # Missing BacDive-ID
            {"Other": {}},  # Missing General
        ]

        ids = extract_bacdive_ids(records, sample_size=10)
        assert len(ids) == 1
        assert ids[0] == 123


class TestEvaluateTransform:
    """Tests for evaluate_transform module."""

    def test_get_strain_node_ids_bacdive(self) -> None:
        """Test strain node ID generation for BacDive."""
        from kg_microbe.eval.evaluate_transform import get_strain_node_ids

        # Test with old format CURIEs
        taxa_curies = ["strain:bacdive_123", "strain:bacdive_456"]
        strain_ids = get_strain_node_ids("bacdive", taxa_curies)

        # Should include both old and new formats for each
        assert "strain:bacdive_123" in strain_ids
        assert "strain:bacdive_456" in strain_ids
        assert "KGMICROBE:123" in strain_ids
        assert "KGMICROBE:456" in strain_ids
        assert len(strain_ids) == 4

        # Test with new KGMICROBE format CURIEs
        taxa_curies_new = ["KGMICROBE:789"]
        strain_ids_new = get_strain_node_ids("bacdive", taxa_curies_new)

        assert "KGMICROBE:789" in strain_ids_new
        assert "strain:bacdive_789" in strain_ids_new
        assert len(strain_ids_new) == 2

        # Test with registered prefix (e.g., ATCC:)
        taxa_curies_reg = ["ATCC:23768"]
        strain_ids_reg = get_strain_node_ids("bacdive", taxa_curies_reg)

        # Registered prefixes are added as-is only
        assert "ATCC:23768" in strain_ids_reg
        assert len(strain_ids_reg) == 1

    def test_get_strain_node_ids_unsupported(self) -> None:
        """Test error handling for unsupported source."""
        from kg_microbe.eval.evaluate_transform import get_strain_node_ids

        with pytest.raises(ValueError, match="Unsupported source"):
            get_strain_node_ids("unsupported", ["strain:bacdive_123"])


class TestCompareTransforms:
    """Tests for compare_transforms module."""

    def test_compare_dicts_no_differences(self) -> None:
        """Test comparing identical dictionaries."""
        dict1 = {"a": 1, "b": 2, "c": {"d": 3}}
        dict2 = {"a": 1, "b": 2, "c": {"d": 3}}

        diffs = compare_dicts(dict1, dict2)
        assert len(diffs) == 0

    def test_compare_dicts_value_change(self) -> None:
        """Test detecting value changes."""
        dict1 = {"count": 10}
        dict2 = {"count": 15}

        diffs = compare_dicts(dict1, dict2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "value_change"
        assert diffs[0]["baseline_value"] == 10
        assert diffs[0]["current_value"] == 15
        assert diffs[0]["change"] == 5
        assert diffs[0]["change_percent"] == 50.0

    def test_compare_dicts_missing_key(self) -> None:
        """Test detecting missing keys."""
        dict1 = {"a": 1, "b": 2}
        dict2 = {"a": 1}

        diffs = compare_dicts(dict1, dict2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "missing_key"
        assert diffs[0]["path"] == "b"

    def test_compare_dicts_new_key(self) -> None:
        """Test detecting new keys."""
        dict1 = {"a": 1}
        dict2 = {"a": 1, "b": 2}

        diffs = compare_dicts(dict1, dict2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "new_key"
        assert diffs[0]["path"] == "b"

    def test_compare_dicts_nested(self) -> None:
        """Test comparing nested dictionaries."""
        dict1 = {"stats": {"count": 10, "avg": 5.0}}
        dict2 = {"stats": {"count": 15, "avg": 5.0}}

        diffs = compare_dicts(dict1, dict2)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "stats.count"
        assert diffs[0]["type"] == "value_change"

    def test_categorize_differences_critical(self) -> None:
        """Test categorizing critical differences."""
        diffs = [
            {
                "path": "total_edges",
                "type": "value_change",
                "baseline_value": 100,
                "current_value": 80,
                "change": -20,
                "change_percent": -20.0,
            }
        ]

        categorized = categorize_differences(diffs)
        assert len(categorized["critical"]) == 1
        assert len(categorized["warning"]) == 0
        assert len(categorized["info"]) == 0

    def test_categorize_differences_warning(self) -> None:
        """Test categorizing warning differences."""
        diffs = [
            {
                "path": "total_edges",
                "type": "value_change",
                "baseline_value": 100,
                "current_value": 93,
                "change": -7,
                "change_percent": -7.0,
            }
        ]

        categorized = categorize_differences(diffs)
        assert len(categorized["critical"]) == 0
        assert len(categorized["warning"]) == 1
        assert len(categorized["info"]) == 0

    def test_categorize_differences_info(self) -> None:
        """Test categorizing info differences."""
        diffs = [
            {
                "path": "total_edges",
                "type": "value_change",
                "baseline_value": 100,
                "current_value": 103,
                "change": 3,
                "change_percent": 3.0,
            }
        ]

        categorized = categorize_differences(diffs)
        assert len(categorized["critical"]) == 0
        assert len(categorized["warning"]) == 0
        assert len(categorized["info"]) == 1

    def test_categorize_differences_missing_key(self) -> None:
        """Test missing keys are critical."""
        diffs = [
            {
                "path": "important_field",
                "type": "missing_key",
                "baseline_value": "something",
                "current_value": None,
            }
        ]

        categorized = categorize_differences(diffs)
        assert len(categorized["critical"]) == 1

    def test_categorize_differences_new_key(self) -> None:
        """Test new keys are informational."""
        diffs = [
            {
                "path": "new_field",
                "type": "new_key",
                "baseline_value": None,
                "current_value": "something",
            }
        ]

        categorized = categorize_differences(diffs)
        assert len(categorized["info"]) == 1


class TestNodeStatistics:
    """Tests for node statistics calculation."""

    def test_calculate_node_statistics_separates_formats(self) -> None:
        """Test that node statistics separate old and new taxa formats."""
        from kg_microbe.eval.evaluate_transform import calculate_node_statistics

        # Mock nodes with different formats
        nodes = {
            "strain:bacdive_123": {"category": "biolink:OrganismTaxon"},
            "strain:bacdive_456": {"category": "biolink:OrganismTaxon"},
            "KGMICROBE:789": {"category": "biolink:OrganismTaxon"},
            "ATCC:23768": {"category": "biolink:OrganismTaxon"},
            "NCBITaxon:1234": {"category": "biolink:OrganismTaxon"},
            "NCBITaxon:5678": {"category": "biolink:OrganismTaxon"},
            "CHEBI:1234": {"category": "biolink:ChemicalEntity"},
        }

        # Search space includes both formats
        strain_ids = {
            "strain:bacdive_123",
            "strain:bacdive_456",
            "KGMICROBE:123",
            "KGMICROBE:456",
            "KGMICROBE:789",
            "ATCC:23768",
        }

        stats = calculate_node_statistics(nodes, strain_ids)

        # Sampled strains: 2 old + 2 new (KGMICROBE + ATCC) = 4 total
        assert stats["sampled_strains_count"] == 4
        assert len(stats["sampled_strains_old_format"]) == 2
        assert len(stats["sampled_strains_new_format"]) == 2

        # Sampled NCBITaxon: 0 (none in the search set)
        assert stats["sampled_ncbitaxon_count"] == 0

        # Connected NCBITaxon nodes: 2
        assert stats["connected_ncbitaxon_count"] == 2
        assert len(stats["connected_ncbitaxon_nodes"]) == 2

        # Total sampled taxa: 4 strains + 0 NCBITaxon = 4
        assert stats["total_sampled_taxa_count"] == 4

        # Total taxa (sampled + connected): 4 + 2 = 6
        assert stats["total_taxa_nodes_count"] == 6

        # Other nodes: 1 CHEBI
        assert stats["other_nodes_count"] == 1
