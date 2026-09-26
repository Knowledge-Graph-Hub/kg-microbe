"""Canonical first-write serialization and one-time release packaging."""

import csv
import hashlib
import io
import json
import tarfile
from multiprocessing.pool import ThreadPool

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.artifact_manifest import MANIFEST_MEMBER
from kg_microbe.merge_utils.kgx_source import RelationAwareTsvSink


@pytest.fixture(autouse=True)
def offline_kgx(monkeypatch):
    """Keep tiny actual KGX merges hermetic and in-process."""
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {"@context": {}})


def _configuration(tmp_path, compression):
    """Write two independent observations with literal extension text."""
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "nodes.tsv").write_text(
        "id\tcategory\tname\tdescription\tprovided_by\tcustom_node\tscalar_node\n"
        'NCBITaxon:1\tbiolink:OrganismTaxon\troot\t\tinfores:fixture\t"literal"\\"node\\"\tbeta|alpha\n'
        "fixture:stub\tbiolink:NamedThing\t\t\t\t\t\n"
    )
    (inputs / "edges.tsv").write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type"
        "\tpublications\tsource_assertion_id\tz_extension\ta_extension\n"
        "NCBITaxon:1\tbiolink:related_to\tNCBITaxon:1\tRO:0000056\tinfores:fixture\tknowledge_assertion"
        '\tmanual_agent\tPMID:1\tsource:1\t"literal"\\"quoted\\"\talpha|beta\n'
        "NCBITaxon:1\tbiolink:related_to\tNCBITaxon:1\tRO:0000057\tinfores:fixture\tknowledge_assertion"
        '\tmanual_agent\tPMID:2\tsource:2\t"literal"\\"quoted\\"\talpha|beta\n'
    )
    output = tmp_path / "published"
    output.mkdir()
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(output), "allow_unfinalized_sources": True},
                "merged_graph": {
                    "source": {
                        "fixture": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(inputs / "nodes.tsv"), str(inputs / "edges.tsv")],
                            }
                        }
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "merged-kg", "compression": compression}},
                },
            }
        )
    )
    return config, output


@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_actual_kgx_is_canonical_without_cleanup_rewrites(tmp_path, monkeypatch, compression):
    """Literal text, extensions, and evidence survive first write; archive is built once."""
    config, output = _configuration(tmp_path, compression)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    original = config.read_bytes()
    writes = []
    real_open = tarfile.open

    def tracked_open(*args, **kwargs):
        """Count graph archive writes rather than read-only manifest inspection."""
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        if mode.startswith("w"):
            writes.append(mode)
        return real_open(*args, **kwargs)

    def forbidden_rewrite(*args, **kwargs):
        """No normalizer is allowed after the canonical serializer."""
        pytest.fail("post-merge TSV rewriting was invoked")

    monkeypatch.setattr(tarfile, "open", tracked_open)
    monkeypatch.setattr(merge_kg, "_normalize_nodes_tsv", forbidden_rewrite)
    monkeypatch.setattr(merge_kg, "_normalize_edges_tsv", forbidden_rewrite)
    merge_kg.load_and_merge(str(config))
    assert config.read_bytes() == original
    if compression:
        assert writes == ["w:gz"]
        with real_open(output / "merged-kg.tar.gz") as archive:
            payloads = {name: archive.extractfile(name).read() for name in archive.getnames()}
        manifest = json.loads(payloads.pop(MANIFEST_MEMBER))
        assert not (output / "merged-kg_nodes.tsv").exists()
        assert not (output / "merged-kg_edges.tsv").exists()
    else:
        assert writes == []
        manifest = json.loads((output / "merged-kg_manifest.json").read_text())
        payloads = {name: (output / name).read_bytes() for name in manifest["members"]}
    nodes = payloads["merged-kg_nodes.tsv"]
    edges = payloads["merged-kg_edges.tsv"]
    assert b"\r" not in nodes + edges
    assert b'"literal"\\"node\\"' in nodes
    node_rows = {
        row["id"]: row for row in csv.DictReader(io.StringIO(nodes.decode()), delimiter="\t", quoting=csv.QUOTE_NONE)
    }
    assert node_rows["NCBITaxon:1"]["scalar_node"] == "beta|alpha"
    assert node_rows["fixture:stub"]["provided_by"] == ""
    rows = list(csv.DictReader(io.StringIO(edges.decode()), delimiter="\t", quoting=csv.QUOTE_NONE))
    header = edges.decode().splitlines()[0].split("\t")
    assert header[:7] == [
        "subject",
        "predicate",
        "object",
        "relation",
        "primary_knowledge_source",
        "knowledge_level",
        "agent_type",
    ]
    assert header[7:] == sorted(header[7:])
    assert not {"id", "key", "knowledge_source"}.intersection(header)
    assert {(row["relation"], row["publications"], row["source_assertion_id"]) for row in rows} == {
        ("RO:0000056", "PMID:1", "source:1"),
        ("RO:0000057", "PMID:2", "source:2"),
    }
    assert all(row["z_extension"] == '"literal"\\"quoted\\"' and row["a_extension"] == "alpha|beta" for row in rows)
    for name, entry in manifest["members"].items():
        assert entry["sha256"] == hashlib.sha256(payloads[name]).hexdigest()
        assert entry["bytes"] == len(payloads[name])


@pytest.mark.parametrize("failure", ["serializer", "validation", "manifest"])
def test_required_failure_preserves_last_public_archive(tmp_path, monkeypatch, failure):
    """Faults after ingestion cannot publish a partial or unvalidated replacement."""
    config, output = _configuration(tmp_path, "tar.gz")
    previous = output / "merged-kg.tar.gz"
    previous.write_bytes(b"last good archive")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)

    def fail(*args, **kwargs):
        """Inject a required-stage fault."""
        raise OSError("injected required failure")

    if failure == "serializer":
        monkeypatch.setattr(RelationAwareTsvSink, "write_edge", fail)
    elif failure == "validation":
        monkeypatch.setattr(merge_kg, "write_merge_validation_report", fail)
    else:
        monkeypatch.setattr(merge_kg, "build_provenance", fail)
    with pytest.raises(OSError, match="injected required failure"):
        merge_kg.load_and_merge(str(config))
    assert previous.read_bytes() == b"last good archive"
    assert not list(tmp_path.glob(".published.merge-*"))


@pytest.mark.parametrize("bad_text", ["embedded\tcolumn", "embedded\nrow", "embedded\rcarriage"])
def test_serializer_refuses_controls_instead_of_editing_text(tmp_path, bad_text):
    """The writer is transport only, never a silent content normalizer."""
    sink = RelationAwareTsvSink(None, str(tmp_path / "graph"), "tsv", node_properties=["id", "name"])
    try:
        with pytest.raises(ValueError, match="control"):
            sink.write_node({"id": "NCBITaxon:1", "name": bad_text})
    finally:
        sink.finalize()
