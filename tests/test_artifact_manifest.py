"""Portable, byte-accurate graph manifests for compressed and loose outputs (#1075)."""

import hashlib
import io
import json
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.artifact_manifest import MANIFEST_MEMBER, write_graph_archive, write_loose_manifest


def _pair(tmp_path):
    """Create immutable-in-test TSV payloads, including an unterminated final record."""
    nodes = tmp_path / "merged-kg_nodes.tsv"
    edges = tmp_path / "merged-kg_edges.tsv"
    nodes.write_bytes(b"id\tcategory\tname\nNCBITaxon:1\tbiolink:OrganismTaxon\tone\n")
    edges.write_bytes(b"subject\tpredicate\tobject\nNCBITaxon:1\tbiolink:related_to\tNCBITaxon:1")
    return nodes, edges


def test_relocated_archive_validates_without_loose_files_or_root_stats(tmp_path):
    """All member locators, hashes and counts resolve using only the moved archive."""
    files = _pair(tmp_path)
    archive = tmp_path / "merged-kg.tar.gz"
    write_graph_archive(archive, files, {"commit": "fixture"})
    for path in files:
        path.unlink()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    moved = archive.rename(snapshot / "renamed.tar.gz")
    with tarfile.open(moved) as tar:
        manifest = json.load(tar.extractfile(MANIFEST_MEMBER))
        assert set(tar.getnames()) == {MANIFEST_MEMBER, *(path.name for path in files)}
        assert manifest["provenance"] == {"commit": "fixture"}
        for name, expected in manifest["members"].items():
            payload = tar.extractfile(name).read()
            assert expected == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "rows": 1}


def test_failed_archive_replacement_retains_previous_file(tmp_path, monkeypatch):
    """A late error never replaces a good artifact with a partial tarball."""
    files = _pair(tmp_path)
    archive = tmp_path / "merged-kg.tar.gz"
    write_graph_archive(archive, files)
    previous = archive.read_bytes()
    real_add = tarfile.TarFile.addfile

    def fail_on_manifest(tar, info, fileobj=None):
        """Fail after graph members were written, before atomic publication."""
        if info.name == MANIFEST_MEMBER:
            raise OSError("simulated manifest failure")
        return real_add(tar, info, fileobj)

    monkeypatch.setattr(tarfile.TarFile, "addfile", fail_on_manifest)
    with pytest.raises(OSError, match="simulated"):
        write_graph_archive(archive, files)
    assert archive.read_bytes() == previous
    assert not list(tmp_path.glob("*.partial"))


def test_loose_manifest_has_same_identity_as_archive(tmp_path):
    """Uncompressed consumers receive equivalent member hashes and row counts."""
    files = _pair(tmp_path)
    manifest_path = tmp_path / "merged-kg_manifest.json"
    write_loose_manifest(manifest_path, files)
    archive = tmp_path / "merged-kg.tar.gz"
    write_graph_archive(archive, files)
    with tarfile.open(archive) as tar:
        assert json.loads(manifest_path.read_text()) == json.load(tar.extractfile(MANIFEST_MEMBER))


@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_cleanup_bundles_manifest_without_external_stats(tmp_path, monkeypatch, compression):
    """Real cleanup hooks work for both output modes and legacy two-member archives."""
    from kg_microbe.merge_utils import merge_kg

    files = _pair(tmp_path)
    archive = tmp_path / "merged-kg.tar.gz"
    if compression:
        with tarfile.open(archive, "w:gz") as tar:
            for path in files:
                tar.add(path, arcname=path.name)
        for path in files:
            path.unlink()
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "destination": {
                        "tsv": {
                            "format": "tsv",
                            "filename": "merged-kg",
                            "compression": compression,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    merge_kg._cleanup_merged_outputs(str(config))
    if compression:
        with tarfile.open(archive) as tar:
            result = json.load(tar.extractfile(MANIFEST_MEMBER))
        assert not any(path.exists() for path in files)
        assert not (tmp_path / MANIFEST_MEMBER).exists()
    else:
        result = json.loads((tmp_path / "merged-kg_manifest.json").read_text())
        assert all(path.exists() for path in files)
    assert all(result["members"][path.name]["rows"] == 1 for path in files)
    assert result["members"]["merged-kg_reference_resolution.tsv"]["rows"] == 1
    assert result["provenance"]["merge_config"] == {
        "name": config.name,
        "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    }
    assert result["provenance"]["repository_schema"] is None


@pytest.mark.parametrize(
    "stage", ["write_merge_validation_report", "build_provenance", "write_graph_archive", "write_loose_manifest"]
)
def test_merge_does_not_report_success_when_required_publication_fails(tmp_path, monkeypatch, stage):
    """Exercise the public merge boundary, not just helper-level atomic replacement."""
    from kg_microbe.merge_utils import merge_kg

    _pair(tmp_path)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "destination": {
                        "tsv": {
                            "format": "tsv",
                            "filename": "merged-kg",
                            "compression": None if stage == "write_loose_manifest" else "tar.gz",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fail(*args, **kwargs):
        """Simulate a required publication failure after graph generation."""
        raise OSError("publication failed")

    def emit_staged_pair(config_file, **kwargs):
        """Model KGX writing only to the temporary configured destination."""
        del kwargs
        staged = Path(merge_kg.parse_load_config(config_file)["configuration"]["output_directory"])
        _pair(staged)

    monkeypatch.setattr(merge_kg, "merge", emit_staged_pair)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(merge_kg, stage, fail)
    with pytest.raises(OSError, match="publication failed"):
        merge_kg.load_and_merge(str(config))


@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_source_reconciliation_precedes_merge_diagnostics_and_manifest(tmp_path, monkeypatch, compression):
    """Repairs happen in explicit source finalization, never implicitly inside merge."""
    from types import SimpleNamespace

    from kg_microbe.merge_utils import merge_kg
    from kg_microbe.utils.source_finalization import finalize_source

    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        for name, payload in {
            "nodes.dmp": b"1\t|\t1\t|\tno rank\t|\n2\t|\t1\t|\tsuperkingdom\t|\n3\t|\t2\t|\tspecies\t|\n",
            "names.dmp": b"3\t|\tFixture bacterium\t|\t\t|\tscientific name\t|\n",
            "merged.dmp": b"33\t|\t3\t|\n",
        }.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    nodes, edges = _pair(tmp_path)
    nodes.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "NCBITaxon:2\tbiolink:OrganismTaxon\tBacteria\tinfores:ncbitaxon\n"
        "NCBITaxon:3\tbiolink:OrganismTaxon\tFixture bacterium\tinfores:ncbitaxon\n"
        "NCBITaxon:33\tbiolink:NamedThing\t\t\n"
    )
    edges.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "NCBITaxon:33\tbiolink:related_to\tNCBITaxon:2\tro:fixture\tinfores:test\n"
    )
    finalize_source(
        SimpleNamespace(output_dir=tmp_path, output_base_dir=tmp_path.parent, input_base_dir=raw, source_name="fixture")
    )
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "destination": {
                        "tsv": {
                            "format": "tsv",
                            "filename": "merged-kg",
                            "compression": compression,
                        }
                    }
                },
            }
        )
    )
    observed = []

    def inspect_reconciled(edges_file, output_dir, nodes_file):
        """Assert the optional checks run after source-aware normalization."""
        payload = edges_file.read_text()
        assert "NCBITaxon:3\tbiolink:related_to" in payload
        assert "original_subject" in payload and "NCBITaxon:33" in payload
        assert "NCBITaxon:33" not in nodes_file.read_text()
        observed.append(True)

    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(merge_kg, "check_merged_invariants", inspect_reconciled)
    merge_kg._cleanup_merged_outputs(str(config))
    assert observed == [True]
    report = tmp_path / "merged-kg_reference_resolution.tsv"
    assert "no_semantic_rewrites" in report.read_text()
    assert "retired_id_replaced" in (tmp_path / "source_reference_resolution.tsv").read_text()
    if compression:
        with tarfile.open(tmp_path / "merged-kg.tar.gz") as archive:
            manifest = json.load(archive.extractfile(MANIFEST_MEMBER))
            payload = archive.extractfile(edges.name).read()
            report_payload = archive.extractfile(report.name).read()
    else:
        manifest = json.loads((tmp_path / "merged-kg_manifest.json").read_text())
        payload = edges.read_bytes()
        report_payload = report.read_bytes()
    assert b"NCBITaxon:3\tbiolink:related_to" in payload
    assert manifest["members"][edges.name]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["members"][nodes.name]["rows"] == 2
    assert b"no_semantic_rewrites" in report_payload
    assert manifest["members"][report.name]["sha256"] == hashlib.sha256(report_payload).hexdigest()


@pytest.mark.parametrize("failure_stage", ["closure", "stats", None])
@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_public_merge_stages_real_kgx_before_publishing(tmp_path, monkeypatch, failure_stage, compression):
    """Actual KGX cannot replace the previous release or stats before required cleanup succeeds."""
    from kg_microbe.merge_utils import merge_kg
    from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {"@context": {}})
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    config_dir = tmp_path / "configured"
    inputs = config_dir / "input"
    inputs.mkdir(parents=True)
    (inputs / "nodes.tsv").write_text(
        "id\tcategory\tname\tprovided_by\nNCBITaxon:1\tbiolink:OrganismTaxon\tnew root\tinfores:fixture\n"
    )
    (inputs / "edges.tsv").write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\n"
        "NCBITaxon:1\tbiolink:related_to\tNCBITaxon:1\tro:fixture\tinfores:fixture\tknowledge_assertion\tmanual_agent\n"
    )
    from types import SimpleNamespace

    from kg_microbe.utils.source_finalization import finalize_source

    finalize_source(
        SimpleNamespace(output_dir=inputs, output_base_dir=config_dir, input_base_dir=tmp_path, source_name="fixture")
    )
    output = config_dir / "published"
    output.mkdir()
    final_graph = output / ("merged-kg.tar.gz" if compression else "merged-kg_nodes.tsv")
    final_graph.write_bytes(b"prior published release")
    stats = tmp_path / "existing_stats.yaml"
    stats.write_bytes(b"prior published stats")
    config = config_dir / "original-config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                # This test isolates actual KGX publication with an unregistered
                # fixture producer; production freshness has separate coverage.
                "configuration": {"output_directory": "published", "allow_unfinalized_sources": True},
                "merged_graph": {
                    "source": {
                        "fixture": {"input": {"format": "tsv", "filename": ["input/nodes.tsv", "input/edges.tsv"]}}
                    },
                    "operations": [
                        {"name": STATS_OPERATION, "args": {"filename": str(stats), "graph_name": "fixture"}}
                    ],
                    "destination": {"tsv": {"format": "tsv", "filename": "merged-kg", "compression": compression}},
                },
            }
        )
    )
    config_bytes = config.read_bytes()
    real_closure = merge_kg.write_merge_validation_report

    def checked_closure(nodes, edges, report):
        """Observe actual new KGX bytes in staging while the existing release remains untouched."""
        assert nodes.parent != output
        assert "new root" in nodes.read_text()
        assert final_graph.read_bytes() == b"prior published release"
        assert stats.read_bytes() == b"prior published stats"
        if failure_stage == "closure":
            raise OSError("injected required closure failure")
        return real_closure(nodes, edges, report)

    monkeypatch.setattr(merge_kg, "write_merge_validation_report", checked_closure)
    if failure_stage == "stats":

        def fail_recount(*args, **kwargs):
            """Fail optional recount without publishing old facets or blocking the valid graph."""
            raise OSError("injected optional stats failure")

        monkeypatch.setattr(merge_kg, "annotate_graph_stats", fail_recount)
    if failure_stage == "closure":
        with pytest.raises(OSError, match="injected required closure failure"):
            merge_kg.load_and_merge(str(config))
        assert final_graph.read_bytes() == b"prior published release"
        assert stats.read_bytes() == b"prior published stats"
    else:
        merge_kg.load_and_merge(str(config))
        assert final_graph.read_bytes() != b"prior published release"
        if compression:
            with tarfile.open(final_graph) as archive:
                manifest = json.load(archive.extractfile(MANIFEST_MEMBER))
                assert b"new root" in archive.extractfile("merged-kg_nodes.tsv").read()
        else:
            manifest = json.loads((output / "merged-kg_manifest.json").read_text())
        assert manifest["provenance"]["merge_config"] == {
            "name": config.name,
            "sha256": hashlib.sha256(config_bytes).hexdigest(),
        }
        if failure_stage == "stats":
            assert stats.read_bytes() == b"prior published stats"
        else:
            updated_stats = yaml.safe_load(stats.read_text())
            assert updated_stats["provenance"]["merge_config"] == str(config)
            if compression:
                assert updated_stats["provenance"]["edges_archive"] == str(final_graph)
            else:
                assert updated_stats["provenance"]["edges_file"] == str(output / "merged-kg_edges.tsv")
        assert ".merge-" not in stats.read_text()
    assert config.read_bytes() == config_bytes
    assert not list(config_dir.glob(".published.merge-*"))


def test_staged_config_preserves_kgx_cwd_precedence_and_relative_stats(tmp_path, monkeypatch):
    """Resolve existing cwd sources before config-local candidates, but never relocate stats' final target."""
    from kg_microbe.merge_utils import merge_kg
    from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION

    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "same.tsv").write_text("cwd input")
    (config_dir / "same.tsv").write_text("config input")
    config = config_dir / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": "out"},
                "merged_graph": {
                    "source": {"a": {"input": {"filename": ["same.tsv"], "format": "tsv"}}},
                    "operations": [{"name": STATS_OPERATION, "args": {"filename": "stats.yaml"}}],
                },
            }
        )
    )
    before = config.read_bytes()
    with merge_kg._staged_merge_configuration(str(config)) as (staged, _output, final, stats):
        temporary = merge_kg.parse_load_config(str(staged))
        assert temporary["merged_graph"]["source"]["a"]["input"]["filename"] == [str(tmp_path / "same.tsv")]
        assert final == config_dir / "out"
        assert set(stats) == {tmp_path / "stats.yaml"}
        assert temporary["merged_graph"]["operations"][0]["args"]["filename"] != "stats.yaml"
    assert config.read_bytes() == before
