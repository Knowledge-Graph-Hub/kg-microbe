"""Test immutable, bounded RDF record serialization extracted from make-nt."""

import hashlib
import json
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal, URIRef

from scripts.adhoc import export_kgx_records_nt as exporter

FIXTURE = Path(__file__).parent / "resources" / "kgx_records_nt"


def run_export(tmp_path, *, nodes=None, edges=None, prefixes=None, output=None):
    """Export immutable fixtures with selectively supplied negative-test inputs."""
    output = output or tmp_path / "graph.nt"
    summary = exporter.export_records(
        nodes or FIXTURE / "nodes.tsv",
        edges or FIXTURE / "edges.tsv",
        prefixes or FIXTURE / "prefixes.json",
        output,
    )
    return output, summary


def test_round_trip_and_no_unconditional_assertion(tmp_path):
    """Preserve negation, every cell and distinct evidence without asserting the triple."""
    before = {path: path.read_bytes() for path in FIXTURE.iterdir()}
    output, summary = run_export(tmp_path)
    graph = Graph().parse(output, format="nt")
    records = list(graph.subjects(RDF.type, RDF.Statement))
    assert len(records) == 2
    assert summary["nodes"]["rows"] == summary["edges"]["rows"] == 2
    assert summary["asserts_edge_triples"] is False
    assert (
        URIRef("http://rdf.rhea-db.org/10000"),
        URIRef("http://rdf.rhea-db.org/substrates"),
        URIRef("http://purl.obolibrary.org/obo/CHEBI_15377"),
    ) not in graph
    assert set(graph.objects(None, URIRef(exporter.FIELD + "negated"))) == {Literal("true"), Literal("false")}
    for kind, filename in (("node", "nodes.tsv"), ("edge", "edges.tsv")):
        lines = before[FIXTURE / filename].decode().splitlines()
        header = lines[0].split("\t")
        for index, line in enumerate(lines[1:], 1):
            subject = URIRef(
                f"{exporter.RECORD}{kind}:{summary['prefix_map_sha256']}:"
                f"{summary[filename.split('.')[0]]['sha256']}:{index}"
            )
            assert [str(graph.value(subject, URIRef(exporter.FIELD + field))) for field in header] == line.split("\t")
    assert before == {path: path.read_bytes() for path in FIXTURE.iterdir()}
    assert json.loads(output.read_text().splitlines()[-1][2:]) == summary


def test_reproducible_and_retains_duplicate_observations(tmp_path):
    """Byte-identical rows have separate coordinates, and repeated exports are deterministic."""
    edges = tmp_path / "edges.tsv"
    original = (FIXTURE / "edges.tsv").read_bytes().splitlines(keepends=True)
    edges.write_bytes(original[0] + original[1] + original[1])
    first, _ = run_export(tmp_path, edges=edges, output=tmp_path / "first.nt")
    second, _ = run_export(tmp_path, edges=edges, output=tmp_path / "second.nt")
    assert first.read_bytes() == second.read_bytes()
    assert len(list(Graph().parse(first, format="nt").subjects(RDF.type, RDF.Statement))) == 2


def test_prefix_map_revision_separates_interpretations(tmp_path):
    """Unioning exports must not give one RDF statement incompatible expanded endpoints."""
    revised = tmp_path / "prefixes.json"
    prefixes = json.loads((FIXTURE / "prefixes.json").read_text())
    prefixes["RHEA"] = "https://example.org/reviewed-rhea/"
    revised.write_text(json.dumps(prefixes))
    first, _ = run_export(tmp_path, output=tmp_path / "first.nt")
    second, _ = run_export(tmp_path, prefixes=revised, output=tmp_path / "second.nt")
    graph = Graph().parse(first, format="nt").parse(second, format="nt")
    statements = list(graph.subjects(RDF.type, RDF.Statement))
    assert len(statements) == 4
    assert all(len(list(graph.objects(statement, RDF.subject))) == 1 for statement in statements)


@pytest.mark.parametrize(
    "content",
    [
        b"id\tname\nunknown:x\tx\n",
        b"id\tid\na\tb\n",
        b"name\na\n",
        b"id\nRHEA:1",
        b"id\r\nRHEA:1\r\n",
        b"id\nRHEA:1\textra\n",
        b"id\n\n",
        b"id\nRHEA:a b\n",
        b"id\nRHEA:a\x00b\n",
        b"id\n\xff\n",
    ],
)
def test_invalid_input_never_published(tmp_path, content):
    """Refuse malformed identities/transport instead of rewriting or skipping rows."""
    nodes = tmp_path / "nodes.tsv"
    nodes.write_bytes(content)
    with pytest.raises(ValueError):
        run_export(tmp_path, nodes=nodes)
    assert not (tmp_path / "graph.nt").exists()
    assert not list(tmp_path.glob(".kgm-nt-*"))


@pytest.mark.parametrize("value", ["x:y", "http://x/a b", "http://x/a|b", "urn:x:", "urn::x", "http://x/%zz"])
def test_invalid_iri_not_silently_rewritten(value):
    """Never normalize lossy text or silently accept unregistered CURIEs."""
    with pytest.raises(ValueError):
        exporter.expand(value, {})


def test_literal_syntax_and_unicode_identity(tmp_path):
    """Escape only RDF syntax and preserve Unicode identifiers rather than English replacements."""
    value = '"slash\\\n\t\r\x01 α → 37°C'
    encoded = exporter.literal(value)
    graph = Graph().parse(data=f"<urn:test:s> <urn:test:p> {encoded} .\n", format="nt")
    assert str(graph.value(URIRef("urn:test:s"), URIRef("urn:test:p"))) == value
    assert exporter.expand("RHEA:α→β°C", {"RHEA": "http://rdf.rhea-db.org/"}) == "<http://rdf.rhea-db.org/α→β°C>"


@pytest.mark.parametrize(
    "content", ["[]", '{"RHEA":"http://x/","RHEA":"http://y/"}', '{"http":"http://x/"}', '{"RHEA":42}']
)
def test_prefix_map_must_be_explicit_unambiguous(tmp_path, content):
    """Ambiguous or malformed local contexts abort without publishing an artifact."""
    prefixes = tmp_path / "prefixes.json"
    prefixes.write_text(content)
    with pytest.raises(ValueError):
        run_export(tmp_path, prefixes=prefixes)
    assert not (tmp_path / "graph.nt").exists()


def test_no_clobber_existing_and_racing_destination(tmp_path, monkeypatch):
    """Atomic link publication cannot overwrite even a concurrently created destination."""
    output = tmp_path / "graph.nt"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        run_export(tmp_path)
    assert output.read_bytes() == b"keep"
    output.unlink()
    original = exporter.os.link

    def race(source, destination):
        """Create another publisher's file at the final commit boundary."""
        destination.write_bytes(b"racing writer")
        return original(source, destination)

    monkeypatch.setattr(exporter.os, "link", race)
    with pytest.raises(FileExistsError):
        run_export(tmp_path)
    assert output.read_bytes() == b"racing writer"
    assert not list(tmp_path.glob(".kgm-nt-*"))


def test_changed_input_fails_before_publication(tmp_path, monkeypatch):
    """Detect source mutation rather than attaching a stale input fingerprint."""
    nodes = tmp_path / "nodes.tsv"
    nodes.write_bytes((FIXTURE / "nodes.tsv").read_bytes())
    original = exporter.write_table

    def mutate_after_read(*args, **kwargs):
        """Change already consumed input to exercise the final fingerprint guard."""
        result = original(*args, **kwargs)
        if args[1] == "node":
            nodes.write_bytes(nodes.read_bytes() + b"CHEBI:1\tx\tx\tx\tx\n")
        return result

    monkeypatch.setattr(exporter, "write_table", mutate_after_read)
    with pytest.raises(ValueError, match="changed"):
        run_export(tmp_path, nodes=nodes)
    assert not (tmp_path / "graph.nt").exists()


def test_hash_reads_are_bounded(tmp_path, monkeypatch):
    """Large files are hashed incrementally and table input is consumed by line iteration."""
    source = tmp_path / "large.tsv"
    content = b"a" * (3 * 1024 * 1024)
    source.write_bytes(content)
    real_open = Path.open

    class BoundedReader:
        """Wrap only the hash input and reject unbounded reads."""

        def __init__(self, handle):
            """Retain the underlying test file handle."""
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def read(self, size=-1):
            """Reject whole-file reads and delegate bounded chunks."""
            assert 0 < size <= 1024 * 1024
            return self.handle.read(size)

    def guarded_open(path, *args, **kwargs):
        """Interpose on the fixture without affecting unrelated pytest files."""
        handle = real_open(path, *args, **kwargs)
        return BoundedReader(handle) if path == source else handle

    monkeypatch.setattr(Path, "open", guarded_open)
    assert exporter.fingerprint(source) == hashlib.sha256(content).hexdigest()
