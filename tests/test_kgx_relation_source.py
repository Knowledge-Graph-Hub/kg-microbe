"""Keep scalar relation assertions paired with their original evidence (#1054)."""

import csv
import io
import multiprocessing
import pickle
import tarfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.kgx_source import (
    RelationAwareGraphSink,
    RelationAwareGraphSource,
    canonical_relation,
    parse_source,
    relation_aware_key,
)

FIXTURES = Path(__file__).parent / "resources" / "relation_aware_merge"


@pytest.fixture(autouse=True)
def local_prefix_context(monkeypatch):
    """Do not let KGX's independent JSON-LD context reader fetch a remote URL."""
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})


def _source(name):
    """Use the immutable node and edge inputs for a source."""
    return {
        "input": {
            "format": "tsv",
            "filename": [str(FIXTURES / f"{name}_nodes.tsv"), str(FIXTURES / f"{name}_edges.tsv")],
        }
    }


def _values(value):
    """Compare KGX properties that may be scalar or multivalued after merging."""
    return set(value) if isinstance(value, (list, tuple, set)) else {value}


def _edges_by_relation(graph):
    """Verify keys include relation identity and collect each distinct assertion."""
    result = {}
    for subject, obj, key, edge in graph.edges(keys=True, data=True):
        relation = canonical_relation(edge["relation"])
        assert key == relation_aware_key(subject, edge["predicate"], obj, relation)
        assert relation not in result
        result[relation] = edge
    return result


def test_same_source_preserves_distinct_relations_and_unions_exact_repeat_evidence(tmp_path):
    """A repeated triple is not necessarily a repeated assertion."""
    store = parse_source("alpha", _source("alpha"), str(tmp_path))
    edges = _edges_by_relation(store.graph)
    assert set(edges) == {"RO:0000056", "RO:0000057"}
    assert _values(edges["RO:0000056"]["primary_knowledge_source"]) == {"infores:alpha-first", "infores:alpha-repeat"}
    assert _values(edges["RO:0000056"]["publications"]) == {"PMID:1", "PMID:2"}
    assert _values(edges["RO:0000057"]["primary_knowledge_source"]) == {"infores:alpha-other-relation"}
    assert _values(edges["RO:0000057"]["publications"]) == {"PMID:3"}
    assert all(isinstance(edge["relation"], str) for edge in edges.values())


def test_canonical_node_aliases_union_sources_and_normalize_imported_categories(tmp_path):
    """Compaction happens before identity matching, for both nodes and edge endpoints."""
    graph = parse_source("alpha", _source("alpha"), str(tmp_path)).graph
    assert set(graph.nodes(data=False)) == {"time:Instant", "FOODON:1"}
    assert _values(graph.nodes()["time:Instant"]["provided_by"]) == {"infores:iri", "infores:curie"}
    assert graph.nodes()["FOODON:1"]["category"] == ["biolink:Food"]
    assert all(subject == "time:Instant" and obj == "FOODON:1" for subject, obj in graph.edges(data=False))


def test_cross_source_merge_preserves_relation_specific_metadata(tmp_path, monkeypatch):
    """Exercise KGX merging and the graph-to-graph export boundary that formerly re-keyed triples."""
    from kgx import transformer as transformer_module
    from kgx.graph_operations.graph_merge import merge_all_graphs

    stores = [parse_source(name, _source(name), str(tmp_path)) for name in ("alpha", "beta")]
    graph = merge_all_graphs([store.graph for store in stores])
    # KGX exports via an intermediate GraphSink, which must retain the same
    # relation-aware identity rather than reverting to a triple-only key.
    monkeypatch.setattr(transformer_module, "GraphSink", RelationAwareGraphSink)
    monkeypatch.setitem(transformer_module.SOURCE_MAP, "graph", RelationAwareGraphSource)
    exporter = transformer_module.Transformer()
    exporter.transform({"format": "graph", "graph": graph})
    edges = _edges_by_relation(exporter.store.graph)
    assert set(edges) == {"RO:0000056", "RO:0000057", "RO:0000058"}
    assert _values(edges["RO:0000056"]["primary_knowledge_source"]) == {
        "infores:alpha-first",
        "infores:alpha-repeat",
        "infores:beta-same-relation",
    }
    assert _values(edges["RO:0000056"]["publications"]) == {"PMID:1", "PMID:2", "PMID:4"}
    assert _values(edges["RO:0000057"]["publications"]) == {"PMID:3"}
    assert _values(edges["RO:0000058"]["publications"]) == {"PMID:5"}
    assert _values(edges["RO:0000056"]["has_percentage"]) == {"0.1", "0.2", "0.4"}
    assert _values(edges["RO:0000057"]["has_percentage"]) == {"0.7"}
    assert _values(edges["RO:0000058"]["has_percentage"]) == {"0.8"}
    assert all(isinstance(edge["relation"], str) and "key" not in edge for edge in edges.values())


@pytest.mark.parametrize("pool_kind", ["thread", "spawn", "fork"])
def test_actual_merge_archive_preserves_source_relation_evidence_pairings(tmp_path, monkeypatch, pool_kind):
    """Test the public merge path, not only source and sink components in isolation."""
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    if pool_kind == "thread":
        pool_class = ThreadPool
    else:
        if pool_kind not in multiprocessing.get_all_start_methods():
            pytest.skip(f"{pool_kind} multiprocessing is unavailable")
        pool_class = partial(multiprocessing.get_context(pool_kind).Pool, initializer=_initialize_spawned_worker)
    monkeypatch.setattr(cli_utils, "Pool", pool_class)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": {name: _source(name) for name in ("alpha", "beta")},
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "merged"}},
                },
            }
        ),
        encoding="utf-8",
    )
    graph = merge(str(config), processes=2)
    assert graph.number_of_edges() == 3
    with tarfile.open(tmp_path / "merged.tar.gz") as archive:
        with archive.extractfile("merged_edges.tsv") as handle:
            edges = {row["relation"]: row for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t")}
        with archive.extractfile("merged_nodes.tsv") as handle:
            nodes = {row["id"]: row for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t")}
    assert set(edges) == {"RO:0000056", "RO:0000057", "RO:0000058"}
    assert set(edges["RO:0000056"]["primary_knowledge_source"].split("|")) == {
        "infores:alpha-first",
        "infores:alpha-repeat",
        "infores:beta-same-relation",
    }
    assert edges["RO:0000057"]["primary_knowledge_source"] == "infores:alpha-other-relation"
    assert edges["RO:0000058"]["primary_knowledge_source"] == "infores:beta-other-relation"
    assert set(edges["RO:0000056"]["publications"].split("|")) == {"PMID:1", "PMID:2", "PMID:4"}
    assert edges["RO:0000057"]["publications"] == "PMID:3"
    assert edges["RO:0000058"]["publications"] == "PMID:5"
    assert set(edges["RO:0000056"]["has_percentage"].split("|")) == {"0.1", "0.2", "0.4"}
    assert edges["RO:0000057"]["has_percentage"] == "0.7"
    assert edges["RO:0000058"]["has_percentage"] == "0.8"
    assert set(nodes["time:Instant"]["provided_by"].split("|")) == {"infores:iri", "infores:curie", "infores:beta"}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("RO:0000056|RO:0000056", "RO:0000056"),
        (["RO:0000056", "RO:0000056"], "RO:0000056"),
        ("RO:0000056|http://purl.obolibrary.org/obo/RO_0000056", "RO:0000056"),
        ("rdfs:subClassOf|http://www.w3.org/2000/01/rdf-schema#subClassOf", "rdfs:subClassOf"),
        ("", ""),
    ],
)
def test_only_exact_relation_repeats_or_registered_aliases_can_collapse(value, expected):
    """Registered aliases are not a license to choose among distinct relation assertions."""
    assert canonical_relation(value) == expected


def test_ambiguous_source_relation_fails_and_restores_worker_overrides(tmp_path):
    """Do not split a pre-merged relation pipe and clone combined evidence onto each part."""
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils

    original_sources = dict(transformer_module.SOURCE_MAP)
    original_tsv_sinks = dict(transformer_module.SINK_MAP)
    original_sink = transformer_module.GraphSink
    original_transformer = cli_utils.Transformer
    edges = tmp_path / "bad_edges.tsv"
    edges.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "time:Instant\tbiolink:related_to\tFOODON:1\tRO:0000056|RO:0000057\tinfores:unknown-pairing\n",
        encoding="utf-8",
    )
    source = {"input": {"format": "tsv", "filename": [str(edges)]}}
    with pytest.raises(ValueError, match="each retaining its own evidence and provenance"):
        parse_source("bad", source, str(tmp_path))
    assert transformer_module.SOURCE_MAP == original_sources
    assert transformer_module.SINK_MAP == original_tsv_sinks
    assert transformer_module.GraphSink is original_sink
    assert cli_utils.Transformer is original_transformer


def test_csv_uses_the_same_identity_adapter(tmp_path):
    """CSV is another route to TsvSource and cannot bypass the relation key."""
    files = []
    for kind in ("nodes", "edges"):
        target = tmp_path / f"alpha_{kind}.csv"
        with (FIXTURES / f"alpha_{kind}.tsv").open(newline="") as source, target.open("w", newline="") as output:
            csv.writer(output, lineterminator="\n").writerows(csv.reader(source, delimiter="\t"))
        files.append(str(target))
    graph = parse_source("alpha", {"input": {"format": "csv", "filename": files}}, str(tmp_path)).graph
    assert set(_edges_by_relation(graph)) == {"RO:0000056", "RO:0000057"}


def test_parser_is_pickleable_and_thread_overrides_restore(tmp_path):
    """Real worker dispatch can pickle it; overlapping thread fixtures cannot leak overrides."""
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils

    assert pickle.loads(pickle.dumps(parse_source)) is parse_source
    original_sources = dict(transformer_module.SOURCE_MAP)
    original_tsv_sinks = dict(transformer_module.SINK_MAP)
    original_sink = transformer_module.GraphSink
    original_transformer = cli_utils.Transformer
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(parse_source, name, _source(name), str(tmp_path)) for name in ("alpha", "beta")]
        assert [future.result().graph.number_of_edges() for future in futures] == [2, 2]
    assert transformer_module.SOURCE_MAP == original_sources
    assert transformer_module.SINK_MAP == original_tsv_sinks
    assert transformer_module.GraphSink is original_sink
    assert cli_utils.Transformer is original_transformer


def _reject_http(*args, **kwargs):
    """Keep the independent spawned interpreter hermetic as well as the pytest process."""
    raise AssertionError("No network permitted in the spawned source parser test")


def _initialize_spawned_worker():
    """Supply a local JSON-LD context and block HTTP in the fresh interpreter."""
    import requests
    from kgx.config import jsonld_context_map

    requests.sessions.Session.request = _reject_http
    jsonld_context_map["biolink"] = {}


def test_real_spawned_worker_installs_its_own_source_and_sink_adapters(tmp_path):
    """A parent-only monkeypatch would pass thread tests but fail macOS multiprocessing."""
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize_spawned_worker,
    ) as pool:
        graph = pool.submit(parse_source, "alpha", _source("alpha"), str(tmp_path)).result(timeout=60).graph
    edges = _edges_by_relation(graph)
    assert set(edges) == {"RO:0000056", "RO:0000057"}
    assert _values(edges["RO:0000056"]["publications"]) == {"PMID:1", "PMID:2"}
