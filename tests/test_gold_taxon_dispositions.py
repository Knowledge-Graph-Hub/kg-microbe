"""Native GOLD referents are not strains merely because their labels differ (#1316)."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.gold import taxon_dispositions as policy
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, finalize_source

FIXTURE = Path(__file__).parent / "resources/gold_taxonomy/native_contexts.json"


def _write(path, fields, rows):
    """Stage small immutable source excerpts, preserving all original columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Use eight actual native records, not invented examples of a legitimate strain."""
    evidence = json.loads(FIXTURE.read_text())
    nodes, edges = {}, []
    for identifier, selection in evidence["selected"].items():
        nodes[identifier] = selection["native_declarations"][identifier]["row"]
        for item in selection["native_incident_edges"]:
            if item["row"]["predicate"] == "biolink:in_taxon":
                edges.append(item["row"])
                target = item["row"]["object"]
                nodes[target] = selection["native_declarations"][target]["row"]
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    _write(raw / "gold/GOLD_nodes.tsv", ("id", "category", "name", "provided_by", "xref"), nodes.values())
    _write(
        raw / "gold/GOLD_edges.tsv",
        ("id", "subject", "predicate", "object", "relation", "primary_knowledge_source"),
        edges,
    )
    _write(
        output / "ontologies/ncbitaxon_nodes.tsv",
        ("id", "category", "name", "provided_by", "xref"),
        (row for row in nodes.values() if row["id"].startswith("NCBITaxon:")),
    )
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "true")
    return GOLDTransform(raw, output)


def _report(source):
    """Build a focused producer-admission record from actual emitted bytes, not fabricated evidence."""

    def identity(path):
        """Describe the exact fixture artifact admitted by the synthetic report."""
        return SourceAdmission().capture(path)

    return {
        "source": "gold",
        "raw_input_directory": str(source.input_base_dir.resolve()),
        "consumed_inputs": source.consumed_input_snapshots,
        "producer_native_inputs": source.producer_native_inputs,
        "producer_audit_members": source.producer_audit_snapshots,
        "audit_members": source.producer_audit_snapshots,
        "members": {name: identity(source.output_dir / name) for name in ("nodes.tsv", "edges.tsv")},
    }


def test_all_eight_native_referents_preserve_names_and_associations(source):
    """Conserve complete selected native meanings without asserting strain identity."""
    source.run()
    originals = json.loads(FIXTURE.read_text())["selected"]
    emitted = {row["id"]: row for row in _read(source.output_node_file)}
    assert set(originals) <= emitted.keys()
    for identifier, item in originals.items():
        native = item["native_declarations"][identifier]["row"]
        assert emitted[identifier]["category"] == "biolink:NamedThing"
        for column in ("name", "xref", "provided_by"):
            assert emitted[identifier][column] == native[column]
    assert emitted["gold:Go0531699"]["name"] == ""
    edges = _read(source.output_edge_file)
    assert len(edges) == 8
    assert {row["predicate"] for row in edges} == {"biolink:related_to"}
    assert {row["relation"] for row in edges} == {"gold:organism_v2.ncbi_taxonomy_id"}
    assert source.producer_native_inputs[policy.CONTRACT_KEY]["retained_count"] == 8


def test_audit_preserves_full_native_and_rejected_identity_claims(source):
    """Retain every original and rejected claim in the mandatory producer audit."""
    source.run()
    audit = _read(source.output_dir / policy.AUDIT_FILE)
    assert len(audit) == 8
    for item in audit:
        assert json.loads(item["native_node_json"])["row"]["category"] == "biolink:IndividualOrganism"
        assert json.loads(item["rejected_node_json"])["category"] == "biolink:OrganismTaxon"
        assert json.loads(item["rejected_edges_json"])[0]["predicate"] == "biolink:subclass_of"
        native = json.loads(item["native_taxon_assertions_json"])[0]
        assert native["row"]["predicate"] == "biolink:in_taxon"
        assert native["full_row_sha256"] == policy._digest(native["row"])
        assert json.loads(item["emitted_node_json"])["name"] == json.loads(item["native_node_json"])["row"]["name"]


def test_recorded_native_rejoin_admits_only_exact_blank_declaration(source):
    """Reject every semantic mutation of the narrowly admitted blank-name declaration."""
    source.run()
    report = _report(source)
    admission = policy.verify_recorded_taxon_inputs(report, source.output_dir / "source_finalization.json")
    provider = admission.gold_native_declarations
    assert set(next(iter(provider._providers.values()))._proofs) == {"gold:Go0531699"}
    proof = provider.declaration_for("gold:Go0531699")
    assert proof.matches(proof.declaration, merged=True)
    for change in ({"name": "invented"}, {"category": "biolink:OrganismTaxon"}, {"provided_by": "Graph"}, {"xref": ""}):
        assert not proof.matches({**proof.declaration, **change}, merged=True)
    assert provider.declaration_for("gold:Go0039676") is None


@pytest.mark.parametrize("mutation", ["audit_missing", "audit_omission", "native_name", "role_removed", "new_taxdump"])
def test_native_or_audit_drift_cannot_be_admitted(source, mutation):
    """Refuse missing or changed native evidence even when graph bytes remain present."""
    source.run()
    report = _report(source)
    if mutation == "audit_missing":
        (source.output_dir / policy.AUDIT_FILE).unlink()
    elif mutation == "audit_omission":
        path = source.output_dir / policy.AUDIT_FILE
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    elif mutation == "native_name":
        path = source.input_base_dir / "gold/GOLD_nodes.tsv"
        path.write_text(path.read_text().replace("Anaerobic digesters metagenome", "invented strain"))
    elif mutation == "role_removed":
        report["consumed_inputs"].pop(policy.NCBI_ROLE)
    else:
        (source.input_base_dir / "taxdump.tar.gz").write_bytes(b"new archive")
    with pytest.raises(SourceFinalizationRequired):
        policy.verify_recorded_taxon_inputs(report, source.output_dir / "source_finalization.json")


def test_late_provider_cache_mutation_is_rejected(source):
    """Retain original proof state through the final admission check."""
    source.run()
    admission = policy.verify_recorded_taxon_inputs(_report(source), source.output_dir / "source_finalization.json")
    next(iter(admission.gold_native_declarations._providers.values()))._proofs.clear()
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


def test_actual_finalization_and_repeat_preserve_native_blank_record(source):
    """Exercise the real source finalizer and a fresh-instance repeat without graph changes."""
    source.run()
    finalize_source(source, fresh_run=True)
    report = json.loads((source.output_dir / "source_finalization.json").read_text())
    assert report["gold_reference_declarations"]["requested_ids"] == ["gold:Go0531699"]
    assert next(row for row in _read(source.output_node_file) if row["id"] == "gold:Go0531699")["name"] == ""
    before = {name: hashlib.sha256((source.output_dir / name).read_bytes()).hexdigest() for name in report["members"]}
    fresh = GOLDTransform(source.input_base_dir, source.output_base_dir)
    finalize_source(fresh)
    assert before == {
        name: hashlib.sha256((source.output_dir / name).read_bytes()).hexdigest() for name in report["members"]
    }


@pytest.mark.parametrize("field", ["producer_code", "finalizer_code"])
def test_consumer_rejects_stale_selected_gold_authoring(source, field):
    """Native/audit-valid bytes do not replace the current authoring-code contract."""
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

    source.run()
    finalize_source(source, fresh_run=True)
    path = source.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    if field == "producer_code":
        report[field]["fingerprint"] = "0" * 64
    else:
        report[field] = "0" * 64
    path.write_text(json.dumps(report))
    consumer = MicrobeDecoderTransform(source.input_base_dir, source.output_base_dir, chemical_loader=object())
    with pytest.raises(SourceFinalizationRequired, match="code changed"):
        policy.load_gold_declarations(consumer, {"gold:Go0039676"})


def test_shared_admission_can_revisit_exact_gold_report(source):
    """Recursive source validation must not mistake its own new compatible guard for drift."""
    source.run()
    report = _report(source)
    admission = SourceAdmission()
    path = source.output_dir / "source_finalization.json"
    policy.verify_recorded_taxon_inputs(report, path, admission=admission)
    policy.verify_recorded_taxon_inputs(report, path, admission=admission)
    admission.verify(metadata_only=True)


@pytest.mark.parametrize(
    "mutation",
    ["remove_registry", "rebind_registry", "remove_entry", "replace_entry", "proof", "report", "lookup", "selector"],
)
def test_completed_native_rejoin_cache_cannot_be_rebased(source, mutation):
    """A warm-cache optimization cannot invent a new native witness or truthful zero cohort."""
    source.run()
    report, admission = _report(source), SourceAdmission()
    path = source.output_dir / "source_finalization.json"
    policy._verify_contract(report, path, admission)
    key = str(path.absolute())
    cache = admission._gold_taxon_rejoins[key]
    if mutation == "remove_registry":
        del admission._gold_taxon_rejoins
    elif mutation == "rebind_registry":
        admission._gold_taxon_rejoins = dict(admission._gold_taxon_rejoins)
    elif mutation == "remove_entry":
        admission._gold_taxon_rejoins.clear()
    elif mutation == "replace_entry":
        import copy

        admission._gold_taxon_rejoins[key] = copy.copy(cache)
    elif mutation == "proof":
        cache._proofs.clear()
    elif mutation == "report":
        cache._report = "{}"
    elif mutation == "lookup":
        cache._looked_up.add("gold:invented")
    else:
        cache.select = lambda *_: {}
    with pytest.raises(SourceFinalizationRequired):
        policy._verify_contract(report, path, admission)


def test_cold_and_warm_requested_proofs_are_identical(source, monkeypatch):
    """Select additional proofs only from the same already verified native audit bytes."""
    source.run()
    report, admission = _report(source), SourceAdmission()
    path = source.output_dir / "source_finalization.json"
    policy._verify_contract(report, path, admission)
    requested = {"gold:Go0039676", "gold:does_not_exist"}
    cold = policy._verify_contract(report, path, SourceAdmission(), requested_ids=requested)
    monkeypatch.setattr(policy, "_rejoin_contract", lambda *_a, **_k: pytest.fail("warm scope rebuilt native index"))
    warm = policy._verify_contract(report, path, admission, requested_ids=requested)
    assert warm == cold
    assert set(warm) == {"gold:Go0039676", "gold:Go0531699"}


@pytest.mark.parametrize("mutation", ["registry_entry", "registry_copy", "aggregate_entry", "aggregate_alias"])
def test_native_provider_binding_mutation_is_rejected(source, mutation):
    """Refuse missing, copied or replaced native provider bindings."""
    source.run()
    admission = policy.verify_recorded_taxon_inputs(_report(source), source.output_dir / "source_finalization.json")
    if mutation == "registry_entry":
        admission._gold_native_record_guards.clear()
    elif mutation == "registry_copy":
        admission._gold_native_record_guards = dict(admission._gold_native_record_guards)
    elif mutation == "aggregate_entry":
        admission.gold_native_declarations._providers.clear()
    else:
        admission.gold_native_declarations = object()
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


def test_real_native_provider_passes_merge_validation_without_rewriting(source):
    """Use the real producer proof provider, not a protocol test double, at merge validation."""
    from kg_microbe.utils.source_finalization import validate_graph_bundle

    source.run()
    finalize_source(source, fresh_run=True)
    path = source.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    admission = policy.verify_recorded_taxon_inputs(report, path)
    before = {name: (source.output_dir / name).read_bytes() for name in report["members"]}
    counts = validate_graph_bundle(
        [source.output_node_file],
        [source.output_edge_file],
        require_closure=True,
        require_contract=True,
        native_declarations=admission.gold_native_declarations,
    )
    assert counts["audited_native_nameless_nodes"] == 1
    assert before == {name: (source.output_dir / name).read_bytes() for name in report["members"]}


def test_quote_dialect_normalization_preserves_literal_native_name(source):
    """A labelled serialization perturbation does not assert a new scientific positive case."""
    path = source.input_base_dir / "gold/GOLD_nodes.tsv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        header, rows = reader.fieldnames, list(reader)
    selected = next(row for row in rows if row["id"] == "gold:Go0039676")
    selected["name"] = 'literal "quoted" source name'
    _write(path, header, rows)
    source.run()
    finalize_source(source, fresh_run=True)
    report_path = source.output_dir / "source_finalization.json"
    report = json.loads(report_path.read_text())
    proofs = policy._verify_contract(report, report_path, SourceAdmission(), requested_ids={selected["id"]})
    proof = policy.VerifiedGoldDeclaration(proofs[selected["id"]])
    assert proof.declaration["name"] == selected["name"]
    assert proof.original_node["row"]["name"] == selected["name"]
