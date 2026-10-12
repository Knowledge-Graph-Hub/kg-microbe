"""Finite native class restrictions are not transferred to broader GO replacement subjects."""

import copy
import csv
import hashlib
import io
import json
import os
import sqlite3
from collections import Counter

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import go_imported_restrictions as restrictions
from kg_microbe.utils.go_authority import _authority_fingerprint, normalize_go_bundle
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.go_subject_restrictions_fixtures import FULL_POLICY, POLICY, prepare, rows, write_rows


def quarantines(audit):
    """Select only the exact finite source-axiom quarantine, not ordinary GO migration events."""
    return [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]


def test_both_native_restrictions_are_losslessly_quarantined(tmp_path, monkeypatch):
    """Preserve exact input/candidate/native quantifiers and every source qualifier."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    before = rows(edges)
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert rows(edges) == []
    assert result["quarantined_imported_subject_restrictions"] == 2
    decisions = quarantines(audit)
    assert [json.loads(row["original_record_json"]) for row in decisions] == before
    for decision in decisions:
        context = json.loads(decision[restrictions.EVIDENCE_COLUMN])
        assert "owl:someValuesFrom" in context["native_class_xml"]
        assert "owl:equivalentClass" in context["native_class_xml"]
        assert context["input_member"]["file"] == edges.name
        assert context["input_record_ordinal"] in (1, 2)
        restrictions.verify_audit_record(decision, context["inputs"])
    assert len({json.loads(row["candidate_record_json"])["object"] for row in decisions}) == 2


def test_already_normalized_history_is_quarantined_and_original_input_preserved(tmp_path, monkeypatch):
    """The fix also applies to old source outputs; it does not pretend normalized rows were native."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    identity = {"path": authority.authority_path, "sha256": authority.authority_sha256}
    normalized = [
        restrictions.expected_candidate(row, row["subject"], "native_subject", identity) for row in rows(edges)
    ]
    write_rows(edges, normalized)
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert rows(edges) == []
    assert [json.loads(row["original_record_json"]) for row in quarantines(audit)] == normalized
    assert {json.loads(row[restrictions.EVIDENCE_COLUMN])["input_style"] for row in quarantines(audit)} == {
        "previously_normalized"
    }


@pytest.mark.parametrize(
    "damage",
    [
        "missing_history",
        "missing_original",
        "wrong_original",
        "wrong_hash",
        "wrong_path",
        "wrong_chain",
        "duplicate_history",
    ],
)
def test_forged_normalized_context_fails_before_graph_writes(tmp_path, monkeypatch, damage):
    """An exact broad-class shadow cannot silently stand in for a verified historical restriction."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    row = rows(edges)[0]
    row = restrictions.expected_candidate(
        row, row["subject"], "native_subject", {"path": authority.authority_path, "sha256": authority.authority_sha256}
    )
    history = json.loads(row["go_reference_context"])
    if damage == "missing_history":
        row["go_reference_context"] = ""
    elif damage == "missing_original":
        row["original_subject"] = ""
    elif damage == "wrong_original":
        row["original_subject"] = "GO:0043603"
    else:
        if damage == "wrong_hash":
            history[0]["authority_sha256"] = "a" * 64
        elif damage == "wrong_path":
            history[0]["authority"] = "wrong/go.db"
        elif damage == "wrong_chain":
            history[0]["replacement_chain"] = ["GO:0006082", "GO:0043603", "GO:0008152"]
        else:
            history.append(copy.deepcopy(history[0]))
        row["go_reference_context"] = json.dumps(history)
    write_rows(edges, [row])
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="history"):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()


def test_duplicate_source_occurrences_keep_separate_audit_evidence(tmp_path, monkeypatch):
    """Do not collapse repeated native claims merely because every other field is identical."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    original = rows(edges)
    write_rows(edges, original + original[:1])
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert result["quarantined_imported_subject_restrictions"] == 3
    assert len(quarantines(audit)) == 3
    assert Counter(json.loads(row["original_record_json"])["subject"] for row in quarantines(audit)) == {
        "GO:0006082": 2,
        "GO:0043603": 1,
    }


def test_unrelated_relations_suppliers_fillers_and_object_observations_remain(tmp_path, monkeypatch):
    """Limit the correction to two assertions; do not block ordinary reference migration."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    original = rows(edges)[0]
    controls = [
        {**original, "source_record": "other-supplier", "primary_knowledge_source": "infores:other"},
        {**original, "source_record": "other-filler", "object": "CHEBI:999999"},
        {**original, "source_record": "other-relation", "relation": "RO:0000057"},
        {**original, "source_record": "live-restriction", "subject": "GO:0008152", "object": "CHEBI:999999"},
        {
            **original,
            "source_record": "organism-observation",
            "subject": "NCBITaxon:1",
            "object": "GO:0006082",
            "relation": "fixture:observed",
        },
        {
            **original,
            "source_record": "assay-observation",
            "subject": "assay:1",
            "object": "GO:0043603",
            "relation": "fixture:observed",
        },
    ]
    write_rows(edges, controls)
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert "quarantined_imported_subject_restrictions" not in result
    after = {row["source_record"]: row for row in rows(edges)}
    assert set(after) == {row["source_record"] for row in controls}
    for row in controls:
        actual = after[row["source_record"]]
        assert all(actual[field] == value for field, value in row.items() if field not in {"subject", "object"})
    assert after["organism-observation"]["object"] == after["assay-observation"]["object"] == "GO:0008152"


def test_policy_is_not_self_authenticating():
    """Restamping an inner native class digest does not authorize another scientific disposition."""
    assert restrictions.load_policy(io.StringIO(json.dumps(FULL_POLICY))) == FULL_POLICY
    policy = copy.deepcopy(FULL_POLICY)
    policy["records"][0]["native_class_xml"] = "invented"
    policy["records"][0]["native_class_sha256"] = hashlib.sha256(b"invented").hexdigest()
    with pytest.raises(ValueError, match="Unreviewed"):
        restrictions.load_policy(io.StringIO(json.dumps(policy)))


@pytest.mark.parametrize("filename", ["pato.owl", "go.db"])
def test_native_input_drift_is_not_a_silent_quarantine(tmp_path, monkeypatch, filename):
    """Changed selected native bytes stop disposition instead of accepting stale proof."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    path = raw / filename
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="authority|database"):
        normalize_go_bundle([nodes], [edges], authority, audit)


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_go_release_file_drift_is_refused(tmp_path, monkeypatch, damage):
    """The go.owl release behind the locally built database is bound, not the database bytes (#1420)."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    if damage == "changed":
        (raw / "go.owl").write_bytes((raw / "go.owl").read_bytes() + b"<!-- another release -->\n")
    else:
        (raw / "go.owl").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        normalize_go_bundle([nodes], [edges], authority, audit)


def test_a_database_of_another_go_release_is_refused(tmp_path, monkeypatch):
    """A rebuilt database must still record the reviewed GO release."""
    raw, nodes, edges, audit, _ = prepare(tmp_path, monkeypatch)
    with sqlite3.connect(raw / "go.db") as connection:
        connection.execute(
            "UPDATE statements SET value='2099-01-01' WHERE subject='obo:go.owl' AND predicate='owl:versionInfo'"
        )
    from kg_microbe.utils.go_authority import load_go_authority

    with pytest.raises(ValueError, match="reviewed GO release"):
        normalize_go_bundle([nodes], [edges], load_go_authority(raw), audit)


def test_old_checkpoint_rechecks_policy_and_preserves_original_audits(tmp_path, monkeypatch):
    """A legacy v2 authority fingerprint is invalidated without discarding its original rows."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    original = rows(edges)[0]
    checkpoint = {
        "version": 2,
        "authority": _authority_fingerprint(authority),
        "bundle": [
            {"kind": kind, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for kind, path in (("nodes", nodes), ("edges", edges))
        ],
    }
    checkpoint["authority"].pop("imported_subject_restriction_policy_version")
    checkpoint["authority"].pop("imported_subject_restriction_policy_sha256")
    checkpoint["authority"].pop("imported_subject_restriction_runtime_version")
    from kg_microbe.utils.go_authority import _REPORT_FIELDS

    previous = {field: "" for field in _REPORT_FIELDS}
    previous.update({"record_kind": "edge", "original_record_json": json.dumps(original), "source_file": edges.name})
    end = {field: "" for field in _REPORT_FIELDS}
    end.update({"record_kind": "bundle_checkpoint", "bundle_fingerprint": json.dumps(checkpoint)})
    write_rows(audit, [previous, end], quoted=True)
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert previous in rows(audit, quoted=True)
    assert len(quarantines(audit)) == 2
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    assert normalize_go_bundle([nodes], [edges], authority, audit) == {"already_normalized": 1}
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())


@pytest.mark.parametrize(
    "role", [restrictions.POLICY_ROLE, restrictions.OWL_ROLE, restrictions.GO_ROLE, restrictions.GO_SOURCE_ROLE]
)
def test_original_consumed_bindings_cannot_be_removed(tmp_path, monkeypatch, role):
    """The live helper retains the original roles independently of mutable receipts."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    guard = restrictions.ImportedGoRestrictionGuard(authority, consume_input=transform.consume_input)
    normalize_go_bundle([nodes], [edges], authority, audit, restriction_guard=guard)
    transform._consumed_input_snapshots.pop(role)
    with pytest.raises(SourceFinalizationRequired, match="binding"):
        guard.verify_bindings(transform.consumed_input_snapshots)
    with pytest.raises(SourceFinalizationRequired):
        restrictions.verify_audit_record(quarantines(audit)[0], transform.consumed_input_snapshots)


@pytest.mark.usefixtures("local_source_schema")
def test_real_source_finalization_preserves_mandatory_evidence_and_repeat_bytes(tmp_path, monkeypatch):
    """Exercise staged publication and actual public recorded admission for the nonempty cohort."""
    raw, nodes, edges, _, _ = prepare(tmp_path, monkeypatch)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    write_rows(
        transform.output_node_file,
        rows(nodes)
        + [
            {
                "id": record["object"],
                "category": "biolink:ChemicalEntity",
                "name": record["object"],
                "provided_by": "infores:pato",
            }
            for record in POLICY["records"]
        ],
    )
    write_rows(transform.output_edge_file, rows(edges))
    report = transform.finalize(fresh_run=True)
    assert report["summaries"]["go"]["quarantined_imported_subject_restrictions"] == 2
    assert {restrictions.POLICY_ROLE, restrictions.GO_ROLE, restrictions.OWL_ROLE} <= report["consumed_inputs"].keys()
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    transform.finalize()
    assert before == {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize(
    "damage", ["class", "candidate", "native_digest", "original_subject", "ordinal", "member", "role"]
)
def test_audit_evidence_tampering_refused(tmp_path, monkeypatch, damage):
    """A restamped outer audit does not authorize a changed finite scientific witness."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    normalize_go_bundle([nodes], [edges], authority, audit)
    record = quarantines(audit)[0]
    context = json.loads(record[restrictions.EVIDENCE_COLUMN])
    snapshots = copy.deepcopy(context["inputs"])
    if damage == "class":
        context["native_class_xml"] = context["native_class_xml"].replace("someValuesFrom", "allValuesFrom")
    elif damage == "candidate":
        candidate = json.loads(record["candidate_record_json"])
        candidate["publications"] = "PMID:invented"
        record["candidate_record_json"] = json.dumps(candidate)
    elif damage == "native_digest":
        context["native_class_sha256"] = "b" * 64
    elif damage == "original_subject":
        context["original_subject"] = "GO:0043603"
    elif damage == "ordinal":
        context["input_record_ordinal"] = True
    elif damage == "member":
        context["input_member"]["file"] = "foreign_edges.tsv"
    else:
        context["inputs"].pop(restrictions.OWL_ROLE)
    record[restrictions.EVIDENCE_COLUMN] = json.dumps(context)
    with pytest.raises(SourceFinalizationRequired, match="quarantine evidence"):
        restrictions.verify_audit_record(record, snapshots)


def test_active_shadow_cannot_be_hidden_by_omitting_audit_and_roles(tmp_path, monkeypatch):
    """Recorded admission examines actual active graph bytes, not only mutable reports."""
    _, _, edges, _, authority = prepare(tmp_path, monkeypatch)
    row = rows(edges)[0]
    normalized = restrictions.expected_candidate(
        row,
        row["subject"],
        "native_subject",
        {
            "path": authority.authority_path,
            "sha256": authority.authority_sha256,
        },
    )
    write_rows(edges, [normalized])
    report = {"members": {edges.name: {}}, "audit_members": {}, "consumed_inputs": {}}
    with pytest.raises(SourceFinalizationRequired, match="remains"):
        restrictions.verify_recorded_restriction_inputs(report, tmp_path / "source_finalization.json")


def test_duplicate_audit_occurrence_cannot_inflate_quarantine_count(tmp_path, monkeypatch):
    """Different native occurrences are preserved, while one repeated receipt is refused."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    normalize_go_bundle([nodes], [edges], authority, audit)
    decision = quarantines(audit)[0]
    write_rows(audit, [decision, decision], quoted=True)
    report = {
        "audit_members": {audit.name: {}},
        "consumed_inputs": json.loads(decision[restrictions.EVIDENCE_COLUMN])["inputs"],
    }
    with pytest.raises(SourceFinalizationRequired, match="Duplicate"):
        restrictions.verify_recorded_restriction_inputs(report, tmp_path / "source_finalization.json")


def test_late_same_size_native_drift_is_detected_before_publish(tmp_path, monkeypatch):
    """Matching timestamps and lengths never substitute for actual interpreted input bytes."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    guard = restrictions.ImportedGoRestrictionGuard(authority)
    guard.prepare()
    path = raw / "pato.owl"
    before_stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"organic acid", b"organic fake", 1))
    os.utime(path, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    assert path.stat().st_size == before_stat.st_size
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="changed during"):
        normalize_go_bundle([nodes], [edges], authority, audit, restriction_guard=guard)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()


def test_unrelated_observations_do_not_load_finite_native_evidence(tmp_path, monkeypatch):
    """The additional native dependency belongs only to the two protected imported axioms."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    write_rows(edges, [{**rows(edges)[0], "subject": "NCBITaxon:1", "object": "GO:0006082"}])
    (raw / "pato.owl").unlink()
    restrictions.POLICY_FILE.unlink()
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert rows(edges)[0]["object"] == "GO:0008152"


@pytest.mark.parametrize("table", ["edge", "entailed_edge"])
def test_new_authority_support_requires_review_not_automatic_quarantine(tmp_path, monkeypatch, table):
    """
    A rebuilt database of the reviewed release cannot contradict the finite disposition premise.

    The database bytes are not pinned (#1420), so new support reaches the content check directly.
    """
    raw, nodes, edges, audit, _ = prepare(tmp_path, monkeypatch)
    with sqlite3.connect(raw / "go.db") as connection:
        connection.execute(f"INSERT INTO {table} VALUES(?,?,?)", ("GO:0008152", "RO:0004007", "CHEBI:64709"))
    from kg_microbe.utils.go_authority import load_go_authority

    authority = load_go_authority(raw)
    with pytest.raises(ValueError, match="authority support"):
        normalize_go_bundle([nodes], [edges], authority, audit)


def test_new_real_run_resets_guard_then_reads_new_snapshots(tmp_path, monkeypatch):
    """A new input epoch must neither reuse an old guard nor inherit old consumption receipts."""
    raw, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    originals = rows(edges)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    first = restrictions.ImportedGoRestrictionGuard(authority, consume_input=transform.consume_input)
    transform._go_imported_restriction_guard = first
    normalize_go_bundle([nodes], [edges], authority, audit, restriction_guard=first)
    assert first.identities
    transform.begin_consumed_inputs()
    assert transform._go_imported_restriction_guard is None
    assert transform.consumed_input_snapshots == {}
    write_rows(edges, originals)
    second = restrictions.ImportedGoRestrictionGuard(authority, consume_input=transform.consume_input)
    transform._go_imported_restriction_guard = second
    result = normalize_go_bundle([nodes], [edges], authority, audit, restriction_guard=second)
    assert result["quarantined_imported_subject_restrictions"] == 2
    assert second.identities == first.identities
    assert second is not first
    second.verify_bindings(transform.consumed_input_snapshots)


@pytest.mark.parametrize("identifier", ["GO:0006082", "GO:0043603"])
@pytest.mark.parametrize("column", ["subject", "object", "relation"])
def test_canonical_native_iri_spellings_preserve_literal_original(tmp_path, monkeypatch, identifier, column):
    """Canonical OBO spellings identify the same finite axiom without changing its source payload."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    row = next(row for row in rows(edges) if row["subject"] == identifier)
    row[column] = "http://purl.obolibrary.org/obo/" + row[column].replace(":", "_")
    write_rows(edges, [row])
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert not rows(edges)
    decision = quarantines(audit)[0]
    assert json.loads(decision["original_record_json"]) == row
    restrictions.verify_audit_record(decision, json.loads(decision[restrictions.EVIDENCE_COLUMN])["inputs"])


@pytest.mark.parametrize("shadow_iri", [False, True])
def test_historical_iri_context_remains_literal_and_verifiable(tmp_path, monkeypatch, shadow_iri):
    """Previously normalized native IRIs retain their actual historical subject and chain."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    row = rows(edges)[0]
    original = row["subject"]
    row["subject"] = "http://purl.obolibrary.org/obo/" + original.replace(":", "_")
    row = restrictions.expected_candidate(
        row,
        original,
        "native_subject",
        {
            "path": authority.authority_path,
            "sha256": authority.authority_sha256,
        },
    )
    if shadow_iri:
        row["subject"] = "http://purl.obolibrary.org/obo/GO_0008152"
    write_rows(edges, [row])
    normalize_go_bundle([nodes], [edges], authority, audit)
    assert not rows(edges)
    assert json.loads(quarantines(audit)[0]["original_record_json"]) == row


@pytest.mark.parametrize("damage", ["quantifier", "original_binding"])
def test_prepared_native_semantics_and_bindings_cannot_be_mutated(tmp_path, monkeypatch, damage):
    """Rehashing a mutable inner witness cannot replace the independently pinned interpretation."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    guard = restrictions.ImportedGoRestrictionGuard(authority)
    guard.prepare()
    if damage == "quantifier":
        record = guard.policy["records"][0]
        record["native_class_xml"] = record["native_class_xml"].replace("someValuesFrom", "allValuesFrom")
        record["native_class_sha256"] = hashlib.sha256(record["native_class_xml"].encode()).hexdigest()
    else:
        guard.identities[restrictions.OWL_ROLE]["path"] += ".invented"
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="policy|bindings"):
        normalize_go_bundle([nodes], [edges], authority, audit, restriction_guard=guard)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()


@pytest.mark.parametrize("erased", [1, 2])
def test_partial_or_total_audit_loss_refuses_direct_checkpoint_reuse(tmp_path, monkeypatch, erased):
    """Checkpoint authority timestamps and unchanged graph hashes cannot conceal lost exclusions."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    normalize_go_bundle([nodes], [edges], authority, audit)
    retained = []
    for row in rows(audit, quoted=True):
        if row["record_kind"] == restrictions.AUDIT_KIND and erased:
            erased -= 1
        else:
            retained.append(row)
    write_rows(audit, retained, quoted=True)
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="inventory"):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("has_go", [False, True])
def test_truthful_empty_inventory_for_ordinary_source(tmp_path, monkeypatch, has_go):
    """No GO or ordinary organism-to-GO observations need no finite PATO evidence."""
    raw, nodes, edges, _, _ = prepare(tmp_path, monkeypatch)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    node_rows = [
        {
            "id": "NCBITaxon:1",
            "category": "biolink:OrganismTaxon",
            "name": "fixture organism",
            "provided_by": "infores:fixture",
        }
    ]
    if has_go:
        node_rows += rows(nodes)
    else:
        node_rows.append({**node_rows[0], "id": "NCBITaxon:2", "name": "second fixture organism"})
    write_rows(transform.output_node_file, node_rows)
    original = rows(edges)[0]
    write_rows(
        transform.output_edge_file,
        [{**original, "subject": "NCBITaxon:1", "object": "GO:0006082" if has_go else "NCBITaxon:2"}],
    )
    (raw / "pato.owl").unlink()
    report = transform.finalize(fresh_run=True)
    assert report[restrictions.INVENTORY_KEY] == restrictions.inventory_contract(0, hashlib.sha256().hexdigest())
    assert (
        not {restrictions.POLICY_ROLE, restrictions.OWL_ROLE, restrictions.GO_ROLE} & report["consumed_inputs"].keys()
    )
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    transform.finalize()


@pytest.mark.usefixtures("local_source_schema")
def test_live_prepublication_inventory_detects_coherently_restamped_loss(tmp_path, monkeypatch):
    """The live guard does not trust a changed staged checkpoint, even if it is internally coherent."""
    from kg_microbe.utils import source_finalization

    raw, nodes, edges, _, _ = prepare(tmp_path, monkeypatch)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    write_rows(
        transform.output_node_file,
        rows(nodes)
        + [
            {
                "id": record["object"],
                "category": "biolink:ChemicalEntity",
                "name": record["object"],
                "provided_by": "infores:pato",
            }
            for record in POLICY["records"]
        ],
    )
    write_rows(transform.output_edge_file, rows(edges))
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    publish = source_finalization._publish_finalization

    def corrupt_then_publish(producer, prepared):
        """Erase the finite audit and restamp its inner receipt after it was independently bound."""
        staging, _, _, _ = prepared
        path = staging / "go_reference_resolution.tsv"
        retained = [row for row in rows(path, quoted=True) if row["record_kind"] != restrictions.AUDIT_KIND]
        for row in retained:
            if row["record_kind"] == "bundle_checkpoint":
                checkpoint = json.loads(row["bundle_fingerprint"])
                checkpoint[restrictions.INVENTORY_KEY] = restrictions.inventory_contract(
                    0, hashlib.sha256().hexdigest()
                )
                row["bundle_fingerprint"] = json.dumps(checkpoint)
        write_rows(path, retained, quoted=True)
        return publish(producer, prepared)

    monkeypatch.setattr(source_finalization, "_publish_finalization", corrupt_then_publish)
    with pytest.raises(SourceFinalizationRequired, match="does not conserve original input occurrences"):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_recorded_admission_retains_native_and_audit_guards(tmp_path, monkeypatch):
    """Terminal admission can still detect drift after the finite verification function returns."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    normalize_go_bundle([nodes], [edges], authority, audit)
    snapshots = json.loads(quarantines(audit)[0][restrictions.EVIDENCE_COLUMN])["inputs"]
    report = {
        "members": {edges.name: {}},
        "audit_members": {audit.name: {}},
        "consumed_inputs": snapshots,
        restrictions.INVENTORY_KEY: restrictions.audit_inventory([audit], snapshots),
    }
    admission = restrictions.verify_recorded_restriction_inputs(report, tmp_path / "source_finalization.json")
    assert admission is not None
    with audit.open("a") as stream:
        stream.write("changed after validation\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        admission.verify(metadata_only=True)


def test_same_count_original_and_candidate_qualifier_rewrite_is_not_conservation(tmp_path, monkeypatch):
    """The finite checkpoint pins complete records, including evidence qualifiers not in the triple."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch)
    normalize_go_bundle([nodes], [edges], authority, audit)
    records = rows(audit, quoted=True)
    snapshots = json.loads(quarantines(audit)[0][restrictions.EVIDENCE_COLUMN])["inputs"]
    for row in records:
        if row["record_kind"] == restrictions.AUDIT_KIND:
            for column in ("original_record_json", "candidate_record_json"):
                content = json.loads(row[column])
                content["publications"] = "PMID:invented but internally consistent"
                row[column] = json.dumps(content)
            break
    write_rows(audit, records, quoted=True)
    with pytest.raises(SourceFinalizationRequired, match="inventory"):
        restrictions.audit_inventory([audit], snapshots)
