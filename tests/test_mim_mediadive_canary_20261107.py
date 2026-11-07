"""A bounded real writer interruption never becomes a completed MediaDive source (#1798)."""

import copy
import importlib
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.mediadive import endpoint_outcomes
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.mediadive_bulk_download import extract_compounds_from_media, extract_solutions_from_media
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from scripts.adhoc import kgm_mim_mediadive_canary_20261107 as canary
from tests.mediadive_generation_fixtures import seal_fixture_raw
from tests.test_mediadive_recipe_identity import _loader

FIXTURE = Path(__file__).parent / "resources/mim_mediadive_canary_20261107"
DISPATCHER = importlib.import_module("kg_microbe.transform")


@pytest.fixture
def actual_writer(tmp_path, monkeypatch):
    """Use actual dispatcher/constructor/read guards/run with a two-medium offline generation."""
    selected = json.loads((FIXTURE / "first-medium.json").read_text())
    origin = json.loads((FIXTURE / "origin.json").read_text())
    assert canary.digest(FIXTURE / "first-medium.json") == origin["fixture_sha256"]
    root = tmp_path / "owned"
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    transformed = root / "data/transformed"
    scratch = root / canary.SUMMARY.parent
    scratch.mkdir(parents=True)
    first, detail = selected["catalogue_medium"], selected["detail"]
    second = {**first, "id": 2, "name": "Explicit synthetic second medium"}
    second_detail = copy.deepcopy(detail)
    second_detail["medium"] = second
    second_detail["solutions"][0].update(id=2, name="Synthetic second solution")
    detailed = {"1": detail, "2": second_detail}
    payloads = {
        "mediadive.json": {"data": [first, second]},
        "mediadive/media_detailed.json": detailed,
        "mediadive/media_strains.json": {},
        "mediadive/solutions.json": extract_solutions_from_media(detailed),
        "mediadive/compounds.json": extract_compounds_from_media(detailed),
    }
    for relative, value in payloads.items():
        path = raw / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(json.dumps(value) + "\n")
    generation = seal_fixture_raw(raw, missing_strains="explicit_empty")
    monkeypatch.setattr(endpoint_outcomes, "CURATED_UNKNOWN_POLICY", generation.curated_policy_path)
    lookup = root / "lookup"
    lookup.mkdir()
    (lookup / "bacdive.tsv").write_text("bacdive_id\tncbitaxon_id\n")
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", lookup)
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", scratch)
    # Only unrelated ontology lookup/index work is replaced in this offline fixture.
    # Native generation parsing, recipe guards, all writers and dispatcher remain real.
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_roles", lambda self: None)
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_categories", lambda self: None)
    monkeypatch.setattr(mod, "ChemicalMappingLoader", _loader)
    prerequisites = []

    def native_prerequisite(cls, input_dir):
        """Observe actual dispatcher prerequisite invocation without a production NCIT database."""
        prerequisites.append(input_dir)
        return []

    monkeypatch.setattr(mod.MediaDiveTransform, "missing_prerequisites", classmethod(native_prerequisite))
    for upstream in mod.MediaDiveTransform.TRANSFORM_INPUTS:
        directory = transformed / upstream
        directory.mkdir(parents=True)
        (directory / "source_fingerprint.json").write_text('{"version":3,"fixture_only":true}\n')
    monkeypatch.setattr(canary, "ROOT", root)
    monkeypatch.setattr(canary, "EVIDENCE", root / "data/evidence/canary")
    native = {"catalogue_count": 2, "first_medium": first, "recipe": detail["solutions"][0]["recipe"]}
    return SimpleNamespace(
        root=root,
        raw=raw,
        transformed=transformed,
        summary=scratch / "mediadive.tsv",
        native=native,
        prerequisites=prerequisites,
        generation=generation,
    )


def first_run(value):
    """Run the real dispatcher until only its progress observer interrupts it."""
    return canary.dispatch_first(DISPATCHER, mod, value.raw, value.transformed, 2)


def test_actual_writer_stops_after_first_complete_medium_and_keeps_native_guards(actual_writer):
    """Exact first-medium rows survive unwinding without finalization or a source marker."""
    value, observation = first_run(actual_writer)
    assert actual_writer.prerequisites == [actual_writer.raw]
    assert observation["updates"] == 1 and not any(observation["network_attempts"].values())
    report = canary.partial_graph(value, actual_writer.native, actual_writer.summary)
    assert len(report["native_occurrences"]) == 4
    identities = canary.retained_inputs(value, SourceAdmission())
    assert identities["native_contract"]["endpoint_coverage"]["sealed"] is False
    assert value._consumed_input_error == canary.STOP_MESSAGE
    with pytest.raises(SourceFinalizationRequired, match="Consumed-input read failed"):
        value.verify_consumed_inputs()
    with pytest.raises(SourceFinalizationRequired):
        value.finalize(fresh_run=True)
    assert not (value.output_dir / "source_finalization.json").exists()
    assert not (value.output_dir / "source_fingerprint.json").exists()


def test_real_dispatcher_requires_upstream_completion_before_running(actual_writer):
    """The helper retains upstream prerequisite checks rather than calling a selected writer directly."""
    marker = actual_writer.transformed / "bacdive/source_fingerprint.json"
    marker.unlink()
    with pytest.raises(FileNotFoundError, match="completed bacdive"):
        first_run(actual_writer)
    assert not (actual_writer.transformed / "mediadive").exists()
    assert not actual_writer.summary.exists()


def test_changed_original_read_cannot_pass_bounded_proof(actual_writer):
    """A source read modified after the callback is refused without clearing the sticky error."""
    value, _ = first_run(actual_writer)
    path = Path(value.consumed_input_snapshots["mediadive_media_list"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Original native consumed bytes changed"):
        canary.retained_inputs(value, SourceAdmission())
    assert value._consumed_input_error == canary.STOP_MESSAGE


def test_cached_native_recipe_mutation_is_detected(actual_writer):
    """Unchanged files cannot legitimize a changed in-memory native payload."""
    value, _ = first_run(actual_writer)
    value.solutions_data["1"]["recipe"][0]["amount"] = 99
    with pytest.raises(ValueError, match="cached payload changed"):
        canary.retained_inputs(value, SourceAdmission())


def test_quantity_context_and_extra_medium_are_not_accepted(actual_writer):
    """Partial graph checks bind exact occurrence context and native quantity cells."""
    value, _ = first_run(actual_writer)
    changed = copy.deepcopy(actual_writer.native)
    changed["recipe"][0]["amount"] = 999
    with pytest.raises(ValueError, match="recipe context changed"):
        canary.partial_graph(value, changed, actual_writer.summary)
    with value.output_node_file.open("a") as stream:
        stream.write("mediadive.medium:2\tbiolink:NamedThing\twrong\n")
    with pytest.raises(ValueError, match="medium graph scope"):
        canary.partial_graph(value, actual_writer.native, actual_writer.summary)


def test_preservation_refuses_unrelated_members_and_existing_destinations(actual_writer):
    """Only the exact newly owned partial cohort may move to exclusive evidence."""
    value, _ = first_run(actual_writer)
    evidence = actual_writer.root / "data/evidence/attempt"
    evidence.mkdir(parents=True)
    before = canary.output_identities(value.output_dir, actual_writer.summary)
    unrelated = value.output_dir / "unrelated.txt"
    unrelated.write_text("retain me")
    with pytest.raises(ValueError, match="Unexpected output member"):
        canary.preserve_partial(value.output_dir, actual_writer.summary, evidence, before)
    assert unrelated.read_text() == "retain me"
    unrelated.unlink()
    (evidence / "partial-output").mkdir()
    with pytest.raises(ValueError, match="destination exists"):
        canary.preserve_partial(value.output_dir, actual_writer.summary, evidence, before)
    assert value.output_node_file.is_file() and actual_writer.summary.is_file()


def test_preserved_interruption_does_not_poison_fresh_native_dispatcher(actual_writer, monkeypatch):
    """A fresh instance completes both native records; this isolated test does not certify source admission."""
    value, _ = first_run(actual_writer)
    evidence = actual_writer.root / "data/evidence/attempt"
    evidence.mkdir(parents=True)
    before = canary.output_identities(value.output_dir, actual_writer.summary)
    saved = canary.preserve_partial(value.output_dir, actual_writer.summary, evidence, before)
    assert len(saved) == 3 and not value.output_dir.exists() and not actual_writer.summary.exists()
    completed = []

    def writer_completion(instance):
        """Verify full native writer guards while isolating unrelated ontology closure finalization."""
        assert instance is not value
        instance.verify_consumed_inputs()
        assert instance._recipe_identity_guard.sealed
        assert instance._endpoint_consumer.contract()["sealed"]
        assert len(instance._recipe_identity_guard.observed) == 8
        completed.append(instance)

    monkeypatch.setattr(DISPATCHER, "_finalize_output", writer_completion)
    monkeypatch.setattr(DISPATCHER, "_record_fingerprint", lambda *args: None)
    DISPATCHER.transform(actual_writer.raw, actual_writer.transformed, sources=["mediadive"], show_status=False)
    assert len(completed) == 1
    assert len(canary.tsv_rows(actual_writer.summary)) == 2
    assert value._consumed_input_error == canary.STOP_MESSAGE
    assert all(canary.digest(path) == identity["sha256"] for path, identity in saved.items())


@pytest.mark.parametrize("operation", ["request", "connect"])
def test_network_tripwire_escapes_ordinary_exception_handlers(operation):
    """A hidden fallback cannot swallow a network attempt as an ordinary record failure."""
    with canary.no_network() as counts, pytest.raises(canary.NetworkAttempt):
        try:
            if operation == "request":
                requests.Session().get("https://invalid.example/never-contact")
            else:
                with socket.socket() as connection:
                    connection.connect(("127.0.0.1", 1))
        except Exception:
            pytest.fail("Network interruption is an ordinary Exception")
    assert sum(counts.values()) == 1


@pytest.mark.parametrize("kind", ["wrong_description", "missing_description", "wrong_total"])
def test_observer_rejects_wrong_or_missing_native_callback(kind):
    """An observer event cannot stand in for the exact first completed medium."""
    with pytest.raises(ValueError):
        observer = canary.FirstMediumObserver(3, total=4 if kind == "wrong_total" else 3, desc="Processing files")
        if kind == "wrong_description":
            observer.set_description("Processing mediadive: mediadive.medium:2")
        observer.update()


def test_missing_callback_is_not_a_success(monkeypatch, tmp_path):
    """A dispatcher that returns normally is not mislabeled as a bounded canary."""
    empty = SimpleNamespace(transform=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="without the required bounded interruption"):
        canary.dispatch_first(empty, mod, tmp_path, tmp_path, 2)


def test_unrelated_failure_preserves_actual_partial_outputs(actual_writer, monkeypatch):
    """The executable failure path retains partial bytes and writes only a failed receipt."""
    guard = SourceAdmission()
    monkeypatch.setattr(canary, "runtime", lambda: (DISPATCHER, mod))
    monkeypatch.setattr(canary, "prepare_inputs", lambda module: (guard, actual_writer.native))

    def unrelated(self, n=1):
        """Fail at the same writer boundary for a reason other than the approved sentinel."""
        raise RuntimeError("Explicit unrelated offline failure")

    monkeypatch.setattr(canary.FirstMediumObserver, "update", unrelated)
    with pytest.raises(DISPATCHER.TransformBatchError):
        canary.execute("unrelated-failure")
    receipt = json.loads((canary.EVIDENCE / "unrelated-failure/result.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["source_completed"] is receipt["source_admitted"] is False
    assert (actual_writer.transformed / "mediadive/nodes.tsv").is_file()
    assert actual_writer.summary.is_file()
    assert not (canary.EVIDENCE / "unrelated-failure/partial-output").exists()


@pytest.mark.parametrize("collision", ["source", "summary", "evidence", "link"])
def test_plan_refuses_preexisting_or_linked_owned_paths(actual_writer, collision):
    """A plan cannot authorize reuse, deletion or overwriting of earlier output."""
    paths = {
        "source": actual_writer.transformed / "mediadive",
        "summary": actual_writer.summary,
        "evidence": canary.EVIDENCE / "attempt",
        "link": actual_writer.transformed / "mediadive",
    }
    path = paths[collision]
    path.parent.mkdir(parents=True, exist_ok=True)
    if collision == "link":
        path.symlink_to(actual_writer.root / "absent")
    elif collision == "summary":
        path.write_text("prior summary")
    else:
        path.mkdir()
    with pytest.raises(ValueError):
        canary.plan("attempt")
    assert path.is_symlink() or path.exists()


def test_default_plan_never_creates_output_or_attempt(actual_writer, capsys):
    """The CLI requires explicit execution and has no input or medium override option."""
    assert canary.main(["--label", "planned"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["source_completed"] is record["source_admitted"] is False
    assert not canary.EVIDENCE.exists()
    assert not (actual_writer.transformed / "mediadive").exists()
    with pytest.raises(SystemExit):
        canary.main(["--label", "planned", "--medium", "2"])


def test_execute_receipt_keeps_partial_source_unadmitted(actual_writer, monkeypatch):
    """The actual writer/preservation composition publishes only a bounded interruption receipt."""
    guard = SourceAdmission()
    monkeypatch.setattr(canary, "runtime", lambda: (DISPATCHER, mod))
    monkeypatch.setattr(canary, "prepare_inputs", lambda module: (guard, actual_writer.native))
    monkeypatch.setattr(
        canary, "origins", lambda: {"fixture": {"path": str(Path(mod.__file__)), "sha256": canary.digest(mod.__file__)}}
    )
    result = canary.execute("bounded-success")
    directory = canary.EVIDENCE / "bounded-success"
    recorded = json.loads((directory / "result.json").read_text())
    assert recorded["status"] == result["status"] == "bounded_interruption_verified"
    assert recorded["source_completed"] is recorded["source_admitted"] is False
    assert recorded["api_calls_made"] == 0
    assert recorded["graph"]["summary_rows"] == 1
    assert len(recorded["graph"]["native_occurrences"]) == 4
    assert len(recorded["preserved_outputs"]) == 3
    assert not actual_writer.summary.exists()
    assert not (actual_writer.transformed / "mediadive").exists()
    assert not (directory / "partial-output/source_finalization.json").exists()
    assert not (directory / "partial-output/source_fingerprint.json").exists()
    assert all(canary.digest(path) == identity["sha256"] for path, identity in recorded["preserved_outputs"].items())
    assert canary.digest(directory / "original-input-identities.json") == recorded["input_identities_sha256"]
