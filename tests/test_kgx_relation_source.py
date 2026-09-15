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
    assertion_key,
    canonical_assertion,
    canonical_relation,
    merge_assertion_graphs,
    parse_source,
)

FIXTURES = Path(__file__).parent / "resources" / "relation_aware_merge"


@pytest.fixture(autouse=True)
def local_prefix_context(monkeypatch):
    """Do not let KGX's independent JSON-LD context reader fetch a remote URL."""
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})


def _source(name):
    """Use the immutable node and edge inputs for a source."""
    name = "alpha_final" if name == "alpha" else name
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
    """Verify observation identity and group observations by their scalar relation."""
    result = {}
    for subject, obj, key, edge in graph.edges(keys=True, data=True):
        relation = canonical_relation(edge["relation"])
        assert key == assertion_key(edge)
        assert subject == edge["subject"] and obj == edge["object"]
        result.setdefault(relation, []).append(edge)
    return result


def test_same_source_preserves_each_observation_and_its_evidence(tmp_path):
    """Neither a repeated triple nor a repeated relation implies identical evidence."""
    store = parse_source("alpha", _source("alpha"), str(tmp_path))
    edges = _edges_by_relation(store.graph)
    assert set(edges) == {"RO:0000056", "RO:0000057"}
    assert store.graph.number_of_edges() == 3
    assert {
        (edge["primary_knowledge_source"], tuple(edge["publications"]), edge["has_percentage"])
        for edge in edges["RO:0000056"]
    } == {
        ("infores:alpha-first", ("PMID:1",), "0.1"),
        ("infores:alpha-repeat", ("PMID:2",), "0.2"),
    }
    assert edges["RO:0000057"][0]["publications"] == ["PMID:3"]


@pytest.mark.parametrize("archive_round_trip", [False, True])
def test_all_prego_and_metatraits_observations_keep_their_original_evidence(tmp_path, monkeypatch, archive_round_trip):
    """All seven habitat rows and four temperatures survive, with no scalar/evidence reassignment."""
    source = {"input": {"format": "tsv", "filename": [str(FIXTURES / "scalar_edges.tsv")]}}
    if archive_round_trip:
        from kgx.cli import cli_utils

        from kg_microbe.merge_utils.merge_kg import merge

        monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
        config = tmp_path / "merge.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "configuration": {"output_directory": str(tmp_path)},
                    "merged_graph": {
                        "source": {"scalar": source},
                        "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "scalar"}},
                    },
                }
            ),
            encoding="utf-8",
        )
        merge(str(config), processes=1)
        with tarfile.open(tmp_path / "scalar.tar.gz") as archive:
            with archive.extractfile("scalar_edges.tsv") as handle:
                edges = list(csv.DictReader(io.TextIOWrapper(handle), delimiter="\t"))
    else:
        graph = parse_source("scalar", source, str(tmp_path)).graph
        edges = [edge for _, _, edge in graph.edges(data=True)]
    assert len(edges) == 11
    with (FIXTURES / "scalar_edges.tsv").open(newline="") as handle:
        expected = {assertion_key(row): canonical_assertion(row) for row in csv.DictReader(handle, delimiter="\t")}
    assert {assertion_key(row): canonical_assertion(row) for row in edges} == expected
    assert sum(row["subject"] == "BTO:0001481" for row in edges) == 7
    assert sum(row["subject"] == "NCBITaxon:165190" for row in edges) == 4


def test_assertion_identity_preserves_scalar_context_and_multivalued_evidence_pairing():
    """Different context or evidence changes identity; list order and transport keys do not."""
    original = {
        "subject": "NCBITaxon:1",
        "predicate": "biolink:has_phenotype",
        "object": "METPO:1",
        "primary_knowledge_source": "infores:test",
        "value": "33.9",
        "unit": "Celsius",
        "publications": ["PMID:1", "PMID:2"],
        "has_evidence": ["ECO:1", "ECO:2"],
    }
    key = assertion_key(original)
    assert (
        assertion_key(
            {**original, "id": "transport-id", "key": "transport-key", "publications": "PMID:2|PMID:1|PMID:1"}
        )
        == key
    )
    for column, value in (
        ("value", "38.1"),
        ("unit", "Kelvin"),
        ("publications", ["PMID:3"]),
        ("primary_knowledge_source", "infores:other"),
        ("has_evidence", ["ECO:3"]),
        ("prego_source", "a different channel"),
    ):
        assert assertion_key({**original, column: value}) != key
    assert assertion_key({k: v for k, v in original.items() if k != "unit"}) != key
    assert assertion_key({**original, "negated": "false"}) == assertion_key({**original, "negated": False})
    assert assertion_key({**original, "negated": "true"}) != assertion_key({**original, "negated": False})
    with pytest.raises(ValueError, match="Pooled scalar"):
        canonical_assertion({**original, "value": ["33.9", "38.1"]})
    with pytest.raises(ValueError, match="Pooled scalar"):
        canonical_assertion({**original, "negated": [False, True]})


def test_cross_source_exact_duplicates_only_and_archive_reingestion_is_idempotent(tmp_path, monkeypatch):
    """Retain same-provider conflicts, absent metadata, explicit IDs and pipe text through real KGX."""
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    sources = {
        name: {"input": {"format": "tsv", "filename": [str(FIXTURES / f"observations_{name}_edges.tsv")]}}
        for name in ("a", "b")
    }
    assert parse_source("a", sources["a"], str(tmp_path)).graph.number_of_edges() == 4
    config = tmp_path / "observations.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": sources,
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "observations"}},
                },
            }
        ),
        encoding="utf-8",
    )
    graph = merge(str(config), processes=2)
    assert graph.number_of_edges() == 7
    before = {key: canonical_assertion(edge) for _, _, key, edge in graph.edges(keys=True, data=True)}
    assert all(edge["context_note"] == "alpha|beta" for edge in before.values())
    assert sum("source_assertion_id" in edge for edge in before.values()) == 1
    with tarfile.open(tmp_path / "observations.tar.gz") as archive:
        payload = archive.extractfile("observations_edges.tsv").read()
    exported = tmp_path / "again_edges.tsv"
    exported.write_bytes(payload)
    again = parse_source("again", {"input": {"format": "tsv", "filename": [str(exported)]}}, str(tmp_path)).graph
    assert {key: canonical_assertion(edge) for _, _, key, edge in again.edges(keys=True, data=True)} == before


def test_finalized_node_aliases_union_sources_without_retyping_at_merge(tmp_path):
    """Source finalization precedes merge; merging only unions canonical declarations."""
    graph = parse_source("alpha", _source("alpha"), str(tmp_path)).graph
    assert set(graph.nodes(data=False)) == {"time:Instant", "FOODON:1"}
    assert _values(graph.nodes()["time:Instant"]["provided_by"]) == {"infores:iri", "infores:curie"}
    assert graph.nodes()["FOODON:1"]["category"] == ["biolink:Food"]
    assert all(subject == "time:Instant" and obj == "FOODON:1" for subject, obj in graph.edges(data=False))


def test_merge_rejects_unfinalized_iri_source(tmp_path):
    """A legacy source must be finalized explicitly, not silently fixed while loading KGX."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    source = {"input": {"format": "tsv", "filename": [str(FIXTURES / "alpha_nodes.tsv")]}}
    with pytest.raises(SourceFinalizationRequired, match="Noncanonical identifier"):
        parse_source("legacy", source, str(tmp_path))


def test_cross_source_merge_preserves_relation_specific_metadata(tmp_path, monkeypatch):
    """Exercise KGX merging and the graph-to-graph export boundary that formerly re-keyed triples."""
    from kgx import transformer as transformer_module

    stores = [parse_source(name, _source(name), str(tmp_path)) for name in ("alpha", "beta")]
    graph = merge_assertion_graphs([store.graph for store in stores])
    # KGX exports via an intermediate GraphSink, which must retain the same
    # relation-aware identity rather than reverting to a triple-only key.
    monkeypatch.setattr(transformer_module, "GraphSink", RelationAwareGraphSink)
    monkeypatch.setitem(transformer_module.SOURCE_MAP, "graph", RelationAwareGraphSource)
    exporter = transformer_module.Transformer()
    exporter.transform({"format": "graph", "graph": graph})
    edges = _edges_by_relation(exporter.store.graph)
    assert set(edges) == {"RO:0000056", "RO:0000057", "RO:0000058"}
    assert exporter.store.graph.number_of_edges() == 5
    assert {
        (edge["primary_knowledge_source"], tuple(edge["publications"]), edge["has_percentage"])
        for edge in edges["RO:0000056"]
    } == {
        ("infores:alpha-first", ("PMID:1",), "0.1"),
        ("infores:alpha-repeat", ("PMID:2",), "0.2"),
        ("infores:beta-same-relation", ("PMID:4",), "0.4"),
    }
    assert all(isinstance(edge["relation"], str) and "key" not in edge for group in edges.values() for edge in group)


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
    assert graph.number_of_edges() == 5
    with tarfile.open(tmp_path / "merged.tar.gz") as archive:
        with archive.extractfile("merged_edges.tsv") as handle:
            edges = list(csv.DictReader(io.TextIOWrapper(handle), delimiter="\t"))
        with archive.extractfile("merged_nodes.tsv") as handle:
            nodes = {row["id"]: row for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t")}
    assert len(edges) == 5
    assert {
        (row["primary_knowledge_source"], row["relation"], row["publications"], row["has_percentage"]) for row in edges
    } == {
        ("infores:alpha-first", "RO:0000056", "PMID:1", "0.1"),
        ("infores:alpha-repeat", "RO:0000056", "PMID:2", "0.2"),
        ("infores:alpha-other-relation", "RO:0000057", "PMID:3", "0.7"),
        ("infores:beta-same-relation", "RO:0000056", "PMID:4", "0.4"),
        ("infores:beta-other-relation", "RO:0000058", "PMID:5", "0.8"),
    }
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
        with (FIXTURES / f"alpha_final_{kind}.tsv").open(newline="") as source, target.open("w", newline="") as output:
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
        assert [future.result().graph.number_of_edges() for future in futures] == [3, 2]
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
    assert {tuple(edge["publications"]) for edge in edges["RO:0000056"]} == {("PMID:1",), ("PMID:2",)}
