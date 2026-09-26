"""Canonical source schema and audited provenance migration precede merge."""

import csv
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

FIXTURE = Path(__file__).parent / "resources" / "source_contract_legacy.json"


def _producer(tmp_path, row, header=None, *, quoting=csv.QUOTE_NONE, newline="\n"):
    """Write one isolated producer bundle without ontology/network dependencies."""
    raw = tmp_path / "raw"
    raw.mkdir()
    producer = Transform("fixture", raw, tmp_path / "transformed")
    producer.TSV_QUOTING = quoting
    producer.output_node_file.write_text(
        "id\tname\tcategory\nfixture:1\tOne\tbiolink:NamedThing\nfixture:2\tTwo\tbiolink:NamedThing\n"
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter="\t",
        quoting=quoting,
        quotechar=None if quoting == csv.QUOTE_NONE else '"',
        lineterminator=newline,
    )
    writer.writerow(header or list(row))
    writer.writerow(list(row.values()) if isinstance(row, dict) else row)
    producer.output_edge_file.write_bytes(buffer.getvalue().encode())
    return producer


def _edge(**extras):
    """Provide the minimum assertion identity and explicit provider."""
    return dict(
        subject="fixture:1",
        predicate="biolink:related_to",
        object="fixture:2",
        relation="skos:related",
        primary_knowledge_source="infores:test",
        **extras,
    )


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text()), ids=lambda case: case["name"])
def test_source_finalization_audits_legacy_provider_and_evidence(tmp_path, case):
    """Compatibility migration retains the complete original provider/evidence pairing."""
    row = _edge(publications="PMID:7", custom_context='literal "quote" | scalar')
    row.update(case["input"])
    producer = _producer(tmp_path, row)
    producer.finalize(fresh_run=True)
    result = next(graph_rows(producer.output_edge_file))
    assert result["primary_knowledge_source"] == case["provider"]
    assert result["publications"] == case["publications"]
    assert "knowledge_source" not in result
    assert result["custom_context"] == row["custom_context"]
    audits = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    edge_audit = next(audit for audit in audits if audit["file"] == "edges.tsv")
    assert json.loads(edge_audit["original_row_json"]) == row
    assert json.loads(edge_audit["normalized_row_json"]) == result


def test_source_finalization_emits_canonical_required_schema_and_lf(tmp_path):
    """Header projection preserves literal text/extensions and never relies on merge cleanup."""
    from kg_microbe.utils.graph_schema import CANONICAL_EDGE_HEADER, canonical_header, validate_canonical_tsv

    row = _edge(z_extra='"literal"', meta="meaningful source metadata", a_extra="a")
    row["id"] = "assertion:original"
    producer = _producer(tmp_path, row, newline="\r\n")
    producer.finalize(fresh_run=True)
    output = next(graph_rows(producer.output_edge_file))
    assert list(output)[:7] == CANONICAL_EDGE_HEADER
    assert list(output) == canonical_header(list(output), False)
    assert output["source_assertion_id"] == "assertion:original"
    assert output["meta"] == row["meta"]
    assert output["z_extra"] == row["z_extra"]
    assert "id" not in output
    assert b"\r" not in producer.output_edge_file.read_bytes()
    assert validate_canonical_tsv(producer.output_edge_file, is_node=False) == 1
    assert validate_canonical_tsv(producer.output_node_file, is_node=True) == 2


@pytest.mark.parametrize(
    "updates",
    [
        {"primary_knowledge_source": "infores:a|infores:b"},
        {"primary_knowledge_source": ""},
        {"knowledge_source": "infores:other"},
        {"primary_knowledge_source": "infores:test", "knowledge_source": "bacdive:12"},
        {"id": "one", "source_assertion_id": "two"},
        {"key": "unexplained transport key"},
    ],
)
def test_source_contract_rejects_ambiguous_or_missing_evidence_without_publication(tmp_path, updates):
    """Failed migration cannot overwrite producer evidence or certify a finalized bundle."""
    row = _edge()
    row.update(updates)
    producer = _producer(tmp_path, row)
    original = producer.output_edge_file.read_bytes()
    with pytest.raises(SourceFinalizationRequired):
        producer.finalize(fresh_run=True)
    assert producer.output_edge_file.read_bytes() == original
    assert not (producer.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("value", ["bacdive", "bacdive:12", "['infores:bacdive']", "infores:a|infores:b", ""])
def test_merge_provenance_validator_cannot_migrate_provider(value):
    """Merge validation rejects legacy semantics instead of repairing source attribution."""
    from kg_microbe.utils.provenance import validate_primary_source_and_publications

    with pytest.raises(ValueError):
        validate_primary_source_and_publications(value, "PMID:7")


def test_merge_provenance_validator_allows_only_representation_roundtrip():
    """Already canonical provider and evidence survive KGX singleton/list representations."""
    from kg_microbe.utils.provenance import validate_primary_source_and_publications

    expected = ("infores:test", ["PMID:7", "https://example.org/record"])
    assert validate_primary_source_and_publications(*expected) == expected
    assert validate_primary_source_and_publications([expected[0]], "|".join(expected[1])) == expected
    with pytest.raises(ValueError):
        validate_primary_source_and_publications("infores:test", "PMID:7||PMID:8")


@pytest.mark.parametrize("duplicate", ["infores:test", "infores:other"])
def test_duplicate_provider_columns_are_coalesced_only_without_conflict(tmp_path, duplicate):
    """Original positional cells are retained when identical header names are coalesced."""
    row = _edge()
    producer = _producer(tmp_path, [*row.values(), duplicate], [*row, "primary_knowledge_source"])
    if duplicate != row["primary_knowledge_source"]:
        with pytest.raises(SourceFinalizationRequired, match="Conflicting duplicate"):
            producer.finalize(fresh_run=True)
        return
    producer.finalize(fresh_run=True)
    assert next(graph_rows(producer.output_edge_file))["primary_knowledge_source"] == duplicate
    audits = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    evidence = json.loads(next(item for item in audits if item["file"] == "edges.tsv")["original_row_json"])
    assert evidence["original_header"] == [*row, "primary_knowledge_source"]
    assert evidence["original_values"] == [*row.values(), duplicate]


@pytest.mark.parametrize("suffix", ["\textra", "", "\rbroken"])
def test_streamed_schema_validation_rejects_malformed_tsv(tmp_path, suffix):
    """Canonical output validation rejects wrong widths and embedded transport controls."""
    from kg_microbe.utils.graph_schema import validate_canonical_tsv

    producer = _producer(tmp_path, _edge())
    producer.finalize(fresh_run=True)
    path = producer.output_edge_file
    lines = path.read_text().splitlines()
    row = lines[1] + suffix if suffix else lines[1].rsplit("\t", 1)[0]
    path.write_bytes((lines[0] + "\n" + row + "\n").encode())
    with pytest.raises(ValueError):
        validate_canonical_tsv(path, is_node=False)


@pytest.mark.parametrize("column", ["primary_knowledge_source", "knowledge_source", "publications"])
def test_provenance_tokenization_cannot_erase_source_controls(tmp_path, column):
    """Legacy migration must not turn malformed source evidence into valid-looking metadata."""
    row = _edge()
    row[column] = "infores:test\n"
    producer = _producer(tmp_path, row, quoting=csv.QUOTE_MINIMAL)
    before = producer.output_edge_file.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="unencoded control"):
        producer.finalize(fresh_run=True)
    assert producer.output_edge_file.read_bytes() == before


def test_changed_contract_requires_new_producer_run_not_dialect_reparse(tmp_path):
    """An old finalized literal TSV cannot be reinterpreted as a legacy quoted producer TSV."""
    producer = _producer(tmp_path, _edge(custom='"literal"'))
    producer.finalize(fresh_run=True)
    path = producer.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    report["version"] = 1
    path.write_text(json.dumps(report))
    before = producer.output_edge_file.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="contract changed"):
        producer.finalize()
    assert producer.output_edge_file.read_bytes() == before


@pytest.mark.parametrize("location", ["name", "custom", "primary_knowledge_source", "publications", "header"])
def test_source_contract_refuses_nul_before_publication(tmp_path, location):
    """A finalized producer must never certify NUL bytes that its canonical serializer rejects."""
    producer = _producer(tmp_path, _edge())
    if location == "name":
        producer.output_node_file.write_bytes(producer.output_node_file.read_bytes().replace(b"One", b"One\x00two"))
    elif location == "header":
        producer.output_edge_file.write_bytes(
            producer.output_edge_file.read_bytes().replace(b"relation", b"rel\x00ation", 1)
        )
    else:
        header, row = producer.output_edge_file.read_text().splitlines()
        if location == "primary_knowledge_source":
            row += "\x00hidden"
        else:
            header += "\t" + location
            row += "\tPMID:1\x00hidden"
        producer.output_edge_file.write_bytes((header + "\n" + row + "\n").encode())
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    with pytest.raises(ValueError, match="control|column|NUL"):
        producer.finalize(fresh_run=True)
    assert before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())
    assert not (producer.output_dir / "source_finalization.json").exists()


def test_merge_schema_contract_rejects_nul_without_editing(tmp_path):
    """Validation-only consumers independently refuse a corrupted otherwise canonical pair."""
    from kg_microbe.utils.graph_schema import validate_canonical_tsv

    producer = _producer(tmp_path, _edge(custom="plain"))
    producer.finalize(fresh_run=True)
    path = producer.output_edge_file
    path.write_bytes(path.read_bytes().replace(b"plain", b"plain\x00hidden"))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="NUL"):
        validate_canonical_tsv(path, is_node=False)
    assert path.read_bytes() == before
