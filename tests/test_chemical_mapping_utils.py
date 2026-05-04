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
        """Loader returns the distinct entity count and populates lookup indices."""
        count = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert count == 4
        # Public API confirms indices are built
        assert find_chebi_by_name("water") == "CHEBI:15377"
        assert get_canonical_name("CHEBI:17234") == "glucose"
        assert get_formula("CHEBI:16240") == "H2O2"

    def test_load_caching(self, mock_mappings_file):
        """Repeated loads reuse the cached indices and skip re-parsing the file."""
        count1 = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        index_ref = chemical_mapping_utils._CANONICAL_NAME_INDEX
        count2 = chemical_mapping_utils.load_unified_mappings(mock_mappings_file)
        assert count1 == count2 == 4
        # Index object identity proves the second call hit the cache path
        assert chemical_mapping_utils._CANONICAL_NAME_INDEX is index_ref

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
        assert chemical_mapping_utils._LOADED is True
        assert chemical_mapping_utils._ENTITY_COUNT > 0

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
        other = tmp_path / "other.sssom.tsv.gz"
        _write_mock_sssom(
            [
                {
                    "id": "CHEBI:99999",
                    "category": "biolink:ChemicalEntity",
                    "canonical_name": "not_a_real_chemical",
                    "formula": "",
                    "synonyms": "",
                    "xrefs": "",
                    "sources": "test",
                }
            ],
            other,
        )

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


class TestFuzzyHydrate:

    """Hydrate-suffix retry behavior in ``find_chebi_by_name``."""

    @pytest.fixture
    def hydrate_mappings_file(self, tmp_path):
        """Build mappings where one entry carries an explicit hydrate suffix in its canonical name."""
        path = tmp_path / "hydrate.sssom.tsv.gz"
        _write_mock_sssom(
            [
                # Entry 1: canonical has no hydrate; users may query with one.
                {
                    "id": "CHEBI:3312",
                    "category": "biolink:ChemicalEntity",
                    "canonical_name": "calcium chloride",
                    "formula": "CaCl2",
                    "synonyms": "",
                    "xrefs": "cas:10043-52-4",
                    "sources": "hydrate_test",
                },
                # Entry 2: canonical has an explicit hydrate suffix; users may query without.
                {
                    "id": "KGM:calcium-chloride-nhydrate",
                    "category": "biolink:ChemicalEntity",
                    "canonical_name": "calcium chloride x n H2O",
                    "formula": "",
                    "synonyms": "",
                    "xrefs": "",
                    "sources": "hydrate_test",
                },
            ],
            path,
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


class TestNarrowMatchChildResolution:

    """
    Regression tests for the asymmetric-MIM child-CURIE resolution path.

    Codex adversarial review #558 round 3 found that prior versions of
    ``scripts/consolidate_chemical_mappings.load_mediaingredientmech_sssom``
    fed asymmetric (skos:narrowMatch / broadMatch) rows through
    ``add_chemical(id=object_id, ...)``, polluting the broader parent's
    synonym/xref table with the child's labels. Name lookup then returned
    the parent CURIE, the new ``_PARENT_INDEX`` was keyed under the child
    CURIE that the lookup never landed on, and the MediaDive subclass-edge
    emission was effectively unreachable.

    These tests exercise the committed unified mapping file (not a mock)
    and check end-to-end that representative MIM-curated child terms now:

      1. Resolve to the kg-microbe-minted child primary, not the parent.
      2. Carry their parent in ``get_parents()`` so MediaDive can emit
         ``biolink:subclass_of`` edges on the next merge.

    If a future consolidator regression re-pollutes parents with child
    labels, the assertions for resolution-to-child will start returning
    the parent CURIE again and these tests will fail loudly.
    """

    def test_vermont_soil_resolves_to_child(self):
        """Vermont Soil should resolve to its kgmicrobe child, not ENVO:00001998 (soil)."""
        # Use the committed mappings (not a mock) so we exercise the real
        # consolidator output rather than reproducing its logic in the test.
        chemical_mapping_utils._LOADED = False
        cid = chemical_mapping_utils.find_chebi_by_name("Vermont Soil")
        assert cid == "kgmicrobe.ingredient:vermont_soil", (
            f"expected kgmicrobe.ingredient:vermont_soil, got {cid!r} "
            "(asymmetric-MIM pollution likely re-introduced — see "
            "scripts/consolidate_chemical_mappings.py purge_asymmetric_pollution)"
        )
        assert chemical_mapping_utils.get_parents(cid) == ["ENVO:00001998"]

    def test_beef_brain_powder_resolves_to_child(self):
        """Beef brain powder should resolve to the kgmicrobe ingredient, not the FOODON parent."""
        chemical_mapping_utils._LOADED = False
        cid = chemical_mapping_utils.find_chebi_by_name("Beef brain powder")
        assert cid == "kgmicrobe.ingredient:beef_brain_powder", (
            f"expected kgmicrobe.ingredient:beef_brain_powder, got {cid!r}"
        )
        assert chemical_mapping_utils.get_parents(cid) == ["FOODON:02020911"]

    def test_actinomycin_a_resolves_to_child(self):
        """Actinomycin A should resolve to the kgmicrobe.compound, not CHEBI:15369."""
        chemical_mapping_utils._LOADED = False
        cid = chemical_mapping_utils.find_chebi_by_name("Actinomycin A")
        assert cid == "kgmicrobe.compound:actinomycin_a", (
            f"expected kgmicrobe.compound:actinomycin_a, got {cid!r}"
        )
        assert chemical_mapping_utils.get_parents(cid) == ["CHEBI:15369"]


class TestHydrateEquivalents:

    """
    Regression tests for ``get_hydrate_equivalents``.

    Anhydrous and hydrated forms of a salt are different chemical
    entities (different formula, different molecular weight) but are
    media-recipe interchangeable. The consolidator emits
    ``skos:closeMatch`` rows for known pairs (e.g. CaCl2 ↔ CaCl2·2H2O)
    with ``comment == 'recipe_equivalent_hydrate'``, and the runtime
    reader exposes them through ``get_hydrate_equivalents`` for use by
    recipe comparators.

    The relationship is symmetric: looking up either form returns the
    other. Distinct from ``get_xrefs`` which asserts chemical identity.
    """

    def test_lookup_returns_recipe_equivalent_pair(self):
        """A known anhydrous CHEBI returns its hydrated companion."""
        chemical_mapping_utils._LOADED = False
        # CHEBI:32149 (Na2SO4) ↔ CHEBI:32586 (Na2SO4·10H2O) — committed
        # in the unified mapping via the mediadive_compounds_hydrate path.
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:32149")
        assert equivs == ["CHEBI:32586"], (
            f"expected ['CHEBI:32586'], got {equivs!r} "
            "(consolidator hydrate-pair emission likely regressed)"
        )

    def test_lookup_is_symmetric(self):
        """The reverse direction returns the original CURIE — closeMatch is symmetric."""
        chemical_mapping_utils._LOADED = False
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:32586")
        assert "CHEBI:32149" in equivs

    def test_unknown_curie_returns_empty(self):
        """A CURIE with no hydrate pair returns an empty list, not None."""
        chemical_mapping_utils._LOADED = False
        # CHEBI:15377 (water) has no hydrate-pair partner.
        equivs = chemical_mapping_utils.get_hydrate_equivalents("CHEBI:15377")
        assert equivs == []

    def test_get_xrefs_does_not_contain_hydrate_partner(self):
        """
        Hydrate pairs are NOT exactMatch — they must not leak into xrefs.

        Regression guard for the prior behavior where the hydrate loader
        appended hydrated_chebi to xrefs (incorrectly asserting chemical
        identity). xref readers should now see only true exactMatch
        cross-references.
        """
        chemical_mapping_utils._LOADED = False
        xrefs = chemical_mapping_utils.get_xrefs("CHEBI:32149")
        assert "CHEBI:32586" not in xrefs, (
            "CHEBI:32586 (hydrated form) leaked into xrefs of CHEBI:32149 "
            "(anhydrous) — must be in get_hydrate_equivalents instead"
        )


class TestKnownBadFilters:

    """
    Regression guards for the consolidator's KNOWN_BAD_* filter lists.

    Two upstream curation bugs surfaced in PR #559 review and were
    filtered at consolidator export time. These tests assert the bad data
    stays out of the unified SSSOM. If a future consolidator change
    accidentally drops the filters, these tests fail loudly.
    """

    def test_polluted_pubchem_mega_node_dropped(self):
        """``pubchem.compound:167312541`` (the peptone+casamino-acids merge) is gone."""
        chemical_mapping_utils._LOADED = False
        chemical_mapping_utils.load_unified_mappings()
        # The mega-node should not appear as either a primary id (with a
        # canonical name index entry) nor as the target of any synonym
        # row. Lookups for the distinct ingredients should NOT resolve to
        # this CURIE.
        assert chemical_mapping_utils.get_canonical_name(
            "pubchem.compound:167312541"
        ) is None
        assert chemical_mapping_utils.find_chebi_by_name("Peptone") != "pubchem.compound:167312541"
        assert chemical_mapping_utils.find_chebi_by_name(
            "Vitamin-free casamino acids"
        ) != "pubchem.compound:167312541"

    def test_wrong_chebi_hydrate_xref_dropped(self):
        """
        CHEBI:32599 ↔ CHEBI:31795 false ``skos:exactMatch`` xref is gone.

        CHEBI:32599 is anhydrous magnesium sulfate; CHEBI:31795 is the
        heptahydrate. Different formulas, different molecular weights —
        not the same entity. The recipe-equivalent ``closeMatch`` row
        (with comment=recipe_equivalent_hydrate) is the only relationship
        between them that the unified SSSOM should carry.
        """
        chemical_mapping_utils._LOADED = False
        xrefs_32599 = set(chemical_mapping_utils.get_xrefs("CHEBI:32599"))
        xrefs_31795 = set(chemical_mapping_utils.get_xrefs("CHEBI:31795"))
        assert "CHEBI:31795" not in xrefs_32599, (
            "CHEBI:31795 (heptahydrate) re-appeared as exactMatch xref of "
            "CHEBI:32599 (anhydrous) — KNOWN_BAD_XREF_PAIRS filter regressed"
        )
        assert "CHEBI:32599" not in xrefs_31795, (
            "Reverse direction also re-appeared — filter regressed"
        )


class TestNamePrecedence:

    """
    Regression tests for canonical-vs-synonym name index precedence.

    The unified SSSOM is exported sorted by ``object_id``, so a naive
    first-row-wins index lets a low-numbered CHEBI hijack a name via its
    synonym list before the higher-numbered CHEBI's canonical row is
    reached. The fix tracks a per-name rank (0=canonical, 1=synonym) and
    only overwrites when the new row has strictly better rank.
    """

    def test_perillyl_alcohol_resolves_to_canonical(self):
        """
        ``perillyl alcohol`` resolves to the canonical CHEBI, not a synonym hit.

        ``perillyl alcohol`` is the canonical name of CHEBI:15420 and
        also appears as a synonym of CHEBI:10782. Because the SSSOM is
        sorted by object_id, CHEBI:10782 is processed first and would
        win under setdefault() first-row-wins. The rank-aware indexer
        must overwrite when CHEBI:15420's canonical row arrives.
        """
        chemical_mapping_utils._LOADED = False
        cid = chemical_mapping_utils.find_chebi_by_name("perillyl alcohol")
        assert cid == "CHEBI:15420", (
            f"expected CHEBI:15420 (canonical), got {cid!r} — "
            "name index precedence regressed: synonym hit hijacked the "
            "canonical-name lookup. See _index_name(rank=...) in "
            "kg_microbe/utils/chemical_mapping_utils.py."
        )

    def test_canonical_name_index_ranks_canonical_above_synonym(self):
        """``_CANONICAL_NAME_INDEX`` should resolve to the canonical owner."""
        chemical_mapping_utils._LOADED = False
        chemical_mapping_utils.load_unified_mappings()
        canonical = chemical_mapping_utils._CANONICAL_NAME_INDEX.get("perillyl alcohol")
        assert canonical == "CHEBI:15420"
