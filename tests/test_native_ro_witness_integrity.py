"""Challenge cached native interpretations and full witness admission, not just edge keys."""

import csv
import json

import pytest

from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_native_ro_retention import audit_rows, frame, prepare


@pytest.mark.parametrize("kind", ["native_assertion", "native_property"])
def test_cached_native_witness_drift_is_refused_before_first_projection(tmp_path, monkeypatch, kind):
    """Refuse later parsed interpretations before publishing their alleged native witnesses."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    if kind == "native_assertion":
        key = next(key for key in authority._native["pato"] if key[1] == "RO:0002492")
        authority._native["pato"][key]["obj"] = "http://purl.obolibrary.org/obo/UBERON_9999999"
    else:
        authority._ro[0]["RO:0002492"]["meta"]["definition"]["val"] = "A changed, unreviewed existence definition."
    rows = frame("pato")
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.project("pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


@pytest.mark.parametrize("field", ["native_assertion_json", "ro_declaration_json"])
def test_full_native_audit_witness_is_semantically_rejoined_at_admission(tmp_path, monkeypatch, field):
    """Rejoin complete audited native records, independently of generic file-integrity checks."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    retained = authority.project("pato", rows, rows, "pato_edges.tsv")
    authority.verify_complete()
    retained.to_csv(transform.output_dir / "pato_edges.tsv", sep="\t", index=False)
    records = audit_rows(audit)
    target = next(row for row in records if json.loads(row["retained_row_json"])["relation"] == "RO:0002492")
    target[field] = json.dumps({"not_the_pinned_native_witness": True})
    with (transform.output_dir / native.AUDIT_FILE).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=native.AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        native.verify_audit_input_bindings(transform.output_dir, transform.consumed_input_snapshots)


@pytest.mark.parametrize("damage", ["prior_object", "input_subject", "retained_metadata", "source_file", "action"])
def test_full_audit_projection_fields_cannot_disagree_with_original_or_emitted_row(tmp_path, monkeypatch, damage):
    """Check complete original/prior/retained field relationships and the emitted graph."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    retained = authority.project("pato", rows, rows, "pato_edges.tsv")
    authority.verify_complete()
    retained.to_csv(transform.output_dir / "pato_edges.tsv", sep="\t", index=False)
    records = audit_rows(audit)
    target = next(row for row in records if json.loads(row["retained_row_json"])["relation"] == "RO:0002492")
    if damage == "prior_object":
        value = json.loads(target["canonical_prior_row_json"])
        value["object"] = "UBERON:9999999"
        target["canonical_prior_row_json"] = json.dumps(value)
    elif damage == "input_subject":
        value = json.loads(target["normalization_input_row_json"])
        value["subject"] = "PATO:9999999"
        target["normalization_input_row_json"] = json.dumps(value)
    elif damage == "retained_metadata":
        value = json.loads(target["retained_row_json"])
        value["knowledge_level"] = "unreviewed_changed_evidence"
        target["retained_row_json"] = json.dumps(value)
    elif damage == "source_file":
        target["source_file"] = "unrelated_edges.tsv"
    else:
        target["projection_action"] = "invented_passing_disposition"
    with (transform.output_dir / native.AUDIT_FILE).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=native.AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        native.verify_audit_input_bindings(transform.output_dir, transform.consumed_input_snapshots)
