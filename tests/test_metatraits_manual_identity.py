"""Guard manual Tier 2 identity and preserve two distinct local ingredients (#1184)."""

import csv
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import AUTOMATED_AGENT, BIOLOGICAL_PROCESS, CHEMICAL_CATEGORY, OBSERVATION
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings
from tests.test_chemical_mapping_utils import _write_mock_sssom
from tests.test_chemical_mapping_utils import reset_cache as reset_cache
from tests.test_metatraits_indeterminate import TAXON, _diagnostics, _input, _record, _rows, _run, _transform

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "resources/metatraits_manual_identity.sssom.tsv"
POSITIVE = "METPO:2000012"
NEGATIVE = "METPO:2000038"
WRONG = "FOODON:00002992"
pytestmark = pytest.mark.usefixtures("reset_cache")


def _supported_rows():
    """Read only the two immutable reviewed source-local identities."""
    return _rows(FIXTURE)


def _configured(tmp_path, monkeypatch, transform_type):
    """Use production readers and a real tiny loader, with no network or full graph."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    transform.microbial_mappings = load_microbial_trait_mappings(REPO / "mappings/canonical")
    transform.special_chemical_mappings = transform._load_special_chemical_mappings()
    transform.metpo_pattern_to_predicate["growth"] = {"positive": POSITIVE, "negative": NEGATIVE}
    entries = [
        {"id": row["object_id"], "canonical_name": row["object_label"], "category": CHEMICAL_CATEGORY}
        for row in _supported_rows()
    ]
    entries.append(
        {
            "id": WRONG,
            "canonical_name": "fresh bratwurst",
            "category": "biolink:Food",
            "synonyms": "Soyton|Proteose|proteose peptone",
        }
    )
    mapping_path = tmp_path / "chemical-fixture.sssom.tsv.gz"
    _write_mock_sssom(entries, mapping_path)
    loader = ChemicalMappingLoader(mapping_path)
    monkeypatch.setattr(metatraits, "ChemicalMappingLoader", lambda: loader)
    transform.chemical_loader = loader
    return transform


def _stale(label="proteose peptone"):
    """Represent the historical wrong target without repairing its input in place."""
    return {
        "object_id": WRONG,
        "object_label": label,
        "object_category": "biolink:Food",
        "biolink_predicate": POSITIVE,
    }


def _summaries(traits):
    """Build independent synthetic signs plus an explicitly indeterminate observation."""
    return [
        {
            "name": trait,
            "is_discrete": True,
            "majority_label": label,
            "percentages": {"true": percent},
        }
        for trait in traits
        for label, percent in [("true: (80%)", 80.0), ("false: (100%)", 0.0), ("No robust majority", 80.0)]
    ]


def test_existing_supported_identities_match_immutable_fixture_and_both_readers():
    """The correction reuses the promoted pair; it does not invent new mappings."""
    expected = {row["subject_id"]: row for row in _supported_rows()}
    with (REPO / "mappings/ingredient_mappings.sssom.tsv").open() as stream:
        rows = csv.DictReader((line for line in stream if not line.startswith("#")), delimiter="\t")
        actual = {row["subject_id"]: row for row in rows if row["subject_id"] in expected}
    assert actual == expected
    manual = load_microbial_trait_mappings(REPO / "mappings/canonical")
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    special = transform._load_special_chemical_mappings()
    for row in expected.values():
        trait = "growth: " + row["subject_label"].lower()
        assert manual[trait]["object_id"] == special[trait]["curie"] == row["object_id"]
        assert manual[trait]["object_label"] == special[trait]["name"] == row["object_label"]
        assert manual[trait]["object_category"] == special[trait]["category"] == CHEMICAL_CATEGORY
        assert manual[trait]["biolink_predicate"] == special[trait]["predicate"] == POSITIVE
    assert len({row["object_id"] for row in expected.values()}) == 2


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
@pytest.mark.parametrize("route", ["manual", "special", "stale_manual", "stale_query_only"])
def test_real_routes_keep_local_identity_polarity_and_provenance(transform_type, mode, route, tmp_path, monkeypatch):
    """Rejected Tier 2 falls through, retaining valid observations and exact local names."""
    transform = _configured(tmp_path, monkeypatch, transform_type)
    identities = _supported_rows()
    traits = ["growth: " + row["subject_label"].lower() for row in identities]
    if route == "special":
        transform.microbial_mappings = {}
    elif route == "stale_manual":
        transform.microbial_mappings = {trait: _stale() for trait in traits}
    elif route == "stale_query_only":
        transform.microbial_mappings = {trait: _stale("fresh bratwurst") for trait in traits}
    record = _record()
    record["summaries"] = _summaries(traits)
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    expected = {
        (TAXON, predicate, row["object_id"], percentage)
        for row in identities
        for predicate, percentage in [(POSITIVE, "80.0"), (NEGATIVE, "0.0")]
    }
    assert len(edges) == len(expected) == 4
    assert {(r["subject"], r["predicate"], r["object"], r["has_percentage"]) for r in edges} == expected
    for edge in edges:
        assert edge["relation"] == BIOLOGICAL_PROCESS
        assert edge["primary_knowledge_source"] == transform.knowledge_source
        assert edge["knowledge_level"] == OBSERVATION
        assert edge["agent_type"] == AUTOMATED_AGENT
    nodes = _rows(transform.output_node_file)
    local = [row for row in nodes if row["id"] != TAXON]
    assert {(r["id"], r["name"]) for r in local} == {(row["object_id"], row["object_label"]) for row in identities}
    assert len(local) == 2
    for node in local:
        assert node["category"] == CHEMICAL_CATEGORY
        assert node["provided_by"] == transform.knowledge_source
        assert not node["xref"] and not node["same_as"] and not node["synonym"]
    diagnostics = _diagnostics(transform.indeterminate_traits_file)
    assert [row["summary"] for row in diagnostics] == record["summaries"][2::3]
    assert _rows(transform.unmapped_traits_file) == []


@pytest.mark.parametrize(
    "label,trait", [("fresh bratwurst", "growth: soyton"), ("proteose peptone", "growth: fresh bratwurst")]
)
def test_manual_guard_checks_query_and_object_label_independently(label, trait):
    """Neither a native-looking label nor a safe-looking query overrides the other rejection."""
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    original = _stale(label)
    transform.microbial_mappings = {trait: original}
    before = deepcopy(original)
    assert transform._reviewed_manual_mapping(trait) is None
    assert original == before


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
def test_label_only_rejection_falls_through_to_independent_native_identity(transform_type, mode, tmp_path, monkeypatch):
    """A bad manual label cannot block or relabel a separately supported native target."""
    transform = _configured(tmp_path, monkeypatch, transform_type)
    trait = "growth: fresh bratwurst"
    transform.microbial_mappings = {trait: _stale()}
    transform.special_chemical_mappings = {}
    record = _record()
    record["summaries"] = _summaries([trait])[:1]
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    assert len(edges) == 1
    assert edges[0]["object"] == WRONG
    target = next(row for row in _rows(transform.output_node_file) if row["id"] == WRONG)
    assert target["name"] == "fresh bratwurst"


@pytest.mark.parametrize(
    "target,label",
    [
        (WRONG, "fresh bratwurst"),
        ("GO:0006113", "fermentation"),
        ("EC:1.1.1.6", "glycerol dehydrogenase"),
        ("METPO:1000698", "gram positive"),
    ],
)
def test_safe_native_and_nonchemical_manual_routes_remain_admitted(target, label):
    """Finite identity exclusions are not a namespace ban or an ontology rewrite."""
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    mapping = {**_stale(label), "object_id": target}
    transform.microbial_mappings = {label: mapping}
    admitted = transform._reviewed_manual_mapping(label.upper())
    assert admitted == mapping
    assert admitted is not mapping


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
def test_valid_manual_native_food_and_nonchemical_routes_survive_real_dispatch(
    transform_type, mode, tmp_path, monkeypatch
):
    """The new shared gate preserves unrelated valid manual observations in each runner."""
    transform = _configured(tmp_path, monkeypatch, transform_type)
    controls = [
        ("growth: fresh bratwurst", WRONG, "fresh bratwurst", "biolink:Food", POSITIVE),
        ("fixture process", "GO:0006113", "fermentation", "biolink:BiologicalProcess", "biolink:capable_of"),
        ("fixture enzyme", "EC:1.1.1.6", "glycerol dehydrogenase", "biolink:MolecularActivity", "biolink:capable_of"),
        ("fixture phenotype", "METPO:1000698", "gram positive", "biolink:PhenotypicQuality", "biolink:has_phenotype"),
    ]
    transform.microbial_mappings = {
        trait: {"object_id": curie, "object_label": label, "object_category": category, "biolink_predicate": pred}
        for trait, curie, label, category, pred in controls
    }
    transform.special_chemical_mappings = {}
    record = _record()
    record["summaries"] = _summaries([control[0] for control in controls])[::3]
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    assert len(edges) == 4
    assert {(row["object"], row["predicate"], row["has_percentage"]) for row in edges} == {
        (curie, pred, "80.0") for _, curie, _, _, pred in controls
    }
    assert {row["primary_knowledge_source"] for row in edges} == {transform.knowledge_source}
    nodes = [row for row in _rows(transform.output_node_file) if row["id"] != TAXON]
    assert {(row["id"], row["name"], row["category"]) for row in nodes} == {
        (curie, label, category) for _, curie, label, category, _ in controls
    }


def test_manual_identity_infrastructure_failure_is_not_absorbed(monkeypatch):
    """A failed policy dependency cannot be mistaken for an ordinary unmapped trait."""
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    transform.microbial_mappings = {"growth: soyton": _stale()}

    def broken_policy(*args):
        """Represent a policy input failure rather than a negative identity decision."""
        raise OSError("identity policy unavailable")

    monkeypatch.setattr(metatraits, "ingredient_mapping_allowed", broken_policy)
    with pytest.raises(OSError, match="identity policy unavailable"):
        transform._reviewed_manual_mapping("growth: soyton")


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
def test_all_stale_overrides_without_independent_identity_stay_unmapped(transform_type, mode, tmp_path, monkeypatch):
    """No forbidden target is emitted when neither current local override is available."""
    transform = _configured(tmp_path, monkeypatch, transform_type)
    trait = "growth: proteose peptone"
    transform.microbial_mappings = {trait: _stale()}
    transform.special_chemical_mappings = {
        trait: {"curie": WRONG, "name": "proteose peptone", "predicate": POSITIVE, "category": "biolink:Food"}
    }
    record = _record()
    record["summaries"] = _summaries([trait])[:1]
    assert _run(transform, mode, [_input(tmp_path, record)], tmp_path) == []
    assert WRONG not in {row["id"] for row in _rows(transform.output_node_file)}
    assert len(_rows(transform.unmapped_traits_file)) == 1
