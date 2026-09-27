"""Actual KGX public-export equivalence and fail-closed eligibility for #1189."""

import copy
import csv
import hashlib
import io
import json
import shutil
import tarfile
from importlib.metadata import PackageNotFoundError
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import kgx_source, merge_kg
from kg_microbe.merge_utils.progress import MergeProgress
from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION

FIXTURE = Path(__file__).parent / "resources/merge_direct_export"


@pytest.fixture(autouse=True)
def offline_pool(monkeypatch):
    """Run the actual source readers in hermetic threads rather than spawned interpreters."""
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    with kgx_source.local_prefix_context():
        yield


def configuration(tmp_path, *, empty=False, statistics=False):
    """Copy immutable inputs; actual public staging, validation and packaging remain enabled."""
    inputs = tmp_path / "input"
    inputs.mkdir(parents=True)
    sources = {}
    for source in ("alpha", "beta"):
        filenames = []
        for kind in ("nodes", "edges"):
            original = FIXTURE / f"{source}_{kind}.tsv"
            target = inputs / original.name
            if empty:
                target.write_text(original.read_text().splitlines()[0] + "\n")
            else:
                shutil.copyfile(original, target)
            filenames.append(str(target))
        sources[source] = {"input": {"format": "tsv", "filename": filenames}}
    graph = {
        "source": sources,
        "destination": {"release": {"format": "tsv", "filename": "result", "compression": "tar.gz"}},
    }
    if statistics:
        graph["operations"] = [
            {"name": STATS_OPERATION, "args": {"graph_name": "fixture", "filename": str(tmp_path / "stats.yaml")}}
        ]
    config = {
        "configuration": {"output_directory": str(tmp_path / "out"), "allow_unfinalized_sources": True},
        "merged_graph": graph,
    }
    path = tmp_path / "merge.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def archive_rows(path):
    """Check exact archive member bytes against its manifest and return literal TSV rows."""
    with tarfile.open(path) as archive:
        payloads = {member.name: archive.extractfile(member).read() for member in archive.getmembers()}
    manifest = json.loads(payloads.pop("manifest.json"))
    for name, metadata in manifest["members"].items():
        payload = payloads[name]
        assert metadata == {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "rows": len(payload.splitlines()) - 1,
        }
    return payloads, {
        name: list(csv.DictReader(io.StringIO(payload.decode()), delimiter="\t", quoting=csv.QUOTE_NONE))
        for name, payload in payloads.items()
    }


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("statistics", [False, True])
def test_actual_public_export_matches_old_path_without_second_graph(tmp_path, monkeypatch, empty, statistics):
    """Real archive outputs are byte-identical while only the old destination builds GraphSink."""
    from kgx import transformer as transformer_module

    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    calls = []
    real_init = kgx_source.RelationAwareGraphSink.__init__

    def tracked_sink(self, owner):
        """Distinguish ingestion sinks from destination sinks by the completed-graph scope."""
        scope = kgx_source._DIRECT_EXPORT.get()
        calls.append(scope is not None and scope["graph"] is not None)
        real_init(self, owner)

    monkeypatch.setattr(kgx_source.RelationAwareGraphSink, "__init__", tracked_sink)
    fast = configuration(tmp_path / "fast", empty=empty, statistics=statistics)
    before = fast.read_bytes()
    fast_graph = merge_kg.load_and_merge(str(fast))
    assert calls == [False, False]
    assert fast.read_bytes() == before
    assert kgx_source._DIRECT_EXPORT.get() is None
    assert transformer_module.GraphSink is not kgx_source.RelationAwareGraphSink
    fast_payload, fast_rows = archive_rows(fast.parent / "out/result.tar.gz")
    calls.clear()
    with monkeypatch.context() as old:
        old.setattr(kgx_source, "_eligible_merge_configuration", lambda *args: False)
        baseline = configuration(tmp_path / "baseline", empty=empty, statistics=statistics)
        baseline_graph = merge_kg.load_and_merge(str(baseline))
    assert len(calls) == 3  # Two ingestion graphs plus the old intermediate export graph.
    old_payload, _ = archive_rows(baseline.parent / "out/result.tar.gz")
    assert fast_payload == old_payload
    assert fast_graph.number_of_nodes() == baseline_graph.number_of_nodes() == (0 if empty else 3)
    assert fast_graph.number_of_edges() == baseline_graph.number_of_edges() == (0 if empty else 4)
    assert "empty_edge_extension" in fast_payload["result_edges.tsv"].decode().splitlines()[0]
    if not empty:
        nodes = {row["id"]: row for row in fast_rows["result_nodes.tsv"]}
        assert nodes["NCBITaxon:1"]["provided_by"] == "infores:alpha|infores:beta"
        assert nodes["fixture:stub"]["provided_by"] == ""
        assert {row["primary_knowledge_source"] for row in fast_rows["result_edges.tsv"]} == {
            "infores:alpha",
            "infores:beta",
        }
    if statistics:
        fast_stats = yaml.safe_load((fast.parent / "stats.yaml").read_text())
        old_stats = yaml.safe_load((baseline.parent / "stats.yaml").read_text())
        for section in ("node_stats", "edge_stats"):
            assert fast_stats[section] == old_stats[section]


@pytest.mark.parametrize("where", ["source", "input", "merged"])
def test_prior_graph_operations_invalidate_eligibility(where):
    """Earlier arbitrary operations are not approved merely because export operations are empty."""
    config = {"merged_graph": {"source": {"one": {"input": {"format": "tsv"}}}}}
    assert kgx_source._eligible_merge_configuration(config)
    graph = config["merged_graph"]
    target = {"source": graph["source"]["one"], "input": graph["source"]["one"]["input"], "merged": graph}[where]
    target["operations"] = [{"name": "unreviewed.mutate_graph", "args": {}}]
    assert not kgx_source._eligible_merge_configuration(config)


def test_unknown_kgx_version_and_non_tsv_inputs_fall_back(monkeypatch):
    """The optimization promises the inspected locked interface, not other installed versions."""
    config = {"merged_graph": {"source": {"one": {"input": {"format": "tsv"}}}}}
    monkeypatch.setattr(kgx_source, "version", lambda name: "2.8.0")
    assert not kgx_source._eligible_merge_configuration(config)
    monkeypatch.setattr(kgx_source, "version", lambda name: "2.7.0")
    config["merged_graph"]["source"]["one"]["input"]["format"] = "graph"
    assert not kgx_source._eligible_merge_configuration(config)


@pytest.mark.parametrize("error", [PackageNotFoundError("kgx"), OSError("unreadable package metadata")])
def test_unavailable_kgx_metadata_disables_only_optimization(monkeypatch, error):
    """Retain the old usable importer when optional version evidence cannot be read."""
    config = {"merged_graph": {"source": {"one": {"input": {"format": "tsv"}}}}}

    def unavailable(name):
        """Represent an absent distribution or a concrete metadata I/O failure."""
        raise error

    monkeypatch.setattr(kgx_source, "version", unavailable)
    assert not kgx_source._eligible_merge_configuration(config)


def test_version_programming_error_is_not_swallowed(monkeypatch):
    """Do not turn arbitrary eligibility defects into a silent fallback."""

    def broken(name):
        """Represent a programming defect rather than unavailable metadata."""
        raise RuntimeError("programming defect")

    monkeypatch.setattr(kgx_source, "version", broken)
    with pytest.raises(RuntimeError, match="programming defect"):
        kgx_source._eligible_merge_configuration({})


def test_scoped_graph_identity_and_nested_failure_restore():
    """No eligibility survives a failed merge or transfers to an arbitrary graph object."""
    config = {"merged_graph": {"source": {"one": {"input": {"format": "tsv"}}}}}
    with kgx_source.direct_export_scope(config):
        scope = kgx_source._DIRECT_EXPORT.get()
        assert scope == {"graph": None}
        arbitrary = {"format": "graph", "graph": object()}
        assert not kgx_source._eligible_graph_export(arbitrary, {}, None, 1)
        with pytest.raises(RuntimeError, match="stop"), kgx_source.direct_export_scope(config):
            raise RuntimeError("stop")
        assert kgx_source._DIRECT_EXPORT.get() is scope
    assert kgx_source._DIRECT_EXPORT.get() is None


@pytest.mark.parametrize("failure", ["serialization", "validation", "packaging", "admission"])
def test_direct_path_failure_preserves_published_archive_and_adapter_state(tmp_path, monkeypatch, failure):
    """Required late failures still prevent publication and restore all scoped overrides."""
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils

    config = configuration(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    previous = output / "result.tar.gz"
    previous.write_bytes(b"previous accepted archive")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    state = (
        cli_utils.Transformer,
        cli_utils.parse_source,
        cli_utils.merge_all_graphs,
        transformer_module.GraphSink,
        dict(transformer_module.SOURCE_MAP),
        dict(transformer_module.SINK_MAP),
    )

    def fail(*args, **kwargs):
        """Inject one required failure without replacing the rest of the export pipeline."""
        raise RuntimeError("required-stage failure")

    if failure == "serialization":
        monkeypatch.setattr(kgx_source.RelationAwareTsvSink, "write_edge", fail)
    elif failure == "validation":
        monkeypatch.setattr(merge_kg, "write_merge_validation_report", fail)
    elif failure == "packaging":
        monkeypatch.setattr(merge_kg, "_rewrite_tarball", fail)
    else:
        real_package = merge_kg._rewrite_tarball

        def drift(*args, **kwargs):
            """Mutate the genuinely admitted config only after creating the private archive."""
            real_package(*args, **kwargs)
            config.write_text(config.read_text() + "\n# late drift\n")

        monkeypatch.setattr(merge_kg, "_rewrite_tarball", drift)
    with pytest.raises((RuntimeError, ValueError)):
        merge_kg.load_and_merge(str(config))
    assert previous.read_bytes() == b"previous accepted archive"
    assert state == (
        cli_utils.Transformer,
        cli_utils.parse_source,
        cli_utils.merge_all_graphs,
        transformer_module.GraphSink,
        dict(transformer_module.SOURCE_MAP),
        dict(transformer_module.SINK_MAP),
    )
    assert kgx_source._DIRECT_EXPORT.get() is None
    assert not list(tmp_path.glob(".out.merge-*"))


def test_progress_is_bounded_and_explicitly_flushed(monkeypatch):
    """Counters never log record payloads or flush once per observation."""
    calls = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: calls.append((args, kwargs)))
    progress = MergeProgress("export-edges", interval=3)
    for _ in range(8):
        progress.advance()
    progress.report("complete")
    assert len(calls) == 4
    assert all(kwargs == {"flush": True} for _, kwargs in calls)
    assert [f"rows={n}" in args[0] for (args, _), n in zip(calls, (0, 3, 6, 8), strict=True)] == [True] * 4


def add_normalized_duplicate(graph):
    """Test graph operation: create a differently keyed, normalization-equivalent observation."""
    _, _, data = next(iter(graph.edges(data=True)))
    duplicate = copy.deepcopy(data)
    duplicate["publications"] = list(reversed(duplicate.get("publications", [])))
    duplicate["relation"] = "http://purl.obolibrary.org/obo/RO_0000056"
    graph.add_edge(duplicate["subject"], duplicate["object"], edge_key="operation-created-copy", **duplicate)


def test_earlier_mutating_operation_keeps_real_intermediate_dedup(tmp_path, monkeypatch):
    """Normalizing distinct graph keys is observable work, so mutated graphs take the old path."""
    config = configuration(tmp_path)
    content = yaml.safe_load(config.read_text())
    content["merged_graph"]["operations"] = [{"name": f"{__name__}.add_normalized_duplicate", "args": {}}]
    config.write_text(yaml.safe_dump(content))
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)

    def forbidden_direct(*args, **kwargs):
        """Reject direct-export eligibility for any mutating configuration."""
        pytest.fail("mutated graph used direct export")

    monkeypatch.setattr(kgx_source.ProvenancePreservingTransformer, "_export_completed_graph", forbidden_direct)
    graph = merge_kg.load_and_merge(str(config))
    assert graph.number_of_edges() == 5  # Returned pre-export graph deliberately retains the operation.
    _, rows = archive_rows(tmp_path / "out/result.tar.gz")
    assert len(rows["result_edges.tsv"]) == 4  # Existing GraphSink canonicalizes/deduplicates it.


@pytest.mark.parametrize(
    "change", ["unregistered", "backend", "operations", "filters", "prefix", "missing", "inspector", "parallel"]
)
def test_destination_eligibility_rejects_unsupported_inputs(tmp_path, monkeypatch, change):
    """Identity, full inventories and unmodified graph-reader semantics are all required."""
    from kgx import transformer as transformer_module
    from kgx.graph.nx_graph import NxGraph

    monkeypatch.setitem(transformer_module.SOURCE_MAP, "graph", kgx_source.RelationAwareGraphSource)
    monkeypatch.setitem(transformer_module.SINK_MAP, "tsv", kgx_source.RelationAwareTsvSink)
    config = {"merged_graph": {"source": {"one": {"input": {"format": "tsv"}}}}}
    graph = NxGraph()
    inputs = {"format": "graph", "graph": graph}
    outputs = {"format": "tsv", "filename": str(tmp_path / "graph"), "node_properties": set(), "edge_properties": set()}
    inspector, parallel = None, 1
    with kgx_source.direct_export_scope(config):
        kgx_source._DIRECT_EXPORT.get()["graph"] = graph
        assert kgx_source._eligible_graph_export(inputs, outputs, inspector, parallel)
        if change == "unregistered":
            inputs["graph"] = object()
        elif change == "backend":
            inputs["graph"] = kgx_source._DIRECT_EXPORT.get()["graph"] = object()
        elif change == "operations":
            inputs["operations"] = []  # Even an unneeded extra argument is outside the finite interface.
        elif change == "filters":
            inputs["edge_filters"] = {"object_category": ["biolink:ChemicalEntity"]}
        elif change == "prefix":
            outputs["reverse_prefix_map"] = {"fixture": "https://example.org/"}
        elif change == "missing":
            del outputs["edge_properties"]
        elif change == "inspector":

            def inspector(*args):
                """Represent an unsupported inspection callback."""
                return None
        else:
            parallel = 2
        assert not kgx_source._eligible_graph_export(inputs, outputs, inspector, parallel)


@pytest.mark.parametrize("bad", ["unannounced", "control", "provider", "boolean"])
def test_direct_writer_refuses_invalid_fields_and_closes_files(tmp_path, monkeypatch, bad):
    """Strict field validation survives the missing intermediate graph, including cleanup on failure."""
    from kgx import transformer as transformer_module
    from kgx.graph.nx_graph import NxGraph

    monkeypatch.setitem(transformer_module.SOURCE_MAP, "graph", kgx_source.RelationAwareGraphSource)
    monkeypatch.setitem(transformer_module.SINK_MAP, "tsv", kgx_source.RelationAwareTsvSink)
    graph = NxGraph()
    graph.add_node("fixture:1", id="fixture:1", name="fixture", category=["biolink:NamedThing"], provided_by=[])
    edge = {
        "subject": "fixture:1",
        "predicate": "biolink:related_to",
        "object": "fixture:1",
        "relation": "",
        "primary_knowledge_source": "infores:alpha",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
    }
    if bad == "unannounced":
        edge["lost_extension"] = "must not disappear"
    elif bad == "control":
        graph.nodes()["fixture:1"]["name"] = "invalid\ttext"
    elif bad == "provider":
        edge["primary_knowledge_source"] = ["infores:alpha", "infores:beta"]
    else:
        graph.nodes()["fixture:1"]["deprecated"] = [False, True]
    graph.add_edge("fixture:1", "fixture:1", edge_key="test", **edge)
    transformer = kgx_source.ProvenancePreservingTransformer()
    previous = (object(), {"old": "node"}, {"old": "edge"})
    transformer.inspector, transformer.node_filters, transformer.edge_filters = previous
    sinks = []
    real_sink = transformer.get_sink

    def tracked(**kwargs):
        """Retain the actual sink only to assert both file handles close on failure."""
        sink = real_sink(**kwargs)
        sinks.append(sink)
        return sink

    monkeypatch.setattr(transformer, "get_sink", tracked)
    with pytest.raises(ValueError):
        transformer._export_completed_graph(
            {"format": "graph", "graph": graph},
            {
                "format": "tsv",
                "filename": str(tmp_path / "bad"),
                "node_properties": {"deprecated"},
                "edge_properties": set(kgx_source.CANONICAL_EDGE_HEADER),
            },
        )
    assert all(sink.NFH.closed and sink.EFH.closed for sink in sinks)
    assert (transformer.inspector, transformer.node_filters, transformer.edge_filters) == previous


@pytest.mark.parametrize("node_only", [False, True])
def test_multiple_public_destinations_preserve_node_only_and_full_graphs(tmp_path, monkeypatch, node_only):
    """A completed graph can serve several destinations without acquiring or leaking export state."""
    config = configuration(tmp_path)
    content = yaml.safe_load(config.read_text())
    content["merged_graph"]["destination"]["second"] = {"format": "tsv", "filename": "second", "compression": "tar.gz"}
    config.write_text(yaml.safe_dump(content))
    if node_only:
        for path in (tmp_path / "input").glob("*_edges.tsv"):
            path.write_text(path.read_text().splitlines()[0] + "\n")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    direct_calls = []
    real = kgx_source.ProvenancePreservingTransformer._export_completed_graph

    def tracked(self, *args):
        """Count real direct exporters without replacing their processing."""
        direct_calls.append(args[0]["graph"])
        return real(self, *args)

    monkeypatch.setattr(kgx_source.ProvenancePreservingTransformer, "_export_completed_graph", tracked)
    graph = merge_kg.load_and_merge(str(config))
    assert direct_calls == [graph, graph]
    first, rows = archive_rows(tmp_path / "out/result.tar.gz")
    second, _ = archive_rows(tmp_path / "out/second.tar.gz")
    assert {name.replace("result", "second"): value for name, value in first.items()} == second
    assert len(rows["result_nodes.tsv"]) == 3
    assert len(rows["result_edges.tsv"]) == (0 if node_only else 4)
    assert kgx_source._DIRECT_EXPORT.get() is None


def test_unknown_version_real_public_export_uses_existing_path(tmp_path, monkeypatch):
    """An untested version cannot silently exercise the optimized implementation."""
    config = configuration(tmp_path)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(kgx_source, "version", lambda name: "2.7.99")

    def forbidden(*args, **kwargs):
        """Reject an accidental optimization of the untested version."""
        pytest.fail("unknown KGX version used direct export")

    monkeypatch.setattr(kgx_source.ProvenancePreservingTransformer, "_export_completed_graph", forbidden)
    graph = merge_kg.load_and_merge(str(config))
    _, rows = archive_rows(tmp_path / "out/result.tar.gz")
    assert graph.number_of_edges() == len(rows["result_edges.tsv"]) == 4


def test_arbitrary_preexisting_graph_retains_normalization_dedup(tmp_path, monkeypatch):
    """No earlier normal merge means no permission, even for a graph with canonical-looking metadata."""
    from kgx import transformer as transformer_module

    source = {"input": {"format": "tsv", "filename": [str(FIXTURE / "alpha_edges.tsv")]}}
    store = kgx_source.parse_source("fixture", source, str(tmp_path))
    add_normalized_duplicate(store.graph)
    assert store.graph.number_of_edges() == 3
    monkeypatch.setattr(transformer_module, "GraphSink", kgx_source.RelationAwareGraphSink)
    monkeypatch.setitem(transformer_module.SOURCE_MAP, "graph", kgx_source.RelationAwareGraphSource)
    monkeypatch.setitem(transformer_module.SINK_MAP, "tsv", kgx_source.RelationAwareTsvSink)
    exporter = kgx_source.ProvenancePreservingTransformer()
    exporter.transform(
        {"format": "graph", "graph": store.graph},
        {
            "format": "tsv",
            "filename": str(tmp_path / "arbitrary"),
            "node_properties": store.node_properties,
            "edge_properties": store.edge_properties,
        },
    )
    with (tmp_path / "arbitrary_edges.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert len(rows) == 2
