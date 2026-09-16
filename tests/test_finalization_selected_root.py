"""An exact-repeat finalization cannot silently ignore a newly selected raw authority root."""

import csv
import sqlite3
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.go_authority import load_go_authority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

FIXTURES = Path(__file__).parent / "resources" / "go_authority"


def _authority_database(raw_dir, fixture):
    """Build a tiny actual SQLite authority from immutable SemSQL-shaped input rows."""
    raw_dir.mkdir()
    with (FIXTURES / fixture).open(newline="") as source, sqlite3.connect(raw_dir / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.execute("CREATE TABLE edge(subject,predicate,object)")
        reader = csv.DictReader(source, delimiter="\t")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            (tuple(row[key] or None for key in ("subject", "predicate", "object", "value")) for row in reader),
        )


def test_repeat_finalization_rejects_changed_selected_raw_root(tmp_path, monkeypatch):
    """A different explicit raw root requires a producer rerun, not reuse of another root's audit."""
    first, second = tmp_path / "first-raw", tmp_path / "second-raw"
    _authority_database(first, "statements.tsv")
    _authority_database(second, "selected_root_statements.tsv")
    # Bypass only production database size/rebuild checks. Metadata parsing,
    # exact byte fingerprints, normalization, publication, and repeat checks
    # all use the real implementation against actual SQLite files.
    monkeypatch.setattr("kg_microbe.utils.go_authority._prepare_go_database", lambda root: root / "go.db")
    assert load_go_authority(first).resolve("GO:0004096").label == "catalase activity"
    assert load_go_authority(second).resolve("GO:0004096").label == "Selected-root catalase activity"

    producer = Transform("fixture", first, tmp_path / "transformed")
    producer.output_node_file.write_text("id\tname\tcategory\nGO:0004096\tImporter label\tbiolink:BiologicalProcess\n")
    producer.output_edge_file.write_text("subject\tpredicate\tobject\trelation\n")
    initial = producer.finalize(fresh_run=True)
    snapshots = {path: path.read_bytes() for path in producer.output_dir.iterdir() if path.is_file()}
    assert producer.finalize() == initial
    assert {path: path.read_bytes() for path in snapshots} == snapshots

    producer.input_base_dir = second
    with pytest.raises(SourceFinalizationRequired, match="Selected raw input directory changed"):
        producer.finalize()
    assert {path: path.read_bytes() for path in snapshots} == snapshots
    assert next(graph_rows(producer.output_node_file))["name"] == "catalase activity"
