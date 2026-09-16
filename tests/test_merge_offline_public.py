"""The public prepared-source merge works in real spawned workers without remote context seeds."""

import hashlib
import ipaddress
import json
import multiprocessing
import os
import socket
import tarfile

import pytest
import requests
import yaml

from kg_microbe.merge_utils import merge_kg
from tests.test_merge_source_freshness import merge_config, prepare_source

pytestmark = pytest.mark.usefixtures("local_source_schema")


def _reject_http(*args, **kwargs):
    """Fail HTTP attempts without replacing KGX's real JSON-LD reader or supplying its context."""
    raise AssertionError("Public merge must not obtain its prefix context over HTTP")


def _block_worker_network():
    """Block external worker sockets and HTTP, leaving every KGX context cache untouched."""
    requests.sessions.Session.request = _reject_http
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect

    def allowed(host):
        """Permit only loopback addresses, or local Unix socket paths outside Internet tuples."""
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            return False

    def guarded_getaddrinfo(host, *args, **kwargs):
        """Reject remote DNS before a worker could attempt an external connection."""
        if not allowed(host):
            raise AssertionError(f"Worker external DNS forbidden: {host}")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        """Allow local multiprocessing sockets without allowing external destinations."""
        if isinstance(address, tuple) and not allowed(address[0]):
            raise AssertionError(f"Worker external socket forbidden: {address[0]}")
        return original_connect(sock, address)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.socket.connect = guarded_connect


@pytest.mark.parametrize("prior_context", [False, True])
@pytest.mark.parametrize("required_failure", [False, True])
def test_public_merge_real_spawn_uses_local_context_and_restores_caller_state(
    tmp_path, monkeypatch, prior_context, required_failure
):
    """Exercise real parsing/export after the production freshness gate, without prefix mocks."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx import config as kgx_config
    from kgx import prefix_manager
    from kgx.cli import cli_utils

    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["destination"]["tsv"]["compression"] = "tar.gz"
    config.write_text(yaml.safe_dump(payload))
    source_bytes = {path.name: path.read_bytes() for path in source.output_dir.iterdir()}
    config_bytes = config.read_bytes()
    published = tmp_path / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"prior complete archive")

    contexts = kgx_config.jsonld_context_map
    caller_context = {"biolink": "https://caller.invalid/", "caller": "urn:caller:"}
    unrelated_context = {"untouched": "urn:untouched:"}
    monkeypatch.setitem(contexts, "unrelated-public-test", unrelated_context)
    if prior_context:
        monkeypatch.setitem(contexts, "biolink", caller_context)
    else:
        monkeypatch.delitem(contexts, "biolink", raising=False)
    monkeypatch.setattr(requests.sessions.Session, "request", _reject_http)
    original_reader = prefix_manager.get_jsonld_context
    spawned_pids = []

    def real_spawn_pool(*args, **kwargs):
        """Use actual fresh processes; the initializer supplies only a network prohibition."""
        pool = multiprocessing.get_context("spawn").Pool(*args, initializer=_block_worker_network, **kwargs)
        spawned_pids.extend(worker.pid for worker in pool._pool)
        return pool

    monkeypatch.setattr(cli_utils, "Pool", real_spawn_pool)
    original_validation = merge_kg.write_merge_validation_report

    def inspect_staged_graph(nodes, edges, report):
        """Require real new KGX output while a prior archive remains unpublished-over."""
        assert "fixture:1" in nodes.read_text()
        assert "infores:test" in edges.read_text()
        assert published.read_bytes() == b"prior complete archive"
        if required_failure:
            raise OSError("injected required validation failure")
        return original_validation(nodes, edges, report)

    monkeypatch.setattr(merge_kg, "write_merge_validation_report", inspect_staged_graph)
    if required_failure:
        with pytest.raises(OSError, match="injected required validation failure"):
            merge_kg.load_and_merge(str(config), processes=1)
        assert published.read_bytes() == b"prior complete archive"
    else:
        graph = merge_kg.load_and_merge(str(config), processes=1)
        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        with tarfile.open(published) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            nodes = archive.extractfile("fixture_nodes.tsv").read()
            edges = archive.extractfile("fixture_edges.tsv").read()
        assert manifest["members"]["fixture_nodes.tsv"]["rows"] == 2
        assert manifest["members"]["fixture_edges.tsv"]["rows"] == 1
        assert manifest["members"]["fixture_edges.tsv"]["sha256"] == hashlib.sha256(edges).hexdigest()
        assert b"infores:test" in nodes and b"infores:test" in edges
        assert manifest["provenance"]["merge_config"]["sha256"] == hashlib.sha256(config_bytes).hexdigest()

    assert spawned_pids and all(pid != os.getpid() for pid in spawned_pids)
    assert source_bytes == {path.name: path.read_bytes() for path in source.output_dir.iterdir()}
    assert config.read_bytes() == config_bytes
    assert kgx_config.jsonld_context_map is contexts
    assert contexts["unrelated-public-test"] is unrelated_context
    if prior_context:
        assert contexts["biolink"] is caller_context
    else:
        assert "biolink" not in contexts
    assert prefix_manager.get_jsonld_context is original_reader
