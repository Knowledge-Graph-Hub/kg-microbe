"""BTO names require exact declared class labels and retained authority bytes."""

import gzip
import hashlib
import sqlite3
from pathlib import Path

import pytest

from kg_microbe.transform_utils.prego import bto_metadata
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_prego_envo_identity import _producer, _rows


def producer(tmp_path, identifiers=("BTO:0000763",)):
    """Use full PREGO parsing with synthetic associations and isolated ontology fixtures."""
    records = [
        {
            "channel": "annotated_genomes_isolates",
            "row": ["-2", "562", "-25", identifier, "JGI IMG", "Isolates", "4", "TRUE", ""],
        }
        for identifier in identifiers
    ]
    return _producer(tmp_path, records=records)


def alter_database(transform, statements):
    """Change only the test's selected authority before the actual loader runs."""
    compressed = transform.input_base_dir / bto_metadata.FILENAME
    database = transform.input_base_dir / "alter.db"
    database.write_bytes(gzip.decompress(compressed.read_bytes()))
    with sqlite3.connect(database) as connection:
        for query, arguments in statements:
            connection.execute(query, arguments)
    compressed.write_bytes(gzip.compress(database.read_bytes(), mtime=0))
    database.unlink()


def test_names_come_from_classes_not_dictionary_synonyms(tmp_path):
    """Only referenced classes are emitted, carrying source version and digest in the audit."""
    transform = producer(tmp_path, ("BTO:0000763", "BTO:9999999"))
    transform.run(show_status=False)
    nodes = {row["id"]: row for row in _rows(transform.output_node_file)}
    assert nodes["BTO:0000763"]["name"] == "lung"
    assert nodes["BTO:0000763"]["provided_by"] == "infores:prego|infores:bto"
    assert nodes["BTO:9999999"]["name"] == ""
    assert "BTO:0001481" not in nodes
    audit = {row["id"]: row for row in _rows(transform.output_dir / bto_metadata.AUDIT_FILE)}
    assert audit["BTO:0000763"]["status"] == "labelled_class"
    assert audit["BTO:9999999"]["status"] == "unresolved_class_or_label"
    assert audit["BTO:0000763"]["version_iri"] == "obo:bto/releases/2021-10-26/bto.owl"
    assert (
        audit["BTO:0000763"]["authority_sha256"]
        == hashlib.sha256((transform.input_base_dir / bto_metadata.FILENAME).read_bytes()).hexdigest()
    )
    assert len(_rows(transform.output_edge_file)) == 2


def test_relative_input_and_output_paths(tmp_path, monkeypatch):
    """Production-style relative paths resolve safely for read-only SQLite access."""
    monkeypatch.chdir(tmp_path)
    transform = producer(Path("relative"))
    transform.run(show_status=False)
    assert any(row["name"] == "lung" for row in _rows(transform.output_node_file))


def test_retired_class_keeps_own_name_id_and_retirement_flag(tmp_path):
    """A label lookup never follows replacements or treats a retired node as live."""
    transform = producer(tmp_path)
    alter_database(
        transform, [("INSERT INTO statements VALUES (?,?,?,?)", ("BTO:0000763", "owl:deprecated", None, "true"))]
    )
    transform.run(show_status=False)
    node = next(row for row in _rows(transform.output_node_file) if row["id"] == "BTO:0000763")
    assert (node["name"], node["deprecated"]) == ("lung", "True")
    assert _rows(transform.output_edge_file)[0]["subject"] == "BTO:0000763"


def test_untyped_label_is_not_admitted(tmp_path):
    """A bare label assertion without an owl:Class declaration cannot hydrate a node."""
    transform = producer(tmp_path)
    alter_database(transform, [("DELETE FROM statements WHERE subject=? AND predicate='rdf:type'", ("BTO:0000763",))])
    transform.run(show_status=False)
    node = next(row for row in _rows(transform.output_node_file) if row["id"] == "BTO:0000763")
    assert node["name"] == ""
    assert node["provided_by"] == "infores:prego"


@pytest.mark.parametrize("damage", ["conflicting_label", "bad_deprecation", "malformed_database", "missing"])
def test_invalid_authority_fails_before_graph_output(tmp_path, damage):
    """No incomplete metadata authority can silently substitute blank-name success."""
    transform = producer(tmp_path)
    path = transform.input_base_dir / bto_metadata.FILENAME
    if damage == "missing":
        path.unlink()
    elif damage == "malformed_database":
        path.write_bytes(gzip.compress(b"not a SQLite database"))
    else:
        predicate, value = (
            ("rdfs:label", "another organ") if damage == "conflicting_label" else ("owl:deprecated", "perhaps")
        )
        alter_database(
            transform, [("INSERT INTO statements VALUES (?,?,?,?)", ("BTO:0000763", predicate, None, value))]
        )
    with pytest.raises((ValueError, sqlite3.DatabaseError, FileNotFoundError)):
        transform.run(show_status=False)
    assert not transform.output_node_file.exists()


@pytest.mark.parametrize("damage", ["bytes", "locator", "audit"])
def test_completed_source_binds_bto_authority_and_audit(tmp_path, damage):
    """Read-only source admission refuses post-completion bytes, locators or audit drift."""
    transform = _producer(tmp_path, records=[])
    authority = transform.input_base_dir / bto_metadata.FILENAME
    if damage == "locator":
        first = tmp_path / "first.gz"
        first.write_bytes(authority.read_bytes())
        authority.unlink()
        authority.symlink_to(first)
    transform.run(show_status=False)
    report = transform.finalize(fresh_run=True)
    assert bto_metadata.ROLE in report["consumed_inputs"]
    assert bto_metadata.AUDIT_FILE in report["producer_audit_members"]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    if damage == "bytes":
        authority.write_bytes(authority.read_bytes() + b"changed")
    elif damage == "locator":
        alternate = tmp_path / "alternate.gz"
        alternate.write_bytes(authority.read_bytes())
        authority.unlink()
        authority.symlink_to(alternate)
    else:
        (transform.output_dir / bto_metadata.AUDIT_FILE).write_text("changed\n")
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
