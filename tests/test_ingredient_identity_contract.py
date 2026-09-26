"""Identity regressions for reviewed ingredient-to-authority mapping defects."""

import csv
import gzip
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils import chemical_mapping_utils as mapping
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed
from tests.test_consolidate_chemical_mappings import _load_module


@pytest.fixture
def identity_sssom(tmp_path, monkeypatch):
    """Provide a tiny stale mapping snapshot without reading developer data."""
    path = tmp_path / "identity.sssom.tsv"
    fixture = Path(__file__).parent / "resources/ingredient_identity_stale.sssom.tsv"
    path.write_bytes(fixture.read_bytes())
    monkeypatch.setattr(mapping, "_LOADED", False)
    mapping.load_unified_mappings(path)
    yield path
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)


def test_stale_unified_names_are_rejected_but_authority_identity_survives(identity_sssom):
    """Do not relabel the detergent or vegetable as a culture ingredient."""
    for name in ["Tryptone", "Bacto-tryptone", "Soyton", "Trypticase soy broth", "Casamino acids", "Proteose peptone"]:
        assert mapping.find_chebi_by_name(name) is None
    assert mapping.find_chebi_by_name("dodecylphosphocholine") == "CHEBI:78018"
    assert mapping.get_canonical_name("CHEBI:78018") == "dodecylphosphocholine"
    assert mapping.find_chebi_by_name("green kidney bean") == "FOODON:03302071"
    assert mapping.get_canonical_name("FOODON:03302071") == "green kidney bean"
    assert mapping.find_chebi_by_xref("MICRO:0000182") is None
    assert mapping.find_chebi_by_formula("C17H38NO4P") == ["CHEBI:78018"]
    assert mapping.find_chebi_by_name("heptacosanoate") == "CHEBI:78020"
    assert mapping.find_chebi_by_name("carbocerate") == "CHEBI:78020"
    assert mapping.get_canonical_name("CHEBI:78020") == "heptacosanoate"
    assert mapping.find_chebi_by_name("(R)-2,6-dimethylheptanoylcarnitine") == "CHEBI:84843"
    assert mapping.find_chebi_by_name("fresh bratwurst") == "FOODON:00002992"
    assert "carbocerate" not in mapping.get_synonyms("CHEBI:78018")


@pytest.mark.parametrize(
    "name,bad_id,route",
    [("Tryptone", "CHEBI:78018", route) for route in ("unified", "legacy", "embedded")]
    + [("Trypticase soy broth", "FOODON:03302071", route) for route in ("unified", "legacy")],
)
def test_mediadive_identity_guard_covers_all_fallback_routes(name, bad_id, route):
    """A stale secondary mapping must not restore a rejected identity."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: bad_id if route == "unified" else None
    )
    transform.compound_mappings = {name.lower(): bad_id} if route == "legacy" else {}
    transform.compounds_data = {"99": {"ChEBI": bad_id.split(":")[1]}} if route == "embedded" else {}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", name) == "mediadive.ingredient:99"


def test_consolidator_reseed_removes_rejected_names_and_xrefs(identity_sssom, monkeypatch):
    """Self-seeding must converge without resurrecting stale ingredient identity."""
    module = _load_module()
    monkeypatch.setattr(module, "_build_mangle_blacklist", lambda *_: set())
    consolidator = module.ChemicalMappingConsolidator()
    consolidator.load_existing_unified(identity_sssom)
    detergent = consolidator.chemicals["CHEBI:78018"]
    assert detergent["canonical_name"] == "dodecylphosphocholine"
    assert "Tryptone" not in detergent["synonyms"]
    assert "MICRO:0000182" not in detergent["xrefs"]
    bean = consolidator.chemicals["FOODON:03302071"]
    assert bean["canonical_name"] == "green kidney bean"
    assert "Trypticase soy broth" not in bean["synonyms"]


def test_mediadive_legacy_loader_filters_both_hydrate_and_strict(tmp_path):
    """Filter before deduplication, allowing a valid later mapping to survive."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    for name in ["compound_mappings_strict.tsv", "compound_mappings_strict_hydrate.tsv"]:
        path = tmp_path / name
        path.write_text(
            "original\tmapped\nTryptone\tCHEBI:78018\nTryptone\tMICRO:0000182\ndodecylphosphocholine\tCHEBI:78018\n"
        )
        loaded = transform._load_mapping_file(path, name)
        assert loaded["tryptone"] == "MICRO:0000182"
        assert loaded["dodecylphosphocholine"] == "CHEBI:78018"


def test_metatraits_and_manual_substrate_routes_do_not_assert_false_identity(identity_sssom):
    """Trait/manual producer calls use the same guarded runtime mapping reader."""
    loader = mapping.ChemicalMappingLoader(identity_sssom)
    traits = MetaTraitsTransform.__new__(MetaTraitsTransform)
    traits.chemical_loader = loader
    traits.special_chemical_mappings = {}
    traits.metpo_pattern_to_predicate = {"utilizes": {"positive": "METPO:2000012"}}
    assert traits._resolve_chemical_trait("utilizes: Tryptone") is None
    bad_special = {
        "curie": "CHEBI:78018",
        "name": "Tryptone",
        "category": "biolink:ChemicalEntity",
        "predicate": "METPO:2000012",
    }
    traits.special_chemical_mappings = {
        "utilizes: tryptone": bad_special,
        "tryptone": bad_special,
        "growth: tryptone": bad_special,
    }
    assert traits._resolve_chemical_trait("utilizes: Tryptone") is None
    assert traits._resolve_growth_substrate("growth: Tryptone") is None
    assert traits._resolve_required_for_growth("required for growth: Tryptone") is None
    assert traits._resolve_chemical_trait("utilizes: dodecylphosphocholine")["curie"] == "CHEBI:78018"
    decoder = MicrobeDecoderTransform.__new__(MicrobeDecoderTransform)
    decoder.chemical_loader = loader
    decoder._mint_placeholder = lambda label, *args, **kwargs: "kgmicrobe.compound:" + label.lower()
    assert (
        decoder._resolve_chemical_curie("Tryptone", csv.writer(io.StringIO()), "bergey:substrates")
        == "kgmicrobe.compound:tryptone"
    )


@pytest.mark.parametrize("route", ["unified", "legacy"])
def test_mediadive_nested_solution_keeps_specific_identity(route):
    """The solution-level mapping path must not restore a rejected mixture ID."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    transform.translation_table = {}
    transform.solutions_data = {
        "1": {"recipe": [{"solution_id": 2, "solution": "Trypticase soy broth", "amount": 5, "unit": "ml"}]}
    }
    transform.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: "FOODON:03302071" if route == "unified" else None
    )
    transform.compound_mappings = {"trypticase soy broth": "FOODON:03302071"} if route == "legacy" else {}
    assert transform.get_compounds_of_solution("1")["Trypticase soy broth"]["id"] == "mediadive.solution:2"


def test_other_groundings_and_propagation_do_not_reinstate_rejected_identity(monkeypatch):
    """Preserve a separately supported ingredient ID without equivalent detergent."""
    module = _load_module()
    monkeypatch.setattr(module, "_build_mangle_blacklist", lambda *_: set())
    consolidator = module.ChemicalMappingConsolidator()
    consolidator.add_chemical("MICRO:0000182", "Tryptone", xrefs=["CHEBI:78018"])
    consolidator.add_chemical("CHEBI:78018", "dodecylphosphocholine", xrefs=["MICRO:0000182"])
    consolidator.add_chemical("FOODON:03302071", "Soyton", synonyms=["green kidney bean", "Polypeptone"])
    consolidator.propagate_synonyms_via_xrefs()
    assert consolidator.chemicals["MICRO:0000182"]["canonical_name"] == "Tryptone"
    assert consolidator.chemicals["MICRO:0000182"]["xrefs"] == set()
    assert "Tryptone" not in consolidator.chemicals["CHEBI:78018"]["synonyms"]
    assert consolidator.name_index["tryptone"] == "MICRO:0000182"


def test_bounded_refresh_preserves_nonidentity_rows_and_is_a_fixed_point(identity_sssom, tmp_path, monkeypatch):
    """No source reload or enrichment can erase parent/hydrate rows in this mode."""
    module = _load_module()
    monkeypatch.setattr(module.ChemicalMappingConsolidator, "_validate_sssom_file", lambda path: None)
    with identity_sssom.open("a") as handle:
        handle.write("CHEBI:1\tparent\tskos:broadMatch\tCHEBI:2\tchild\t\t\tbiolink:ChemicalEntity\tfixture\n")
        handle.write(
            "CHEBI:3\tanhydrous\tskos:closeMatch\tCHEBI:4\thydrated\trecipe_equivalent_hydrate\t\tbiolink:ChemicalEntity\tfixture\n"
        )
    first, second = tmp_path / "first.tsv.gz", tmp_path / "second.tsv.gz"
    stats = module.refresh_identity_policy(identity_sssom, first)
    assert stats["rows_removed"] == 12
    module.refresh_identity_policy(first, second)
    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[-2]["predicate_id"] == "skos:broadMatch"
    assert rows[-1]["comment"] == "recipe_equivalent_hydrate"
    assert {row["object_id"] for row in rows} >= {"CHEBI:78018", "FOODON:03302071"}
    mapping.load_unified_mappings(first)
    assert mapping.get_canonical_name("CHEBI:78018") == "dodecylphosphocholine"
    assert mapping.get_canonical_name("FOODON:03302071") == "green kidney bean"
    assert mapping.get_canonical_name("CHEBI:78020") == "heptacosanoate"
    with pytest.raises(ValueError, match="separate candidate"):
        module.refresh_identity_policy(identity_sssom, identity_sssom)


def test_bounded_refresh_failure_does_not_replace_output(identity_sssom, tmp_path, monkeypatch):
    """Keep any previously validated candidate on validation failure."""
    module = _load_module()

    def fail(_path):
        """Simulate a validator rejecting the candidate before publication."""
        raise ValueError("invalid SSSOM")

    monkeypatch.setattr(module.ChemicalMappingConsolidator, "_validate_sssom_file", fail)
    output = tmp_path / "candidate.tsv.gz"
    output.write_bytes(b"previous candidate")
    with pytest.raises(ValueError, match="invalid SSSOM"):
        module.refresh_identity_policy(identity_sssom, output)
    assert output.read_bytes() == b"previous candidate"


@pytest.mark.parametrize(
    "name",
    ["Trypticase_soy_broth", "Trypticase-soy-broth", "animal_protein_hydrolyzed", "Animal  protein (hydrolyzed)"],
)
def test_producer_separator_variants_cannot_bypass_identity_policy(name):
    """Source-specific label normalization is not an identity exception."""
    assert not ingredient_mapping_allowed(name, "FOODON:03302071")
    assert ingredient_mapping_allowed(name, "MICRO:0000182")


def test_reader_normalization_does_not_bypass_reviewed_policy(identity_sssom):
    """Punctuation-normalized names and case-folded CURIE xrefs remain blocked."""
    assert not ingredient_mapping_allowed("Trypt.one", "CHEBI:78018")
    assert not ingredient_mapping_allowed("Tryptone", "chebi:78018")
    assert mapping.find_chebi_by_name("Tryptone") is None
    assert mapping.find_chebi_by_name("Trypt.one") is None
    assert mapping.find_chebi_by_xref("MICRO:0000182") is None
    assert mapping.find_chebi_by_name("dodecylphosphocholine") == "CHEBI:78018"


def test_deprecated_amino_acid_association_cannot_override_current_identity(tmp_path, monkeypatch):
    """Reject the stale acid/anion names without redirecting to an unrelated replacement."""
    source = Path(__file__).parent / "resources/deprecated_amino_acid.sssom.tsv"
    monkeypatch.setattr(mapping, "_LOADED", False)
    mapping.load_unified_mappings(source)
    assert mapping.find_chebi_by_name("3-aminobutyric acid") == "CHEBI:37081"
    assert mapping.find_chebi_by_name("3-aminobutyrate") is None
    assert mapping.find_chebi_by_xref("MIM:3-aminobutyric_Acid") == "CHEBI:37081"
    assert mapping.find_chebi_by_name("replacement control") == "CHEBI:17261"
    module = _load_module()
    monkeypatch.setattr(module.ChemicalMappingConsolidator, "_validate_sssom_file", lambda path: None)
    output = tmp_path / "corrected.tsv"
    result = module.refresh_identity_policy(source, output)
    assert result["rows_removed"] == 2
    assert "CHEBI:18309" not in output.read_text()
    assert "CHEBI:17261" in output.read_text()
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize(
    "name,slug,parent",
    [
        ("rhodomycin A", "rhodomycin_a", "mesh:C004977"),
        ("pluramycin A", "pluramycin_a", "mesh:C003169"),
        ("racemomycin E", "racemomycin_e", "mesh:C019594"),
    ],
)
def test_specific_metabolite_overrides_preserve_supported_registry(transform_type, name, slug, parent):
    """Both real trait routes retain the specific compound even with a stale family lookup."""
    transform = transform_type.__new__(transform_type)
    transform.special_chemical_mappings = transform._load_special_chemical_mappings()
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: parent)
    result = transform._resolve_chemical_trait("produces: " + name)
    assert result["curie"] == "kgmicrobe.compound:" + slug
    assert result["name"].casefold() == name.casefold()
    assert result["predicate"] == "METPO:2000202"
    assert not ingredient_mapping_allowed(name, parent)
    assert ingredient_mapping_allowed(name.rsplit(" ", 1)[0], parent)


def test_embedded_id_uses_raw_compound_name_when_caller_omits_name():
    """MediaDive bulk records store their labels under compound, not name."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.compounds_data = {"3": {"compound": "Tryptone", "ChEBI": "78018"}}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("3") == "mediadive.ingredient:3"
