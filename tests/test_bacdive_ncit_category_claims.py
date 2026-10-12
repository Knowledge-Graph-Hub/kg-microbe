"""Four native leaf claims remain source observations with lossless upstream dispositions."""

import copy
import csv
import io
import json
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import isolation_categories as pride
from kg_microbe.transform_utils.bacdive import ncit_category_claims as claims
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform, load_metpo_metabolite_production_mappings
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.isolation_source_mapping_utils import load_isolation_source_mappings
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.test_bacdive_isolation_categories import _run

RESOURCE = Path(__file__).parent / "resources/bacdive_ncit_category_claims"


def records():
    """Use complete immutable native records, not a fabricated target-only biology excerpt."""
    return json.loads((RESOURCE / "records.json").read_text())["records"]


def run_native(tmp_path, monkeypatch, native):
    """Complete only unrelated source-constructor context omitted by the tiny run harness."""

    def context(transform, policy):
        """Supply only the offline context needed by the native category fixture."""
        transform.lpsn_name_index = {}
        transform.metpo_metabolite_production_mappings = load_metpo_metabolite_production_mappings()

    return _run(tmp_path, monkeypatch, native, during_prepare=context)


def test_complete_native_run_retains_four_observations_and_existing_pride_coordinates(tmp_path, monkeypatch):
    """Run all four complete records through the real producer with only unrelated ontology context stubbed."""
    native = records()
    before = copy.deepcopy(native)
    transform, edges, nodes, pride_audit = run_native(tmp_path, monkeypatch, native)
    nodes = list(graph_rows(transform.output_node_file, quoting=csv.QUOTE_MINIMAL))
    audit = list(graph_rows(transform.output_dir / claims.AUDIT_FILE))
    assert native == before
    assert len(audit) == 4
    assert {row["record_id"] for row in audit} == {"13026", "156949", "157411", "157533"}
    assert len({json.loads(row["emitted_node_json"])["id"] for row in audit}) == 4
    assert not any(row["subject"] in {"NCIT:C3824", "NCIT:C28176"} for row in edges)
    assert {json.loads(row["source_record_json"])["General"]["BacDive-ID"] for row in audit} == {
        13026,
        156949,
        157411,
        157533,
    }
    for row in audit:
        node, edge = json.loads(row["emitted_node_json"]), json.loads(row["emitted_edge_json"])
        assert any(all(found.get(key, "") == value for key, value in node.items()) for found in nodes)
        assert any(all(found.get(key, "") == value for key, value in edge.items()) for found in edges)
        assert node["category"] == "biolink:Attribute"
        assert node["has_attribute_type"] == pride.ATTRIBUTE_TYPE
        assert edge["knowledge_level"] == "observation"
        assert edge["primary_knowledge_source"] == "infores:bacdive"
        assert json.loads(row["original_mapping_json"])["predicate_id"] == "skos:exactMatch"
        assert json.loads(row["original_edge_json"])["predicate"] == "biolink:location_of"
    parasite = next(row for row in audit if row["record_id"] == "156949")
    assert (
        len(
            json.loads(parasite["source_record_json"])["Isolation, sampling and environmental information"]["isolation"]
        )
        == 2
    )
    preserved = [row for row in pride_audit if row["organism_id"] == "kgmicrobe.strain:bacdive_156949"]
    assert any(json.loads(row["source_path_json"])[-2:] == [1, "Cat1"] for row in preserved)
    transform.verify_native_inputs()
    assert not {"lesion incl. necrosis", "parasite"} & load_isolation_source_mappings().keys()


@pytest.mark.parametrize(
    "damage", ["new-record", "alias", "reorder", "reference", "duplicate", "removed-leaf", "wrong-field"]
)
def test_changed_eligible_records_fail_preflight_before_graph_output(tmp_path, monkeypatch, damage):
    """Finite approval does not expand to altered contexts, aliases or additional records."""
    native = records()
    selected = native[0]
    section = selected["Isolation, sampling and environmental information"]
    if damage == "new-record":
        selected["General"]["BacDive-ID"] = 999999
    elif damage == "alias":
        section["isolation source categories"][2]["Cat3"] = "#LESION (incl. Necrosis)"
    elif damage == "reorder":
        section["isolation source categories"].reverse()
    elif damage == "reference":
        selected["General"]["BacDive-ID"] = 13026
        selected["References"] = {"invented": "reference"}
    elif damage == "duplicate":
        native.append(copy.deepcopy(selected))
    elif damage == "removed-leaf":
        section["isolation source categories"][2].pop("Cat3")
    else:
        group = section["isolation source categories"][2]
        group["Cat4"] = group.pop("Cat3")
    with pytest.raises(SourceFinalizationRequired, match="finite NCIT"):
        _run(tmp_path, monkeypatch, native)
    assert not (tmp_path / "transformed/bacdive/nodes.tsv").exists()
    assert not (tmp_path / "transformed/bacdive/edges.tsv").exists()


@pytest.mark.parametrize("damage", ["delete", "target", "record", "policy-key"])
def test_policy_cannot_self_reauthorize_changed_scope(damage):
    """The complete four-rule native digest is independently anchored in producer code."""
    policy = json.loads(claims.POLICY_PATH.read_text())
    if damage == "delete":
        policy["rules"].pop()
    elif damage == "target":
        policy["rules"][0]["target"] = "NCIT:C28176"
    elif damage == "record":
        policy["rules"][0]["native_record_sha256"] = "0" * 64
    text = json.dumps(policy)
    if damage == "policy-key":
        text = text.replace('"version": 1', '"version": 1, "version": 1')
    with pytest.raises(SourceFinalizationRequired, match="policy"):
        claims.load_policy(io.StringIO(text))


def test_public_finalization_repeat_and_merge_admission(tmp_path, monkeypatch, local_source_schema):
    """Nonempty actual producer outputs must survive real finalization, repeat and read-only admission."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    report = transform.finalize()
    assert len(report["producer_native_inputs"]["selected_records"]) == 4
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    admission.verify()
    repeated = transform.finalize()
    assert repeated == report
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()


@pytest.mark.parametrize(
    "damage",
    [
        "audit-context",
        "audit-empty",
        "observation-name",
        "observation-category",
        "edge-object",
        "original-edge",
        "outgoing-identity",
        "type-missing",
    ],
)
def test_emitted_native_observations_cannot_be_laundered(tmp_path, monkeypatch, damage):
    """Raw producer verification rejoins all native and graph fields before finalization."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    audit = list(graph_rows(transform.output_dir / claims.AUDIT_FILE))
    attr = json.loads(audit[0]["emitted_node_json"])["id"]
    if damage.startswith("audit"):
        target = transform.output_dir / claims.AUDIT_FILE
        if damage == "audit-context":
            audit[0]["source_record_json"] = "{}"
        else:
            audit = []
        with target.open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=claims.AUDIT_FIELDS,
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
                quotechar=None,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(audit)
    else:
        target = (
            transform.output_node_file
            if damage.startswith("observation") or damage == "type-missing"
            else transform.output_edge_file
        )
        with target.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields, rows = reader.fieldnames, list(reader)
        if damage == "type-missing":
            rows = [row for row in rows if row["id"] != pride.ATTRIBUTE_TYPE]
        elif damage.startswith("observation"):
            row = next(row for row in rows if row["id"] == attr)
            row["name" if damage == "observation-name" else "category"] = "changed"
        elif damage == "edge-object":
            next(row for row in rows if row["object"] == attr)["object"] = "NCIT:C3824"
        elif damage == "original-edge":
            rows.append({field: json.loads(audit[0]["original_edge_json"]).get(field, "") for field in fields})
        else:
            row = next(row for row in rows if row["object"] == attr).copy()
            row.update(subject=attr, predicate="biolink:same_as", object="NCIT:C3824", relation="owl:sameAs")
            rows.append(row)
        with target.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    with pytest.raises(SourceFinalizationRequired, match="finite NCIT"):
        transform.verify_native_inputs()


@pytest.mark.parametrize(
    "damage", ["role-delete", "role-rebind", "cohort-clear", "context-change", "policy-change", "emission-clear"]
)
def test_live_cached_state_remains_bound_and_failures_sticky(tmp_path, monkeypatch, damage):
    """An in-memory false zero cannot replace the immutable actual-read contract."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    guard = transform._ncit_category_claim_guard
    if damage == "role-delete":
        transform._consumed_input_snapshots.pop(claims.ROLES[0])
    elif damage == "role-rebind":
        transform._consumed_input_snapshots[claims.ROLES[0]] = transform._consumed_input_snapshots[claims.ROLES[2]]
    elif damage == "cohort-clear":
        guard._selected = "[]"
        guard.emitted.clear()
    elif damage == "context-change":
        selected = json.loads(guard._selected)
        selected[0]["record"]["General"]["BacDive-ID"] = 123
        guard._selected = json.dumps(selected)
    elif damage == "policy-change":
        guard._policy = "{}"
    else:
        guard.emitted.clear()
    with pytest.raises(SourceFinalizationRequired, match="finite NCIT"):
        transform.verify_native_inputs()
    assert guard.failed
    with pytest.raises(SourceFinalizationRequired, match="prior finite-claim check"):
        transform.verify_native_inputs()


@pytest.mark.parametrize(
    "damage", ["contract-deleted", "contract-zero", "role-policy", "role-mapping", "role-raw", "rebound", "members"]
)
def test_recorded_admission_requires_actual_complete_roles_and_native_cohort(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Even internally consistent receipts cannot substitute an empty cohort or unrelated role."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    report = transform.finalize()
    if damage == "contract-deleted":
        report.pop("producer_native_inputs")
    elif damage == "contract-zero":
        report["producer_native_inputs"]["selected_records"] = []
    elif damage.startswith("role"):
        role = {"role-policy": claims.ROLES[0], "role-mapping": claims.ROLES[1], "role-raw": claims.ROLES[2]}[damage]
        report["consumed_inputs"].pop(role)
    elif damage == "rebound":
        report["consumed_inputs"][claims.ROLES[0]] = report["consumed_inputs"][claims.ROLES[2]]
    else:
        report["members"]["other_nodes.tsv"] = report["members"]["nodes.tsv"]
    with pytest.raises(ValueError, match="finite NCIT"):
        BacDiveTransform.verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


def test_truthful_zero_target_run_has_native_contract_and_audit(tmp_path, monkeypatch, local_source_schema):
    """Empty actual source still consumes all three roles and supplies a real header-only audit."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, [])
    report = transform.finalize()
    assert report["producer_native_inputs"]["selected_records"] == []
    assert list(graph_rows(transform.output_dir / claims.AUDIT_FILE)) == []
    assert set(report["producer_native_inputs"]["consumed_inputs"]) == set(claims.ROLES)
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("flag", ["completed", "producer-ready", "guard-ready", "both-ready"])
def test_completion_phase_reset_cannot_disable_output_checks(tmp_path, monkeypatch, flag):
    """Successful emission and output readiness are monotonic retained evidence (#1329)."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    guard = transform._ncit_category_claim_guard
    if flag == "completed":
        guard.completed = False
    if flag in {"producer-ready", "both-ready"}:
        transform._ncit_claim_output_ready = False
    if flag in {"guard-ready", "both-ready"}:
        guard._outputs_ready = False
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


@pytest.mark.parametrize("field", ["provided_by", "same_as", "xref", "synonym", "deprecated"])
def test_scoped_node_cannot_acquire_external_identity_or_provenance(tmp_path, monkeypatch, field):
    """The unresolved observation's complete base node metadata remains source-faithful."""
    transform, _, _, _ = run_native(tmp_path, monkeypatch, records())
    audit = list(graph_rows(transform.output_dir / claims.AUDIT_FILE))
    identifier = json.loads(audit[0]["emitted_node_json"])["id"]
    with transform.output_node_file.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        header, rows = reader.fieldnames, list(reader)
    next(row for row in rows if row["id"] == identifier)[field] = "NCIT:C3824"
    with transform.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(SourceFinalizationRequired, match="node changed"):
        transform.verify_native_inputs()
