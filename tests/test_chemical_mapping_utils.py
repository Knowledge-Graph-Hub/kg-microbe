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


_SSSOM_COLUMNS = [
    "subject_id", "subject_label", "predicate_id",
    "object_id", "object_label", "object_source",
    "mapping_justification", "source", "mapping_date",
    "confidence", "comment",
    "object_formula", "object_category",
]


def _write_mock_sssom(entries, path: Path):
    """
    Serialise a list of entity dicts into a minimal SSSOM mapping set.

    Each entry is a dict with keys ``id``, ``category``, ``canonical_name``,
    ``formula``, ``synonyms`` (pipe-delimited), ``xrefs`` (pipe-delimited),
    ``sources`` (pipe-delimited). The exporter mirrors ``export_unified_sssom``
    (see scripts/consolidate_chemical_mappings.py): one row per xref, one
    canonical-name row via ``kgm.name:<slug>``, one synonym row per synonym.
    """
    header = [
        "# curie_map:",
        '#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"',
        '#   cas: "https://bioregistry.io/cas:"',
        '#   kegg.compound: "https://bioregistry.io/kegg.compound:"',
        '#   pubchem.compound: "https://bioregistry.io/pubchem.compound:"',
        '#   obo: "http://purl.obolibrary.org/obo/"',
        '#   skos: "http://www.w3.org/2004/02/skos/core#"',
        '#   semapv: "https://w3id.org/semapv/vocab/"',
        '#   kgm.name: "https://w3id.org/kg-microbe/name/"',
        '# license: "https://creativecommons.org/publicdomain/zero/1.0/"',
        '# mapping_set_id: "https://w3id.org/sssom/mappings/kg_microbe_unified_ingredients_test"',
        '# mapping_set_version: "2026-04-20"',
        '# mapping_date: "2026-04-20"',
    ]

    def _slug(name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")

    rows = []
    for entry in entries:
        obj_id = entry["id"]
        obj_label = entry.get("canonical_name", "")
        obj_formula = entry.get("formula", "")
        obj_category = entry.get("category", "")
        obj_source = (
            "obo:chebi.owl" if obj_id.startswith("CHEBI:")
            else f"obo:{obj_id.split(':', 1)[0].lower()}.owl"
        )
        source_tag = entry.get("sources", "")

        for xref in entry.get("xrefs", "").split("|"):
            if not xref:
                continue
            rows.append({
                "subject_id": xref,
                "subject_label": "",
                "predicate_id": "skos:exactMatch",
                "object_id": obj_id,
                "object_label": obj_label,
                "object_source": obj_source,
                "mapping_justification": "semapv:UnspecifiedMatching",
                "source": source_tag,
                "mapping_date": "2026-04-20",
                "confidence": "",
                "comment": "",
                "object_formula": obj_formula,
                "object_category": obj_category,
            })

        if obj_label:
            rows.append({
                "subject_id": f"kgm.name:{_slug(obj_label)}",
                "subject_label": obj_label,
                "predicate_id": "skos:exactMatch",
                "object_id": obj_id,
                "object_label": obj_label,
                "object_source": obj_source,
                "mapping_justification": "semapv:LexicalMatching",
                "source": source_tag,
                "mapping_date": "2026-04-20",
                "confidence": "",
                "comment": "canonical_name",
                "object_formula": obj_formula,
                "object_category": obj_category,
            })

        for syn in entry.get("synonyms", "").split("|"):
            syn = syn.strip()
            if not syn or syn == obj_label:
                continue
            rows.append({
                "subject_id": f"kgm.name:{_slug(syn)}",
                "subject_label": syn,
                "predicate_id": "skos:closeMatch",
                "object_id": obj_id,
                "object_label": obj_label,
                "object_source": obj_source,
                "mapping_justification": "semapv:LexicalMatching",
                "source": source_tag,
                "mapping_date": "2026-04-20",
                "confidence": "",
                "comment": "synonym",
                "object_formula": obj_formula,
                "object_category": obj_category,
            })

    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for line in header:
            fh.write(line + "\n")
        fh.write("\t".join(_SSSOM_COLUMNS) + "\n")
        for row in rows:
            fh.write("\t".join(str(row.get(c, "")) for c in _SSSOM_COLUMNS) + "\n")


@pytest.fixture
def mock_mappings_file():
    """Create a temporary mock unified SSSOM mappings file."""
    entries = [
        {
            "id": "CHEBI:15377",
            "category": "biolink:ChemicalSubstance",
            "canonical_name": "water",
            "formula": "H2O",
            "synonyms": "H2O|dihydrogen oxide|oxidane",
            "xrefs": "cas:7732-18-5|kegg.compound:C00001",
            "sources": "chebi_xrefs|mediadive_compounds",
        },
        {
            "id": "CHEBI:17234",
            "category": "biolink:ChemicalSubstance",
            "canonical_name": "glucose",
            "formula": "C6H12O6",
            "synonyms": "D-glucose|dextrose|grape sugar",
            "xrefs": "cas:50-99-7|kegg.compound:C00031|pubchem.compound:5793",
            "sources": "chebi_xrefs|primary_mappings[kegg_compound]",
        },
        {
            "id": "CHEBI:16240",
            "category": "biolink:ChemicalSubstance",
            "canonical_name": "hydrogen peroxide",
            "formula": "H2O2",
            "synonyms": "peroxide",
            "xrefs": "cas:7722-84-1|kegg.compound:C00027",
            "sources": "chebi_xrefs",
        },
        {
            "id": "CHEBI:17925",
            "category": "biolink:ChemicalSubstance",
            "canonical_name": "lactate",
            "formula": "C3H6O3",
            "synonyms": "lactic acid|2-hydroxypropanoic acid",
            "xrefs": "cas:79-33-4|kegg.compound:C00186",
            "sources": "bacdive_metabolites|chebi_xrefs",
        },
    ]

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".sssom.tsv.gz", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    _write_mock_sssom(entries, tmp_path)

    yield tmp_path

    tmp_path.unlink()


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level cache before each test."""
    def _reset():
        chemical_mapping_utils._LOADED = False
        chemical_mapping_utils._ENTITY_COUNT = 0
        chemical_mapping_utils._NAME_INDEX = None
        chemical_mapping_utils._CANONICAL_NAME_INDEX = None
        chemical_mapping_utils._HYDRATE_FREE_NAME_INDEX = None
        chemical_mapping_utils._FORMULA_INDEX = None
        chemical_mapping_utils._XREF_INDEX = None
        chemical_mapping_utils._CATEGORY_INDEX = None
        chemical_mapping_utils._PRIMARY_NAME_INDEX = None
        chemical_mapping_utils._PRIMARY_SYNONYMS_INDEX = None
        chemical_mapping_utils._PRIMARY_XREFS_INDEX = None
        chemical_mapping_utils._PRIMARY_FORMULA_INDEX = None
        chemical_mapping_utils._CACHED_PATH = None
        chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE.clear()

    _reset()
    yield
    _reset()


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
        assert "id" in df.columns
        assert "category" in df.columns
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


class TestStripStereochemistry:

    """Test stereochemistry prefix normalization."""

    def test_r_prefix(self):
        """Test (R)- prefix removal."""
        assert normalize_name("(R)-lactate", strip_stereochemistry=True) == "lactate"

    def test_s_prefix(self):
        """Test (S)- prefix removal."""
        assert normalize_name("(S)-lactate", strip_stereochemistry=True) == "lactate"

    def test_d_prefix(self):
        """Test D- prefix removal."""
        assert normalize_name("D-glucose", strip_stereochemistry=True) == "glucose"

    def test_l_prefix(self):
        """Test L- prefix removal."""
        assert normalize_name("L-alanine", strip_stereochemistry=True) == "alanine"

    def test_plus_prefix(self):
        """Test (+)- prefix removal."""
        assert normalize_name("(+)-lactate", strip_stereochemistry=True) == "lactate"

    def test_minus_prefix(self):
        """Test (-)- prefix removal."""
        assert normalize_name("(-)-lactate", strip_stereochemistry=True) == "lactate"

    def test_no_prefix_unchanged(self):
        """Names without stereochemistry prefixes are only lowercased/cleaned."""
        assert normalize_name("water", strip_stereochemistry=True) == "water"

    def test_strip_off_preserves_original(self):
        """Without strip_stereochemistry the prefixes survive (hyphens preserved)."""
        # (+)/(-) parentheses are stripped by general punctuation rules but hyphens remain.
        assert normalize_name("D-glucose") == "d-glucose"
        assert normalize_name("(R)-lactate") == "r-lactate"


class TestFuzzyStereochemistry:

    """Test fuzzy stereochemistry retry behavior in find_chebi_by_name."""

    def test_fuzzy_retry_finds_match(self, mock_mappings_file):
        """Fuzzy mode finds canonical after stripping stereochemistry prefix."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        # "(R)-lactate" normalizes to "r-lactate" (miss); stripping yields "lactate" (hit)
        assert find_chebi_by_name("(R)-lactate", fuzzy_stereochemistry=True) == "CHEBI:17925"

    def test_fuzzy_off_does_not_retry(self, mock_mappings_file):
        """Stereochemistry-prefixed miss stays a miss when fuzzy is off."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        # "(R)-lactate" is not in canonical names or synonyms; normal mode misses.
        assert find_chebi_by_name("(R)-lactate", fuzzy_stereochemistry=False) is None

    def test_fuzzy_retry_skipped_when_normalized_forms_equal(self, mock_mappings_file):
        """
        If the stripped form is identical to the unstripped form, no extra retry is done.

        We verify behavior: a plain name with no stereochemistry prefix still
        returns the canonical match — the fuzzy path short-circuits rather
        than double-looking-up.
        """
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        # "water" has no stereochemistry prefix so strip == noop; result is still a hit.
        assert find_chebi_by_name("water", fuzzy_stereochemistry=True) == "CHEBI:15377"
        # And for a definite miss, fuzzy_off and fuzzy_on behave the same.
        assert find_chebi_by_name("nonexistent", fuzzy_stereochemistry=True) is None
        assert find_chebi_by_name("nonexistent", fuzzy_stereochemistry=False) is None


class TestNegativeCache:

    """Test bounded negative-lookup cache behavior."""

    def test_miss_is_cached(self, mock_mappings_file):
        """Failed lookup is stored in the negative cache."""
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("not_a_real_chemical") is None
        norm = chemical_mapping_utils.normalize_name("not_a_real_chemical")
        # Cache key is (normalized_name, synonyms, fuzzy_stereochemistry, fuzzy_hydrate).
        assert (norm, True, False, False) in chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE

    def test_cache_cleared_on_reload(self, mock_mappings_file, tmp_path):
        """Reloading from a new mappings path clears the negative cache."""
        # First load, populate a miss.
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert find_chebi_by_name("not_a_real_chemical") is None
        assert len(chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE) >= 1

        # Build a second mappings file at a different path so the path-equality
        # short-circuit in load_unified_mappings does not skip the reload.
        other = tmp_path / "other.tsv.gz"
        df = pd.DataFrame(
            {
                "id": ["CHEBI:99999"],
                "category": ["biolink:ChemicalSubstance"],
                "canonical_name": ["not_a_real_chemical"],
                "formula": [""],
                "synonyms": [""],
                "xrefs": [""],
                "sources": ["test"],
            }
        )
        with gzip.open(other, "wt") as f:
            df.to_csv(f, sep="\t", index=False)

        chemical_mapping_utils.load_unified_mappings(other)
        # Cache is cleared on reload, and the previously-missing name now resolves.
        assert len(chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE) == 0
        assert find_chebi_by_name("not_a_real_chemical") == "CHEBI:99999"

    def test_cache_is_bounded(self, mock_mappings_file, monkeypatch):
        """Negative cache never exceeds the configured max size."""
        monkeypatch.setattr(chemical_mapping_utils, "_NEGATIVE_CACHE_MAX_SIZE", 5)
        chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        for i in range(20):
            find_chebi_by_name(f"no_such_chemical_{i}")
        assert len(chemical_mapping_utils._NEGATIVE_LOOKUP_CACHE) <= 5


def _write_gzipped_tsv(path: Path, data: dict) -> None:
    """Write a dict-of-columns as a gzipped TSV."""
    df = pd.DataFrame(data)
    with gzip.open(path, "wt") as f:
        df.to_csv(f, sep="\t", index=False)


class TestSchemaUpgrade:

    """Legacy ``chebi_id`` column still loads; canonical schema is ``id``."""

    def test_legacy_chebi_id_column_loads(self, tmp_path):
        """A fixture written with the old ``chebi_id`` column still resolves lookups."""
        legacy_path = tmp_path / "legacy.tsv.gz"
        _write_gzipped_tsv(
            legacy_path,
            {
                # No `id` column; legacy alias only.
                "chebi_id": ["CHEBI:15377"],
                "canonical_name": ["water"],
                "formula": ["H2O"],
                "synonyms": ["H2O|oxidane"],
                "xrefs": ["cas:7732-18-5"],
                "sources": ["legacy_test"],
            },
        )
        chemical_mapping_utils.load_unified_mappings(legacy_path)
        assert find_chebi_by_name("water") == "CHEBI:15377"
        assert find_chebi_by_name("oxidane") == "CHEBI:15377"


class TestFuzzyHydrate:

    """Hydrate-suffix retry behavior in ``find_chebi_by_name``."""

    @pytest.fixture
    def hydrate_mappings_file(self, tmp_path):
        """Build mappings where one entry carries an explicit hydrate suffix in its canonical name."""
        path = tmp_path / "hydrate.tsv.gz"
        _write_gzipped_tsv(
            path,
            {
                # Entry 1: canonical has no hydrate; users may query with one.
                # Entry 2: canonical has an explicit hydrate suffix; users may query without.
                "id": ["CHEBI:3312", "KGM:calcium-chloride-nhydrate"],
                "category": [
                    "biolink:ChemicalSubstance",
                    "biolink:ChemicalSubstance",
                ],
                "canonical_name": [
                    "calcium chloride",
                    "calcium chloride x n H2O",
                ],
                "formula": ["CaCl2", ""],
                "synonyms": ["", ""],
                "xrefs": ["cas:10043-52-4", ""],
                "sources": ["hydrate_test", "hydrate_test"],
            },
        )
        return path

    def test_query_with_hydrate_finds_anhydrous_canonical(self, hydrate_mappings_file):
        """Query "CaCl2 x 2 H2O" → hits entry whose canonical is "calcium chloride" (hydrate stripped from query)."""
        chemical_mapping_utils.load_unified_mappings(hydrate_mappings_file)
        # Stereochemistry-stripped form of "calcium chloride · 2 H2O" is "calcium chloride".
        assert (
            find_chebi_by_name("calcium chloride · 2 H2O", fuzzy_hydrate=True)
            == "CHEBI:3312"
        )

    def test_query_without_hydrate_finds_hydrated_canonical(self, hydrate_mappings_file):
        """Query without hydrate resolves via the hydrate-free canonical index."""
        chemical_mapping_utils.load_unified_mappings(hydrate_mappings_file)
        # "calcium chloride" alone should resolve via the hydrate-free canonical
        # index to the first matching entry. We accept either entry — both are
        # valid calcium chloride rows — but the lookup must not return None.
        result = find_chebi_by_name("calcium chloride", fuzzy_hydrate=True)
        assert result in {"CHEBI:3312", "KGM:calcium-chloride-nhydrate"}

    def test_fuzzy_hydrate_off_does_not_retry(self, hydrate_mappings_file):
        """A query with a hydrate suffix misses when ``fuzzy_hydrate=False``."""
        chemical_mapping_utils.load_unified_mappings(hydrate_mappings_file)
        assert (
            find_chebi_by_name("calcium chloride · 2 H2O", fuzzy_hydrate=False)
            is None
        )

    def test_fuzzy_hydrate_cache_key_is_distinct(self, hydrate_mappings_file):
        """
        Verify that ``fuzzy_hydrate`` is part of the negative-cache key.

        A miss cached with ``fuzzy_hydrate=False`` must not prevent a retry
        under ``fuzzy_hydrate=True`` from reaching the hydrate fallback path.
        """
        chemical_mapping_utils.load_unified_mappings(hydrate_mappings_file)
        # First call: misses and caches under fuzzy_hydrate=False.
        assert (
            find_chebi_by_name("calcium chloride · 2 H2O", fuzzy_hydrate=False)
            is None
        )
        # Second call: same name, fuzzy_hydrate=True — different cache key → hits.
        assert (
            find_chebi_by_name("calcium chloride · 2 H2O", fuzzy_hydrate=True)
            == "CHEBI:3312"
        )
