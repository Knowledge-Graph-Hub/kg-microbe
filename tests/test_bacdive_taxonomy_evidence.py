"""
Exercise source-local taxonomy evidence and owned native-reader lifecycle.

All output and synthetic authorities belong under tmp_path. The literal control
fixtures explicitly make no biological/native-source identity claims.
"""

import copy
import csv
import hashlib
import json
import os
import sqlite3
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
    extra_edges=(),
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
        write_selected(selected, labels, {"NCBITaxon:99": "Actinobacteria"})
        monkeypatch.setattr(bacdive_module, "NCBITAXON_NODES_FILE", selected)
        transform.ncbitaxon_fallback_cache = {}
        transform._ncbitaxon_ancestor_cache = {}
        transform.ncbitaxon_labels = {}
        if retired_fixture:
            # Suppress only the producer's unrelated local stub insertion, using
            # its existing preview-label route. Actual source finalization must
            # discover and prove this undeclared reference from real native tar.
            transform.ncbitaxon_labels = {"NCBITaxon:10": "fixture historical preview"}
            _taxdump(Path(transform.input_base_dir))
        transform.lpsn_name_index = {}
        transform.metpo_metabolite_production_mappings = load_metpo_metabolite_production_mappings()
        if gss:
            (Path(transform.input_base_dir) / "lpsn_gss.csv").write_bytes((RESOURCE / "lpsn_gss.csv").read_bytes())
        if forbid_ancestry_selection:

            def forbidden(_adapter):
                """Refuse a second adapter selection when deposit resolver demand is zero."""
                raise AssertionError("zero-query deposit phase resolved an adapter")

            monkeypatch.setattr(bacdive_module, "resolve_adapter", forbidden)

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
    # Keep the original immutable inode readable after replacement on platforms
    # where the default writable SQLite handle reports a moved-file I/O error.
    # The engine URL still identifies the real selected path for the new reader.
    engine = create_engine(
        "sqlite:///" + str(path.absolute()),
        creator=lambda: sqlite3.connect(path.absolute().as_uri() + "?mode=ro&immutable=1", uri=True),
        poolclass=StaticPool,
    )
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


def retired_producer(tmp_path, monkeypatch):
    """Create one actual supplied parent with a literal native 10→11→12 retirement chain."""
    record = {
        "General": {"BacDive-ID": 31, "NCBI tax id": {"NCBI tax id": 10}},
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    transform, _, _, _ = produce(
        tmp_path, monkeypatch, [record], gss=False, retired_fixture=True, forbid_ancestry_selection=True
    )
    return transform


def test_actual_finalization_retirement_keeps_raw_choice_and_exact_projection(
    tmp_path, monkeypatch, local_source_schema
):
    """Real source-finalizer retirement is verified separately, not mistaken for changed parent selection."""
    transform = retired_producer(tmp_path, monkeypatch)
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
