"""Exercise unsupported mapping predicates through the real lookup consumer."""

import csv

import pytest
import yaml

from kg_microbe.utils import chemical_mapping_utils as cmu
from kg_microbe.utils.ingredient_scope import profile_metadata


def write_rows(path, rows, *, metadata=""):
    """Write a small SSSOM with the same field names as the unified artifact."""
    fields = [
        "subject_id",
        "subject_label",
        "predicate_id",
        "object_id",
        "object_label",
        "comment",
        "object_formula",
        "object_category",
    ]
    fields.extend(sorted({field for row in rows for field in row} - set(fields)))
    with path.open("w") as stream:
        stream.write(metadata)
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture(autouse=True)
def reset_loaded_state(monkeypatch):
    """Keep fixture lookups independent of the production mapping cache."""
    monkeypatch.setattr(cmu, "_LOADED", False)
    monkeypatch.setattr(cmu, "_CACHED_PATH", None)
    yield
    cmu._LOADED = False
    cmu._CACHED_PATH = None


@pytest.mark.parametrize(
    "predicate", ["example:unknown", "skos:relatedMatch", "skos:closeMatch", "oboInOwl:hasDbXref", ""]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_nonidentity_cannot_enter_any_lookup(tmp_path, predicate, reverse):
    """A nonidentity row cannot create a hidden name/formula/xref resolution."""
    rows = [
        {
            "subject_id": "source:unsupported",
            "predicate_id": predicate,
            "object_id": "CHEBI:999998",
            "object_label": "unsupported chemical",
            "object_formula": "UnsupportedFormula",
            "object_category": "biolink:ChemicalEntity",
        },
        {
            "subject_id": "source:approved",
            "predicate_id": "skos:exactMatch",
            "object_id": "CHEBI:999997",
            "object_label": "approved chemical",
        },
    ]
    cmu.load_unified_mappings(write_rows(tmp_path / "rows.tsv", list(reversed(rows)) if reverse else rows))
    assert cmu.find_chebi_by_name("unsupported chemical") is None
    assert cmu.find_chebi_by_formula("UnsupportedFormula") == []
    assert cmu.find_chebi_by_xref("source:unsupported") is None
    assert cmu.get_node_enrichment("CHEBI:999998")["xref"] == ""
    assert cmu.find_chebi_by_name("approved chemical") == "CHEBI:999997"
    assert cmu.find_chebi_by_xref("source:approved") == "CHEBI:999997"
    audit = cmu.get_mapping_load_audit()
    assert sum(audit["counts"].values()) == 2
    assert audit["diagnostics"][0]["subject_id"] == "source:unsupported"


def test_explicit_lexical_and_hydrate_routes_remain_separate(tmp_path):
    """Legacy lexical exceptions preserve names without asserting hydrate identity."""
    rows = [
        {
            "subject_id": "kgm.name:compound",
            "predicate_id": "skos:exactMatch",
            "object_id": "CHEBI:999997",
            "object_label": "approved chemical",
            "comment": "canonical_name",
        },
        {
            "subject_id": "kgm.name:synonym",
            "subject_label": "approved synonym",
            "predicate_id": "skos:closeMatch",
            "object_id": "CHEBI:999997",
            "comment": "synonym",
        },
        {
            "subject_id": "CHEBI:999997",
            "predicate_id": "skos:closeMatch",
            "object_id": "CHEBI:999996",
            "comment": "recipe_equivalent_hydrate",
        },
        {
            "subject_id": "kgm.name:unsupported",
            "subject_label": "unsupported synonym",
            "predicate_id": "example:unknown",
            "object_id": "CHEBI:999997",
            "comment": "synonym",
        },
    ]
    cmu.load_unified_mappings(write_rows(tmp_path / "rows.tsv", rows))
    assert cmu.find_chebi_by_name("approved synonym") == "CHEBI:999997"
    assert cmu.find_chebi_by_name("unsupported synonym") is None
    assert cmu.find_chebi_by_xref("CHEBI:999996") is None
    assert cmu.get_hydrate_equivalents("CHEBI:999997") == ["CHEBI:999996"]
    assert cmu.get_xrefs("CHEBI:999997") == []


def test_broader_relation_needs_independent_entity_declarations(tmp_path):
    """Retain broader alignment without using its attributes to create an identity."""
    row = {
        "subject_id": "source:preparation",
        "predicate_id": "skos:broadMatch",
        "object_id": "CHEBI:999997",
        "object_label": "parent-only label",
    }
    cmu.load_unified_mappings(write_rows(tmp_path / "rows.tsv", [row], metadata="# predicate_semantics: skos\n"))
    assert cmu.get_parents("source:preparation") == ["CHEBI:999997"]
    assert cmu.find_chebi_by_name("parent-only label") is None
    assert cmu.find_chebi_by_xref("source:preparation") is None


def test_failed_reload_does_not_cache_partial_indices(tmp_path):
    """Reject a malformed reload and rebuild after that same path is corrected."""
    path = write_rows(
        tmp_path / "rows.tsv",
        [{"subject_id": "source:approved", "predicate_id": "skos:exactMatch", "object_id": "CHEBI:999997"}],
    )
    cmu.load_unified_mappings(path)
    broken = tmp_path / "broken.tsv"
    broken.write_text("subject_id\tpredicate_id\tobject_id\nsource:broken\tskos:exactMatch\n")
    with pytest.raises(ValueError, match="Malformed SSSOM row 1"):
        cmu.load_unified_mappings(broken)
    assert not cmu._LOADED
    write_rows(
        broken,
        [{"subject_id": "source:fixed", "predicate_id": "skos:exactMatch", "object_id": "CHEBI:999996"}],
    )
    cmu.load_unified_mappings(broken)
    assert cmu.find_chebi_by_xref("source:fixed") == "CHEBI:999996"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, "CHEBI:999997"),
        ({"ext_identity_authorized": "false"}, None),
        ({"ext_object_scope": "mimscope:chemical_family"}, None),
        ({"ext_subject_scope": "mimscope:unknown", "ext_object_scope": "mimscope:unknown"}, None),
        ({"ext_scope_review_status": "WITHHOLD"}, None),
        ({"ext_scope_review_status": "UNREVIEWED"}, None),
        ({"ext_scope_evidence": ""}, None),
        ({"ext_scope_profile": "mimprofile:ingredient-scope/v2"}, None),
    ],
)
def test_profile_authorization_is_enforced_by_actual_lookup(tmp_path, overrides, expected):
    """Unsupported or conflicting scope cannot enter a legacy identity path."""
    metadata = profile_metadata({})
    row = {
        "subject_id": "source:scoped",
        "predicate_id": "skos:exactMatch",
        "object_id": "CHEBI:999997",
        "object_label": "scoped chemical",
        "ext_subject_scope": "mimscope:defined_substance",
        "ext_object_scope": "mimscope:defined_substance",
        "ext_subject_composition": "mimscope:single_component",
        "ext_object_composition": "mimscope:single_component",
        "ext_scope_review_status": "SUPPORTED",
        "ext_scope_evidence": "https://example.org/review#scope",
        "ext_identity_authorized": "true",
    }
    row.update(overrides)
    header = "".join("# " + line + "\n" for line in yaml.safe_dump(metadata).splitlines())
    cmu.load_unified_mappings(write_rows(tmp_path / "profile.tsv", [row], metadata=header))
    assert cmu.find_chebi_by_xref("source:scoped") == expected
    assert cmu.find_chebi_by_name("scoped chemical") == expected
    assert cmu.get_mapping_load_audit()["complete"]


def test_duplicate_profile_declaration_aborts_loading(tmp_path):
    """Do not accept a last-key-wins YAML profile or leave a usable partial cache."""
    path = write_rows(
        tmp_path / "profile.tsv",
        [],
        metadata="# ext_scope_profile: one\n# ext_scope_profile: two\n",
    )
    with pytest.raises(ValueError, match="Duplicate SSSOM metadata key"):
        cmu.load_unified_mappings(path)
    assert not cmu._LOADED


def test_metadata_marker_inside_quoted_value_is_not_discarded(tmp_path):
    """TSV quoting, not a per-line comment filter, determines row boundaries."""
    row = {
        "subject_id": "source:approved",
        "predicate_id": "skos:exactMatch",
        "object_id": "CHEBI:999997",
        "object_label": "approved chemical",
        "comment": "source text\n# retained text",
    }
    path = write_rows(tmp_path / "quoted.tsv", [row])
    assert list(cmu._iter_sssom_rows(path))[0]["comment"] == row["comment"]
    cmu.load_unified_mappings(path)
    assert cmu.find_chebi_by_xref("source:approved") == "CHEBI:999997"


@pytest.mark.parametrize(
    "subject,predicate,comment",
    [
        ("source:negative", "skos:exactMatch", ""),
        ("kgm.name:negative", "skos:exactMatch", "canonical_name"),
        ("kgm.name:negative", "skos:closeMatch", "synonym"),
        ("source:negative", "skos:broadMatch", ""),
        ("source:negative", "skos:narrowMatch", ""),
        ("CHEBI:999998", "skos:closeMatch", "recipe_equivalent_hydrate"),
    ],
)
def test_negation_never_becomes_a_positive_resolution_or_relation(tmp_path, subject, predicate, comment):
    """The predicate modifier is checked before every positive consumer route."""
    row = {
        "subject_id": subject,
        "subject_label": "negative alias",
        "predicate_id": predicate,
        "predicate_modifier": "Not",
        "object_id": "CHEBI:999997",
        "object_label": "negative chemical",
        "comment": comment,
    }
    cmu.load_unified_mappings(write_rows(tmp_path / "negative.tsv", [row]))
    assert cmu.find_chebi_by_xref(subject) is None
    assert cmu.find_chebi_by_name("negative alias") is None
    assert cmu.find_chebi_by_name("negative chemical") is None
    assert cmu.get_parents(subject) == []
    assert cmu.get_parents("CHEBI:999997") == []
    assert cmu.get_hydrate_equivalents(subject) == []
    assert cmu.get_mapping_load_audit()["diagnostics"][0]["reason"] == "unsupported_predicate_modifier"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("declaration", ["missing", "independent", "conflicting_broader"])
def test_broader_category_is_nonresolving_fallback(tmp_path, reverse, declaration):
    """Endpoint category survives without granting an identity to the mapping."""
    rows = [
        {
            "subject_id": "source:more-specific",
            "predicate_id": "skos:broadMatch",
            "object_id": "CHEBI:999998",
            "object_label": "nonresolving parent",
            "object_formula": "ParentFormula",
            "object_category": "biolink:ChemicalEntity",
        }
    ]
    if declaration != "missing":
        other = dict(rows[0], object_category="biolink:NamedThing")
        if declaration == "independent":
            other.update(
                subject_id="CHEBI:999998",
                predicate_id="skos:exactMatch",
                object_label="independent parent",
                object_formula="",
            )
        rows.append(other)
    cmu.load_unified_mappings(write_rows(tmp_path / "rows.tsv", rows[::-1] if reverse else rows))
    expected = {"missing": "biolink:ChemicalEntity", "independent": "biolink:NamedThing", "conflicting_broader": None}[
        declaration
    ]
    assert cmu.get_category("CHEBI:999998") == expected
    assert cmu.find_chebi_by_name("nonresolving parent") is None
    assert cmu.find_chebi_by_formula("ParentFormula") == []
    assert cmu.find_chebi_by_xref("source:more-specific") is None
