"""ChEBI role loading follows headers and retains ontology evidence (#1080)."""

import csv
from pathlib import Path

import pytest

from kg_microbe.transform_utils.mediadive import mediadive as module
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.transform_utils.transform import Transform

FIXTURE = Path(__file__).parent / "resources" / "assay_reference_repairs"


@pytest.fixture
def transform(monkeypatch, tmp_path):
    """Load only immutable ChEBI fixtures; no clients, production data, or adapters."""
    result = MediaDiveTransform.__new__(MediaDiveTransform)
    Transform.__init__(result, "mediadive", input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    result.chebi_roles = {}
    result.chebi_role_edges = {}
    result.chebi_labels = {}
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", FIXTURE / "chebi_edges.tsv")
    monkeypatch.setattr(module, "CHEBI_NODES_FILE", FIXTURE / "chebi_nodes.tsv")
    return result


def _rewrite(path, fields, rows):
    """Create one temporary schema variant without changing the immutable fixture."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_current_header_loads_unique_roles_and_labels(transform):
    """The current seven-column schema is not the retired id-first layout."""
    transform._load_chebi_roles()
    assert transform.chebi_roles == {"CHEBI:100": ["CHEBI:76924"], "CHEBI:10002": ["CHEBI:35620"]}
    assert len(transform.chebi_role_edges["CHEBI:100"]) == 1
    assert transform.chebi_labels["CHEBI:76924"] == "fixture role"


@pytest.mark.parametrize("extensions", [[], ["value", "unit", "publications"]])
def test_role_rows_match_seven_or_ten_column_headers(transform, extensions):
    """Restored role loading must not turn ontology axioms into experimental observations."""
    transform.edge_header += extensions
    transform._load_chebi_roles()
    rows = transform._generate_chebi_role_edges(["CHEBI:100", "CHEBI:100", "CHEBI:missing"])
    assert len(rows) == 1
    assert len(rows[0]) == len(transform.edge_header)
    row = dict(zip(transform.edge_header, rows[0], strict=True))
    assert row["subject"] == "CHEBI:100"
    assert row["object"] == "CHEBI:76924"
    assert row["predicate"] == "biolink:has_chemical_role"
    assert row["relation"] == "RO:0000087"
    assert row["primary_knowledge_source"] == "infores:chebi"
    assert row["knowledge_level"] == "knowledge_assertion"
    assert row["agent_type"] == "manual_agent"
    assert all(row[column] == "" for column in extensions)


def test_reordered_and_legacy_extra_id_columns_are_supported(transform, tmp_path, monkeypatch):
    """Only header names, never positions, identify subject, object and relation."""
    with (FIXTURE / "chebi_edges.tsv").open(newline="") as stream:
        original = csv.DictReader(stream, delimiter="\t")
        fields = ["id", *reversed(original.fieldnames)]
        rows = [{"id": str(index), **row} for index, row in enumerate(original)]
    path = tmp_path / "edges.tsv"
    _rewrite(path, fields, rows)
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", path)
    transform._load_chebi_roles()
    assert transform.chebi_roles["CHEBI:100"] == ["CHEBI:76924"]
    transform.edge_header.reverse()
    row = dict(zip(transform.edge_header, transform._generate_chebi_role_edges(["CHEBI:10002"])[0], strict=True))
    assert row["object"] == "CHEBI:35620"


@pytest.mark.parametrize("filename", ["CHEBI_EDGES_FILE", "CHEBI_NODES_FILE"])
def test_missing_required_inputs_fail_with_recovery_command(transform, tmp_path, monkeypatch, filename):
    """Missing inputs cannot silently publish a zero-role transform."""
    monkeypatch.setattr(module, filename, tmp_path / "missing.tsv")
    with pytest.raises(FileNotFoundError, match="poetry run kg transform -s ontologies"):
        transform._load_chebi_roles()
    assert transform.chebi_roles == {}


@pytest.mark.parametrize(
    "contents",
    [
        "subject\tobject\nCHEBI:100\tCHEBI:76924\n",
        "subject\tobject\tobject\nCHEBI:100\tCHEBI:76924\tCHEBI:2\n",
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\nCHEBI:100\ttruncated\n",
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\nCHEBI:100\tbiolink:has_chemical_role\tCHEBI:76924\tRO:0000087\tinfores:chebi\t\tmanual_agent\n",
    ],
)
def test_invalid_headers_rows_or_role_metadata_fail(transform, tmp_path, monkeypatch, contents):
    """Malformed schemas and incomplete ontology evidence fail rather than becoming empty lookups."""
    path = tmp_path / "invalid.tsv"
    path.write_text(contents)
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", path)
    with pytest.raises(ValueError):
        transform._load_chebi_roles()
    assert transform.chebi_roles == {}


def test_distinct_source_metadata_is_not_pooled(transform, tmp_path, monkeypatch):
    """Exact duplicate assertions deduplicate, but distinct source evidence remains distinct."""
    with (FIXTURE / "chebi_edges.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    rows.append({**rows[0], "agent_type": "automated_agent"})
    path = tmp_path / "edges.tsv"
    _rewrite(path, list(rows[0]), rows)
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", path)
    transform._load_chebi_roles()
    assert len(transform._generate_chebi_role_edges(["CHEBI:100"])) == 2


def test_unquoted_kgx_scalar_quotes_are_preserved(transform, tmp_path, monkeypatch):
    """Literal quote characters survive the ontology finalizer's QUOTE_NONE dialect."""
    path = tmp_path / "nodes.tsv"
    path.write_text('id\tcategory\tname\nCHEBI:76924\tbiolink:ChemicalRole\t"quoted role"\n')
    monkeypatch.setattr(module, "CHEBI_NODES_FILE", path)
    edge_path = tmp_path / "edges.tsv"
    edge_path.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\tpublications\n"
        "CHEBI:100\tbiolink:has_chemical_role\tCHEBI:76924\tRO:0000087\t"
        'infores:chebi\tknowledge_assertion\tmanual_agent\t"literal citation"\n'
    )
    monkeypatch.setattr(module, "CHEBI_EDGES_FILE", edge_path)
    transform.edge_header.append("publications")
    transform._load_chebi_roles()
    assert transform.chebi_labels["CHEBI:76924"] == '"quoted role"'
    row = dict(zip(transform.edge_header, transform._generate_chebi_role_edges(["CHEBI:100"])[0], strict=True))
    assert row["publications"] == '"literal citation"'
