"""Reconstruct exclusions from actual retained pre-GO input, not restamped output receipts."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import go_imported_restrictions as restrictions
from kg_microbe.utils import source_finalization
from kg_microbe.utils.go_authority import normalize_go_bundle
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.go_subject_restrictions_fixtures import FULL_POLICY, prepare, rows, write_rows
from tests.test_go_subject_restrictions_public_extension import (
    _canonical,
    _damage_audit,
    _identity,
    _paths,
    _snapshot,
    _stage,
)

pytestmark = pytest.mark.usefixtures("local_source_schema")


def _finite(audit):
    """Select full finite decisions independently of ordinary GO migration events."""
    return [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]


def _original_inputs(report):
    """Identify distinct actual-read roles without inferring their set from surviving audit rows."""
    return {
        role: identity
        for role, identity in report["consumed_inputs"].items()
        if role.startswith(restrictions.ORIGINAL_INPUT_ROLE_PREFIX)
    }


@pytest.mark.parametrize("damage", ["partial", "all", "same_count_qualifier"])
@pytest.mark.parametrize("route", ["public", "fresh_repeat"])
def test_coherent_recorded_receipts_cannot_replace_original_occurrences(tmp_path, monkeypatch, damage, route):
    """Public cold admission and repeat recover the original cohort despite mutually restamped receipts."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, audit, report_path = _paths(transform)
    verify_finalized_source_files(graph)
    inputs_before = {role: Path(identity["path"]).read_bytes() for role, identity in _original_inputs(report).items()}
    assert len(inputs_before) == 1
    inventory = _damage_audit(audit, damage, coherent=True)
    report[restrictions.INVENTORY_KEY] = inventory
    report["summaries"]["go"]["quarantined_imported_subject_restrictions"] = inventory["quarantined_occurrences"]
    report["audit_members"][audit.name] = _identity(audit)
    report_path.write_text(_canonical(report))
    before = _snapshot(transform.output_dir)
    with pytest.raises(SourceFinalizationRequired):
        if route == "public":
            verify_finalized_source_files(graph)
        else:
            Transform("fixture", transform.input_base_dir, transform.output_base_dir).finalize()
    assert _snapshot(transform.output_dir) == before
    assert inputs_before == {
        role: Path(identity["path"]).read_bytes() for role, identity in _original_inputs(report).items()
    }


@pytest.mark.parametrize("damage", ["partial", "all", "same_count_qualifier"])
def test_direct_checkpoint_reuse_rejoins_original_stream(tmp_path, monkeypatch, damage):
    """Even complete audit erasure cannot remove the separately bound original member's cohort."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    normalize_go_bundle([nodes], [edges], authority, audit)
    _damage_audit(audit, damage, coherent=True)
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    with pytest.raises(SourceFinalizationRequired):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())


def test_standalone_scope_cannot_be_recovered_after_all_input_descriptors_are_removed(tmp_path, monkeypatch):
    """Document the direct cold-call trust boundary rather than infer scope from orphaned objects."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    normalize_go_bundle([nodes], [edges], authority, audit)
    snapshots = {path.name: path.read_bytes() for path in (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir()}
    _damage_audit(audit, "all", coherent=True)
    content = rows(audit, quoted=True)
    checkpoint = next(row for row in content if row["record_kind"] == "bundle_checkpoint")
    bundle = json.loads(checkpoint["bundle_fingerprint"])
    bundle[restrictions.INPUTS_KEY] = {}
    checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(audit, content, quoted=True)
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    # No external admitted role set is supplied to this standalone call. Once
    # every descriptor is erased, existing digest objects cannot identify the
    # caller's original member/dialect. This case is not claimed as protected.
    assert normalize_go_bundle([nodes], [edges], authority, audit) == {"already_normalized": 1}
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())
    assert snapshots == {
        path.name: path.read_bytes() for path in (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir()
    }


def test_public_admission_still_owns_original_scope_when_direct_descriptors_are_erased(tmp_path, monkeypatch):
    """The same checkpoint erasure fails when the caller retains its admitted source read roles."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, audit, report_path = _paths(transform)
    original_roles = _original_inputs(report)
    assert original_roles
    inventory = _damage_audit(audit, "all", coherent=True)
    content = rows(audit, quoted=True)
    checkpoint = next(row for row in content if row["record_kind"] == "bundle_checkpoint")
    bundle = json.loads(checkpoint["bundle_fingerprint"])
    bundle[restrictions.INPUTS_KEY] = {}
    checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(audit, content, quoted=True)
    report[restrictions.INVENTORY_KEY] = inventory
    report["summaries"]["go"]["quarantined_imported_subject_restrictions"] = 0
    report["audit_members"][audit.name] = _identity(audit)
    report_path.write_text(_canonical(report))
    assert _original_inputs(report) == original_roles
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(graph)


@pytest.mark.parametrize("size", [0, 1, 2, len(FULL_POLICY["records"])])
def test_actual_subsets_and_truthful_zero_retain_only_required_original_inputs(tmp_path, monkeypatch, size):
    """Twelve native definitions do not require every producer input to contain twelve occurrences."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    original = rows(edges)[:size]
    fields = list(rows(edges)[0])
    write_rows(edges, original, fields=fields)
    source_bytes = edges.read_bytes()
    normalize_go_bundle([nodes], [edges], authority, audit)
    decisions = _finite(audit)
    assert len(decisions) == size
    snapshot_directory = tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY
    if size:
        objects = list(snapshot_directory.iterdir())
        assert len(objects) == 1
        assert objects[0].read_bytes() == source_bytes
        assert objects[0].name == hashlib.sha256(source_bytes).hexdigest() + ".tsv"
        assert [json.loads(row["original_record_json"]) for row in decisions] == original
    else:
        assert not snapshot_directory.exists()
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    assert normalize_go_bundle([nodes], [edges], authority, audit) == {"already_normalized": 1}
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())
    if size:
        assert objects[0].read_bytes() == source_bytes


@pytest.mark.parametrize("quoted", [False, True])
def test_full_member_dialect_and_original_ordinals_survive_exclusion(tmp_path, monkeypatch, quoted):
    """Capture unselected records too; count data records rather than quoted physical lines."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    original = rows(edges)[0]
    original["publications"] = 'literal "quoted" evidence' + ("\nsecond physical line" if quoted else "")
    unrelated = {**original, "subject": "NCBITaxon:1", "object": "CHEBI:64709"}
    before_rows = [unrelated, original, original]
    write_rows(edges, before_rows, quoted=quoted)
    source_bytes = edges.read_bytes()
    normalize_go_bundle([nodes], [edges], authority, audit, quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE)
    decisions = _finite(audit)
    assert len(decisions) == 2
    assert [json.loads(row[restrictions.EVIDENCE_COLUMN])["input_record_ordinal"] for row in decisions] == [2, 3]
    assert [json.loads(row["original_record_json"]) for row in decisions] == [original, original]
    assert rows(edges, quoted=quoted)[0]["publications"] == unrelated["publications"]
    snapshot = next((tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir())
    assert snapshot.read_bytes() == source_bytes
    assert rows(snapshot, quoted=quoted) == before_rows
    for decision in decisions:
        context = json.loads(decision[restrictions.EVIDENCE_COLUMN])
        restrictions.verify_audit_record(decision, context["inputs"])


@pytest.mark.parametrize("damage", ["missing", "changed", "symlink", "foreign_member", "wrong_dialect", "erased_role"])
def test_public_admission_requires_original_input_identity_and_scope(tmp_path, monkeypatch, damage):
    """Native PATO pins and apparently valid audits do not replace the actual original source input."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, _, report_path = _paths(transform)
    role, identity = next(iter(_original_inputs(report).items()))
    snapshot = Path(identity["path"])
    if damage == "missing":
        snapshot.unlink()
    elif damage == "changed":
        content = snapshot.read_bytes()
        assert b"PMID:fixture" in content
        snapshot.write_bytes(content.replace(b"PMID:fixture", b"PMID:changed", 1))
    elif damage == "symlink":
        other = tmp_path / "equal-bytes.tsv"
        snapshot.rename(other)
        snapshot.symlink_to(other)
    elif damage == "erased_role":
        report["consumed_inputs"].pop(role)
    else:
        descriptor = restrictions._original_input_descriptor(role)
        if damage == "foreign_member":
            descriptor["file"] = "foreign_edges.tsv"
        else:
            descriptor["quoting"] = csv.QUOTE_MINIMAL
        replacement = restrictions._original_input_role(descriptor, descriptor["quoting"])
        report["consumed_inputs"][replacement] = report["consumed_inputs"].pop(role)
    report_path.write_text(_canonical(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(graph)


@pytest.mark.parametrize("change", ["same_size_bytes", "equal_bytes_symlink"])
def test_recorded_admission_retains_late_original_input_bindings(tmp_path, monkeypatch, change):
    """The caller's actual retained admission observes snapshot bytes and owned lexical resolution."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    _, _, report_path = _paths(transform)
    admission = SourceAdmission()
    assert (
        source_finalization._verify_recorded_consumed_inputs(report, report_path=report_path, admission=admission)
        is admission
    )
    _, identity = next(iter(_original_inputs(report).items()))
    snapshot = Path(identity["path"])
    if change == "same_size_bytes":
        content = snapshot.read_bytes()
        assert b"PMID:fixture" in content
        changed = content.replace(b"PMID:fixture", b"PMID:changed", 1)
        assert changed != content and len(changed) == len(content)
        snapshot.write_bytes(changed)
    else:
        other = tmp_path / "same-bytes.tsv"
        snapshot.rename(other)
        snapshot.symlink_to(other)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        admission.verify(metadata_only=True)


def test_legacy_active_evidence_is_not_reconstructed_from_rewritten_output(tmp_path, monkeypatch):
    """An old active report requires the original producer rerun, never synthetic input adoption."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    normalize_go_bundle([nodes], [edges], authority, audit)
    content = rows(audit, quoted=True)
    checkpoint = next(row for row in content if row["record_kind"] == "bundle_checkpoint")
    bundle = json.loads(checkpoint["bundle_fingerprint"])
    bundle.pop(restrictions.INPUTS_KEY)
    bundle["authority"]["imported_subject_restriction_runtime_version"] = restrictions.RUNTIME_VERSION - 1
    for row in content:
        if row["record_kind"] == restrictions.AUDIT_KIND:
            context = json.loads(row[restrictions.EVIDENCE_COLUMN])
            context.pop("input_role")
            context["inputs"] = {
                role: identity
                for role, identity in context["inputs"].items()
                if not role.startswith(restrictions.ORIGINAL_INPUT_ROLE_PREFIX)
            }
            row[restrictions.EVIDENCE_COLUMN] = _canonical(context)
    checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(audit, content, quoted=True)
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    snapshots = {path.name: path.read_bytes() for path in (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir()}
    with pytest.raises(SourceFinalizationRequired):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())
    assert snapshots == {
        path.name: path.read_bytes() for path in (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir()
    }


def test_legacy_truthful_zero_needs_no_native_or_original_input_adoption(tmp_path, monkeypatch):
    """A prior empty finite contract may be explicitly reprocessed without inventing a cohort."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    fields = list(rows(edges)[0])
    write_rows(edges, [], fields=fields)
    normalize_go_bundle([nodes], [edges], authority, audit)
    content = rows(audit, quoted=True)
    checkpoint = next(row for row in content if row["record_kind"] == "bundle_checkpoint")
    bundle = json.loads(checkpoint["bundle_fingerprint"])
    bundle.pop(restrictions.INPUTS_KEY)
    bundle["authority"]["imported_subject_restriction_runtime_version"] = restrictions.RUNTIME_VERSION - 1
    bundle[restrictions.INVENTORY_KEY]["version"] = restrictions.RUNTIME_VERSION - 1
    checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(audit, content, quoted=True)
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert not _finite(audit)
    assert not (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).exists()


@pytest.mark.parametrize("kind", ["conflicting_object", "symlinked_object", "symlinked_directory"])
def test_original_capture_never_overwrites_or_follows_owned_symlinks(tmp_path, monkeypatch, kind):
    """A cache collision refuses before graph/audit publication and preserves the unrelated target."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    source_bytes = edges.read_bytes()
    directory = tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    target = unrelated / "keep.tsv"
    target.write_bytes(b"preserve this unrelated input\n")
    if kind == "symlinked_directory":
        directory.symlink_to(unrelated, target_is_directory=True)
    else:
        directory.mkdir()
        destination = directory / (hashlib.sha256(source_bytes).hexdigest() + ".tsv")
        if kind == "symlinked_object":
            destination.symlink_to(target)
        else:
            destination.write_bytes(b"wrong bytes under original digest\n")
    before = nodes.read_bytes(), edges.read_bytes(), target.read_bytes()
    with pytest.raises((ValueError, OSError)):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes(), target.read_bytes())
    assert not audit.exists()


def test_equal_existing_original_object_is_verified_without_replacement(tmp_path, monkeypatch):
    """A genuine digest-addressed object can be reused without overwriting its bytes or inode."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    content = edges.read_bytes()
    directory = tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY
    directory.mkdir()
    snapshot = directory / (hashlib.sha256(content).hexdigest() + ".tsv")
    snapshot.write_bytes(content)
    before = snapshot.stat()
    normalize_go_bundle([nodes], [edges], authority, audit)
    after = snapshot.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    assert snapshot.read_bytes() == content
    assert len(_finite(audit)) == 2


@pytest.mark.parametrize("damage", ["duplicate_header", "extra_column", "missing_column"])
def test_malformed_original_input_refuses_before_any_output(tmp_path, monkeypatch, damage):
    """Malformed producer rows cannot become a trusted retained occurrence stream."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    lines = edges.read_text().splitlines()
    if damage == "duplicate_header":
        fields = lines[0].split("\t")
        fields[-1] = fields[0]
        lines[0] = "\t".join(fields)
    elif damage == "extra_column":
        lines[-1] += "\textra"
    else:
        lines[-1] = lines[-1].rsplit("\t", 1)[0]
    edges.write_text("\n".join(lines) + "\n")
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()
    assert not (tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).exists()


def test_source_mutation_between_inspection_and_capture_is_not_adopted(tmp_path, monkeypatch):
    """The original pre-inspection byte identity, not a later source epoch, owns the input object."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    old_node = nodes.read_bytes()
    original = restrictions._retain_original_input

    def change_before_copy(source, expected_digest, directory):
        """Inject a narrow race after initial inspection but before the actual snapshot copy."""
        source.write_bytes(source.read_bytes() + b"\n")
        return original(source, expected_digest, directory)

    monkeypatch.setattr(restrictions, "_retain_original_input", change_before_copy)
    with pytest.raises(ValueError, match="changed before snapshot capture"):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert nodes.read_bytes() == old_node
    assert not audit.exists()
    assert not list((tmp_path / restrictions.ORIGINAL_INPUT_DIRECTORY).iterdir())


def test_multiple_original_members_cannot_lose_one_whole_member_in_audit(tmp_path, monkeypatch):
    """All admitted source-input roles participate even if none of one member's audit rows remain."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    originals = rows(edges)
    second = tmp_path / "second_edges.tsv"
    write_rows(edges, originals[:1])
    write_rows(second, originals[1:])
    normalize_go_bundle([nodes], [edges, second], authority, audit)
    content = rows(audit, quoted=True)
    decisions = _finite(audit)
    inputs = json.loads(decisions[0][restrictions.EVIDENCE_COLUMN])["inputs"]
    assert len([role for role in inputs if role.startswith(restrictions.ORIGINAL_INPUT_ROLE_PREFIX)]) == 2
    retained = [
        row
        for row in content
        if not (row["record_kind"] == restrictions.AUDIT_KIND and row["source_file"] == second.name)
    ]
    digest = hashlib.sha256()
    for row in retained:
        if row["record_kind"] == restrictions.AUDIT_KIND:
            digest.update((_canonical(row) + "\n").encode())
    checkpoint = next(row for row in retained if row["record_kind"] == "bundle_checkpoint")
    bundle = json.loads(checkpoint["bundle_fingerprint"])
    bundle[restrictions.INVENTORY_KEY] = {
        "version": restrictions.RUNTIME_VERSION,
        "quarantined_occurrences": 1,
        "records_sha256": digest.hexdigest(),
    }
    checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(audit, retained, quoted=True)
    with pytest.raises(SourceFinalizationRequired, match="original input occurrences"):
        restrictions.audit_inventory([audit], inputs)
