"""Draft #1365 controls: synthetic selectors, actual producer loop, no native identity claims."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    INFERRED_SUBCLASS_RELATION,
    MANUAL_AGENT,
    OBSERVATION,
    PREDICTION,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.utils.source_finalization import graph_rows
from tests.bacdive_synthetic_fallback_context import (
    assert_actual_native_batch,
)
from tests.bacdive_synthetic_fallback_context import (
    synthetic_fallback_context as _synthetic_fallback_context,
)
from tests.test_bacdive_run_references import _run_fixture

synthetic_fallback_context = _synthetic_fallback_context


def test_immutable_native_missing_name_records_have_distinct_actual_selector_keys():
    """The original18491 cache seed and134696 cannot collide; do not infer their identities here."""
    fixture = Path(__file__).parent / "resources/bacdive_fallback/records.json"
    assert (
        hashlib.sha256(fixture.read_bytes()).hexdigest()
        == "be2b7269e266394ec4e7cb2170d8d2c52430197ae16719e4868e17942cd42e22"
    )
    data = json.loads(fixture.read_text())
    assert data["origin"]["sha256"] == "57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2"
    indexed = {}
    for item in data["records"]:
        record = item["record"]
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert hashlib.sha256(encoded.encode()).hexdigest() == item["canonical_record_sha256"]
        indexed[record["General"]["BacDive-ID"]] = item
    assert set(indexed) == {18491, 134696, 175523}
    assert indexed[18491]["native_array_index"] == 18216
    first = indexed[18491]["record"]["Name and taxonomic classification"]
    second = indexed[134696]["record"]["Name and taxonomic classification"]
    assert "full scientific name" not in first and "full scientific name" not in second
    assert first.get("full scientific name", "unknown") == second.get("full scientific name", "unknown")
    assert BacDiveTransform._ncbitaxon_fallback_key(first) != BacDiveTransform._ncbitaxon_fallback_key(second)


def _record(identifier, genus, *, full_name=None, direct=False):
    """Create clearly synthetic source controls, not a rewritten native fixture."""
    general = {"BacDive-ID": identifier, "keywords": ["fixture_keyword"]}
    if direct:
        general["NCBI tax id"] = {"NCBI tax id": 33}
    classification = {"species": "Fixture missing species", "genus": genus}
    if full_name is not None:
        classification["full scientific name"] = full_name
    return {"General": general, "Name and taxonomic classification": classification}


@pytest.mark.parametrize("full_name", [None, "Same displayed scientific name"])
@pytest.mark.parametrize("reverse", [False, True])
def test_actual_rank_inputs_not_missing_or_shared_display_name_control_cache(
    tmp_path, monkeypatch, synthetic_fallback_context, full_name, reverse
):
    """Different genera cannot share success, while equal selectors preserve a cache hit."""
    records = [
        _record(1, "FixtureGenusA", full_name=full_name),
        _record(2, "FixtureGenusB", full_name=full_name),
        _record(3, "FixtureGenusB", full_name=full_name),
        _record(4, "FixtureGenusA", direct=True),
    ]
    if reverse:
        records.reverse()
    before = copy.deepcopy(records)
    captured, _ = synthetic_fallback_context(
        {"FixtureGenusA": "NCBITaxon:11", "FixtureGenusB": "NCBITaxon:22"},
        direct_labels={"NCBITaxon:33": "FixtureDirect"},
    )
    original_begin = BacDiveTransform.begin_consumed_inputs

    def begin(transform):
        """Seed stale state before the real producer begins; its actual reset must remove it."""
        transform.ncbitaxon_fallback_cache = {"unknown": "NCBITaxon:999"}
        original_begin(transform)
        assert transform.ncbitaxon_fallback_cache == {}

    monkeypatch.setattr(BacDiveTransform, "begin_consumed_inputs", begin)
    edges, nodes = _run_fixture(tmp_path, monkeypatch, records)
    assert records == before
    child = assert_actual_native_batch(
        captured[0], expected_targets={"NCBITaxon:11", "NCBITaxon:22"}, expected_eligible=3
    )
    assert child["native_queries"]["exact_label_batch"]["queries"] == sorted(
        {"Fixture missing species", "FixtureGenusA", "FixtureGenusB", *(["Same"] if full_name else [])}
    )
    parents = [row for row in edges if row["predicate"] == SUBCLASS_PREDICATE]
    assert {(row["subject"], row["object"]) for row in parents} == {
        ("kgmicrobe.strain:bacdive_1", "NCBITaxon:11"),
        ("kgmicrobe.strain:bacdive_2", "NCBITaxon:22"),
        ("kgmicrobe.strain:bacdive_3", "NCBITaxon:22"),
        ("kgmicrobe.strain:bacdive_4", "NCBITaxon:33"),
    }
    for row in parents:
        direct = row["subject"] == "kgmicrobe.strain:bacdive_4"
        assert row["relation"] == (RDFS_SUBCLASS_OF if direct else INFERRED_SUBCLASS_RELATION)
        assert row["knowledge_level"] == (OBSERVATION if direct else PREDICTION)
        assert row["agent_type"] == (MANUAL_AGENT if direct else AUTOMATED_AGENT)
        assert row["primary_knowledge_source"] == "infores:bacdive"
        assert row["publications"] == "https://bacdive.dsmz.de/strain/" + row["subject"].rsplit("_", 1)[1]
        assert all(
            value == ""
            for key, value in row.items()
            if key
            not in {
                "subject",
                "predicate",
                "object",
                "relation",
                "knowledge_level",
                "agent_type",
                "primary_knowledge_source",
                "publications",
            }
        )
    traits = [row for row in edges if row["predicate"] != SUBCLASS_PREDICATE]
    assert len(traits) == 4
    assert all(
        row["object"] == "METPO:1000001" and row["knowledge_level"] == OBSERVATION and row["agent_type"] == MANUAL_AGENT
        for row in traits
    )
    assert {row["id"] for row in nodes if row["id"].startswith("kgmicrobe.strain:")} == {
        f"kgmicrobe.strain:bacdive_{i}" for i in range(1, 5)
    }
    assert len(captured[0].ncbitaxon_fallback_cache) == 2


def test_failed_result_does_not_alias_a_different_rank_selector():
    """A cached failure and a successful independent selector occupy separate slots."""
    first = BacDiveTransform._ncbitaxon_fallback_key({"genus": "Missing"})
    second = BacDiveTransform._ncbitaxon_fallback_key({"genus": "Resolved"})
    cache = {first: None, second: "NCBITaxon:11"}
    assert cache[first] is None and cache[second] == "NCBITaxon:11"


def test_key_preserves_missing_null_empty_case_and_whitespace_without_using_display_name():
    """Do not make a new normalizing equivalence the real lookup never used."""
    key = BacDiveTransform._ncbitaxon_fallback_key
    values = [{}, {"genus": None}, {"genus": ""}, {"genus": "A"}, {"genus": "a"}, {"genus": " A"}]
    assert len({key(value) for value in values}) == len(values)
    assert key({"genus": "A", "full scientific name": "one"}) == key({"genus": "A", "full scientific name": "two"})
    assert len(key({})) == 7


def test_typed_json_values_remain_distinct_without_eager_semantic_validation():
    """An unused later rank retains its native type without becoming a search term."""
    values = [None, [], {}, ["A"], 1, 1.0, True, False, "1", "true", "[]", {"nested": [1, "1"]}]
    keys = [BacDiveTransform._ncbitaxon_fallback_key({"genus": value}) for value in values]
    assert len(set(keys)) == len(values)
    assert BacDiveTransform._ncbitaxon_fallback_key({"genus": {"a": 1, "b": 2}}) == (
        BacDiveTransform._ncbitaxon_fallback_key({"genus": {"b": 2, "a": 1}})
    )


@pytest.mark.parametrize("value", [[], {}, ["A"], 1, False])
def test_actual_earlier_species_hit_does_not_validate_unused_later_rank(
    tmp_path, monkeypatch, synthetic_fallback_context, value
):
    """Key construction cannot skip an otherwise resolvable record because of unvisited data."""
    record = _record(1, value)
    captured, _ = synthetic_fallback_context({"Fixture missing species": "NCBITaxon:11"})
    before = copy.deepcopy(record)
    edges, _ = _run_fixture(tmp_path, monkeypatch, [record])
    assert record == before
    child = assert_actual_native_batch(captured[0], expected_targets={"NCBITaxon:11"}, expected_eligible=1)
    assert child["native_queries"]["exact_label_batch"]["queries"] == ["Fixture missing species"]
    assert [(row["subject"], row["object"]) for row in edges if row["predicate"] == SUBCLASS_PREDICATE] == [
        ("kgmicrobe.strain:bacdive_1", "NCBITaxon:11")
    ]
    assert len([row for row in edges if row["object"] == "METPO:1000001"]) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_actual_loop_cached_miss_does_not_hide_a_different_selector(
    tmp_path, monkeypatch, synthetic_fallback_context, reverse
):
    """Repeated misses are cached independently of a later valid genus in either record order."""
    records = [_record(1, "Missing"), _record(2, "Missing"), _record(3, "Resolved")]
    if reverse:
        records.reverse()
    captured, _ = synthetic_fallback_context({"Resolved": "NCBITaxon:22"})
    # Missing full scientific names reach the real parser, which emits no
    # provisional identity; no parser or native lookup is replaced.
    before = copy.deepcopy(records)
    edges, nodes = _run_fixture(tmp_path, monkeypatch, records)
    assert records == before
    child = assert_actual_native_batch(captured[0], expected_targets={None, "NCBITaxon:22"}, expected_eligible=3)
    assert child["native_queries"]["exact_label_batch"]["queries"] == ["Fixture missing species", "Missing", "Resolved"]
    assert [(row["subject"], row["object"]) for row in edges if row["predicate"] == SUBCLASS_PREDICATE] == [
        ("kgmicrobe.strain:bacdive_3", "NCBITaxon:22")
    ]
    assert len([row for row in edges if row["object"] == "METPO:1000001"]) == 3
    assert {row["id"] for row in nodes if row["id"].startswith("kgmicrobe.strain:")} == {
        f"kgmicrobe.strain:bacdive_{number}" for number in (1, 2, 3)
    }
    cache = captured[0].ncbitaxon_fallback_cache
    assert cache[BacDiveTransform._ncbitaxon_fallback_key(records[1]["Name and taxonomic classification"])] is None
    assert len(cache) == 2


def test_actual_second_run_does_not_reuse_first_run_lookup_result(tmp_path, monkeypatch, synthetic_fallback_context):
    """The same producer re-queries after begin resets its cache; native guard checks are separate."""
    answers = {"FixtureGenusA": "NCBITaxon:11"}
    captured, epochs = synthetic_fallback_context(answers)
    first_edges, _ = _run_fixture(tmp_path, monkeypatch, [_record(1, "FixtureGenusA")])
    transform = captured[0]
    previous_cache = transform.ncbitaxon_fallback_cache
    answers["FixtureGenusA"] = "NCBITaxon:22"
    first_contract = assert_actual_native_batch(transform, expected_targets={"NCBITaxon:11"}, expected_eligible=1)
    transform.run(show_status=False)
    second_edges = list(graph_rows(transform.output_edge_file))
    second_contract = assert_actual_native_batch(transform, expected_targets={"NCBITaxon:22"}, expected_eligible=1)
    assert len(epochs) == 2
    assert epochs[0]["database"] != epochs[1]["database"]
    assert epochs[0]["selected"] != epochs[1]["selected"]
    assert (
        first_contract["native_queries"]["connection"]["authority"]
        != second_contract["native_queries"]["connection"]["authority"]
    )
    assert [row["object"] for row in first_edges if row["predicate"] == SUBCLASS_PREDICATE] == ["NCBITaxon:11"]
    assert [row["object"] for row in second_edges if row["predicate"] == SUBCLASS_PREDICATE] == ["NCBITaxon:22"]
    assert transform.ncbitaxon_fallback_cache is not previous_cache
    assert list(previous_cache.values()) == ["NCBITaxon:11"]
    assert [row for row in first_edges if row["predicate"] != SUBCLASS_PREDICATE] == [
        row for row in second_edges if row["predicate"] != SUBCLASS_PREDICATE
    ]


def test_real_begin_resets_cache_without_mutating_previous_dictionary(monkeypatch):
    """A new run has no old results; old evidence objects are not cleared in place."""
    from kg_microbe.transform_utils.transform import Transform

    monkeypatch.setattr(Transform, "begin_consumed_inputs", lambda _self: None)
    transform = BacDiveTransform.__new__(BacDiveTransform)
    previous = {BacDiveTransform._ncbitaxon_fallback_key({"genus": "A"}): "NCBITaxon:11"}
    transform.ncbitaxon_fallback_cache = previous
    BacDiveTransform.begin_consumed_inputs(transform)
    assert transform.ncbitaxon_fallback_cache == {} and previous
    assert transform.ncbitaxon_fallback_cache is not previous
