"""Keep reviewed form-to-parent mappings directional and outside identity (#1790, #1791)."""

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from scripts import mim_conservative_refresh as refresh
from tests import test_mim_reviewed_release as release_fixtures
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _metadata, _node, _row, _table

FIXTURE = Path(__file__).parent / "resources/mim_reviewed_broader_20261107/source-claims.json"
FIXTURE_SHA256 = "a08a231ea586e84b549736c76b3e8c5d6c8c4d9a8977da69cdfa481b8ef378c0"


def _claims():
    """Read the unchanged six actual source claims and their original review decisions."""
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    claims = json.loads(raw)["claims"]
    for claim in claims:
        assert refresh.row_sha256(claim["row"]) == claim["decision"]["row_sha256"]
        assert claim["decision"]["disposition"] == "SUPPORTED"
    return [claim["row"] for claim in claims]


def _release(directory, rows, withheld=()):
    """Build an explicitly synthetic subset partition, never an official complete export."""
    directory.mkdir(exist_ok=True)
    fields = list(rows[0])
    for group, name, values in (
        ("supported", "ingredient_mappings.sssom.tsv", rows),
        ("withhold", "withheld_mappings.sssom.tsv", withheld),
    ):
        metadata = _metadata()
        metadata["mapping_set_id"] = f"https://example.org/mim-broader-fixture/{group}"
        metadata["mapping_set_version"] = "2026-11-04"
        metadata["curie_map"]["kgmicrobe.compound"] = "https://w3id.org/kg-microbe/compound/"
        metadata["curie_map"]["registry"] = "https://example.org/registry/"
        metadata["curie_map"]["kgm"] = "https://example.org/kgm/"
        metadata["extension_definitions"].append(
            {
                "slot_name": "validation_method",
                "property": "https://example.org/validation_method",
                "type_hint": "xsd:string",
            }
        )
        _table(directory / name, fields, values, metadata)
    decisions = [
        release_fixtures._decision(row, position, disposition)
        for position, (row, disposition) in enumerate(
            [*((row, "SUPPORTED") for row in rows), *((row, "WITHHOLD") for row in withheld)], 1
        )
    ]
    _table(directory / "mapping-dispositions.tsv", release_fixtures.release.DISPOSITION_FIELDS, decisions)
    manifest = {
        "schema_version": 1,
        "scope": "MIM-only reviewed SSSOM; no KGX dependency",
        "semantic_status": "PASS_SUPPORTED_SUBSET",
        "source_sssom": "mappings/ingredient_mappings.sssom.tsv",
        "source_sha256": hashlib.sha256(json.dumps([*rows, *withheld], sort_keys=True).encode()).hexdigest(),
        "review_sha256": hashlib.sha256(json.dumps(decisions, sort_keys=True).encode()).hexdigest(),
        "counts": {"source": len(rows) + len(withheld), "supported": len(rows), "withhold": len(withheld)},
        "mapping_set_ids": {
            group: f"https://example.org/mim-broader-fixture/{group}" for group in ("supported", "withhold")
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return release_fixtures._repin(directory)


@pytest.fixture
def broader_inputs(tmp_path):
    """Pair the actual claims with a clearly synthetic native baseline and authority table."""
    rows = _claims()
    directory = tmp_path / "release"
    pin = _release(directory, rows)
    baseline = tmp_path / "baseline.tsv"
    metadata = _metadata()
    metadata.pop("predicate_semantics")
    metadata["curie_map"]["kgmicrobe.compound"] = "https://w3id.org/kg-microbe/compound/"
    parents = [row for row in rows if row["predicate_id"] == "skos:broadMatch"]
    historical = [
        _row(
            "kgm.name:parent_" + row["object_id"],
            row["object_id"],
            row["object_label"],
            name=row["object_label"],
            comment="canonical_name",
        )
        for row in parents
    ]
    historical.append(
        _row(
            "kgm.name:parent_only_alias",
            "CHEBI:6731",
            "melezitose",
            name="Parent-only historical alias",
            predicate="skos:closeMatch",
            comment="synonym",
        )
    )
    _table(baseline, FIELDS, historical, metadata)
    native = tmp_path / "chebi_nodes.tsv"
    _table(native, NODE_FIELDS, [_node(row["object_id"], row["object_label"]) for row in parents])
    return {
        "baseline": baseline,
        "release_directory": directory,
        "expected_manifest_sha256": pin,
        "ontology_paths": (native,),
        "independent_sources": (),
        "output_directory": tmp_path / "candidate",
    }


def _load(path, monkeypatch):
    """Query only a test-owned candidate through the unchanged real lookup reader."""
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)


def _expected_relations(rows):
    """Derive the finite expected relation set from explicit same-subject exact claims."""
    return {
        (exact["object_id"], broad["object_id"])
        for broad in rows
        if broad["predicate_id"] == "skos:broadMatch"
        for exact in rows
        if exact["predicate_id"] == "skos:exactMatch" and exact["subject_id"] == broad["subject_id"]
    }


def test_actual_two_broad_claims_project_four_nonidentity_relations(broader_inputs, monkeypatch):
    """Both CAS and local form identities retain parent navigation without identity strengthening."""
    source_rows = _claims()
    before = {path: path.read_bytes() for path in broader_inputs["release_directory"].iterdir()}
    result = refresh.build_conservative_candidate(**broader_inputs)
    rows = list(refresh._rows(result.candidate_path))
    broad_rows = [row for row in rows if row["predicate_id"] == "skos:broadMatch"]
    assert {(row["subject_id"], row["object_id"]) for row in broad_rows} == _expected_relations(source_rows)
    assert len(broad_rows) == 4
    assert refresh._header(result.candidate_path)[0]["predicate_semantics"] == "skos"
    assert result.report["counts"]["supported_exact_rows"] == 4
    assert result.report["counts"]["supported_broader_rows"] == 2
    assert result.report["counts"]["derived_broader_rows"] == 4
    assert result.report["supported_name_lookup_conflicts"] == []
    assert result.report["supported_xref_lookup_conflicts"] == []
    parents = {row["object_id"] for row in broad_rows}
    assert not parents.intersection(result.report["initial_affected_entities"])
    hashes = {refresh.row_sha256(row): row for row in source_rows}
    for derivation in result.report["supported_broader_relation_derivations"]:
        broad = hashes[derivation["broad_row_sha256"]]
        assert broad["predicate_id"] == "skos:broadMatch"
        assert len(derivation["exact_identity_row_sha256"]) == 1
        exact = hashes[derivation["exact_identity_row_sha256"][0]]
        assert exact["predicate_id"] == "skos:exactMatch"
        assert exact["subject_id"] == broad["subject_id"] == derivation["source_subject_id"]
        assert derivation["row"]["subject_id"] == exact["object_id"]
        assert derivation["derived_row_sha256"] == refresh.row_sha256(derivation["row"])
        assert derivation["broad_row_sha256"] in derivation["row"]["source"]
        assert derivation["exact_identity_row_sha256"][0] in derivation["row"]["source"]
    _load(result.candidate_path, monkeypatch)
    for child, parent in _expected_relations(source_rows):
        assert runtime.get_parents(child) == [parent]
        assert not runtime.get_parents(parent)
        assert parent not in runtime.get_xrefs(child)
    for broad in (row for row in source_rows if row["predicate_id"] == "skos:broadMatch"):
        approved = {
            row["object_id"]
            for row in source_rows
            if row["predicate_id"] == "skos:exactMatch" and row["subject_id"] == broad["subject_id"]
        }
        assert runtime.find_chebi_by_name(broad["subject_label"]) in approved
        assert runtime.find_chebi_by_xref(broad["subject_id"]) in approved
        assert broad["subject_id"] not in runtime.get_xrefs(broad["object_id"])
        assert broad["subject_label"] not in runtime.get_synonyms(broad["object_id"])
        assert runtime.find_chebi_by_name(broad["object_label"]) == broad["object_id"]
    assert before == {path: path.read_bytes() for path in before}


def test_actual_broader_second_cycle_keeps_bytes_and_identity_scope(broader_inputs):
    """A known derived relation must not taint its parent on a later reconstruction cycle."""
    first = refresh.build_conservative_candidate(**broader_inputs)
    second = refresh.build_conservative_candidate(
        **dict(broader_inputs, baseline=first.candidate_path, output_directory=first.directory.with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    assert first.report["initial_affected_entities"] == second.report["initial_affected_entities"]
    assert (
        first.report["supported_broader_relation_derivations"]
        == second.report["supported_broader_relation_derivations"]
    )


def test_source_order_cannot_choose_a_different_form_parent(broader_inputs, monkeypatch):
    """Every explicit form retains the same parent when source product ordering reverses."""
    first = refresh.build_conservative_candidate(**broader_inputs)
    rows = list(reversed(_claims()))
    pin = _release(broader_inputs["release_directory"], rows)
    second = refresh.build_conservative_candidate(
        **dict(broader_inputs, expected_manifest_sha256=pin, output_directory=first.directory.with_name("reversed"))
    )
    assert {
        (row["subject_id"], row["object_id"])
        for row in refresh._rows(second.candidate_path)
        if row["predicate_id"] == "skos:broadMatch"
    } == _expected_relations(rows)
    _load(second.candidate_path, monkeypatch)
    for child, parent in _expected_relations(rows):
        assert runtime.get_parents(child) == [parent]


def test_withheld_exact_sibling_never_gets_a_derived_parent(broader_inputs, monkeypatch):
    """Only supported exact identities may transport the broader assertion to a form."""
    all_rows = _claims()
    held = next(row for row in all_rows if row["object_id"] == "cas:10030-67-8")
    rows = [row for row in all_rows if row != held]
    pin = _release(broader_inputs["release_directory"], rows, [held])
    result = refresh.build_conservative_candidate(**dict(broader_inputs, expected_manifest_sha256=pin))
    _load(result.candidate_path, monkeypatch)
    assert runtime.get_parents(held["object_id"]) == []
    assert runtime.get_parents("kgmicrobe.compound:d-_-melezitose_monohydrate") == ["CHEBI:6731"]
    assert result.report["counts"]["derived_broader_rows"] == 3


@pytest.mark.parametrize("change", ["wrong_water_count", "parent_is_exact"])
def test_contradictory_exact_form_cannot_transport_broader_claim(broader_inputs, change):
    """Reject contradictory synthetic siblings rather than emitting an inferred form relation."""
    rows = _claims()
    exact = next(row for row in rows if row["object_id"] == "cas:10030-67-8")
    if change == "wrong_water_count":
        exact["subject_label"] = "D-(+)-melezitose dihydrate"
    else:
        exact["object_id"] = "CHEBI:6731"
    pin = _release(broader_inputs["release_directory"], rows)
    with pytest.raises(ValueError, match="Broader (source changes|parent is also)"):
        refresh.build_conservative_candidate(**dict(broader_inputs, expected_manifest_sha256=pin))
    assert not broader_inputs["output_directory"].exists()


def test_broader_aliases_and_labels_do_not_enter_identity_diagnostics(broader_inputs, monkeypatch):
    """A broad row alone supplies neither a parent declaration nor lexical resolution."""
    rows = _claims()
    for row in rows:
        if row["predicate_id"] == "skos:broadMatch":
            row["object_label"] = "Broad-only parent display"
            row["other"] = "Broad-only unsupported alias"
    pin = _release(broader_inputs["release_directory"], rows)
    result = refresh.build_conservative_candidate(**dict(broader_inputs, expected_manifest_sha256=pin))
    assert result.report["supported_name_lookup_conflicts"] == []
    assert result.report["supported_xref_lookup_conflicts"] == []
    _load(result.candidate_path, monkeypatch)
    assert runtime.find_chebi_by_name("Broad-only parent display") is None
    assert runtime.find_chebi_by_name("Broad-only unsupported alias") is None
    assert runtime.find_chebi_by_name("Parent-only historical alias") == "CHEBI:6731"


def test_old_false_exact_claims_keep_full_quarantine_multiplicity(broader_inputs, monkeypatch):
    """Historical exact contamination is still reset even when current support is only broader."""
    path = broader_inputs["baseline"]
    metadata, fields = refresh._header(path)
    bad = _row("MIM:D-_-melezitose_Monohydrate", "CHEBI:6731", "melezitose", source="mediaingredientmech_reviewed")
    _table(path, fields, [*refresh._rows(path), bad, dict(bad)], metadata)
    result = refresh.build_conservative_candidate(**broader_inputs)
    held = [row for row in refresh._rows(result.quarantine_path) if row["subject_id"] == bad["subject_id"]]
    assert len(held) == 2
    assert all({key: value for key, value in row.items() if key != "quarantine_reason"} == bad for row in held)
    _load(result.candidate_path, monkeypatch)
    assert runtime.find_chebi_by_xref(bad["subject_id"]) != "CHEBI:6731"
    assert runtime.find_chebi_by_name("melezitose") == "CHEBI:6731"


@pytest.mark.parametrize("semantics", [None, "sk0s"])
def test_new_skos_rows_refuse_mixed_or_unknown_legacy_semantics(broader_inputs, semantics):
    """Do not silently flip an existing synthetic legacy relation with a new file-wide declaration."""
    path = broader_inputs["baseline"]
    metadata, fields = refresh._header(path)
    if semantics is not None:
        metadata["predicate_semantics"] = semantics
    legacy = _row("CHEBI:6731", "CHEBI:132103", "sodium perchlorate", predicate="skos:narrowMatch")
    _table(path, fields, [*refresh._rows(path), legacy], metadata)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Cannot mix legacy or unknown asymmetric semantics"):
        refresh.build_conservative_candidate(**broader_inputs)
    assert not broader_inputs["output_directory"].exists()
    assert path.read_bytes() == before


def test_existing_skos_relation_is_conserved_with_new_broader_rows(broader_inputs, monkeypatch):
    """Preserve the complete independent directed relation alongside the new source claims."""
    path = broader_inputs["baseline"]
    metadata, fields = refresh._header(path)
    metadata["predicate_semantics"] = "skos"
    old = _row("CHEBI:6731", "CHEBI:132103", "sodium perchlorate", predicate="skos:narrowMatch")
    _table(path, fields, [*refresh._rows(path), old], metadata)
    result = refresh.build_conservative_candidate(**broader_inputs)
    assert Counter(tuple(row.items()) for row in refresh._rows(result.candidate_path))[tuple(old.items())] == 1
    _load(result.candidate_path, monkeypatch)
    assert runtime.get_parents("CHEBI:132103") == ["CHEBI:6731"]


@pytest.mark.parametrize("claim", ["broad", "local_registry", "cas"])
def test_builder_refuses_modified_supported_claim_before_projection(broader_inputs, monkeypatch, claim):
    """Defend the builder boundary even if a supplied validated bundle is later modified (#1794)."""
    bundle = refresh.validate_reviewed_bundle(
        broader_inputs["release_directory"],
        expected_manifest_sha256=broader_inputs["expected_manifest_sha256"],
    )
    rows = [dict(row, predicate_modifier="") for row in bundle.supported_rows]
    target = {
        "broad": "CHEBI:6731",
        "local_registry": "kgmicrobe.compound:d-_-melezitose_monohydrate",
        "cas": "cas:10030-67-8",
    }[claim]
    next(row for row in rows if row["object_id"] == target)["predicate_modifier"] = "Not"
    changed = replace(bundle, supported_rows=tuple(rows))
    monkeypatch.setattr(refresh, "validate_reviewed_bundle", lambda *args, **kwargs: changed)

    def unexpected_projection(*args, **kwargs):
        """Fail if a modified supported claim reaches positive relation construction."""
        pytest.fail("Modified supported claim reached broader projection")

    monkeypatch.setattr(refresh, "_broader_projections", unexpected_projection)
    before = {path: path.read_bytes() for path in broader_inputs["release_directory"].iterdir()}
    with pytest.raises(ValueError, match="Supported MIM predicate modifiers cannot become positive assertions"):
        refresh.build_conservative_candidate(**broader_inputs)
    assert not broader_inputs["output_directory"].exists()
    assert before == {path: path.read_bytes() for path in before}


def test_blank_supported_modifiers_preserve_actual_positive_relations(broader_inputs, monkeypatch):
    """An explicit blank modifier has the same positive meaning as the native absent column."""
    rows = [dict(row, predicate_modifier="") for row in _claims()]
    pin = _release(broader_inputs["release_directory"], rows)
    result = refresh.build_conservative_candidate(**dict(broader_inputs, expected_manifest_sha256=pin))
    _load(result.candidate_path, monkeypatch)
    for child, parent in _expected_relations(rows):
        assert runtime.get_parents(child) == [parent]
    assert result.report["counts"]["derived_broader_rows"] == 4
