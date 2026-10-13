"""Honest native excerpts for finite restrictions, retaining the original two controls."""

import copy
import csv
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from kg_microbe.utils import go_authority
from kg_microbe.utils import go_imported_restrictions as restrictions

FIXTURE = Path(__file__).parent / "resources/go_subject_restrictions"
FULL_POLICY = json.loads(restrictions.POLICY_FILE.read_text())
# Existing regression tests deliberately continue to exercise the old two rows.
# The actual prepared policy and native fixtures always include the full scope.
POLICY = {**FULL_POLICY, "records": FULL_POLICY["records"][:2]}
ORIGIN = json.loads((FIXTURE / "origin.json").read_text())


# The policy binds go.db through the go.owl release it was built from. Only that
# file's bytes are checked, so a stand-in exercises the same path as the real release.
GO_OWL_STAND_IN = b'<?xml version="1.0"?>\n<!-- stand-in for the pinned go.owl release -->\n'


def rows(path, *, quoted=False):
    """Read only tiny fixture graphs or quoted diagnostic evidence."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE))


def write_rows(path, records, *, fields=None, quoted=False):
    """Write test-owned rows with the actual source dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields or list(records[0]),
            delimiter="\t",
            quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE,
            quotechar='"' if quoted else None,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(records)


def prepare(tmp_path, monkeypatch, *, all_claims=False, additional_go_statements=()):
    """Bind the exact excerpt bytes explicitly, never pretend they are complete native inputs."""
    assert restrictions._digest(restrictions._json(FULL_POLICY).encode()) == ORIGIN["reviewed_policy_sha256"]
    assert FULL_POLICY["sources"] == ORIGIN["full_sources"]
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    shutil.copyfile(FIXTURE / "pato.owl", raw / "pato.owl")
    for record in FULL_POLICY["records"]:
        assert record["native_class_xml"].encode() in (raw / "pato.owl").read_bytes()
        assert (
            restrictions._digest(record["native_class_xml"].encode())
            == ORIGIN["native_class_sha256"][record["subject"]]
        )
    # Multiple reviewed restrictions can share a subject. Preserve each complete
    # subject's statement multiset once, as in the real SQL authority, rather
    # than multiplying its SQL rows by the number of restrictions.
    by_subject = {}
    for block in [FULL_POLICY["canonical_go_metadata"], *[r["selected_go_metadata"] for r in FULL_POLICY["records"]]]:
        grouped = {}
        for row in block:
            grouped.setdefault(row["subject"], []).append(row)
        for subject, values in grouped.items():
            if subject in by_subject:
                assert sorted(json.dumps(r, sort_keys=True) for r in by_subject[subject]) == sorted(
                    json.dumps(r, sort_keys=True) for r in values
                )
            else:
                by_subject[subject] = values
    statements = [row for values in by_subject.values() for row in values]
    # Two selected rows point at rdftab blank nodes; a real build stores what they state.
    statements.extend({"subject": label, **row} for label, rows in FULL_POLICY["blank_nodes"].items() for row in rows)
    # A sibling-only control can add separately sourced native context before
    # constructing and hashing the actual fixture database and authority.
    statements.extend(additional_go_statements)
    # A real SemSQL build records the GO release on the ontology node; the policy
    # binds that release and the go.owl it was built from, not the database bytes.
    statements.append(
        {
            "subject": "obo:go.owl",
            "predicate": "owl:versionInfo",
            "object": None,
            "value": FULL_POLICY["sources"]["go.db"]["release"],
        }
    )
    (raw / "go.owl").write_bytes(GO_OWL_STAND_IN)
    with sqlite3.connect(raw / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.execute("CREATE TABLE edge(subject,predicate,object)")
        connection.execute("CREATE TABLE entailed_edge(subject,predicate,object)")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [tuple(row[column] for column in ("subject", "predicate", "object", "value")) for row in statements],
        )
    policy = copy.deepcopy(FULL_POLICY)
    policy["sources"]["pato.owl"]["sha256"] = hashlib.sha256((raw / "pato.owl").read_bytes()).hexdigest()
    policy["sources"]["go.db"]["source"]["sha256"] = hashlib.sha256(GO_OWL_STAND_IN).hexdigest()
    path = tmp_path / "fixture-policy.json"
    path.write_text(json.dumps(policy, sort_keys=True))
    monkeypatch.setattr(restrictions, "POLICY_FILE", path)
    monkeypatch.setattr(
        restrictions, "REVIEWED_POLICY_SHA256", restrictions._digest(restrictions._json(policy).encode())
    )
    monkeypatch.setattr(go_authority, "_prepare_go_database", lambda root: root / "go.db")
    authority = go_authority.load_go_authority(raw)
    nodes, edges, audit = (
        tmp_path / name for name in ("pato_nodes.tsv", "pato_edges.tsv", "go_reference_resolution.tsv")
    )
    node_rows, edge_rows = [], []
    for record in policy["records"] if all_claims else POLICY["records"]:
        subject = record["subject"]
        node_rows.append(
            {
                "id": subject,
                "category": "biolink:BiologicalProcess",
                "name": authority.records[subject].label,
                "provided_by": "infores:pato",
            }
        )
        edge_rows.append(
            {
                "subject": subject,
                "predicate": record["predicate"],
                "object": record["object"],
                "relation": record["relation"],
                "primary_knowledge_source": "infores:pato",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
                "publications": "PMID:fixture-native-context",
                "source_record": subject,
            }
        )
    write_rows(nodes, node_rows)
    write_rows(edges, edge_rows)
    return raw, nodes, edges, audit, authority
