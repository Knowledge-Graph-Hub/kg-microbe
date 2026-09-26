"""Record-local citations survive keyword/enzyme processing in the actual run path (#1173)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import ORIGINAL_OBJECT_COLUMN, PUBLICATIONS_COLUMN
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import graph_rows

FIXTURE = Path(__file__).parent / "resources/bacdive_publications/run_records.json"


def _run_fixture(tmp_path, monkeypatch, records):
    """Run the producer itself with tiny local mappings and no external ontology or assay setup."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bacdive_strains.json").write_text(json.dumps(records))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / module.BACDIVE_MAPPING_FILE).write_text("EC_ID\tCHEBI_ID\tsubstrate\n")
    custom = tmp_path / "custom.yaml"
    custom.write_text("{}\n")
    monkeypatch.setattr(module, "BACDIVE_TMP_DIR", scratch)
    monkeypatch.setattr(module, "CUSTOM_CURIES_YAML_FILE", custom)
    monkeypatch.setattr(module, "METABOLITE_MAP", {})
    # This fixture contains no NCBITaxon assertions. Only adapter preflight is
    # replaced; run(), keyword/phenotype processing, emitters and TSV writers run.
    monkeypatch.setattr(module, "resolve_adapter", lambda adapter: adapter)
    transform = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(transform, "bacdive", raw, tmp_path / "transformed")
    transform.edge_header.extend(["value", "unit", PUBLICATIONS_COLUMN, ORIGINAL_OBJECT_COLUMN])
    transform.ncbi_impl = object()
    transform.knowledge_source = "infores:bacdive"
    transform.chemical_loader = None
    transform.chebi_categories = {}
    transform.assay_kit_mappings = {}
    transform.pathogenicity_mappings = {}
    transform._ncbitaxon_ancestry_failures = set()
    transform._lpsn_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    transform.bacdive_metpo_mappings = {
        "fixture_keyword": {"curie": "METPO:1000001", "label": "fixture keyword"},
        "fixture phenotype": {"curie": "METPO:1000002", "label": "fixture phenotype"},
    }
    transform.bacdive_metpo_tree = {
        "METPO:1000000": SimpleNamespace(bacdive_json_paths=["Physiology and metabolism.oxygen tolerance"], children=[])
    }
    transform.phenotype_routing = [{"metpo_parent_id": "METPO:1000000"}]
    transform.metpo_enzyme_mappings = {"+": {"curie": "METPO:2000300"}}
    transform.metpo_metabolite_utilization_mappings = {
        "carbon source": {"+": {"curie": "METPO:2000006"}, "-": {"curie": "METPO:2000031"}}
    }
    transform.run(show_status=False)
    return list(graph_rows(transform.output_edge_file)), list(graph_rows(transform.output_node_file))


@pytest.mark.parametrize("keyword", [False, True], ids=["no-keywords", "matched-keyword"])
@pytest.mark.parametrize("enzyme", ["dict", "list", "skipped", "absent"])
@pytest.mark.parametrize("old_input_shape", [False, True], ids=["list-records", "dict-records"])
def test_run_preserves_record_and_item_references(tmp_path, monkeypatch, keyword, enzyme, old_input_shape):
    """Active/skipped enzymes and keyword dictionaries cannot replace the record or its DOI index."""
    records = json.loads(FIXTURE.read_text())
    for record in records:
        if not keyword:
            record["General"].pop("keywords")
        physiology = record["Physiology and metabolism"]
        if enzyme == "list":
            physiology["enzymes"] = [physiology["enzymes"]]
        elif enzyme == "skipped":
            # Missing EC causes a continue only AFTER the old scalar assignment.
            physiology["enzymes"] = {"activity": "+", "value": None}
        elif enzyme == "absent":
            physiology.pop("enzymes")
    input_records = {str(i): record for i, record in enumerate(records)} if old_input_shape else records
    edges, nodes = _run_fixture(tmp_path, monkeypatch, input_records)

    observed = {
        (row["subject"], row["predicate"], row["object"], frozenset(row[PUBLICATIONS_COLUMN].split("|")))
        for row in edges
        if row["predicate"] in {"METPO:2000006", "METPO:2000031"}
    }
    first = "https://bacdive.dsmz.de/strain/1"
    second = "https://bacdive.dsmz.de/strain/2"
    third = "https://bacdive.dsmz.de/strain/3"
    assert observed == {
        ("kgmicrobe.strain:bacdive_1", "METPO:2000006", "CHEBI:17234", frozenset([first, "doi:10.1234/positive"])),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000031", "CHEBI:17234", frozenset([first, "doi:10.1234/negative"])),
        (
            "kgmicrobe.strain:bacdive_1",
            "METPO:2000006",
            "CHEBI:17234",
            frozenset([first, "doi:10.1234/positive-second"]),
        ),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000006", "CHEBI:17234", frozenset([first])),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000031", "CHEBI:15377", frozenset([first])),
        (
            "kgmicrobe.strain:bacdive_2",
            "METPO:2000006",
            "CHEBI:17234",
            frozenset([second, "doi:10.1234/second-record"]),
        ),
        ("kgmicrobe.strain:bacdive_3", "METPO:2000031", "CHEBI:17234", frozenset([third])),
    }
    assert len(observed) == 7
    assert len(edges) == 10 + (3 if keyword else 0) + (3 if enzyme in {"dict", "list"} else 0)
    for row in edges:
        assert row["primary_knowledge_source"] == "infores:bacdive"
        assert row["knowledge_level"] == "observation"
        assert row["agent_type"] == "manual_agent"
        if row["predicate"] not in {"METPO:2000006", "METPO:2000031"}:
            assert row[PUBLICATIONS_COLUMN] == f"https://bacdive.dsmz.de/strain/{row['subject'].rsplit('_', 1)[1]}"
    # Phenotype routing occurs after both shadowing paths and also needs the record.
    assert {row["subject"] for row in edges if row["object"] == "METPO:1000002"} == {
        f"kgmicrobe.strain:bacdive_{number}" for number in (1, 2, 3)
    }
    enzyme_nodes = [row for row in nodes if row["id"] == "EC:1.1.1.1"]
    assert [row["name"] for row in enzyme_nodes] == (["fixture enzyme"] if enzyme in {"dict", "list"} else [])
