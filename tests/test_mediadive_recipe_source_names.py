"""Recipe display normalization must not alter chemical lookup scope (#1167)."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_hydrate_identity import resolver


@pytest.mark.parametrize("route", ["compound", "solution"])
@pytest.mark.parametrize("mapping_route", ["unified", "legacy"])
def test_recipe_identity_uses_original_formula_and_preserves_cached_source(route, mapping_route):
    """Existing native-compatible tetrahydrate mappings survive display-only cleanup."""
    original = "Ca(NO3)2 x 4 H2O"
    target = "CHEBI:86159"
    calls = []

    def lookup(name):
        """Resolve only the independently supplied spelling, never a repaired formula."""
        calls.append(name)
        return target if mapping_route == "unified" and name == original else None

    value = resolver(legacy={original.lower(): target} if mapping_route == "legacy" else {})
    value.chemical_loader = SimpleNamespace(find_chebi_by_name=lookup)
    value.chebi_labels[target] = "calcium nitrate tetrahydrate"
    value.translation_table = str.maketrans("", "", "()")
    item = {route + "_id": 99, route: original, "amount": 2, "unit": "g", "g_l": 3, "mmol_l": 4}
    value.solutions_data = {"1": {"recipe": [item]}}
    before = deepcopy(value.solutions_data)
    expected = {"CaNO32 x 4 H2O": {"id": target, "amount": 2, "unit": "g", "g_l": 3, "mmol_l": 4}}
    assert value.get_compounds_of_solution("1") == expected
    assert value.get_compounds_of_solution("1") == expected
    assert value.solutions_data == before
    assert calls == [original, original]


@pytest.mark.parametrize("route", ["compound", "solution"])
def test_display_cleanup_cannot_remove_hydration_scope_before_admission(route):
    """A polluted alias still cannot assign the anhydrous parent after display cleanup."""
    value = resolver(unified="CHEBI:30808")
    value.translation_table = str.maketrans("", "", "()")
    original = "FeCl3 (hexahydrate)"
    value.solutions_data = {"1": {"recipe": [{route + "_id": 99, route: original}]}}
    item = value.get_compounds_of_solution("1")["FeCl3 hexahydrate"]
    prefix = "ingredient" if route == "compound" else "solution"
    assert item["id"] == "mediadive." + prefix + ":99"
    assert value.solutions_data["1"]["recipe"][0][route] == original
