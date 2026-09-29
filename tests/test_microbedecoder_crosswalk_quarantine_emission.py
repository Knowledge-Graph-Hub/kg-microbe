"""Actual producer preflight, pre-fold dispatch and audit publication regressions."""

import base64
import csv
import hashlib
import json

import pytest

from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_transform import _NoChebi, _supply_gold_fold_report


def _read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _setup(tmp_path, selected=((1, "NCBI_Taxonomy_ID"), (1, "GOLD_Organism_ID"))):
    raw = tmp_path / "database.csv"
    rows = [
        {
            "LPSN_ID": "101",
            "BacDive_ID": "42",
            "NCBI_Taxonomy_ID": "1352",
            "GOLD_Organism_ID": "Go0020981",
            "GTDB_ID": "RS_GCF_027571405.1",
            "IMG_Genome_ID": "2548876819",
            "Species": "Synthetic species",
        },
        {
            "LPSN_ID": "102",
            "BacDive_ID": "43",
            "NCBI_Taxonomy_ID": "1352",
            "GOLD_Organism_ID": "Go0020981",
            "GTDB_ID": "",
            "IMG_Genome_ID": "",
            "Species": "Different synthetic species",
        },
    ]
    with raw.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _supply_gold_fold_report(tmp_path)
    transform = MicrobeDecoderTransform(input_dir=tmp_path, output_dir=tmp_path, chemical_loader=_NoChebi())
    policy = bind_fixture_quarantine_policy(transform, raw, selected=selected)
    return transform, raw, policy, rows


def test_actual_producer_quarantines_only_exact_records_and_preserves_all_other_links(tmp_path):
    """Preserve unrelated assembly/IMG and same-target other-record assertions."""
    transform, raw, _, rows = _setup(tmp_path)
    transform.run(raw)
    edges = _read(transform.output_edge_file)
    first = [edge for edge in edges if edge["subject"] == "lpsn:101"]
    assert "NCBITaxon:1352" not in {edge["object"] for edge in first}
    assert "gold:Go0020981" not in {edge["object"] for edge in first}
    assert {"ncbi.assembly:GCF_027571405.1", "IMG:2548876819"} <= {edge["object"] for edge in first}
    assert {"NCBITaxon:1352", "gold:Go0020981"} <= {edge["object"] for edge in edges if edge["subject"] == "lpsn:102"}
    audit = _read(transform.output_dir / "crosswalk_quarantine.tsv")
    assert len(audit) == 2 and transform._stats["crosswalk_quarantined"] == 2
    for item in audit:
        claim = json.loads(item["original_claim_json"])
        assert set(claim) == set(transform.edge_header)
        assert claim["source_record"].endswith("#record=1")
        assert claim["subject"] == "lpsn:101" and claim["object"] == item["object"]
        assert json.loads(base64.b64decode(item["raw_record_base64"])) == rows[0]
    snapshot = transform.producer_audit_snapshots["crosswalk_quarantine.tsv"]
    assert (
        snapshot["sha256"]
        == hashlib.sha256((transform.output_dir / "crosswalk_quarantine.tsv").read_bytes()).hexdigest()
    )
    assert {"crosswalk_raw", "crosswalk_policy", "crosswalk_decisions", "crosswalk_evidence"} <= set(
        transform.consumed_input_snapshots
    )


def test_gold_quarantine_precedes_fold_and_never_suppresses_ncbi_field(tmp_path):
    """A GOLD rule cannot capture an NCBI source claim after folding."""
    transform, raw, _, _ = _setup(tmp_path, selected=((1, "GOLD_Organism_ID"),))
    transform._load_gold_organism_folds = lambda: {"gold:Go0020981": "NCBITaxon:1352"}
    transform.run(raw)
    first = [edge for edge in _read(transform.output_edge_file) if edge["subject"] == "lpsn:101"]
    assert len([edge for edge in first if edge["object"] == "NCBITaxon:1352"]) == 1
    assert all(edge.get("original_object", "") != "gold:Go0020981" for edge in first)
    audit = _read(transform.output_dir / "crosswalk_quarantine.tsv")
    assert len(audit) == 1 and audit[0]["object"] == "gold:Go0020981"
    assert json.loads(audit[0]["original_claim_json"])["object"] == "gold:Go0020981"


@pytest.mark.parametrize("mutation", ["blank_reference", "blank_subject", "reorder", "change_context"])
def test_drift_fails_before_any_existing_output_is_replaced(tmp_path, mutation):
    """Complete snapshot preflight protects all previous output bytes."""
    transform, raw, _, _ = _setup(tmp_path)
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    protected = [
        transform.output_node_file,
        transform.output_edge_file,
        transform.output_dir / "crosswalk_quarantine.tsv",
    ]
    for path in protected:
        path.write_text("previous committed bytes\n")
    payload = raw.read_bytes()
    if mutation == "blank_reference":
        payload = payload.replace(b",1352,", b",,")
    elif mutation == "blank_subject":
        payload = payload.replace(b"101,42", b",42")
    elif mutation == "reorder":
        lines = payload.splitlines(keepends=True)
        payload = b"".join([lines[0], lines[2], lines[1]])
    else:
        payload = payload.replace(b"Synthetic species", b"changed")
    raw.write_bytes(payload)
    with pytest.raises(ValueError, match="newly reviewed policy"):
        transform.run(raw)
    assert all(path.read_text() == "previous committed bytes\n" for path in protected)


def test_zero_decision_policy_still_emits_required_header_only_audit(tmp_path):
    """Every successful run must produce its declared audit artifact."""
    transform, raw, _, _ = _setup(tmp_path, selected=())
    transform.run(raw)
    assert _read(transform.output_dir / "crosswalk_quarantine.tsv") == []
    assert transform._stats["crosswalk_quarantined"] == 0
    assert "crosswalk_quarantine.tsv" in transform.producer_audit_snapshots


def test_reused_instance_resets_dispatch_and_audit_state(tmp_path):
    """Replaying the exact source does not accumulate decisions or counts."""
    transform, raw, _, _ = _setup(tmp_path)
    transform.run(raw)
    before = (transform.output_dir / "crosswalk_quarantine.tsv").read_bytes()
    transform.run(raw)
    assert (transform.output_dir / "crosswalk_quarantine.tsv").read_bytes() == before
    assert transform._stats["crosswalk_quarantined"] == 2
