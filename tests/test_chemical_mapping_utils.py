"""Tests for chemical mapping utilities."""

import gzip
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.utils import chemical_mapping_utils
from kg_microbe.utils.chemical_mapping_utils import (
    ChemicalMappingLoader,
    find_chebi_by_formula,
    find_chebi_by_name,
    find_chebi_by_xref,
    get_canonical_name,
    get_formula,
    get_synonyms,
    get_xrefs,
    normalize_name,
)


@pytest.fixture
def mock_mappings_file():
    """Create a temporary mock unified mappings file."""
    # Create mock data
    data = {
        "chebi_id": ["CHEBI:15377", "CHEBI:17234", "CHEBI:16240", "CHEBI:17925"],
        "canonical_name": ["water", "glucose", "hydrogen peroxide", "lactate"],
        "formula": ["H2O", "C6H12O6", "H2O2", "C3H6O3"],
        "synonyms": [
            "H2O|dihydrogen oxide|oxidane",
            "D-glucose|dextrose|grape sugar",
            "hydrogen peroxide|peroxide",
            "lactic acid|2-hydroxypropanoic acid",
        ],
        "xrefs": [
            "cas:7732-18-5|kegg.compound:C00001",
            "cas:50-99-7|kegg.compound:C00031|pubchem.compound:5793",
            "cas:7722-84-1|kegg.compound:C00027",
            "cas:79-33-4|kegg.compound:C00186",
        ],
        "sources": [
            "chebi_xrefs|mediadive_compounds",
            "chebi_xrefs|primary_mappings[kegg_compound]",
            "chebi_xrefs",
            "bacdive_metabolites|chebi_xrefs",
        ],
    }

    df = pd.DataFrame(data)

    # Create temporary gzipped TSV
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".tsv.gz", delete=False) as tmp:
        with gzip.open(tmp.name, "wt") as f:
            df.to_csv(f, sep="\t", index=False)
        tmp_path = Path(tmp.name)

    yield tmp_path

    # Cleanup
    tmp_path.unlink()


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level cache before each test."""
    chemical_mapping_utils._UNIFIED_MAPPINGS = None
    chemical_mapping_utils._NAME_INDEX = None
    chemical_mapping_utils._FORMULA_INDEX = None
    chemical_mapping_utils._XREF_INDEX = None
    yield
    # Reset after test too
    chemical_mapping_utils._UNIFIED_MAPPINGS = None
    chemical_mapping_utils._NAME_INDEX = None
    chemical_mapping_utils._FORMULA_INDEX = None
    chemical_mapping_utils._XREF_INDEX = None


class TestNormalizeName:

    """Test name normalization."""

    def test_normalize_lowercase(self):
        """Test conversion to lowercase."""
        assert normalize_name("WATER") == "water"
        assert normalize_name("Water") == "water"

    def test_normalize_punctuation(self):
        """Test punctuation removal."""
        assert normalize_name("D-glucose") == "d-glucose"  # Hyphens are preserved
        assert normalize_name("(+)-lactate") == "-lactate"  # Parentheses removed, hyphen kept

    def test_normalize_whitespace(self):
        """Test whitespace handling."""
        assert normalize_name("hydrogen  peroxide") == "hydrogen peroxide"
        assert normalize_name("  water  ") == "water"

    def test_normalize_empty(self):
        """Test empty and None inputs."""
        assert normalize_name("") == ""
        assert normalize_name(None) == ""
        assert normalize_name(pd.NA) == ""


class TestLoadUnifiedMappings:

    """Test loading unified mappings file."""

    def test_load_with_path(self, mock_mappings_file):
        """Test loading with explicit path."""
        df = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert df is not None
        assert len(df) == 4
        assert "chebi_id" in df.columns
        assert "canonical_name" in df.columns

    def test_load_caching(self, mock_mappings_file):
        """Test that mappings are cached."""
        # First load
        df1 = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        # Second load should return cached version
        df2 = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert df1 is df2  # Same object reference

    def test_load_file_not_found(self):
        """Test error when file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            chemical_mapping_utils.load_unified_mappings(Path("/nonexistent/file.tsv.gz"))


class TestFindChebiByName:

    """Test ChEBI ID lookup by name."""

    def test_find_by_canonical_name(self, mock_mappings_file):
        """Test lookup by canonical name."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("water") == "CHEBI:15377"
        assert find_chebi_by_name("glucose") == "CHEBI:17234"

    def test_find_by_synonym(self, mock_mappings_file):
        """Test lookup by synonym."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("dextrose") == "CHEBI:17234"
        assert find_chebi_by_name("lactic acid") == "CHEBI:17925"

    def test_find_case_insensitive(self, mock_mappings_file):
        """Test case-insensitive lookup."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("WATER") == "CHEBI:15377"
        assert find_chebi_by_name("Water") == "CHEBI:15377"

    def test_find_with_punctuation(self, mock_mappings_file):
        """Test lookup with punctuation normalization."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        # Hyphens are preserved in normalization, so "D-glucose" should match
        assert find_chebi_by_name("D-glucose") == "CHEBI:17234"
        # Test that hyphen/space differences don't break lookup for synonyms
        assert find_chebi_by_name("2-hydroxypropanoic acid") == "CHEBI:17925"

    def test_find_not_found(self, mock_mappings_file):
        """Test lookup with non-existent name."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("nonexistent") is None

    def test_find_empty_name(self, mock_mappings_file):
        """Test lookup with empty name."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("") is None
        assert find_chebi_by_name(None) is None


class TestFindChebiByFormula:

    """Test ChEBI ID lookup by formula."""

    def test_find_by_formula(self, mock_mappings_file):
        """Test lookup by molecular formula."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        result = find_chebi_by_formula("H2O")
        assert "CHEBI:15377" in result
        assert len(result) == 1

    def test_find_by_formula_multiple(self, mock_mappings_file):
        """Test lookup when formula matches multiple compounds."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        result = find_chebi_by_formula("C6H12O6")
        assert "CHEBI:17234" in result

    def test_find_formula_not_found(self, mock_mappings_file):
        """Test lookup with non-existent formula."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        result = find_chebi_by_formula("XYZ123")
        assert result == []

    def test_find_empty_formula(self, mock_mappings_file):
        """Test lookup with empty formula."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_formula("") == []
        assert find_chebi_by_formula(None) == []


class TestFindChebiByXref:

    """Test ChEBI ID lookup by cross-reference."""

    def test_find_by_cas_number(self, mock_mappings_file):
        """Test lookup by CAS number."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("cas:7732-18-5") == "CHEBI:15377"

    def test_find_by_kegg_compound(self, mock_mappings_file):
        """Test lookup by KEGG compound ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("kegg.compound:C00031") == "CHEBI:17234"

    def test_find_by_pubchem(self, mock_mappings_file):
        """Test lookup by PubChem ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("pubchem.compound:5793") == "CHEBI:17234"

    def test_find_xref_case_insensitive(self, mock_mappings_file):
        """Test case-insensitive xref lookup."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("CAS:7732-18-5") == "CHEBI:15377"
        assert find_chebi_by_xref("KEGG.COMPOUND:C00031") == "CHEBI:17234"

    def test_find_xref_not_found(self, mock_mappings_file):
        """Test lookup with non-existent xref."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("cas:999-99-9") is None

    def test_find_empty_xref(self, mock_mappings_file):
        """Test lookup with empty xref."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_xref("") is None
        assert find_chebi_by_xref(None) is None


class TestGetCanonicalName:

    """Test getting canonical name for ChEBI ID."""

    def test_get_canonical_name(self, mock_mappings_file):
        """Test getting canonical name."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_canonical_name("CHEBI:15377") == "water"
        assert get_canonical_name("CHEBI:17234") == "glucose"

    def test_get_canonical_name_not_found(self, mock_mappings_file):
        """Test with non-existent ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_canonical_name("CHEBI:99999") is None

    def test_get_canonical_name_empty(self, mock_mappings_file):
        """Test with empty ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_canonical_name("") is None
        assert get_canonical_name(None) is None


class TestGetSynonyms:

    """Test getting synonyms for ChEBI ID."""

    def test_get_synonyms(self, mock_mappings_file):
        """Test getting synonyms."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        synonyms = get_synonyms("CHEBI:15377")
        assert "H2O" in synonyms
        assert "dihydrogen oxide" in synonyms
        assert "oxidane" in synonyms

    def test_get_synonyms_not_found(self, mock_mappings_file):
        """Test with non-existent ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_synonyms("CHEBI:99999") == []

    def test_get_synonyms_empty(self, mock_mappings_file):
        """Test with empty ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_synonyms("") == []
        assert get_synonyms(None) == []


class TestGetXrefs:

    """Test getting cross-references for ChEBI ID."""

    def test_get_xrefs(self, mock_mappings_file):
        """Test getting xrefs."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        xrefs = get_xrefs("CHEBI:15377")
        assert "cas:7732-18-5" in xrefs
        assert "kegg.compound:C00001" in xrefs

    def test_get_xrefs_not_found(self, mock_mappings_file):
        """Test with non-existent ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_xrefs("CHEBI:99999") == []

    def test_get_xrefs_empty(self, mock_mappings_file):
        """Test with empty ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_xrefs("") == []
        assert get_xrefs(None) == []


class TestGetFormula:

    """Test getting formula for ChEBI ID."""

    def test_get_formula(self, mock_mappings_file):
        """Test getting formula."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_formula("CHEBI:15377") == "H2O"
        assert get_formula("CHEBI:17234") == "C6H12O6"

    def test_get_formula_not_found(self, mock_mappings_file):
        """Test with non-existent ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_formula("CHEBI:99999") is None

    def test_get_formula_empty(self, mock_mappings_file):
        """Test with empty ChEBI ID."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert get_formula("") is None
        assert get_formula(None) is None


class TestChemicalMappingLoader:

    """Test ChemicalMappingLoader class."""

    def test_loader_initialization(self, mock_mappings_file):
        """Test loader initializes correctly."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        assert loader.mappings_path == mock_mappings_file
        # Check that mappings are loaded
        assert chemical_mapping_utils._UNIFIED_MAPPINGS is not None

    def test_loader_find_by_name(self, mock_mappings_file):
        """Test loader find_chebi_by_name method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        assert loader.find_chebi_by_name("water") == "CHEBI:15377"
        assert loader.find_chebi_by_name("dextrose") == "CHEBI:17234"

    def test_loader_find_by_formula(self, mock_mappings_file):
        """Test loader find_chebi_by_formula method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        result = loader.find_chebi_by_formula("H2O")
        assert "CHEBI:15377" in result

    def test_loader_find_by_xref(self, mock_mappings_file):
        """Test loader find_chebi_by_xref method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        assert loader.find_chebi_by_xref("cas:7732-18-5") == "CHEBI:15377"

    def test_loader_get_canonical_name(self, mock_mappings_file):
        """Test loader get_canonical_name method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        assert loader.get_canonical_name("CHEBI:15377") == "water"

    def test_loader_get_synonyms(self, mock_mappings_file):
        """Test loader get_synonyms method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        synonyms = loader.get_synonyms("CHEBI:15377")
        assert "H2O" in synonyms

    def test_loader_get_xrefs(self, mock_mappings_file):
        """Test loader get_xrefs method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        xrefs = loader.get_xrefs("CHEBI:15377")
        assert "cas:7732-18-5" in xrefs

    def test_loader_get_formula(self, mock_mappings_file):
        """Test loader get_formula method."""
        loader = ChemicalMappingLoader(mock_mappings_file)
        assert loader.get_formula("CHEBI:15377") == "H2O"
