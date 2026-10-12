"""Actual local SQL and selected-file context for explicitly synthetic fallback controls."""

import csv
import sqlite3
from contextlib import closing

import pytest
from oaklib.implementations.sqldb.sql_implementation import SqlImplementation
from oaklib.resource import OntologyResource

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive import isolation_categories


def create_database(path, labels):
    """Create honest synthetic live prokaryotic classes, never copied native-epoch receipts."""
    rows = []
    all_labels = {"NCBITaxon:1": "Fixture root", "NCBITaxon:2": "Bacteria", **labels}
    for identifier, label in all_labels.items():
        rows.extend(
            [
                (identifier, identifier, "rdf:type", "owl:Class", None, None, None),
                (identifier, identifier, "rdfs:label", None, label, None, None),
            ]
        )
        if identifier != "NCBITaxon:1":
            parent = "NCBITaxon:1" if identifier == "NCBITaxon:2" else "NCBITaxon:2"
            rank = "superkingdom" if identifier == "NCBITaxon:2" else "genus"
            rows.extend(
                [
                    (identifier, identifier, "rdfs:subClassOf", parent, None, None, None),
                    (identifier, identifier, "obo:ncbitaxon#has_rank", "NCBITaxon:" + rank, None, None, None),
                ]
            )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE statements(stanza TEXT,subject TEXT,predicate TEXT,object TEXT,"
            "value TEXT,datatype TEXT,language TEXT)"
        )
        connection.execute("CREATE INDEX statements_spv ON statements(subject,predicate,value)")
        connection.execute("CREATE INDEX statements_p ON statements(predicate)")
        connection.execute("CREATE TABLE entailed_edge(subject TEXT,predicate TEXT,object TEXT)")
        connection.executemany("INSERT INTO statements VALUES (?,?,?,?,?,?,?)", rows)
        connection.execute(
            "INSERT INTO statements(subject,predicate,value) VALUES "
            "('obo:ncbitaxon.owl','owl:versionInfo','synthetic-selector-fixture-not-a-native-epoch')"
        )
    return path


def write_selected(path, labels, synonyms=None):
    """Write actual tiny selected-node input, with unmodified synthetic labels and explicit aliases."""
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "category", "name", "synonym"])
        for identifier, label in sorted(labels.items()):
            writer.writerow([identifier, "biolink:OrganismTaxon", label, (synonyms or {}).get(identifier, "")])


@pytest.fixture
def synthetic_fallback_context(tmp_path, monkeypatch):
    """Seed real fixture authorities per run and close only fixture-owned original adapters afterward."""
    adapters = []

    def install(answers, *, direct_labels=None):
        """Retain a mutable test answer source while each run consumes a distinct immutable file."""
        original_prepare = isolation_categories.prepare_policy
        captured, epochs = [], []

        def prepare(transform):
            """Replace omitted constructor context before native preparation, never a selection method."""
            labels = dict(direct_labels or {})
            for name, identifier in answers.items():
                assert identifier not in labels or labels[identifier] == name
                labels[identifier] = name
            root = tmp_path / f"synthetic-authority-epoch-{len(epochs)}"
            root.mkdir()
            database = create_database(root / "ncbitaxon.db", labels)
            selected = root / "ncbitaxon_nodes.tsv"
            write_selected(selected, labels)
            adapter = SqlImplementation(resource=OntologyResource(slug=str(database.absolute())))
            adapters.append(adapter)
            transform.ncbi_impl = adapter
            transform.ncbitaxon_labels = dict(labels)
            transform._ncbitaxon_ancestor_cache = {}
            transform.lpsn_name_index = {}
            monkeypatch.setattr(module, "NCBITAXON_NODES_FILE", selected)
            captured.append(transform)
            epochs.append({"database": database, "selected": selected, "labels": labels})
            return original_prepare(transform)

        monkeypatch.setattr(isolation_categories, "prepare_policy", prepare)
        return captured, epochs

    yield install
    for adapter in adapters:
        if adapter._session is not None:
            adapter._session.close()
        adapter.engine.dispose()


def assert_actual_native_batch(transform, *, expected_targets, expected_eligible):
    """Require native eligibility and single physical reads, not a mocked legacy lookup call counter."""
    child = transform._taxonomy_evidence_guard.contract["fallback_native_evidence"]
    assert child["eligible_record_count"] == expected_eligible
    assert {plan["early_target"] for plan in child["plans"].values()} == set(expected_targets)
    native = child["native_queries"]
    assert native["connection"]["computed_queries"] == []
    assert native["exact_label_batch"]["native_statements_scanned"] > 0
    physical = [(row["kind"], row["parameter"]) for row in native["physical_queries"]]
    assert len(physical) == len(set(physical))
    assert all(kind == "declaration" for kind, _identifier in physical)
    assert child["selected_input"]["role"] is not None
    return child
