"""Production merge parsers must derive their real prefix context from pinned local inputs."""

import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

from kg_microbe.merge_utils.kgx_source import parse_source

FIXTURES = Path(__file__).parent / "resources/relation_aware_merge"


@pytest.fixture(autouse=True)
def pinned_namespace_fixture(monkeypatch):
    """Keep tests immutable while exercising the real model's bundled default-map precedence."""
    schema = Path(__file__).parent / "resources/merge_offline_context/biolink-model.yaml"
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(schema))


def _source():
    """Use immutable finalized scalar/evidence fixture rows, without changing production inputs."""
    return {
        "input": {
            "format": "tsv",
            "filename": [str(FIXTURES / "alpha_final_nodes.tsv"), str(FIXTURES / "alpha_final_edges.tsv")],
        }
    }


def _reject_http(*args, **kwargs):
    """Reject network calls instead of supplying a fake successful JSON-LD context."""
    raise AssertionError("No HTTP permitted in the production prefix-context regression")


def _worker_http_guard():
    """Block worker HTTP without injecting a prefix-map cache or replacing its reader."""
    requests.sessions.Session.request = _reject_http


def test_real_parser_loads_nonempty_pinned_context_without_http(tmp_path, monkeypatch):
    """The actual unmocked KGX PrefixManager must not fetch its packaged Biolink 2.2.5 URL."""
    from kgx.config import jsonld_context_map

    monkeypatch.delitem(jsonld_context_map, "biolink", raising=False)
    monkeypatch.setattr(requests.sessions.Session, "request", _reject_http)
    store = parse_source("alpha", _source(), str(tmp_path))
    assert store.graph.number_of_edges() == 3
    assert store.prefix_manager.prefix_map["biolink"] == "https://w3id.org/biolink/vocab/"
    assert store.prefix_manager.prefix_map["GO"] == "http://purl.obolibrary.org/obo/GO_"
    assert store.prefix_manager.prefix_map["CHEBI"] == "http://purl.obolibrary.org/obo/CHEBI_"
    assert store.prefix_manager.prefix_map["NCBITaxon"] == "http://purl.obolibrary.org/obo/NCBITaxon_"
    assert "biolink" not in jsonld_context_map


def test_real_spawned_parser_needs_no_context_injection(tmp_path):
    """A fresh spawned worker initializes the pinned context through production code alone."""
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_worker_http_guard,
    ) as pool:
        store = pool.submit(parse_source, "alpha", _source(), str(tmp_path)).result(timeout=60)
    assert store.graph.number_of_edges() == 3
    assert store.prefix_manager.prefix_map["GO"] == "http://purl.obolibrary.org/obo/GO_"
    assert store.prefix_manager.prefix_map["biolink"] == "https://w3id.org/biolink/vocab/"


@pytest.mark.parametrize("fail_worker", [False, True])
def test_nested_thread_scope_restores_only_after_parent_finishes(monkeypatch, fail_worker):
    """A parent merge context cannot deadlock its thread workers or restore their cache too early."""
    from kgx.config import jsonld_context_map

    from kg_microbe.merge_utils.local_context import local_prefix_context

    previous = {"biolink": "https://previous-context.invalid/"}
    unrelated = {"unrelated": "https://unrelated.invalid/"}
    monkeypatch.setitem(jsonld_context_map, "biolink", previous)
    monkeypatch.setitem(jsonld_context_map, "unrelated-review-context", unrelated)
    monkeypatch.setattr(requests.sessions.Session, "request", _reject_http)

    def worker():
        """Enter the production nested context in a different thread, optionally unwinding with error."""
        with local_prefix_context():
            assert jsonld_context_map["biolink"]["GO"] == "http://purl.obolibrary.org/obo/GO_"
            if fail_worker:
                raise RuntimeError("fixture worker failed")

    with local_prefix_context():
        active = jsonld_context_map["biolink"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            if fail_worker:
                with pytest.raises(RuntimeError, match="fixture worker failed"):
                    future.result(timeout=10)
            else:
                future.result(timeout=10)
        assert jsonld_context_map["biolink"] is active
        assert active is not previous
        assert jsonld_context_map["unrelated-review-context"] is unrelated
    assert jsonld_context_map["biolink"] is previous
    assert jsonld_context_map["unrelated-review-context"] is unrelated


def test_conflicting_nested_context_does_not_modify_active_or_prior_cache(monkeypatch):
    """A different namespace selection fails without corrupting an already active merge scope."""
    from kgx.config import jsonld_context_map

    from kg_microbe.merge_utils import local_context

    previous = {"biolink": "https://previous-context.invalid/"}
    monkeypatch.setitem(jsonld_context_map, "biolink", previous)
    with local_context.local_prefix_context():
        active = jsonld_context_map["biolink"]
        conflicting = {**active, "biolink": "https://conflicting-context.invalid/"}
        monkeypatch.setattr(local_context, "_pinned_prefix_map", lambda: conflicting)
        with pytest.raises(ValueError, match="different pinned namespaces"):
            with local_context.local_prefix_context():
                pytest.fail("A conflicting context must not be entered")
        assert jsonld_context_map["biolink"] is active
    assert jsonld_context_map["biolink"] is previous


@pytest.mark.parametrize("entrypoint", ["parent", "worker"])
def test_missing_local_schema_fails_without_cache_or_adapter_mutation(tmp_path, monkeypatch, entrypoint):
    """Missing pinned inputs abort before KGX work, never fall back to a remote context."""
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils
    from kgx.config import jsonld_context_map

    from kg_microbe.merge_utils import kgx_source, merge_kg

    previous = {"biolink": "https://previous-context.invalid/"}
    monkeypatch.setitem(jsonld_context_map, "biolink", previous)
    monkeypatch.setattr(requests.sessions.Session, "request", _reject_http)
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(tmp_path / "missing-local-schema.yaml"))
    original_transformer = cli_utils.Transformer
    original_sources = dict(transformer_module.SOURCE_MAP)
    original_sinks = dict(transformer_module.SINK_MAP)

    def no_kgx(*args, **kwargs):
        """Fail if missing local authority reaches graph construction or publication."""
        pytest.fail("Missing local model must abort before KGX")

    monkeypatch.setattr(cli_utils, "merge", no_kgx)
    monkeypatch.setattr(kgx_source, "_kgx_parse_source", no_kgx)
    with pytest.raises(FileNotFoundError, match="Pinned Biolink"):
        if entrypoint == "parent":
            merge_kg.merge("unused.yaml")
        else:
            parse_source("alpha", _source(), str(tmp_path))
    assert jsonld_context_map["biolink"] is previous
    assert cli_utils.Transformer is original_transformer
    assert transformer_module.SOURCE_MAP == original_sources
    assert transformer_module.SINK_MAP == original_sinks
    assert not list(tmp_path.iterdir())
