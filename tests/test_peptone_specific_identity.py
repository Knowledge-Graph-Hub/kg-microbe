"""Distinct recipe ingredients must retain their reviewed MIM identities."""

import csv
import gzip
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as mapping
from kg_microbe.utils.ingredient_identity import ingredient_xref_allowed


@pytest.fixture
def peptone_mappings(tmp_path, monkeypatch):
    """Reproduce broad-class synonyms sorting before the reviewed MICRO terms."""
    path = tmp_path / "peptones.sssom.tsv"
    path.write_bytes((Path(__file__).parent / "resources/peptone_specific_identity.sssom.tsv").read_bytes())
    monkeypatch.setattr(mapping, "_LOADED", False)
    mapping.load_unified_mappings(path)
    yield path
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)


def test_casein_digest_ingredients_remain_distinct_in_the_same_recipe(peptone_mappings):
    """Solution 2722 requires 5 g of each ingredient, not one collapsed 5 g edge."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    transform.translation_table = {}
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=mapping.find_chebi_by_name)
    transform.compound_mappings = {}
    transform.compounds_data = {}
    transform.solutions_data = {
        "2722": {
            "recipe": [
                {"compound_id": 71, "compound": "Tryptone", "amount": 5, "unit": "g"},
                {"compound_id": 101, "compound": "Casamino acids", "amount": 5, "unit": "g"},
            ]
        }
    }
    ingredients = transform.get_compounds_of_solution("2722")
    assert ingredients["Tryptone"]["id"] == "MICRO:0000182"
    assert ingredients["Casamino acids"]["id"] == "FOODON:03315719"
    assert len({(item["id"], item["amount"], item["unit"]) for item in ingredients.values()}) == 2


def test_trypticase_keeps_its_reviewed_specific_identity(peptone_mappings):
    """The broader milk-protein class must not outrank the curated peptone."""
    assert mapping.find_chebi_by_name("Trypticase") == "MICRO:0000175"
    assert mapping.find_chebi_by_name("mammalian milk protein (hydrolyzed)") == "FOODON:03315719"


@pytest.mark.parametrize("specific", ["MICRO:0000175", "MICRO:0000182"])
def test_peptone_and_broader_milk_protein_are_not_equivalent(specific):
    """Do not reintroduce the conflation through symmetric xref propagation."""
    assert not ingredient_xref_allowed(specific, "FOODON:03315719")
    assert not ingredient_xref_allowed("FOODON:03315719", specific)


def test_identity_rejection_preserves_a_broader_parent(peptone_mappings):
    """Reject equivalence without deleting the legitimate asymmetric parent relation."""
    assert mapping.get_parents("MICRO:0000182") == ["FOODON:03315719"]
    assert "MICRO:0000182" not in mapping.get_xrefs("FOODON:03315719")


def test_bounded_refresh_preserves_broader_parent_rows(peptone_mappings, tmp_path, monkeypatch):
    """Policy refresh must retain broader relations even when that pair is not equivalent."""
    from tests.test_consolidate_chemical_mappings import _load_module

    module = _load_module()
    monkeypatch.setattr(module.ChemicalMappingConsolidator, "_validate_sssom_file", lambda path: None)
    output = tmp_path / "refreshed.tsv.gz"
    module.refresh_identity_policy(peptone_mappings, output)
    with gzip.open(output, "rt") as handle:
        rows = list(csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t"))
    pairs = [row for row in rows if row["subject_id"] == "MICRO:0000182" and row["object_id"] == "FOODON:03315719"]
    assert [row["predicate_id"] for row in pairs] == ["skos:broadMatch"]
