"""Production consumer controls for sealed endpoint evidence and qualified source replay."""

import csv
import hashlib
import json

import pytest

from kg_microbe.transform_utils.mediadive import endpoint_outcomes
from kg_microbe.transform_utils.mediadive.endpoint_consumer import AUDIT_FILENAME
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.mediadive_generation_fixtures import seal_fixture_raw
from tests.test_mediadive_bulk_inputs import bulk_build as _bulk_build
from tests.test_mediadive_bulk_inputs import write_bulk_inputs

bulk_build = _bulk_build


@pytest.fixture
def outcome_source(tmp_path, monkeypatch, bulk_build):
    """Create one source recipe with explicit synthetic empty or reviewed unknown endpoint evidence."""

    def build(state="unknown_unavailable", *, run=True):
        """Seal the selected endpoint outcome and optionally run its real consumer."""
        raw = tmp_path / "raw"
        write_bulk_inputs(raw, seal=False)
        medium = {"id": 1, "name": "Qualified fixture medium", "complex_medium": False}
        (raw / "mediadive.json").write_text(json.dumps({"data": [medium]}))
        (raw / "mediadive/media_detailed.json").write_text(json.dumps({"1": {"medium": medium}}))
        generation = seal_fixture_raw(
            raw, missing_strains="explicit_empty", unknown_ids=("1",) if state == "unknown_unavailable" else ()
        )
        monkeypatch.setattr(endpoint_outcomes, "CURATED_UNKNOWN_POLICY", generation.curated_policy_path)
        producer = bulk_build(raw)
        if run:
            producer.run(show_status=False)
        return producer

    return build


@pytest.mark.parametrize("state", ["explicit_empty", "unknown_unavailable"])
def test_typed_outcomes_preserve_recipe_without_invented_associations(outcome_source, state):
    """Identical absent native strain keys retain different validated source meanings."""
    producer = outcome_source(state)
    expected = [] if state == "explicit_empty" else None
    assert producer.get_json_object("", "medium-strains/1", producer.output_dir) == expected
    contract = producer.producer_native_inputs
    assert contract["version"] == 3
    assert contract["endpoint_coverage"]["sealed"] is True
    qualification = producer._endpoint_consumer.view.qualification
    assert qualification["endpoint_accounting_complete"] is True
    assert qualification["association_coverage_complete"] is (state == "explicit_empty")
    with (producer.output_dir / AUDIT_FILENAME).open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 2
    assert next(row for row in rows if "/medium-strains/" in row["endpoint"])["state"] == state
    assert "mediadive.medium:1" in producer.output_node_file.read_text()


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("state", ["explicit_empty", "unknown_unavailable"])
def test_current_contract_replays_in_a_fresh_consumer(outcome_source, bulk_build, state):
    """Actual completion, mandatory audit and fresh immutable rereads retain qualified coverage."""
    producer = outcome_source(state)
    report = producer.finalize(fresh_run=True)
    before = (producer.output_dir / "source_finalization.json").read_bytes()
    fresh = bulk_build(producer.input_base_dir)
    assert fresh.finalize() == report
    verify_finalized_source_files([fresh.output_node_file, fresh.output_edge_file])
    assert (producer.output_dir / "source_finalization.json").read_bytes() == before
    assert fresh.producer_native_inputs["endpoint_coverage"] == report["producer_native_inputs"]["endpoint_coverage"]
    assert report["producer_audit_members"][AUDIT_FILENAME] == report["audit_members"][AUDIT_FILENAME]


def test_historical_root_files_do_not_replace_the_selected_generation(outcome_source):
    """Previously acquired root exports remain historical and cannot shadow current sealed evidence."""
    producer = outcome_source(run=False)
    historical = producer.input_base_dir / "mediadive/media_strains.json"
    historical.write_text('{"1":[{"id":999,"growth":0}]}\n')
    producer.run(show_status=False)
    assert producer.media_strains == {}
    assert producer.get_json_object("", "medium-strains/1", producer.output_dir) is None


@pytest.mark.parametrize("damage", ["pointer", "outcomes", "policy", "body"])
def test_changed_generation_evidence_refuses_before_graph_writes(outcome_source, damage):
    """A producer cannot consume a changed evidence generation beneath constructor-loaded native data."""
    producer = outcome_source(run=False)
    view = producer._endpoint_consumer.view
    paths = {
        "pointer": producer.bulk_data_dir / "current.json",
        "outcomes": view.generation_dir / "endpoint-outcomes.json",
        "policy": view.curated_policy_path,
        "body": next((view.generation_dir / "bodies").iterdir()),
    }
    path = paths[damage]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SourceFinalizationRequired):
        producer.run(show_status=False)
    assert not producer.output_node_file.exists()
    assert not producer.output_edge_file.exists()


@pytest.mark.usefixtures("local_source_schema")
def test_restamped_endpoint_audit_cannot_relabel_unknown_as_empty(outcome_source):
    """Full source replay rejects altered semantics even when every outer audit hash is updated."""
    producer = outcome_source()
    report = producer.finalize(fresh_run=True)
    path = producer.output_dir / AUDIT_FILENAME
    path.write_bytes(path.read_bytes().replace(b"unknown_unavailable", b"explicit_empty"))
    identity = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    report["audit_members"][AUDIT_FILENAME] = identity
    report["producer_audit_members"][AUDIT_FILENAME] = identity
    report["producer_native_inputs"]["endpoint_coverage"]["audit"] = {"name": AUDIT_FILENAME, **identity}
    (producer.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="endpoint contract differs|endpoint audit differs"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


def test_unknown_endpoint_cannot_gain_a_growth_assertion(outcome_source):
    """Source-level unavailable evidence cannot be used to create a positive or negative growth claim."""
    from kg_microbe.transform_utils.constants import NCBI_TO_MEDIUM_NEGATIVE_EDGE

    producer = outcome_source()
    with producer.output_edge_file.open() as stream:
        header = next(csv.reader(stream, delimiter="\t"))
    row = {name: "" for name in header}
    row.update(subject="NCBITaxon:1", predicate=NCBI_TO_MEDIUM_NEGATIVE_EDGE, object="mediadive.medium:1")
    with producer.output_edge_file.open("a", newline="") as stream:
        csv.DictWriter(stream, fieldnames=header, delimiter="\t").writerow(row)
    with pytest.raises(SourceFinalizationRequired, match="unsupported growth assertion"):
        producer._endpoint_consumer.verify()


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("change", ["sealed_integer", "count_boolean", "coverage_integer"])
def test_endpoint_contract_preserves_json_types_during_restore_and_replay(outcome_source, bulk_build, change):
    """Boolean/integer equality cannot reinterpret a recorded sealed flag or coverage count."""
    import copy

    producer = outcome_source()
    report = producer.finalize(fresh_run=True)
    altered = copy.deepcopy(report)
    endpoint = altered["producer_native_inputs"]["endpoint_coverage"]
    if change == "sealed_integer":
        endpoint["sealed"] = 1
    elif change == "count_boolean":
        endpoint["generation"]["qualification"]["state_counts"]["nonempty"] = True
    else:
        endpoint["generation"]["qualification"]["association_coverage_complete"] = 0
    with pytest.raises(SourceFinalizationRequired, match="bulk reads differ"):
        producer.producer_native_inputs = altered["producer_native_inputs"]
    report_path = producer.output_dir / "source_finalization.json"
    report_path.write_text(json.dumps(altered))
    with pytest.raises(SourceFinalizationRequired, match="endpoint contract differs"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    fresh = bulk_build(producer.input_base_dir)
    with pytest.raises(SourceFinalizationRequired, match="checkpoint endpoint evidence differs"):
        fresh.finalize()


def test_replaced_cached_audit_cannot_become_producer_completion(outcome_source):
    """Changing cached projected bytes cannot relabel source evidence or overwrite the sealed audit."""
    producer = outcome_source()
    path = producer.output_dir / AUDIT_FILENAME
    before = path.read_bytes()
    endpoint = producer._endpoint_consumer
    endpoint._audit = endpoint._audit.replace(b"unknown_unavailable", b"explicit_empty")
    for operation in (
        producer.verify_native_inputs,
        endpoint.write,
        lambda: producer.finalize(fresh_run=True),
    ):
        with pytest.raises(SourceFinalizationRequired, match="cached endpoint audit differs"):
            operation()
    assert path.read_bytes() == before
    assert not (producer.output_dir / "source_finalization.json").exists()


@pytest.mark.usefixtures("local_source_schema")
def test_recorded_semantic_read_binds_the_exact_source_edge_bytes(outcome_source, monkeypatch):
    """A byte change after the omission scan is detected by that replay's own admission guard."""
    from kg_microbe.transform_utils.mediadive import endpoint_consumer

    producer = outcome_source()
    report = producer.finalize(fresh_run=True)
    original = endpoint_consumer._check_omitted_assertions

    def changed(path, states):
        """Mutate only after actual source semantics have been inspected."""
        original(path, states)
        path.write_bytes(path.read_bytes() + b"\\n")

    monkeypatch.setattr(endpoint_consumer, "_check_omitted_assertions", changed)
    with pytest.raises(SourceFinalizationRequired):
        endpoint_consumer.verify_recorded_endpoints(report, producer.output_dir / "source_finalization.json")
