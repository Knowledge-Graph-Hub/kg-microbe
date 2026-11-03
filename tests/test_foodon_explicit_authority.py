"""Explicit FOODON authority controls every public category lookup (#1430)."""

import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.utils import foodon_classification as policy
from kg_microbe.utils.ontology_resolution import foodon_category
from kg_microbe.utils.ontology_utils import get_foodon_category

FIXTURES = Path(__file__).parent / "resources"
NATIVE = FIXTURES / "foodon_category_ancestry.json"
EXPLICIT = FIXTURES / "foodon_explicit_authority"
LOOKUPS = [policy.authoritative_foodon_category, foodon_category, get_foodon_category]


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("checkout_present", [False, True])
@pytest.mark.parametrize("identifier", ["FOODON:00004038", "FOODON:03411744", "FOODON:00002894", "FOODON:unknown"])
def test_missing_authority_never_depends_on_checkout(lookup, checkout_present, identifier, tmp_path, monkeypatch):
    """Process, curated organism, anatomical and unknown IDs all require explicit input."""
    monkeypatch.setattr(policy, "FOODON_GRAPH", NATIVE if checkout_present else tmp_path / "absent.json")
    with pytest.raises(ValueError, match="exactly one explicit FOODON authority"):
        lookup(identifier)


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("identifier", ["FOODON:00004038", "FOODON:03411744", "FOODON:00002894", "FOODON:unknown"])
def test_missing_selected_path_never_falls_back(lookup, identifier, tmp_path, monkeypatch):
    """A missing selected file fails for every branch, even with checkout data available."""
    monkeypatch.setattr(policy, "FOODON_GRAPH", NATIVE)
    with pytest.raises(FileNotFoundError, match="FOODON category authority.*absent.json"):
        lookup(identifier, path=tmp_path / "absent.json")


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("route", ["path", "categories"])
def test_native_branch_classifications_survive_public_wrappers(lookup, route):
    """Explicit input preserves food, organism, process, quality and information semantics."""
    authority = (
        {"path": NATIVE}
        if route == "path"
        else {"categories": policy.foodon_categories(json.loads(NATIVE.read_text())["graphs"])}
    )
    expected = {
        "FOODON:03307083": "biolink:Food",
        "FOODON:00001155": "biolink:OrganismTaxon",
        "FOODON:00004038": "biolink:Activity",
        "FOODON:03430105": "biolink:PhenotypicQuality",
        "FOODON:03510198": "biolink:InformationContentEntity",
        "OBO:COB_0000022": "biolink:OrganismTaxon",
    }
    assert {identifier: lookup(identifier, **authority) for identifier in expected} == expected


@pytest.mark.parametrize("lookup", LOOKUPS)
def test_selected_raw_roots_have_independent_category_decisions(lookup, tmp_path, monkeypatch):
    """Synthetic conflicting roots expose both checkout leakage and path-insensitive caching."""
    paths = []
    for name in ("food", "activity"):
        raw = tmp_path / name / "raw"
        raw.mkdir(parents=True)
        path = raw / "foodon.json"
        shutil.copyfile(EXPLICIT / f"{name}.json", path)
        paths.append(path)
    foreign = tmp_path / "checkout.json"
    foreign.write_text("Must not read checkout authority")
    monkeypatch.setattr(policy, "FOODON_GRAPH", foreign)
    assert lookup("FOODON:fixture", path=paths[0]) == "biolink:Food"
    assert lookup("FOODON:fixture", path=paths[1]) == "biolink:Activity"
    assert lookup("FOODON:fixture", path=paths[0]) == "biolink:Food"


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("identifier", ["FOODON:unknown", "FOODON:retired", "FOODON:property"])
def test_invalid_or_undeclared_selected_class_is_not_food(lookup, identifier):
    """An explicit path cannot authorize missing, retired or nonclass identifiers."""
    with pytest.raises(ValueError, match="No live FOODON CLASS declaration"):
        lookup(identifier, path=EXPLICIT / "food.json")


@pytest.mark.parametrize("lookup", LOOKUPS)
@pytest.mark.parametrize("categories", [{}, {"FOODON:fixture": "biolink:Food"}])
def test_partial_category_mapping_cannot_authorize_unlisted_class(lookup, categories, monkeypatch):
    """An empty or finite admitted mapping never becomes a complete default authority."""
    monkeypatch.setattr(policy, "FOODON_GRAPH", NATIVE)
    with pytest.raises(ValueError, match="No live FOODON CLASS declaration"):
        lookup("FOODON:00004038", categories=categories)


@pytest.mark.parametrize("lookup", LOOKUPS)
def test_two_supplied_authorities_are_ambiguous(lookup):
    """Conflicting native and admitted decisions must not silently choose one input."""
    with pytest.raises(ValueError, match="exactly one explicit FOODON authority"):
        lookup("FOODON:00004038", path=NATIVE, categories={"FOODON:00004038": "biolink:Food"})
