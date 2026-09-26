"""Synthetic GTDB crosswalks must respect the canonical fan-in decisions (#1053)."""

import csv
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import GTDB, METATRAITS_GTDB
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.tsv_io import tsv_dict_writer

FIXTURES = Path(__file__).parent / "resources" / "metatraits_gtdb_mapping"


@pytest.fixture
def transform(tmp_path):
    """Construct only the post-processing stage, without live ontology resources."""
    instance = object.__new__(MetaTraitsGTDBTransform)
    Transform.__init__(instance, METATRAITS_GTDB, input_dir=tmp_path / "raw", output_dir=tmp_path)
    instance.edge_header += ["has_percentage", "value", "unit"]
    instance.knowledge_source = "infores:gtdb-metatraits"
    instance.accession_to_gtdb_species = {
        "sp000000001": "Current one",
        "sp000000002": "Current solo",
        "sp000000003": "Current missing",
        "sp000000005": "Current solo",
    }
    instance.accession_to_ncbi = {
        "sp000000001": "NCBITaxon:1",
        "sp000000002": "NCBITaxon:2",
        "sp000000003": "NCBITaxon:3",
        "sp000000004": "NCBITaxon:4",
        "sp000000005": "NCBITaxon:2",
    }
    shutil.copyfile(FIXTURES / "nodes.tsv", instance.output_node_file)
    with instance.output_edge_file.open("w", newline="") as handle:
        tsv_dict_writer(handle, fieldnames=instance.edge_header).writeheader()
    canonical_dir = tmp_path / GTDB
    canonical_dir.mkdir()
    shutil.copyfile(FIXTURES / "gtdb_edges.tsv", canonical_dir / "edges.tsv")
    return instance


def _read_edges(transform):
    with transform.output_edge_file.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_synthetic_mappings_copy_whole_release_fan_in_decisions(transform, capsys):
    """Outside taxa force broad_match; two aliases of one taxon do not force it."""
    transform._create_hierarchical_edges()
    edges = _read_edges(transform)
    mappings = {edge["subject"]: edge for edge in edges if edge["object"].startswith("NCBITaxon:")}
    assert len(edges) == 7  # Four current-species parents and three supported mappings.
    assert len(mappings) == 3
    shared = mappings["GTDB:s__Historical_sp000000001"]
    assert (shared["predicate"], shared["relation"]) == ("biolink:broad_match", "skos:broadMatch")
    for node_id in ("GTDB:s__Solo_sp000000002", "GTDB:s__Alias_sp000000005"):
        assert (mappings[node_id]["predicate"], mappings[node_id]["relation"]) == (
            "biolink:close_match",
            "skos:closeMatch",
        )
    assert not any(edge["predicate"] == "biolink:same_as" for edge in edges)
    assert "1 NCBI links skipped: no matching canonical GTDB mapping" in capsys.readouterr().out


def test_appended_hierarchy_and_mapping_edges_have_complete_provenance_and_lf(transform):
    """Post-processing must not bypass the seven-column edge contract again."""
    transform._create_hierarchical_edges()
    for edge in _read_edges(transform):
        assert None not in edge
        for column in transform.edge_header[:7]:
            assert edge[column], f"Missing {column} in {edge}"
        assert edge["primary_knowledge_source"] == "infores:gtdb-metatraits"
        expected_level = "knowledge_assertion" if edge["predicate"] == "biolink:subclass_of" else "prediction"
        assert edge["knowledge_level"] == expected_level
        assert edge["agent_type"] == "automated_agent"
    assert b"\r\n" not in transform.output_edge_file.read_bytes()


def test_missing_canonical_gtdb_output_aborts_before_appending(transform):
    """A missing upstream is not evidence for identity or an unpooled match."""
    (transform.output_base_dir / GTDB / "edges.tsv").unlink()
    with pytest.raises(FileNotFoundError, match="Run the gtdb transform"):
        transform._create_hierarchical_edges()
    assert _read_edges(transform) == []


@pytest.mark.parametrize(
    "rows",
    [
        [("biolink:same_as", "owl:sameAs")],
        [("biolink:broad_match", "skos:closeMatch")],
        [("biolink:broad_match", "skos:broadMatch"), ("biolink:close_match", "skos:closeMatch")],
    ],
)
def test_invalid_or_conflicting_upstream_mapping_is_not_silently_strengthened(transform, rows):
    """Reject inconsistent upstream decisions instead of depending on row order."""
    edge_file = transform.output_base_dir / GTDB / "edges.tsv"
    with edge_file.open("w", newline="") as handle:
        writer = tsv_dict_writer(handle, fieldnames=["subject", "predicate", "object", "relation"])
        writer.writeheader()
        for predicate, relation in rows:
            writer.writerow(
                {
                    "subject": "GTDB:s__Current_one",
                    "predicate": predicate,
                    "object": "NCBITaxon:1",
                    "relation": relation,
                }
            )
    with pytest.raises(ValueError, match="canonical GTDB mapping"):
        transform._create_hierarchical_edges()
    assert _read_edges(transform) == []


def test_canonical_gtdb_dependency_is_declared():
    """Upstream reruns must invalidate this output's freshness fingerprint."""
    assert {"ontologies", GTDB} <= set(MetaTraitsGTDBTransform.TRANSFORM_INPUTS)


def test_taxonomy_lookup_uses_selected_raw_root_not_default(monkeypatch):
    """Metadata and taxonomy must not combine selected and default GTDB releases."""
    import kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb as module

    roots = Path(__file__).parent / "resources" / "metatraits_gtdb_selected_root"
    monkeypatch.setattr(module, "RAW_DATA_DIR", roots / "default")
    instance = object.__new__(MetaTraitsGTDBTransform)
    instance.input_base_dir = roots / "selected"
    instance.accession_to_gtdb_species = {}
    instance._load_gtdb_taxonomy()
    assert instance.accession_to_gtdb_species == {
        "sp000000001": "Selected bacterium sp000000001",
        "sp000000002": "Selected archaeon sp000000002",
    }


def test_missing_selected_taxonomy_does_not_borrow_default_release(tmp_path, monkeypatch):
    """Absent selected taxonomy cannot silently substitute valid default-release files."""
    import kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb as module

    roots = Path(__file__).parent / "resources" / "metatraits_gtdb_selected_root"
    monkeypatch.setattr(module, "RAW_DATA_DIR", roots / "default")
    instance = object.__new__(MetaTraitsGTDBTransform)
    instance.input_base_dir = tmp_path
    instance.accession_to_gtdb_species = {}
    instance._load_gtdb_taxonomy()
    assert instance.accession_to_gtdb_species == {}
