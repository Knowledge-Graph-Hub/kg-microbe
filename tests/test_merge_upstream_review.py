"""Independent recursive freshness review: matching consumer metadata is not enough (#1092)."""

import inspect
import json
import shutil
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.transform_fingerprint import upstream_fingerprint, write_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "resources/merge_source_freshness"
pytestmark = pytest.mark.usefixtures("local_source_schema")


def _record(transform):
    """Record actual registered code/declarations without executing a producer or adapter."""
    cls = type(transform)
    return write_fingerprint(
        transform.output_dir,
        Path(inspect.getsourcefile(cls)).parent,
        ROOT,
        cls.DATA_INPUTS,
        cls.TRANSFORM_INPUTS,
        input_dir=transform.input_base_dir,
        finalization_inputs=transform.finalization_inputs,
    )


def _prepare(tmp_path, name):
    """Finalize immutable tiny named fixtures with a registered class but inert base construction."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    cls = DATA_SOURCES[name].transform_class
    transform = cls.__new__(cls)
    Transform.__init__(transform, name, raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", transform.output_dir / f"{kind}.tsv")
    for role in getattr(cls, "REQUIRED_CONSUMED_INPUTS", ()):
        assert role == "bacdive_taxon_lookup", f"An explicit immutable fixture is required for {role}"
        lookup = tmp_path / f"{name}-bacdive-lookup.tsv"
        shutil.copyfile(FIXTURES / "lookup.tsv", lookup)
        with transform.consume_input(role, lookup) as reader:
            reader.read()
    transform.finalize(fresh_run=True)
    _record(transform)
    return transform


def _chain(tmp_path):
    """Prepare a real ontology-to-BacDive-to-MediaDive dependency chain in tmp_path only."""
    return {name: _prepare(tmp_path, name) for name in ("ontologies", "bacdive", "mediadive")}


def _config(tmp_path, sources):
    """Write an explicit source selection using arbitrary aliases rather than directory inference."""
    path = tmp_path / "merge-review.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path / "published")},
                "merged_graph": {
                    "source": {
                        alias: {
                            "input": {
                                "format": "tsv",
                                "filename": [str(source.output_node_file), str(source.output_edge_file)],
                            }
                        }
                        for alias, source in sources.items()
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        )
    )
    return str(path)


@pytest.mark.parametrize("damage", ["missing", "unsupported", "invalid_json", "code", "shared", "data", "schema"])
def test_rerecorded_consumer_cannot_bless_invalid_upstream(tmp_path, monkeypatch, damage):
    """Matching upstream digest cannot make a missing, unreadable, or stale upstream current."""
    prepared = _chain(tmp_path)
    consumer, upstream = prepared["mediadive"], prepared["bacdive"]
    config = _config(tmp_path, {"selected_consumer": consumer})
    merge_kg._assert_sources_finalized(config)
    upstream_marker = upstream.output_dir / "source_fingerprint.json"
    payload = json.loads(upstream_marker.read_text())
    if damage == "missing":
        upstream_marker.unlink()
    elif damage == "invalid_json":
        upstream_marker.write_text("{not valid JSON}")
    else:
        if damage == "unsupported":
            payload["version"] = 999
        elif damage == "schema":
            payload["schema"] = {"version": "obsolete", "digest": "obsolete"}
        else:
            payload[damage] = "previous-content-fingerprint"
        upstream_marker.write_text(json.dumps(payload))
    consumer_marker = _record(consumer)
    assert consumer_marker["upstream"] == upstream_fingerprint(
        consumer.output_base_dir, type(consumer).TRANSFORM_INPUTS
    )
    archive = tmp_path / "published/fixture.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"previous independently valid archive")
    before = {path.name: path.read_bytes() for path in archive.parent.iterdir()}

    def no_kgx(*args, **kwargs):
        """Fail if incomplete dependency validation admits KGX or publication."""
        pytest.fail("KGX must not run for a recursively stale upstream")

    monkeypatch.setattr(merge_kg, "merge", no_kgx)
    with pytest.raises(SourceFinalizationRequired):
        merge_kg.load_and_merge(config, sources=["selected_consumer"])
    assert before == {path.name: path.read_bytes() for path in archive.parent.iterdir()}


def test_new_upstream_declared_data_is_not_hidden_by_recorded_inputs(tmp_path, monkeypatch):
    """A current declaration absent from an old marker still invalidates that upstream output."""
    prepared = _chain(tmp_path)
    consumer, upstream = prepared["mediadive"], prepared["bacdive"]
    config = _config(tmp_path, {"selected_consumer": consumer})
    merge_kg._assert_sources_finalized(config)
    declaration = tmp_path / "new-reviewed-mapping.tsv"
    declaration.write_text("source\ttarget\nfixture:1\tfixture:2\n")
    cls = type(upstream)
    monkeypatch.setattr(cls, "DATA_INPUTS", (*cls.DATA_INPUTS, str(declaration)))
    upstream_record = json.loads((upstream.output_dir / "source_fingerprint.json").read_text())
    assert str(declaration) not in upstream_record.get("finalization_inputs", [])
    consumer_record = _record(consumer)
    assert consumer_record["upstream"] == upstream_fingerprint(
        consumer.output_base_dir, type(consumer).TRANSFORM_INPUTS
    )
    with pytest.raises(SourceFinalizationRequired):
        merge_kg._assert_sources_finalized(config)


def test_subset_checks_required_upstreams_but_not_unrelated_stale_source(tmp_path):
    """Selecting one source traverses its dependencies without gating unrelated configured rows."""
    prepared = _chain(tmp_path)
    unrelated = _prepare(tmp_path, "madin_etal")
    marker_path = unrelated.output_dir / "source_fingerprint.json"
    marker = json.loads(marker_path.read_text())
    marker["code"] = "older-unrelated-code"
    marker_path.write_text(json.dumps(marker))
    config = _config(tmp_path, {"keep": prepared["mediadive"], "not_selected": unrelated})
    merge_kg._assert_sources_finalized(config, sources=["keep"])
    with pytest.raises(SourceFinalizationRequired):
        merge_kg._assert_sources_finalized(config)


@pytest.mark.parametrize("damage", ["missing_schema", "stale_schema"])
def test_valid_scoped_fallback_cannot_hide_incomplete_whole_schema(tmp_path, damage):
    """An exact scoped pair still needs current schema evidence when its whole record is stale."""
    ontology = _prepare(tmp_path, "ontologies")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", ontology.output_dir / f"pato_{kind}.tsv")
    ontology.finalize(fresh_run=True)
    _record(ontology)
    nodes = ontology.output_dir / "pato_nodes.tsv"
    nodes.write_text(nodes.read_text().replace("One", "Updated"))
    ontology.finalize(file_prefix="pato_", fresh_run=True)
    ontology.output_node_file = nodes
    ontology.output_edge_file = ontology.output_dir / "pato_edges.tsv"
    config = _config(tmp_path, {"arbitrary_scoped_alias": ontology})
    merge_kg._assert_sources_finalized(config)

    marker_path = ontology.output_dir / "source_fingerprint.json"
    marker = json.loads(marker_path.read_text())
    if damage == "missing_schema":
        del marker["schema"]
    else:
        marker["schema"] = {"version": "older-pinned-schema", "digest": "older-pinned-bytes"}
    marker_path.write_text(json.dumps(marker))
    with pytest.raises(SourceFinalizationRequired, match="schema"):
        merge_kg._assert_sources_finalized(config)
