"""Exact source, claim and reversible audit contracts for reviewed crosswalks."""

import base64
import csv
import hashlib
import io
import json
from dataclasses import asdict

import pytest

from kg_microbe.transform_utils.microbedecoder.crosswalk_quarantine import (
    CrosswalkQuarantine,
    QuarantinePolicy,
)
from tests.microbedecoder_quarantine_fixtures import write_fixture_quarantine_policy


def _source(tmp_path, rows=None):
    path = tmp_path / "database.csv"
    rows = rows or [
        {
            "LPSN_ID": "101",
            "NCBI_Taxonomy_ID": "1352",
            "GOLD_Organism_ID": "Go0020981",
            "citation": 'literal "x", pipe| and\nnewline',
        },
        {"LPSN_ID": "102", "NCBI_Taxonomy_ID": "1352", "GOLD_Organism_ID": "Go0020981", "citation": "another record"},
    ]
    rows = [{"BacDive_ID": "42", **row} for row in rows]
    with path.open("w", newline="", encoding="utf-8", errors="surrogateescape") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _load(policy_path):
    policy = QuarantinePolicy.load(policy_path)
    return CrosswalkQuarantine(
        policy, policy_path.parent / policy.decisions_file, policy_path.parent / policy.evidence_file
    )


def _preflight(quarantine, raw_path, accepted=None):
    stream = io.StringIO(raw_path.read_bytes().decode("utf-8", errors="surrogateescape"), newline="")
    quarantine.preflight(stream, hashlib.sha256(raw_path.read_bytes()).hexdigest(), accepted or {})
    return list(csv.DictReader(stream))


def _edit_decisions(policy_path, change):
    policy = json.loads(policy_path.read_text())
    path = policy_path.parent / policy["decisions_file"]
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        header, rows = reader.fieldnames, list(reader)
    change(rows)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    policy["decisions_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    policy_path.write_text(json.dumps(policy))


def test_exact_claim_only_and_reversible_original_evidence(tmp_path):
    """Only the selected record/field is removed, with lossless full evidence."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])
    quarantine = _load(policy)
    rows = _preflight(quarantine, raw)
    record = f"sha256:{quarantine.policy.source_sha256}#record=1"
    assert quarantine.match(record, rows[0], "lpsn:101", "GOLD_Organism_ID", "Go0020981", "gold:Go0020981") is None
    assert (
        quarantine.match(
            record.replace("record=1", "record=2"), rows[1], "lpsn:102", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352"
        )
        is None
    )
    rule = quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    claim = {
        key: value
        for key, value in asdict(rule).items()
        if key
        in {
            "subject",
            "object",
            "predicate",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "source_record",
        }
    }
    claim["unanticipated_context"] = 'retain "quotes" | and\ttab'
    audit = quarantine.audit_row(rule, rows[0], claim)
    assert json.loads(audit["original_claim_json"]) == claim
    assert json.loads(base64.b64decode(audit["original_claim_base64"])) == claim
    assert json.loads(base64.b64decode(audit["raw_record_base64"])) == rows[0]
    assert json.loads(audit["raw_record_json"]) == rows[0]
    quarantine.require_complete()
    with pytest.raises(ValueError, match="duplicate quarantine dispatch"):
        quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")


@pytest.mark.parametrize("field,value", [("LPSN_ID", ""), ("NCBI_Taxonomy_ID", ""), ("citation", "changed")])
def test_complete_record_drift_rejects_even_after_rebinding_outer_source_hash(tmp_path, field, value):
    """Known record changes cannot escape a disposition through a blank field."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])
    quarantine = _load(policy)
    rows = _preflight(quarantine, raw)
    rows[0][field] = value
    with pytest.raises(ValueError, match="complete record"):
        quarantine.match(
            f"sha256:{quarantine.policy.source_sha256}#record=1",
            rows[0],
            "lpsn:101",
            "NCBI_Taxonomy_ID",
            "1352",
            "NCBITaxon:1352",
        )


def test_changed_snapshot_cannot_evade_rules_by_reordering_or_blanking(tmp_path):
    """Any raw byte change requires deliberate new source review."""
    raw = _source(tmp_path)
    quarantine = _load(write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")]))
    raw.write_bytes(raw.read_bytes().replace(b"101,1352", b"101,"))
    with pytest.raises(ValueError, match="newly reviewed policy"):
        _preflight(quarantine, raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("predicate", "biolink:same_as"),
        ("relation", "owl:sameAs"),
        ("subject", "NCBITaxon:101"),
        ("source_column", "GTDB_ID"),
        ("object", "NCBITaxon:1"),
        ("source_token", "999"),
        ("knowledge_level", "prediction"),
        ("primary_knowledge_source", "infores:other"),
        ("agent_type", "automated_agent"),
        ("disposition", "replace"),
        ("raw_record_sha256", "invalid"),
        ("source_cell_base64", "invalid"),
        ("witness_id", "missing"),
    ],
)
def test_invalid_finite_claim_contract_fails_closed(tmp_path, field, value):
    """A curated table cannot authorize an unsupported route or target."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])
    _edit_decisions(policy, lambda rows: rows[0].update({field: value}))
    with pytest.raises(ValueError):
        _load(policy)


def test_duplicate_and_undispatched_claims_are_not_partial_success(tmp_path):
    """Require one dispatch per reviewed occurrence and no partial success."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])
    quarantine = _load(policy)
    with pytest.raises(ValueError, match="preflight"):
        quarantine.match("anything", {}, "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    _preflight(quarantine, raw)
    with pytest.raises(ValueError, match="not all dispatched"):
        quarantine.require_complete()
    _edit_decisions(policy, lambda rows: rows.append(dict(rows[0])))
    with pytest.raises(ValueError, match="duplicate/conflicting"):
        _load(policy)


@pytest.mark.parametrize("member", ["decisions_file", "evidence_file"])
def test_contract_bytes_are_not_mutable_after_pin(tmp_path, member):
    """Both scientific disposition and detailed evidence remain immutable."""
    raw = _source(tmp_path)
    policy_path = write_fixture_quarantine_policy(raw, tmp_path / "policy")
    policy = json.loads(policy_path.read_text())
    path = policy_path.parent / policy[member]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bytes differ"):
        _load(policy_path)


def test_zero_decisions_is_explicit_hash_bound_policy_not_source_bypass(tmp_path):
    """An empty finite fixture policy still enforces its exact raw snapshot."""
    raw = _source(tmp_path)
    quarantine = _load(write_fixture_quarantine_policy(raw, tmp_path / "policy"))
    _preflight(quarantine, raw)
    quarantine.require_complete()
    raw.write_bytes(raw.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="newly reviewed policy"):
        _preflight(quarantine, raw)


@pytest.mark.parametrize(
    "raw_text", ["LPSN_ID,LPSN_ID\n101,101\n", "LPSN_ID,x\n101\n", "LPSN_ID\n101,extra\n", ",LPSN_ID\nx,101\n"]
)
def test_malformed_raw_headers_and_rows_fail_before_emission(tmp_path, raw_text):
    """Raw field corruption is not silently hidden by DictReader behavior."""
    raw = tmp_path / "raw.csv"
    raw.write_text(raw_text)
    quarantine = _load(write_fixture_quarantine_policy(raw, tmp_path / "policy"))
    with pytest.raises(ValueError, match="raw CSV"):
        _preflight(quarantine, raw)


def test_non_utf8_raw_evidence_remains_reversible(tmp_path):
    """Surrogateescaped upstream bytes remain recoverable from the audit."""
    raw = _source(tmp_path, [{"LPSN_ID": "101", "NCBI_Taxonomy_ID": "1352", "citation": "byte\udcff"}])
    quarantine = _load(write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")]))
    rows = _preflight(quarantine, raw)
    record = f"sha256:{quarantine.policy.source_sha256}#record=1"
    rule = quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    claim = {
        key: value
        for key, value in asdict(rule).items()
        if key
        in {
            "subject",
            "object",
            "predicate",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "source_record",
        }
    }
    recovered = json.loads(quarantine.audit_row(rule, rows[0], claim)["raw_record_json"])
    assert recovered["citation"].encode("utf-8", errors="surrogateescape") == b"byte\xff"


def test_failed_preflight_revokes_prior_ready_state_before_hash_validation(tmp_path):
    """A caught wrong-source retry cannot leave a previous consumer epoch usable."""
    raw = _source(tmp_path)
    quarantine = _load(write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")]))
    rows = _preflight(quarantine, raw)
    record = f"sha256:{quarantine.policy.source_sha256}#record=1"
    quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    with pytest.raises(ValueError, match="newly reviewed policy"):
        quarantine.preflight(io.StringIO("ignored"), "f" * 64, {})
    assert not quarantine._preflight_done and not quarantine._used
    with pytest.raises(ValueError, match="preflight"):
        quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    _preflight(quarantine, raw)
    quarantine.match(record, rows[0], "lpsn:101", "NCBI_Taxonomy_ID", "1352", "NCBITaxon:1352")
    quarantine.require_complete()
