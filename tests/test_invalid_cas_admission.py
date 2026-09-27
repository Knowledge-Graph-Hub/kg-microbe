"""Invalid registry identifiers cannot establish identity or erase source occurrences."""

import json
from collections import Counter
from copy import deepcopy

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils import ingredient_identity as identity
from kg_microbe.utils.cas import invalid_cas_identifier, valid_cas
from kg_microbe.utils.ingredient_bundle_contract import annotation_id, canonical_json, validate_payload
from kg_microbe.utils.ingredient_bundle_contract import valid_cas as bundle_valid_cas
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed, ingredient_xref_allowed
from kg_microbe.utils.sssom_identity_policy import classify_mapping_row
from scripts import consolidate_chemical_mappings as consolidate
from scripts import mim_conservative_refresh as refresh
from tests.test_ingredient_bundle import producer_bundle as producer_bundle
from tests.test_mediadive_embedded_identity import _transform
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs

INVALID = "cas:977046-75-5"
VALID = "cas:7732-18-5"


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch):
    """Prevent these synthetic inputs from sharing the process-global mapping cache."""
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    yield
    runtime._LOADED = False
    runtime._CACHED_PATH = None


@pytest.mark.parametrize("value", [VALID, "cas:50-00-0", "cas:9000-40-2", "cas:51142-18-8"])
def test_existing_canonical_checksum_contract_is_shared(value):
    """Valid structure is necessary, not proof that a substance has that identity."""
    assert bundle_valid_cas is valid_cas
    assert valid_cas(value)
    assert ingredient_mapping_allowed("fixture", value)
    assert ingredient_xref_allowed("CHEBI:1", value)
    assert not invalid_cas_identifier(value)


@pytest.mark.parametrize(
    "value",
    [
        INVALID,
        "cas:01-23-4",
        "cas:1-23-4",
        "cas:12345678-90-1",
        "cas:50-0-0",
        "cas:abc",
        "cas:",
        "cas:187235376",
        "cas:1-Sep-14",
        "cas:７７３２-１８-５",
        None,
        12,
    ],
)
def test_invalid_canonical_identifiers_are_not_repaired(value):
    """Checksum, ASCII syntax and canonical digit widths are enforced together."""
    assert not valid_cas(value)


@pytest.mark.parametrize("value", [INVALID, "CAS:977046-75-5", "CAS-RN:977046-75-5", " cAs-rN:977046-75-5 "])
def test_aliases_cannot_bypass_mapping_or_xref_policy(value):
    """Representation aliases do not turn an invalid number into an active target."""
    assert invalid_cas_identifier(value)
    assert not ingredient_mapping_allowed("Yeast autolysate", value)
    assert not ingredient_mapping_allowed(value, "CHEBI:1")
    assert not ingredient_xref_allowed(value, "CHEBI:1")
    assert not ingredient_xref_allowed("CHEBI:1", value)
    assert consolidate.extract_curie(value) == ""
    assert not consolidate.is_accepted_primary(value)


def test_invalid_bare_registry_query_cannot_reenter_as_a_lexical_alias(tmp_path):
    """Invalid numbers are not names that authorize an otherwise valid target."""
    path = tmp_path / "names.tsv"
    rows = [
        _row("kgm.name:bad", "CHEBI:1", "Native name", name="977046-75-5", comment="synonym"),
        _row("kgm.name:good", "CHEBI:1", "Native name", name="Native name", comment="canonical_name"),
    ]
    _table(path, FIELDS, rows, _metadata())
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("Native name") == "CHEBI:1"
    for name in ("977046-75-5", INVALID, "CAS-RN:977046-75-5"):
        assert runtime.find_chebi_by_name(name) is None
        assert runtime.find_chebi_by_name(name, fuzzy_hydrate=True, fuzzy_stereochemistry=True) is None
    assert runtime.get_synonyms("CHEBI:1") == []


@pytest.mark.parametrize(
    "predicate,comment",
    [
        ("skos:exactMatch", ""),
        ("skos:exactMatch", "attribute_carrier"),
        ("skos:exactMatch", "canonical_name"),
        ("skos:closeMatch", "synonym"),
        ("skos:broadMatch", ""),
        ("skos:narrowMatch", ""),
        ("skos:closeMatch", "recipe_equivalent_hydrate"),
        ("oboInOwl:hasDbXref", ""),
    ],
)
@pytest.mark.parametrize("invalid_subject", [False, True])
def test_invalid_endpoints_are_quarantined_before_any_index(tmp_path, predicate, comment, invalid_subject):
    """No formula, category, name, parent, hydrate or xref can leak from a rejected row."""
    subject = (
        INVALID if invalid_subject else ("kgm.name:bad" if comment in {"canonical_name", "synonym"} else "CHEBI:2")
    )
    target = "CHEBI:1" if invalid_subject else INVALID
    if comment == "attribute_carrier":
        subject = target = INVALID
    bad = _row(subject, target, "Rejected label", predicate=predicate, name="Rejected alias", comment=comment)
    bad.update(object_formula="RejectedFormula", object_category="biolink:Food")
    assert classify_mapping_row(bad, _metadata()) == ("quarantined", "invalid_cas_identifier")
    good = _row("kgm.name:water", VALID, "water", name="water", comment="canonical_name")
    good.update(object_formula="H2O")
    path = tmp_path / "endpoints.tsv"
    _table(path, FIELDS, [bad, good], _metadata())
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_formula("RejectedFormula") == []
    assert runtime.find_chebi_by_name("Rejected label") is None
    assert runtime.find_chebi_by_name("Rejected alias") is None
    for identifier in {subject, target, INVALID, "CHEBI:1", "CHEBI:2"} - {VALID}:
        assert runtime.get_canonical_name(identifier) is None
        assert runtime.get_formula(identifier) is None
        assert runtime.get_category(identifier) is None
        assert runtime.get_xrefs(identifier) == []
        assert runtime.get_parents(identifier) == []
        assert runtime.get_hydrate_equivalents(identifier) == []
        assert runtime.find_chebi_by_xref(identifier) is None
    assert runtime.find_chebi_by_formula("H2O") == [VALID]
    assert runtime.find_chebi_by_name("water") == VALID
    assert runtime.get_mapping_load_audit()["counts"]["quarantined"] == 1
    assert runtime.get_mapping_load_audit()["diagnostics"][0]["reason"] == "invalid_cas_identifier"


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded", "all"])
def test_mediadive_retains_local_identity_and_every_typed_occurrence(route):
    """Repeated local ingredients retain positions, quantities and complete raw item JSON."""
    name = "Yeast autolysate"
    value = _transform(
        {"CAS-RN": "977046-75-5"} if route in {"embedded", "all"} else {},
        {name.lower(): INVALID} if route in {"legacy", "all"} else {},
        INVALID if route in {"unified", "all"} else None,
    )
    value.compounds_data["1603"] = value.compounds_data.pop("99")
    value.translation_table = str.maketrans("", "", "()")
    # Synthetic recipe context: the test asserts preservation, not an inferred
    # replacement CAS or a scientific claim about these arbitrary amounts.
    items = [
        {"compound_id": 1603, "compound": name, "amount": 5, "unit": "g", "g_l": 4.9505, "optional": False},
        {
            "compound_id": 1603,
            "compound": name,
            "amount": 5.0,
            "unit": "mg",
            "mmol_l": None,
            "citation": "fixture:2",
            "optional": 0,
        },
    ]
    value.solutions_data = {"1": {"recipe": deepcopy(items)}}
    actual = value.get_solution_recipe_occurrences("1")
    assert len(actual) == 2
    for position, (result, raw) in enumerate(zip(actual, items, strict=True), 1):
        assert result["id"] == "mediadive.ingredient:1603"
        assert result["source_assertion_id"] == f"mediadive.solution:1#recipe/{position}"
        assert canonical_json(json.loads(result["source_record"])) == canonical_json(raw)
        for field in ("amount", "unit", "g_l", "mmol_l"):
            assert type(result[field]) is type(raw.get(field))
            assert result[field] == raw.get(field)
    assert canonical_json(value.solutions_data["1"]["recipe"]) == canonical_json(items)
    with pytest.raises(ValueError, match="duplicate recipe display name"):
        value.get_compounds_of_solution("1")


def test_legacy_mapping_rejection_preserves_source_and_independent_valid_route(tmp_path):
    """Neither first-row selection nor legacy CAS-RN normalization resurrects a bad claim."""
    path = tmp_path / "legacy.tsv"
    content = "original\tmapped\nYeast autolysate\tCAS-RN:977046-75-5\nwater\tCAS-RN:7732-18-5\n"
    path.write_text(content)
    value = _transform({})
    assert value._load_mapping_file(path, "fixture") == {"water": "CAS-RN:7732-18-5"}
    assert path.read_text() == content
    supplied = _transform({"ChEBI": "15377", "CAS-RN": "977046-75-5"}, unified=INVALID)
    assert supplied.standardize_compound_id("99", "fixture") == "CHEBI:15377"
    assert _transform({"CAS-RN": "7732-18-5"}).standardize_compound_id("99", "water") == "CAS-RN:7732-18-5"


@pytest.mark.parametrize("query", ["07732-18-5", "７７３２-１８-５", "977046-75-5"])
def test_invalid_bare_registry_queries_have_no_hydration_scope_exemption(query):
    """Leading zeroes and Unicode digits cannot bypass the canonical checksum contract."""
    assert invalid_cas_identifier(query, allow_bare=True)
    assert not ingredient_mapping_allowed(query, "CHEBI:1")
    assert not identity.ingredient_hydration_compatible(query, "fixture hexahydrate")
    assert not identity.ingredient_hydration_compatible("CAS-RN:" + query, "fixture hexahydrate")


@pytest.mark.parametrize("query", ["10025-77-1", "cas:10025-77-1", "CAS:10025-77-1", "CAS-RN:10025-77-1"])
def test_valid_existing_registry_queries_retain_hydration_exception(query):
    """An independently supplied valid registry lookup can still name its declared hydrate."""
    assert identity.ingredient_hydration_compatible(query, "iron trichloride hexahydrate")


@pytest.mark.parametrize("query,valid", [(VALID, True), ("cas:07732-18-5", False), ("cas:７７３２-１８-５", False)])
def test_reviewed_cas_annotations_share_structural_validation(tmp_path, monkeypatch, query, valid):
    """A curated route may not admit a checksum-consistent but malformed registry number."""
    path = tmp_path / "scopes.tsv"
    path.write_text(f"kind\tquery\ttarget_id\treason\ncas\t{query}\tCHEBI:15377\tfixture\n")
    monkeypatch.setattr(identity, "NAME_SCOPE_POLICY", path)
    identity.ingredient_name_scopes.cache_clear()
    try:
        if valid:
            routes, annotations = identity.ingredient_name_scopes()
            assert annotations == {VALID: "CHEBI:15377"}
            assert routes["7732-18-5"] == "CHEBI:15377"
        else:
            with pytest.raises(ValueError, match="Invalid reviewed CAS annotation"):
                identity.ingredient_name_scopes()
    finally:
        identity.ingredient_name_scopes.cache_clear()


@pytest.mark.parametrize("identifier", [INVALID, "CAS:977046-75-5", "CAS-RN:977046-75-5", "cas:07732-18-5"])
def test_companion_annotation_cannot_admit_invalid_legacy_prefix(producer_bundle, identifier):
    """Even a claimed VALID annotation fails before becoming an active registry xref."""
    claim = producer_bundle.identifier_claims("CHEBI:29673")[0]
    claim.update(identifier=identifier, raw_identifier=identifier, identifier_validity="VALID")
    claim["annotation_id"] = annotation_id(claim)
    with pytest.raises(ValueError, match="Invalid normalized identifier"):
        validate_payload("identifier", claim)


@pytest.mark.parametrize("identifier", [VALID, "CAS-RN:7732-18-5", ""])
def test_companion_keeps_valid_inputs_and_invalid_raw_evidence(producer_bundle, identifier):
    """Existing valid inputs remain admissible; rejected evidence is retained only as raw text."""
    claim = producer_bundle.identifier_claims("CHEBI:29673")[0]
    claim.update(
        identifier=identifier,
        raw_identifier=identifier or INVALID,
        identifier_validity="VALID" if identifier else "INVALID",
        xref_eligible=False,
    )
    claim["annotation_id"] = annotation_id(claim)
    before = canonical_json(claim)
    validate_payload("identifier", claim)
    assert canonical_json(claim) == before


def test_invalid_cas_nested_solution_preserves_its_own_local_id_and_context():
    """A solution reference stays a solution; it is not guessed to be compound1603."""
    name = "Yeast autolysate"
    value = _transform({}, {name.lower(): INVALID}, INVALID)
    value.translation_table = str.maketrans("", "", "()")
    item = {"solution_id": 1729, "solution": name, "amount": 50, "unit": "ml", "optional": False}
    value.solutions_data = {"1727": {"recipe": [deepcopy(item)]}}
    (result,) = value.get_solution_recipe_occurrences("1727")
    assert result["id"] == "mediadive.solution:1729"
    assert result["source_assertion_id"] == "mediadive.solution:1727#recipe/1"
    assert result["amount"] == 50 and type(result["amount"]) is int
    assert result["unit"] == "ml"
    assert canonical_json(json.loads(result["source_record"])) == canonical_json(item)
    assert canonical_json(value.solutions_data["1727"]["recipe"][0]) == canonical_json(item)


def test_seed_and_export_reject_invalid_cas_before_metadata_or_parent_carrier_paths(tmp_path):
    """Full consolidation cannot retain malformed primary, xref, parent or hydrate endpoints."""
    seed = tmp_path / "seed.tsv"
    bad = _row(INVALID, "CHEBI:1", "Poison", name="Poison")
    bad.update(object_formula="PoisonFormula", object_category="biolink:Food")
    good = _row("kgm.name:native", "CHEBI:1", "Native", name="Native", comment="canonical_name")
    _table(seed, FIELDS, [bad, good, _row(INVALID, INVALID, "", comment="attribute_carrier")], _metadata())
    original = seed.read_bytes()
    value = consolidate.ChemicalMappingConsolidator()
    value.load_existing_unified(seed)
    assert set(value.chemicals) == {"CHEBI:1"}
    assert value.chemicals["CHEBI:1"]["canonical_name"] == "Native"
    assert value.chemicals["CHEBI:1"]["formula"] == ""
    value.add_chemical(INVALID, "Rejected", formula="RejectedFormula")
    assert INVALID not in value.chemicals
    # Defense in depth for callers adding relation records after the normal loaders.
    value.chemicals[INVALID] = dict(value.chemicals["CHEBI:1"], id=INVALID, canonical_name="", formula="Bad")
    value.chemicals["CHEBI:1"]["xrefs"].add(INVALID)
    value.parent_relations = [
        _row(INVALID, "CHEBI:1", "Native", predicate="skos:broadMatch"),
        _row("CHEBI:1", INVALID, "Bad", predicate="skos:narrowMatch"),
    ]
    value.hydrate_equivalences.add(("CHEBI:1", INVALID))
    output = tmp_path / "export.tsv.gz"
    value.export_unified_sssom(output)
    rows = _read(output)
    assert rows
    assert all(not invalid_cas_identifier(row[field]) for row in rows for field in ("subject_id", "object_id"))
    assert not any(row["object_formula"] == "Bad" for row in rows)
    assert seed.read_bytes() == original


def test_identity_only_refresh_does_not_preserve_invalid_asymmetric_rows(tmp_path):
    """Structural rejection precedes the weaker-relation pass-through, preserving raw input."""
    source, output = tmp_path / "baseline.tsv", tmp_path / "candidate.tsv.gz"
    good = _row(VALID, "CHEBI:15377", "water")
    bad = [
        _row(INVALID, "CHEBI:15377", "water", predicate="skos:broadMatch"),
        _row("CHEBI:15377", INVALID, "Bad", predicate="skos:narrowMatch"),
        _row(INVALID, INVALID, "Bad", comment="attribute_carrier"),
    ]
    _table(source, FIELDS, [*bad, good], _metadata())
    original = source.read_bytes()
    stats = consolidate.refresh_identity_policy(source, output)
    assert stats["rows_removed"] == len(bad)
    assert _read(output) == [good]
    assert source.read_bytes() == original


def test_official_candidate_preserves_invalid_claims_and_traces_historical_taint(inputs):
    """Bad historical links still trace copied aliases, but never establish active identity."""
    path = inputs["baseline"]
    baseline = list(refresh._rows(path))
    bad = [
        _row("kgm.name:yeast", INVALID, "Yeast autolysate", name="Yeast autolysate", comment="synonym"),
        _row(INVALID, "CHEBI:1", "One"),
        _row(INVALID, "CHEBI:4", "Untouched"),
        _row(INVALID, "CHEBI:4", "Untouched", predicate="skos:broadMatch"),
        _row("CHEBI:4", INVALID, "Bad", predicate="skos:narrowMatch"),
        _row(INVALID, INVALID, "", comment="attribute_carrier"),
        _row("CHEBI:4", INVALID, "Bad", predicate="skos:closeMatch", comment="recipe_equivalent_hydrate"),
    ]
    bad[0].update(confidence="0.73", object_formula="untrusted formula", source="source:original|source:second")
    bad.append(dict(bad[0]))
    copied = _row("kgm.name:copied", "CHEBI:4", "Untouched", name="Unsupported copied alias", comment="synonym")
    _table(path, FIELDS, [*baseline, *bad, copied], _metadata())
    original = path.read_bytes()
    result = refresh.build_conservative_candidate(**inputs)
    assert "CHEBI:4" in result.report["affected_entities"]
    output = _read(result.candidate_path)
    assert not any(invalid_cas_identifier(row[field]) for row in output for field in ("subject_id", "object_id"))
    quarantined = [row for row in _read(result.quarantine_path) if row["quarantine_reason"] == "invalid_cas_identifier"]
    assert Counter(tuple(row[field] for field in FIELDS) for row in quarantined) == Counter(
        tuple(row[field] for field in FIELDS) for row in bad
    )
    assert any(key.endswith("/kg_microbe/utils/cas.py") for key in result.report["input_sha256"])
    assert dict(copied, quarantine_reason="historical_entity_provenance_or_identity_component") in _read(
        result.quarantine_path
    )
    runtime.load_unified_mappings(result.candidate_path)
    assert runtime.find_chebi_by_name("Unsupported copied alias") is None
    assert runtime.find_chebi_by_name("Untouched") == "CHEBI:4"  # Independently native fixture authority.
    assert runtime.find_chebi_by_name("Yeast autolysate") is None
    assert path.read_bytes() == original
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=result.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert result.candidate_path.read_bytes() == second.candidate_path.read_bytes()
