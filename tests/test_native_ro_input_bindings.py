"""Read-time role evidence cannot disappear during projection, finalization or admission."""

import copy
import hashlib

import pytest

from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_native_ro_retention import audit_rows, frame, prepare


@pytest.mark.parametrize("role", ["ontology_native_relation_pato", "ontology_native_relation_ro"])
@pytest.mark.parametrize("damage", ["missing", "rebound"])
def test_prepared_native_role_is_required_after_actual_byte_mutation(tmp_path, monkeypatch, role, damage):
    """A changed current receipt is not the immutable snapshot used to interpret native axioms."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    path = transform.input_base_dir / (role.removeprefix("ontology_native_relation_") + ".json")
    payload = path.read_bytes().replace(b'"lbl": "', b'"lbl": "x', 1)
    path.write_bytes(payload)
    if damage == "missing":
        transform._consumed_input_snapshots.pop(role)
    else:
        transform._consumed_input_snapshots[role]["sha256"] = hashlib.sha256(payload).hexdigest()
    rows = frame("pato")
    with pytest.raises(SourceFinalizationRequired, match="binding"):
        authority.project("pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


def _completed(tmp_path, monkeypatch):
    """Write actual helper output and its complete audit as a bounded producer result."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    result = authority.project("pato", rows, rows, "pato_edges.tsv")
    result.to_csv(transform.output_dir / "pato_edges.tsv", sep="\t", index=False)
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    transform.record_producer_audit(native.AUDIT_FILE)
    authority.verify_complete()
    return transform, authority, audit


@pytest.mark.parametrize("role", ["ontology_native_relation_pato", "ontology_native_relation_ro"])
def test_post_run_finalization_requires_original_dynamic_roles(tmp_path, monkeypatch, role):
    """Clearing the transient normalization helper does not clear its evidence requirements."""
    transform, _, _ = _completed(tmp_path, monkeypatch)
    transform._native_relation_authority = None
    transform._consumed_input_snapshots.pop(role)
    with pytest.raises(SourceFinalizationRequired, match="binding"):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize(
    "damage", ["missing_ro", "missing_pato", "rebound", "empty_audit", "missing_edge", "extra_edge"]
)
def test_recorded_admission_joins_audit_roles_and_protected_output(tmp_path, monkeypatch, damage):
    """Use the registered producer's admission hook, independently of live helper state."""
    transform, _, audit = _completed(tmp_path, monkeypatch)
    report = {
        "consumed_inputs": copy.deepcopy(transform.consumed_input_snapshots),
        "producer_native_inputs": transform.producer_native_inputs,
    }
    type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")
    if damage.startswith("missing_") and damage != "missing_edge":
        report["consumed_inputs"].pop("ontology_native_relation_" + damage.removeprefix("missing_"))
    elif damage == "rebound":
        report["consumed_inputs"]["ontology_native_relation_ro"]["sha256"] = "a" * 64
    elif damage == "empty_audit":
        (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue().splitlines()[0] + "\n")
    else:
        path = transform.output_dir / "pato_edges.tsv"
        lines = path.read_text().splitlines(keepends=True)
        path.write_text("".join(lines[:1] + lines[2:] if damage == "missing_edge" else lines + lines[1:2]))
    with pytest.raises(SourceFinalizationRequired):
        type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


def test_idempotent_projection_still_checks_prepared_role_bindings(tmp_path, monkeypatch):
    """Repeated normalization cannot certify native predicates after the witnesses disappear."""
    transform, authority, _ = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    result = authority.project("pato", rows, rows, "pato_edges.tsv")
    transform._consumed_input_snapshots.pop("ontology_native_relation_ro")
    with pytest.raises(SourceFinalizationRequired, match="binding"):
        authority.project("pato", result, result, "pato_edges.tsv")
