"""Conserve PREGO observations while resolving only reviewed native ENVO identities."""

import copy
import csv
import hashlib
import io
import json
import tarfile
from collections import Counter

import pytest

from kg_microbe.transform_utils.prego import prego
from kg_microbe.transform_utils.prego.envo_identity import (
    POLICY_COLUMNS,
    POLICY_FILE,
    REVIEWED_ENVO_IDS,
    load_identity_decisions,
    record_digest,
)
from kg_microbe.transform_utils.prego.native_inputs import verify_native_contract
from kg_microbe.transform_utils.prego.utils import iter_database_pair_lines
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.prego_identity_fixtures import IDENTITY_FIXTURES, stage_prego_identity_inputs


def _inputs():
    """Read immutable exact native excerpts and the actual shipped policy."""
    with POLICY_FILE.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    return (
        rows,
        json.loads((IDENTITY_FIXTURES / "envo.json").read_text()),
        json.loads((IDENTITY_FIXTURES / "foodon.json").read_text()),
    )


def _load(rows=None, envo=None, foodon=None):
    """Invoke the production loader with isolated streams, never a permissive test replacement."""
    defaults = _inputs()
    rows, envo, foodon = [
        default if value is None else value for value, default in zip((rows, envo, foodon), defaults, strict=True)
    ]
    policy = io.StringIO()
    writer = csv.DictWriter(policy, fieldnames=POLICY_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    policy.seek(0)
    return load_identity_decisions(policy, io.StringIO(json.dumps(envo)), io.StringIO(json.dumps(foodon)))


def _records():
    """Return the recorded actual source rows, with their native channel identities."""
    return json.loads((IDENTITY_FIXTURES / "native-records.json").read_text())["records"]


def _write_archive(path, records):
    """Package explicit small test rows while preserving native column order and physical blanks."""
    payload = ("\n" + "".join("\t".join(row) + "\n" for row in records)).encode()
    with tarfile.open(path, "w:gz") as stream:
        member = tarfile.TarInfo("nested/database_pairs.tsv")
        member.size = len(payload)
        stream.addfile(member, io.BytesIO(payload))


def _producer(tmp_path, *, records=None, shapes="all", reverse=False, habitat_min_score=0):
    """Stage actual native records and evidence for a complete offline PREGO producer run."""
    raw = tmp_path / "raw"
    stage_prego_identity_inputs(raw)
    (raw / "prego").mkdir()
    records = _records() if records is None else records
    for channel in ("annotated_genomes_isolates", "environmental_samples"):
        selected = [item["row"] for item in records if item["channel"] == channel]
        _write_archive(raw / "prego" / f"{channel}.tar.gz", list(reversed(selected)) if reverse else selected)
    return prego.PregoTransform(raw, tmp_path / "transformed", shapes=shapes, habitat_min_score=habitat_min_score)


def _rows(path):
    """Read a bounded fixture TSV with full field names."""
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def test_complete_native_cohort_has_five_exact_and_five_unresolved():
    """Native consider annotations never become identity assertions, even for one candidate."""
    decisions = _load()
    assert set(decisions) == REVIEWED_ENVO_IDS
    assert Counter(item.disposition for item in decisions.values()) == {
        "replace_explicit_unique": 5,
        "retain_unresolved": 5,
    }
    assert decisions["ENVO:00002002"].target_id == "FOODON:00001002"
    assert decisions["ENVO:01000009"].target_id == "ENVO:01000009"
    assert decisions["ENVO:01000159"].target_id == "ENVO:01000159"
    with pytest.raises(TypeError):
        decisions["ENVO:1"] = decisions["ENVO:00002002"]


@pytest.mark.parametrize(
    "damage", ["delete_row", "header_only", "duplicate", "target", "consider", "digest", "disposition"]
)
def test_policy_damage_fails_closed(damage):
    """Incomplete, unsupported or changed finite policy rows cannot silently change identity."""
    rows, envo, foodon = _inputs()
    if damage == "delete_row":
        rows.pop()
    elif damage == "header_only":
        rows.clear()
    elif damage == "duplicate":
        rows.append(rows[0])
    else:
        key, value = {
            "target": ("replacement_id", "ENVO:01001814"),
            "consider": ("consider", "ENVO:01001814"),
            "digest": ("native_record_sha256", "a" * 64),
            "disposition": ("disposition", "same_as"),
        }[damage]
        rows[0][key] = value
    with pytest.raises(ValueError):
        _load(rows, envo, foodon)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "nonclass",
        "live",
        "bad_flag",
        "conflicting_flag",
        "two_targets",
        "consider_only",
        "duplicate",
        "empty",
    ],
)
def test_native_retirement_damage_fails_closed(damage):
    """No absent, malformed, conflicting or nonidentity authority becomes a replacement."""
    rows, envo, foodon = _inputs()
    nodes = envo["graphs"][0]["nodes"]
    old = next(node for node in nodes if node["id"].endswith("ENVO_00000373"))
    if damage == "missing":
        nodes.remove(old)
    elif damage == "nonclass":
        old["type"] = "PROPERTY"
    elif damage == "live":
        old["meta"]["deprecated"] = False
    elif damage == "bad_flag":
        old["meta"]["deprecated"] = "true"
    elif damage == "conflicting_flag":
        old["meta"]["basicPropertyValues"].append({"pred": "owl:deprecated", "val": "false"})
    elif damage == "two_targets":
        old["meta"]["basicPropertyValues"].append({"pred": "IAO:0100001", "val": "ENVO:01001814"})
    elif damage == "consider_only":
        old["meta"]["basicPropertyValues"][0]["pred"] = "http://www.geneontology.org/formats/oboInOwl#consider"
    elif damage == "duplicate":
        other = copy.deepcopy(old)
        other["lbl"] = "contradictory native record"
        nodes.append(other)
    else:
        envo["graphs"] = []
    with pytest.raises(ValueError):
        _load(rows, envo, foodon)


@pytest.mark.parametrize("damage", ["missing", "retired", "nonclass", "changed", "cycle"])
def test_native_successor_must_be_the_pinned_live_class(damage):
    """One-hop proof requires a present live target and never follows a replacement chain."""
    rows, envo, foodon = _inputs()
    nodes = envo["graphs"][0]["nodes"]
    target = next(node for node in nodes if node["id"].endswith("ENVO_01001851"))
    if damage == "missing":
        nodes.remove(target)
    elif damage == "retired":
        target.setdefault("meta", {})["deprecated"] = True
    elif damage == "nonclass":
        target["type"] = "INDIVIDUAL"
    elif damage == "changed":
        target["lbl"] = "different identity evidence"
    else:
        target.setdefault("meta", {}).update(
            {"deprecated": True, "basicPropertyValues": [{"pred": "IAO:0100001", "val": "ENVO:00000373"}]}
        )
        rows[0]["target_record_sha256"] = record_digest(target)
    with pytest.raises(ValueError):
        _load(rows, envo, foodon)


@pytest.mark.parametrize("shapes", ["all", "habitat"])
@pytest.mark.parametrize("reverse", [False, True])
def test_native_record_multiset_and_lossless_audit_survive(tmp_path, shapes, reverse):
    """Real cohort rows retain every evidence column; duplicates and converging identities survive."""
    records = _records()
    records.append(copy.deepcopy(records[0]))
    current = copy.deepcopy(records[0])
    current["row"][1] = "ENVO:01001851"
    records.append(current)
    transform = _producer(tmp_path, records=records, shapes=shapes, reverse=reverse)
    transform.run(show_status=False)
    edges = _rows(transform.output_edge_file)
    audit = _rows(transform.output_dir / "prego_envo_identity.tsv")
    decisions = _load()
    assert len(edges) == len(records) == 12
    assert len(audit) == 11
    assert len({row["source_assertion_id"] for row in audit}) == 11
    actual = Counter(
        (
            edge["subject"],
            edge["object"],
            edge["prego_source"],
            edge["prego_evidence"],
            edge["prego_score"],
            edge["prego_direct_flag"],
            edge["prego_evidence_url"],
            edge["prego_channel"],
        )
        for edge in edges
    )
    expected = Counter(
        (
            decisions[item["row"][1]].target_id if item["row"][1] in decisions else item["row"][1],
            "NCBITaxon:" + item["row"][3],
            *item["row"][4:],
            item["channel"],
        )
        for item in records
    )
    assert actual == expected
    assert all(edge["relation"] == "RO:0001015" and edge["predicate"] == "biolink:location_of" for edge in edges)
    for item in audit:
        native = json.loads(item["original_record_json"])
        emitted = json.loads(item["emitted_edge_json"])
        assert emitted in edges
        assert item["original_subject"] == native[1] == emitted["original_subject"]
        assert item["normalized_subject"] == emitted["subject"]
        assert int(item["physical_line"]) >= 2
        assert item["member"] == "nested/database_pairs.tsv"
        assert item["envo_sha256"] == hashlib.sha256((transform.input_base_dir / "envo.json").read_bytes()).hexdigest()
    nodes = {node["id"]: node for node in _rows(transform.output_node_file)}
    for decision in decisions.values():
        assert nodes[decision.target_id]["name"] == decision.name
        assert (nodes[decision.target_id]["deprecated"] == "True") == decision.deprecated
    assert "ENVO:00002002" not in nodes
    assert not nodes["FOODON:00001002"]["name"].startswith("obsolete")
    verify_producer_audits(transform)
    transform.verify_consumed_inputs()


def test_identity_only_applies_after_shape_type_and_score_eligibility(tmp_path):
    """Wrong type/prefix and low-score observations do not receive migration/audit decisions."""
    records = _records()
    wrong_type = copy.deepcopy(records[0])
    wrong_type["row"][0] = "-25"
    substring = copy.deepcopy(records[0])
    substring["row"][1] += "0"
    records += [wrong_type, substring]
    transform = _producer(tmp_path, records=records, shapes="habitat", habitat_min_score=1)
    transform.run(show_status=False)
    edges = _rows(transform.output_edge_file)
    audit = _rows(transform.output_dir / "prego_envo_identity.tsv")
    assert len(edges) == 5 and len(audit) == 4
    assert any(row["subject"] == substring["row"][1] and row["original_subject"] == "" for row in edges)
    assert all(json.loads(row["original_record_json"])[0] == "-27" for row in audit)


def test_same_size_payload_corruption_is_reextracted(tmp_path):
    """A cached member of the right size is not evidence of its archive's bytes."""
    transform = _producer(tmp_path)
    transform.run(show_status=False)
    before = transform.output_edge_file.read_bytes()
    payload = next(iter(transform._payload_cache.values()))
    original = payload.read_bytes()
    payload.write_bytes(original.replace(b"ENVO:00000373", b"ENVO:99999999"))
    assert payload.stat().st_size == len(original)
    transform.run(show_status=False)
    assert payload.read_bytes() == original
    assert transform.output_edge_file.read_bytes() == before


@pytest.mark.parametrize("damage", ["authority", "policy", "payload", "archive", "new_archive"])
def test_post_read_mutations_cannot_be_restamped(tmp_path, monkeypatch, damage):
    """Later input changes invalidate original read evidence and the archive selection contract."""
    policy = tmp_path / "policy.tsv"
    policy.write_bytes(POLICY_FILE.read_bytes())
    monkeypatch.setattr(prego, "POLICY_FILE", policy)
    transform = _producer(tmp_path)
    transform.run(show_status=False)
    if damage == "authority":
        path = transform.input_base_dir / "envo.json"
    elif damage == "policy":
        path = policy
    elif damage == "payload":
        path = next(iter(transform._payload_cache.values()))
    elif damage == "archive":
        path = next(iter(transform._payload_cache))
    else:
        path = transform.input_base_dir / "prego" / "literature.tar.gz"
    with path.open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["omit_archive", "omit_payload", "change_member", "missing_contract"])
def test_recorded_contract_requires_actual_dynamic_reads(tmp_path, damage):
    """Merge-time admission cannot certify a report omitting parsed payload identity."""
    transform = _producer(tmp_path, records=[])
    transform.run(show_status=False)
    contract, snapshots = transform.producer_native_inputs, transform.consumed_input_snapshots
    if damage == "missing_contract":
        contract = None
    elif damage == "change_member":
        next(iter(contract["archives"].values()))["member"] = "unrelated.tsv"
    else:
        prefix = "prego_archive_" if damage == "omit_archive" else "prego_payload_"
        snapshots.pop(next(role for role in snapshots if role.startswith(prefix)))
    with pytest.raises(SourceFinalizationRequired):
        verify_native_contract(contract, snapshots, transform.input_base_dir)


def test_empty_cohort_still_consumes_evidence_and_writes_required_audit(tmp_path):
    """Zero eligible observations is not permission to skip authorities or fabricate an audit."""
    transform = _producer(tmp_path, records=[])
    transform.run(show_status=False)
    assert _rows(transform.output_dir / "prego_envo_identity.tsv") == []
    assert set(transform.REQUIRED_CONSUMED_INPUTS) <= transform.consumed_input_snapshots.keys()
    verify_producer_audits(transform)
    transform._producer_audit_snapshots.clear()
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(transform)


def test_physical_lines_include_blank_and_malformed_native_records():
    """Audit positions come from physical source lines, never emitted-edge ordinals."""
    rows = list(
        iter_database_pair_lines(
            io.StringIO("\nmalformed\n\n-27\tENVO:00002002\t-2\t1\tJGI IMG\tIsolates\t3\tTRUE\t\n")
        )
    )
    assert [row[2] for row in rows] == [2, 4]
    assert rows[0][1] is not None and rows[1][1] is None


def test_authority_mutation_during_preflight_preserves_prior_graph(tmp_path, monkeypatch):
    """Authority read failures are preflighted before any old graph output is opened."""
    transform = _producer(tmp_path)
    transform.output_node_file.write_text("old nodes\n")
    transform.output_edge_file.write_text("old edges\n")
    original = prego.load_identity_decisions

    def mutate(*args):
        """Change selected bytes after the immutable helper read."""
        decisions = original(*args)
        path = transform.input_base_dir / "envo.json"
        path.write_text(path.read_text() + "\n")
        return decisions

    monkeypatch.setattr(prego, "load_identity_decisions", mutate)
    with pytest.raises(SourceFinalizationRequired):
        transform.run(show_status=False)
    assert transform.output_node_file.read_text() == "old nodes\n"
    assert transform.output_edge_file.read_text() == "old edges\n"


@pytest.mark.parametrize("damage", ["payload", "archive"])
def test_during_emission_mutation_prevents_completion(tmp_path, monkeypatch, damage):
    """A native input mutation mid-emission cannot certify the partial producer bundle."""
    transform = _producer(tmp_path)
    original = transform._process_row
    changed = False

    def mutate(*args, **kwargs):
        """Modify original selected bytes while the parser reads its immutable snapshot."""
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            path = next(iter(transform._payload_cache.values() if damage == "payload" else transform._payload_cache))
            with path.open("ab") as stream:
                stream.write(b"\n")
            changed = True
        return result

    monkeypatch.setattr(transform, "_process_row", mutate)
    with pytest.raises(SourceFinalizationRequired):
        transform.run(show_status=False)
    assert not transform.producer_audit_snapshots
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("name", ["envo.json", "foodon.json"])
def test_authority_symlink_retarget_does_not_launder_original_consumption(tmp_path, name):
    """Even identical replacement bytes do not preserve the selected authority locator binding."""
    transform = _producer(tmp_path, records=[])
    path = transform.input_base_dir / name
    initial = tmp_path / ("initial-" + name)
    alternate = tmp_path / ("alternate-" + name)
    initial.write_bytes(path.read_bytes())
    alternate.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(initial)
    transform.run(show_status=False)
    path.unlink()
    path.symlink_to(alternate)
    with pytest.raises(SourceFinalizationRequired, match="locator"):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize(
    "damage", ["audit_changed", "audit_missing", "payload_changed", "archive_added", "authority_changed"]
)
def test_public_finalization_and_readonly_admission_recheck_native_evidence(tmp_path, damage):
    """The registered producer's empty cohort exercises real finalization and merge admission."""
    transform = _producer(tmp_path, records=[])
    transform.run(show_status=False)
    report = transform.finalize(fresh_run=True)
    assert report["producer_native_inputs"] == transform.producer_native_inputs
    assert report["producer_audit_members"] == transform.producer_audit_snapshots
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    if damage.startswith("audit"):
        target = transform.output_dir / "prego_envo_identity.tsv"
    elif damage == "payload_changed":
        target = next(iter(transform._payload_cache.values()))
    elif damage == "authority_changed":
        target = transform.input_base_dir / "envo.json"
    else:
        target = transform.input_base_dir / "prego" / "literature.tar.gz"
    if damage == "audit_missing":
        target.unlink()
    else:
        with target.open("ab") as stream:
            stream.write(b"\n")
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
