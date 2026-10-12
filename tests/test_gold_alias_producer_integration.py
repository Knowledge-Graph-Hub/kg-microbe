"""The actual GOLD producer composes finite selected aliases without record identity or fold changes."""

import json
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.gold import selected_taxon_aliases as aliases
from kg_microbe.transform_utils.gold import taxon_dispositions as taxonomy
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.gold_selected_alias_fixtures import stage
from tests.test_gold_taxon_dispositions import _read, _report, _write

FIXTURE = Path(__file__).parent / "resources/gold_selected_taxon_aliases/producer_contexts.json"


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Use all eleven actual native records, all their assertions and complete original context."""
    transform, _ = stage(tmp_path)
    evidence = json.loads(FIXTURE.read_text())
    _write(
        transform.input_base_dir / "gold/GOLD_nodes.tsv",
        evidence["node_header"],
        (item["row"] for item in evidence["native_declarations"].values()),
    )
    _write(
        transform.input_base_dir / "gold/GOLD_edges.tsv",
        evidence["edge_header"],
        (
            item["row"]
            for item in evidence["native_incident_assertions"] + evidence["complete_ecosystem_parent_assertions"]
        ),
    )
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "true")
    result = GOLDTransform(transform.input_base_dir, transform.output_base_dir)
    result.run()
    return result


def test_actual_producer_preserves_eleven_native_referents_and_selected_taxon_associations(source):
    """Aliases repair selected authority resolution, never infer source record identity or strains."""
    evidence = json.loads(FIXTURE.read_text())
    nodes = {row["id"]: row for row in _read(source.output_node_file)}
    edges = _read(source.output_edge_file)
    expected = {old: target for old, target in (("53360", "53362"), ("659496", "33920"), ("1194211", "4927"))}
    assertions = [row for row in edges if row["subject"] in evidence["selected_source_ids"]]
    assert len(assertions) == 18  # eleven taxon associations plus seven non-root environments
    for item in evidence["native_incident_assertions"]:
        native = item["row"]
        if native["predicate"] != "biolink:in_taxon":
            continue
        identifier = native["subject"]
        assert nodes[identifier]["category"] == "biolink:NamedThing"
        for field in ("name", "xref", "provided_by"):
            assert nodes[identifier][field] == evidence["native_declarations"][identifier]["row"][field]
        target = "NCBITaxon:" + expected[native["object"].split(":")[1]]
        assert any(
            row["subject"] == identifier
            and row["predicate"] == "biolink:related_to"
            and row["object"] == target
            and row["relation"] == native["relation"]
            for row in assertions
        )
        assert target in nodes
    assert not any(row["category"] == "biolink:Study" for row in nodes.values())
    alias_contract = source.producer_native_inputs[aliases.CONTRACT_KEY]
    assert alias_contract["eligible_record_count"] == 11
    assert alias_contract["native_incident_count"] == 27
    taxon_contract = source.producer_native_inputs[taxonomy.CONTRACT_KEY]
    assert taxon_contract["retained_count"] == taxon_contract["association_count"] == 11
    assert taxon_contract["historical_fold_count"] == taxon_contract["folded_count"] == 0
    assert _read(source.output_dir / "gold_lexical_fold_restorations.tsv") == []


def test_producer_alias_audit_preserves_all_original_claims_and_resolution_steps(source):
    """Five Study and four root-only habitat exclusions remain auditable, not newly emitted claims."""
    audit = _read(source.output_dir / aliases.AUDIT_FILE)
    assert len(audit) == 3
    assert sum(len(json.loads(row["native_incident_rows_json"])) for row in audit) == 27
    association_audit = _read(source.output_dir / taxonomy.AUDIT_FILE)
    assert len(association_audit) == 11
    for row in association_audit:
        native = json.loads(row["native_taxon_assertions_json"])[0]["row"]
        witness = json.loads(row["taxid_remaps_json"])[native["object"]]["selected_authority_alias"]
        assert witness["original_id"] == native["object"]
        assert witness["selected_target"] == json.loads(row["emitted_edges_json"])[0]["object"]
    source.verify_consumed_inputs()
    report = _report(source)
    admission = GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")
    admission.verify()


def test_alias_target_missing_native_declaration_uses_selected_authority_metadata(source):
    """A former name must not be donated to the new identifier when its native target row is absent."""
    nodes = {row["id"]: row for row in _read(source.output_node_file)}
    for row in _read(source.output_dir / aliases.AUDIT_FILE):
        selected = json.loads(row["selected_declaration_json"])["row"]
        assert nodes[row["selected_target"]] == {key: selected.get(key, "") for key in source.node_header}


@pytest.mark.parametrize("field", ["name", "category", "xref", "provided_by"])
def test_recorded_alias_fallback_target_metadata_cannot_be_restamped(source, field):
    """The target fallback is bound to actual selected metadata, not only an emitted identifier."""
    report = _report(source)
    nodes = _read(source.output_node_file)
    selected = next(row for row in nodes if row["id"] == "NCBITaxon:53362")
    selected[field] = "unproved"
    _write(source.output_node_file, source.node_header, nodes)
    report["members"]["nodes.tsv"] = SourceAdmission().capture(source.output_node_file)
    with pytest.raises(SourceFinalizationRequired, match="alias target declaration changed"):
        GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


@pytest.mark.parametrize("mutation", ["missing_audit", "missing_inventory", "missing_contract", "missing_json_role"])
def test_public_producer_admission_requires_complete_alias_disposition(source, mutation):
    """No saved alias omission can silently restore the former trim decision or skip native verification."""
    report = _report(source)
    if mutation == "missing_audit":
        (source.output_dir / aliases.AUDIT_FILE).unlink()
    elif mutation == "missing_inventory":
        report["producer_audit_members"].pop(aliases.AUDIT_FILE)
    elif mutation == "missing_contract":
        report["producer_native_inputs"].pop(aliases.CONTRACT_KEY)
    else:
        report["consumed_inputs"].pop(aliases.JSON_ROLE)
    with pytest.raises(SourceFinalizationRequired):
        GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


def test_late_publication_preserves_original_alias_roles(source):
    """The integrated GOLD live guard retains the isolated resolver's original role contract."""
    source._consumed_input_snapshots.pop(aliases.JSON_ROLE)
    with pytest.raises(SourceFinalizationRequired):
        source.verify_consumed_inputs()


def _fresh_producer(source):
    """Restore the actual public finalization through a new producer instance."""
    source.finalize(fresh_run=True)
    fresh = GOLDTransform(source.input_base_dir, source.output_base_dir)
    fresh.finalize()
    fresh.verify_consumed_inputs()
    return fresh


@pytest.mark.parametrize("role", [aliases.JSON_ROLE, aliases.NCBI_ROLE, aliases.TAXDUMP_ROLE])
@pytest.mark.parametrize("mutation", ["remove", "rebind"])
def test_fresh_repeat_retains_original_dynamic_role_contract(source, role, mutation):
    """Fresh-instance repeat retains full active receipts, not only the Abscess subset (#1339)."""
    fresh = _fresh_producer(source)
    original = dict(fresh._consumed_input_snapshots[role])
    if mutation == "remove":
        fresh._consumed_input_snapshots.pop(role)
    else:
        fresh._consumed_input_snapshots[role] = dict(fresh._consumed_input_snapshots[aliases.NODES_ROLE])
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()
    fresh._consumed_input_snapshots[role] = original
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()  # A refused restored guard cannot heal itself.


@pytest.mark.parametrize("field", [aliases.CONTRACT_KEY, taxonomy.CONTRACT_KEY, "actual_roles"])
@pytest.mark.parametrize("route", ["setter", "cached"])
def test_fresh_repeat_cannot_erase_composed_native_contract(source, field, route):
    """Both public assignment and mutable cached payloads preserve every composed contract."""
    fresh = _fresh_producer(source)
    candidate = json.loads(json.dumps(fresh.producer_native_inputs))
    candidate.pop(field)
    with pytest.raises(SourceFinalizationRequired):
        if route == "setter":
            fresh.producer_native_inputs = candidate
        else:
            fresh._recorded_crosswalk_inputs = candidate
        fresh.verify_consumed_inputs()


@pytest.mark.parametrize("mutation", ["clear", "replace"])
def test_fresh_repeat_cannot_clear_native_guard(source, mutation):
    """A missing restored guard is not interpreted as an inactive finite cohort."""
    fresh = _fresh_producer(source)
    fresh._recorded_native_guard = None if mutation == "clear" else lambda **kwargs: None
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()


def test_fresh_repeat_rejects_equal_byte_selected_role_rebinding(source):
    """Identical copied bytes do not authorize replacing the selected native locator."""
    fresh = _fresh_producer(source)
    original = Path(fresh.consumed_input_snapshots[aliases.JSON_ROLE]["path"])
    substitute = source.input_base_dir / "same-bytes.json"
    substitute.write_bytes(original.read_bytes())
    fresh._consumed_input_snapshots[aliases.JSON_ROLE]["path"] = str(substitute)
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()


def test_fresh_repeat_retains_native_graph_byte_guard(source):
    """Saved native admission continues to protect finalized graph members after repeat."""
    fresh = _fresh_producer(source)
    rows = _read(fresh.output_edge_file)
    location = next(row for row in rows if row["predicate"] == "biolink:located_in")
    location["original_object"] = ""
    _write(fresh.output_edge_file, list(rows[0]), rows)
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()


def test_fresh_repeat_cannot_replace_retained_admission(source):
    """An empty admission cannot replace the original fully rejoined native evidence."""
    fresh = _fresh_producer(source)
    fresh._recorded_native_admission = SourceAdmission()
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_consumed_inputs()


def test_real_finalization_keeps_every_scientific_alias_observation_field(source):
    """Canonical finalizer columns leave all producer assertion fields byte-for-value unchanged."""
    selected = set(json.loads(FIXTURE.read_text())["selected_source_ids"])
    before = [row for row in _read(source.output_edge_file) if row["subject"] in selected]
    fresh = _fresh_producer(source)
    after = [row for row in _read(fresh.output_edge_file) if row["subject"] in selected]

    def canonical(row):
        """Project only the explicitly audited producer assertion fields."""
        return json.dumps({key: row[key] for key in taxonomy.EDGE_HEADER}, sort_keys=True)

    assert sorted(map(canonical, before)) == sorted(map(canonical, after))
    assert set(taxonomy.EDGE_HEADER) <= after[0].keys()


@pytest.mark.parametrize(
    "field",
    [
        "publications",
        "description",
        "source_record",
        "source_column",
        "source_citation",
        "source_citation_base64",
        "original_subject",
        "value",
        "value_encoding",
    ],
)
def test_finalized_alias_observation_cannot_gain_unsupported_extra_evidence(source, field):
    """Blank finalizer columns are compatible, but nonempty unaudited claims are not."""
    source.finalize(fresh_run=True)
    report = json.loads((source.output_dir / "source_finalization.json").read_text())
    rows = _read(source.output_edge_file)
    assert "publications" in rows[0]  # Actual finalization adds this canonical optional column.
    for row in rows:
        row.setdefault(field, "")
    selected = next(row for row in rows if row["predicate"] == "biolink:located_in")
    selected[field] = "PMID:99999999" if field == "publications" else "unsupported assertion evidence"
    _write(source.output_edge_file, list(rows[0]), rows)
    report["members"]["edges.tsv"] = SourceAdmission().capture(source.output_edge_file)
    with pytest.raises(SourceFinalizationRequired, match="additional assertion evidence"):
        GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


@pytest.mark.parametrize("position", range(7))
@pytest.mark.parametrize("mutation", ["remove", "foreign_owner", "qualifier"])
def test_every_alias_environment_is_native_rejoined_on_recorded_admission(source, position, mutation):
    """All seven record-owned observations survive unchanged under restamped output receipts (#1340)."""
    report = _report(source)
    rows = _read(source.output_edge_file)
    locations = [row for row in rows if row["subject"].startswith("gold:") and row["predicate"] == "biolink:located_in"]
    assert len(locations) == 7
    selected = locations[position]
    if mutation == "remove":
        rows.remove(selected)
    elif mutation == "foreign_owner":
        selected["subject"] = next(row["subject"] for row in locations if row["subject"] != selected["subject"])
    else:
        selected["original_object"] = ""
    _write(source.output_edge_file, list(rows[0]), rows)
    report["members"]["edges.tsv"] = SourceAdmission().capture(source.output_edge_file)
    with pytest.raises(SourceFinalizationRequired, match="observation"):
        GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


def test_late_alias_environment_loss_cannot_complete_finalization(source):
    """The live producer protects finite observations before any finalization receipt exists."""
    rows = _read(source.output_edge_file)
    rows.remove(
        next(row for row in rows if row["subject"].startswith("gold:") and row["predicate"] == "biolink:located_in")
    )
    _write(source.output_edge_file, list(rows[0]), rows)
    with pytest.raises(SourceFinalizationRequired, match="observation"):
        source.verify_consumed_inputs()


def test_alias_observation_guard_cannot_be_replaced(source):
    """The original live observation-check binding cannot be replaced by a no-op."""
    source._taxon_dispositions.index.alias_observations.verify_graph = lambda *args, **kwargs: None
    with pytest.raises(SourceFinalizationRequired):
        source.verify_consumed_inputs()


def test_truthful_empty_alias_producer_survives_fresh_repeat(tmp_path, monkeypatch):
    """An actual empty native source restores explicit zero audits without an invented JSON read."""
    bare, _ = stage(tmp_path, empty=True)
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "false")
    producer = GOLDTransform(bare.input_base_dir, bare.output_base_dir)
    producer.run()
    fresh = _fresh_producer(producer)
    assert fresh.producer_native_inputs[aliases.CONTRACT_KEY]["eligible_record_count"] == 0
    assert aliases.JSON_ROLE not in fresh.consumed_input_snapshots


def test_alias_observation_scan_is_not_per_consumer_reference(source, monkeypatch):
    """Warm requested proofs and retained admission callbacks never rescan graph-scale edges."""
    original = taxonomy._rows
    scans = []

    def counted(path, *args, **kwargs):
        """Count actual emitted-edge iterations across independent native admission."""
        if Path(path) == source.output_edge_file:
            scans.append(str(path))
        yield from original(path, *args, **kwargs)

    monkeypatch.setattr(taxonomy, "_rows", counted)
    requested = set(json.loads(FIXTURE.read_text())["selected_source_ids"])
    report, admission = _report(source), SourceAdmission()
    path = source.output_dir / "source_finalization.json"
    provider = taxonomy.admitted_gold_declarations(report, path, requested, admission=admission)
    initial_scans = len(scans)
    assert initial_scans > 0
    for _ in range(100):
        for identifier in requested:
            assert provider.declaration_for(identifier) is not None
        admission.verify(metadata_only=True)
    taxonomy.admitted_gold_declarations(report, path, requested, admission=admission)
    assert len(scans) == initial_scans
