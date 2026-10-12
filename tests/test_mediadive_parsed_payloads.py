"""Native byte receipts must bind the parsed dictionaries actually used by MediaDive (#1299)."""

import copy
import json

import pytest

from kg_microbe.transform_utils.mediadive import bulk_inputs
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests import test_mediadive_catalase_scope as native


@pytest.mark.parametrize("attribute", bulk_inputs.PAYLOAD_ATTRIBUTES.values())
@pytest.mark.parametrize("mode", ["mutate", "replace"])
def test_first_use_changed_native_cache_fails_before_output(tmp_path, monkeypatch, attribute, mode):
    """Every public cache, including a wholly replaced dictionary, retains its actual read identity."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    original = copy.deepcopy(getattr(producer, attribute))
    if mode == "replace":
        setattr(producer, attribute, copy.deepcopy(original))
    getattr(producer, attribute)["synthetic-added-native-record"] = {"not": "admitted"}
    with pytest.raises(SourceFinalizationRequired, match="cached native payload changed"):
        producer.run(show_status=False)
    assert not producer.output_node_file.exists()
    assert not producer.output_edge_file.exists()
    assert not (producer.output_dir / native.material.audit.AUDIT_FILENAME).exists()
    setattr(producer, attribute, original)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        producer.run(show_status=False)


@pytest.mark.parametrize("value", [999, None, False, "0", 0.0])
def test_first_use_quantity_drift_never_inherits_unchanged_raw_hash(tmp_path, monkeypatch, value):
    """Native null, boolean, string, integer and floating-point values remain distinct."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    record = producer.solutions_data["269"]["recipe"][8]
    original = record["amount"]
    assert original != value or type(original) is not type(value)
    record["amount"] = value
    with pytest.raises(SourceFinalizationRequired):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


@pytest.mark.parametrize("change", ["remove", "reorder", "tuple", "numeric_key"])
def test_native_container_shape_and_positions_are_bound(tmp_path, monkeypatch, change):
    """JSON-compatible serialization must not hide non-JSON cache types or changed occurrence coordinates."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    solution = producer.solutions_data["269"]
    if change == "remove":
        solution["recipe"].pop(0)
    elif change == "reorder":
        solution["recipe"].reverse()
    elif change == "tuple":
        solution["recipe"] = tuple(solution["recipe"])
    else:
        producer.solutions_data[269] = producer.solutions_data.pop("269")
    with pytest.raises(SourceFinalizationRequired):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_media_list_object_mutation_is_detected_after_read_before_use(tmp_path, monkeypatch):
    """A local run-time list is protected too; constructor-only cache coverage is insufficient."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    original = producer._preflight_bulk_records

    def altered(payload):
        """Mutate a parsed source title after the real preflight has admitted it."""
        original(payload)
        payload["data"][0]["name"] = "not the admitted source title"

    monkeypatch.setattr(producer, "_preflight_bulk_records", altered)
    with pytest.raises(SourceFinalizationRequired, match="cached native payload changed"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_later_parse_cannot_rebaseline_an_earlier_mutated_payload(tmp_path, monkeypatch):
    """Real immutable reads bind each parse before the constructor publishes its cache set."""
    real = json.load
    parsed = []

    def read(reader, *args, **kwargs):
        """Corrupt an earlier parsed native recipe when a later payload is read."""
        result = real(reader, *args, **kwargs)
        # Only the four role payloads have these native bulk record keys.
        if isinstance(result, dict) and "269" in result and "recipe" in result["269"]:
            parsed.append(result)
        elif parsed and isinstance(result, dict) and "270" in result:
            parsed[0]["269"]["recipe"][8]["amount"] = 999
        return result

    monkeypatch.setattr(json, "load", read)
    producer, _ = native._producer(tmp_path, monkeypatch)
    assert parsed
    with pytest.raises(SourceFinalizationRequired):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_single_solution_check_does_not_hash_all_native_solutions(tmp_path, monkeypatch):
    """The per-lookup check scales with the selected solution, not the 5,430-record bulk tree."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    actual = bulk_inputs._payload_digest

    def bounded(payload):
        """Reject whole-cache hashing during an individual solution check."""
        assert payload is not producer.solutions_data
        assert payload is not producer.compounds_data
        return actual(payload)

    monkeypatch.setattr(bulk_inputs, "_payload_digest", bounded)
    producer.get_solution_recipe_occurrences("269")
    producer.solutions_data["269"]["recipe"][8]["amount"] = 999
    with pytest.raises(SourceFinalizationRequired, match="cached native record changed"):
        producer.get_solution_recipe_occurrences("269")


def test_unchanged_replacement_cache_and_repeat_run_remain_valid(tmp_path, monkeypatch):
    """Binding concerns exact native values, not accidental Python object identity or dict insertion order."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    producer.solutions_data = dict(reversed(list(copy.deepcopy(producer.solutions_data).items())))
    producer.run(show_status=False)
    before = producer.output_edge_file.read_bytes()
    producer.run(show_status=False)
    assert producer.output_edge_file.read_bytes() == before
    producer.verify_consumed_inputs()


def test_cached_payload_drift_is_checked_again_at_native_finalization(tmp_path, monkeypatch):
    """A successful run cannot later acquire a different parsed payload beneath its original source receipt."""
    producer, _ = native._producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    producer.compounds_data["270"]["compound"] = "Changed catalog"
    with pytest.raises(SourceFinalizationRequired, match="cached native payload changed"):
        producer.verify_native_inputs()
