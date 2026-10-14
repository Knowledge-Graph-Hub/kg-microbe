"""UPA computed projections remain audited, without promoting xref substitutions to claims."""

import copy
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import upa_route_review as upa
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.upa_route_fixtures import prepare, prepare_empty_upa_route_contract, rows, run_upa, write_rows

# Exact full-native UER/ULS/UPA/xref-position/original/selected-GO tuples.
# Twelve native spellings represent seven route/canonical-target decisions;
# only seven (the historical last-xref selections) were writer claims.
FINITE_NATIVE_SPELLINGS = {
    ("UPA:UER00367", "UPA:ULS00165", "UPA:UPA00257", 1, "GO:0042282", "GO:0004420"),
    ("UPA:UER00879", "UPA:ULS00434", "UPA:UPA00904", 6, "GO:0043840", "GO:0004084"),
    ("UPA:UER00879", "UPA:ULS00434", "UPA:UPA00904", 8, "GO:0046571", "GO:0004084"),
    ("UPA:UER00846", "UPA:ULS00420", "UPA:UPA00869", 1, "GO:0047949", "GO:0102810"),
    ("UPA:UER00712", "UPA:ULS00393", "UPA:UPA00834", 12, "GO:0052622", "GO:0052622"),
    ("UPA:UER00712", "UPA:ULS00393", "UPA:UPA00834", 13, "GO:0052623", "GO:0052622"),
    ("UPA:UER00448", "UPA:ULS00213", "UPA:UPA00051", 12, "GO:0052622", "GO:0052622"),
    ("UPA:UER00448", "UPA:ULS00213", "UPA:UPA00051", 13, "GO:0052623", "GO:0052622"),
    ("UPA:UER00587", "UPA:ULS00278", "UPA:UPA00529", 15, "GO:0033709", "GO:0033709"),
    ("UPA:UER00587", "UPA:ULS00278", "UPA:UPA00529", 27, "GO:0052677", "GO:0033709"),
    ("UPA:UER00134", "UPA:ULS00055", "UPA:UPA00074", 2, "GO:0018271", "GO:0004077"),
    ("UPA:UER00134", "UPA:ULS00055", "UPA:UPA00074", 4, "GO:0071734", "GO:0004077"),
}


def finite_spellings(candidates):
    """Read actual full candidate witnesses without collapsing repeated native occurrences."""
    return Counter(
        (
            witness["node"],
            witness["step"],
            witness["pathway"],
            witness["xref_position"],
            witness["xref"]["val"],
            witness["go_identity"]["canonical_id"],
        )
        for candidate in candidates
        for witness in candidate["witnesses"]
        if witness["exclusion_rule"]
    )


def evidence(transform):
    """Decode the complete actual producer audit without collapsing occurrences."""
    return [
        (row["record_kind"], json.loads(row["evidence_json"]))
        for row in rows(transform.output_dir / upa.AUDIT_FILE, quoted=True)
    ]


def actual_authority(transform):
    """Use the same existing GO resolver over literal fixture SQL, not mocked resolutions."""
    path = transform.input_base_dir / "go.db"
    identity = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        return upa._authority(connection, identity)


def test_actual_writer_excludes_seven_and_inventories_all_twelve_native_representations(tmp_path, monkeypatch):
    """The actual tiny native parse conserves complete multiplicity and makes no missing-edge promotions."""
    transform, policy, _, _ = run_upa(tmp_path, monkeypatch)
    audit = evidence(transform)
    candidates = [row for kind, row in audit if kind == "candidate"]
    selected = [row for kind, row in audit if kind == "generated"]
    exclusions = [row for row in selected if row["disposition"] == "quarantined_reaction_context"]
    assert len(exclusions) == 7
    assert len({row["candidate_key"][0] + "|" + row["candidate_key"][2] for row in exclusions}) == 7
    assert finite_spellings(candidates) == Counter({row: 1 for row in FINITE_NATIVE_SPELLINGS})
    assert {witness["exclusion_rule"] for row in exclusions for witness in row["witnesses"]} == {
        rule["id"] for rule in policy["rules"]
    }
    assert all(row["original_row"] and row["witnesses"] and row["expected_normalized_candidate"] for row in selected)
    retained = [row for row in rows(transform.output_dir / "upa_edges.tsv", quoted=True) if upa._family(row)]
    assert len(retained) == len([row for row in selected if row["disposition"].startswith("retained_")])
    assert len(candidates) > len(selected)
    assert Counter(row["predicate"] for row in retained) == {"biolink:related_to": 1}
    audit_only = [row for row in selected if row["disposition"] == "audit_only_unverified_xref_substitution"]
    assert len(audit_only) == 1
    assert audit_only[0]["kind"] == "computed"
    assert audit_only[0]["original_row"]["predicate"] == "biolink:part_of"
    assert audit_only[0]["expected_normalized_candidate"]["predicate"] == "biolink:part_of"
    assert all(witness["route"] == "enzyme_xref_two_hop" for witness in audit_only[0]["witnesses"])
    assert all(row["relation"] == "biolink:related_to" for row in retained if row["predicate"] == "biolink:related_to")
    assert set(upa._owned(transform.consumed_input_snapshots)) == set(upa.ROLES)
    assert (
        transform.consumed_input_snapshots[upa.JSON_ROLE]["path"]
        != transform.consumed_input_snapshots[upa.PROCESSED_ROLE]["path"]
    )
    assert (transform.input_base_dir / "upa.json").read_bytes() == (
        transform.output_dir
        / ".ontology-inputs"
        / transform.consumed_input_snapshots[upa.JSON_ROLE]["sha256"]
        / "upa.json"
    ).read_bytes()
    intermediate_path = transform.consumed_input_snapshots[upa.INTERMEDIATE_ROLE]["path"]
    intermediate = json.loads(Path(intermediate_path).read_text())
    native_pair = next(row for row in intermediate if row["subject"] == "OBO:UPa_UER00134")
    assert native_pair["object"] == "OBO:UPa_ULS00055"
    assert (native_pair["predicate"], native_pair["relation"]) == ("biolink:part_of", "BFO:0000050")
    transform.verify_native_inputs()


def test_original_and_current_go_spellings_are_both_excluded_only_on_the_exact_route(tmp_path, monkeypatch):
    """Current-ID reintroduction cannot bypass the seven normalized route decisions."""
    transform, policy, _ = prepare(tmp_path, monkeypatch)
    document = json.loads((transform.input_base_dir / "upa.json").read_text())
    candidates = upa.enumerate_candidates(document, actual_authority(transform), policy)
    for candidate in candidates:
        if not any(witness["exclusion_rule"] for witness in candidate["witnesses"]):
            continue
        subject, predicate, obj = candidate["key"]
        claim = {"subject": subject, "predicate": predicate, "object": obj, "relation": "BFO:0000050"}
        keep, audit = upa._screen([claim], candidates)
        assert keep == [] and audit[0]["original_row"] == claim
    excluded = [row for row in candidates if any(item["exclusion_rule"] for item in row["witnesses"])]
    assert len(excluded) == len(FINITE_NATIVE_SPELLINGS) == 12
    assert finite_spellings(candidates) == Counter({row: 1 for row in FINITE_NATIVE_SPELLINGS})
    assert sum(row["key"][0] in {"GO:0052622", "GO:0033709"} for row in excluded) == 3


@pytest.mark.parametrize(
    ("original", "canonical"),
    [("GO:0043840", "GO:0004084"), ("GO:0018271", "GO:0004077")],
)
def test_additional_historical_spellings_have_literal_native_replacement_rows(
    tmp_path, monkeypatch, original, canonical
):
    """The two previously uncounted spellings follow native evidence, not a changed exclusion rule."""
    transform, _, _ = prepare(tmp_path, monkeypatch)
    database = transform.input_base_dir / "go.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        statements = list(
            connection.execute("SELECT subject,predicate,object,value FROM statements WHERE subject=?", (original,))
        )
    assert (original, "owl:deprecated", None, "true") in statements
    assert (original, "IAO:0100001", canonical, None) in statements
    resolution = actual_authority(transform).resolve(original)
    assert resolution.canonical_id == canonical
    assert resolution.replacement_chain == (original, canonical)


def test_multivalued_routes_preserve_duplicate_occurrences_and_do_not_depend_on_last_xref(tmp_path, monkeypatch):
    """The audit collector is complete even though admission of additional graph edges remains pending."""
    transform, policy, _ = prepare(tmp_path, monkeypatch)
    document = json.loads((transform.input_base_dir / "upa.json").read_text())
    authority = actual_authority(transform)
    original = upa.enumerate_candidates(document, authority, policy)
    altered = copy.deepcopy(document)
    node = next(row for row in altered["graphs"][0]["nodes"] if row["id"].endswith("UER00367"))
    node["meta"]["xrefs"].append({"val": "EC:1.1.1.88"})
    assert {tuple(row["key"]) for row in upa.enumerate_candidates(altered, authority, policy)} == {
        tuple(row["key"]) for row in original
    }
    node["meta"]["xrefs"].append({"val": "GO:0042282"})
    duplicated = upa.enumerate_candidates(altered, authority, policy)
    candidate = next(row for row in duplicated if row["key"][0] == "GO:0042282")
    assert len(candidate["witnesses"]) == 2
    assert len({witness["xref_position"] for witness in candidate["witnesses"]}) == 2
    altered["graphs"][0]["edges"].reverse()
    assert Counter(tuple(row["key"]) for row in upa.enumerate_candidates(altered, authority, policy)) == Counter(
        tuple(row["key"]) for row in duplicated
    )


def test_mixed_reviewed_and_new_witness_does_not_silently_override_a_finite_exclusion(tmp_path, monkeypatch):
    """A future extra route requires review, rather than blanket deletion or unreviewed rescue."""
    transform, policy, _ = prepare(tmp_path, monkeypatch)
    document = json.loads((transform.input_base_dir / "upa.json").read_text())
    candidates = upa.enumerate_candidates(document, actual_authority(transform), policy)
    selected = next(row for row in candidates if row["key"][0] == "GO:0042282")
    other = copy.deepcopy(selected["witnesses"][0])
    other["exclusion_rule"] = None
    selected["witnesses"].append(other)
    subject, predicate, obj = selected["key"]
    with pytest.raises(SourceFinalizationRequired, match="mixed"):
        upa._screen(
            [{"subject": subject, "predicate": predicate, "object": obj, "relation": "BFO:0000050"}], candidates
        )


def test_unverified_projection_audit_preserves_repeated_rows_and_qualifiers(tmp_path, monkeypatch):
    """Audit-only is not triple dedup, field loss, or a claim that the native evidence is false."""
    transform, policy, _ = prepare(tmp_path, monkeypatch)
    document = json.loads((transform.input_base_dir / "upa.json").read_text())
    candidates = upa.enumerate_candidates(document, actual_authority(transform), policy)
    selected = next(
        row
        for row in candidates
        if row["key"][1] == "biolink:part_of" and not any(w["exclusion_rule"] for w in row["witnesses"])
    )
    subject, predicate, obj = selected["key"]
    original = {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "relation": "BFO:0000050",
        "primary_knowledge_source": "infores:upa",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
        "qualifier": "literal|not-normalized",
        "publications": "PMID:fixture",
    }
    records = [original, dict(original), {**original, "qualifier": "different"}]
    before = copy.deepcopy(records)
    keep, audit = upa._screen(records, candidates)
    assert keep == []
    assert [row["position"] for row in audit] == [0, 1, 2]
    assert [row["original_row"] for row in audit] == before == records
    assert all(row["disposition"] == "audit_only_unverified_xref_substitution" for row in audit)
    assert all(row["witnesses"] == selected["witnesses"] for row in audit)


@pytest.mark.parametrize(
    "damage", ["policy", "json", "json_release", "owl", "go_release", "go_owl", "sidecar", "duplicate_json_key"]
)
def test_original_native_evidence_failures_abort_the_actual_run(tmp_path, monkeypatch, damage):
    """
    A different release, other bytes or a malformed native object cannot stand in for the reviewed epoch.

    The locally built go.db is bound by release and content, not bytes (#1420). The converted
    upa.json keeps its byte pin as well as its release, since the pinned ROBOT reproduces it
    from the pinned upa.owl (#1516).
    """
    transform, _, policy_path = prepare(tmp_path, monkeypatch)
    if damage == "policy":
        policy_path.write_text("{}")
    elif damage == "sidecar":
        (transform.input_base_dir / "go.db-wal").write_bytes(b"unexpected")
    elif damage == "json_release":
        path = transform.input_base_dir / "upa.json"
        path.write_bytes(path.read_bytes().replace(b"releases/2024-03-06", b"releases/2099-01-01", 1))
    elif damage == "go_release":
        with sqlite3.connect(transform.input_base_dir / "go.db") as connection:
            connection.execute("UPDATE statements SET value='2099-01-01' WHERE predicate='owl:versionInfo'")
    elif damage == "go_owl":
        path = transform.input_base_dir / "go.owl"
        path.write_bytes(path.read_bytes() + b"<!-- another release -->\n")
    else:
        filename = {"json": "upa.json", "owl": "upa.owl", "duplicate_json_key": "upa.json"}[damage]
        path = transform.input_base_dir / filename
        payload = path.read_bytes()
        path.write_bytes(
            payload.replace(b'"graphs":', b'"graphs":[],"graphs":', 1)
            if damage == "duplicate_json_key"
            else payload + b" "
        )
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        transform.run(data_file="upa.json", show_status=False)
    assert not (transform.output_dir / "upa_source_finalization.json").exists()


def test_a_same_release_upa_json_with_a_changed_xref_is_refused(tmp_path, monkeypatch):
    """One changed pathway xref in a JSON that still declares the reviewed release is refused (#1516)."""
    transform, _, _ = prepare(tmp_path, monkeypatch)
    path = transform.input_base_dir / "upa.json"
    document = json.loads(path.read_text())
    node = next(node for node in document["graphs"][0]["nodes"] if node["id"].endswith("UPa_UPA00450"))
    assert [xref["val"] for xref in node["meta"]["xrefs"]] == ["GO:0033353"]
    node["meta"]["xrefs"][0]["val"] = "GO:0004077"
    path.write_text(json.dumps(document))
    with pytest.raises(SourceFinalizationRequired, match="source epoch changed"):
        transform.run(data_file="upa.json", show_status=False)
    assert not (transform.output_dir / "upa_source_finalization.json").exists()


def test_a_same_release_go_db_missing_a_selected_statement_is_refused(tmp_path, monkeypatch):
    """With no go.db byte pin, the selected GO statements alone catch a changed database (#1517)."""
    transform, policy, _ = prepare(tmp_path, monkeypatch)
    subject, predicate = policy["finite_go_statements"][0][:2]
    with sqlite3.connect(transform.input_base_dir / "go.db") as connection:
        rowid = connection.execute(
            "SELECT rowid FROM statements WHERE subject=? AND predicate=? LIMIT 1", (subject, predicate)
        ).fetchone()[0]
        connection.execute("DELETE FROM statements WHERE rowid=?", (rowid,))
    with pytest.raises(SourceFinalizationRequired, match="finite GO"):
        transform.run(data_file="upa.json", show_status=False)
    assert not (transform.output_dir / "upa_source_finalization.json").exists()


@pytest.mark.parametrize("role", upa.ROLES)
def test_deleted_actual_read_roles_refuse_even_after_graph_completion(tmp_path, monkeypatch, role):
    """All native, processed and producer-derived inputs remain mandatory after completion."""
    transform, _, _, _ = run_upa(tmp_path, monkeypatch)
    del transform._consumed_input_snapshots[role]
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


def test_caught_selector_failure_stays_failed_after_restore_but_new_run_recovers(tmp_path, monkeypatch):
    """An observed locator change is sticky only for that source invocation."""
    transform, _, policy_path, _ = run_upa(tmp_path, monkeypatch)
    alternative = policy_path.with_name("same-policy-different-locator.json")
    alternative.write_bytes(policy_path.read_bytes())
    monkeypatch.setattr(upa, "POLICY_FILE", alternative)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        transform.verify_native_inputs()
    monkeypatch.setattr(upa, "POLICY_FILE", policy_path)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        transform.verify_native_inputs()
    fresh = OntologiesTransform(transform.input_base_dir, tmp_path / "new-run")
    fresh.run(data_file="upa.json", show_status=False)
    fresh.verify_native_inputs()


@pytest.mark.parametrize(
    "damage",
    [
        "witness",
        "generated",
        "intermediate",
        "clear_completion_then_graph",
        "reintroduced_current_id",
        "reintroduced_unverified",
    ],
)
def test_cached_or_graph_tampering_cannot_bypass_the_actual_native_rejoin(tmp_path, monkeypatch, damage):
    """Completion flags do not authorize rewritten metadata, lost evidence or excluded edges."""
    transform, policy, _, _ = run_upa(tmp_path, monkeypatch)
    guard = transform._upa_route_input_contract
    if damage == "witness":
        guard._candidate_records[0]["witnesses"][0]["xref_position"] += 1
    elif damage == "generated":
        guard._generated[0]["rows"][0]["primary_knowledge_source"] = "infores:invented"
    elif damage == "intermediate":
        guard._intermediate[0]["relation"] = "biolink:related_to"
    else:
        path = transform.output_dir / "upa_edges.tsv"
        current = rows(path, quoted=True)
        if damage == "clear_completion_then_graph":
            guard._final_seal = None
            current[0]["primary_knowledge_source"] = "infores:invented"
        elif damage == "reintroduced_unverified":
            original = next(
                row["original_row"]
                for item in guard._generated
                for row in item["dispositions"]
                if row["disposition"] == "audit_only_unverified_xref_substitution"
            )
            current.append({column: original.get(column, "") for column in current[0]})
        else:
            rule = policy["rules"][0]
            row = {column: "" for column in current[0]}
            row.update(
                subject=rule["canonical_go"],
                predicate="biolink:part_of",
                object=rule["pathway"],
                relation="BFO:0000050",
                primary_knowledge_source="infores:upa",
                knowledge_level="knowledge_assertion",
                agent_type="manual_agent",
            )
            current.append(row)
        write_rows(path, current, quoted=True)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        transform.verify_native_inputs()


def test_actual_public_finalize_repeat_and_retained_late_admission(tmp_path, monkeypatch):
    """Public contracts preserve source history and exact UPA scope on a fresh repeat."""
    transform, _, _, report = run_upa(tmp_path, monkeypatch, finalize=True)
    paths = [transform.output_dir / name for name in upa.MEMBERS]
    verify_finalized_source_files(paths)
    repeat = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
    repeated = repeat.finalize(file_prefix="upa_")
    assert repeated["producer_native_inputs"] == report["producer_native_inputs"]
    admission = SourceAdmission()
    OntologiesTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "upa_source_finalization.json", admission=admission
    )
    admission.verify()
    (transform.input_base_dir / "go.db-shm").write_bytes(b"late")
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        admission.verify()
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        repeat.verify_native_inputs()


def test_a_bound_go_db_sqlite_cannot_read_is_a_clean_refusal(tmp_path, monkeypatch):
    """A SQLite error during recorded admission is refused like any other contract failure (#1552)."""
    transform, _, _, report = run_upa(tmp_path, monkeypatch, finalize=True)

    def broken(*args, **kwargs):
        """Stand in for a bound go.db SQLite cannot read."""
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(upa.sqlite3, "connect", broken)
    with pytest.raises(SourceFinalizationRequired, match="UPA admitted GO database cannot be read") as info:
        OntologiesTransform.verify_recorded_native_inputs(report, transform.output_dir / "upa_source_finalization.json")
    assert isinstance(info.value.__cause__, sqlite3.DatabaseError)


@pytest.mark.parametrize("damage", ["contract", "audit", "roles", "witness", "wrong_scope"])
def test_recorded_class_hook_refuses_missing_contract_or_evidence(tmp_path, monkeypatch, damage):
    """The producer hook independently checks native scope; public counterpart tests are separate."""
    transform, _, _, original = run_upa(tmp_path, monkeypatch, finalize=True)
    report = copy.deepcopy(original)
    if damage == "contract":
        del report["producer_native_inputs"]["upa_route_review"]
    elif damage == "roles":
        report["consumed_inputs"] = {
            key: value for key, value in report["consumed_inputs"].items() if key not in upa.ROLES
        }
    elif damage == "wrong_scope":
        report["producer_native_inputs"]["upa_route_review"] = upa.contract(())
    elif damage == "audit":
        (transform.output_dir / upa.AUDIT_FILE).unlink()
    else:
        path = transform.output_dir / upa.AUDIT_FILE
        current = rows(path, quoted=True)
        claim = json.loads(current[0]["evidence_json"])
        claim["witnesses"][0]["native_nodes"][0]["record"]["lbl"] = "invented"
        current[0]["evidence_json"] = json.dumps(claim)
        write_rows(path, current, quoted=True)
    with pytest.raises((SourceFinalizationRequired, ValueError, FileNotFoundError)):
        OntologiesTransform.verify_recorded_native_inputs(report, transform.output_dir / "upa_source_finalization.json")


def test_genuine_non_upa_zero_reads_only_policy_and_rejects_late_added_owned_role(tmp_path):
    """Unrelated native sources do not require UPA/GO inputs, but zero is not a skip switch."""
    raw = tmp_path / "raw"
    raw.mkdir()
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    assert prepare_empty_upa_route_contract(transform) == (upa.POLICY_ROLE,)
    transform.verify_native_inputs()
    audit = evidence(transform)
    assert len(audit) == 1 and audit[0][1]["candidate_count"] == 0
    assert audit[0][1]["contract"]["members"] == []
    transform._consumed_input_snapshots[upa.GO_ROLE] = dict(transform.consumed_input_snapshots[upa.POLICY_ROLE])
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


def test_policy_and_native_json_duplicate_keys_are_rejected_without_last_value_wins():
    """Outer wrapper keys and selected native metadata receive the same strict decoding."""
    for payload in ('{"graphs":[],"graphs":[{}]}', '{"meta":{"type":"PROPERTY","type":"CLASS"}}'):
        with pytest.raises(SourceFinalizationRequired, match="Duplicate"):
            upa.decode(payload)


def test_original_alternative_id_context_is_preserved_in_exclusion_evidence(tmp_path, monkeypatch):
    """GO:0042282 uses its actual alternative-ID owner, not an invented replaced_by claim."""
    transform, _, _, _ = run_upa(tmp_path, monkeypatch)
    claim = next(
        row
        for kind, row in evidence(transform)
        if kind == "generated" and row["original_row"]["subject"] == "GO:0042282"
    )
    normalized = claim["expected_normalized_candidate"]
    assert normalized["subject"] == "GO:0004420"
    assert normalized["original_subject"] == "GO:0042282"
    assert json.loads(normalized["go_reference_context"])[0]["replacement_chain"] == ["GO:0042282", "GO:0004420"]
