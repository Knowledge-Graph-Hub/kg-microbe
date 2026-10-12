"""Actual UPA policy/snapshot fixtures, with separate active and inactive entry points."""

import copy
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from kg_microbe.transform_utils.ontologies import ontologies_transform as ontology_module
from kg_microbe.utils import go_authority
from kg_microbe.utils import upa_route_review as upa

FIXTURE = Path(__file__).parent / "resources/upa_route_review"


# Only the go.owl release file's bytes are checked, so a stand-in exercises the real path.
GO_OWL_STAND_IN = b'<?xml version="1.0"?>\n<!-- stand-in for the pinned go.owl release -->\n'


def rows(path, *, quoted=False):
    """Read a tiny literal graph or explicitly quoted producer audit."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE))


def write_rows(path, values, *, fields=None, quoted=False):
    """Write only test-owned graph rows without hiding literal quote semantics."""
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields or list(values[0]),
            delimiter="\t",
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE,
            quotechar='"' if quoted else None,
        )
        writer.writeheader()
        writer.writerows(values)


def prepare_empty_upa_route_contract(transform):
    """Read the genuine reviewed policy and emit a truthful non-UPA checkpoint."""
    if getattr(transform, "_upa_route_input_contract", None) is not None:
        raise AssertionError("An inactive fixture must not overwrite an existing UPA run")
    with (transform.output_dir / upa.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        guard = upa.UPARouteReview(transform, stream)
        assert guard.member_names() == ()
        guard.verify_complete()
    transform.record_producer_audit(upa.AUDIT_FILE)
    return (upa.POLICY_ROLE,)


def convert_with_native_schema(*, inputs, input_format, output, output_format):
    """Run the unchanged converter with genuine pinned mappings in a fresh offline interpreter."""
    assert len(inputs) == 1 and input_format == "obojson" and output_format == "tsv"
    native = FIXTURE.parent / "ingredient_bundle/native"
    origin = json.loads((native / "acceptance-native-origin.json").read_text())
    for name in ("biolink-model.yaml", "predicate_mapping.yaml", "attributes.yaml"):
        assert hashlib.sha256((native / name).read_bytes()).hexdigest() == origin["members"][name]["sha256"]
    # KGX retains Toolkit bindings at import time. An env change in this pytest
    # process would not replace those objects from other minimal-schema tests.
    script = """
import socket
import sys
import urllib.request
import requests

def reject_network(*args, **kwargs):
    raise AssertionError("Network prohibited in native UPA fixture conversion")

socket.getaddrinfo = reject_network
socket.gethostbyname = reject_network
socket.gethostbyname_ex = reject_network
socket.gethostbyaddr = reject_network
socket.create_connection = reject_network
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network
urllib.request.urlopen = reject_network
requests.sessions.Session.request = reject_network
from kg_microbe.transform_utils.ontologies.ontologies_transform import _run_kgx_transform
_run_kgx_transform(inputs=[sys.argv[1]], input_format="obojson", output=sys.argv[2], output_format="tsv")
"""
    try:
        result = subprocess.run(  # noqa: S603 - fixed local interpreter/script and immutable local fixture schema
            [sys.executable, "-c", script, str(inputs[0]), str(output)],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "KG_MICROBE_BIOLINK_MODEL": str((native / "biolink-model.yaml").resolve()),
                "KG_MICROBE_BIOLINK_PREDICATE_MAP": str((native / "predicate_mapping.yaml").resolve()),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            check=False,
            timeout=90,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        # Keep the child's partial output: a bare timeout says nothing about where it stalled.
        partial = f"{exc.stdout or ''}\n{exc.stderr or ''}"
        raise AssertionError(f"Native UPA fixture conversion timed out\n{partial}") from exc
    assert result.returncode == 0, result.stdout + result.stderr


def prepare(tmp_path, monkeypatch):
    """Bind faithful excerpts explicitly; never pretend their hashes identify full native files."""
    policy = upa.load_policy(upa.POLICY_FILE.read_bytes())
    origin = json.loads((FIXTURE / "origin.json").read_text())
    assert policy["sources"] == origin["full_sources"]
    assert upa.digest(policy) == origin["reviewed_policy_semantic_sha256"]
    for filename, expected in origin["fixtures"].items():
        assert hashlib.sha256((FIXTURE / filename).read_bytes()).hexdigest() == expected
    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for filename in ("upa.json", "upa.owl"):
        shutil.copyfile(FIXTURE / filename, raw / filename)
    statements = json.loads((FIXTURE / "go_statements.json").read_text())
    # A real SemSQL build records the GO release on the ontology node; the policy binds that
    # release and the go.owl it was built from, not the database bytes (#1420).
    statements.append(["obo:go.owl", "owl:versionInfo", None, policy["sources"]["go.db"]["release"]])
    (raw / "go.owl").write_bytes(GO_OWL_STAND_IN)
    with sqlite3.connect(raw / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.execute("CREATE TABLE edge(subject,predicate,object)")
        connection.execute("CREATE TABLE entailed_edge(subject,predicate,object)")
        connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)
    fixture_policy = copy.deepcopy(policy)
    fixture_policy["sources"]["upa.json"]["sha256"] = hashlib.sha256((raw / "upa.json").read_bytes()).hexdigest()
    fixture_policy["sources"]["upa.owl"] = hashlib.sha256((raw / "upa.owl").read_bytes()).hexdigest()
    fixture_policy["sources"]["go.db"]["source"]["sha256"] = hashlib.sha256(GO_OWL_STAND_IN).hexdigest()
    policy_path = tmp_path / "upa-fixture-policy.json"
    policy_path.write_text(json.dumps(fixture_policy), encoding="utf-8")
    monkeypatch.setattr(upa, "POLICY_FILE", policy_path)
    monkeypatch.setattr(upa, "POLICY_SHA256", upa.digest(fixture_policy))
    # The database already contains literal selected SQL evidence; no network/build bootstrap.
    # The existing authority loader, resolver and all input guards remain real.
    monkeypatch.setattr(go_authority, "_prepare_go_database", lambda directory: directory / "go.db")
    xrefs = tmp_path / "xrefs"
    monkeypatch.setattr(ontology_module, "ONTOLOGIES_XREFS_DIR", xrefs)
    monkeypatch.setattr(ontology_module, "UNIPATHWAYS_XREFS_FILEPATH", xrefs / "upa.tsv")
    monkeypatch.setattr(ontology_module, "_run_kgx_transform", convert_with_native_schema)
    transform = ontology_module.OntologiesTransform(raw, tmp_path / "transformed")
    return transform, fixture_policy, policy_path


def run_upa(tmp_path, monkeypatch, *, finalize=False):
    """Exercise the actual converter, legacy selector, screening, tail and optional publication."""
    transform, policy, policy_path = prepare(tmp_path, monkeypatch)
    transform.run(data_file="upa.json", show_status=False)
    report = transform.finalize(file_prefix="upa_", fresh_run=True) if finalize else None
    return transform, policy, policy_path, report
