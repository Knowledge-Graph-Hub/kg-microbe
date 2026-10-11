"""Exercise the complete reviewed restriction cohort through source publication and admission."""

import copy
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

pytestmark = pytest.mark.usefixtures("local_source_schema")
EXPECTED_CLAIMS = len(FULL_POLICY["records"])


def _canonical(value):
    """Encode complete audit records using the documented inventory serialization."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity(path):
    """Hash a tiny test artifact without obtaining a replacement admission receipt."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _project(original, replacement, authority):
    """Independently describe existing GO endpoint projection, not quarantine-helper output."""
    candidate = dict(original)
    history = json.loads(original.get("go_reference_context") or "[]")
    for column in ("subject", "object"):
        literal = original[column]
        compact = literal.replace("http://purl.obolibrary.org/obo/GO_", "GO:", 1)
        if not compact.startswith("GO:"):
            continue
        canonical = replacement if column == "subject" else compact
        if literal == canonical:
            continue
        candidate[column] = canonical
        candidate["original_" + column] = original.get("original_" + column) or literal
        history.append(
            {
                "column": column,
                "original_id": literal,
                "canonical_id": canonical,
                "replacement_chain": [compact, canonical] if compact != canonical else [compact],
                "authority": authority.authority_path,
                "authority_sha256": authority.authority_sha256,
            }
        )
        candidate["go_reference_context"] = _canonical(history)
    return candidate


def _stage(tmp_path, monkeypatch, *, historical_go_object=False):
    """Use genuine pinned native excerpts and declare every finite target before real finalization."""
    import csv

    raw, nodes, edges, _, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    declarations = rows(nodes)
    originals = rows(edges)
    declared = {row["id"] for row in declarations}
    for original in originals:
        identifier = original["object"]
        if identifier in declared:
            continue
        declared.add(identifier)
        if identifier.startswith("GO:"):
            declaration = authority.resolve(identifier).node_fields()
            declaration["provided_by"] = "infores:pato"
        else:
            declaration = {
                "id": identifier,
                "category": "biolink:OrganismTaxon"
                if identifier.startswith("NCBITaxon:")
                else "biolink:ChemicalEntity",
                "name": "synthetic fixture declaration " + identifier,
                "provided_by": "infores:pato",
            }
        declarations.append(declaration)
    if historical_go_object:
        row = next(row for row in originals if row["subject"] == "GO:0006643")
        row["subject"] = "http://purl.obolibrary.org/obo/GO_0006643"
        row["object"] = "http://purl.obolibrary.org/obo/GO_0016020"
        row.update(_project(row, "GO:0006629", authority))
    fields = list(dict.fromkeys(field for row in declarations for field in row))
    write_rows(transform.output_node_file, declarations, fields=fields)
    fields = list(dict.fromkeys(field for row in originals for field in row))
    write_rows(transform.output_edge_file, originals, fields=fields)
    return transform, authority, originals


def _paths(transform):
    """Name only the actual source bundle's published graph and mandatory evidence."""
    return (
        [transform.output_node_file, transform.output_edge_file],
        transform.output_dir / "go_reference_resolution.tsv",
        transform.output_dir / "source_finalization.json",
    )


def _snapshot(directory):
    """Keep exact tiny fixture outputs for all-validation-before-publication assertions."""
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def _decisions(audit):
    """Select finite dispositions without confusing generic GO migration events with claims."""
    return [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]


def _assert_complete_records(audit, originals, authority):
    """Compare every preserved source field and the whole independently predicted candidate."""
    decisions = _decisions(audit)
    assert len(decisions) == len(originals) == EXPECTED_CLAIMS
    by_coordinate = {(row["source_record"], row["relation"], row["object"]): row for row in originals}
    for decision in decisions:
        original = json.loads(decision["original_record_json"])
        source = by_coordinate[(original["source_record"], original["relation"], original["object"])]
        assert source.keys() <= original.keys()
        assert original == {field: source.get(field, "") for field in original}
        native = next(record for record in FULL_POLICY["records"] if record["subject"] == source["source_record"])
        assert json.loads(decision["candidate_record_json"]) == _project(original, native["replacement"], authority)
        context = json.loads(decision[restrictions.EVIDENCE_COLUMN])
        assert context["native_class_xml"] == native["native_class_xml"]
        assert context["native_class_sha256"] == native["native_class_sha256"]
        assert context["input_member"]["file"] == "edges.tsv"
    assert {json.loads(row[restrictions.EVIDENCE_COLUMN])["input_record_ordinal"] for row in decisions} == set(
        range(1, EXPECTED_CLAIMS + 1)
    )


@pytest.mark.parametrize("historical_go_object", [False, True])
def test_full_cohort_public_finalization_same_and_fresh_repeat(tmp_path, monkeypatch, historical_go_object):
    """Real publication keeps all rows/history, actual consumed roles and repeat evidence bytes."""
    transform, authority, originals = _stage(tmp_path, monkeypatch, historical_go_object=historical_go_object)
    report = transform.finalize(fresh_run=True)
    graph, audit, _ = _paths(transform)
    assert rows(transform.output_edge_file) == []
    assert report["summaries"]["go"]["quarantined_imported_subject_restrictions"] == EXPECTED_CLAIMS
    assert report[restrictions.INVENTORY_KEY]["quarantined_occurrences"] == EXPECTED_CLAIMS
    expected_roles = {restrictions.POLICY_ROLE, restrictions.OWL_ROLE, restrictions.GO_ROLE}
    assert expected_roles <= report["consumed_inputs"].keys()
    for role in expected_roles:
        identity = report["consumed_inputs"][role]
        assert hashlib.sha256(Path(identity["path"]).read_bytes()).hexdigest() == identity["sha256"]
    _assert_complete_records(audit, originals, authority)
    verify_finalized_source_files(graph)
    before = _snapshot(transform.output_dir)
    assert transform.finalize() == report
    assert _snapshot(transform.output_dir) == before
    fresh = Transform("fixture", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    assert fresh.consumed_input_snapshots == report["consumed_inputs"]
    assert _snapshot(transform.output_dir) == before
    verify_finalized_source_files(graph)


@pytest.mark.parametrize("target", ["native", "audit", "graph"])
def test_public_recorded_reader_retains_late_admission_bindings(tmp_path, monkeypatch, target):
    """The actual recorded-input path retains native, audit and graph bytes after returning."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, audit, report_path = _paths(transform)
    verify_finalized_source_files(graph)
    admission = SourceAdmission()
    returned = source_finalization._verify_recorded_consumed_inputs(
        report, report_path=report_path, admission=admission
    )
    assert returned is admission
    admission.verify(metadata_only=True)
    path = transform.input_base_dir / "pato.owl" if target == "native" else audit if target == "audit" else graph[1]
    path.write_bytes(path.read_bytes() + b"changed after admission\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        admission.verify(metadata_only=True)


def _damage_audit(path, damage, *, coherent=False):
    """Model evidence loss without using the implementation under test to derive the new receipt."""
    content = rows(path, quoted=True)
    finite = [row for row in content if row["record_kind"] == restrictions.AUDIT_KIND]
    assert len(finite) == EXPECTED_CLAIMS
    if damage in {"partial", "all"}:
        removed = {id(row) for row in (finite[:1] if damage == "partial" else finite)}
        content = [row for row in content if id(row) not in removed]
    else:
        for column in ("original_record_json", "candidate_record_json"):
            value = json.loads(finite[0][column])
            value["publications"] = "PMID:invented-but-consistent"
            finite[0][column] = _canonical(value)
    retained = [row for row in content if row["record_kind"] == restrictions.AUDIT_KIND]
    digest = hashlib.sha256()
    for row in retained:
        digest.update((_canonical(row) + "\n").encode())
    inventory = {
        "version": restrictions.RUNTIME_VERSION,
        "quarantined_occurrences": len(retained),
        "records_sha256": digest.hexdigest(),
    }
    if coherent:
        checkpoint = next(row for row in content if row["record_kind"] == "bundle_checkpoint")
        bundle = json.loads(checkpoint["bundle_fingerprint"])
        bundle[restrictions.INVENTORY_KEY] = inventory
        checkpoint["bundle_fingerprint"] = _canonical(bundle)
    write_rows(path, content, quoted=True)
    return inventory


@pytest.mark.parametrize("damage", ["partial", "all", "same_count_qualifier"])
@pytest.mark.parametrize("route", ["public", "fresh_repeat"])
def test_full_cohort_public_admission_rejects_restamped_audit_loss(tmp_path, monkeypatch, damage, route):
    """Restamping the outer audit identity cannot erase one or all exclusions or rewrite qualifiers."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, audit, report_path = _paths(transform)
    _damage_audit(audit, damage)
    report["audit_members"][audit.name] = _identity(audit)
    report_path.write_text(_canonical(report))
    before = _snapshot(transform.output_dir)
    with pytest.raises(SourceFinalizationRequired):
        if route == "public":
            verify_finalized_source_files(graph)
        else:
            Transform("fixture", transform.input_base_dir, transform.output_base_dir).finalize()
    assert _snapshot(transform.output_dir) == before


@pytest.mark.parametrize("claim", FULL_POLICY["records"], ids=lambda claim: claim["subject"])
def test_each_current_shadow_without_original_history_refuses_publication(tmp_path, monkeypatch, claim):
    """Do not turn a current-class assertion into a historical restriction without evidence."""
    transform, authority, originals = _stage(tmp_path, monkeypatch)
    original = next(
        row
        for row in originals
        if all(row[key] == claim[key] for key in ("subject", "relation", "object", "predicate"))
    )
    candidate = _project(original, claim["replacement"], authority)
    candidate.pop("go_reference_context", None)
    candidate.pop("original_subject", None)
    write_rows(transform.output_edge_file, [candidate])
    before = _snapshot(transform.output_dir)
    with pytest.raises(ValueError, match="history"):
        transform.finalize(fresh_run=True)
    assert _snapshot(transform.output_dir) == before
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("damage", ["partial", "all", "same_count_qualifier"])
def test_full_cohort_direct_checkpoint_rejects_changed_finite_audit(tmp_path, monkeypatch, damage):
    """The direct repeat route cannot bypass conservation by recognizing unchanged graph bytes."""
    transform, authority, _ = _stage(tmp_path, monkeypatch)
    transform.finalize(fresh_run=True)
    graph, audit, _ = _paths(transform)
    _damage_audit(audit, damage)
    before = _snapshot(transform.output_dir)
    with pytest.raises(SourceFinalizationRequired):
        normalize_go_bundle([graph[0]], [graph[1]], authority, audit)
    assert _snapshot(transform.output_dir) == before


@pytest.mark.parametrize("damage", ["partial", "all", "same_count_qualifier"])
def test_full_cohort_prepublication_coherent_restamp_is_refused(tmp_path, monkeypatch, damage):
    """The original live guard remains independent of coherently rewritten staged reports."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    before = _snapshot(transform.output_dir)
    publish = source_finalization._publish_finalization

    def corrupt_then_publish(producer, prepared):
        """Rewrite all mutable evidence receipts but not the independently held original guard."""
        staging, report_path, _, report = prepared
        audit = staging / "go_reference_resolution.tsv"
        inventory = _damage_audit(audit, damage, coherent=True)
        report[restrictions.INVENTORY_KEY] = inventory
        report["summaries"]["go"]["quarantined_imported_subject_restrictions"] = inventory["quarantined_occurrences"]
        report["audit_members"][audit.name] = _identity(audit)
        report_path.write_text(_canonical(report))
        return publish(producer, prepared)

    monkeypatch.setattr(source_finalization, "_publish_finalization", corrupt_then_publish)
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)
    assert _snapshot(transform.output_dir) == before
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("role", [restrictions.POLICY_ROLE, restrictions.OWL_ROLE, restrictions.GO_ROLE])
def test_full_cohort_recorded_admission_requires_each_original_role(tmp_path, monkeypatch, role):
    """Graph emptiness and correct audit hashes do not excuse an erased actual-read authority role."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    graph, _, report_path = _paths(transform)
    report["consumed_inputs"].pop(role)
    report_path.write_text(_canonical(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(graph)


@pytest.mark.parametrize("native_name", ["pato.owl", "go.db"])
def test_full_cohort_fresh_repeat_refuses_native_drift(tmp_path, monkeypatch, native_name):
    """A fresh producer instance must validate original native inputs, not accept replacement bytes."""
    transform, _, _ = _stage(tmp_path, monkeypatch)
    transform.finalize(fresh_run=True)
    before = _snapshot(transform.output_dir)
    path = transform.input_base_dir / native_name
    path.write_bytes(path.read_bytes() + b"new epoch")
    fresh = Transform("fixture", transform.input_base_dir, transform.output_base_dir)
    with pytest.raises(SourceFinalizationRequired):
        fresh.finalize()
    assert _snapshot(transform.output_dir) == before


@pytest.mark.parametrize("mode", ["other_supplier", "other_relation", "ordinary_observation", "no_go"])
def test_public_truthful_zero_keeps_unselected_sources_dependency_free(tmp_path, monkeypatch, mode):
    """Unselected observations and class relations do not load finite PATO quarantine evidence."""
    transform, _, originals = _stage(tmp_path, monkeypatch)
    record = copy.deepcopy(originals[0])
    declarations = rows(transform.output_node_file)
    if mode == "other_supplier":
        record["primary_knowledge_source"] = "infores:fixture"
    elif mode == "other_relation":
        record["relation"] = "RO:0000057"
    else:
        declarations.append(
            {
                "id": "NCBITaxon:1",
                "category": "biolink:OrganismTaxon",
                "name": "fixture organism",
                "provided_by": "infores:fixture",
            }
        )
        record["subject"] = "NCBITaxon:1"
        record["object"] = "GO:0006082"
        if mode == "no_go":
            declarations = [row for row in declarations if row["id"] == "NCBITaxon:1"]
            declarations.append({**declarations[0], "id": "NCBITaxon:2", "name": "second fixture organism"})
            record["object"] = "NCBITaxon:2"
    fields = list(dict.fromkeys(field for row in declarations for field in row))
    write_rows(transform.output_node_file, declarations, fields=fields)
    write_rows(transform.output_edge_file, [record])
    (transform.input_base_dir / "pato.owl").unlink()
    restrictions.POLICY_FILE.unlink()
    report = transform.finalize(fresh_run=True)
    graph, audit, _ = _paths(transform)
    assert report[restrictions.INVENTORY_KEY] == {
        "version": restrictions.RUNTIME_VERSION,
        "quarantined_occurrences": 0,
        "records_sha256": hashlib.sha256().hexdigest(),
    }
    assert (
        not {restrictions.POLICY_ROLE, restrictions.OWL_ROLE, restrictions.GO_ROLE} & report["consumed_inputs"].keys()
    )
    assert not _decisions(audit)
    assert len(rows(transform.output_edge_file)) == 1
    verify_finalized_source_files(graph)
    before = _snapshot(transform.output_dir)
    assert transform.finalize() == report
    assert _snapshot(transform.output_dir) == before


def test_supported_sibling_start_location_is_not_quarantined_with_destination():
    """A reviewed destination disposition never authorizes a subject-wide sibling exclusion."""
    row = {
        "subject": "GO:0055108",
        "predicate": "biolink:related_to",
        "object": "GO:0005794",
        "relation": "RO:0002338",
        "primary_knowledge_source": "infores:pato",
    }
    before = copy.deepcopy(row)
    assert restrictions.identify(row) is None
    assert row == before
