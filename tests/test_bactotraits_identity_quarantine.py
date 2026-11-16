"""Finite mixed-strain disposition blocks emission and survives producer admission."""

import csv
import hashlib
import json
import shutil
from copy import deepcopy

import pytest

from kg_microbe.transform_utils.bactotraits import bactotraits as bacto
from kg_microbe.transform_utils.bactotraits.identity_quarantine import (
    AUDIT_FIELDS,
    AUDIT_FILE,
    DEFAULT_POLICY,
    POLICY_ROLE,
    SOURCE_ROLE,
    IdentityQuarantine,
)
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.bactotraits_identity_fixtures import FIXTURES, fixture_policy, write_fixture_policy
from tests.test_consumed_inputs import _bacto, _rows


@pytest.fixture
def producer(tmp_path, monkeypatch):
    """Run the real emitter against two immutable synthetic rows and a reviewed fixture policy."""
    result = _bacto(tmp_path, monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    result.input_base_dir = raw
    shutil.copyfile(FIXTURES / "source.csv", raw / "source.csv")
    result.IDENTITY_QUARANTINE_POLICY = write_fixture_policy(raw / "source.csv", raw / "policy.json")
    lookup = tmp_path / "bacdive/lookup.tsv"
    lookup.parent.mkdir(exist_ok=True)
    shutil.copyfile(FIXTURES / "lookup.tsv", lookup.parent / "bacdive.tsv")
    return result


def test_exact_reviewed_row_withheld_and_control_retained_with_original_audit(producer):
    """The mixed row supplies no nodes/edges and no replacement taxon; the control is emitted."""
    producer.run(data_file="source.csv", show_status=False)
    edges = _rows(producer.output_edge_file)
    assert edges and {row["subject"] for row in edges} == {"NCBITaxon:1"}
    assert "NCBITaxon:1123071" not in {row["id"] for row in _rows(producer.output_node_file)}
    audit = _rows(producer.output_dir / AUDIT_FILE)
    assert len(audit) == 1
    row = audit[0]
    assert row["bacdive_id"] == "17851" and row["ncbitaxon_id"] == "NCBITaxon:1123071"
    assert row["culture_collection_codes"] == "DSM 19353, JCM 14586"
    assert row["disposition"] == "quarantine_mixed_strain_row"
    assert json.loads(row["raw_row_json"])["Trait"] == "1"
    assert row["source_sha256"] == producer.consumed_input_snapshots[SOURCE_ROLE]["sha256"]
    assert row["policy_sha256"] == producer.consumed_input_snapshots[POLICY_ROLE]["sha256"]
    verify_producer_audits(producer)
    producer.verify_consumed_inputs()


def test_bounded_slice_uses_same_policy_and_records_actual_ordinal(producer):
    """Reviewed row identity survives an isolated slice without repinning the disposition."""
    source = producer.input_base_dir / "source.csv"
    original = source.read_bytes()
    source.write_bytes(b"\n".join(original.splitlines()[:4]) + b"\n")
    producer.run(data_file="source.csv", show_status=False)
    assert _rows(producer.output_edge_file) == []
    row = _rows(producer.output_dir / AUDIT_FILE)[0]
    assert row["source_sha256"] != row["reviewed_source_sha256"]
    assert row["reviewed_source_sha256"] == hashlib.sha256(original).hexdigest()
    assert row["source_data_row"] == "1"


@pytest.mark.parametrize("damage", ["changed_trait", "missing", "duplicate", "duplicate_header", "short_row"])
def test_source_drift_rejected_before_existing_outputs_are_opened(producer, damage):
    """Reject changed reviewed records without truncating previously produced graphs."""
    path = producer.input_base_dir / "source.csv"
    lines = path.read_text().splitlines()
    if damage == "changed_trait":
        lines[3] = lines[3][:-1] + "0"
    elif damage == "missing":
        del lines[3]
    elif damage == "duplicate":
        lines.append(lines[3])
    elif damage == "duplicate_header":
        lines[2] += ";Trait"
    else:
        lines[3] = "1;17851"
    path.write_text("\n".join(lines) + "\n")
    producer.output_edge_file.write_bytes(b"previous edges")
    producer.output_node_file.write_bytes(b"previous nodes")
    with pytest.raises(ValueError, match="BactoTraits identity quarantine"):
        producer.run(data_file="source.csv", show_status=False)
    assert producer.output_edge_file.read_bytes() == b"previous edges"
    assert producer.output_node_file.read_bytes() == b"previous nodes"
    assert not (producer.output_dir / AUDIT_FILE).exists()


@pytest.mark.parametrize("damage", ["changed", "missing", "duplicate"])
def test_lookup_drift_does_not_reassign_reviewed_row(producer, tmp_path, damage):
    """The original reviewed mapping is checked before emission rather than silently replaced."""
    path = tmp_path / "bacdive/bacdive.tsv"
    text = path.read_text()
    if damage == "changed":
        text = text.replace("NCBITaxon:1123071", "NCBITaxon:571898")
    elif damage == "missing":
        text = "\n".join(line for line in text.splitlines() if "17851" not in line) + "\n"
    else:
        text += next(line for line in text.splitlines() if "17851" in line) + "\n"
    path.write_text(text)
    with pytest.raises(ValueError, match="(mapping changed or is missing|duplicate reviewed BacDive mapping)"):
        producer.run(data_file="source.csv", show_status=False)
    assert not producer.output_edge_file.exists()


@pytest.mark.parametrize("damage", ["duplicate_selector", "bad_hash", "replacement", "extra_field", "empty_reason"])
def test_invalid_policies_fail_without_a_permissive_fallback(damage):
    """A finite disposition must preserve its closed schema and evidence contract."""
    policy = fixture_policy(FIXTURES / "source.csv")
    decision = policy["decisions"][0]
    if damage == "duplicate_selector":
        policy["decisions"].append(deepcopy(decision))
    elif damage == "bad_hash":
        decision["row_sha256"] = "missing"
    elif damage == "replacement":
        decision["disposition"] = "replace_taxon"
    elif damage == "extra_field":
        decision["replacement_taxon"] = "NCBITaxon:571898"
    else:
        decision["rationale"] = " "
    with pytest.raises(ValueError, match="BactoTraits identity quarantine"):
        IdentityQuarantine(json.dumps(policy))


def test_duplicate_json_keys_rejected():
    """No last-key-wins policy rewrite may erase a reviewed disposition."""
    text = json.dumps(fixture_policy(FIXTURES / "source.csv"))
    text = text.replace('"decisions":', '"decisions": [], "decisions":')
    with pytest.raises(ValueError, match="duplicate policy JSON key"):
        IdentityQuarantine(text)


def test_empty_review_cohort_emits_header_and_is_recorded(producer):
    """An explicit empty fixture policy still produces mandatory auditable bytes."""
    write_fixture_policy(producer.input_base_dir / "source.csv", producer.IDENTITY_QUARANTINE_POLICY, reviewed=False)
    producer.run(data_file="source.csv", show_status=False)
    audit = producer.output_dir / AUDIT_FILE
    with audit.open() as stream:
        assert next(csv.reader(stream, delimiter="\t")) == list(AUDIT_FIELDS)
    assert _rows(audit) == []
    assert len({row["subject"] for row in _rows(producer.output_edge_file)}) == 2
    verify_producer_audits(producer)


@pytest.mark.parametrize("damage", ["source", "policy", "audit"])
def test_post_emission_mutation_cannot_be_certified(producer, damage):
    """Original consumed and produced byte identities survive subsequent verification."""
    producer.run(data_file="source.csv", show_status=False)
    paths = {
        "source": producer.input_base_dir / "source.csv",
        "policy": producer.IDENTITY_QUARANTINE_POLICY,
        "audit": producer.output_dir / AUDIT_FILE,
    }
    paths[damage].write_bytes(b"changed")
    with pytest.raises(SourceFinalizationRequired):
        if damage == "audit":
            verify_producer_audits(producer)
        else:
            producer.verify_consumed_inputs()


def test_shipped_policy_has_only_the_reviewed_row_and_declared_input():
    """The production disposition stays one reviewed row, not an inferred bulk detector."""
    policy = IdentityQuarantine(DEFAULT_POLICY.read_text())
    assert set(policy.decisions) == {"17851"}
    assert policy.decisions["17851"]["row_sha256"] == "345fd2d00ee93334d975085716692dd4d4c530d5529f04c5b07af0766d5a512a"
    assert AUDIT_FILE in bacto.BactoTraitsTransform.REQUIRED_AUDIT_FILES
    assert {POLICY_ROLE, SOURCE_ROLE} <= set(bacto.BactoTraitsTransform.REQUIRED_CONSUMED_INPUTS)
