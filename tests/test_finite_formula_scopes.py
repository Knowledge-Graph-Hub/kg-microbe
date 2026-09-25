"""Finite reviewed COCl2/CoCl2 identity routes, not general formula interpretation (#1151)."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils import ingredient_identity as identity
from kg_microbe.utils.ingredient_identity import (
    ingredient_case_sensitive_name_scope,
    ingredient_mapping_allowed,
    ingredient_name_scopes,
)
from scripts.mim_conservative_refresh import _candidate_name_lookup
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table


def _native_aliases():
    """Use immutable native label/alias evidence, never a live chemical service."""
    path = Path(__file__).parent / "resources/chemical_formula_aliases.tsv"
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _load_formulas(tmp_path, monkeypatch, declared):
    """Load independently declared native targets; a scope alone never declares a target."""
    rows = []
    for node in _native_aliases():
        if node["id"] not in declared:
            continue
        rows.extend(
            [
                _row("kgm.name:" + node["name"], node["id"], node["name"], name=node["name"], comment="canonical_name"),
                _row("kgm.name:" + node["synonym"], node["id"], node["name"], name=node["synonym"], comment="synonym"),
            ]
        )
    path = tmp_path / "native-formulas.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)


@pytest.mark.parametrize("queries", [("COCl2", "CoCl2"), ("CoCl2", "COCl2")])
@pytest.mark.parametrize("synonyms", [True, False])
@pytest.mark.parametrize("padding", ["", " \t"])
def test_reviewed_exact_case_routes_are_order_independent(tmp_path, monkeypatch, queries, synonyms, padding):
    """Explicit reviewed scopes retain existing scope semantics in both lookup modes."""
    targets = {node["synonym"]: node["id"] for node in _native_aliases()}
    _load_formulas(tmp_path, monkeypatch, set(targets.values()))
    for query in queries:
        assert runtime.find_chebi_by_name(padding + query + padding, synonyms=synonyms) == targets[query]
    assert "cocl2" not in runtime._NAME_INDEX
    ordinary, cas = ingredient_name_scopes()
    assert "COCl2" not in ordinary and "CoCl2" not in ordinary
    assert cas  # Public two-item interface and existing CAS annotations remain intact.


@pytest.mark.parametrize("declared", [{"CHEBI:29365"}, {"CHEBI:35696"}, {"CHEBI:29365", "CHEBI:35696"}])
@pytest.mark.parametrize("synonyms", [True, False])
def test_missing_target_and_unknown_case_do_not_fall_through(tmp_path, monkeypatch, declared, synonyms):
    """Neither a remaining declaration nor a case-folded collision can choose an unsupported identity."""
    _load_formulas(tmp_path, monkeypatch, declared)
    for node in _native_aliases():
        expected = node["id"] if node["id"] in declared else None
        assert runtime.find_chebi_by_name(node["synonym"], synonyms=synonyms) == expected
        assert _candidate_name_lookup(node["synonym"], {"cocl2": "CHEBI:29365"}, declared) == expected
    for query in ["cocl2", "COCL2", "cOCl2", "CoCl2!"]:
        assert runtime.find_chebi_by_name(query, synonyms=synonyms, fuzzy_hydrate=True) is None
        assert _candidate_name_lookup(query, {"cocl2": "CHEBI:29365"}, declared) is None


def test_recognized_family_is_distinct_from_an_unscoped_name():
    """Consumers must distinguish ambiguous known spelling from an unrelated ordinary name."""
    assert ingredient_case_sensitive_name_scope("cocl2") == (True, None)
    assert ingredient_case_sensitive_name_scope("COCl2") == (True, "CHEBI:29365")
    assert ingredient_case_sensitive_name_scope("CoCl2") == (True, "CHEBI:35696")
    assert ingredient_case_sensitive_name_scope("water") == (False, None)
    assert ingredient_case_sensitive_name_scope("CoCl2!") == (True, None)


@pytest.mark.parametrize("query", ["CoCl2 x 2 H2O", "CoCl2.6H2O", "CoCl2 · 6 H2O", "cocl2 x 2 H2O"])
def test_hydrates_do_not_inherit_bare_formula_identity(tmp_path, monkeypatch, query):
    """Reviewed bare formulas do not justify dihydrate/hexahydrate equivalence."""
    _load_formulas(tmp_path, monkeypatch, {"CHEBI:29365", "CHEBI:35696"})
    assert runtime.find_chebi_by_name(query, fuzzy_hydrate=True) is None


@pytest.mark.parametrize(
    "query,wrong",
    [
        ("CoCl2", "CHEBI:29365"),
        ("COCl2", "CHEBI:35696"),
        ("cocl2", "CHEBI:29365"),
        ("cocl2", "CHEBI:35696"),
        ("CoCl2!", "CHEBI:29365"),
        ("CoCl2!", "CHEBI:35696"),
        ("COCl2!", "CHEBI:29365"),
        ("COCl2!", "CHEBI:35696"),
    ],
)
def test_finite_case_scope_also_rejects_legacy_and_embedded_false_ids(query, wrong):
    """A missing scoped target cannot silently choose another formula's target in a fallback."""
    assert not ingredient_mapping_allowed(query, wrong)
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: None)
    transform.compound_mappings = {query.lower(): wrong}
    transform.compounds_data = {"99": {"ChEBI": wrong.split(":")[1]}}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", query) == "mediadive.ingredient:99"


def test_hydrated_cobalt_cannot_fall_back_from_phosgene_to_anhydrous_cobalt():
    """Reject distinct bad identities in successive unified, legacy and embedded routes."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: "CHEBI:29365")
    transform.compound_mappings = {"cocl2 x 2 h2o": "CHEBI:35696"}
    transform.compounds_data = {"99": {"ChEBI": "35696"}}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", "CoCl2 x 2 H2O") == "mediadive.ingredient:99"


def test_public_scope_cache_reset_refreshes_every_scope_route(tmp_path, monkeypatch):
    """The preserved cache_clear interface cannot leave case or ordinary scopes stale."""
    path = tmp_path / "scopes.tsv"
    path.write_text(
        "kind\tquery\ttarget_id\treason\ncase_sensitive_name\tAb2\tCHEBI:1\tfixture\nname\tFirst\tCHEBI:2\tfixture\n"
    )
    with monkeypatch.context() as patch:
        patch.setattr(identity, "NAME_SCOPE_POLICY", path)
        identity.ingredient_name_scopes.cache_clear()
        try:
            assert identity.ingredient_case_sensitive_name_scope("Ab2") == (True, "CHEBI:1")
            assert identity.ingredient_name_target("first") == "CHEBI:2"
            path.write_text(
                "kind\tquery\ttarget_id\treason\ncase_sensitive_name\tCd2\tCHEBI:3\tfixture\nname\tSecond\tCHEBI:4\tfixture\n"
            )
            identity.ingredient_name_scopes.cache_clear()
            assert identity.ingredient_case_sensitive_name_scope("Ab2") == (False, None)
            assert identity.ingredient_case_sensitive_name_scope("Cd2") == (True, "CHEBI:3")
            assert identity.ingredient_name_target("first") is None
            assert identity.ingredient_name_target("second") == "CHEBI:4"
        finally:
            identity.ingredient_name_scopes.cache_clear()
