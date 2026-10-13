"""Native RO assertions retain meaning, evidence and explicit model limitations."""

import copy
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.foodon_kernel_fixtures import prepare_empty_foodon_kernel_contract
from tests.ontology_parent_fixtures import prepare_empty_parent_contract

FIXTURE = Path(__file__).parent / "resources/native_ro_retention"
ORIGIN = json.loads((FIXTURE / "origin.json").read_text())
POLICY = json.loads(native.POLICY_FILE.read_text())


def fixture_policy():
    """
    Bind verbatim excerpts as their own release files, without claiming they are the full release.

    The excerpts carry the reviewed release and exactly the reviewed content, so only
    the upstream source binding is substituted (#1420).
    """
    policy = copy.deepcopy(POLICY)
    for filename, authority in policy["authorities"].items():
        evidence = ORIGIN["native_files"][filename]
        content = (FIXTURE / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == evidence["fixture_sha256"]
        [graph] = json.loads(content)["graphs"]
        assert graph["meta"]["version"] == authority["release"]
        assert native.selected_content_sha256(filename[:-5], graph) == authority["selected_sha256"]
        authority["source"] = {"file": filename, "sha256": evidence["fixture_sha256"]}
    return policy


def legacy_authorities(filenames):
    """Rebuild the whole-file authority pins that policies before version 3 carried."""
    return {
        filename: {
            "graph_id": POLICY["authorities"][filename]["graph_id"],
            "sha256": ORIGIN["native_files"][filename]["full_source_sha256"],
        }
        for filename in sorted(filenames)
    }


@pytest.mark.parametrize("damage", ["definition_hash", "authority_hash", "cohort", "strict_disposition"])
def test_restamped_policy_cannot_redefine_reviewed_native_evidence(damage):
    """Keep the code-anchored reviewed policy independent of self-authenticating receipts."""
    policy = copy.deepcopy(POLICY)
    if damage == "definition_hash":
        policy["relations"]["RO:0002216"]["native_node_sha256"] = "a" * 64
    elif damage == "authority_hash":
        policy["authorities"]["ro.json"]["selected_sha256"] = "a" * 64
    elif damage == "cohort":
        policy["records"][0]["object"] = "GO:9999999"
        policy["finite_cohort_sha256"] = native._digest(native._json(policy["records"]).encode())
    else:
        policy["strict_biolink_disposition"] = "passing"
    with pytest.raises(ValueError, match="Unreviewed native RO policy evidence"):
        native.load_policy(io.StringIO(json.dumps(policy)))


def prepare(tmp_path, monkeypatch, *, sources=("pato", "uberon"), policy=None):
    """Exercise actual consumed snapshots with faithful immutable offline evidence."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    for filename in POLICY["authorities"]:
        shutil.copyfile(FIXTURE / filename, raw / filename)
    policy = fixture_policy() if policy is None else policy
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(native, "POLICY_FILE", path)
    # The production policy digest pins complete native definitions and input
    # bytes. This explicit fixture-only digest binds the already verified,
    # separately identified excerpts; it is not a production escape hatch.
    monkeypatch.setattr(native, "REVIEWED_POLICY_SHA256", native._digest(native._json(policy).encode()))
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    prepare_empty_foodon_kernel_contract(transform)
    prepare_empty_parent_contract(transform)
    from tests.upa_route_fixtures import prepare_empty_upa_route_contract

    prepare_empty_upa_route_contract(transform)
    audit = io.StringIO()
    authority = native.NativeROPredicateRetention(transform, audit)
    for name in sources:
        private = authority.prepare_source(name, raw / (name + ".json"))
        assert private.read_bytes() == (raw / (name + ".json")).read_bytes()
        assert private != raw / (name + ".json")
    return transform, authority, audit


def frame(name, *, extra=True):
    """Construct only the documented prior converter projection from reviewed fixture records."""
    rows = [
        {
            "subject": row["subject"],
            "predicate": row["prior_predicate"],
            "object": row["object"],
            "relation": row["relation"],
            "primary_knowledge_source": "infores:" + name,
            "knowledge_level": "knowledge_assertion",
            "agent_type": "manual_agent",
        }
        for row in POLICY["records"] + POLICY["unchanged_records"]
        if row["ontology"] == name
    ]
    if extra:
        rows.append(
            {
                "subject": "fixture:1",
                "predicate": "biolink:participates_in",
                "object": "fixture:2",
                "relation": "RO:0000056",
                "primary_knowledge_source": "infores:" + name,
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
            }
        )
    return pd.DataFrame(rows)


def audit_rows(audit):
    """Read only small producer audit fixtures."""
    return list(csv.DictReader(io.StringIO(audit.getvalue()), delimiter="\t"))


def test_all326_are_changed_only_in_predicate_and_every_audit_rejoins_native(tmp_path, monkeypatch):
    """Preserve every nonpredicate field and every exact native assertion witness."""
    transform, authority, audit = prepare(tmp_path, monkeypatch)
    native_rows = {}
    for name in ("pato", "uberon"):
        document = json.loads((FIXTURE / (name + ".json")).read_text())
        native_rows[name] = document["graphs"][0]["edges"]
        before = frame(name)
        originals = before.copy()
        originals["converter_id"] = [f"literal-{name}-{i}" for i in before.index]
        retained = authority.project(name, before, originals, name + "_edges.tsv")
        expected = before.copy()
        membership = native._cohort(POLICY, name)
        selected = expected.apply(
            lambda row, membership=membership: (row["subject"], row["relation"], row["object"]) in membership, axis=1
        )
        expected.loc[selected, "predicate"] = expected.loc[selected, "relation"]
        pd.testing.assert_frame_equal(retained, expected)
        first_audit = audit.getvalue()
        pd.testing.assert_frame_equal(authority.project(name, retained, retained, name + "_edges.tsv"), retained)
        assert audit.getvalue() == first_audit
    authority.verify_complete()
    rows = audit_rows(audit)
    assert len(rows) == 326
    assert Counter(row["ontology"] for row in rows) == {"uberon": 252, "pato": 74}
    for row in rows:
        old, new = json.loads(row["canonical_prior_row_json"]), json.loads(row["retained_row_json"])
        assert new == {**old, "predicate": old["relation"]}
        assert json.loads(row["normalization_input_row_json"])["converter_id"].startswith("literal-")
        assert json.loads(row["native_assertion_json"]) in native_rows[row["ontology"]]
        assert row["native_authority_sha256"] == ORIGIN["native_files"][row["ontology"] + ".json"]["fixture_sha256"]
        assert row["strict_biolink_disposition"] == native.STRICT_DISPOSITION
        assert row["projection_action"] == "restore_native_predicate"
    assert set(transform.consumed_input_snapshots) == {
        "ontology_foodon_kernel_policy",
        "ontology_parent_disposition_policy",
        "upa_route_policy",
        native.POLICY_ROLE,
        "ontology_native_relation_pato",
        "ontology_native_relation_uberon",
        "ontology_native_relation_ro",
    }


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "object", "subject", "supplier", "predicate", "relation", "wrong_module"]
)
def test_bad_emitted_claims_refuse_before_any_retention_audit(tmp_path, monkeypatch, damage):
    """Reject missing, duplicated, changed and incorrectly attributed emitted claims."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    if damage == "missing":
        rows = rows.drop(index=0)
    elif damage == "duplicate":
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    elif damage in {"object", "subject"}:
        rows.loc[0, damage] = "fixture:unexpected"
    elif damage == "supplier":
        rows.loc[0, "primary_knowledge_source"] = "infores:uberon"
    elif damage == "predicate":
        rows.loc[0, "predicate"] = "biolink:related_to"
    elif damage == "relation":
        rows.loc[0, "relation"] = "RO:0000056"
    with pytest.raises(ValueError):
        authority.project("uberon" if damage == "wrong_module" else "pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


@pytest.mark.parametrize("filename", ["pato.json", "uberon.json", "ro.json", "envo.json", "mondo.json"])
def test_changed_native_bytes_do_not_get_restamped(tmp_path, monkeypatch, filename):
    """Refuse selected native byte drift before interpreting its declarations."""
    transform, authority, _ = prepare(tmp_path, monkeypatch, sources=())
    path = transform.input_base_dir / filename
    path.write_bytes(path.read_bytes() + b"\n")
    name = "pato" if filename == "ro.json" else Path(filename).stem
    with pytest.raises(ValueError, match="release file"):
        authority.prepare_source(name, transform.input_base_dir / (name + ".json"))


@pytest.mark.parametrize(
    "damage",
    [
        "missing_edge",
        "duplicate_edge",
        "missing_node",
        "obsolete_node",
        "property_endpoint",
        "wrong_graph",
        "duplicate_declaration",
    ],
)
def test_native_semantics_are_checked_beyond_fullfile_pins(tmp_path, monkeypatch, damage):
    """Challenge live native semantics even after explicit test-only full-file repinning."""
    transform, _, _ = prepare(tmp_path, monkeypatch, sources=())
    path = transform.input_base_dir / "pato.json"
    document = json.loads(path.read_text())
    graph = document["graphs"][0]
    edge = graph["edges"][0]
    node = next(node for node in graph["nodes"] if node["id"] == edge["sub"])
    if damage == "missing_edge":
        graph["edges"].pop(0)
    elif damage == "duplicate_edge":
        graph["edges"].append(copy.deepcopy(edge))
    elif damage == "missing_node":
        graph["nodes"].remove(node)
    elif damage == "obsolete_node":
        node.setdefault("meta", {})["deprecated"] = True
    elif damage == "property_endpoint":
        node["type"] = "PROPERTY"
    elif damage == "wrong_graph":
        graph["id"] = "http://example.org/unreviewed"
    else:
        graph["nodes"].append(copy.deepcopy(node))
    payload = json.dumps(document).encode()
    path.write_bytes(payload)
    policy = fixture_policy()
    policy["authorities"]["pato.json"]["source"]["sha256"] = hashlib.sha256(payload).hexdigest()
    native.POLICY_FILE.write_text(json.dumps(policy))
    monkeypatch.setattr(native, "REVIEWED_POLICY_SHA256", native._digest(native._json(policy).encode()))
    transform.begin_consumed_inputs()
    authority = native.NativeROPredicateRetention(transform, io.StringIO())
    with pytest.raises(ValueError):
        authority.prepare_source("pato", path)


@pytest.mark.parametrize("damage", ["policy", "native"])
def test_drift_after_preparation_fails_before_projection(tmp_path, monkeypatch, damage):
    """Bind read-time evidence through the write boundary without certifying edited inputs."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    path = native.POLICY_FILE if damage == "policy" else transform.input_base_dir / "pato.json"
    path.write_bytes(path.read_bytes() + b"\n")
    rows = frame("pato")
    with pytest.raises(SourceFinalizationRequired):
        authority.project("pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


def test_unemitted_prepared_source_cannot_complete(tmp_path, monkeypatch):
    """Preparation is not proof that its asserted cohort survived transformation."""
    _, authority, _ = prepare(tmp_path, monkeypatch, sources=("pato",))
    with pytest.raises(ValueError, match="not completely emitted"):
        authority.verify_complete()


def test_unprepared_protected_assertions_cannot_pass_direct_normalization(tmp_path):
    """Prevent convenience helpers from bypassing the run-owned evidence contract."""
    transform = OntologiesTransform(tmp_path / "raw", tmp_path / "transformed")
    path = transform.output_dir / "pato_edges.tsv"
    frame("pato").to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="prepared ontology run"):
        transform._normalize_schema(tmp_path / "absent_nodes.tsv", path)


def test_complete_run_orders_ro_first_without_changing_selected_modules(tmp_path, monkeypatch):
    """Establish RO freshness before its consumers while preserving the selected modules."""
    from kg_microbe.transform_utils.ontologies import ontologies_transform as module

    transform = OntologiesTransform(tmp_path / "raw", tmp_path / "transformed")
    selected = []
    monkeypatch.setattr(transform, "parse", lambda name, path, source: selected.append(name))
    transform.run()
    assert selected[0] == "ro"
    assert Counter(selected) == Counter(module.ONTOLOGIES_MAP.keys())
    assert set(transform.producer_audit_snapshots) == set(transform.REQUIRED_AUDIT_FILES)
    assert len((transform.output_dir / native.AUDIT_FILE).read_text().splitlines()) == 1


@pytest.mark.parametrize("damage", ["missing", "changed", "unrecorded"])
def test_empty_source_audit_is_mandatory_at_admission(tmp_path, damage):
    """Require header-only evidence even for the genuine unrelated fixture cohort."""
    from tests.test_merge_source_freshness import prepare_source

    transform = prepare_source(tmp_path, "ontologies", marker=False)
    path = transform.output_dir / native.AUDIT_FILE
    if damage == "unrecorded":
        transform._producer_audit_snapshots.pop(native.AUDIT_FILE)
        with pytest.raises(SourceFinalizationRequired):
            transform.finalize(fresh_run=True)
    else:
        if damage == "missing":
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b"changed\n")
        with pytest.raises(SourceFinalizationRequired):
            verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("name", ["pato", "uberon"])
def test_real_kgx_run_preserves_native_predicates_and_strict_rejection(tmp_path, monkeypatch, name):
    """Use a fresh pinned Toolkit, real private-copy parse and actual KGX predicate validation."""
    transform, _, _ = prepare(tmp_path, monkeypatch, sources=())
    script = """
import csv, json, socket, sys
from pathlib import Path
def offline(*args, **kwargs):
    raise AssertionError('Network prohibited in native RO regression')
socket.getaddrinfo = offline
socket.socket.connect = offline
from kg_microbe.utils import native_ro_retention as native
native.POLICY_FILE = Path(sys.argv[1])
native.REVIEWED_POLICY_SHA256 = sys.argv[5]
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils.biolink_model import prepare_kgx
prepare_kgx()
from kgx.validator import Validator
from bmt import Toolkit
transform = OntologiesTransform(Path(sys.argv[2]), Path(sys.argv[3]))
transform.run(data_file=sys.argv[4] + '.json')
with (transform.output_dir / (sys.argv[4] + '_edges.tsv')).open() as stream:
    rows = list(csv.DictReader(stream, delimiter='\\t'))
policy = json.loads(native.POLICY_FILE.read_text())
membership = native._cohort(policy, sys.argv[4])
selected = [row for row in rows if (row['subject'], row['relation'], row['object']) in membership]
assert len(selected) == {'pato': 74, 'uberon': 252}[sys.argv[4]]
controls = native._cohort(policy, sys.argv[4], 'unchanged_records')
untouched = [row for row in rows if (row['subject'], row['relation'], row['object']) in controls]
assert len(untouched) == {'pato': 3, 'uberon': 5}[sys.argv[4]]
assert all(row['predicate'] == 'biolink:temporally_related_to' for row in untouched)
assert all(row['predicate'] == row['relation'] for row in selected)
assert all(row['primary_knowledge_source'] == 'infores:' + sys.argv[4] for row in selected)
assert any(row['relation'] == 'RO:0000056' and row['predicate'] == 'biolink:participates_in' for row in rows)
from kg_microbe.merge_utils.local_context import local_prefix_context
with local_prefix_context():
    validator = Validator()
toolkit = Toolkit()
rejected = 0
for row in selected:
    validator.clear_errors()
    validator.validate_edge_predicate(row['subject'], row['object'], row, toolkit=toolkit)
    assert validator.errors['ERROR']['INVALID_EDGE_PREDICATE']
    rejected += 1
validator.clear_errors()
validator.validate_edge_predicate('fixture:1', 'fixture:2', {'predicate': 'biolink:participates_in'}, toolkit=toolkit)
assert not validator.errors
assert rejected == len(selected)
print(json.dumps({'retained': len(selected), 'strict_predicate_errors': rejected}))
"""
    model = FIXTURE.parent / "ingredient_bundle/native"
    result = subprocess.run(  # noqa: S603 - fixed local script and immutable offline fixtures
        [
            sys.executable,
            "-c",
            script,
            str(native.POLICY_FILE),
            str(transform.input_base_dir),
            str(tmp_path / "real-output"),
            name,
            native.REVIEWED_POLICY_SHA256,
        ],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str(model / "biolink-model.yaml"),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(model / "predicate_mapping.yaml"),
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for filename in POLICY["authorities"]:
        assert (transform.input_base_dir / filename).read_bytes() == (FIXTURE / filename).read_bytes()
