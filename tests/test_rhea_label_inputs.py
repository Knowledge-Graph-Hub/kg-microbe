"""Rhea labels come only from exact, consumed, read-only DBs in the selected raw root."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from kg_microbe.transform_utils.rhea_mappings import label_inputs as module
from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import RheaMappingsTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_consumed_inputs
from tests.rhea_fixtures import stage_rhea_label_databases
from tests.test_rhea_native_transform import _producer, _rows


class LabelFixture(Transform):
    """Require real label snapshots without pretending this fixture emitted Rhea reactions."""

    REQUIRED_CONSUMED_INPUTS = module.REQUIRED_LABEL_INPUTS


def _fixture(tmp_path):
    """Prepare tiny selected-root authorities without an OAK adapter or network access."""
    transform = LabelFixture("rhea_mappings", tmp_path / "selected raw", tmp_path / "out")
    stage_rhea_label_databases(transform.input_base_dir)
    return transform


def _sql(transform, filename, statement, args=()):
    """Vary only an isolated fixture authority before its actual snapshot is consumed."""
    with sqlite3.connect(transform.input_base_dir / filename) as connection:
        connection.execute(statement, args)


def test_all_three_authorities_are_exact_consumed_raw_root_inputs(tmp_path):
    """Successful lookups bind every authority even when only one namespace is requested."""
    transform = _fixture(tmp_path)
    with module.external_label_lookup(transform) as lookup:
        assert lookup("CHEBI:15377") == "water"
        assert lookup("GO:0000001") == "fixture GO activity"
        assert lookup("EC:1.2.3.4") == "fixture EC activity"
    assert set(transform.consumed_input_snapshots) == set(module.REQUIRED_LABEL_INPUTS)
    for role, (filename, _, _) in module.LABEL_DATABASES.items():
        path = transform.input_base_dir / filename
        assert transform.consumed_input_snapshots[role] == {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    verify_consumed_inputs(transform)


def test_exact_identity_missing_labels_and_literal_text_are_not_reinterpreted(tmp_path):
    """No alias, synonym, local-part fallback, or label sanitization establishes an identity."""
    transform = _fixture(tmp_path)
    _sql(transform, "chebi.db", "UPDATE statements SET value=? WHERE subject='CHEBI:15377'", (' literal "water" ',))
    _sql(transform, "chebi.db", "INSERT INTO statements VALUES ('CHEBI:99','oboInOwl:hasExactSynonym',NULL,'water')")
    with module.external_label_lookup(transform) as lookup:
        assert lookup("CHEBI:15377") == ' literal "water" '
        assert lookup("CHEBI:99") == ""
        assert lookup("CHEBI:99") == ""  # Count distinct queried IDs, not participant occurrences.
        assert lookup("CHEBI:9999999") == ""
        assert lookup("EC:3.6.5.n1") == ""
        assert lookup.missing_counts == {"CHEBI:": 2, "GO:": 0, "EC:": 1}
        with pytest.raises(ValueError, match="Unsupported"):
            lookup("chebi:15377")


def test_duplicate_identical_labels_do_not_create_ambiguity(tmp_path):
    """Repeated evidence for one literal is not a second competing label."""
    transform = _fixture(tmp_path)
    _sql(transform, "chebi.db", "INSERT INTO statements VALUES ('CHEBI:15377','rdfs:label',NULL,'water')")
    with module.external_label_lookup(transform) as lookup:
        assert lookup("CHEBI:15377") == "water"


@pytest.mark.parametrize("filename", ["chebi.db", "go.db", "ec.db"])
def test_absent_authority_never_falls_back_to_a_global_database(tmp_path, filename):
    """The selected root must supply each authority; nothing is built or downloaded."""
    transform = _fixture(tmp_path)
    (transform.input_base_dir / filename).unlink()
    with pytest.raises(FileNotFoundError):
        with module.external_label_lookup(transform):
            pytest.fail("Missing selected-root DB must fail before lookup")
    assert not (transform.input_base_dir / filename).exists()
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize(
    "change,error",
    [
        ("DROP TABLE statements", "columns"),
        ("ALTER TABLE statements RENAME COLUMN value TO wrong", "columns"),
        ("DROP INDEX statements_spv", "index"),
        ("DELETE FROM statements WHERE predicate='rdf:type'", "expected ontology"),
        ("UPDATE statements SET subject='obo:go.owl' WHERE predicate='rdf:type'", "expected ontology"),
    ],
)
def test_wrong_schema_or_ontology_fails_closed(tmp_path, change, error):
    """A readable SQLite file is not automatically the selected ontology authority."""
    transform = _fixture(tmp_path)
    _sql(transform, "chebi.db", change)
    with pytest.raises(SourceFinalizationRequired, match=error):
        with module.external_label_lookup(transform):
            pytest.fail("Invalid label authority must not be yielded")
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


def test_corrupt_sqlite_propagates_an_infrastructure_failure(tmp_path):
    """Corruption is not converted into thousands of missing labels."""
    transform = _fixture(tmp_path)
    (transform.input_base_dir / "chebi.db").write_bytes(b"not SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        with module.external_label_lookup(transform):
            pytest.fail("Corrupt authority must fail")
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize(
    "obj,value,error",
    [(None, "different water", "Ambiguous"), ("CHEBI:1", "water", "Nonliteral"), (None, b"water", "Nonliteral")],
)
def test_ambiguous_or_nonliteral_labels_are_not_selected(tmp_path, obj, value, error):
    """Exact subject matching does not justify choosing one conflicting annotation."""
    transform = _fixture(tmp_path)
    _sql(transform, "chebi.db", "INSERT INTO statements VALUES ('CHEBI:15377','rdfs:label',?,?)", (obj, value))
    with pytest.raises(SourceFinalizationRequired, match=error):
        with module.external_label_lookup(transform) as lookup:
            lookup("CHEBI:15377")
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("when", ["before", "during", "after"])
def test_unconsumed_sqlite_state_is_rejected_at_every_gate(tmp_path, suffix, when):
    """A main DB hash alone cannot prove that a new WAL or journal was absent."""
    transform = _fixture(tmp_path)
    sidecar = Path(str(transform.input_base_dir / "chebi.db") + suffix)
    if when == "before":
        sidecar.write_bytes(b"")
    if when in {"before", "during"}:
        with pytest.raises(SourceFinalizationRequired, match="sidecar"):
            with module.external_label_lookup(transform) as lookup:
                assert lookup("CHEBI:15377") == "water"
                sidecar.write_bytes(b"")
        with pytest.raises(SourceFinalizationRequired, match="read failed"):
            verify_consumed_inputs(transform)
    else:
        with module.external_label_lookup(transform):
            pass
        sidecar.write_bytes(b"")
        report = {
            "producer_native_inputs": module.LABEL_CONTRACT,
            "raw_input_directory": str(transform.input_base_dir),
            "consumed_inputs": transform.consumed_input_snapshots,
        }
        with pytest.raises(SourceFinalizationRequired, match="sidecar"):
            RheaMappingsTransform.verify_recorded_native_inputs(report, None)


def test_only_read_only_immutable_snapshots_are_opened_by_sqlite(tmp_path, monkeypatch):
    """SQLite never queries the mutable original or opens any write-capable connection."""
    transform = _fixture(tmp_path)
    real_connect, opened = sqlite3.connect, []

    def checked_connect(database, **kwargs):
        """Inspect the real connection mode without replacing any SQLite query behavior."""
        assert database.endswith("?mode=ro&immutable=1") and kwargs == {"uri": True}
        assert str(transform.input_base_dir) not in database
        connection = real_connect(database, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO statements VALUES ('bad','bad',NULL,'bad')")
        opened.append(database)
        return connection

    monkeypatch.setattr(module.sqlite3, "connect", checked_connect)
    with module.external_label_lookup(transform) as lookup:
        assert lookup("CHEBI:15377") == "water"
    assert len(opened) == 3


@pytest.mark.parametrize("filename", ["chebi.db", "go.db", "ec.db"])
def test_authority_drift_after_read_prevents_finalization(tmp_path, filename):
    """Freshness is bound to the bytes actually read, not a later DB restamp."""
    transform = _fixture(tmp_path)
    with module.external_label_lookup(transform):
        pass
    _sql(transform, filename, "INSERT INTO statements VALUES ('changed','rdfs:label',NULL,'changed')")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        verify_consumed_inputs(transform)


def test_lookup_reads_snapshot_even_if_original_changes_during_run(tmp_path):
    """A lookup sees the consumed bytes and the original drift still aborts the context."""
    transform = _fixture(tmp_path)
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        with module.external_label_lookup(transform) as lookup:
            _sql(transform, "chebi.db", "UPDATE statements SET value='changed' WHERE subject='CHEBI:15377'")
            assert lookup("CHEBI:15377") == "water"
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize(
    "contract", [None, {}, {**module.LABEL_CONTRACT, "version": True}, {**module.LABEL_CONTRACT, "extra": 1}]
)
def test_reader_contract_is_exact_in_repeat_and_recorded_admission(tmp_path, contract):
    """Neither a bool version nor extra keys may masquerade as the validated reader epoch."""
    producer = RheaMappingsTransform(tmp_path / "raw", tmp_path / "out")
    with pytest.raises(SourceFinalizationRequired, match="contract changed"):
        producer.producer_native_inputs = contract
    with pytest.raises(SourceFinalizationRequired, match="contract changed"):
        producer.verify_recorded_native_inputs({"producer_native_inputs": contract}, None)


def test_recorded_role_cannot_switch_to_another_raw_root(tmp_path):
    """Even an otherwise well-formed role must name its declared raw-root DB."""
    transform = _fixture(tmp_path)
    with module.external_label_lookup(transform):
        pass
    with pytest.raises(SourceFinalizationRequired, match="selected raw root"):
        module.verify_label_bindings(tmp_path / "other", transform.consumed_input_snapshots)


def test_real_producer_has_no_global_adapter_dependency_and_keeps_authoritative_labels(tmp_path, monkeypatch):
    """All native graph semantics remain while external labels use the selected prepared inputs."""
    from kg_microbe.utils import ontology_utils

    def forbidden(*args, **kwargs):
        """Fail if the producer reaches an ambient ontology adapter."""
        pytest.fail("Rhea must not build, resolve, or download through a global ontology adapter")

    for name in ("get_chebi_adapter", "get_go_adapter", "get_ec_adapter", "resolve_adapter"):
        monkeypatch.setattr(ontology_utils, name, forbidden)
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    nodes = {row["id"]: row for row in _rows(producer.output_node_file)}
    assert nodes["CHEBI:15377"]["name"] == "water"
    assert nodes["GO:0000001"]["name"] == "fixture GO activity"
    assert nodes["EC:1.2.3.4"]["name"] == "fixture EC activity"
    assert nodes["rheav:Polymer_2"]["name"] == "fixture polymer (n+1)"
    verify_consumed_inputs(producer)
    Path(str(producer.input_base_dir / "chebi.db") + "-wal").write_bytes(b"")
    with pytest.raises(SourceFinalizationRequired, match="sidecar"):
        verify_consumed_inputs(producer)


def test_label_failure_preserves_existing_graph_and_audit_outputs(tmp_path, monkeypatch):
    """The label context exits and verifies before any atomic output is published."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    _sql(producer, "chebi.db", "INSERT INTO statements VALUES ('CHEBI:15377','rdfs:label',NULL,'conflict')")
    outputs = (
        producer.output_node_file,
        producer.output_edge_file,
        producer.output_dir / "rhea_reaction_dispositions.tsv",
    )
    for output in outputs:
        output.write_text("previous output\n")
    with pytest.raises(SourceFinalizationRequired, match="Ambiguous"):
        producer.run(show_status=False)
    assert all(output.read_text() == "previous output\n" for output in outputs)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(producer)


def test_real_producer_reports_unique_missing_external_labels(tmp_path, monkeypatch, capsys):
    """An absent exact-ID label is explicit and countable, never replaced by its local identifier."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    _sql(producer, "ec.db", "DELETE FROM statements WHERE predicate='rdfs:label'")
    producer.run(show_status=True)
    node = next(row for row in _rows(producer.output_node_file) if row["id"] == "EC:1.2.3.4")
    assert node["name"] == ""
    assert "missing_external_labels={'CHEBI:': 0, 'GO:': 0, 'EC:': 1}" in capsys.readouterr().out
