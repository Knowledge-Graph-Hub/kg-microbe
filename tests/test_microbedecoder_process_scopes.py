"""Keep local process definitions finite, source-specific and evidence-bound."""

import csv
import hashlib
import io
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from kg_microbe.transform_utils.microbedecoder.process_scopes import (
    DEFAULT_PROCESS_SCOPE_DEFINITIONS,
    ProcessScopeCuration,
)


def _rows():
    with DEFAULT_PROCESS_SCOPE_DEFINITIONS.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _stream(rows, fields=None):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return stream


def test_committed_forty_five_scopes_keep_complete_source_evidence():
    """Native-target holds still retain an interpretable, explicitly source-local meaning."""
    curation = ProcessScopeCuration()
    assert len(curation.rules) == 45
    for rule in curation.rules:
        assert curation.resolve(rule.source_column, rule.source_literal) == rule
        assert rule.source_column == "FAPROTAX_Type_of_metabolism"
        assert rule.scope_definition
        assert rule.source_version == "FAPROTAX_1.2.12"
        assert rule.archive_sha256 == "87e229e5201c23f8286aeb5f092f50a95bfe6281c7746d89a50c0aac11a5923c"
        assert rule.member_sha256 == "e5b9eead9f936316410c1a3d58aaa5fe4c2fafb8e859d250796ac70486c12963"
    union = curation.resolve("FAPROTAX_Type_of_metabolism", "nitrification")
    assert "only one component" in union.scope_definition
    sulfate = curation.resolve("FAPROTAX_Type_of_metabolism", "sulfate_respiration")
    assert "not sulfate incorporation" in sulfate.scope_definition


@pytest.mark.parametrize(
    "column,literal",
    [
        ("FAPROTAX2_Type_of_metabolism", "nitrification"),
        ("Bergey_Type_of_metabolism", "nitrification"),
        ("FAPROTAX_Type_of_metabolism", "Nitrification"),
        ("FAPROTAX_Type_of_metabolism", "nitrification "),
        ("FAPROTAX_Type_of_metabolism", "novel_nitrification"),
        ("FAPROTAX_Type_of_metabolism", "knallgas_bacteria"),
        ("FAPROTAX_Type_of_metabolism", "photoautotrophy"),
        ("FAPROTAX_Type_of_metabolism", "phototrophy"),
    ],
)
def test_unreviewed_spelling_source_or_other_policy_never_resolves(column, literal):
    """Do not infer scope definitions from substring similarity or another reviewed policy."""
    assert ProcessScopeCuration().resolve(column, literal) is None


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("source_column", "Bergey_Type_of_metabolism", "source column"),
        ("source_literal", "phototrophy", "Non-process"),
        ("source_literal", " nitrification", "malformed"),
        ("scope_definition", "", "malformed"),
        ("scope_definition", "bad\x01definition", "malformed"),
        ("source_version", "latest", "source version"),
        ("source_version", "FAPROTAX_1.2", "source version"),
        ("source_version", "FAPROTAX2_1.2.12", "source version"),
        ("source_version", "FAPROTAX_1.٢.12", "source version"),
        ("archive_sha256", "a" * 63, "SHA-256"),
        ("archive_sha256", "G" * 64, "SHA-256"),
        ("member_sha256", "a" * 65, "SHA-256"),
        ("member_sha256", "A" * 64, "SHA-256"),
        ("source_first_line", "0", "source line"),
        ("source_first_line", "01", "source line"),
        ("source_first_line", "-1", "source line"),
        ("source_first_line", "1.0", "source line"),
        ("source_first_line", "1٢", "source line"),
        ("evidence_uri", "http://example.org/evidence", "evidence URI"),
        ("evidence_uri", "file:///tmp/evidence", "evidence URI"),
        ("evidence_uri", "https://example.org|", "evidence URI"),
        ("evidence_uri", "https://user:password@example.org/evidence", "evidence URI"),
        ("evidence_uri", "https://example.org/bad path", "evidence URI"),
    ],
)
def test_invalid_or_incomplete_evidence_aborts(field, value, error):
    """No malformed row can silently disappear from the curation cohort."""
    row = _rows()[0]
    row[field] = value
    with pytest.raises(ValueError, match=error):
        ProcessScopeCuration(_stream([row]))


@pytest.mark.parametrize(
    "kind", ["duplicate", "conflict", "extra_field", "missing_field", "duplicate_header", "ragged", "empty"]
)
def test_structural_errors_abort(kind):
    """Exact table schema prevents native-target or predicate assertions entering this contract."""
    row = _rows()[0]
    rows, header = [row], list(row)
    if kind in {"duplicate", "conflict"}:
        rows.append(dict(row))
        if kind == "conflict":
            rows[-1]["scope_definition"] = "A conflicting definition."
        error = "Duplicate or conflicting"
    elif kind == "extra_field":
        row["target_curie"] = "GO:0019420"
        header.append("target_curie")
        error = "columns"
    elif kind == "missing_field":
        header.remove("member_sha256")
        row.pop("member_sha256")
        error = "columns"
    elif kind == "duplicate_header":
        header.append("source_literal")
        error = "columns"
    elif kind == "ragged":
        stream = _stream([row]).getvalue().splitlines()
        stream[-1] = stream[-1].rsplit("\t", 1)[0]
        with pytest.raises(ValueError, match="malformed"):
            ProcessScopeCuration(io.StringIO("\n".join(stream) + "\n"))
        return
    else:
        rows = []
        error = "No MicrobeDecoder"
    with pytest.raises(ValueError, match=error):
        ProcessScopeCuration(_stream(rows, header))


def test_stream_ownership_rule_immutability_and_fresh_load(tmp_path):
    """A later file mutation cannot reuse previously validated definitions."""
    stream = _stream(_rows())
    curation = ProcessScopeCuration(stream)
    assert not stream.closed
    with pytest.raises(FrozenInstanceError):
        curation.rules[0].scope_definition = "changed"
    path = tmp_path / "scopes.tsv"
    path.write_text(stream.getvalue(), encoding="utf-8")
    assert len(ProcessScopeCuration(path).rules) == 45
    path.write_text("id\ttarget_curie\na\tGO:0019420\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        ProcessScopeCuration(path)


def test_exact_source_identity_is_stable_and_definition_updates_do_not_rename_it():
    """Source/field/literal identity, not slug or mutable wording, determines the local ID."""
    rule = ProcessScopeCuration().resolve("FAPROTAX_Type_of_metabolism", "nitrification")
    expected = hashlib.sha256(
        json.dumps(
            ["microbedecoder", "FAPROTAX_Type_of_metabolism", "nitrification"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8", errors="surrogateescape")
    ).hexdigest()
    assert rule.curie == f"kgmicrobe.pathway:microbedecoder_faprotax_type_of_metabolism_{expected}"
    assert replace(rule, scope_definition="Reviewed wording updated.").curie == rule.curie
    assert replace(rule, source_literal="Nitrification").curie != rule.curie
    assert replace(rule, source_column="Bergey_Type_of_metabolism").curie != rule.curie
    assert replace(rule, source_literal="a-b").curie != replace(rule, source_literal="a b").curie


def test_source_description_carries_full_review_context_without_ontology_identity():
    """Descriptions remain scientifically qualified and independently reproducible."""
    rule = ProcessScopeCuration().resolve("FAPROTAX_Type_of_metabolism", "sulfate_respiration")
    for value in (
        rule.source_column,
        rule.source_literal,
        rule.scope_definition,
        rule.evidence_uri,
        rule.source_version,
        rule.archive_sha256,
        rule.member_sha256,
        rule.source_first_line,
    ):
        assert value in rule.description
    assert "not an ontology identity mapping" in rule.description
    assert "not establish the generating version" in rule.description
    assert "independent confirmation" in rule.description
