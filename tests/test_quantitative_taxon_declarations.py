"""Quantitative-only worker assertions must retain their taxon declarations."""

import json
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest

from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from tests.test_metatraits_indeterminate import _input, _rows, _run, _transform

FIXTURE = Path(__file__).parent / "resources/metatraits_gtdb_quantitative_only.json"


def _ready(tmp_path, monkeypatch, transform_type):
    transform, _ = _transform(tmp_path, monkeypatch, transform_type, route="tier1")
    transform.metpo_binned_ranges = {
        "temperature": [
            {"curie": "METPO:1000443", "label": "fixture temperature bin", "range_min": 0, "range_max": 100}
        ],
        "NaCl": [{"curie": "METPO:1000001", "label": "fixture salinity bin", "range_min": 0, "range_max": 100}],
        "pH": [{"curie": "METPO:1000002", "label": "fixture pH bin", "range_min": 0, "range_max": 14}],
    }
    return transform


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
def test_all_observed_quantitative_only_records_declare_worker_taxa(tmp_path, monkeypatch, transform_type):
    """Use all 25 immutable source records via the actual worker and output merger."""
    transform = _ready(tmp_path, monkeypatch, transform_type)
    records = [item["record"] for item in json.loads(FIXTURE.read_text())["records"]]
    assert len(records) == 25 and all(len(record["summaries"]) == 1 for record in records)
    if transform_type is MetaTraitsTransform:
        transform.ncbitaxon_name_to_id = {
            record["tax_name"].lower(): f"NCBITaxon:{100 + i}" for i, record in enumerate(records)
        }
    paths = [_input(tmp_path, record, f"input_{i}.jsonl") for i, record in enumerate(records)]
    edges = _run(transform, "worker", paths, tmp_path)
    nodes = _rows(transform.output_node_file)
    by_id = {node["id"]: node for node in nodes}
    assert len(edges) == 25
    for edge, record in zip(edges, records, strict=True):
        node = by_id[edge["subject"]]
        assert node["category"] == "biolink:OrganismTaxon"
        assert node["name"] == record["tax_name"]
        assert node["provided_by"] == transform.knowledge_source
        assert sum(n["id"] == node["id"] for n in nodes) == 1
        assert edge["predicate"] == "biolink:has_phenotype"
        assert edge["unit"] == "Celsius"


@pytest.mark.parametrize("trait", ["temperature growth", "salinity growth", "pH growth"])
@pytest.mark.parametrize("mixed", [False, True])
def test_optimum_bins_and_categorical_traits_share_one_declaration(tmp_path, monkeypatch, trait, mixed):
    """Each numeric branch declares once even when a categorical branch also emits."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    record = {"tax_name": "Arthrobacter_D sp030433645", "summaries": [{"name": trait, "majority_label": "Median: 7.0"}]}
    if mixed:
        record["summaries"].append({"name": "gram positive", "majority_label": "true", "percentages": {"true": 100}})
    edges = _run(transform, "worker", [_input(tmp_path, record)], tmp_path)
    taxa = [node for node in _rows(transform.output_node_file) if node["id"].startswith("GTDB:")]
    assert len(taxa) == 1
    assert len(edges) == (2 if mixed else 1)
    assert {edge["subject"] for edge in edges} == {taxa[0]["id"]}


@pytest.mark.parametrize("kind", ["temperature", "salinity", "ph"])
def test_range_phenotype_routes_also_declare_taxa(tmp_path, monkeypatch, kind):
    """Cover the three range-classification writer branches independently."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    phenotype = {
        "curie": "METPO:1000615",
        "name": "fixture phenotype",
        "category": "biolink:PhenotypicQuality",
        "predicate": "biolink:has_phenotype",
    }
    # Direct worker invocation keeps this narrow fixture classifier in-process.
    for other in ("temperature", "salinity", "ph"):
        monkeypatch.setattr(transform, f"_classify_{other}_phenotypes", lambda *args: [])
    monkeypatch.setattr(transform, f"_classify_{kind}_phenotypes", lambda *args: [phenotype])
    record = {"tax_name": "Arthrobacter_D sp030433645", "summaries": []}
    temp = tmp_path / "worker"
    temp.mkdir()
    result = transform._process_single_file(_input(tmp_path, record), temp, show_status=False)
    nodes = _rows(Path(result["nodes_file"]))
    assert any(
        row["id"] == "GTDB:s__Arthrobacter_D_sp030433645" and row["category"] == "biolink:OrganismTaxon"
        for row in nodes
    )


@pytest.mark.parametrize(
    "summary",
    [
        None,
        {"name": "temperature growth", "majority_label": "No robust majority"},
        {"name": "gram positive", "majority_label": "No robust majority"},
    ],
)
def test_empty_unclassified_and_deferred_records_do_not_mint_taxa(tmp_path, monkeypatch, summary):
    """Do not create edgeless nodes for empty or explicitly indeterminate records."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    record = {"tax_name": "Arthrobacter_D sp030433645", "summaries": [] if summary is None else [summary]}
    assert _run(transform, "worker", [_input(tmp_path, record)], tmp_path) == []
    assert _rows(transform.output_node_file) == []


def test_serial_numeric_semantics_are_not_expanded(tmp_path, monkeypatch):
    """Retain the pre-existing serial treatment of quantitative summaries."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    record = json.loads(FIXTURE.read_text())["records"][0]["record"]
    assert _run(transform, "serial", [_input(tmp_path, record)], tmp_path) == []
    assert _rows(transform.output_node_file) == []


def test_chunked_pool_dispatch_preserves_numeric_subject_declarations(tmp_path, monkeypatch):
    """Exercise the production chunk split, pooled worker dispatch and output merger."""
    transform = _ready(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    records = [item["record"] for item in json.loads(FIXTURE.read_text())["records"][:3]]
    path = tmp_path / "records.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    monkeypatch.setattr(metatraits.multiprocessing, "Pool", ThreadPool)
    transform._run_parallel_chunked(path, show_status=False, num_workers=2)
    edges = _rows(transform.output_edge_file)
    taxa = [node for node in _rows(transform.output_node_file) if node["id"].startswith("GTDB:")]
    assert len(edges) == len(taxa) == 3
    assert {row["subject"] for row in edges} == {row["id"] for row in taxa}
    assert all(row["category"] == "biolink:OrganismTaxon" and row["name"] for row in taxa)
