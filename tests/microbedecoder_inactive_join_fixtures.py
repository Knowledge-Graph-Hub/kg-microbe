"""Explicit inactive protocol fixtures, separate from old and active join policies."""

import csv
import hashlib
import json
from pathlib import Path


def _json(value):
    """Use the finite protocol's canonical decoded-object digest convention."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha(payload):
    """Hash actual fixture bytes, never invent a consumed-input receipt."""
    return hashlib.sha256(payload).hexdigest()


def write_empty_join_gss(raw_directory):
    """Supply explicit empty GSS only in a caller-selected isolated fixture directory."""
    directory = Path(raw_directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "lpsn_gss.csv"
    if not path.exists():
        path.write_text("record_no,record_lnk,status\n", encoding="utf-8")
    # Existing intentional accepted-name fixtures are never overwritten.
    return path


def write_inactive_join_policy(source, gss, directory):
    """Pin real fixture CSV/GSS and explicit zero decisions; never run a producer."""
    source, gss, directory = Path(source), Path(gss), Path(directory)
    with source.open(encoding="utf-8", errors="surrogateescape", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not {"LPSN_ID", "BacDive_ID"} <= set(reader.fieldnames):
            raise ValueError("Explicit fixture source requires LPSN_ID and BacDive_ID headers")
        records = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in records):
            raise ValueError("Malformed literal fixture source")
    with gss.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not {"record_no", "record_lnk", "status"} <= set(reader.fieldnames):
            raise ValueError("Explicit fixture GSS requires native headers")
        list(reader)
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = directory / "microbedecoder_bacdive_join_evidence.json"
    policy_path = directory / "microbedecoder_bacdive_join_dispositions.json"
    evidence = {
        "version": 1,
        "cases": [],
        "fixture_boundary": "Synthetic inactive protocol; not scientific six-case authority.",
    }
    evidence_payload = _json(evidence).encode()
    policy = {
        "version": 1,
        "source_sha256": _sha(source.read_bytes()),
        "source_records": len(records),
        "lpsn_gss_sha256": _sha(gss.read_bytes()),
        "evidence_file": evidence_path.name,
        "evidence_sha256": _sha(evidence_payload),
        "decisions": [],
    }
    for path, payload in ((evidence_path, evidence_payload), (policy_path, _json(policy).encode())):
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Fixture policy path already represents different source bytes")
        if not path.exists():
            path.write_bytes(payload)
    return policy_path


def bind_inactive_join_policy(transform, source, monkeypatch, *, canonical_directory=None):
    """Bind an explicit caller-owned patch scope through run/finalize/admission."""
    from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins

    source = Path(source)
    gss = Path(transform.input_base_dir) / "lpsn_gss.csv"
    # Different source epochs get different files, not an overwritten receipt
    # under an earlier admitted path. Changing anchors here is an explicit
    # fixture rebind before a real run, never part of production verification.
    cohort = _sha(source.read_bytes()) + "-" + _sha(gss.read_bytes())
    directory = Path(transform.output_base_dir) / "fixture-bacdive-join-policy" / cohort
    policy_path = write_inactive_join_policy(source, gss, directory)
    evidence_path = policy_path.parent / "microbedecoder_bacdive_join_evidence.json"
    monkeypatch.setattr(joins, "POLICY_SHA256", _sha(policy_path.read_bytes()))
    monkeypatch.setattr(joins, "EVIDENCE_SHA256", _sha(evidence_path.read_bytes()))
    monkeypatch.setattr(joins, "DECISIONS_SHA256", _sha(_json([]).encode()))
    transform.bacdive_join_policy = policy_path
    if canonical_directory is not None:
        canonical = write_inactive_join_policy(source, gss, canonical_directory)
        assert canonical.read_bytes() == policy_path.read_bytes()
    return policy_path
