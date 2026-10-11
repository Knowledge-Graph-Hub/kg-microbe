"""A retained nested solution keeps its source-owned recipe-mixture category."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import INGREDIENT_CATEGORY, NAMED_THING_CATEGORY, SOLUTION_CATEGORY
from kg_microbe.utils.pandas_utils import drop_duplicates
from tests.test_mediadive_recipe_occurrences import _resolver

FIXTURE = Path(__file__).parent / "resources/mediadive_nested_solution_6257.json"


@pytest.mark.parametrize("nested_first", [True, False])
def test_soil_extract_category_survives_both_declaration_orders(tmp_path, nested_first):
    """Nested and own-solution declarations must agree before node deduplication."""
    raw = json.loads(FIXTURE.read_text())["solutions"]
    transform = _resolver(raw)
    nested = transform.get_solution_recipe_occurrences("6194")[3]
    assert nested["id"] == "mediadive.solution:6257"
    assert json.loads(nested["source_record"]) == raw["6194"]["recipe"][3]
    assert nested["amount"] == 100 and nested["unit"] == "ml"
    category = transform._classify_ingredient_category(nested["id"], nested["name"])
    assert category == SOLUTION_CATEGORY
    transform.node_header = [
        "id",
        "category",
        "name",
        "description",
        "xref",
        "provided_by",
        "synonym",
        "deprecated",
        "same_as",
    ]
    transform.knowledge_source = "infores:mediadive"
    declarations = [
        transform._create_node_row(nested["id"], category, nested["name"]),
        transform._create_node_row(nested["id"], SOLUTION_CATEGORY, nested["name"]),
    ]
    if not nested_first:
        declarations.reverse()
    path = tmp_path / "nodes.tsv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(transform.node_header)
        writer.writerows(declarations)
    drop_duplicates(path, sort_by_column="id", dedup_on_sort_column=True)
    with path.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 1 and rows[0]["category"] == SOLUTION_CATEGORY


@pytest.mark.parametrize(
    "identifier", ["mediadive.ingredient:6257", "unknown.solution:6257", "KEGG:C00001", "PubChem:123"]
)
def test_other_unresolved_identities_do_not_become_solutions(identifier):
    """Only source-owned solution IDs receive the recipe-mixture category."""
    transform = _resolver({})
    assert transform._classify_ingredient_category(identifier, "unmapped material") == INGREDIENT_CATEGORY


def test_retained_solution_category_is_not_overridden_by_mapping_loader():
    """A generic external lookup cannot weaken a source-owned solution's type."""
    transform = _resolver({"6257": {"id": 6257, "name": "SE1 Soil Extract 1"}})
    transform.chemical_loader.get_category = lambda identifier: "biolink:ChemicalEntity"
    assert transform._classify_ingredient_category("mediadive.solution:6257", "SE1 Soil Extract 1") == SOLUTION_CATEGORY


@pytest.mark.parametrize("solution_id", [6420, 6572])
def test_absent_child_remains_named_unresolved_source_referent(solution_id):
    """Preserve the raw solution reference without asserting unverified composition (#1319)."""
    fixture = FIXTURE.with_name("mediadive_nested_solutions_without_child_recipes.json")
    observations = json.loads(fixture.read_text())["observations"]
    observation = next(item for item in observations if item["row"]["solution_id"] == solution_id)
    assert observation["child_recipe_available"] is False
    raw = observation["row"]
    transform = _resolver({})
    assert (
        transform._classify_ingredient_category(f"mediadive.solution:{solution_id}", raw["solution"])
        == NAMED_THING_CATEGORY
    )
    assert transform.solutions_data == {}  # Classification does not invent a missing recipe.
