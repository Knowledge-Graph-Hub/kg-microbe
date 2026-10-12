"""Finite NCIT category changes preserve native evidence, source meaning and admission guards."""

import copy
import gzip
import io
import json
import shutil
import sqlite3

import pytest

from kg_microbe.utils import ncit_eight_categories as finite
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.go_subject_restrictions_fixtures import write_rows
from tests.ncit_eight_fixtures import POLICY, SOURCE_ROWS, prepare


@pytest.mark.parametrize("identifier", sorted(finite.FINITE_IDS))
def test_all_finite_real_native_decisions_and_definition_absence(tmp_path, monkeypatch, identifier):
    """All selected primary declarations are read from actual SQLite, not mock category returns."""
    _, _, policy, transform, authority = prepare(tmp_path, monkeypatch)
    expected = policy["records"][identifier]["category"]
    assert authority.category_for(identifier) == expected
    assert json.loads(authority._evidence_json) == POLICY["native_statements"]
    assert authority.contract()["identifiers"] == [identifier]
    authority.verify(transform.consumed_input_snapshots)
    for existing in ("", "biolink:NamedThing", "biolink:OntologyClass", expected, expected + "|biolink:OntologyClass"):
        assert finite.apply_category(existing, expected) == expected
    if identifier in {"NCIT:C71971", "NCIT:C72000", "NCIT:C72005", "NCIT:C77500", "NCIT:C85253", "NCIT:C87343"}:
        assert policy["records"][identifier]["native_definitions"] == []
    if identifier == "NCIT:C72005":
        assert policy["records"][identifier]["native_semantic_types"] == ["Food", "Plant"]


@pytest.mark.parametrize("identifier", ["NCIT:C71939", "NCIT:C16883", "NCIT:C62695", "NCIT:C14234", "CHEBI:1"])
def test_unrelated_and_previous_two_concepts_do_not_open_new_native_authority(tmp_path, identifier):
    """No parent propagation, previous two-policy changes, or OAK-cache dependency is introduced."""

    def forbidden(path):
        """Reject unexpected authority reads for unselected identifiers."""
        raise AssertionError(f"Unexpected authority read: {path}")

    authority = finite.FiniteNcitCategoryAuthority(tmp_path, opener=forbidden)
    assert authority.category_for(identifier) is None
    assert authority.contract() == {"version": 1, "authority": None}
    assert authority.source_paths == set()


@pytest.mark.parametrize(
    "existing",
    ["biolink:ChemicalEntity", "biolink:OrganismTaxon", "biolink:Mammal", "biolink:Food|biolink:ChemicalEntity"],
)
def test_conflicting_substantive_categories_fail_closed(existing):
    """A generic suffix cannot authorize erasing an unexplained substantive category."""
    with pytest.raises(ValueError, match="Conflicting substantive"):
        finite.apply_category(existing + "|biolink:OntologyClass", "biolink:CellularOrganism")


@pytest.mark.parametrize("damage", ["definition", "parent", "duplicate", "property", "deprecated", "missing"])
def test_changed_live_native_statements_refuse_without_any_database_pin(tmp_path, monkeypatch, damage):
    """No database pin is left to repin (#1420); the complete statement witness alone refuses."""
    raw, _, _, _, authority = prepare(tmp_path, monkeypatch)
    with sqlite3.connect(raw / "ncit.db") as connection:
        if damage == "definition":
            connection.execute(
                "INSERT INTO statements VALUES(?,?,?,?,?,?)",
                ("NCIT:C72005", "IAO:0000115", None, "invented", None, None),
            )
        elif damage == "parent":
            connection.execute(
                "UPDATE statements SET object='NCIT:C14234' WHERE subject='NCIT:C72005' AND predicate='rdfs:subClassOf'"
            )
        elif damage == "duplicate":
            connection.execute(
                "INSERT INTO statements SELECT * FROM statements WHERE subject='NCIT:C72005' AND predicate='rdfs:label'"
            )
        elif damage == "property":
            connection.execute(
                "UPDATE statements SET object='owl:ObjectProperty' WHERE subject='NCIT:C72005' AND predicate='rdf:type'"
            )
        elif damage == "deprecated":
            connection.execute(
                "INSERT INTO statements VALUES(?,?,?,?,?,?)",
                ("NCIT:C72005", "owl:deprecated", None, "true", None, None),
            )
        else:
            connection.execute("DELETE FROM statements WHERE subject='NCIT:C72005'")
    with pytest.raises(ValueError, match="native statements changed"):
        authority.category_for("NCIT:C72005")


@pytest.mark.parametrize("release", ["26.08e", None])
def test_any_release_with_reviewed_statements_is_accepted_and_recorded(tmp_path, monkeypatch, release):
    """No database pin (#1420): a later or unstamped release passes on its statements and is recorded."""
    raw, _, policy, transform, authority = prepare(tmp_path, monkeypatch)
    assert "native_sha256" not in policy
    with sqlite3.connect(raw / "ncit.db") as connection:
        connection.execute("DELETE FROM statements WHERE subject='obo:ncit.owl'")
        if release is not None:
            connection.execute(
                "INSERT INTO statements VALUES(?,?,?,?,?,?)",
                ("obo:ncit.owl", "owl:versionInfo", None, release, None, None),
            )
        connection.execute(
            "INSERT INTO statements VALUES(?,?,?,?,?,?)", ("NCIT:C999999", "rdfs:label", None, "unrelated", None, None)
        )
    assert authority.category_for("NCIT:C72005") == policy["records"]["NCIT:C72005"]["category"]
    authority.verify(transform.consumed_input_snapshots)
    contract = authority.contract()
    assert contract["native_release"] == release != policy["native_reviewed_release"]
    assert contract["authority"]["sha256"] == finite.digest((raw / "ncit.db").read_bytes())


def test_fixture_database_records_the_reviewed_release(tmp_path, monkeypatch):
    """The receipt records the release the run read, here the reviewed one."""
    _, _, policy, _, authority = prepare(tmp_path, monkeypatch)
    authority.category_for("NCIT:C72005")
    assert authority.contract()["native_release"] == policy["native_reviewed_release"] == "26.02d"


def test_only_the_downloaded_archive_is_unpacked_for_the_authority(tmp_path, monkeypatch):
    """The ontologies source can finalize NCIT ids before ontologies_stubs has unpacked ncit.db (#1526)."""
    raw, _, policy, _, authority = prepare(tmp_path, monkeypatch)
    database = raw / "ncit.db"
    (raw / "ncit.db.gz").write_bytes(gzip.compress(database.read_bytes()))
    database.unlink()
    assert authority.category_for("NCIT:C14191") == policy["records"]["NCIT:C14191"]["category"]
    assert database.is_file()
    assert sorted(path.name for path in raw.iterdir() if path.name.startswith("ncit.db")) == ["ncit.db", "ncit.db.gz"]


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_sqlite_sidecars_are_absent_before_read_and_through_lifetime(tmp_path, monkeypatch, suffix, when):
    """SQLite state cannot silently change after the readonly snapshot was parsed."""
    raw, _, _, transform, authority = prepare(tmp_path, monkeypatch)
    if when == "after":
        authority.category_for("NCIT:C72005")
    (raw / ("ncit.db" + suffix)).write_bytes(b"unexpected SQLite state")
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.category_for("NCIT:C72005")
    if when == "after":
        with pytest.raises((ValueError, SourceFinalizationRequired)):
            authority.verify(transform.consumed_input_snapshots)


@pytest.mark.parametrize("damage", ["policy", "witness", "receipt", "missing_role", "rebound_role"])
def test_cached_interpretation_and_original_role_bindings_are_not_mutable_authority(tmp_path, monkeypatch, damage):
    """The first consumed witness remains authoritative despite later cache/receipt restamping."""
    _, _, _, transform, authority = prepare(tmp_path, monkeypatch)
    authority.category_for("NCIT:C72005")
    snapshots = copy.deepcopy(transform.consumed_input_snapshots)
    if damage == "policy":
        policy = json.loads(authority._policy_json)
        policy["records"]["NCIT:C72005"]["category"] = "biolink:OrganismTaxon"
        authority._policy_json = finite.canonical(policy)
    elif damage == "witness":
        authority._evidence_json = "{}"
    elif damage == "receipt":
        receipt = json.loads(authority._contract_json)
        receipt["policy"]["path"] += ".replacement"
        authority._contract_json = finite.canonical(receipt)
        snapshots[finite.POLICY_ROLE] = receipt["policy"]
    elif damage == "missing_role":
        snapshots.pop(finite.NATIVE_ROLE)
    else:
        snapshots[finite.NATIVE_ROLE]["path"] += ".replacement"
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.verify(snapshots)


def test_native_snapshot_not_mutable_original_is_used_and_external_symlink_refused(tmp_path, monkeypatch):
    """Only a selected in-raw immutable snapshot can be read by the SQLite parser."""
    raw, _, _, _, _ = prepare(tmp_path, monkeypatch)
    direct = finite.FiniteNcitCategoryAuthority(raw, opener=lambda path: path.open())
    with pytest.raises(ValueError, match="immutable private snapshot"):
        direct.category_for("NCIT:C72005")
    outside = tmp_path / "outside.db"
    shutil.copyfile(raw / "ncit.db", outside)
    (raw / "ncit.db").unlink()
    (raw / "ncit.db").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        direct.category_for("NCIT:C72005")


def test_same_byte_native_symlink_retarget_is_refused(tmp_path, monkeypatch):
    """Byte equality does not authorize replacement of the originally selected native locator."""
    raw, _, _, _, authority = prepare(tmp_path, monkeypatch)
    original, replacement = raw / "native-original.db", raw / "native-replacement.db"
    (raw / "ncit.db").rename(original)
    shutil.copyfile(original, replacement)
    (raw / "ncit.db").symlink_to(original)
    authority.category_for("NCIT:C72005")
    (raw / "ncit.db").unlink()
    (raw / "ncit.db").symlink_to(replacement)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.verify()


def test_policy_changes_not_self_authenticating():
    """An altered finite decision cannot approve itself by keeping plausible native metadata."""
    changed = copy.deepcopy(POLICY)
    changed["records"]["NCIT:C14191"]["category"] = "biolink:Mammal"
    with pytest.raises(ValueError, match="Unreviewed"):
        finite.load_policy(io.StringIO(json.dumps(changed)))


def prepare_source(tmp_path, monkeypatch):
    """Use actual 38 native/imported rows with unchanged non-category fields."""
    raw, _, _, transform, authority = prepare(tmp_path, monkeypatch)
    records = [dict(entry["row"]) for entry in SOURCE_ROWS]
    # Multiple producers are tested through one shared-category source bundle;
    # original provenance and all non-category fields stay byte-equivalent.
    write_rows(transform.output_node_file, records)
    write_rows(
        transform.output_edge_file,
        [],
        fields=[
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "publications",
        ],
    )
    return raw, transform, authority, records


@pytest.mark.usefixtures("local_source_schema")
def test_actual_finalizer_all38_importer_declarations_repeat_and_admission(tmp_path, monkeypatch):
    """Actual shared finalization converges imports while preserving every non-category field."""
    _, transform, _, original = prepare_source(tmp_path, monkeypatch)
    before_edges = transform.output_edge_file.read_bytes()
    report = transform.finalize(fresh_run=True)
    actual = list(graph_rows(transform.output_node_file))
    assert len(actual) == len(original) == 38
    assert actual == [{**row, "category": POLICY["records"][row["id"]]["category"]} for row in original]
    assert transform.output_edge_file.read_bytes() == before_edges
    assert report[finite.CONTRACT_KEY]["identifiers"] == sorted(finite.FINITE_IDS)
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    transform.finalize()
    assert before == {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "null",
        "sidecars",
        "role",
        "policy",
        "native",
        "model",
        "inventory",
        "late_sidecar",
        "release",
        "new_database",
    ],
)
def test_recorded_public_admission_requires_complete_finite_contract(tmp_path, monkeypatch, damage):
    """A syntactically valid ordinary finalization receipt cannot drop the finite native proof."""
    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    contract = report[finite.CONTRACT_KEY]
    if damage == "missing":
        report.pop(finite.CONTRACT_KEY)
    elif damage == "null":
        report[finite.CONTRACT_KEY] = {"version": 1, "authority": None}
    elif damage == "sidecars":
        contract["authority"]["absent_sqlite_sidecars"].pop()
    elif damage == "role":
        report["consumed_inputs"].pop(finite.NATIVE_ROLE)
    elif damage == "policy":
        contract["policy"]["sha256"] = "0" * 64
    elif damage == "native":
        contract["native_evidence_sha256"] = "0" * 64
    elif damage == "model":
        contract["model"]["path"] += ".replacement"
    elif damage == "inventory":
        contract["identifiers"].pop()
    elif damage == "release":
        contract["native_release"] = 26
    elif damage == "new_database":
        # Same reviewed statements, but not the database this run read and recorded.
        with sqlite3.connect(raw / "ncit.db") as connection:
            connection.execute(
                "INSERT INTO statements VALUES(?,?,?,?,?,?)",
                ("NCIT:C999999", "rdfs:label", None, "unrelated", None, None),
            )
    else:
        (raw / "ncit.db-wal").write_bytes(b"late")
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
def test_module_admission_compares_the_database_this_run_read(tmp_path, monkeypatch):
    """The recorded database, not a reviewed pin, is admitted; a later replacement is refused."""
    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    report_path = transform.output_dir / "source_finalization.json"
    assert report[finite.CONTRACT_KEY]["native_release"] == POLICY["native_reviewed_release"]
    finite.verify_recorded_inputs(report, report_path)
    # Same reviewed statements, but not the database this run read and recorded.
    with sqlite3.connect(raw / "ncit.db") as connection:
        connection.execute(
            "INSERT INTO statements VALUES(?,?,?,?,?,?)", ("NCIT:C999999", "rdfs:label", None, "unrelated", None, None)
        )
    with pytest.raises(SourceFinalizationRequired, match="Invalid finite NCIT") as info:
        finite.verify_recorded_inputs(report, report_path)
    assert "native binding changed" in str(info.value.__cause__)


@pytest.mark.usefixtures("local_source_schema")
def test_recorded_release_must_be_the_bound_databases(tmp_path, monkeypatch):
    """The receipt's release is provenance, but a rewritten value is refused at admission (#1531)."""
    _, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    report_path = transform.output_dir / "source_finalization.json"
    report[finite.CONTRACT_KEY]["native_release"] = "99.99z"
    with pytest.raises(SourceFinalizationRequired, match="Invalid finite NCIT") as info:
        finite.verify_recorded_inputs(report, report_path)
    assert "release provenance changed" in str(info.value.__cause__)


@pytest.mark.usefixtures("local_source_schema")
def test_truthfully_empty_source_has_no_ncit_native_dependency(tmp_path, monkeypatch):
    """No finite target must not consult, require or fabricate a native NCIT authority."""
    raw, _, _, transform, _ = prepare(tmp_path, monkeypatch)
    (raw / "ncit.db").unlink()
    records = [
        {"id": "example:1", "name": "Unrelated", "category": "biolink:NamedThing", "provided_by": "infores:fixture"}
    ]
    write_rows(transform.output_node_file, records)
    write_rows(
        transform.output_edge_file,
        [],
        fields=[
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
        ],
    )
    report = transform.finalize(fresh_run=True)
    assert report[finite.CONTRACT_KEY] == {"version": 1, "authority": None}
    assert not {finite.NATIVE_ROLE, finite.POLICY_ROLE} & report["consumed_inputs"].keys()
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
def test_new_instance_repeat_retains_sqlite_absence_guard_for_later_marker(tmp_path, monkeypatch):
    """Successful repeat admission must not forget sidecar absence before a later completion check."""
    from kg_microbe.transform_utils.transform import Transform

    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    transform.finalize(fresh_run=True)
    repeated = Transform("fixture", raw, tmp_path / "transformed")
    repeated.finalize()
    (raw / "ncit.db-wal").write_bytes(b"state appeared after repeat admission")
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        repeated.verify_consumed_inputs()


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("damage", ["policy", "all_evidence", "scope", "seen"])
def test_clearing_policy_cannot_make_active_native_guard_inert_before_publication(tmp_path, monkeypatch, damage):
    """A cached-field deletion must not convert consumed native evidence into a truthful zero cohort."""
    from kg_microbe.utils import source_finalization

    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original_publish = source_finalization._publish_finalization

    def clear_policy_then_publish(producer, prepared):
        """Damage cached proof and add a SQLite sidecar before real publication."""
        guard = producer._ncit_eight_category_guard
        if damage in {"policy", "all_evidence"}:
            guard._policy_json = None
        if damage == "all_evidence":
            guard._evidence_json = guard._contract_json = guard._admission = None
            guard._seen.clear()
        if damage == "scope":
            guard._members = ()
        if damage == "seen":
            guard._seen.clear()
        (raw / "ncit.db-wal").write_bytes(b"late unguarded SQLite state")
        return original_publish(producer, prepared)

    monkeypatch.setattr(source_finalization, "_publish_finalization", clear_policy_then_publish)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())


@pytest.mark.usefixtures("local_source_schema")
def test_scoped_source_selection_does_not_include_unrelated_neighbor_node_files(tmp_path, monkeypatch):
    """A selected ontology member must not acquire unrelated nearby declarations or edits."""
    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    nodes = transform.output_dir / "selected_nodes.tsv"
    edges = transform.output_dir / "selected_edges.tsv"
    transform.output_node_file.rename(nodes)
    transform.output_edge_file.rename(edges)
    neighbor = transform.output_dir / "unrelated_nodes.tsv"
    write_rows(neighbor, [SOURCE_ROWS[0]["row"]])
    before = neighbor.read_bytes()
    report = transform.finalize(file_prefix="selected_", fresh_run=True)
    assert set(report["members"]) == {nodes.name, edges.name}
    assert neighbor.read_bytes() == before
    transform.finalize(file_prefix="selected_")
    from kg_microbe.transform_utils.transform import Transform

    repeated = Transform("fixture", raw, tmp_path / "transformed")
    repeated.finalize(file_prefix="selected_")
    repeated.verify_consumed_inputs()
    verify_finalized_source_files([nodes, edges])
    assert neighbor.read_bytes() == before


@pytest.mark.usefixtures("local_source_schema")
def test_recorded_admission_retains_absence_guard_after_validation_returns(tmp_path, monkeypatch):
    """A returned source admission remains valid only while its originally absent sidecars stay absent."""
    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    guard = finite.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
    (raw / "ncit.db-journal").write_bytes(b"late native journal")
    with pytest.raises(SourceFinalizationRequired):
        guard.verify(metadata_only=True)


@pytest.mark.usefixtures("local_source_schema")
def test_chosen_raw_directory_symlink_preserves_lexical_selection(tmp_path, monkeypatch):
    """A legitimate raw-directory alias may select its contained DB, but cannot later be retargeted."""
    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    alias = tmp_path / "selected_raw"
    alias.symlink_to(raw, target_is_directory=True)
    transform.input_base_dir = alias
    report = transform.finalize(fresh_run=True)
    assert report[finite.CONTRACT_KEY]["authority"]["selected_path"] == str(alias / "ncit.db")
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    replacement = tmp_path / "alternate_raw"
    shutil.copytree(raw, replacement)
    alias.unlink()
    alias.symlink_to(replacement, target_is_directory=True)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        transform.verify_consumed_inputs()


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_lost_optional_absence_entry_cannot_publish_with_late_native_sidecar(tmp_path, monkeypatch, suffix):
    """The finite required-state contract survives partial optional-input cache loss (#1315)."""
    from kg_microbe.utils import source_finalization

    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original_publish = source_finalization._publish_finalization

    def lose_absence_then_publish(producer, prepared):
        """Remove a captured absence guard and create the previously absent sidecar."""
        sidecar = raw / ("ncit.db" + suffix)
        producer._ncit_eight_category_guard._admission.absent.remove(sidecar)
        sidecar.write_bytes(b"late native SQLite state")
        return original_publish(producer, prepared)

    monkeypatch.setattr(source_finalization, "_publish_finalization", lose_absence_then_publish)
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("route", ["repeat", "returned_admission"])
@pytest.mark.parametrize("create_sidecar", [False, True])
def test_lost_recorded_absence_entries_cannot_disable_completion_guards(tmp_path, monkeypatch, route, create_sidecar):
    """Late marker/merge admission retains mandatory absence independently of its mutable cache."""
    from kg_microbe.transform_utils.transform import Transform

    raw, transform, _, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    if route == "repeat":
        repeated = Transform("fixture", raw, tmp_path / "transformed")
        repeated.finalize()
        repeated._ncit_eight_category_guard._admission.absent.clear()
        verify = repeated.verify_consumed_inputs
    else:
        admission = finite.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
        admission.absent.clear()

        def verify():
            """Call the unchanged public late merge guard."""
            admission.verify(metadata_only=True)

    if create_sidecar:
        (raw / "ncit.db-wal").write_bytes(b"late native state")
    with pytest.raises(SourceFinalizationRequired):
        verify()


@pytest.mark.parametrize("damage", ["absent", "binding"])
def test_selected_and_resolved_native_sidecars_are_both_mandatory(tmp_path, monkeypatch, damage):
    """An in-raw SQLite symlink needs the lexical and target sidecar sets, not only ncit.db-wal."""
    raw, _, _, transform, authority = prepare(tmp_path, monkeypatch)
    database = raw / "native-pinned.db"
    (raw / "ncit.db").rename(database)
    (raw / "ncit.db").symlink_to(database.name)
    authority.category_for("NCIT:C72005")
    assert len(authority.contract()["authority"]["absent_sqlite_sidecars"]) == 6
    sidecar = raw / "native-pinned.db-journal"
    if damage == "absent":
        authority._admission.absent.remove(sidecar)
    else:
        authority._admission.bindings.pop(sidecar)
    with pytest.raises(SourceFinalizationRequired):
        authority.verify(transform.consumed_input_snapshots)
