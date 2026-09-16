"""Independent source-bundle closure preserves same-ID authoritative declarations (#1087)."""

import csv
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    graph_rows,
    validate_graph_bundle,
    verify_finalized_source_files,
)

FIXTURES = Path(__file__).parent / "resources" / "source_finalization_review"


@pytest.mark.parametrize("split_files", [False, True])
def test_named_and_anonymous_same_id_keep_authoritative_declaration(tmp_path, split_files):
    """A same-ID anonymous donor cannot remove the named node, within or across source files."""
    raw = tmp_path / "raw"
    raw.mkdir()
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        for name in ("nodes.dmp", "names.dmp", "merged.dmp"):
            archive.add(FIXTURES / name, arcname=name)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    node_paths = [transform.output_node_file]
    shutil.copyfile(FIXTURES / "named_nodes.tsv", node_paths[0])
    if split_files:
        donor_path = transform.output_dir / "donor_nodes.tsv"
        shutil.copyfile(FIXTURES / "anonymous_nodes.tsv", donor_path)
        node_paths.append(donor_path)
    else:
        with node_paths[0].open("a", encoding="utf-8") as stream:
            stream.write((FIXTURES / "anonymous_nodes.tsv").read_text().split("\n", 1)[1])
    shutil.copyfile(FIXTURES / "edges.tsv", transform.output_edge_file)

    transform.finalize(fresh_run=True)
    verify_finalized_source_files([*node_paths, transform.output_edge_file])
    actual = [row for path in node_paths for row in graph_rows(path) if row["id"] == "NCBITaxon:12"]
    assert len(actual) == 1
    assert actual[0]["name"] == "Named canonical declaration"
    assert actual[0]["category"] == "biolink:OrganismTaxon"
    assert set(actual[0]["provided_by"].split("|")) == {"infores:source", "infores:donor", "infores:ncbitaxon"}
    assert "Canonical declaration context." in actual[0]["description"]
    assert "Anonymous donor context." in actual[0]["description"]
    validate_graph_bundle(node_paths, [transform.output_edge_file], require_closure=True)
    assert len(list(graph_rows(transform.output_edge_file))) == 1
    report = list(graph_rows(transform.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    donors = [json.loads(row["original_node_json"]) for row in report if row["original_node_json"]]
    assert any(row["name"] == "" and row["provided_by"] == "infores:donor" for row in donors)


@pytest.mark.parametrize(
    "audit_name",
    ["source_canonicalization.tsv", "go_reference_resolution.tsv", "source_reference_resolution.tsv"],
)
@pytest.mark.parametrize("change", ["missing", "changed"])
def test_audit_integrity_is_required_for_preflight_and_repeat(tmp_path, audit_name, change):
    """A missing or modified disposition report invalidates lossless source preparation."""
    raw = tmp_path / "raw"
    raw.mkdir()
    transform = Transform("fixture", raw, tmp_path / "transformed")
    shutil.copyfile(FIXTURES / "pato_nodes.tsv", transform.output_node_file)
    shutil.copyfile(FIXTURES / "pato_edges.tsv", transform.output_edge_file)
    transform.finalize(fresh_run=True)
    graph_paths = [transform.output_node_file, transform.output_edge_file]
    verify_finalized_source_files(graph_paths)
    before_graph = tuple(path.read_bytes() for path in graph_paths)
    original_audit = transform.output_dir / "source_canonicalization.tsv"
    assert "biolink:OntologyClass" in original_audit.read_text()
    audit = transform.output_dir / audit_name
    if change == "missing":
        audit.unlink()
    else:
        with audit.open("a", encoding="utf-8") as stream:
            stream.write("corrupted audit evidence\n")
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(graph_paths)
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize()
    assert tuple(path.read_bytes() for path in graph_paths) == before_graph
    assert not audit.exists() if change == "missing" else "corrupted audit evidence" in audit.read_text()
