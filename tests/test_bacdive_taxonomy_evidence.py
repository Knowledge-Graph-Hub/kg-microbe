"""
Exercise source-local taxonomy evidence and owned native-reader lifecycle.

All output and synthetic authorities belong under tmp_path. The literal control
fixtures explicitly make no biological/native-source identity claims.
"""

import copy
import csv
import hashlib
import io
import json
import os
import sqlite3
import tarfile
from collections import Counter
from contextlib import closing
from pathlib import Path

import pytest
from oaklib.implementations.sqldb.sql_implementation import SqlImplementation
from oaklib.resource import OntologyResource

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import ancestry_authority as authority
from kg_microbe.transform_utils.bacdive import bacdive as bacdive_module
from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.bacdive import (
    BacDiveTransform,
    load_metpo_metabolite_production_mappings,
)
from kg_microbe.transform_utils.bacdive.emission import resolve_deposit_parents
from kg_microbe.transform_utils.constants import INFERRED_SUBCLASS_RELATION, RDFS_SUBCLASS_OF
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    graph_rows,
    verify_finalized_source_files,
)
from tests.bacdive_synthetic_fallback_context import write_selected
from tests.test_bacdive_isolation_categories import _run
from tests.test_external_node_closure import _taxdump

RESOURCE = Path(__file__).parent / "resources/bacdive_taxonomy_evidence"


def controls():
    """Load clearly synthetic immutable behavior evidence separately from actual-native acceptance."""
    return json.loads((RESOURCE / "controls.json").read_text())


def database(path, *, object_id=None, missing_edges=False, extra_edges=()):
    """Materialize the exact tiny offline SemSQL fixture only in an isolated test directory."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript((RESOURCE / "authority.sql").read_text())
        if object_id is not None:
            connection.execute("UPDATE entailed_edge SET object=? WHERE subject='NCBITaxon:20'", (object_id,))
        connection.executemany(
            "INSERT INTO entailed_edge VALUES (?, 'rdfs:subClassOf', ?)", [tuple(edge) for edge in extra_edges]
        )
        if missing_edges:
            connection.execute("DROP TABLE entailed_edge")
    return path


def adapter(path):
    """Construct OAK directly on the tiny local file, without selector/build/network APIs."""
    return SqlImplementation(resource=OntologyResource(slug=str(path.absolute())))


def close_adapter(value):
    """Dispose only a test-owned original adapter, never the producer's private guard by proxy."""
    if value._session is not None:
        value._session.close()
    value.engine.dispose()


def produce(
    tmp_path,
    monkeypatch,
    records=None,
    *,
    gss=True,
    missing_edges=False,
    forbid_ancestry_selection=False,
    retired_fixture=False,
    declare_retired=False,
    deleted_fixture=False,
    extra_edges=(),
    declaration_context=None,
):
    """Run the real producer/readers/writers, replacing only unrelated label/assay fixture context."""
    fixture = controls()
    labels = fixture["labels"]
    selected_records = fixture["records"] if records is None else records
    owned = []

    def context(transform, _policy):
        """Use a real local query adapter and actual GSS file before production native reads begin."""
        path = database(
            Path(transform.input_base_dir) / "fixture-query-authority.db",
            missing_edges=missing_edges,
            extra_edges=extra_edges,
        )
        transform.ncbi_impl = adapter(path)
        owned.append(transform.ncbi_impl)
        selected = Path(transform.input_base_dir) / "fixture-selected-ncbitaxon.tsv"
        selected_labels = dict(labels)
        if retired_fixture and declare_retired:
            selected_labels.pop("NCBITaxon:10")
        write_selected(selected, selected_labels, {"NCBITaxon:99": "Actinobacteria"})
        monkeypatch.setattr(bacdive_module, "NCBITAXON_NODES_FILE", selected)
        transform.ncbitaxon_fallback_cache = {}
        transform._ncbitaxon_ancestor_cache = {}
        transform.ncbitaxon_labels = dict(selected_labels)
        if retired_fixture:
            # A real selected declaration suppresses the local stub. Omitting
            # that ID from both native selected bytes and cache exercises the
            # producer's mandatory typed-stub branch without a forged cache.
            if deleted_fixture:
                _taxdump(Path(transform.input_base_dir), merged="", deleted="10 |\n")
            else:
                _taxdump(Path(transform.input_base_dir))
        else:
            # Finalization checks declared taxids too; this fixture has no
            # retirement/deletion claims. The selected fixture taxa are live
            # prokaryotes in the actual SQL context; their native tar agrees.
            with tarfile.open(Path(transform.input_base_dir) / "taxdump.tar.gz", "w:gz") as archive:
                members = {
                    "merged.dmp": "",
                    "delnodes.dmp": "",
                    "nodes.dmp": "1 | 1 | no rank |\n2 | 1 | superkingdom |\n"
                    + "".join(f"{identifier.removeprefix('NCBITaxon:')} | 2 | species |\n" for identifier in labels),
                    "names.dmp": "".join(
                        f"{identifier.removeprefix('NCBITaxon:')} | {label} | | scientific name |\n"
                        for identifier, label in labels.items()
                    ),
                }
                for name, value in members.items():
                    payload = value.encode()
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
        transform.lpsn_name_index = {}
        transform.metpo_metabolite_production_mappings = load_metpo_metabolite_production_mappings()
        if gss:
            (Path(transform.input_base_dir) / "lpsn_gss.csv").write_bytes((RESOURCE / "lpsn_gss.csv").read_bytes())
        if forbid_ancestry_selection:

            def forbidden(_adapter):
                """Refuse a second adapter selection when deposit resolver demand is zero."""
                raise AssertionError("zero-query deposit phase resolved an adapter")

            monkeypatch.setattr(bacdive_module, "resolve_adapter", forbidden)
        if declaration_context is not None:
            declaration_context(transform)

    # Direct-ID preview labels remain fixture-only; actual fallback selection
    # reads the synthetic native SQL/selected files and its own private connection.
    monkeypatch.setattr(BacDiveTransform, "_get_ncbitaxon_label", lambda _self, key: labels.get(key))
    try:
        return _run(tmp_path, monkeypatch, selected_records, during_prepare=context)
    finally:
        for value in owned:
            close_adapter(value)


def scoped_rows(transform):
    """Read complete small output rows without conflating source or finalized quoting."""
    return list(graph_rows(transform.output_edge_file, quoting=csv.QUOTE_MINIMAL))


def test_real_producer_preserves_targets_and_exact_support_metadata(tmp_path, monkeypatch):
    """Direct, inferred, mixed, same-target, repeated and suppressed cases keep their original shape."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    rows = scoped_rows(transform)
    deposits = {
        row["subject"]: row
        for row in rows
        if row["subject"].startswith("kgmicrobe.strain:TEST-") and row["predicate"] == "biolink:subclass_of"
    }
    assert {key: row["object"] for key, row in deposits.items()} == {
        "kgmicrobe.strain:TEST-DIRECT": "NCBITaxon:20",
        "kgmicrobe.strain:TEST-INFERRED": "NCBITaxon:10",
        "kgmicrobe.strain:TEST-MIXED": "NCBITaxon:10",
        "kgmicrobe.strain:TEST-BOTH": "NCBITaxon:10",
        "kgmicrobe.strain:TEST-REPEAT": "NCBITaxon:20",
    }
    for identifier, row in deposits.items():
        derived = identifier.endswith(("INFERRED", "MIXED"))
        assert row["relation"] == (INFERRED_SUBCLASS_RELATION if derived else RDFS_SUBCLASS_OF)
        assert row["knowledge_level"] == ("prediction" if derived else "observation")
        assert row["agent_type"] == ("automated_agent" if derived else "manual_agent")
        assert row["primary_knowledge_source"] == "infores:bacdive"
        assert row["value"] == row["unit"] == row["publications"] == row["original_object"] == ""
    assert not any(row["object"] == "kgmicrobe.strain:TEST-DISJOINT" for row in rows)
    assert any(row["subject"] == "kgmicrobe.strain:bacdive_10" and row["object"] == "NCBITaxon:99" for row in rows)
    audit = list(graph_rows(transform.output_dir / taxonomy.AUDIT_FILE))
    selected = {row["subject"]: row for row in audit if row["kind"] == "deposit"}
    assert selected["kgmicrobe.strain:TEST-BOTH"]["status"] == "direct_at_selected_parent"
    mixed = json.loads(selected["kgmicrobe.strain:TEST-MIXED"]["native_evidence_json"])
    assert {item["claim_parent"] for item in mixed["claims"]} == {"NCBITaxon:10", "NCBITaxon:20"}
    assert {item["selected_parent_choice"]["inferred"] for item in mixed["claims"]} == {False, True}
    assert mixed["computed_ancestry"]["asserted_native_parent_rows"] is False
    assert mixed["computed_ancestry"]["native_version_statements"]
    assert transform._taxonomy_evidence_guard.native_deposit_claims()["kgmicrobe.strain:TEST-REPEAT"][
        "NCBITaxon:20"
    ] == ["9", "9"]


def test_real_lookup_convergence_preserves_original_rows_and_true_ambiguity(tmp_path, monkeypatch):
    """Two explicit GSS rows converging on one accepted record yield one edge, not an ambiguity."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    observed = {(row["subject"], row["object"]) for row in scoped_rows(transform) if row["object"].startswith("lpsn:")}
    assert observed == {("kgmicrobe.strain:bacdive_1", "lpsn:5"), ("kgmicrobe.strain:bacdive_2", "lpsn:2")}
    audit = [row for row in graph_rows(transform.output_dir / taxonomy.AUDIT_FILE) if row["kind"] == "lpsn_lookup"]
    by_record = {row["subject"]: row for row in audit}
    convergence = json.loads(by_record["kgmicrobe.strain:bacdive_2"]["lookup_evidence_json"])
    assert convergence["original_ids"] == ["1", "2"]
    assert convergence["resolved_ids_with_multiplicity"] == ["2", "2"]
    assert convergence["distinct_resolved_ids"] == ["2"]
    assert {item["record_no"] for chain in convergence["chains"] for item in chain} == {"1", "2"}
    assert by_record["kgmicrobe.strain:bacdive_12"]["emitted_edge_json"] == "null"


def test_an_audit_cell_over_the_csv_field_limit_still_verifies(tmp_path, monkeypatch, local_source_schema):
    """An audit cell can exceed CSV's 131,072-character default; every reader keeps the caller's limit (#1571)."""
    records = copy.deepcopy(controls()["records"])
    # BacDive 4 is the inferred TEST MIXED claim, whose deposit row embeds this record's General block.
    records[3]["General"]["fixture padding"] = "x" * 140_000
    # Pin CSV's default: the read-back must cope with it whatever limit the caller had set.
    previous = csv.field_size_limit(131_072)
    try:
        transform, _, _, _ = produce(tmp_path, monkeypatch, records)
        audit = (transform.output_dir / taxonomy.AUDIT_FILE).read_text(encoding="utf-8")
        assert max(len(cell) for line in audit.splitlines() for cell in line.split("\t")) > 131_072
        report = transform.finalize()
        fresh = BacDiveTransform.__new__(BacDiveTransform)
        Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
        assert fresh.finalize() == report
        fresh.verify_native_inputs()
        BacDiveTransform.verify_recorded_native_inputs(
            report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
        ).verify()
        assert csv.field_size_limit() == 131_072
    finally:
        csv.field_size_limit(previous)


@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {
                "General": {"BacDive-ID": 23, "NCBI tax id": {"NCBI tax id": 10}},
                "External links": {"culture collection no.": "TEST SINGLE"},
            }
        ],
    ],
)
def test_genuine_zero_query_runs_do_not_fabricate_an_authority_read(
    tmp_path, monkeypatch, local_source_schema, records
):
    """Empty and single-parent sources have a mandatory, native-derived explicit zero query contract."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False, forbid_ancestry_selection=True)
    report = transform.finalize()
    contract = report["producer_native_inputs"]["taxonomy"]
    assert contract["ancestry"]["actual_queries"] is None
    assert contract["ancestry"]["callback_demand_counts"] == []
    assert contract["optional_gss"]["sha256"] is None
    assert taxonomy.GSS_ROLE not in report["consumed_inputs"]
    assert list(graph_rows(transform.output_dir / taxonomy.AUDIT_FILE)) == []
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_actual_nonempty_finalize_fresh_repeat_and_retained_admission(tmp_path, monkeypatch, local_source_schema):
    """The actual public path retains full active query evidence after new-instance repetition."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    report = transform.finalize()
    witness = report["producer_native_inputs"]["taxonomy"]["ancestry"]
    assert witness["actual_queries"]["computed_queries"]
    assert witness["callback_demand_counts"] == [
        ["NCBITaxon:10", 1],
        ["NCBITaxon:20", 2],
        ["NCBITaxon:30", 1],
    ]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    admission.verify()
    database_path = Path(witness["actual_queries"]["authority"]["selected_path"])
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE entailed_edge SET object='NCBITaxon:777' WHERE subject='NCBITaxon:20'")
    with pytest.raises(SourceFinalizationRequired):
        admission.verify()
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_native_inputs()


@pytest.mark.parametrize(
    "damage",
    [
        "whole-contract",
        "ancestry-contract",
        "false-zero",
        "raw-role",
        "gss-role",
        "gss-rebound",
        "query-subject",
        "query-multiplicity",
        "query-predicate",
        "query-reflexivity",
        "query-result",
        "authority-missing",
        "native-version-missing",
        "selected-parent",
        "members",
        "audit-deleted",
        "audit-empty",
    ],
)
def test_public_admission_rejects_lost_or_forged_scoped_proof(tmp_path, monkeypatch, local_source_schema, damage):
    """A coherent report cannot substitute for missing actual native demand, input or audited output."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    report = copy.deepcopy(transform.finalize())
    native = report["producer_native_inputs"]
    if damage == "whole-contract":
        native.pop("taxonomy")
    elif damage == "ancestry-contract":
        native["taxonomy"].pop("ancestry")
    elif damage == "false-zero":
        native["taxonomy"]["ancestry"]["actual_queries"] = None
        native["taxonomy"]["ancestry"]["callback_demand_counts"] = []
    elif damage in {"raw-role", "gss-role"}:
        report["consumed_inputs"].pop(taxonomy.RAW_ROLE if damage == "raw-role" else taxonomy.GSS_ROLE)
    elif damage == "gss-rebound":
        report["consumed_inputs"][taxonomy.GSS_ROLE] = report["consumed_inputs"][taxonomy.RAW_ROLE]
    elif damage == "query-subject":
        native["taxonomy"]["ancestry"]["actual_queries"]["computed_queries"][0]["subject"] = "NCBITaxon:777"
    elif damage == "query-multiplicity":
        native["taxonomy"]["ancestry"]["callback_demand_counts"][0][1] += 1
    elif damage in {"query-predicate", "query-reflexivity", "query-result"}:
        row = native["taxonomy"]["ancestry"]["actual_queries"]["computed_queries"][0]
        if damage == "query-predicate":
            row["predicates"] = ["biolink:related_to"]
        elif damage == "query-reflexivity":
            row["reflexive"] = False
        else:
            row["computed_ancestors"].append("NCBITaxon:777")
    elif damage == "authority-missing":
        native["taxonomy"]["ancestry"]["actual_queries"].pop("authority")
    elif damage == "native-version-missing":
        native["taxonomy"]["ancestry"]["actual_queries"]["native_version_statements"] = []
    elif damage == "selected-parent":
        native["taxonomy"]["contested"][0][3] = "NCBITaxon:777"
    elif damage == "members":
        report["members"]["unrelated_nodes.tsv"] = report["members"]["nodes.tsv"]
    elif damage == "audit-deleted":
        (transform.output_dir / taxonomy.AUDIT_FILE).unlink()
    else:
        (transform.output_dir / taxonomy.AUDIT_FILE).write_text("\t".join(taxonomy.AUDIT_FIELDS) + "\n")
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        BacDiveTransform.verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


def test_old_and_fresh_queries_preserve_the_exact_existing_resolver(tmp_path):
    """Real OAK calls and the actual resolver agree without assuming every candidate triggers a query."""
    original = adapter(database(tmp_path / "authority.db"))
    claims = {
        "deposit:a": {"NCBITaxon:20": ["1"], "NCBITaxon:10": ["2"]},
        "deposit:b": {"NCBITaxon:20": ["3"], "NCBITaxon:30": ["4"]},
        "deposit:single": {"NCBITaxon:99": ["5"]},
    }
    old_demand, new_demand = [], []

    def old(identifier):
        """Observe the original resolver's exact callback demand independently of the new helper."""
        old_demand.append(identifier)
        return frozenset(original.ancestors([identifier], predicates=[RDFS_SUBCLASS_OF])) - {identifier}

    try:
        prior = resolve_deposit_parents(claims, ancestors_of=old, ancestry_failed=lambda _id: False)
        with authority.FreshAncestryAuthority.from_resolved_adapter(original) as fresh:

            def new(identifier):
                """Compare actual demand and values using the new private query connection."""
                new_demand.append(identifier)
                return fresh.ancestors(identifier)

            current = resolve_deposit_parents(claims, ancestors_of=new, ancestry_failed=lambda _id: False)
            receipt = fresh.finish()
        assert current == prior
        assert Counter(new_demand) == Counter(old_demand)
        assert "NCBITaxon:99" not in new_demand
        assert Counter(row["subject"] for row in receipt["computed_queries"]) == Counter(new_demand)
        assert receipt["asserted_native_parent_rows"] is False
    finally:
        close_adapter(original)


def test_cached_stale_caller_does_not_determine_new_connection_bytes(tmp_path):
    """Replacing a path before binding does not make an old open handle the new authority."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    path = database(tmp_path / "authority.db")

    def snapshot():
        """Connect the caller to an in-memory copy of the selected file as it is at connection time."""
        memory = sqlite3.connect(":memory:")
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as source:
            source.backup(memory)
        return memory

    # The caller keeps the original bytes in memory, never reading the replaced
    # file: on macOS's system SQLite, a read of a replaced file that misses the
    # page cache can fail with SQLITE_IOERR_VNODE, "disk I/O error" (#1512). A
    # reconnect would copy the new file, so the last assertion still shows the
    # caller was never reconnected. The engine URL still identifies the real
    # selected path for the new reader.
    engine = create_engine("sqlite:///" + str(path.absolute()), creator=snapshot, poolclass=StaticPool)
    original = SqlImplementation(resource=OntologyResource(slug=str(path.absolute())), engine=engine)
    try:
        assert "NCBITaxon:10" in original.ancestors(["NCBITaxon:20"], predicates=[RDFS_SUBCLASS_OF])
        replacement = database(tmp_path / "replacement.db", object_id="NCBITaxon:77")
        os.replace(replacement, path)
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with authority.FreshAncestryAuthority.from_resolved_adapter(original) as fresh:
            assert fresh.ancestors("NCBITaxon:20") == frozenset({"NCBITaxon:77"})
            receipt = fresh.finish()
        assert receipt["authority"]["identity"]["sha256"] == current_hash
        assert "NCBITaxon:10" in original.ancestors(["NCBITaxon:20"], predicates=[RDFS_SUBCLASS_OF])
    finally:
        close_adapter(original)


def test_the_authority_leaves_the_callers_session_and_engine_alone(tmp_path, monkeypatch):
    """
    No caller engine or session is queried, reset or closed (the module's contract, #1582).

    A session reopens after close or rollback and an engine reconnects after
    dispose, so a caller that still works proves nothing; only a spy shows them.
    """
    original = adapter(database(tmp_path / "authority.db"))
    session, engine = original.session, original.engine
    calls = []
    spied = (
        (session, ("close", "rollback", "commit", "execute", "connection")),
        (engine, ("dispose", "connect", "begin", "raw_connection")),
    )
    for owner, names in spied:
        for name in names:
            real, label = getattr(owner, name), f"{type(owner).__name__}.{name}"

            def spy(*args, _real=real, _label=label, **kwargs):
                """Record a call on the caller's own session or engine, then make it."""
                calls.append(_label)
                return _real(*args, **kwargs)

            monkeypatch.setattr(owner, name, spy)
    try:
        with authority.FreshAncestryAuthority.from_resolved_adapter(original) as fresh:
            assert "NCBITaxon:10" in fresh.ancestors("NCBITaxon:20")
            fresh.finish()
        assert calls == []
        assert original._session is session and original.engine is engine
    finally:
        monkeypatch.undo()
        close_adapter(original)


@pytest.mark.parametrize("damage", ["bytes", "inode", "wal", "query-table", "engine", "session"])
def test_authority_failure_is_sticky_even_if_outer_code_catches_it(tmp_path, damage):
    """No input/connection/query failure can later become a harmless empty result or successful finish."""
    path = database(tmp_path / "authority.db", missing_edges=damage == "query-table")
    original = adapter(path)
    fresh = authority.FreshAncestryAuthority.from_resolved_adapter(original)
    try:
        if damage == "bytes":
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE entailed_edge SET object='NCBITaxon:77'")
        elif damage == "inode":
            replacement = tmp_path / "replacement.db"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        elif damage == "wal":
            Path(str(path) + "-wal").write_bytes(b"fixture drift")
        elif damage == "engine":
            fresh._adapter.engine = original.engine
        elif damage == "session":
            fresh._adapter._session = original.session
        try:
            fresh.ancestors("NCBITaxon:20")
        except Exception:  # noqa: S110 -- Exercise deliberate legacy catching; finish/verify must still refuse.
            pass  # Deliberately model a caller's broad legacy catch.
        else:
            pytest.fail("the original authority/query failure was not surfaced")
        with pytest.raises(SourceFinalizationRequired):
            fresh.finish()
        with pytest.raises(SourceFinalizationRequired):
            fresh.verify()
    finally:
        # Restore only object references changed by this hostile test, so the
        # guard never closes the caller's independently owned session/engine.
        fresh._adapter.engine = fresh._engine
        fresh._adapter._session = fresh._session
        fresh.close()
        close_adapter(original)


def test_infrastructure_failure_preserves_existing_producer_outputs(tmp_path, monkeypatch):
    """A missing native query table is fatal; it is not a suppressed-deposit success."""
    output = tmp_path / "transformed/bacdive"
    output.mkdir(parents=True)
    nodes, edges = output / "nodes.tsv", output / "edges.tsv"
    nodes.write_bytes(b"previous nodes\n")
    edges.write_bytes(b"previous edges\n")
    with pytest.raises(SourceFinalizationRequired):
        produce(tmp_path, monkeypatch, missing_edges=True)
    assert nodes.read_bytes() == b"previous nodes\n"
    assert edges.read_bytes() == b"previous edges\n"


def test_mid_binding_selector_change_cannot_be_recaptured_as_original(tmp_path, monkeypatch):
    """Changing the caller URL during initial hashing aborts and closes only the private connection."""
    original = adapter(database(tmp_path / "original.db"))
    other = adapter(database(tmp_path / "other.db", object_id="NCBITaxon:777"))
    initial_engine = original.engine
    closed = []
    real_init = authority.FreshAncestryAuthority.__init__

    def changing_init(guard, *args, **kwargs):
        """Model an authority-selector race inside the long binding without changing read code."""
        real_init(guard, *args, **kwargs)
        original.engine = other.engine
        closed.append(guard)

    monkeypatch.setattr(authority.FreshAncestryAuthority, "__init__", changing_init)
    try:
        with pytest.raises(SourceFinalizationRequired, match="selection changed"):
            authority.FreshAncestryAuthority.from_resolved_adapter(original)
        assert closed and closed[0]._closed
        # The failure closed the owned private engine, not this caller/other
        # adapter's independently owned readable database connection.
        assert "NCBITaxon:777" in other.ancestors(["NCBITaxon:20"], predicates=[RDFS_SUBCLASS_OF])
    finally:
        original.engine = initial_engine
        close_adapter(original)
        close_adapter(other)


def test_failed_flag_reset_cannot_heal_retained_raw_admission(tmp_path):
    """A deliberately broad catch and reset cannot erase the incompatible retained failed state."""
    original = adapter(database(tmp_path / "authority.db", missing_edges=True))
    fresh = authority.FreshAncestryAuthority.from_resolved_adapter(original)
    try:
        with pytest.raises(SourceFinalizationRequired, match="query failed"):
            fresh.ancestors("NCBITaxon:20")
        fresh._failed = False
        with pytest.raises(SourceFinalizationRequired):
            fresh.admission.verify(metadata_only=True)
        with pytest.raises(SourceFinalizationRequired):
            fresh.finish()
    finally:
        fresh.close()
        close_adapter(original)


@pytest.mark.parametrize("damage", ["input-hash", "input-stamp", "lexical-binding", "absent-sidecar", "code"])
def test_actual_read_obligations_survive_mutable_cache_erasure(tmp_path, damage):
    """Losing a native identity, locator, absence or imported-code cache entry fails closed."""
    original = adapter(database(tmp_path / "authority.db"))
    fresh = authority.FreshAncestryAuthority.from_resolved_adapter(original)
    try:
        fresh.ancestors("NCBITaxon:20")
        fresh.finish()
        if damage == "input-hash":
            fresh.admission.identities.pop(fresh.resolved)
        elif damage == "input-stamp":
            fresh.admission.stamps.pop(fresh.resolved)
        elif damage == "lexical-binding":
            fresh.admission.bindings.pop(fresh.selected)
        elif damage == "absent-sidecar":
            fresh.admission.absent.remove(fresh._sidecars[0].resolve())
        else:
            fresh.admission.identities.pop(fresh._implementation.resolve())
        with pytest.raises(SourceFinalizationRequired):
            fresh.verify()
    finally:
        fresh.close()
        close_adapter(original)


@pytest.mark.parametrize("damage", ["file-appears", "role-appears", "absence-cache-lost"])
def test_genuine_absent_gss_stays_absent_through_retained_admission(tmp_path, monkeypatch, local_source_schema, damage):
    """A valid zero-source receipt cannot license a later GSS file or forged consumed role."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [], gss=False)
    report = transform.finalize()
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    path = Path(transform.input_base_dir) / "lpsn_gss.csv"
    if damage == "file-appears":
        path.write_bytes((RESOURCE / "lpsn_gss.csv").read_bytes())
    elif damage == "role-appears":
        report["consumed_inputs"][taxonomy.GSS_ROLE] = {"path": str(path), "sha256": "0" * 64}
    else:
        admission.absent.remove(path.resolve())
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


@pytest.mark.parametrize("flag", ["_completed", "_outputs_ready"])
def test_completed_guard_cannot_skip_changed_output_by_resetting_phase(tmp_path, monkeypatch, flag):
    """Completion and output-ready phase bindings are monotonic after successful production."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    path = transform.output_edge_file
    before = path.read_text()
    path.write_text(before.replace("kgmicrobe.strain:TEST-INFERRED", "kgmicrobe.strain:FORGED", 1))
    setattr(transform._taxonomy_evidence_guard, flag, False)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


@pytest.mark.parametrize("field", ["relation", "knowledge_level", "agent_type", "publications", "original_object"])
def test_scoped_output_qualifiers_are_not_silently_discarded(tmp_path, monkeypatch, field):
    """Changing any protected full-row field refuses publication/admission, not just changed endpoints."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    path = transform.output_edge_file
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    selected = next(row for row in rows if row["subject"] == "kgmicrobe.strain:TEST-INFERRED")
    selected[field] = "forged"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


def test_missing_native_metadata_table_closes_private_handles(tmp_path, monkeypatch):
    """Even construction-time SQL failures are fatal infrastructure errors with no leaked owned session."""
    path = database(tmp_path / "authority.db")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE statements")
    original = adapter(path)
    closed = []
    real_close = authority.FreshAncestryAuthority.close

    def close(guard):
        """Observe cleanup without replacing the actual closer or admitting an invalid database."""
        real_close(guard)
        closed.append(guard._closed)

    monkeypatch.setattr(authority.FreshAncestryAuthority, "close", close)
    try:
        with pytest.raises(SourceFinalizationRequired, match="metadata query failed"):
            authority.FreshAncestryAuthority.from_resolved_adapter(original)
        assert closed and all(closed)
    finally:
        close_adapter(original)


def test_constructor_preview_and_direct_lookup_remain_compatible(tmp_path):
    """Preserve the original standalone preview helper without treating it as actual-run read evidence."""
    (tmp_path / "lpsn_gss.csv").write_bytes((RESOURCE / "lpsn_gss.csv").read_bytes())
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.input_base_dir = tmp_path
    transform._lpsn_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    transform.lpsn_name_index = transform._load_lpsn_name_index()
    assert transform._lookup_lpsn({"species": "Fixture convergens"}) == "2"
    assert transform._lookup_lpsn({"species": "Fixture ambiguous"}) is None
    assert transform._lookup_lpsn({"species": "Fixture unique"}) == "5"


def retired_producer(tmp_path, monkeypatch, *, declare_retired=False, deleted_fixture=False):
    """Create one actual supplied parent with a literal native 10→11→12 retirement chain."""
    record = {
        "General": {"BacDive-ID": 31, "NCBI tax id": {"NCBI tax id": 10}},
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    transform, _, _, _ = produce(
        tmp_path,
        monkeypatch,
        [record],
        gss=False,
        retired_fixture=True,
        declare_retired=declare_retired,
        deleted_fixture=deleted_fixture,
        forbid_ancestry_selection=True,
    )
    return transform


@pytest.mark.parametrize("declare_retired", [False, True])
def test_actual_finalization_retirement_keeps_raw_choice_and_exact_projection(
    tmp_path, monkeypatch, local_source_schema, declare_retired
):
    """Real source-finalizer retirement is verified separately, not mistaken for changed parent selection."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=declare_retired)
    if declare_retired:
        assert any(
            row["id"] == "NCBITaxon:10" and row["name"] and row["category"] == "biolink:OrganismTaxon"
            for row in graph_rows(transform.output_node_file)
        )
    guard = transform._taxonomy_evidence_guard
    raw_contract = copy.deepcopy(guard.contract)
    raw = next(row for row in scoped_rows(transform) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED")
    assert raw["object"] == "NCBITaxon:10" and raw["original_object"] == ""
    report = transform.finalize()
    final = next(
        row for row in graph_rows(transform.output_edge_file) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED"
    )
    assert final["object"] == "NCBITaxon:12" and final["original_object"] == "NCBITaxon:10"
    assert taxonomy._equal_row(final, {**raw, "object": "NCBITaxon:12", "original_object": "NCBITaxon:10"})
    assert report["producer_native_inputs"]["taxonomy"] == raw_contract
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    admission.verify()
    (Path(transform.input_base_dir) / "taxdump.tar.gz").unlink()
    with pytest.raises(SourceFinalizationRequired):
        admission.verify()


@pytest.mark.parametrize(
    "damage",
    [
        "audit-missing",
        "wrong-canonical",
        "wrong-hash",
        "original-row-field",
        "missing-row",
        "wrong-chain",
        "live-old",
    ],
)
def test_finalized_retirement_needs_full_row_and_actual_native_proof(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Neither original_object nor a self-consistent forged receipt licenses an unsupported target."""
    transform = retired_producer(tmp_path, monkeypatch)
    report = transform.finalize()
    path = transform.output_dir / "source_reference_resolution.tsv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    affected = [
        row
        for row in rows
        if row["original_edge_json"]
        and json.loads(row["original_edge_json"])["subject"] == "kgmicrobe.strain:TEST-RETIRED"
    ]
    assert affected
    if damage == "audit-missing":
        path.unlink()
    else:
        for row in affected:
            if damage == "wrong-canonical":
                row["canonical_id"] = "NCBITaxon:13"
            elif damage == "wrong-hash":
                row["authority_sha256"] = "0" * 64
            elif damage == "original-row-field":
                original = json.loads(row["original_edge_json"])
                original["agent_type"] = "automated_agent"
                row["original_edge_json"] = json.dumps(original)
            elif damage == "missing-row":
                rows.remove(row)
        if damage in {"wrong-chain", "live-old"}:
            raw = Path(transform.input_base_dir)
            _taxdump(
                raw,
                merged="10 | 13 |\n" if damage == "wrong-chain" else "10 | 11 |\n11 | 12 |\n",
                nodes=(
                    "1 | 1 | no rank |\n2 | 1 | superkingdom |\n10 | 2 | species |\n12 | 2 | species |\n"
                    if damage == "live-old"
                    else None
                ),
            )
            # Coherently update the report's claimed native bytes; actual
            # explicit chain/live-ID semantics must still reject the projection.
            digest = hashlib.sha256((raw / "taxdump.tar.gz").read_bytes()).hexdigest()
            for row in rows:
                if row["authority"] == "taxdump.tar.gz":
                    row["authority_sha256"] = digest
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        BacDiveTransform.verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize("damage", [None, "wrong-hash", "wrong-row", "not-deleted"])
def test_declared_deleted_parent_retains_assertion_and_requires_exact_proof(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """An unchanged deleted parent is auditable, never a guessed replacement or guard exemption."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True, deleted_fixture=True)
    raw = next(row for row in scoped_rows(transform) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED")
    report = transform.finalize()
    final = next(
        row for row in graph_rows(transform.output_edge_file) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED"
    )
    assert taxonomy._equal_row(final, raw)
    path = transform.output_dir / "source_reference_resolution.tsv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    assert {row["disposition"] for row in rows} == {"unresolved_deleted_taxid"}
    if damage is None:
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
        assert transform.finalize() == report
        return
    if damage == "not-deleted":
        _taxdump(Path(transform.input_base_dir), merged="", deleted="")
        digest = hashlib.sha256((Path(transform.input_base_dir) / "taxdump.tar.gz").read_bytes()).hexdigest()
        for row in rows:
            row["authority_sha256"] = digest
    elif damage == "wrong-hash":
        for row in rows:
            row["authority_sha256"] = "0" * 64
    else:
        for row in rows:
            original = json.loads(row["original_edge_json"])
            original["relation"] = "unsupported:relation"
            row["original_edge_json"] = json.dumps(original)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(SourceFinalizationRequired):
        transform._taxonomy_evidence_guard._finalized_expectations({taxonomy._row_key(raw): raw}, transform.output_dir)


def _restamp_retirement_authority(transform, report, *, audit_rows=None):
    """Keep bounded fixture receipts coherent so public admission must inspect native semantics."""
    taxdump = Path(transform.input_base_dir) / "taxdump.tar.gz"
    digest = hashlib.sha256(taxdump.read_bytes()).hexdigest()
    report["consumed_inputs"]["ncbi_taxonomy_authority"]["sha256"] = digest
    for item in report["inputs"]:
        if item["path"] == str(taxdump.resolve()):
            item["sha256"] = digest
    audit = transform.output_dir / "source_reference_resolution.tsv"
    with audit.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields = reader.fieldnames
        rows = list(reader) if audit_rows is None else audit_rows
    for row in rows:
        if row["authority"] == "taxdump.tar.gz":
            row["authority_sha256"] = digest
    with audit.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report["audit_members"][audit.name] = {
        "bytes": audit.stat().st_size,
        "sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
    }
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))


@pytest.mark.parametrize("declaration", ["named", "typed"])
def test_declared_nonprokaryote_retirement_passes_independent_bacdive_admission(
    tmp_path, monkeypatch, local_source_schema, declaration
):
    """Explicit original declarations keep exact nonprokaryote replacements and all observation fields."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True)
    if declaration == "typed":
        # Retain the producer's specific category while exercising a blank
        # original label; only the original declaration, not the new label,
        # determines whether anonymous-reference trimming applies.
        path = Path(transform.output_node_file)
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row["id"] == "NCBITaxon:10":
                row["name"] = ""
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE)
            writer.writeheader()
            writer.writerows(rows)
    _taxdump(Path(transform.input_base_dir), merged="10 | 20 |\n")
    raw = next(row for row in scoped_rows(transform) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED")
    contract = copy.deepcopy(transform._taxonomy_evidence_guard.contract)
    report = transform.finalize()
    final = next(row for row in scoped_rows(transform) if row["subject"] == raw["subject"])
    assert taxonomy._equal_row(final, {**raw, "object": "NCBITaxon:20", "original_object": "NCBITaxon:10"})
    assert report["producer_native_inputs"]["taxonomy"] == contract
    originals = [
        json.loads(row["original_node_json"])
        for row in graph_rows(transform.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL)
        if row["original_id"] == "NCBITaxon:10" and row["original_node_json"]
    ]
    assert originals and all(row["category"] == "biolink:OrganismTaxon" for row in originals)
    assert all(bool(row["name"]) == (declaration == "named") for row in originals)
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report


def test_anonymous_nonprokaryote_retirement_does_not_relax_bacdive_assertion_guard(
    tmp_path, monkeypatch, local_source_schema
):
    """The declared-taxid exception cannot authorize dropping an anonymous scoped observation."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=False)
    _taxdump(Path(transform.input_base_dir), merged="10 | 20 |\n")
    paths = [Path(transform.output_node_file), Path(transform.output_edge_file)]
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(SourceFinalizationRequired, match="unsupported or incomplete finalized taxonomy"):
        transform.finalize()
    assert {path: path.read_bytes() for path in paths} == before
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("damage", ["missing", "anonymous", "wrong-id"])
def test_nonprokaryote_retirement_needs_its_original_source_declaration(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """A named projected node cannot substitute for a matching explicit original source declaration."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True)
    _taxdump(Path(transform.input_base_dir), merged="10 | 20 |\n")
    report = transform.finalize()
    rows = list(graph_rows(transform.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    assert any(row["original_node_json"] for row in rows)
    for row in rows:
        if not row["original_node_json"]:
            continue
        original = json.loads(row["original_node_json"])
        if damage == "missing":
            row["original_node_json"] = ""
        else:
            if damage == "anonymous":
                original.update(name="", category="biolink:NamedThing")
            else:
                original["id"] = "NCBITaxon:999"
            row["original_node_json"] = json.dumps(original)
    _restamp_retirement_authority(transform, report, audit_rows=rows)
    message = "wrong original identifier" if damage == "wrong-id" else "does not prove the finalized taxonomy"
    with pytest.raises(SourceFinalizationRequired, match=message):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_public_anonymous_retirement_still_requires_prokaryote_authority(tmp_path, monkeypatch, local_source_schema):
    """Restamping a nonprokaryote lineage cannot use the generated final label as declaration proof."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=False)
    report = transform.finalize()
    _taxdump(
        Path(transform.input_base_dir),
        nodes="1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 1 | species |\n",
    )
    _restamp_retirement_authority(transform, report)
    with pytest.raises(SourceFinalizationRequired, match="does not prove the finalized taxonomy replacement"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("reverse_chain", [False, True])
@pytest.mark.parametrize("live_chain_member", [None, "10", "11", "31"])
def test_public_retirement_proof_checks_every_selected_native_nonterminal(
    tmp_path, monkeypatch, local_source_schema, reverse_chain, live_chain_member
):
    """Fresh admission rejects live hidden chain members, but leaves unrelated chains outside this proof."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True)
    report = transform.finalize()
    graph_before = {
        Path(path): Path(path).read_bytes() for path in (transform.output_node_file, transform.output_edge_file)
    }
    witness_before = copy.deepcopy(report["producer_native_inputs"])
    chain = ["10 | 11 |\n", "11 | 12 |\n", "30 | 31 |\n", "31 | 12 |\n"]
    if reverse_chain:
        chain.reverse()
    nodes = "1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 2 | species |\n"
    if live_chain_member:
        # No scientific name for these extra nodes: nodes.dmp membership itself
        # contradicts retirement, even when that taxid was never a source endpoint.
        nodes += f"{live_chain_member} | 2 | species |\n"
    _taxdump(Path(transform.input_base_dir), merged="".join(chain), nodes=nodes)
    _restamp_retirement_authority(transform, report)
    if live_chain_member in {"10", "11"}:
        with pytest.raises(SourceFinalizationRequired, match="live chain member"):
            verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    else:
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    assert report["producer_native_inputs"] == witness_before
    assert {path: path.read_bytes() for path in graph_before} == graph_before


@pytest.mark.parametrize("claim", [{"name": "Invented local name"}, {"category": "biolink:OrganismTaxon"}])
def test_public_retirement_rejects_forged_original_declaration(tmp_path, monkeypatch, local_source_schema, claim):
    """Neither audit names nor categories can invent a native-proven local producer declaration."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=False)
    assert not any(row["id"] == "NCBITaxon:10" for row in graph_rows(transform.output_node_file))
    report = transform.finalize()
    graph_before = {
        Path(path): Path(path).read_bytes() for path in (transform.output_node_file, transform.output_edge_file)
    }
    native_before = copy.deepcopy(report["producer_native_inputs"])
    _taxdump(Path(transform.input_base_dir), nodes="1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 1 | species |\n")
    rows = list(graph_rows(transform.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    for row in rows:
        if row["original_id"] == "NCBITaxon:10":
            assert not row["original_node_json"]
            row["original_node_json"] = json.dumps({"id": "NCBITaxon:10", **claim})
    _restamp_retirement_authority(transform, report, audit_rows=rows)
    with pytest.raises(SourceFinalizationRequired, match="does not prove the finalized taxonomy replacement"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    assert report["producer_native_inputs"] == native_before
    assert {path: path.read_bytes() for path in graph_before} == graph_before


@pytest.mark.parametrize("damage", ["insert", "remove", "label"])
def test_original_declaration_requires_actual_selected_cache_membership(tmp_path, monkeypatch, damage):
    """A mutable constructor preview cannot add, erase, or relabel native selected membership."""
    original = taxonomy.prepare_source_declarations

    def corrupt(transform, *args):
        """Mutate only the real producer cache immediately before the proof checkpoint."""
        if damage == "insert":
            transform.ncbitaxon_labels["NCBITaxon:10"] = "Injected declaration"
        elif damage == "remove":
            transform.ncbitaxon_labels.pop("NCBITaxon:10")
        else:
            transform.ncbitaxon_labels["NCBITaxon:10"] = "Changed label"
        return original(transform, *args)

    monkeypatch.setattr(taxonomy, "prepare_source_declarations", corrupt)
    with pytest.raises(SourceFinalizationRequired, match="cache differs from actual selected membership"):
        retired_producer(tmp_path, monkeypatch, declare_retired=damage == "insert")


@pytest.mark.parametrize("damage", ["edit", "delete", "role", "cache"])
def test_source_declaration_input_and_cache_remain_bound_until_finalization(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """An earlier successful proof does not permit later source-role, input, or cache substitution."""
    from kg_microbe.transform_utils.bacdive.source_declaration_evidence import SELECTED_ROLE

    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True)
    before = {Path(path): Path(path).read_bytes() for path in (transform.output_node_file, transform.output_edge_file)}
    selected = Path(transform.input_base_dir) / "fixture-selected-ncbitaxon.tsv"
    if damage == "edit":
        selected.write_text(selected.read_text() + "NCBITaxon:10\tbiolink:OrganismTaxon\tNew\t\n")
    elif damage == "delete":
        selected.unlink()
    elif damage == "role":
        transform._consumed_input_snapshots.pop(SELECTED_ROLE)
    else:
        transform.ncbitaxon_labels["NCBITaxon:10"] = "Changed after producer"
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize()
    assert {path: path.read_bytes() for path in before} == before
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize(
    "route",
    [
        "medium",
        "pdf-medium",
        "custom-keyword",
        "alias-keyword",
        "tree-keyword",
        "unknown-medium",
        "ambiguous-keyword",
        "missing-tree-context",
    ],
)
@pytest.mark.parametrize("shared_parent", [False, True])
def test_selected_member_native_emitters_prove_local_retirement_declaration(
    tmp_path, monkeypatch, local_source_schema, route, shared_parent
):
    """Actual medium/keyword emitters can declare a selected parent, including for another record's edge."""
    from kg_microbe.transform_utils.bacdive.source_declaration_evidence import CUSTOM_ROLE, METPO_ROLE, SELECTED_ROLE
    from kg_microbe.transform_utils.constants import BACDIVE_MEDIUM_DICT

    first = {
        "General": {"BacDive-ID": 31, "NCBI tax id": {"NCBI tax id": 10}},
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    records = [first]
    emitter = first
    if shared_parent:
        emitter = {"General": {"BacDive-ID": 32, "NCBI tax id": {"NCBI tax id": 10}}}
        records.append(emitter)
    if "medium" in route:
        url = (
            "https://www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium1.pdf"
            if route == "pdf-medium"
            else next(iter(BACDIVE_MEDIUM_DICT.values())) + "1"
        )
        if route == "unknown-medium":
            url = "https://example.org/unrecognized-medium"
        emitter["Culture and growth conditions"] = {
            "culture medium": {"link": url, "name": "Fixture medium", "growth": "yes"}
        }
    else:
        emitter["General"]["keywords"] = [
            "tree-key"
            if route in {"tree-keyword", "missing-tree-context"}
            else "yes"
            if route == "ambiguous-keyword"
            else "fixture_keyword"
        ]
        if route == "tree-keyword":
            emitter["Example"] = {"values": "tree-key"}

    def context(transform):
        """Supply actual key inputs and matching constructor caches, never a claimed declaration flag."""
        if route == "custom-keyword":
            Path(bacdive_module.CUSTOM_CURIES_YAML_FILE).write_text(
                "fixture:\n  fixture_keyword:\n    category: biolink:PhenotypicQuality\n"
                "    predicate: biolink:has_phenotype\n    curie: METPO:1000001\n    name: Fixture keyword\n"
            )
        elif route in {"alias-keyword", "tree-keyword", "missing-tree-context", "ambiguous-keyword"}:
            Path(bacdive_module.CUSTOM_CURIES_YAML_FILE).write_text("{}\n")
            templates = tmp_path / "keyword-templates"
            templates.mkdir()
            fixture_templates = Path(__file__).parent / "resources/metpo_templates"
            (templates / "metpo-properties.tsv").write_text(
                (fixture_templates / "metpo-properties.tsv")
                .read_text()
                .replace("http://w3id.org/biolink/vocab/", "biolink:")
            )
            alias = "fixture_keyword" if route == "alias-keyword" else ""
            path = "Example.values" if route in {"tree-keyword", "missing-tree-context"} else ""
            synonym = "tree-key" if route in {"tree-keyword", "missing-tree-context"} else ""
            classes = (
                "ID\tlabel\tparent classes (one strongly preferred)\tmadin synonym or field\tbacdive keyword synonym\n"
                "ID\tLABEL\tSC %\tA synonym\tA synonym\n"
                f"METPO:1000059\tphenotype\t\t\t{path}\n"
                f"METPO:1000001\tFixture keyword\tphenotype\t{synonym}\t{alias}\n"
            )
            if route == "ambiguous-keyword":
                classes += (
                    "METPO:1000010\tfirst context\tphenotype\t\t\n"
                    "METPO:1000011\tsecond context\tphenotype\t\t\n"
                    "METPO:1000012\tfirst yes\tfirst context\t\tyes\n"
                    "METPO:1000013\tsecond yes\tsecond context\t\tyes\n"
                )
            (templates / "metpo_sheet.tsv").write_text(classes)
            monkeypatch.setenv("KG_MICROBE_METPO_TEMPLATE_DIR", str(templates))
            transform.bacdive_metpo_mappings = bacdive_module.load_metpo_mappings("bacdive keyword synonym")
            transform.bacdive_metpo_tree = bacdive_module._build_metpo_tree()
            transform.metpo_iri_to_mapping = transform._build_metpo_iri_index()
            transform.__dict__.pop("_ambiguous_metpo_aliases", None)

    transform, _, _, _ = produce(
        tmp_path,
        monkeypatch,
        records,
        gss=False,
        retired_fixture=True,
        forbid_ancestry_selection=True,
        declaration_context=context,
    )
    has_local = route not in {"unknown-medium", "ambiguous-keyword", "missing-tree-context"}
    assert any(row["id"] == "NCBITaxon:10" for row in graph_rows(transform.output_node_file)) == has_local
    if not has_local:
        report = transform.finalize()
        assert report["producer_native_inputs"]["taxonomy"]["source_declarations"]["native_emissions"] == []
        _taxdump(
            Path(transform.input_base_dir), nodes="1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 1 | species |\n"
        )
        rows = list(graph_rows(transform.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
        for row in rows:
            if row["original_id"] == "NCBITaxon:10":
                row["original_node_json"] = json.dumps({"id": "NCBITaxon:10", "category": "biolink:OrganismTaxon"})
        _restamp_retirement_authority(transform, report, audit_rows=rows)
        with pytest.raises(SourceFinalizationRequired, match="does not prove the finalized taxonomy replacement"):
            verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
        return
    _taxdump(Path(transform.input_base_dir), merged="10 | 20 |\n")
    report = transform.finalize()
    proof = report["producer_native_inputs"]["taxonomy"]["source_declarations"]
    assert proof["native_emissions"] and {entry["target"] for entry in proof["native_emissions"]} == {"NCBITaxon:10"}
    assert SELECTED_ROLE in report["consumed_inputs"]
    if "keyword" in route:
        assert {CUSTOM_ROLE, METPO_ROLE} <= report["consumed_inputs"].keys()
    final = next(row for row in scoped_rows(transform) if row["subject"] == "kgmicrobe.strain:TEST-RETIRED")
    assert final["object"] == "NCBITaxon:20" and final["original_object"] == "NCBITaxon:10"
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    assert transform.finalize() == report


@pytest.mark.parametrize("damage", ["bytes", "same-byte-retarget", "lost-admission"])
def test_public_original_declaration_keeps_selected_input_binding_alive(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Fresh public admission retains selected locator, bytes, and guard membership after returning."""
    selected_paths = {}

    def context(transform):
        """Select a real symlink before the original producer proof consumes it."""
        locator = Path(transform.input_base_dir) / "fixture-selected-ncbitaxon.tsv"
        original = locator.with_name("original-selected.tsv")
        locator.rename(original)
        locator.symlink_to(original)
        selected_paths.update(locator=locator, original=original)

    record = {
        "General": {"BacDive-ID": 31, "NCBI tax id": {"NCBI tax id": 10}},
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    transform, _, _, _ = produce(
        tmp_path,
        monkeypatch,
        [record],
        gss=False,
        retired_fixture=True,
        declare_retired=True,
        forbid_ancestry_selection=True,
        declaration_context=context,
    )
    report = transform.finalize()
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    locator, original = selected_paths["locator"], selected_paths["original"]
    if damage == "bytes":
        original.write_text(original.read_text() + "NCBITaxon:10\tbiolink:OrganismTaxon\tInserted\t\n")
    elif damage == "same-byte-retarget":
        replacement = original.with_name("replacement-selected.tsv")
        replacement.write_bytes(original.read_bytes())
        locator.unlink()
        locator.symlink_to(replacement)
    else:
        admission.identities.pop(original.resolve())
        admission.stamps.pop(original.resolve())
    with pytest.raises(SourceFinalizationRequired):
        admission.verify()


def test_genuine_zero_source_declaration_demand_consumes_no_authority(tmp_path, monkeypatch):
    """No native NCBI parent demand must not fabricate selected or keyword read obligations."""
    from kg_microbe.transform_utils.bacdive.source_declaration_evidence import (
        ALIASES_ROLE,
        CUSTOM_ROLE,
        METPO_ROLE,
        SELECTED_ROLE,
    )

    def context(_transform):
        """Leave an unused selected locator absent without weakening any actual parent proof."""
        monkeypatch.setattr(bacdive_module, "NCBITAXON_NODES_FILE", tmp_path / "unused-nonexistent-selected.tsv")

    transform, _, _, _ = produce(
        tmp_path,
        monkeypatch,
        [{"General": {"BacDive-ID": 31}}],
        gss=False,
        forbid_ancestry_selection=True,
        declaration_context=context,
    )
    proof = transform._taxonomy_evidence_guard.contract["source_declarations"]
    assert proof["targets"] == [] and proof["selected_input"] is None
    assert proof["keyword_inputs"] == {} and proof["native_emissions"] == []
    assert not {SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE} & transform.consumed_input_snapshots.keys()
    assert transform._taxonomy_evidence_guard.contract["fallback_native_evidence"]["selected_input"] is None


def test_prior_taxonomy_contract_requires_independent_declaration_proof(tmp_path, monkeypatch, local_source_schema):
    """Version three already had withheld contests but cannot authorize the new declaration exception."""
    transform = retired_producer(tmp_path, monkeypatch, declare_retired=True)
    report = transform.finalize()
    report["producer_native_inputs"]["taxonomy"]["version"] = 3
    with pytest.raises(SourceFinalizationRequired, match="predates independent original source declaration proof"):
        BacDiveTransform.verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")
