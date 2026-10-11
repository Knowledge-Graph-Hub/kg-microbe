"""Native RO audit verification is scoped to a record's members, not the shared ontologies directory."""

import csv
import hashlib

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_native_ro_retention import POLICY


def _shared_directory(tmp_path):
    """Build a scoped run's header-only audit beside a prior full build's protected supplier control row."""
    directory = tmp_path / "ontologies"
    directory.mkdir()
    with (directory / native.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerow(native.AUDIT_FIELDS)
    control = POLICY["unchanged_records"][0]
    supplier = control["ontology"]
    (directory / f"{supplier}_edges.tsv").write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        f"{control['subject']}\t{control['prior_predicate']}\t{control['object']}\t"
        f"{control['relation']}\tinfores:{supplier}\n",
        encoding="utf-8",
    )
    policy = native.POLICY_FILE.resolve()
    snapshots = {native.POLICY_ROLE: {"path": str(policy), "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}}
    return directory, snapshots, f"{supplier}_edges.tsv"


def test_unselected_supplier_file_in_shared_directory_is_outside_the_record(tmp_path):
    """A scoped `-s ec` record does not answer for a prior full build's supplier rows."""
    directory, snapshots, _ = _shared_directory(tmp_path)
    native.verify_audit_input_bindings(directory, snapshots, members=("ec_nodes.tsv", "ec_edges.tsv"))


def test_member_supplier_file_still_requires_its_native_authority(tmp_path):
    """An empty audit can never admit protected rows that the record itself publishes."""
    directory, snapshots, supplier_edges = _shared_directory(tmp_path)
    with pytest.raises(SourceFinalizationRequired, match="control lost its prior projection"):
        native.verify_audit_input_bindings(directory, snapshots, members=("ec_edges.tsv", supplier_edges))
    with pytest.raises(SourceFinalizationRequired, match="control lost its prior projection"):
        native.verify_audit_input_bindings(directory, snapshots)


def test_transform_scopes_shared_directory_verification_to_bound_members(tmp_path, monkeypatch):
    """Finalization binds the record's members before verifying against the shared directory."""
    seen = []
    monkeypatch.setattr(native, "verify_audit_input_bindings", lambda *args, **kwargs: seen.append(kwargs))
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.output_dir = tmp_path
    transform._consumed_input_snapshots = {}
    transform._producer_audit_snapshots = {native.AUDIT_FILE: {}}
    transform.bind_finalization_members(["ec_edges.tsv", "ec_nodes.tsv"])
    transform.verify_native_inputs()
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "ec_edges.tsv").write_text("")
    (staging / "ec_nodes.tsv").write_text("")
    transform.verify_native_inputs(output_dir=staging)
    assert [call["members"] for call in seen] == [("ec_edges.tsv", "ec_nodes.tsv")] * 2
