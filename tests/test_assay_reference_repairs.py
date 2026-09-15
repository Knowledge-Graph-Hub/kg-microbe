"""Assay references use authoritative GO aspects and historical identity evidence (#1079)."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as bacdive_module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import go_authority as go_module
from kg_microbe.utils.go_authority import GoAuthority, GoReferenceError
from kg_microbe.utils.mapping_file_utils import (
    generate_assay_entity_edges,
    generate_assay_entity_nodes,
    load_assay_kit_mappings,
)

FIXTURES = Path(__file__).parent / "resources"


@pytest.fixture
def authority():
    """Load immutable real-aspect and deliberately synthetic replacement evidence."""
    statements = []
    for path in (FIXTURES / "go_authority/statements.tsv", FIXTURES / "assay_reference_repairs/go_processes.tsv"):
        with path.open(encoding="utf-8", newline="") as stream:
            statements.extend(
                tuple(row[key] or None for key in ("subject", "predicate", "object", "value"))
                for row in csv.DictReader(stream, delimiter="\t")
            )
    return GoAuthority.from_statements(statements, authority_path="fixture/go.db")


@pytest.fixture
def transform(tmp_path):
    """Use the actual transform headers without constructing unrelated download clients."""
    result = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(result, "bacdive", input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    result.edge_header += ["value", "unit", "publications", "original_object"]
    return result


def _one_target(identifier):
    """Build one narrowly controlled GO reference for negative and identity tests."""
    return {
        "api_kits": [{"kit_name": "Fixture", "wells": [{"name": "test", "type": ["enzyme"], "go_terms": [identifier]}]}]
    }


def _read_assays():
    """Read the immutable affected source-well slice."""
    return json.loads((FIXTURES / "assay_reference_repairs/assays.json").read_text())


def test_process_and_activity_relations_follow_authority(authority, transform):
    """Three process targets keep their IDs but no longer assert enzymatic molecular function."""
    rows = [
        dict(zip(transform.edge_header, row, strict=True))
        for row in generate_assay_entity_edges(_read_assays(), transform.edge_header, go_authority=authority)
    ]
    processes = {"GO:0006569", "GO:1904659", "GO:0019660"}
    assert sum(row["object"] in processes for row in rows) == 3
    for row in rows:
        expected = (
            "MICRO:0001215"
            if row["object"] in processes
            else ("MICRO:0000065" if row["object"].startswith("CHEBI:") else "MICRO:0001206")
        )
        assert row["predicate"] == row["relation"] == expected
        assert row["primary_knowledge_source"] == "infores:assay-metadata"
        assert row["knowledge_level"] == "knowledge_assertion"
        assert row["agent_type"] == "manual_agent"


def test_historical_activity_preserves_label_aspect_and_consider(authority, transform):
    """The two GGT wells retain historical identity rather than being silently remapped."""
    data = _read_assays()
    nodes = {
        row[0]: dict(zip(transform.node_header, row, strict=True))
        for row in generate_assay_entity_nodes(data, transform.node_header, go_authority=authority)
    }
    historical = nodes["GO:0003840"]
    assert historical["category"] == "biolink:MolecularActivity"
    assert historical["name"] == "obsolete gamma-glutamyltransferase activity"
    assert historical["deprecated"] == "true"
    assert "not identity replacements" in historical["description"]
    assert "GO:0036374" in historical["description"]
    assert historical["provided_by"] == "infores:go"
    assert "GO:0036374" not in nodes
    assert nodes["GO:0004096"]["category"] == "biolink:MolecularActivity"
    rows = [
        dict(zip(transform.edge_header, row, strict=True))
        for row in generate_assay_entity_edges(data, transform.edge_header, go_authority=authority)
    ]
    assert sum(row["object"] == "GO:0003840" and row["predicate"] == "MICRO:0001206" for row in rows) == 2


def test_exact_replacement_nodes_and_edges_share_canonical_identity(authority, transform):
    """Only an exact replacement changes identity, retaining the original edge target."""
    data = _one_target("GO:9999002")
    node_rows = generate_assay_entity_nodes(data, transform.node_header, go_authority=authority)
    edge_rows = generate_assay_entity_edges(data, transform.edge_header, go_authority=authority)
    node = dict(zip(transform.node_header, node_rows[0], strict=True))
    edge = dict(zip(transform.edge_header, edge_rows[0], strict=True))
    assert node["id"] == edge["object"] == "GO:0004096"
    assert node["deprecated"] == ""
    assert edge["original_object"] == "GO:9999002"
    with pytest.raises(ValueError, match="original_object"):
        generate_assay_entity_edges(data, transform.edge_header[:-1], go_authority=authority)


def test_authority_and_supported_aspect_are_required(authority, transform):
    """Missing authority, unknown GO IDs and unsupported cellular targets cannot be guessed."""
    with pytest.raises(ValueError, match="go_authority"):
        generate_assay_entity_edges(_one_target("GO:0004096"), transform.edge_header)
    with pytest.raises(GoReferenceError):
        generate_assay_entity_nodes(_one_target("GO:9999999"), transform.node_header, go_authority=authority)
    with pytest.raises(ValueError, match="Unsupported GO assay aspect"):
        generate_assay_entity_edges(_one_target("GO:0005575"), transform.edge_header, go_authority=authority)


def test_assay_preflight_failure_preserves_existing_outputs(authority, transform, monkeypatch):
    """The actual run fails on GO references before opening either prior output."""
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    for path in (transform.output_node_file, transform.output_edge_file):
        path.write_text("previous completed output\n")
    transform.ncbi_impl = object()
    transform.assay_kit_mappings = {"fixture": {}}
    transform.assay_raw_data = _one_target("GO:9999999")
    monkeypatch.setattr(bacdive_module, "resolve_adapter", lambda adapter: None)
    monkeypatch.setattr(go_module, "load_go_authority", lambda raw: authority)
    with pytest.raises(GoReferenceError):
        transform.run()
    assert transform.output_node_file.read_text() == "previous completed output\n"
    assert transform.output_edge_file.read_text() == "previous completed output\n"


def test_assay_source_and_go_authority_use_the_same_selected_raw_root(authority, transform, monkeypatch):
    """A custom input root must not combine its GO snapshot with the default assay snapshot."""
    transform.input_base_dir.mkdir(parents=True)
    selected = transform.input_base_dir / "assay_kits_simple.json"
    selected.write_text((FIXTURES / "assay_reference_repairs/assays.json").read_text())
    transform.assay_kit_mappings = load_assay_kit_mappings(selected)
    transform.assay_raw_data = None
    seen = []

    def selected_authority(raw_root):
        """Record exactly which raw root supplies ontology authority."""
        seen.append(raw_root)
        return authority

    # A nonexistent default path with the same basename must never be opened.
    monkeypatch.setattr(bacdive_module, "ASSAY_KITS_FILE", selected.parent / "wrong-root" / selected.name)
    monkeypatch.setattr(go_module, "load_go_authority", selected_authority)
    transform._prepare_assay_outputs()
    assert seen == [transform.input_base_dir]
    assert "API 20E" in transform.assay_kit_mappings
    rows = [dict(zip(transform.edge_header, row, strict=True)) for row in transform.assay_edges_generated]
    assert any(row["object"] == "GO:0006569" and row["predicate"] == "MICRO:0001215" for row in rows)


def test_selected_assay_file_does_not_fall_back_to_default(transform, monkeypatch):
    """An absent selected source is explicit even if another snapshot exists at the default path."""
    from kg_microbe.transform_utils import constants

    monkeypatch.setattr(constants, "ASSAY_KITS_FILE", FIXTURES / "assay_reference_repairs/assays.json")
    with pytest.raises(FileNotFoundError):
        load_assay_kit_mappings(transform.input_base_dir / "assay_kits_simple.json")
