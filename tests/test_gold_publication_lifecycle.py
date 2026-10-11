"""Actual GOLD CLI publication retains native guards across legitimate output replacement (#1342)."""

import json
import os

import pytest

from kg_microbe.transform_utils.gold import selected_taxon_aliases as aliases
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests import test_gold_alias_producer_integration as alias_fixtures
from tests import test_gold_taxon_dispositions as taxonomy_fixtures
from tests.test_gold_taxon_dispositions import _read, _write


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Reuse the complete reviewed eleven-record native alias producer fixture."""
    return alias_fixtures.source.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def native_referents(tmp_path, monkeypatch):
    """Reuse genuine native referents including the original nameless GOLD record."""
    return taxonomy_fixtures.source.__wrapped__(tmp_path, monkeypatch)


def test_actual_dispatcher_records_marker_on_same_published_producer(source, monkeypatch):
    """Run the real producer, finalizer and fingerprint writer, not a mocked success callback."""
    import kg_microbe.transform as dispatcher

    with monkeypatch.context() as factory:
        factory.setitem(dispatcher.DATA_SOURCES, "gold", lambda *args: source)
        dispatcher._run_one("gold", source.input_base_dir, source.output_base_dir, False)
    # Public admission must inspect the genuine registered producer contract,
    # not the test's temporary factory for selecting this exact live instance.
    source.verify_consumed_inputs()
    marker = source.output_dir / "source_fingerprint.json"
    assert json.loads(marker.read_text())["version"] == 3
    first = json.loads((source.output_dir / "source_finalization.json").read_text())
    assert source.finalize() == first
    source.verify_consumed_inputs()


def test_same_instance_publication_preserves_own_nameless_gold_declaration(native_referents):
    """The genuine unnamed source referent keeps its admitted proof after retiring live output guards."""
    native_referents.run()
    first = native_referents.finalize(fresh_run=True)
    native_referents.verify_consumed_inputs()
    proof = native_referents._gold_declaration_guard.declaration_for("gold:Go0531699")
    assert proof is not None and proof.declaration["name"] == ""
    assert native_referents.finalize() == first


@pytest.mark.parametrize("target", ["raw", "audit", "graph"])
def test_same_instance_rejects_late_equal_byte_replacements(source, target):
    """Publication does not authorize later inode replacement of native inputs or admitted outputs."""
    source.finalize(fresh_run=True)
    path = {
        "raw": source.input_base_dir / "ncbitaxon_removed_subset.json",
        "audit": source.output_dir / aliases.AUDIT_FILE,
        "graph": source.output_edge_file,
    }[target]
    replacement = path.with_suffix(path.suffix + ".replacement")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    with pytest.raises(SourceFinalizationRequired):
        source.verify_consumed_inputs()


@pytest.mark.parametrize("mutation", ["raw_equal_bytes", "returned_contract"])
def test_publication_transition_cannot_rebase_mutated_native_boundary(source, monkeypatch, mutation):
    """Changes in the publication window are refused before retiring original native guards."""
    from kg_microbe.utils import source_finalization

    original_publish = source_finalization._publish_finalization
    old_guard = source._crosswalk_quarantine

    def changed(transform, prepared):
        """Inject one change after actual publication and before producer transition."""
        report = original_publish(transform, prepared)
        if mutation == "raw_equal_bytes":
            path = source.input_base_dir / "ncbitaxon_removed_subset.json"
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        else:
            report["producer_native_inputs"].pop(aliases.CONTRACT_KEY)
        return report

    monkeypatch.setattr(source_finalization, "_publish_finalization", changed)
    with pytest.raises(SourceFinalizationRequired):
        source.finalize(fresh_run=True)
    assert source._crosswalk_quarantine is old_guard
    assert source._recorded_native_guard is None
    with pytest.raises(SourceFinalizationRequired, match="previously failed"):
        source.verify_consumed_inputs()


def test_failed_base_publication_does_not_transition_or_write_success_marker(source, monkeypatch):
    """Only a completed and independently rejoined publication can enter recorded mode."""
    import kg_microbe.transform as dispatcher
    from kg_microbe.utils import source_finalization

    old_guard = source._crosswalk_quarantine

    def fail(*args):
        """Simulate publication failure before any successful return."""
        raise OSError("deliberate publication failure")

    monkeypatch.setattr(source_finalization, "_publish_finalization", fail)
    with pytest.raises(OSError, match="deliberate"):
        source.finalize(fresh_run=True)
    assert source._crosswalk_quarantine is old_guard and source._recorded_native_guard is None
    dispatcher._record_fingerprint(source, "gold")
    assert not (source.output_dir / "source_fingerprint.json").exists()


def test_published_original_producer_rejects_environment_reinterpretation(source):
    """The successful same-instance callback still rejects semantic output drift."""
    source.finalize(fresh_run=True)
    rows = _read(source.output_edge_file)
    location = next(row for row in rows if row["predicate"] == "biolink:located_in")
    location["original_object"] = ""
    _write(source.output_edge_file, list(rows[0]), rows)
    with pytest.raises(SourceFinalizationRequired):
        source.verify_consumed_inputs()
