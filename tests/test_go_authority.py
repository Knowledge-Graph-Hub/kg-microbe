"""Authoritative GO references retain aspects, historical evidence, and source identity."""

import csv
import json
import pickle
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from kg_microbe.utils.go_authority import (
    GoAuthority,
    GoReferenceError,
    load_go_authority,
    normalize_go_bundle,
)

FIXTURE = Path(__file__).parent / "resources" / "go_authority" / "statements.tsv"


@pytest.fixture
def statements():
    """Read immutable, intentionally tiny GO authority evidence."""
    with FIXTURE.open(newline="") as handle:
        return [
            tuple(row[column] or None for column in ("subject", "predicate", "object", "value"))
            for row in csv.DictReader(handle, delimiter="\t")
        ]


@pytest.fixture
def authority(statements):
    """Prepare a pure in-memory authority without production data or adapters."""
    return GoAuthority.from_statements(statements, authority_path="fixture/go.db", authority_sha256="a" * 64)


def _write(path, fields, rows):
    """Write a bounded source fixture under the pytest temporary directory."""
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    """Read a bounded test output."""
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.mark.parametrize(
    "identifier,category",
    [
        ("GO:0004096", "biolink:MolecularActivity"),
        ("GO:0008152", "biolink:BiologicalProcess"),
        ("GO:0005575", "biolink:CellularComponent"),
    ],
)
def test_authority_uses_all_three_aspects(authority, identifier, category):
    """Known GO namespaces are never replaced by a prefix-wide guessed aspect."""
    result = authority.resolve(identifier)
    assert result.category == category
    assert result.canonical_id == identifier
    assert result.node_fields()["provided_by"] == "infores:go"
    assert result.node_fields()["name"]


def test_historical_activity_retains_identity_and_consider(authority):
    """Consider is a curation suggestion, never an exact identity replacement."""
    result = authority.resolve("GO:0003840")
    assert result.canonical_id == "GO:0003840"
    assert result.deprecated
    assert result.namespace == "molecular_function"
    assert result.consider == ("GO:0036374",)
    assert result.node_fields()["deprecated"] == "true"
    assert "obsolete gamma-glutamyltransferase activity" == result.label
    assert "GO:0036374" in result.node_fields()["description"]


def test_exact_chain_and_alternate_id_are_proven(authority):
    """Only explicit unique replacements and alternative IDs change identity."""
    result = authority.resolve("GO:9999002")
    assert result.canonical_id == "GO:0004096"
    assert result.replacement_chain == ("GO:9999002", "GO:9999003", "GO:0004096")
    assert not result.deprecated
    assert authority.resolve("GO:9999001").canonical_id == "GO:0004096"
    assert authority.resolve("GO:9999004").canonical_id == "GO:9999004"
    assert authority.resolve("GO:9999005").deprecated


def test_unknown_identifier_fails_without_a_fabricated_aspect(authority):
    """An absent term is a visible reference error, not an invented BiologicalProcess."""
    with pytest.raises(GoReferenceError, match="GO:9999999"):
        authority.resolve("GO:9999999")


def test_authority_is_immutable_and_pickleable(authority):
    """Spawned workers receive metadata, not live database handles or mutable caches."""
    restored = pickle.loads(pickle.dumps(authority))
    assert restored.resolve("GO:0003840") == authority.resolve("GO:0003840")
    with pytest.raises(TypeError):
        authority.records["GO:0004096"] = None


@pytest.mark.parametrize(
    "extra",
    [
        [("GO:9999003", "IAO:0100001", "GO:9999002", None)],
        [("GO:0004096", "oio:hasOBONamespace", None, "biological_process")],
        [("GO:0008152", "oio:hasAlternativeId", "GO:9999001", None)],
    ],
)
def test_conflicting_authority_is_rejected(statements, extra):
    """Cycles, conflicting namespaces, and ambiguous alternative IDs are not guessed."""
    # Replace the fixture's second exact link when making a true cycle.
    if extra[0][0] == "GO:9999003":
        statements = [row for row in statements if not (row[0] == "GO:9999003" and row[1] == "IAO:0100001")]
    with pytest.raises(ValueError):
        GoAuthority.from_statements([*statements, *extra])


def test_loader_reads_selected_root_and_invalidates_changed_bytes(tmp_path, monkeypatch, statements):
    """A second raw root or changed database cannot inherit another authority's cache."""
    import kg_microbe.utils.go_authority as module

    monkeypatch.setattr(module, "_prepare_go_database", lambda raw_dir: raw_dir / "go.db")
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        with sqlite3.connect(directory / "go.db") as connection:
            connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
            connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)
    first = load_go_authority(tmp_path / "first")
    with sqlite3.connect(tmp_path / "second" / "go.db") as connection:
        connection.execute(
            "UPDATE statements SET value='second label' WHERE subject='GO:0004096' AND predicate='rdfs:label'"
        )
    second = load_go_authority(tmp_path / "second")
    assert second.resolve("GO:0004096").label == "second label"
    assert first.resolve("GO:0004096").label == "catalase activity"
    with sqlite3.connect(tmp_path / "first" / "go.db") as connection:
        connection.execute(
            "UPDATE statements SET value='new first label' WHERE subject='GO:0004096' AND predicate='rdfs:label'"
        )
    changed = load_go_authority(tmp_path / "first")
    assert changed.resolve("GO:0004096").label == "new first label"
    assert changed.authority_sha256 != first.authority_sha256


def test_legacy_go_helpers_accept_prepared_authority_without_io(authority, monkeypatch):
    """A caller may prepare immutable GO evidence before opening any producer output."""
    from kg_microbe.utils import ontology_utils

    def unexpected_io(*args, **kwargs):
        """Reject any authority lookup after immutable evidence is prepared."""
        raise AssertionError("Prepared authority must not open a database")

    monkeypatch.setattr("kg_microbe.utils.go_authority.load_go_authority", unexpected_io)
    assert ontology_utils.get_go_aspect("GO:0003840", authority=authority) == "molecular_function"
    assert ontology_utils.get_go_category_by_aspect("GO:0005575", authority=authority) == "biolink:CellularComponent"


def test_ontology_and_bakta_use_selected_authority_before_finalization(tmp_path, monkeypatch, statements):
    """Both producers classify from the explicit raw root, never a repository-default GO DB."""
    import kg_microbe.utils.go_authority as module
    from kg_microbe.transform_utils.bakta.bakta import BaktaTransform
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
    from kg_microbe.utils import ontology_utils

    raw_dir = tmp_path / "selected-raw"
    raw_dir.mkdir()
    with sqlite3.connect(raw_dir / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)
    prepared_roots = []

    def prepare_selected(directory):
        """Record and enforce use of the selected raw directory."""
        prepared_roots.append(directory)
        assert directory == raw_dir
        return directory / "go.db"

    monkeypatch.setattr(module, "_prepare_go_database", prepare_selected)
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent-default" / "go.owl")
    assert ontology_utils.get_go_aspect("GO:0004096", raw_dir=raw_dir) == "molecular_function"

    nodes = tmp_path / "go_nodes.tsv"
    _write(
        nodes,
        ["id", "category", "name"],
        [{"id": "GO:0004096", "category": "biolink:BiologicalProcess", "name": "catalase activity"}],
    )
    ontology = OntologiesTransform.__new__(OntologiesTransform)
    ontology.input_base_dir = raw_dir
    ontology._fix_node_categories(nodes, "go")
    assert _read(nodes)[0]["category"] == "biolink:MolecularActivity"

    bakta = BaktaTransform.__new__(BaktaTransform)
    bakta.input_base_dir = raw_dir
    bakta.knowledge_source = "infores:bakta"
    bakta.go_aspect_cache = {"GO:0004096": "biological_process"}
    bakta.nodes, bakta.edges, bakta.seen_nodes = [], [], set()
    bakta.add_go_annotation("UniProtKB:fixture", "GO:0004096")
    assert bakta.nodes[0]["category"] == "biolink:MolecularActivity"
    assert bakta.edges[0]["predicate"] == "biolink:enables"
    assert prepared_roots == [raw_dir]


@pytest.mark.parametrize("source", ["ec", "mondo"])
def test_imported_go_postprocessing_uses_selected_root(tmp_path, monkeypatch, statements, source):
    """Imported GO rows in EC/MONDO must not silently query the default raw release."""
    import kg_microbe.transform_utils.ontologies.ontologies_transform as ontology_module
    import kg_microbe.utils.go_authority as module

    raw_dir = tmp_path / "selected-raw"
    raw_dir.mkdir()
    with sqlite3.connect(raw_dir / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)

    def prepare_selected(directory):
        """Require imported ontology rows to use the selected GO release."""
        assert directory == raw_dir
        return directory / "go.db"

    monkeypatch.setattr(module, "_prepare_go_database", prepare_selected)
    monkeypatch.setattr("kg_microbe.transform_utils.constants.GO_SOURCE", tmp_path / "absent-default" / "go.owl")
    monkeypatch.setattr(ontology_module, "ONTOLOGIES_XREFS_DIR", tmp_path / "xrefs")
    monkeypatch.setattr(ontology_module, "MONDO_XREFS_FILEPATH", tmp_path / "xrefs" / "mondo.tsv")
    producer = ontology_module.OntologiesTransform(raw_dir, tmp_path / "transformed")
    nodes, edges = (producer.output_dir / f"{source}_{kind}.tsv" for kind in ("nodes", "edges"))
    _write(
        nodes,
        producer.node_header,
        [
            {
                "id": "GO:0004096",
                "category": "biolink:BiologicalProcess",
                "name": "catalase activity",
                "provided_by": "infores:go",
            }
        ],
    )
    _write(edges, producer.edge_header, [])
    producer.post_process(source)
    assert _read(nodes)[0]["category"] == "biolink:MolecularActivity"


def test_bundle_repairs_imports_preserves_observations_and_is_idempotent(tmp_path, authority):
    """Correction happens in source files, retaining historic assertions and distinct origins."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "resolution.tsv"))
    _write(
        nodes,
        ["id", "category", "name", "provided_by"],
        [
            {
                "id": "GO:0004096",
                "category": "biolink:BiologicalProcess|biolink:MolecularActivity",
                "name": "wrong",
                "provided_by": "infores:rhea",
            },
            {"id": "GO:0003840", "category": "biolink:BiologicalProcess", "name": "", "provided_by": ""},
            {"id": "taxon:1", "category": "biolink:OrganismTaxon", "name": "Organism", "provided_by": "infores:rhea"},
        ],
    )
    edge_fields = [
        "subject",
        "predicate",
        "object",
        "relation",
        "primary_knowledge_source",
        "knowledge_level",
        "agent_type",
        "publications",
    ]
    _write(
        edges,
        edge_fields,
        [
            {
                "subject": "taxon:1",
                "predicate": "biolink:capable_of",
                "object": target,
                "relation": "RO:0002215",
                "primary_knowledge_source": "infores:rhea",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
                "publications": "PMID:1",
            }
            for target in ("GO:9999002", "GO:9999003", "GO:0003840", "GO:0005575")
        ],
    )
    normalize_go_bundle([nodes], [edges], authority, report)
    actual = {row["id"]: row for row in _read(nodes)}
    assert actual["GO:0004096"]["category"] == "biolink:MolecularActivity"
    assert actual["GO:0004096"]["name"] == "catalase activity"
    assert actual["GO:0003840"]["deprecated"] == "true"
    assert actual["GO:0005575"]["category"] == "biolink:CellularComponent"
    rows = _read(edges)
    assert len(rows) == 4
    assert {row["original_object"] for row in rows if row["object"] == "GO:0004096"} == {"GO:9999002", "GO:9999003"}
    assert all(row["publications"] == "PMID:1" and row["primary_knowledge_source"] == "infores:rhea" for row in rows)
    before = nodes.read_bytes(), edges.read_bytes()
    normalize_go_bundle([nodes], [edges], authority, report)
    assert (nodes.read_bytes(), edges.read_bytes()) == before


def test_bundle_unknown_reference_leaves_both_files_unchanged(tmp_path, authority):
    """All target resolution succeeds before any source file is replaced."""
    nodes, edges = tmp_path / "nodes.tsv", tmp_path / "edges.tsv"
    _write(
        nodes,
        ["id", "name", "category"],
        [{"id": "GO:0004096", "name": "wrong", "category": "biolink:BiologicalProcess"}],
    )
    _write(
        edges,
        ["subject", "predicate", "object", "relation"],
        [{"subject": "GO:0004096", "predicate": "biolink:related_to", "object": "GO:9999999", "relation": "RO:1"}],
    )
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(GoReferenceError):
        normalize_go_bundle([nodes], [edges], authority, tmp_path / "report.tsv")
    assert (nodes.read_bytes(), edges.read_bytes()) == before


def test_deprecated_alias_stub_agrees_with_explicit_alternate_identity(statements):
    """Real GO alternate IDs can also be unlabeled deprecated redirect classes."""
    statements.extend(
        [
            ("GO:9999001", "owl:deprecated", None, "true"),
            ("GO:9999001", "IAO:0100001", "GO:0004096", None),
        ]
    )
    assert GoAuthority.from_statements(statements).resolve("GO:9999001").canonical_id == "GO:0004096"
    statements[-1] = ("GO:9999001", "IAO:0100001", "GO:0008152", None)
    with pytest.raises(ValueError, match="alternative identity"):
        GoAuthority.from_statements(statements)


def test_bundle_preserves_literal_kgx_values_and_existing_originals(tmp_path, authority):
    """KGX literal quotes and preexisting original identifiers are observation evidence."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "report.tsv"))
    _write(
        nodes, ["id", "name", "category"], [{"id": "taxon:1", "name": "Organism", "category": "biolink:OrganismTaxon"}]
    )
    original = {
        "subject": "taxon:1",
        "predicate": "biolink:capable_of",
        "object": "GO:9999002",
        "relation": "RO:0002215",
        "value": '"quoted"',
        "value_encoding": "backslash",
        "original_object": "GO:9999003",
    }
    with edges.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(original),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            quotechar=None,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(original)
    normalize_go_bundle([nodes], [edges], authority, report)
    with edges.open(newline="") as handle:
        result = next(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert result["value"] == '"quoted"'
    assert result["value_encoding"] == "backslash"
    assert result["original_object"] == "GO:9999003"
    assert result["object"] == "GO:0004096"
    assert any('"object": "GO:9999002"' in row["original_record_json"] for row in _read(report))


def test_empty_go_bundle_does_not_resolve_or_leave_stale_report(tmp_path):
    """A source without GO remains literal and clears a previous resolution report."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "report.tsv"))
    _write(nodes, ["id", "name"], [{"id": "taxon:1", "name": "Organism"}])
    _write(
        edges,
        ["subject", "predicate", "object", "relation"],
        [{"subject": "taxon:1", "predicate": "biolink:related_to", "object": "taxon:1", "relation": "RO:1"}],
    )
    report.write_text("old report\n")
    before = nodes.read_bytes(), edges.read_bytes()
    assert normalize_go_bundle([nodes], [edges], None, report) == {}
    assert (nodes.read_bytes(), edges.read_bytes()) == before
    assert _read(report) == []


def test_multistage_go_history_and_audit_remain_distinct(tmp_path, authority):
    """A later exact replacement preserves incoming contexts and every earlier audited source row."""
    from kg_microbe.merge_utils.kgx_source import assertion_key

    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "report.tsv"))
    for source, destination in (("evidence_nodes.tsv", nodes), ("evidence_edges.tsv", edges)):
        shutil.copyfile(FIXTURE.parent / source, destination)
    normalize_go_bundle([nodes], [edges], authority, report)
    first_audit = {row["original_record_json"] for row in _read(report) if row["original_record_json"]}
    first_report = report.read_bytes()
    assert normalize_go_bundle([nodes], [edges], authority, report) == {"already_normalized": 1}
    assert report.read_bytes() == first_report

    terms = dict(authority.records)
    terms["GO:0004096"] = replace(terms["GO:0004096"], deprecated=True, replaced_by=("GO:0008152",))
    later_authority = GoAuthority(terms, authority.authority_path, "b" * 64)
    normalize_go_bundle([nodes], [edges], later_authority, report)
    with edges.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert {row["object"] for row in rows} == {"GO:0008152"}
    assert {row["original_object"] for row in rows} == {"GO:9999001"}
    assert len({assertion_key(row) for row in rows}) == 2
    assert all(len(json.loads(row["go_reference_context"])) == 2 for row in rows)
    assert first_audit <= {row["original_record_json"] for row in _read(report) if row["original_record_json"]}
    final_bytes = nodes.read_bytes(), edges.read_bytes(), report.read_bytes()
    normalize_go_bundle([nodes], [edges], later_authority, report)
    assert (nodes.read_bytes(), edges.read_bytes(), report.read_bytes()) == final_bytes


def test_replaced_source_bundle_does_not_inherit_stale_go_audit(tmp_path, authority):
    """Reusing filenames for a fresh producer result must not falsely attribute its predecessor's audit."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "report.tsv"))
    for source, destination in (("evidence_nodes.tsv", nodes), ("evidence_edges.tsv", edges)):
        shutil.copyfile(FIXTURE.parent / source, destination)
    normalize_go_bundle([nodes], [edges], authority, report)
    assert "GO:9999002" in report.read_text()
    _write(
        nodes,
        ["id", "name", "category"],
        [{"id": "GO:0005575", "name": "cellular component", "category": "biolink:CellularComponent"}],
    )
    _write(edges, ["subject", "predicate", "object", "relation"], [])
    normalize_go_bundle([nodes], [edges], authority, report)
    assert "GO:9999002" not in report.read_text()


def test_go_loader_fails_loudly_without_caching_bad_authority(tmp_path, monkeypatch, statements):
    """Malformed authority is fatal, and repairing it allows a clean subsequent read."""
    import kg_microbe.utils.go_authority as module
    from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

    monkeypatch.setattr(module, "_prepare_go_database", lambda raw_dir: raw_dir / "go.db")
    path = tmp_path / "go.db"
    path.write_text("not sqlite")
    with pytest.raises(OntologyDbUnavailableError):
        load_go_authority(tmp_path)
    path.unlink()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)
    assert load_go_authority(tmp_path).resolve("GO:0004096").category == "biolink:MolecularActivity"


def test_prepared_cache_does_not_reinitialize_authority_per_term(tmp_path, monkeypatch, statements):
    """Repeated lookups avoid database preparation; changing the selected source invalidates it."""
    import kg_microbe.utils.go_authority as module

    calls = []

    def prepare(raw_dir):
        """Record each explicit parent preparation without invoking infrastructure."""
        calls.append(raw_dir)
        return raw_dir / "go.db"

    monkeypatch.setattr(module, "_prepare_go_database", prepare)
    with sqlite3.connect(tmp_path / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.executemany("INSERT INTO statements VALUES(?,?,?,?)", statements)
    first = load_go_authority(tmp_path)
    assert load_go_authority(tmp_path) is first
    assert len(calls) == 1
    (tmp_path / "go.owl").write_text("new selected input")
    second = load_go_authority(tmp_path)
    assert second.source_paths == (str(tmp_path / "go.owl"),)
    assert len(calls) == 2
