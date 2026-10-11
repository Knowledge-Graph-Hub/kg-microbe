"""Synthetic GTDB crosswalks must respect the canonical fan-in decisions (#1053)."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import GTDB, METATRAITS_GTDB
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import (
    HISTORICAL_BRIDGE_AUDIT,
    MetaTraitsGTDBTransform,
    _register_numeric_candidate,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import optional_consumed_inputs
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_dict_writer

FIXTURES = Path(__file__).parent / "resources" / "metatraits_gtdb_mapping"


@pytest.fixture
def transform(tmp_path, monkeypatch):
    """Construct only the post-processing stage, without live ontology resources."""
    # MetaTraits resolves its optional ec2go table against the repository root,
    # not this fixture's raw directory. Pin it to an absent fixture path so a
    # local run never binds the developer's data/raw copy (CI has none).
    real_paths = optional_consumed_inputs.optional_input_paths

    def fixture_paths(producer, *, input_dir=None):
        """Keep every other declared role; relocate only the shared raw ec2go table."""
        paths = real_paths(producer, input_dir=input_dir)
        if "ec_to_go" in paths:
            paths["ec_to_go"] = (tmp_path / "raw" / "ec2go.txt").absolute()
        return paths

    monkeypatch.setattr(optional_consumed_inputs, "optional_input_paths", fixture_paths)
    instance = object.__new__(MetaTraitsGTDBTransform)
    Transform.__init__(instance, METATRAITS_GTDB, input_dir=tmp_path / "raw", output_dir=tmp_path)
    instance.edge_header += ["has_percentage", "value", "unit"]
    instance.knowledge_source = "infores:gtdb-metatraits"
    instance.ec_to_go = instance._load_ec_to_go()
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


def test_historical_mappings_preserve_proposals_without_asserting_containment(transform, capsys):
    """The fan-in decision is about today's subject, not an alleged historical alias."""
    original_nodes = transform.output_node_file.read_bytes()
    original_edges = transform.output_edge_file.read_bytes()
    transform._create_hierarchical_edges()
    assert transform.output_node_file.read_bytes() == original_nodes
    assert transform.output_edge_file.read_bytes() == original_edges
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        audit = list(csv.DictReader(handle, delimiter="\t"))
    assert len(audit) == 6
    proposals = [edge for row in audit for edge in json.loads(row["proposed_edges_json"])]
    assert len(proposals) == 7  # Four unproved subclass and three copied mapping proposals.
    mappings = {edge["subject"]: edge for edge in proposals if edge["object"].startswith("NCBITaxon:")}
    assert len(mappings) == 3
    shared = mappings["GTDB:s__Historical_sp000000001"]
    assert (shared["predicate"], shared["relation"]) == ("biolink:broad_match", "skos:broadMatch")
    for node_id in ("GTDB:s__Solo_sp000000002", "GTDB:s__Alias_sp000000005"):
        assert (mappings[node_id]["predicate"], mappings[node_id]["relation"]) == (
            "biolink:close_match",
            "skos:closeMatch",
        )
    assert not _read_edges(transform)
    verify_producer_audits(transform)
    transform.verify_consumed_inputs()
    assert "1 NCBI links skipped: no matching canonical GTDB mapping" in capsys.readouterr().out


def test_quarantined_proposals_keep_complete_provenance_and_lf(transform):
    """Audit-only proposals retain the exact old semantics; they are not graph assertions."""
    transform._create_hierarchical_edges()
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        audit = list(csv.DictReader(handle, delimiter="\t"))
    proposals = [edge for row in audit for edge in json.loads(row["proposed_edges_json"])]
    assert len(proposals) == 7
    for edge in proposals:
        assert None not in edge
        for column in transform.edge_header[:7]:
            assert edge[column], f"Missing {column} in {edge}"
        assert edge["primary_knowledge_source"] == "infores:gtdb-metatraits"
        expected_level = "knowledge_assertion" if edge["predicate"] == "biolink:subclass_of" else "prediction"
        assert edge["knowledge_level"] == expected_level
        assert edge["agent_type"] == "automated_agent"
    assert b"\r\n" not in transform.output_edge_file.read_bytes()
    assert b"\r\n" not in (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).read_bytes()


def test_audit_and_consumed_canonical_input_cannot_be_restamped(transform):
    """Audit drift and authority mutation invalidate producer completion."""
    transform._create_hierarchical_edges()
    audit = transform.output_dir / HISTORICAL_BRIDGE_AUDIT
    audit.write_bytes(audit.read_bytes() + b"changed\n")
    with pytest.raises(SourceFinalizationRequired, match="audit changed"):
        verify_producer_audits(transform)
    canonical = transform.output_base_dir / GTDB / "edges.tsv"
    canonical.write_bytes(canonical.read_bytes() + b"changed\n")
    with pytest.raises(SourceFinalizationRequired, match="changed or missing"):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("values", [("first", "second", "first"), ("second", "first", "second")])
def test_numeric_hint_conflicts_are_not_last_row_wins(values):
    """Discarding accession namespace/version cannot resolve conflicting taxa."""
    lookup, conflicts = {}, {}
    for value in values:
        _register_numeric_candidate(lookup, conflicts, "sp000000001", value)
    assert lookup == {}
    assert conflicts == {"sp000000001": {"first", "second"}}


def test_conflicting_hint_keeps_every_candidate_in_audit(transform):
    """Conflict candidates remain explicit and never authorize an edge."""
    transform.accession_to_gtdb_species.pop("sp000000001")
    transform.accession_species_conflicts = {"sp000000001": {"Current one", "Current other"}}
    transform._create_hierarchical_edges()
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        audit = {row["subject"]: row for row in csv.DictReader(handle, delimiter="\t")}
    row = audit["GTDB:s__Historical_sp000000001"]
    assert row["disposition"] == "quarantined_ambiguous_numeric_hint"
    assert json.loads(row["candidate_species_json"]) == ["Current one", "Current other"]
    assert not _read_edges(transform)


def test_exact_current_subject_retains_conflicted_ncbi_disposition(transform):
    """An identical species name cannot resolve a conflicting NCBI hint (#1287)."""
    transform.accession_to_gtdb_species["sp000000001"] = "Historical sp000000001"
    transform.accession_to_ncbi.pop("sp000000001")
    transform.accession_ncbi_conflicts = {"sp000000001": {"NCBITaxon:1", "NCBITaxon:9"}}
    transform._create_hierarchical_edges()
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        audit = {row["subject"]: row for row in csv.DictReader(handle, delimiter="\t")}
    row = audit["GTDB:s__Historical_sp000000001"]
    assert row["disposition"] == "quarantined_ambiguous_numeric_hint"
    assert json.loads(row["candidate_ncbi_json"]) == ["NCBITaxon:1", "NCBITaxon:9"]
    assert not _read_edges(transform)


def test_conflicting_hint_preserves_canonical_evidence_without_asserting_it(transform):
    """Every supported candidate stays auditable, not just a chosen mapping (#1287)."""
    transform.accession_to_gtdb_species.pop("sp000000001")
    transform.accession_species_conflicts = {"sp000000001": {"Current one", "Current other"}}
    path = transform.output_base_dir / GTDB / "edges.tsv"
    with path.open() as handle:
        header = next(csv.reader(handle, delimiter="\t"))
    with path.open("a", newline="") as handle:
        tsv_dict_writer(handle, fieldnames=header).writerow(
            {
                "subject": "GTDB:s__Current_other",
                "predicate": "biolink:broad_match",
                "object": "NCBITaxon:1",
                "relation": "skos:broadMatch",
                "primary_knowledge_source": "infores:gtdb",
                "knowledge_level": "prediction",
                "agent_type": "automated_agent",
            }
        )
    before = transform.output_edge_file.read_bytes()
    transform._create_hierarchical_edges()
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        audit = {row["subject"]: row for row in csv.DictReader(handle, delimiter="\t")}
    evidence = json.loads(audit["GTDB:s__Historical_sp000000001"]["canonical_evidence_json"])
    assert {row["subject"] for row in evidence} == {"GTDB:s__Current_one", "GTDB:s__Current_other"}
    assert transform.output_edge_file.read_bytes() == before


def test_reloading_selected_taxonomy_does_not_carry_previous_epoch(tmp_path):
    """A new load resets candidates and conflicts together (#1287)."""
    transform = object.__new__(MetaTraitsGTDBTransform)
    transform.input_base_dir = tmp_path
    transform.accession_to_gtdb_species = {"sp000000001": "Former species"}
    root = tmp_path / "gtdb"
    root.mkdir()
    selected = Path(__file__).parent / "resources/metatraits_gtdb_selected_root/selected/gtdb"
    for name in ("bac120_taxonomy.tsv", "ar53_taxonomy.tsv"):
        shutil.copyfile(selected / name, root / name)
    transform._load_gtdb_taxonomy()
    assert transform.accession_to_gtdb_species["sp000000001"] == "Selected bacterium sp000000001"
    assert transform.accession_species_conflicts == {}


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
