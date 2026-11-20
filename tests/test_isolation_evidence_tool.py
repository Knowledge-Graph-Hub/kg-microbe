"""Preserve literal isolation evidence without site identity, dropped rows or unsafe publication."""

import csv
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.adhoc import reshape_isolation_evidence as tool

FIXTURE = Path(__file__).parent / "resources/isolation_evidence/source.csv"
SCHEMA = Path(__file__).parents[1] / "schema/bacdive_isolation_evidence.schema.json"


def read_output(path):
    """Read and validate only tiny test output using the committed local schema."""
    document = json.loads(path.read_text())
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(document)
    return document


def write_csv(path, headers, rows):
    """Write deliberately varied local CSV fixtures with real quoting rules."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def test_exact_source_occurrences_conflicts_paths_and_no_grounding(tmp_path):
    """Retain duplicates, conflicting scalar values, NA literals and all native category paths."""
    output = tmp_path / "evidence.json"
    summary = tool.export_evidence(FIXTURE, output)
    result = read_output(output)
    assert summary == {
        "source_records": 4,
        "distinct_bacdive_ids": 2,
        "duplicate_rows": 1,
        "conflicting_bacdive_ids": 1,
    }
    assert result["summary"] == summary
    assert result["source"]["sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    with FIXTURE.open(newline="") as stream:
        source = list(csv.DictReader(stream))
    rows = sorted(
        (row for record in result["records"] for row in record["occurrences"]), key=lambda row: row["source_record"]
    )
    assert [row["raw_fields"] for row in rows] == source
    assert [row["source_record"] for row in rows] == [1, 2, 3, 4]
    first, second = result["records"]
    assert first["bacdive_id"] == "101"
    assert first["values"]["species"] == ["Bacillus example", "Bacillus other"]
    assert first["conflicting_fields"] == ["species"]
    assert first["values"]["culture_collection_number"] == ["DSM 1, ATCC 2"]
    assert first["values"]["country"] == ["NA"]
    assert first["values"]["isolation_source"] == ["NA", "soil, wet", "description only"]
    assert first["occurrences"][0]["raw_fields"] == first["occurrences"][1]["raw_fields"]
    assert len(first["category_paths"]) == 2
    assert second["values"]["species"] == ['Case "quoted"']
    assert second["values"]["country"] == ["N/A"]
    assert second["values"]["isolation_source"] == ["first line\nsecond line"]
    assert (second["occurrences"][0]["line_start"], second["occurrences"][0]["line_end"]) == (3, 4)
    assert second["category_paths"][0]["category_3"] == "#mouth"
    # The output schema permits neither predicates/ontology mappings nor a
    # category decision: these identical lexical labels remain source strings.
    assert "ENVO:" not in output.read_text() and "biolink:" not in output.read_text()
    assert not list(tmp_path.glob(".isolation-evidence-*"))


def test_reordered_canonical_columns_and_same_row_token_order(tmp_path):
    """Match explicit names rather than positions, retaining token order and raw whitespace."""
    input_path, output = tmp_path / "input.csv", tmp_path / "output.json"
    names = list(reversed(tool.HEADERS))
    values = {key: "" for key in tool.HEADERS}
    values.update(id="900", species=" NA ", isolation_source=" z ### a ### z ", category_3="#unknown")
    write_csv(input_path, names, [[values[name] for name in names]])
    tool.export_evidence(input_path, output)
    document = read_output(output)
    record = document["records"][0]
    assert document["source"]["headers"] == names
    assert record["values"]["isolation_source"] == ["z", "a"]
    assert record["values"]["species"] == [" NA "]
    assert record["occurrences"][0]["raw_fields"] == values
    assert record["category_paths"] == [{"category_1": "", "category_2": "", "category_3": "#unknown"}]


def test_conflicts_and_identical_labels_do_not_collapse_distinct_source_contexts(tmp_path):
    """Retain both scalar conflicts and different paths sharing one terminal label."""
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    write_csv(
        source,
        list(tool.HEADERS),
        [
            ["42", "Species A", "DSM 1", "mouth", "", "", "#Host", "#Human", "#mouth"],
            ["42", "Species B", "DSM 2", "mouth", "", "", "#Environment", "#Cave", "#mouth"],
        ],
    )
    tool.export_evidence(source, output)
    record = read_output(output)["records"][0]
    assert record["conflicting_fields"] == ["species", "culture_collection_number"]
    assert record["values"]["culture_collection_number"] == ["DSM 1", "DSM 2"]
    assert record["values"]["isolation_source"] == ["mouth"]
    assert len(record["occurrences"]) == len(record["category_paths"]) == 2
    assert record["duplicate_rows"] == 0


@pytest.mark.parametrize("damage", ["unknown", "duplicate", "missing", "alias_duplicate"])
def test_bad_headers_fail_without_publication(tmp_path, damage):
    """Reject unknown, duplicate and incomplete named columns before positional interpretation."""
    headers = list(tool.HEADERS.values())
    if damage == "unknown":
        headers[-1] = "New unexplained field"
    elif damage == "duplicate":
        headers[-1] = headers[0]
    elif damage == "missing":
        headers.pop()
    else:
        headers[-1] = "id"
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    write_csv(source, headers, [])
    with pytest.raises(ValueError, match="header|column"):
        tool.export_evidence(source, output)
    assert not output.exists() and not list(tmp_path.glob(".isolation-evidence-*"))


@pytest.mark.parametrize("identifier", ["", "0", "01", "1.0", " 1", "-1", "NA", "one"])
def test_missing_or_ambiguous_record_identity_is_not_repaired(tmp_path, identifier):
    """Do not invent record IDs or silently drop malformed groups."""
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    write_csv(source, list(tool.HEADERS), [[identifier] + [""] * 8])
    with pytest.raises(ValueError, match="BacDive ID"):
        tool.export_evidence(source, output)
    assert not output.exists()


@pytest.mark.parametrize("suffix", [b"", b"\n1,too,few\n", b'\n1,"unterminated'])
def test_empty_and_truncated_inputs_cannot_publish(tmp_path, suffix):
    """Fail on header-only inputs or malformed rows rather than publishing partial success."""
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    data = b",".join(name.encode() for name in tool.HEADERS) + suffix
    source.write_bytes(data)
    with pytest.raises((ValueError, csv.Error)):
        tool.export_evidence(source, output)
    assert not output.exists() and not list(tmp_path.glob(".isolation-evidence-*"))


@pytest.mark.parametrize("suffix", [b"1,too,few\n", b'1,"unterminated', b"\xff\n"])
def test_late_malformed_or_non_utf8_records_do_not_publish_prior_valid_rows(tmp_path, suffix):
    """Abort the whole artifact even after valid occurrences have entered private grouping."""
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    source.write_bytes(FIXTURE.read_bytes() + suffix)
    with pytest.raises((ValueError, csv.Error, UnicodeError)):
        tool.export_evidence(source, output)
    assert not output.exists() and not list(tmp_path.glob(".isolation-evidence-*"))


def test_input_mutation_after_parse_refuses_publication(tmp_path, monkeypatch):
    """Bind results to the parsed bytes, not a freshly recomputed claim about changed data."""
    source, output = tmp_path / "input.csv", tmp_path / "output.json"
    source.write_bytes(FIXTURE.read_bytes())
    original = tool._write_document

    def mutate_after_write(*args):
        """Replace the original input after the private snapshot has been parsed."""
        summary = original(*args)
        source.write_bytes(source.read_bytes() + b"\n")
        return summary

    monkeypatch.setattr(tool, "_write_document", mutate_after_write)
    with pytest.raises(ValueError, match="Input bytes changed"):
        tool.export_evidence(source, output)
    assert not output.exists() and not list(tmp_path.glob(".isolation-evidence-*"))


@pytest.mark.parametrize("kind", ["file", "directory", "broken_symlink"])
def test_existing_output_is_preserved(tmp_path, kind):
    """Refuse every existing destination, including an empty directory or dangling link."""
    output = tmp_path / "output.json"
    if kind == "file":
        output.write_bytes(b"user evidence")
    elif kind == "directory":
        output.mkdir()
    else:
        output.symlink_to(tmp_path / "missing")
    with pytest.raises(FileExistsError):
        tool.export_evidence(FIXTURE, output)
    if kind == "file":
        assert output.read_bytes() == b"user evidence"
    elif kind == "directory":
        assert output.is_dir() and not list(output.iterdir())
    else:
        assert output.is_symlink()


def test_concurrent_publication_cannot_clobber_another_result(tmp_path, monkeypatch):
    """The final publication primitive, not merely a prior existence check, is exclusive."""
    output = tmp_path / "output.json"
    original = tool.os.link

    def race(source, destination):
        """Emulate another publisher winning after this process completed its checks."""
        Path(destination).write_bytes(b"other publisher")
        return original(source, destination)

    monkeypatch.setattr(tool.os, "link", race)
    with pytest.raises(FileExistsError):
        tool.export_evidence(FIXTURE, output)
    assert output.read_bytes() == b"other publisher"
    assert not list(tmp_path.glob(".isolation-evidence-*"))


@pytest.mark.parametrize("error", [RuntimeError("write failed"), KeyboardInterrupt()])
def test_failed_or_interrupted_write_is_not_a_result(tmp_path, monkeypatch, error):
    """Preserve failure semantics even when an interrupted writer created private partial bytes."""
    output = tmp_path / "output.json"

    def fail(database, stream, source, count):
        """Stop during a staged write; this must not create a public artifact."""
        stream.write("partial")
        raise error

    monkeypatch.setattr(tool, "_write_document", fail)
    with pytest.raises(type(error)):
        tool.export_evidence(FIXTURE, output)
    assert not output.exists() and not list(tmp_path.glob(".isolation-evidence-*"))


def test_rerun_to_new_path_is_deterministic_and_help_is_offline(tmp_path, capsys):
    """Keep repeated exports stable without overwriting their predecessors or opening services."""
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    tool.main(["--input", str(FIXTURE), "--output", str(first)])
    tool.main(["--input", str(FIXTURE), "--output", str(second)])
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(SystemExit) as stopped:
        tool.main(["--help"])
    assert stopped.value.code == 0
    assert "--input" in capsys.readouterr().out
