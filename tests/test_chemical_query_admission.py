"""Original query restrictions survive normalized and fuzzy resolution (#1151)."""

from collections import OrderedDict

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed


@pytest.mark.parametrize(
    "query,normalized,flags",
    [
        ("CoCl2 x 2 H2O", "cocl2", {"fuzzy_hydrate": True}),
        ("D-query", "query", {"fuzzy_stereochemistry": True}),
        ("CaseSensitive", "casesensitive", {}),
    ],
)
def test_original_query_is_checked_after_all_lookup_routes(monkeypatch, query, normalized, flags):
    """An allowed indexed alias cannot authorize a separately rejected query/target."""
    monkeypatch.setattr(runtime, "_LOADED", True)
    monkeypatch.setattr(runtime, "_NAME_INDEX", {normalized: "CHEBI:29365"})
    monkeypatch.setattr(runtime, "_NEGATIVE_LOOKUP_CACHE", OrderedDict())
    monkeypatch.setattr(runtime, "ingredient_name_target", lambda name: None)
    monkeypatch.setattr(runtime, "ingredient_case_sensitive_name_scope", lambda name: (False, None))
    monkeypatch.setattr(runtime, "ingredient_mapping_allowed", lambda name, target: name != query)
    assert runtime.find_chebi_by_name(query, **flags) is None
    assert runtime.find_chebi_by_name(normalized) == "CHEBI:29365"


def test_case_sensitive_rejection_does_not_poison_valid_formula(monkeypatch):
    """The same normalized name can have different original-query policy decisions."""
    monkeypatch.setattr(runtime, "_LOADED", True)
    monkeypatch.setattr(runtime, "_NAME_INDEX", {"cocl2": "CHEBI:29365"})
    monkeypatch.setattr(runtime, "_NEGATIVE_LOOKUP_CACHE", OrderedDict())
    monkeypatch.setattr(runtime, "ingredient_name_target", lambda name: None)
    monkeypatch.setattr(runtime, "ingredient_case_sensitive_name_scope", lambda name: (False, None))
    monkeypatch.setattr(runtime, "ingredient_mapping_allowed", lambda name, target: name != "CoCl2")
    assert runtime.find_chebi_by_name("CoCl2") is None
    assert runtime.find_chebi_by_name("COCl2") == "CHEBI:29365"
    assert runtime.find_chebi_by_name("CoCl2") is None


def test_reviewed_scope_cannot_override_identity_rejection(monkeypatch):
    """Even an explicit route must satisfy the independent negative identity policy."""
    monkeypatch.setattr(runtime, "_LOADED", True)
    monkeypatch.setattr(runtime, "_PRIMARY_NAME_INDEX", {"CHEBI:29365": "phosgene"})
    monkeypatch.setattr(runtime, "ingredient_name_target", lambda name: "CHEBI:29365")
    monkeypatch.setattr(runtime, "ingredient_mapping_allowed", lambda name, target: False)
    assert runtime.find_chebi_by_name("unreviewed specific material") is None


def test_query_padding_cannot_bypass_anchored_identity_policy():
    """Ignore outer whitespace consistently with the lookup and its negative cache."""
    assert not ingredient_mapping_allowed(" \tBerberine\n", "CHEBI:31271")
    assert ingredient_mapping_allowed(" \tBerberine chloride\n", "CHEBI:31271")
