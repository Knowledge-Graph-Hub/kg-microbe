"""Numeric declarations must not introduce reflexive GTDB hierarchy edges."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    BROAD_MATCH_PREDICATE,
    BROAD_MATCH_RELATION,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    PREDICTION,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import HISTORICAL_BRIDGE_AUDIT, MetaTraitsGTDBTransform
from kg_microbe.utils.tsv_io import tsv_dict_writer
from tests.test_metatraits_indeterminate import _input, _rows
from tests.test_quantitative_taxon_declarations import FIXTURE, _ready


def _canonical_fixture(transform, subject, canonical):
    """Prepare a real canonical TSV and actual consumed/audit lifecycle for the tiny worker."""
    transform.begin_consumed_inputs()
    transform.output_base_dir = transform.output_dir.parent
    path = transform.output_base_dir / "gtdb" / "edges.tsv"
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = tsv_dict_writer(handle, fieldnames=transform.edge_header)
        writer.writeheader()
        if canonical:
            writer.writerow(
                {
                    "subject": subject,
                    "predicate": canonical[0],
                    "object": "NCBITaxon:11",
                    "relation": canonical[1],
                    "primary_knowledge_source": "infores:gtdb",
                    "knowledge_level": "prediction",
                    "agent_type": "automated_agent",
                }
            )


@pytest.mark.parametrize(
    "canonical",
    [None, (BROAD_MATCH_PREDICATE, BROAD_MATCH_RELATION), (CLOSE_MATCH_PREDICATE, CLOSE_MATCH_RELATION)],
)
def test_same_current_species_keeps_observation_and_canonical_mapping(tmp_path, monkeypatch, canonical):
    """Skip only self-subclass; independently authorized broad/close links survive."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    record = json.loads(FIXTURE.read_text())["records"][0]["record"]
    subject = "GTDB:s__Arthrobacter_D_sp030433645"
    transform.accession_to_gtdb_species = {"sp030433645": record["tax_name"]}
    transform.accession_to_ncbi = {"sp030433645": "NCBITaxon:11"} if canonical else {}
    assert not transform.gtdb_to_ncbi.get(record["tax_name"])
    result = transform._process_single_file(_input(tmp_path, record), tmp_path, show_status=False)
    transform.output_node_file = Path(result["nodes_file"])
    transform.output_edge_file = Path(result["edges_file"])
    original_nodes = transform.output_node_file.read_bytes()
    before = _rows(transform.output_edge_file)
    assert len(before) == 1 and before[0]["subject"] == subject
    _canonical_fixture(transform, subject, canonical)
    transform._create_hierarchical_edges()
    after = _rows(transform.output_edge_file)
    assert after[: len(before)] == before
    assert transform.output_node_file.read_bytes() == original_nodes
    assert not any(row["subject"] == row["object"] for row in after)
    assert len(after) == (2 if canonical else 1)
    if canonical:
        assert (after[-1]["predicate"], after[-1]["relation"]) == canonical
        assert after[-1]["subject"] == subject and after[-1]["object"] == "NCBITaxon:11"
        assert after[-1]["knowledge_level"] == PREDICTION
        assert after[-1]["primary_knowledge_source"] == transform.knowledge_source


def test_distinct_current_species_quarantines_unproved_hierarchy(tmp_path, monkeypatch):
    """A shared numeric hint is not evidence that one historical species contains another."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    record = json.loads(FIXTURE.read_text())["records"][0]["record"]
    transform.accession_to_gtdb_species = {"sp030433645": "Arthrobacter_D burdickii"}
    transform.accession_to_ncbi = {}
    result = transform._process_single_file(_input(tmp_path, record), tmp_path, show_status=False)
    transform.output_node_file = Path(result["nodes_file"])
    transform.output_edge_file = Path(result["edges_file"])
    before = _rows(transform.output_edge_file)
    _canonical_fixture(transform, "GTDB:s__Arthrobacter_D_burdickii", None)
    transform._create_hierarchical_edges()
    after = _rows(transform.output_edge_file)
    assert after == before
    with (transform.output_dir / HISTORICAL_BRIDGE_AUDIT).open(newline="") as handle:
        (row,) = list(csv.DictReader(handle, delimiter="\t"))
    (proposed,) = json.loads(row["proposed_edges_json"])
    assert proposed["subject"] == "GTDB:s__Arthrobacter_D_sp030433645"
    assert proposed["object"] == "GTDB:s__Arthrobacter_D_burdickii"
    assert (proposed["predicate"], proposed["relation"]) == (SUBCLASS_PREDICATE, RDFS_SUBCLASS_OF)
