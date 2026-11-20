"""Exercise a reporting-only, explicit-local CMM intake without network or graph mutation."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.adhoc import audit_cmm_intake as intake

FIXTURE = Path(__file__).parent / "resources/cmm_intake"


@pytest.fixture
def inputs(tmp_path):
    """Copy immutable evidence into a test-owned directory."""
    nodes, edges = tmp_path / "nodes.tsv", tmp_path / "edges.tsv"
    shutil.copyfile(FIXTURE / "nodes.tsv", nodes)
    shutil.copyfile(FIXTURE / "edges.tsv", edges)
    return nodes, edges, tmp_path / "audit"


def _records(output):
    """Read only tiny test findings, not graph-scale data."""
    return [json.loads(line) for line in (output / "findings.jsonl").read_text().splitlines()]


def test_preserves_complete_original_claims_and_duplicates(inputs):
    """Retain literal original bytes, duplicate claims and their original row numbers."""
    nodes, edges, output = inputs
    before = {"nodes": nodes.read_bytes(), "edges": edges.read_bytes()}
    result = intake.audit(nodes, edges, output)
    assert result["status"] == "INTAKE_AUDIT_ONLY_NOT_ADMITTED"
    assert result["source_activated"] is result["canonical_admission"] is result["release_ready"] is False
    assert result["tables"]["nodes"]["rows"] == result["tables"]["edges"]["rows"] == 5
    for role, source in (("nodes", nodes), ("edges", edges)):
        assert source.read_bytes() == before[role] == (output / f"original_{role}.tsv").read_bytes()
        assert result["inputs"][role]["sha256"] == hashlib.sha256(before[role]).hexdigest()
        assert result["inputs"][role]["bytes"] == len(before[role])
    assert set(path.name for path in output.iterdir()) == {
        "original_nodes.tsv",
        "original_edges.tsv",
        "findings.jsonl",
        "counts.jsonl",
        "manifest.json",
    }
    findings = _records(output)
    duplicates = [row for row in findings if row["code"] == "duplicate_edge_row_preserved"]
    assert len(duplicates) == 1 and duplicates[0]["line"] == 3
    assert result["finding_counts"]["duplicate_node_id"] == 1
    assert result["finding_counts"]["endpoint_not_declared_in_supplied_nodes"] == 1
    assert result["finding_counts"]["self_loop_requires_review"] == 1
    assert result["finding_counts"]["non_scalar_infores_provenance"] == 5
    assert result["tables"]["edges"]["missing_required_columns"] == ["agent_type", "knowledge_level"]
    counts = [json.loads(line) for line in (output / "counts.jsonl").read_text().splitlines()]
    assert result["tables"]["nodes"]["distinct_node_prefixes"] == 4
    assert result["tables"]["edges"]["distinct_predicates"] == 3
    assert {"table": "edges", "kind": "predicate", "value": "biolink:has_part", "rows": 3} in counts
    assert result == json.loads((output / "manifest.json").read_text())
    for name, pin in result["artifacts"].items():
        assert pin["sha256"] == hashlib.sha256((output / name).read_bytes()).hexdigest()


def test_reuses_current_repository_schema_constants():
    """Fail if this finite intake profile drifts from the shared canonical schema."""
    from kg_microbe.utils.graph_schema import CANONICAL_EDGE_HEADER, CANONICAL_NODE_HEADER, REQUIRED_NODE_COLUMNS

    assert list(intake.NODE_COLUMNS) == CANONICAL_NODE_HEADER
    assert list(intake.EDGE_COLUMNS) == CANONICAL_EDGE_HEADER
    assert intake.NODE_REQUIRED == REQUIRED_NODE_COLUMNS


def test_high_cardinality_labels_are_streamed_outside_manifest(inputs):
    """Keep arbitrary prefix/predicate cardinality in the on-disk index and streamed count report."""
    nodes, edges, output = inputs
    with nodes.open("w") as node_stream, edges.open("w") as edge_stream:
        node_stream.write("id\n")
        edge_stream.write("subject\tpredicate\tobject\n")
        for number in range(1500):
            node_stream.write(f"prefix{number}:1\n")
            edge_stream.write(f"prefix{number}:1\tbiolink:predicate_{number}\tprefix{number}:1\n")
    result = intake.audit(nodes, edges, output)
    assert result["tables"]["nodes"]["distinct_node_prefixes"] == 1500
    assert result["tables"]["edges"]["distinct_predicates"] == 1500
    assert "biolink:predicate_1499" not in (output / "manifest.json").read_text()
    with (output / "counts.jsonl").open() as stream:
        assert sum(1 for _ in stream) == 3000


@pytest.mark.parametrize(
    "table,content,match",
    [
        ("nodes", b"", "missing TSV header"),
        ("nodes", b"name\nExample\n", "missing identity columns"),
        ("edges", b"subject\tobject\na\tb\n", "missing identity columns"),
        ("nodes", b"id\tid\na\ta\n", "duplicate header"),
        ("nodes", b"id\t\na\tb\n", "blank"),
        ("nodes", b"id\t name\na\tb\n", "whitespace"),
        ("nodes", b"id\tname\na\n", "expected 2 fields"),
        ("nodes", b"id\na\tb\n", "expected 1 fields"),
        ("nodes", b"id\n\n", "empty graph identity"),
        ("nodes", b"id\n   \n", "empty graph identity"),
        ("edges", b"subject\tpredicate\tobject\na\t\tb\n", "empty graph identity"),
        ("nodes", b"id\nNCBITaxon:1\x00\n", "NUL"),
        ("nodes", b"id\n\xff\n", "utf-8"),
    ],
)
def test_structural_failure_publishes_nothing(inputs, table, content, match):
    """Refuse invalid structure and leave inputs plus preexisting files untouched."""
    nodes, edges, output = inputs
    target = nodes if table == "nodes" else edges
    target.write_bytes(content)
    with pytest.raises((ValueError, UnicodeError), match=match):
        intake.audit(nodes, edges, output)
    assert not output.exists()
    assert target.read_bytes() == content
    assert not list(output.parent.glob(".cmm-intake-*"))


@pytest.mark.parametrize("ending", [b"\r\n", b"\r", b""])
def test_noncanonical_transport_is_reported_not_rewritten(inputs, ending):
    """Preserve CRLF, CR and missing-final-LF evidence while reporting canonical transport gaps."""
    nodes, edges, output = inputs
    if ending:
        original = edges.read_bytes().replace(b"\n", ending)
    else:
        original = edges.read_bytes().rstrip(b"\n")
    edges.write_bytes(original)
    result = intake.audit(nodes, edges, output)
    assert result["finding_counts"]["noncanonical_line_ending"] > 0
    assert (output / "original_edges.tsv").read_bytes() == original


@pytest.mark.parametrize("kind", ["file", "directory", "populated", "symlink", "dangling_symlink"])
def test_existing_output_is_never_overwritten(inputs, kind):
    """An existing output belongs to its owner, including an empty directory or symlink."""
    nodes, edges, output = inputs
    if kind == "file":
        output.write_text("keep")
    elif kind in {"directory", "populated"}:
        output.mkdir()
        if kind == "populated":
            (output / "keep").write_text("keep")
    else:
        output.symlink_to(nodes if kind == "symlink" else output.parent / "absent")
    with pytest.raises(FileExistsError):
        intake.audit(nodes, edges, output)
    assert output.exists() or output.is_symlink()
    if kind == "populated":
        assert (output / "keep").read_text() == "keep"


def test_rejects_source_aliases_and_overlap(inputs):
    """Reject identical or hard-linked source roles and output paths overlapping original input."""
    nodes, edges, output = inputs
    with pytest.raises(ValueError, match="distinct files"):
        intake.audit(nodes, nodes, output)
    hardlink = nodes.parent / "alias.tsv"
    os.link(nodes, hardlink)
    with pytest.raises(ValueError, match="distinct files"):
        intake.audit(nodes, hardlink, output)
    with pytest.raises(FileExistsError):
        intake.audit(nodes, edges, nodes)
    with pytest.raises(FileExistsError):
        intake.audit(nodes, edges, nodes.parent)


def test_rejects_linked_or_nonregular_inputs(inputs):
    """Do not silently follow input symlinks or accept directories as source files."""
    nodes, edges, output = inputs
    alias = nodes.parent / "linked.tsv"
    alias.symlink_to(nodes)
    with pytest.raises(ValueError, match="regular non-symlink"):
        intake.audit(alias, edges, output)
    with pytest.raises(ValueError, match="regular non-symlink"):
        intake.audit(nodes.parent, edges, output)


def test_detects_original_input_change_after_snapshot(inputs, monkeypatch):
    """A scan of stable copied bytes must not conceal a source file changed during the audit."""
    nodes, edges, output = inputs
    scan = intake._scan

    def changed(*args):
        """Simulate a source writer without altering the stable copied table."""
        result = scan(*args)
        if args[1] == "edges":
            edges.write_bytes(edges.read_bytes() + edges.read_bytes().splitlines(keepends=True)[1])
        return result

    monkeypatch.setattr(intake, "_scan", changed)
    with pytest.raises(ValueError, match="Input changed during audit"):
        intake.audit(nodes, edges, output)
    assert not output.exists()


def test_detects_retained_copy_change(inputs, monkeypatch):
    """Verify the retained originals again before publishing the report."""
    nodes, edges, output = inputs
    scan = intake._scan

    def changed(path, *args):
        """Simulate a changed retained file after its complete inspection."""
        result = scan(path, *args)
        if args[0] == "edges":
            path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(intake, "_scan", changed)
    with pytest.raises(ValueError, match="Retained input changed"):
        intake.audit(nodes, edges, output)
    assert not output.exists()


def test_output_created_during_audit_is_not_replaced(inputs, monkeypatch):
    """Use an exclusive publication reservation even if the initial destination check passed."""
    nodes, edges, output = inputs
    publish = intake._publish

    def collision(staging, destination):
        """Create another owner's output immediately before publication."""
        destination.mkdir()
        (destination / "keep").write_text("keep")
        publish(staging, destination)

    monkeypatch.setattr(intake, "_publish", collision)
    with pytest.raises(FileExistsError):
        intake.audit(nodes, edges, output)
    assert [path.name for path in output.iterdir()] == ["keep"]


def test_failed_publication_removes_only_owned_empty_reservation(inputs, monkeypatch):
    """A rename failure does not leave a misleading complete-looking report directory."""
    nodes, edges, output = inputs

    def fail(*args):
        """Simulate an atomic publication failure."""
        raise OSError("test filesystem failure")

    monkeypatch.setattr(intake.os, "replace", fail)
    with pytest.raises(OSError, match="test filesystem failure"):
        intake.audit(nodes, edges, output)
    assert not output.exists()
    assert not list(output.parent.glob(".cmm-intake-*"))


def test_clean_mechanical_shape_still_never_claims_admission(inputs):
    """Even no finite finding cannot establish scientific authority or full KG conformance."""
    nodes, edges, output = inputs
    nodes.write_text(
        "id\tcategory\tname\tdescription\tprovided_by\n"
        "NCBITaxon:1\tbiolink:OrganismTaxon\tOne\t\tfixture\n"
        "NCBITaxon:2\tbiolink:OrganismTaxon\tTwo\t\tfixture\n"
    )
    edges.write_text(
        "\t".join(intake.EDGE_COLUMNS) + "\n"
        "NCBITaxon:1\tbiolink:related_to\tNCBITaxon:2\tbiolink:related_to\t"
        "infores:fixture\tknowledge_assertion\tmanual_agent\n"
    )
    result = intake.audit(nodes, edges, output)
    assert result["finding_counts"] == {}
    assert result["canonical_admission"] is result["release_ready"] is False
    assert len(result["limitations"]) == 6


@pytest.mark.parametrize(
    "field,value,code",
    [
        (intake.PRIMARY, "infores:a|infores:b", "non_scalar_infores_provenance"),
        (intake.PRIMARY, "", "blank_edge_value"),
        (intake.KNOWLEDGE, "invented", "unrecognized_provenance_value"),
        (intake.AGENT, "invented", "unrecognized_provenance_value"),
        (intake.RELATION, "", "blank_edge_value"),
        (intake.PREDICATE, "biolink:related_to|biolink:has_part", "non_curie_identifier"),
        (intake.OBJECT, "https://example.org/term", "full_iri_requires_review"),
    ],
)
def test_reports_provenance_and_identifier_gaps_without_repair(inputs, field, value, code):
    """Retain absent, pooled, unknown and malformed values as original evidence."""
    nodes, edges, output = inputs
    row = dict(
        zip(
            intake.EDGE_COLUMNS,
            (
                "NCBITaxon:1",
                "biolink:related_to",
                "NCBITaxon:1",
                "biolink:related_to",
                "infores:fixture",
                "knowledge_assertion",
                "manual_agent",
            ),
            strict=True,
        )
    )
    row[field] = value
    original = "\t".join(row) + "\n" + "\t".join(row.values()) + "\n"
    edges.write_text(original)
    intake.audit(nodes, edges, output)
    assert any(item["code"] == code and item["field"] == field and item["value"] == value for item in _records(output))
    assert (output / "original_edges.tsv").read_text() == original


def test_help_and_real_cli_work_without_site_packages(inputs):
    """Keep help and the complete local audit independent of KGX, OAK, pandas or downloads."""
    nodes, edges, output = inputs
    script = str(Path(intake.__file__).resolve())
    command = [sys.executable, "-I", "-S", script]
    helped = subprocess.run(command + ["--help"], capture_output=True, text=True, check=False)  # noqa: S603
    assert helped.returncode == 0 and "--nodes" in helped.stdout
    ran = subprocess.run(  # noqa: S603 - fixed local script and test-owned input paths
        command + ["--nodes", str(nodes), "--edges", str(edges), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert json.loads(ran.stdout)["status"] == "INTAKE_AUDIT_ONLY_NOT_ADMITTED"


def test_cli_error_does_not_publish(inputs):
    """A malformed table yields a nonzero CLI status, not a partial successful report."""
    nodes, edges, output = inputs
    edges.write_text("subject\n")
    command = [
        sys.executable,
        "-I",
        "-S",
        str(Path(intake.__file__).resolve()),
        "--nodes",
        str(nodes),
        "--edges",
        str(edges),
        "--output",
        str(output),
    ]
    ran = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    assert ran.returncode == 2 and "CMM intake failed" in ran.stderr
    assert not output.exists()
