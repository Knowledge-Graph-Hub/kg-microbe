"""Independent public-gate checks for required producer-read snapshots."""

import hashlib
import json
import shutil

import pytest

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_merge_source_freshness import FIXTURES, merge_config, prepare_source, record_source


def _prepared_consumer(tmp_path, source="mediadive"):
    """Build only tiny immutable source pairs and their real registered dependency metadata."""
    prepare_source(tmp_path, "ontologies")
    prepare_source(tmp_path, "bacdive")
    consumer = prepare_source(tmp_path, source)
    assert "bacdive_taxon_lookup" in type(consumer).REQUIRED_CONSUMED_INPUTS
    config = merge_config(tmp_path, [consumer])
    merge_kg._assert_sources_finalized(str(config))
    return consumer, config


def _assert_rejected_without_publication(consumer, config, tmp_path, monkeypatch):
    """Require both repeat and public entry rejection without changing source or published bytes."""
    before = {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    archive = tmp_path / "published/fixture.tar.gz"
    archive.parent.mkdir(exist_ok=True)
    archive.write_bytes(b"previous validated graph")

    def no_kgx(*args, **kwargs):
        """Fail if lost producer-read evidence admits KGX."""
        pytest.fail("KGX must not run without valid required consumed-input snapshots")

    monkeypatch.setattr(merge_kg, "merge", no_kgx)
    paths = [consumer.output_node_file, consumer.output_edge_file]
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(paths)
    with pytest.raises(SourceFinalizationRequired):
        merge_kg.load_and_merge(str(config))
    # A newly reconstructed object has no in-memory snapshot to accidentally
    # rescue damaged persisted evidence during the repeat-finalize API.
    repeated = type(consumer).__new__(type(consumer))
    Transform.__init__(repeated, consumer.source_name, consumer.input_base_dir, consumer.output_base_dir)
    with pytest.raises(SourceFinalizationRequired):
        repeated.finalize()
    assert before == {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    assert archive.read_bytes() == b"previous validated graph"


@pytest.mark.parametrize(
    "damage",
    [
        "missing_role",
        "missing_map",
        "malformed_map",
        "all_bindings_removed",
        "wrong_source_label",
        "unknown_source_label",
    ],
)
def test_required_snapshot_cannot_be_omitted_from_current_metadata(tmp_path, monkeypatch, damage):
    """Current graph/code/audits and a re-recorded marker do not replace a required named read."""
    consumer, config = _prepared_consumer(tmp_path)
    record_path = consumer.output_dir / "source_finalization.json"
    report = json.loads(record_path.read_text())
    lookup = report["consumed_inputs"]["bacdive_taxon_lookup"]["path"]
    if damage == "missing_map":
        report.pop("consumed_inputs")
    elif damage == "malformed_map":
        report["consumed_inputs"] = []
    else:
        report["consumed_inputs"] = {}
    if damage in {"all_bindings_removed", "wrong_source_label", "unknown_source_label"}:
        report["inputs"] = [item for item in report["inputs"] if item["path"] != lookup]
    if damage == "wrong_source_label":
        report["source"] = "rhea_mappings"
    elif damage == "unknown_source_label":
        report["source"] = "unregistered_alias"
    record_path.write_text(json.dumps(report))
    consumer.finalization_inputs = tuple(item["path"] for item in report["inputs"])
    record_source(consumer)
    _assert_rejected_without_publication(consumer, config, tmp_path, monkeypatch)


@pytest.mark.parametrize("source", ["mediadive", "bactotraits"])
def test_current_generic_hash_cannot_restamp_original_consumed_bytes(tmp_path, monkeypatch, source):
    """Changing a lookup and generic hashes cannot bless graph rows based on the earlier read."""
    consumer, config = _prepared_consumer(tmp_path, source)
    record_path = consumer.output_dir / "source_finalization.json"
    report = json.loads(record_path.read_text())
    snapshot = report["consumed_inputs"]["bacdive_taxon_lookup"]
    shutil.copyfile(FIXTURES / "changed_lookup.tsv", snapshot["path"])
    changed_digest = hashlib.sha256((FIXTURES / "changed_lookup.tsv").read_bytes()).hexdigest()
    assert changed_digest != snapshot["sha256"]
    for item in report["inputs"]:
        if item["path"] == snapshot["path"]:
            item["sha256"] = changed_digest
    record_path.write_text(json.dumps(report))
    record_source(consumer)
    _assert_rejected_without_publication(consumer, config, tmp_path, monkeypatch)


def test_selected_downstream_requires_upstream_consumed_snapshot(tmp_path, monkeypatch):
    """Recursive freshness must validate named reads of required upstreams, not only selected files."""
    upstream, _ = _prepared_consumer(tmp_path)
    cls = DATA_SOURCES["madin_etal"].transform_class
    monkeypatch.setattr(cls, "TRANSFORM_INPUTS", ("mediadive",))
    consumer = prepare_source(tmp_path, "madin_etal")
    config = merge_config(tmp_path, [consumer])
    merge_kg._assert_sources_finalized(str(config))
    record_path = upstream.output_dir / "source_finalization.json"
    report = json.loads(record_path.read_text())
    report["consumed_inputs"] = {}
    record_path.write_text(json.dumps(report))
    # The selected downstream is independently valid. Only recursion discovers
    # the upstream's missing required logical binding; all generic hashes stay.
    verify_finalized_source_files([consumer.output_node_file, consumer.output_edge_file])
    archive = tmp_path / "published/fixture.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"previous validated graph")

    def no_kgx(*args, **kwargs):
        """Fail if a recursively missing consumed binding admits publication."""
        pytest.fail("KGX must not run without upstream required consumed-input evidence")

    monkeypatch.setattr(merge_kg, "merge", no_kgx)
    with pytest.raises(SourceFinalizationRequired, match="upstream.*consumed"):
        merge_kg.load_and_merge(str(config))
    assert archive.read_bytes() == b"previous validated graph"
