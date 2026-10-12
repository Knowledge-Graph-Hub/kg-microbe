"""The seven unsupported GOLD exact identities must not erase native site observations."""

import csv
import gzip
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.gold import crosswalk_quarantine as policy
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

FIXTURE = Path(__file__).parent / "resources/gold_abscess"


def rows(path):
    """Read only a small immutable fixture or bounded audit."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def canonical(value):
    """Match the independently pinned structural selection contract."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Stage exact native excerpts; never turn invented ontology claims into positive fixtures."""
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    (raw / "gold").mkdir(parents=True)
    (output / "ontologies_stubs").mkdir(parents=True)
    (output / "ontologies").mkdir()
    shutil.copyfile(FIXTURE / "ncbitaxon_nodes.tsv", output / "ontologies/ncbitaxon_nodes.tsv")
    for name in ("GOLD_nodes.tsv", "GOLD_edges.tsv"):
        shutil.copyfile(FIXTURE / name, raw / "gold" / name)
    shutil.copyfile(FIXTURE / "mesh_nodes.tsv", output / "ontologies_stubs/mesh_nodes.tsv")
    with gzip.open(raw / "mesh2026.nt.gz", "wb") as stream:
        stream.write((FIXTURE / "mesh.nt").read_bytes())
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "false")
    return GOLDTransform(input_dir=raw, output_dir=output)


def test_policy_and_fixture_are_independently_pinned():
    """A mutable policy cannot self-certify a changed scientific selection."""
    assert (
        hashlib.sha256(canonical(json.loads(policy.POLICY_PATH.read_text())).encode()).hexdigest()
        == policy.POLICY_SHA256
    )
    selected = json.loads((FIXTURE / "native_selection.json").read_text())
    assert hashlib.sha256(canonical(selected).encode()).hexdigest() == policy.NATIVE_SELECTION_SHA256
    assert len(selected["nodes"]) == 23
    assert len(selected["assignments"]) == 34


def test_exact_native_cohort_only_seven_crosswalks_removed(source, tmp_path):
    """Same-stage comparison preserves every node and every other complete edge row."""
    baseline = GOLDTransform(input_dir=source.input_base_dir, output_dir=tmp_path / "baseline")
    (baseline.output_base_dir / "ontologies_stubs").mkdir()
    (baseline.output_base_dir / "ontologies").mkdir()
    shutil.copyfile(FIXTURE / "ncbitaxon_nodes.tsv", baseline.output_base_dir / "ontologies/ncbitaxon_nodes.tsv")
    shutil.copyfile(FIXTURE / "mesh_nodes.tsv", baseline.output_base_dir / "ontologies_stubs/mesh_nodes.tsv")
    baseline._mesh_sites = baseline._mesh_site_terms() | {"mesh:D000038"}
    baseline._run_snapshot(source.input_base_dir / "gold/GOLD_nodes.tsv", source.input_base_dir / "gold/GOLD_edges.tsv")
    source.run()
    assert source.output_node_file.read_bytes() == baseline.output_node_file.read_bytes()
    before = Counter(map(canonical, rows(baseline.output_edge_file)))
    after = Counter(map(canonical, rows(source.output_edge_file)))
    assert not after - before
    removed = [json.loads(value) for value in (before - after).elements()]
    assert len(removed) == 7
    assert {item["subject"] for item in removed} == set(source.producer_native_inputs["ecosystem_ids"])
    assert all(item["predicate"] == "biolink:exact_match" and item["object"] == "mesh:D000038" for item in removed)
    locations = [item for item in rows(source.output_edge_file) if item["predicate"] == "biolink:located_in"]
    assert len(locations) == 34
    assert Counter(item["original_object"] for item in locations) == {"": 30, "gold.ecosystem:6347": 4}


def test_every_quarantine_retains_complete_original_and_current_evidence(source):
    """Audit carries historical assertion, original mapping, full native context and all observations."""
    source.run()
    audit = rows(source.output_dir / policy.AUDIT_FILE)
    assert len(audit) == 7
    assert set(audit[0]) == set(policy.AUDIT_HEADER)
    for item in audit:
        assert json.loads(item["original_mapping_json"])["decision"] == "SITE"
        assert json.loads(item["current_mapping_json"])["row"]["decision"] == "QUARANTINE_EXACT"
        assert json.loads(item["native_declaration_json"])["row"]["id"] == item["ecosystem_id"]
        assert len(json.loads(item["native_context_nodes_json"])) == 23
        assert len(json.loads(item["native_assignments_json"])) == 34
        assert len(json.loads(item["retained_location_edges_json"])) == 34
        current_locations = json.loads(item["retained_location_edges_json"])
        historical_locations = json.loads(item["historical_location_edges_json"])
        assert len(historical_locations) == 34
        assert all(row["subject"].startswith("gold:") for row in current_locations)
        assert sum(row["row"]["subject"].startswith("NCBITaxon:") for row in historical_locations) == 11
        assert len(json.loads(item["mesh_native_evidence_json"])) == 53
        snapshots = json.loads(item["consumed_inputs_json"])
        assert set(policy.REQUIRED_INPUTS + policy.ACTIVE_INPUTS) <= set(snapshots)
        assert all(len(value["sha256"]) == 64 for value in snapshots.values())
    verify_producer_audits(source)
    source.verify_consumed_inputs()


@pytest.mark.parametrize("mutation", ["swapped", "omitted"])
def test_actual_abscess_output_cannot_diverge_after_emitter_callback(source, monkeypatch, mutation):
    """A saved in-memory observation is not proof of the actual emitted source ownership."""
    original = source._write_nodes

    def tamper_after_observation(*args):
        """Alter the actual location output after its audit callback has observed it."""
        original(*args)
        claims = rows(source.output_edge_file)
        locations = [row for row in claims if row["predicate"] == "biolink:located_in"]
        if mutation == "omitted":
            claims.remove(locations[0])
        else:
            first, second = next(
                (left, right) for left in locations for right in locations if left["object"] != right["object"]
            )
            first["subject"], second["subject"] = second["subject"], first["subject"]
        with source.output_edge_file.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(claims[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(claims)

    monkeypatch.setattr(source, "_write_nodes", tamper_after_observation)
    with pytest.raises(SourceFinalizationRequired, match="actual source-owned"):
        source.run()


def test_coherently_restamped_abscess_source_ownership_is_rejected(source):
    """Even changing both graph and all seven audits cannot invent a native source assignment."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.transform_utils.gold.taxon_dispositions import verify_recorded_taxon_inputs
    from tests.test_gold_taxon_dispositions import _report, _write

    source.run()
    report = _report(source)
    claims = rows(source.output_edge_file)
    # Two non-folded native referents leave the fold-specific verifier out of
    # this negative control: the finite Abscess proof must independently reject.
    locations = [
        row
        for row in claims
        if row["predicate"] == "biolink:located_in"
        and row["subject"] not in source._taxon_dispositions.index.historical_folds
    ]
    left, right = next((left, right) for left in locations for right in locations if left["object"] != right["object"])
    left["subject"], right["subject"] = right["subject"], left["subject"]
    _write(source.output_edge_file, list(claims[0]), claims)
    audit_path = source.output_dir / policy.AUDIT_FILE
    audit = rows(audit_path)
    changed_locations = [row for row in claims if row["predicate"] == "biolink:located_in"]
    for row in audit:
        row["retained_location_edges_json"] = canonical(changed_locations)
    _write(audit_path, policy.AUDIT_HEADER, audit)
    identity = SourceAdmission().capture(audit_path)
    report["producer_audit_members"][policy.AUDIT_FILE] = report["audit_members"][policy.AUDIT_FILE] = identity
    report["members"]["edges.tsv"] = SourceAdmission().capture(source.output_edge_file)
    with pytest.raises(SourceFinalizationRequired, match="audit source-owned"):
        verify_recorded_taxon_inputs(report, source.output_dir / "source_finalization.json")


@pytest.mark.parametrize("phase", ["emitter", "recorded"])
@pytest.mark.parametrize("spelling", ["canonical", "relation_only", "reverse_full_iri"])
def test_quarantined_bridge_cannot_reappear_in_actual_output(source, monkeypatch, phase, spelling):
    """Finite reviewed identity pairs stay absent even after callbacks or restamped member hashes (#1335)."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from tests.test_gold_taxon_dispositions import _report, _write

    def reintroduce():
        """Restore a prohibited identity bridge to the otherwise valid edge output."""
        claims = rows(source.output_edge_file)
        bridge = dict(next(iter(source._crosswalk_quarantine.proposals.values())))
        if spelling == "relation_only":
            bridge["predicate"] = "biolink:related_to"
        elif spelling == "reverse_full_iri":
            bridge["subject"], bridge["object"] = bridge["object"], bridge["subject"]
            bridge["predicate"] = "biolink:related_to"
            bridge["relation"] = "http://www.w3.org/2004/02/skos/core#exactMatch"
        claims.append({key: bridge.get(key, "") for key in claims[0]})
        _write(source.output_edge_file, list(claims[0]), claims)

    if phase == "emitter":
        original = source._write_nodes

        def mutate(*args):
            """Inject the prohibited bridge after normal producer emission."""
            original(*args)
            reintroduce()

        monkeypatch.setattr(source, "_write_nodes", mutate)
        with pytest.raises(SourceFinalizationRequired, match="quarantined identity bridge"):
            source.run()
    else:
        source.run()
        report = _report(source)
        reintroduce()
        report["members"]["edges.tsv"] = SourceAdmission().capture(source.output_edge_file)
        with pytest.raises(SourceFinalizationRequired, match="quarantined identity bridge"):
            GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


@pytest.mark.parametrize("field", [field for field in policy.AUDIT_HEADER if field != "ecosystem_id"])
def test_all_quarantine_fields_are_independently_required_after_restamping(source, field):
    """Neither lost evidence nor a restamped new claim can substitute for complete native rejoin (#1336)."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from tests.test_gold_taxon_dispositions import _report, _write

    source.run()
    report = _report(source)
    path = source.output_dir / policy.AUDIT_FILE
    audit = rows(path)
    audit[0][field] = "[]" if field.endswith("_json") else "changed"
    _write(path, policy.AUDIT_HEADER, audit)
    identity = SourceAdmission().capture(path)
    report["producer_audit_members"][policy.AUDIT_FILE] = report["audit_members"][policy.AUDIT_FILE] = identity
    with pytest.raises(SourceFinalizationRequired, match="GOLD Abscess audit"):
        GOLDTransform.verify_recorded_native_inputs(report, source.output_dir / "source_finalization.json")


def test_saved_admission_retains_actual_mesh_and_curation_inputs(source):
    """Full evidence verification keeps native locator/byte guards alive after the audit rejoin."""
    from tests.test_gold_taxon_dispositions import _report

    source.run()
    admission = GOLDTransform.verify_recorded_native_inputs(
        _report(source), source.output_dir / "source_finalization.json"
    )
    selected = source.input_base_dir / "mesh2026.nt.gz"
    with selected.open("ab") as stream:
        stream.write(b"drift")
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "renamed", "additional_parent", "assignment_changed"])
def test_native_cohort_changes_fail_before_graph_output(source, mutation):
    """No partly reviewed cohort, hidden multi-parent context, or changed assertion is admitted."""
    nodes = source.input_base_dir / "gold/GOLD_nodes.tsv"
    edges = source.input_base_dir / "gold/GOLD_edges.tsv"
    if mutation in {"missing", "duplicate", "renamed"}:
        lines = nodes.read_text().splitlines(keepends=True)
        selected = next(line for line in lines if line.startswith("gold.ecosystem:6338\t"))
        if mutation == "missing":
            lines.remove(selected)
        elif mutation == "duplicate":
            lines.append(selected)
        else:
            lines[lines.index(selected)] = selected.replace("\tAbscess\t", "\tOther condition\t")
        nodes.write_text("".join(lines))
    elif mutation == "additional_parent":
        with edges.open("a") as stream:
            stream.write(
                "adversarial\tgold.ecosystem:6338\tbiolink:subclass_of\tgold.ecosystem:6114\trdfs:subClassOf\tinfores:gold\n"
            )
    else:
        edges.write_text(edges.read_text().replace("gold:Go0001180-occurs_in", "changed-occurs_in", 1))
    with pytest.raises(ValueError):
        source.run()
    assert not source.output_edge_file.exists()
    assert not source.producer_audit_snapshots


@pytest.mark.parametrize("target", ["policy", "curation", "native_mesh", "target_label"])
def test_changed_authority_does_not_self_certify(source, tmp_path, monkeypatch, target):
    """Changed policy/native evidence cannot be accepted by updating only a supplied receipt."""
    if target == "policy":
        changed = json.loads(policy.POLICY_PATH.read_text())
        changed["native_selection_sha256"] = "0" * 64
        path = tmp_path / "changed_policy.json"
        path.write_text(json.dumps(changed))
        monkeypatch.setattr(policy, "POLICY_PATH", path)
    elif target == "curation":
        path = tmp_path / "changed_curation.tsv"
        path.write_text(policy.CURATION_PATH.read_text().replace("QUARANTINE_EXACT\t34", "SITE\t34"))
        monkeypatch.setattr(policy, "CURATION_PATH", path)
    elif target == "native_mesh":
        with gzip.open(source.input_base_dir / "mesh2026.nt.gz", "wb") as stream:
            stream.write((FIXTURE / "mesh.nt").read_bytes().replace(b'"Abscess"', b'"Changed"'))
    else:
        path = source.output_base_dir / "ontologies_stubs/mesh_nodes.tsv"
        path.write_text(path.read_text().replace("Abscess", "Changed"))
    with pytest.raises(ValueError):
        source.run()
    assert not source.output_edge_file.exists()


def test_constructor_cache_cannot_override_current_scope(source):
    """Run resets lexical/authority caches and cannot reuse a stale successful crosswalk."""
    source._mesh_sites = {"mesh:D000038"}
    source._label_index = {"abscess": "mesh:wrong"}
    source._envo_map = {"abscess": "ENVO:wrong"}
    source.run()
    assert len(rows(source.output_dir / policy.AUDIT_FILE)) == 7


def test_lost_location_assertion_cannot_complete(source, monkeypatch):
    """Even a downstream emission defect must fail the explicit 34-observation conservation gate."""
    original = policy.CrosswalkQuarantine.observe_location

    def lose_first(scope, native, emitted):
        """Suppress one required native location observation."""
        if native["subject"] != "gold:Go0001180":
            original(scope, native, emitted)

    monkeypatch.setattr(policy.CrosswalkQuarantine, "observe_location", lose_first)
    with pytest.raises(ValueError, match="exactly conserved"):
        source.run()
    assert not source.producer_audit_snapshots


def test_incomplete_proposal_cohort_cannot_complete(source, monkeypatch):
    """Skipping one proposed identity cannot silently pass as a clean completed source."""
    original = policy.CrosswalkQuarantine.intercept

    def skip_first(scope, identifier, label, target, proposal):
        """Omit one finite crosswalk proposal from the completed quarantine cohort."""
        if identifier != "gold.ecosystem:6338":
            return original(scope, identifier, label, target, proposal)
        return True

    monkeypatch.setattr(policy.CrosswalkQuarantine, "intercept", skip_first)
    with pytest.raises(ValueError, match="exactly seven"):
        source.run()
    assert not source.producer_audit_snapshots


def test_mutation_after_parser_snapshot_cannot_be_certified(source, monkeypatch):
    """Native bytes changing after parsing invalidate producer admission, even with intact output."""
    original = source._write_nodes

    def change_original(*args):
        """Change an original input after the parser has consumed its snapshot."""
        original(*args)
        path = source.input_base_dir / "gold/GOLD_edges.tsv"
        path.write_text(path.read_text() + "\n")

    monkeypatch.setattr(source, "_write_nodes", change_original)
    with pytest.raises((ValueError, SourceFinalizationRequired), match="changed"):
        source.run()
    assert not source.producer_audit_snapshots


def test_audit_tampering_is_not_reconstructed(source):
    """The mandatory audit is a producer product, not regenerable by merge admission."""
    source.run()
    path = source.output_dir / policy.AUDIT_FILE
    path.write_text(path.read_text() + "\n")
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(source)


def test_recorded_admission_requires_active_native_roles(source):
    """Removing active authority roles and forging an empty marker cannot hide the raw cohort."""
    source.run()
    report = {
        "consumed_inputs": source.consumed_input_snapshots,
        "producer_native_inputs": source.producer_native_inputs,
        "raw_input_directory": str(source.input_base_dir.resolve()),
    }
    policy.verify_recorded_inputs(report)
    del report["consumed_inputs"][policy.ACTIVE_INPUTS[0]]
    with pytest.raises(SourceFinalizationRequired, match="evidence incomplete"):
        policy.verify_recorded_inputs(report)
    report["producer_native_inputs"]["ecosystem_ids"] = []
    with pytest.raises(SourceFinalizationRequired, match="contract missing or changed"):
        policy.verify_recorded_inputs(report)


def test_empty_cohort_has_explicit_contract_and_header_only_audit(source):
    """No native MeSH file is required when there are genuinely no affected source concepts."""
    (source.input_base_dir / "gold/GOLD_nodes.tsv").write_text(
        (FIXTURE / "GOLD_nodes.tsv").read_text().splitlines()[0] + "\n"
    )
    (source.input_base_dir / "gold/GOLD_edges.tsv").write_text(
        (FIXTURE / "GOLD_edges.tsv").read_text().splitlines()[0] + "\n"
    )
    (source.input_base_dir / "mesh2026.nt.gz").unlink()
    source.run()
    assert rows(source.output_dir / policy.AUDIT_FILE) == []
    assert source.producer_native_inputs["expected_locations"] == 0
    assert source.producer_native_inputs["ecosystem_ids"] == []
    assert set(source.consumed_input_snapshots) == set(policy.REQUIRED_INPUTS) | {
        "gold_taxon_disposition_policy",
        "gold_taxon_disposition_ncbi",
        "gold_selected_taxon_alias_policy",
    }
    policy.verify_recorded_inputs(
        {
            "consumed_inputs": source.consumed_input_snapshots,
            "producer_native_inputs": source.producer_native_inputs,
            "raw_input_directory": str(source.input_base_dir.resolve()),
        }
    )


@pytest.mark.parametrize("mutation", ["header", "width", "new_abscess_id"])
def test_malformed_or_unreviewed_native_scope_fails_closed(source, mutation):
    """Strict source structure and finite identity prevent accidental scope expansion."""
    path = source.input_base_dir / "gold/GOLD_nodes.tsv"
    lines = path.read_text().splitlines(keepends=True)
    if mutation == "header":
        lines[0] = lines[0].replace("\tname\t", "\tid\t")
    elif mutation == "width":
        index = next(i for i, line in enumerate(lines) if line.startswith("gold.ecosystem:6338\t"))
        lines[index] = lines[index].rstrip("\n") + "\textra\n"
    else:
        lines.append("gold.ecosystem:unreviewed\tbiolink:EnvironmentalFeature\tAbscess\tinfores:gold\t\n")
    path.write_text("".join(lines))
    with pytest.raises(ValueError):
        source.run()
    assert not source.output_node_file.exists()


def test_failed_rerun_cannot_reuse_previous_audit_receipt(source):
    """Starting a real run invalidates an earlier success, including its producer audit."""
    source.run()
    assert source.producer_audit_snapshots
    path = source.input_base_dir / "gold/GOLD_nodes.tsv"
    path.write_text(path.read_text().replace("\tAbscess\t", "\tChanged\t", 1))
    with pytest.raises(ValueError):
        source.run()
    assert not source.producer_audit_snapshots
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(source)


def test_audit_symlink_is_rejected(source, tmp_path):
    """Audit publication cannot overwrite a symlink target or manufacture a successful receipt."""
    target = tmp_path / "untouched.txt"
    target.write_text("untouched\n")
    (source.output_dir / policy.AUDIT_FILE).symlink_to(target)
    with pytest.raises(SourceFinalizationRequired, match="symlink"):
        source.run()
    assert target.read_text() == "untouched\n"
    assert not source.producer_audit_snapshots


@pytest.mark.parametrize("origin", ["raw", "derived"])
def test_recorded_native_origins_cannot_be_substituted(source, tmp_path, origin):
    """Matching filenames elsewhere are not the producer's selected source or ontology export."""
    source.run()
    report = {
        "consumed_inputs": source.consumed_input_snapshots,
        "producer_native_inputs": source.producer_native_inputs,
        "raw_input_directory": str(source.input_base_dir.resolve()),
    }
    report_path = source.output_dir / "source_finalization.json"
    policy.verify_recorded_inputs(report, report_path)
    if origin == "raw":
        report["raw_input_directory"] = str(tmp_path / "different_raw")
    else:
        other = tmp_path / "other/ontologies_stubs/mesh_nodes.tsv"
        other.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE / "mesh_nodes.tsv", other)
        report["consumed_inputs"][policy.ACTIVE_INPUTS[1]]["path"] = str(other)
    with pytest.raises(SourceFinalizationRequired, match="differs from selected"):
        policy.verify_recorded_inputs(report, report_path)


def test_inert_fixture_helper_consumes_real_empty_sources(tmp_path):
    """Shared fake chains use the real reader/audit without modifying their artificial graph rows."""
    from kg_microbe.transform_utils.transform import Transform
    from tests.gold_fixtures import prepare_empty_gold_crosswalk_inputs

    transform = GOLDTransform.__new__(GOLDTransform)
    Transform.__init__(transform, "gold", tmp_path / "raw", tmp_path / "transformed")
    transform.output_node_file.write_text("id\tcategory\tname\nfixture:untouched\tbiolink:NamedThing\tUntouched\n")
    transform.output_edge_file.write_text("subject\tpredicate\tobject\n")
    original = transform.output_node_file.read_bytes()
    assert prepare_empty_gold_crosswalk_inputs(transform) == (
        *policy.REQUIRED_INPUTS,
        "gold_taxon_disposition_policy",
        "gold_selected_taxon_alias_policy",
    )
    assert transform.output_node_file.read_bytes() == original
    assert transform.producer_native_inputs["ecosystem_ids"] == []
    assert rows(transform.output_dir / policy.AUDIT_FILE) == []
    verify_producer_audits(transform)


def test_inert_fixture_helper_refuses_active_source(source):
    """A fixture cannot use an empty marker to bypass conservation of actual raw observations."""
    from tests.gold_fixtures import prepare_empty_gold_crosswalk_inputs

    with pytest.raises(AssertionError, match="Nonempty GOLD inputs"):
        prepare_empty_gold_crosswalk_inputs(source)


@pytest.mark.parametrize(
    "subject",
    [
        rb"<http://id.nlm.nih.gov/mesh/2026/D00003\u0038>",
        rb"<http://id.nlm.nih.gov/mesh/2026/D00003\U00000038>",
        b"<http://id.nlm.nih.gov/mesh/2025/D000038>",
        rb"<http://id.nlm.nih.gov/mesh/2026/D00003\uZZZZ>",
        rb"<http://id.nlm.nih.gov/mesh/2026/D00003\U00110000>",
        rb"<http://id.nlm.nih.gov/mesh/2026/D00003\uD800>",
    ],
)
def test_native_subject_spelling_cannot_hide_extra_claims(source, subject):
    """Finite membership recognizes RDF UCHAR spellings while keeping literal evidence unchanged."""
    path = source.input_base_dir / "mesh2026.nt.gz"
    statement = subject + b' <http://www.w3.org/2000/01/rdf-schema#label> "Adversarial extra assertion"@en .\n'
    path.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()) + statement, mtime=0))
    with pytest.raises(ValueError, match="MeSH"):
        source.run()
    assert not source.output_edge_file.exists()


@pytest.mark.parametrize("role", [*policy.ACTIVE_INPUTS, policy.ONTOLOGY_INPUT])
@pytest.mark.parametrize("mutation", ["remove", "restamp"])
def test_all_actual_read_roles_survive_until_producer_completion(source, monkeypatch, role, mutation):
    """Neither active nor optional-but-read authority bindings can disappear before audit capture."""
    if role == policy.ONTOLOGY_INPUT:
        # An empty, legal source RDF/XML is a structural negative control, not scientific evidence.
        (source.input_base_dir / "gold_ontology.owl").write_text(
            '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>\n'
        )
    original = source._run_snapshot

    def damage_read(*args):
        """Remove or rebind an actual-read role before producer completion."""
        original(*args)
        if mutation == "remove":
            source._consumed_input_snapshots.pop(role)
        else:
            source._consumed_input_snapshots[role]["sha256"] = "0" * 64

    monkeypatch.setattr(source, "_run_snapshot", damage_read)
    with pytest.raises(SourceFinalizationRequired, match="role missing or changed"):
        source.run()
    assert not source.producer_audit_snapshots


def test_recorded_optional_ontology_read_cannot_be_erased(source):
    """Optional authority, once read, remains part of recorded admission rather than a transient guard."""
    (source.input_base_dir / "gold_ontology.owl").write_text(
        '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>\n'
    )
    source.run()
    report = {
        "consumed_inputs": source.consumed_input_snapshots,
        "producer_native_inputs": source.producer_native_inputs,
        "raw_input_directory": str(source.input_base_dir.resolve()),
    }
    policy.verify_recorded_inputs(report)
    del report["consumed_inputs"][policy.ONTOLOGY_INPUT]
    with pytest.raises(SourceFinalizationRequired, match="ontology role missing or changed"):
        policy.verify_recorded_inputs(report)
