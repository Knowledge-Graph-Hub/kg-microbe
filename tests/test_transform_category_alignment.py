"""Hermetic category alignment checks using real isolated source loaders (#1244)."""

import builtins
from collections import Counter
from pathlib import Path

import pytest
import requests

from kg_microbe.transform_utils.bacdive import bacdive as bacdive_module
from kg_microbe.transform_utils.constants import INGREDIENT_CATEGORY, METABOLITE_CATEGORY
from kg_microbe.transform_utils.mediadive import mediadive as mediadive_module

RESOURCE = Path(__file__).parent / "resources/transform_category_alignment/chebi_nodes.tsv"
EXPECTED = {
    "CHEBI:16828": "biolink:ChemicalEntity",
    "CHEBI:50906": "biolink:ChemicalRole",
    "CHEBI:60004": "biolink:ChemicalEntity",
}
PRODUCERS = {
    "bacdive": (bacdive_module, bacdive_module.BacDiveTransform, METABOLITE_CATEGORY),
    "mediadive": (mediadive_module, mediadive_module.MediaDiveTransform, INGREDIENT_CATEGORY),
}


@pytest.fixture(params=["absent", "populated"])
def category_loader(tmp_path, monkeypatch, request):
    """Exercise real loaders while rejecting full initialization and unrelated I/O."""
    immutable = RESOURCE.read_bytes()
    selected = tmp_path / "selected-chebi-nodes.tsv"
    selected.write_bytes(immutable)
    defaults = tmp_path / "unrelated-defaults"
    defaults.mkdir()
    if request.param == "populated":
        for relative in (
            "data/raw/mediadive/media_detailed.json",
            "data/raw/bacdive/record.yaml",
            "data/transformed/ontologies/chebi_nodes.tsv",
        ):
            path = defaults / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Poison default input: unit tests must never read this.\n")
    monkeypatch.chdir(defaults)
    opened = []
    forbidden = []
    real_open = builtins.open

    def reject_initialization(*args, **kwargs):
        """Reject full constructors, mapping/ontology setup and network requests."""
        forbidden.append("initialization or network")
        raise AssertionError("Category unit test invoked unrelated initialization or network")

    def category_only_open(path, mode="r", *args, **kwargs):
        """Admit only the selected fixture in read-only mode; never production files."""
        if Path(path).resolve() != selected.resolve() or mode not in ("r", "rt"):
            forbidden.append(str(path))
            raise AssertionError(f"Category unit test attempted unrelated file I/O: {path}")
        opened.append(str(Path(path).resolve()))
        return real_open(path, mode, *args, **kwargs)

    for module, producer, _ in PRODUCERS.values():
        monkeypatch.setattr(producer, "__init__", reject_initialization)
        monkeypatch.setattr(module, "CHEBI_NODES_FILE", selected)
        monkeypatch.setattr(module, "open", category_only_open, raising=False)
        monkeypatch.setattr(module, "ChemicalMappingLoader", reject_initialization)
    monkeypatch.setattr(requests.sessions.Session, "request", reject_initialization)

    def load(source, *, missing=False):
        """Call the unmodified loader without constructor side effects or stubbed results."""
        module, producer, _ = PRODUCERS[source]
        if missing:
            monkeypatch.setattr(module, "CHEBI_NODES_FILE", tmp_path / "missing-selected-category.tsv")
        value = producer.__new__(producer)
        value.chebi_categories = {}
        before = len(opened)
        value._load_chebi_categories()
        assert len(opened) == before + (0 if missing else 1)
        assert not forbidden, "A real loader swallowed an unrelated-I/O rejection"
        return value

    yield load
    assert forbidden == []
    assert selected.read_bytes() == immutable
    assert RESOURCE.read_bytes() == immutable


@pytest.mark.parametrize("source", PRODUCERS)
def test_loads_exact_native_category_fixture(category_loader, source):
    """Both real loaders must retain every fixture category, not only the default type."""
    assert category_loader(source).chebi_categories == EXPECTED


@pytest.mark.parametrize("source", PRODUCERS)
@pytest.mark.parametrize("identifier", EXPECTED)
def test_each_known_category_matches_native_fixture(category_loader, source, identifier):
    """Check all selected IDs so a loader returning only fallback ChemicalEntity fails."""
    assert category_loader(source)._get_chebi_category(identifier) == EXPECTED[identifier]


@pytest.mark.parametrize("source", PRODUCERS)
def test_exact_category_distribution(category_loader, source):
    """Use a finite fixture distribution, never a graph-scale count or conditional skip."""
    assert Counter(category_loader(source).chebi_categories.values()) == {
        "biolink:ChemicalEntity": 2,
        "biolink:ChemicalRole": 1,
    }


@pytest.mark.parametrize("source", PRODUCERS)
def test_unknown_identifier_uses_source_fallback(category_loader, source):
    """Unknown IDs retain each source-specific declared fallback contract."""
    assert category_loader(source)._get_chebi_category("CHEBI:99999999") == PRODUCERS[source][2]


@pytest.mark.parametrize("source", PRODUCERS)
def test_missing_selected_fixture_uses_fallback_without_default_input(category_loader, source):
    """A missing explicit category file never authorizes unrelated default data access."""
    value = category_loader(source, missing=True)
    assert value.chebi_categories == {}
    assert value._get_chebi_category("CHEBI:16828") == PRODUCERS[source][2]


@pytest.mark.parametrize("identifier", EXPECTED)
def test_mediadive_ingredient_classification_uses_native_category(category_loader, identifier):
    """The real ingredient classifier must preserve the selected ChEBI category."""
    assert (
        category_loader("mediadive")._classify_ingredient_category(identifier, "test compound") == EXPECTED[identifier]
    )
