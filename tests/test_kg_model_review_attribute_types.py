"""MicrobeDecoder's focused node-slot review exposes its profile exception (#1222)."""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    ATTRIBUTE_CATEGORY,
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/resources/microbedecoder"
TARGET = "METPO:1000698"
ATTRIBUTE_ID = "kgmicrobe.source_attribute:test"


def _node(value=TARGET, category=ATTRIBUTE_CATEGORY):
    """Build a source node without importing a producer resolver."""
    return {
        ID_COLUMN: ATTRIBUTE_ID,
        CATEGORY_COLUMN: category,
        NAME_COLUMN: "raw value",
        HAS_ATTRIBUTE_TYPE_COLUMN: value,
    }


def _write(path, rows, header=None):
    """Write a deliberately selected TSV fixture under tmp_path."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header or list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def reviewer(tmp_path, monkeypatch):
    """Load the real skill with immutable offline Biolink and native METPO fixtures."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    skill = REPO / ".claude/skills/kg-model-review/kg_model_review.py"
    name = "kg_model_review_attribute_types_tests"
    spec = importlib.util.spec_from_file_location(name, skill)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    toolkit = Toolkit(schema=str(FIXTURES / "biolink-4.4.2-attributes.yaml"))
    monkeypatch.setattr(module, "_TOOLKIT", toolkit)
    monkeypatch.setattr(module, "_MODEL_DR_CACHE", {})
    ontology_dir = tmp_path / "ontologies"
    ontology_dir.mkdir()
    (ontology_dir / "metpo_nodes.tsv").write_bytes((FIXTURES / "metpo_nodes.tsv").read_bytes())
    monkeypatch.setattr(module, "ONTOLOGIES_DIR", ontology_dir)
    return module


def _errors(findings):
    """Return exact ERROR messages for assertions."""
    return [finding.message for finding in findings if finding.severity == "ERROR"]


def _native(reviewer):
    """Return the selected immutable declaration, allowing targeted temporary corruption."""
    with (reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv").open() as handle:
        return next(row for row in csv.DictReader(handle, delimiter="\t") if row[ID_COLUMN] == TARGET)


def test_valid_singleton_types_resolve_unique_native_class(reviewer):
    """Two attributes may share one uniquely declared native type."""
    other = dict(_node(), id="kgmicrobe.source_attribute:second")
    findings = reviewer.check_microbedecoder_attribute_types([_node(), other], True)
    assert not _errors(findings)
    assert "2 singleton" in findings[0].message
    assert "1 unique active native METPO" in findings[0].message
    assert "not full LinkML" in findings[0].message


@pytest.mark.parametrize("absent_column", [True, False])
def test_untyped_values_are_explicit_profile_exception_not_false_schema_claim(reviewer, absent_column):
    """Both historical missing-column and current blank values remain scientifically untyped."""
    row = _node("")
    if absent_column:
        row.pop(HAS_ATTRIBUTE_TYPE_COLUMN)
    (reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv").unlink()
    findings = reviewer.check_microbedecoder_attribute_types([row], True)
    assert len(findings) == 1 and findings[0].severity == "INFO"
    assert "1 untyped" in findings[0].message
    assert "required by full Biolink" in findings[0].message
    assert "house-profile exception" in findings[0].message
    assert "not full LinkML instance conformance" in findings[0].message


@pytest.mark.parametrize(
    "value",
    [
        TARGET + "|" + TARGET,
        " " + TARGET,
        TARGET + " ",
        " ",
        "METPO:2000001",
        "METPO:1",
        "GO:0008150",
        "https://w3id.org/metpo/1000698",
    ],
)
def test_malformed_or_out_of_scope_type_is_error(reviewer, value):
    """A scalar source-specific type must not accept whitespace, lists or another namespace."""
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node(value)], True))
    assert any("not one native METPO class CURIE" in error for error in errors)


@pytest.mark.parametrize(
    "category", ["biolink:OrganismTaxon", "biolink:Attribute|biolink:NamedThing", "", "biolink:OntologyClass"]
)
def test_present_type_requires_exact_attribute_owner(reviewer, category):
    """Ontology range compatibility cannot authorize typing an unrelated source node."""
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node(category=category)], True))
    assert any("not typed exactly Attribute" in error for error in errors)


def test_consumer_stub_cannot_replace_missing_native_declaration(reviewer):
    """The actual source stub is not an ontology authority for its own type."""
    target = "METPO:1999999"
    stub = {ID_COLUMN: target, CATEGORY_COLUMN: "biolink:OntologyClass", NAME_COLUMN: "invented"}
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node(target), stub], True))
    assert any("missing native METPO declaration" in error for error in errors)


@pytest.mark.parametrize(
    "category",
    ["biolink:PhenotypicQuality", "biolink:BiologicalProcess", "biolink:OntologyClass|biolink:Attribute", ""],
)
def test_wrong_native_category_is_error_not_retyping(reviewer, category):
    """The exact native slot-range category is required; the reviewer never edits declarations."""
    declaration = _native(reviewer)
    declaration[CATEGORY_COLUMN] = category
    path = reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv"
    _write(path, [declaration])
    before = path.read_bytes()
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    assert any("category differs" in error for error in errors)
    assert path.read_bytes() == before


@pytest.mark.parametrize("status", ["true", "TRUE", "1", "unknown", "false|true"])
def test_deprecated_or_invalid_native_status_is_error(reviewer, status):
    """Unknown status must not be silently interpreted as active."""
    declaration = _native(reviewer)
    declaration[DEPRECATED_COLUMN] = status
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration])
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    assert any("deprecated or has invalid status" in error for error in errors)


@pytest.mark.parametrize("status", ["", "false", "False", "0"])
def test_supported_native_active_statuses(reviewer, status):
    """Honor the existing producer's active-status dialect."""
    declaration = _native(reviewer)
    declaration[DEPRECATED_COLUMN] = status
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration])
    assert not _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))


@pytest.mark.parametrize("field", [ID_COLUMN, NAME_COLUMN, CATEGORY_COLUMN, DEPRECATED_COLUMN])
def test_missing_native_header_column_is_error(reviewer, field):
    """Incomplete infrastructure cannot be interpreted as successful validation."""
    declaration = _native(reviewer)
    declaration.pop(field)
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration])
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    assert any("header is malformed" in error for error in errors)


def test_duplicate_native_header_is_error(reviewer):
    """DictReader must not silently overwrite duplicate authority columns."""
    declaration = _native(reviewer)
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration], [*declaration, ID_COLUMN])
    assert any(
        "header is malformed" in error
        for error in _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    )


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_native_declaration_is_error(reviewer, conflicting):
    """Even identical duplicate selected declarations are not unique authority."""
    declaration = _native(reviewer)
    duplicate = dict(declaration)
    if conflicting:
        duplicate[CATEGORY_COLUMN] = "biolink:BiologicalProcess"
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration, duplicate])
    assert any(
        "duplicate native" in error for error in _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    )


def test_blank_native_name_is_error(reviewer):
    """A selected stub without a native label is not an authoritative class declaration."""
    declaration = _native(reviewer)
    declaration[NAME_COLUMN] = " "
    _write(reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv", [declaration])
    assert any(
        "has no name" in error for error in _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    )


@pytest.mark.parametrize("malformation", ["missing_file", "invalid_utf8", "truncated_row", "extra_cell"])
def test_unverifiable_native_source_is_error(reviewer, malformation):
    """Absent or malformed supporting evidence never produces a green typed-slot finding."""
    path = reviewer.ONTOLOGIES_DIR / "metpo_nodes.tsv"
    if malformation == "missing_file":
        path.unlink()
    elif malformation == "invalid_utf8":
        path.write_bytes(b"\xff")
    else:
        columns = [ID_COLUMN, NAME_COLUMN, CATEGORY_COLUMN, DEPRECATED_COLUMN]
        data = [TARGET, "positive", "biolink:OntologyClass"]
        if malformation == "extra_cell":
            data.extend(["", "unexpected"])
        path.write_text("\t".join(columns) + "\n" + "\t".join(data) + "\n")
    errors = _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    assert errors


def test_unknown_pinned_slot_range_is_error(reviewer, monkeypatch):
    """A missing schema contract must not trigger a guessed category fallback."""
    monkeypatch.setattr(reviewer, "_model_domain_range", lambda _: None)
    assert any(
        "pinned Attribute slot range" in error
        for error in _errors(reviewer.check_microbedecoder_attribute_types([_node()], True))
    )


@pytest.mark.parametrize("source, expect_error", [("microbedecoder", True), ("other_source", False)])
def test_source_review_hook_is_bounded_and_tallies_slot_errors(reviewer, tmp_path, source, expect_error):
    """The real entry point includes the targeted diagnostic without imposing it on other sources."""
    directory = tmp_path / source
    directory.mkdir()
    _write(directory / "nodes.tsv", [_node("METPO:1999999")])
    edge = {"subject": "lpsn:1", "predicate": "biolink:has_attribute", "object": ATTRIBUTE_ID, "relation": "SIO:000008"}
    _write(directory / "edges.tsv", [edge])
    prefixes = {"lpsn", "kgmicrobe.source_attribute", "SIO"}
    result = reviewer.review_transform(source, directory, 0, prefixes, {TARGET}, True)
    assert bool(result["errors"]) == expect_error
    assert any(finding.check == "AttributeType" for finding in result["nodes"]) == expect_error
