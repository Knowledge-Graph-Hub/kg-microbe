"""Actual native GOLD/CSV witnesses at the MicrobeDecoder crosswalk boundary (#1316)."""

import csv
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.transform_utils.gold.taxon_dispositions import load_gold_declarations
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.test_gold_taxon_dispositions import _write

FIXTURE = Path(__file__).parent / "resources/gold_taxonomy/microbedecoder_native_context.json"
FIELDS = (
    "source_record",
    "source_column",
    "source_cell_json",
    "source_token_json",
    "native_record_json",
    "original_claim_json",
    "emitted_claim_json",
    "gold_declaration_json",
    "gold_native_node_json",
    "gold_evidence_sha256",
)


@pytest.fixture
def native_dispatch(tmp_path, monkeypatch):
    """Stage complete selected records, retaining full-export coordinates only as labelled evidence."""
    evidence = json.loads(FIXTURE.read_text())
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    nodes = [item["row"] for item in evidence["gold_nodes"].values()]
    _write(raw / "gold/GOLD_nodes.tsv", nodes[0].keys(), nodes)
    edges = [item["row"] for item in evidence["gold_parent_claims"]]
    _write(raw / "gold/GOLD_edges.tsv", edges[0].keys(), edges)
    _write(
        output / "ontologies/ncbitaxon_nodes.tsv",
        nodes[0].keys(),
        [node for node in nodes if node["id"].startswith("NCBITaxon:")],
    )
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "true")
    gold = GOLDTransform(raw, output)
    gold.run()
    gold.finalize(fresh_run=True)
    consumer = MicrobeDecoderTransform(raw, output, chemical_loader=object())
    consumer._gold_crosswalk_declarations = load_gold_declarations(consumer, {evidence["selected"]})
    consumer._source_record = evidence["microbedecoder"]["source_record"]
    return consumer, evidence


def _dispatch(consumer, evidence):
    """Exercise the actual crosswalk emitter; this is not a complete trait-transform replay."""
    nodes, edges, audit = io.StringIO(), io.StringIO(), io.StringIO()
    consumer._gold_crosswalk_writer = csv.DictWriter(audit, fieldnames=FIELDS, delimiter="\t")
    consumer._gold_crosswalk_writer.writeheader()
    native = evidence["microbedecoder"]["full_native_record"]
    subject = evidence["microbedecoder"]["current_claims"][0]["row"]["subject"]
    consumer._emit_crosswalk_edges(
        subject, native, csv.writer(nodes, delimiter="\t"), csv.writer(edges, delimiter="\t")
    )

    def rows(handle, header=None):
        """Dispatch immutable fixture rows through the requested native table shape."""
        return list(csv.DictReader(io.StringIO(handle.getvalue()), fieldnames=header, delimiter="\t"))

    return rows(nodes, consumer.node_header), rows(edges, consumer.edge_header), rows(audit)


def test_actual_native_crosswalk_retains_observation_not_identity(native_dispatch):
    """Rejoin actual native records to the emitted association and complete audit."""
    consumer, evidence = native_dispatch
    nodes, edges, audit = _dispatch(consumer, evidence)
    identifier = evidence["selected"]
    retained = next(row for row in nodes if row["id"] == identifier)
    assert retained["category"] == "biolink:NamedThing"
    assert retained["name"] == evidence["gold_nodes"][identifier]["row"]["name"]
    selected = [row for row in edges if row["object"] == identifier]
    assert len(selected) == len(audit) == 1
    assert selected[0]["predicate"] == selected[0]["relation"] == "biolink:related_to"
    assert selected[0]["source_record"] == evidence["microbedecoder"]["source_record"]
    assert selected[0]["source_column"] == "GOLD_Organism_ID"
    assert json.loads(audit[0]["native_record_json"]) == evidence["microbedecoder"]["full_native_record"]
    assert json.loads(audit[0]["original_claim_json"])["predicate"] == "biolink:close_match"
    assert json.loads(audit[0]["gold_native_node_json"])["row"] == evidence["gold_nodes"][identifier]["row"]
    assert (
        consumer._gold_crosswalk_declarations.declaration_for(identifier).evidence_sha256
        == audit[0]["gold_evidence_sha256"]
    )


def test_different_native_observation_ordinals_are_not_collapsed(native_dispatch):
    """An explicit duplicate-observation perturbation is not additional scientific fixture evidence."""
    consumer, evidence = native_dispatch
    _, first, _ = _dispatch(consumer, evidence)
    consumer._source_record = consumer._source_record.rsplit("=", 1)[0] + "=4"
    _, second, _ = _dispatch(consumer, evidence)
    a = next(row for row in first if row["object"] == evidence["selected"])
    b = next(row for row in second if row["object"] == evidence["selected"])
    assert a["source_record"] != b["source_record"]
    assert a["object"] == b["object"]
