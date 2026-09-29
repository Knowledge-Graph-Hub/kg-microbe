"""Keep a source-qualified supplier material distinct from a pure acyl species (#1241)."""

import copy
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.mediadive import material_scope_audit as audit
from kg_microbe.utils import chemical_mapping_utils as mapping
from kg_microbe.utils.ingredient_identity import (
    ingredient_authority_label,
    ingredient_mapping_allowed,
    ingredient_xref_allowed,
)
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests import test_mediadive_material_scope_audit as audit_tests
from tests import test_mim_conservative_refresh as refresh_tests
from tests.test_consolidate_chemical_mappings import _load_module
from tests.test_mediadive_material_scope_audit import _producer, _rows
from tests.test_mediadive_recipe_occurrences import _resolver
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _table

FIXTURE = Path(__file__).parent / "resources/mediadive/p3556_scope.json"
TARGET = "CHEBI:86658"
inputs = refresh_tests.inputs
bundle = refresh_tests.bundle


def _saved():
    """Bind the immutable original source, native structure and complete imported rows."""
    data = FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "7c06f4e2179356ddf1d917a6938cba5e3bdf6669f42a29019b93963e4a70646c"
    return json.loads(data)


def _claims(table):
    """Retain full columns from the selected immutable mapping excerpt."""
    return [item["row"] for item in _saved()["mapping_claims"] if item["table"] == table]


def _mapping_files(root, *, unified=None, supported=None):
    """Write tiny synthetic snapshots, never a repository mapping export."""
    unified = _claims("unified") if unified is None else unified
    supported = _claims("supported") if supported is None else supported
    directory = root / "mappings"
    directory.mkdir(exist_ok=True)
    with gzip.open(directory / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(unified)
    path = directory / "ingredient_mappings.sssom.tsv"
    _table(path, tuple(_claims("supported")[0]), supported)
    return path


@pytest.mark.parametrize(
    "name", ["L-alpha-Phosphatidylcholine", "L-α-Phosphatidylcholine", " l ALPHA phosphatidylcholine "]
)
def test_generic_alias_is_not_native_specific_structure(name):
    """The authority's generic display label must not defeat its explicit molecular structure."""
    assert not ingredient_mapping_allowed(name, TARGET)
    assert not ingredient_xref_allowed(audit.P3556_MIM, TARGET)
    assert not ingredient_xref_allowed(TARGET, audit.P3556_MIM)
    for row in _claims("unified")[1:5]:
        assert ingredient_mapping_allowed(row["subject_label"], TARGET)
    assert ingredient_mapping_allowed(name, "CHEBI:16110")
    assert ingredient_mapping_allowed(name, "CHEBI:49183")
    assert ingredient_mapping_allowed(name, "cas:8002-43-5")
    assert ingredient_xref_allowed("cas:8002-43-5", "CHEBI:16110")


def test_native_reader_retains_structure_but_not_generic_or_direct_identity(tmp_path, monkeypatch):
    """Actual reader policies close both lexical and MIM paths without banning the molecule."""
    path = tmp_path / "fixture.tsv"
    _table(path, FIELDS, _claims("unified"), _metadata())
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)
    mapping.load_unified_mappings(path)
    for name in ("L-alpha-Phosphatidylcholine", "L-α-Phosphatidylcholine"):
        assert mapping.find_chebi_by_name(name) is None
    assert mapping.find_chebi_by_xref(audit.P3556_MIM) is None
    assert mapping.get_canonical_name(TARGET) == ingredient_authority_label(TARGET)
    for row in _claims("unified")[1:5]:
        assert mapping.find_chebi_by_name(row["subject_label"]) == TARGET


@pytest.mark.parametrize("target", [TARGET, "CHEBI:16110", "CHEBI:49183", "CAS-RN:8002-43-5", "PubChem:123"])
@pytest.mark.parametrize("kind", ["compound", "solution"])
def test_product_qualifier_precedes_every_name_route(target, kind):
    """The whole product stays local even when the displayed name is structurally specific."""
    raw = dict(_saved()["raw"], compound=_claims("unified")[2]["subject_label"])
    if kind == "solution":
        raw["solution_id"] = raw.pop("compound_id")
        raw["solution"] = raw.pop("compound")
    transform = _resolver({"629": {"recipe": [raw]}})
    calls = []
    transform.chemical_loader.find_chebi_by_name = lambda name: calls.append(name) or target
    transform.compound_mappings[raw.get("compound", raw.get("solution")).lower()] = target
    transform.compounds_data = {
        "2082": {"ChEBI": "86658", "KEGG-Compound": "C1", "PubChem": 123, "CAS-RN": "8002-43-5"}
    }
    occurrence = transform.get_solution_recipe_occurrences("629")[0]
    assert calls == []
    assert occurrence["id"] == f"mediadive.{'ingredient' if kind == 'compound' else 'solution'}:2082"
    assert json.loads(occurrence["source_record"]) == raw
    assert {key: occurrence[key] for key in ("amount", "unit", "g_l", "mmol_l")} == {
        "amount": 5,
        "unit": "mg",
        "g_l": 5,
        "mmol_l": None,
    }


@pytest.mark.parametrize("qualifier", ["SIGMA P3556", " sigma   p3556 "])
def test_direct_call_uses_explicit_embedded_evidence_but_empty_occurrence_does_not(qualifier):
    """A source ID never borrows another occurrence's material qualifier when one was supplied."""
    transform = _resolver({})
    transform.compounds_data = {"2082": {"attribute": qualifier, "ChEBI": "16110"}}
    transform.chemical_loader.find_chebi_by_name = lambda _: "CHEBI:16110"
    assert transform.standardize_compound_id("2082", "Generic") == "mediadive.ingredient:2082"
    assert transform.standardize_compound_id("2082", "Generic", source_record={}) == "CHEBI:16110"
    assert transform.standardize_compound_id("2082", "Generic", source_record={"attribute": "Other"}) == "CHEBI:16110"


@pytest.mark.parametrize("qualifier", [None, "", "SIGMA P35560", "P3556", "SIGMA P3556 alternative", "SIGMA P3555"])
def test_no_product_or_id_only_hold(qualifier):
    """Neither ingredient number nor a fuzzy catalog code imposes this finite scientific decision."""
    raw = dict(_saved()["raw"], attribute=qualifier)
    transform = _resolver({"629": {"recipe": [raw]}})
    transform.chemical_loader.find_chebi_by_name = lambda _: "CHEBI:16110"
    assert transform.get_solution_recipe_occurrences("629")[0]["id"] == "CHEBI:16110"


def test_actual_writer_preserves_original_observation_and_all_available_claims(tmp_path, monkeypatch):
    """Audit originals are candidates, not invented raw CAS assertions or attempted lookups."""
    raw = _saved()["raw"]
    producer, _ = _producer(
        tmp_path, monkeypatch, recipes={"629": {"recipe": [raw]}}, legacy=False, selected="CHEBI:16110"
    )
    supported = _mapping_files(tmp_path)
    before = supported.read_bytes()
    producer.run(show_status=False)
    rows = _rows(producer)
    # All seven unified rows carry the old generic canonical object label;
    # preserve them as available claims even when the new policy rejects it.
    assert len(rows) == 8
    assert Counter(row["candidate_route"] for row in rows) == {audit.UNIFIED_ROLE: 7, audit.SUPPORTED_ROLE: 1}
    originals = {audit._json(row) for row in _claims("unified") + _claims("supported")}
    for row in rows:
        assert row["candidate_record"] in originals
        assert json.loads(row["source_record"]) == raw
        assert row["retained_target"] == "mediadive.ingredient:2082"
        assert row["source_assertion_id"] == _saved()["source_assertion_id"]
        assert row["reason"] == "whole_product_not_molecular_identity"
        assert row["authority_uri"] == audit.P3556_AUTHORITY_URI
        assert row["source_record_sha256"] == hashlib.sha256(row["source_record"].encode()).hexdigest()
        assert "CAS-RN" not in json.loads(row["source_record"])
    with producer.output_edge_file.open() as stream:
        # The producer's pandas deduplication still writes CSV-quoted fields;
        # source finalization supplies the canonical literal TSV boundary.
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 1
    edge = edges[0]
    assert edge["object"] == "mediadive.ingredient:2082"
    assert json.loads(edge["source_record"]) == raw
    assert (edge["primary_knowledge_source"], edge["knowledge_level"], edge["agent_type"]) == (
        "infores:mediadive",
        "observation",
        "manual_agent",
    )
    assert (edge["value"], edge["unit"], edge["g_l"], edge["mmol_l"]) == ("5.0", "mg", "5.0", "")
    with producer.output_node_file.open() as stream:
        node = next(
            row
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if row["id"] == "mediadive.ingredient:2082"
        )
    assert node["category"] == "biolink:ChemicalEntity"
    assert node["provided_by"] == "infores:mediadive"
    assert supported.read_bytes() == before
    verify_producer_audits(producer)


def test_actual_spelling_and_duplicate_candidate_rows_are_preserved(tmp_path, monkeypatch):
    """A contradictory structural display still holds the product and retains its own original claims."""
    specific = _claims("unified")[2]
    raw = dict(_saved()["raw"], compound=specific["subject_label"], custom=None, optional=False)
    embedded = {"2082": dict(raw, ChEBI="86658", PubChem=0, **{"KEGG-Compound": "C1", "CAS-RN": "8002-43-5"})}
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [raw]}}, legacy=False, embedded=embedded)
    _mapping_files(tmp_path, unified=[specific, specific, *_claims("unified")[-2:]])
    # Legacy optional selection happened at constructor-time: create it first in
    # a separate test below; this test exercises selected unified and embedded inputs.
    producer.run(show_status=False)
    rows = _rows(producer)
    assert Counter(row["candidate_route"] for row in rows) == {
        audit.UNIFIED_ROLE: 2,
        audit.SUPPORTED_ROLE: 1,
        "mediadive_compounds": 4,
    }
    assert {
        json.loads(row["candidate_record"])["subject_label"]
        for row in rows
        if row["candidate_route"] == audit.UNIFIED_ROLE
    } == {specific["subject_label"]}
    assert len({row["candidate_record_locator"] for row in rows if row["candidate_route"] == audit.UNIFIED_ROLE}) == 2
    assert all(json.loads(row["source_record"]) == raw for row in rows)


@pytest.mark.parametrize("removed", [False, True])
def test_removed_unified_claim_keeps_original_supported_evidence_or_valid_empty_audit(tmp_path, monkeypatch, removed):
    """Removing an identity claim is a normal state, not a reason to invent a candidate."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _mapping_files(tmp_path, unified=[], supported=[] if removed else None)
    producer.run(show_status=False)
    assert len(_rows(producer)) == (0 if removed else 1)
    assert audit.SUPPORTED_ROLE in producer.consumed_input_snapshots
    verify_producer_audits(producer)
    report = {"consumed_inputs": producer.consumed_input_snapshots}
    audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")
    del report["consumed_inputs"][audit.SUPPORTED_ROLE]
    if not removed:
        with pytest.raises(SourceFinalizationRequired, match="origin"):
            audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")


def test_supported_origin_drift_and_repeated_visits_are_guarded(tmp_path, monkeypatch):
    """The supported table is audit-only evidence with the same immutable-consumption guarantees."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    supported = _mapping_files(tmp_path)
    producer.run(show_status=False)
    path = producer.output_dir / audit.AUDIT_FILENAME
    original = path.read_bytes()
    producer.get_solution_recipe_occurrences("1")
    producer._material_scope_audit.write()
    assert path.read_bytes() == original
    report = {"consumed_inputs": copy.deepcopy(producer.consumed_input_snapshots)}
    report["consumed_inputs"][audit.SUPPORTED_ROLE]["path"] = str(tmp_path / "other.tsv")
    with pytest.raises(SourceFinalizationRequired, match="origin"):
        audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")
    supported.write_text(supported.read_text() + "changed")
    with pytest.raises(Exception, match="changed|drift|identity"):
        producer._material_scope_audit.write()


def test_identity_refresh_keeps_explicit_structures_and_is_idempotent(tmp_path):
    """The ordinary bounded refresher cannot reinstate generic aliases or the MIM identity pair."""
    module = _load_module()
    source, first, second = (tmp_path / name for name in ("source.tsv", "first.tsv.gz", "second.tsv.gz"))
    _table(source, FIELDS, _claims("unified"), _metadata())
    before = source.read_bytes()
    result = module.refresh_identity_policy(source, first)
    assert result["rows_removed"] == 3
    assert result["rows_relabelled"] == 4
    module.refresh_identity_policy(first, second)
    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt") as stream:
        rows = list(csv.DictReader((line for line in stream if not line.startswith("#")), delimiter="\t"))
    expected = [dict(row, object_label=ingredient_authority_label(TARGET)) for row in _claims("unified")[1:5]]
    assert rows == expected
    assert source.read_bytes() == before


@pytest.mark.parametrize("name", ["L-alpha-Phosphatidylcholine", "L-α-Phosphatidylcholine"])
def test_legacy_regeneration_does_not_restore_generic_alias(tmp_path, monkeypatch, name):
    """Legacy import retains the native molecule but must not propagate its rejected generic label."""
    module = _load_module()
    monkeypatch.setattr(module, "_build_mangle_blacklist", lambda *_: set())
    path = tmp_path / "compound_mappings_strict.tsv"
    _table(
        path,
        ("original", "mapped", "chebi_label"),
        [{"original": name, "mapped": TARGET, "chebi_label": "L-alpha-Phosphatidylcholine"}],
    )
    consolidator = module.ChemicalMappingConsolidator()
    consolidator.load_compound_mappings(path)
    assert consolidator.chemicals[TARGET]["canonical_name"] == ingredient_authority_label(TARGET)
    assert name not in consolidator.chemicals[TARGET]["synonyms"]


def test_conservative_refresh_losslessly_quarantines_original_generic_rows(inputs):
    """Ordinary regeneration preserves full rejected claims and row multiplicity across cycles."""
    refresh = refresh_tests.refresh
    held = [_claims("unified")[index] for index in (0, 5, 6)]
    _table(inputs["baseline"], FIELDS, [*refresh._rows(inputs["baseline"]), *held, *held], _metadata())
    before = inputs["baseline"].read_bytes()
    first = refresh.build_conservative_candidate(**inputs)
    rows = [row for row in refresh_tests._read(first.quarantine_path) if row["object_id"] == TARGET]
    assert len(rows) == 6
    assert {row.pop("quarantine_reason") for row in rows} == {
        "reviewed_identity_policy_name",
        "reviewed_identity_policy_xref",
    }
    assert Counter(audit._json(row) for row in rows) == Counter(audit._json(row) for row in held * 2)
    assert all(row["object_id"] != TARGET for row in refresh_tests._read(first.candidate_path))
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    assert inputs["baseline"].read_bytes() == before


def test_mixed_profiles_legacy_candidates_and_full_payloads_do_not_cross(tmp_path, monkeypatch):
    """Available legacy row multiplicity is retained only on its matching material occurrence."""
    original = audit_tests._write_mappings

    def write_with_legacy(root, **kwargs):
        """Populate selected optional files before the producer chooses its immutable inputs."""
        result = original(root, **kwargs)
        for filename in (
            audit_tests.mod.MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE,
            audit_tests.mod.MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE,
        ):
            with (root / "raw" / filename).open("a") as stream:
                for _ in range(2):
                    stream.write('L-α-Phosphatidylcholine\tCHEBI:16110\tsaved alternative\t"literal|pipe"\n')
        return result

    monkeypatch.setattr(audit_tests, "_write_mappings", write_with_legacy)
    raw = _saved()["raw"]
    recipes = {"1": {"recipe": [raw, {"compound": "Potato", "compound_id": 1606}]}}
    producer, _ = _producer(tmp_path, monkeypatch, recipes=recipes)
    potato = json.loads(audit_tests.FIXTURE.read_text())["mapping_claims"]["unified"]["row"]
    _mapping_files(tmp_path, unified=[*_claims("unified"), potato])
    producer.run(show_status=False)
    rows = _rows(producer)
    product = [row for row in rows if row["reason"] == "whole_product_not_molecular_identity"]
    tuber = [row for row in rows if row["reason"] != "whole_product_not_molecular_identity"]
    assert len(product) == 12 and len(tuber) == 3
    assert {row["candidate_target"] for row in tuber} == {"CAS-RN:93348-51-7", "cas:93348-51-7"}
    assert {row["candidate_target"] for row in product} == {TARGET, "CHEBI:16110"}
    assert Counter(row["candidate_route"] for row in product) == {
        audit.UNIFIED_ROLE: 7,
        audit.SUPPORTED_ROLE: 1,
        "micromediaparam_hydrate": 2,
        "micromediaparam_strict": 2,
    }
    assert all(
        json.loads(row["candidate_record"])["extra"] == "literal|pipe"
        for row in product
        if row["candidate_route"].startswith("micromediaparam")
    )


@pytest.mark.parametrize("predicate", ["skos:broadMatch", "skos:narrowMatch", "rdfs:seeAlso"])
def test_nonidentity_candidates_are_not_misreported_as_product_groundings(tmp_path, monkeypatch, predicate):
    """A product hold is not permission to misclassify unrelated parent or annotation evidence."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    rows = [dict(row, predicate_id=predicate) for row in _claims("unified")]
    _mapping_files(tmp_path, unified=rows, supported=[])
    producer.run(show_status=False)
    assert _rows(producer) == []


def test_supported_symlink_retarget_fails_even_for_same_bytes(tmp_path, monkeypatch):
    """The selected canonical evidence locator cannot silently change its physical origin."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    path = _mapping_files(tmp_path)
    one, two = tmp_path / "one.tsv", tmp_path / "two.tsv"
    one.write_bytes(path.read_bytes())
    two.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(one)
    producer.run(show_status=False)
    path.unlink()
    path.symlink_to(two)
    with pytest.raises(Exception, match="changed|binding|resolved|retarget"):
        producer._material_scope_audit.write()


@pytest.mark.usefixtures("local_source_schema")
def test_p3556_finalization_repeat_and_public_admission_keep_original_audit(tmp_path, monkeypatch):
    """Real native closure/finalization retains product-local rows and immutable candidate evidence."""
    from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
    from tests.test_mediadive_recipe_occurrences import _run_transform

    _mapping_files(tmp_path)
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    producer = _run_transform(tmp_path, monkeypatch, {"629": {"recipe": [_saved()["raw"]]}})
    path = producer.output_dir / audit.AUDIT_FILENAME
    before = path.read_bytes()
    identity = producer.producer_audit_snapshots[audit.AUDIT_FILENAME]
    report = producer.finalize(fresh_run=True)
    assert report["producer_audit_members"][audit.AUDIT_FILENAME] == identity
    assert report["audit_members"][audit.AUDIT_FILENAME] == identity
    assert audit.SUPPORTED_ROLE in report["consumed_inputs"]
    assert path.read_bytes() == before
    assert producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    rows = [row for row in graph_rows(producer.output_edge_file) if row.get("source_assertion_id")]
    assert len(rows) == 1 and rows[0]["object"] == "mediadive.ingredient:2082"
    assert json.loads(rows[0]["source_record"]) == _saved()["raw"]


@pytest.mark.parametrize("route", ["identity", "attribute", "canonical_name", "synonym"])
def test_canonical_object_label_candidate_matches_the_actual_reader(tmp_path, monkeypatch, route):
    """All recognized primary routes can index object metadata, without a subject-label match (#1243)."""
    raw = _saved()["raw"]
    row = dict(
        _claims("unified")[0],
        subject_id="MIM:independent-material",
        subject_label="Independent source spelling",
        object_id="CHEBI:16110",
        object_label=raw["compound"],
        comment="",
    )
    if route == "attribute":
        row["subject_id"] = row["object_id"]
    elif route in {"canonical_name", "synonym"}:
        row.update(subject_id="kgm.name:independent-spelling", comment=route)
    producer, path = _producer(tmp_path, monkeypatch, recipes={"629": {"recipe": [raw]}}, legacy=False)
    _mapping_files(tmp_path, unified=[row], supported=[])
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)
    mapping.load_unified_mappings(path)
    assert mapping.find_chebi_by_name(raw["compound"]) == "CHEBI:16110"
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 1
    assert rows[0]["candidate_record"] == audit._json(row)
    assert rows[0]["retained_target"] == "mediadive.ingredient:2082"


def test_subject_and_object_match_is_one_claim_per_original_ordinal(tmp_path, monkeypatch):
    """One row with two applicable labels is not two claims; duplicate source rows still are."""
    raw = _saved()["raw"]
    row = dict(_claims("unified")[-2], subject_label=raw["compound"], object_label=raw["compound"])
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"629": {"recipe": [raw]}}, legacy=False)
    _mapping_files(tmp_path, unified=[row, row], supported=[])
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 2
    assert {item["candidate_record"] for item in rows} == {audit._json(row)}
    assert len({item["candidate_record_locator"] for item in rows}) == 2


def test_canonical_row_subject_only_is_not_a_reader_name_route(tmp_path, monkeypatch):
    """Canonical-name rows use object_label; only synonym rows contribute subject_label."""
    raw = _saved()["raw"]
    row = dict(_claims("unified")[-1], object_id="CHEBI:16110", object_label="Different material")
    producer, path = _producer(tmp_path, monkeypatch, recipes={"629": {"recipe": [raw]}}, legacy=False)
    _mapping_files(tmp_path, unified=[row], supported=[])
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)
    mapping.load_unified_mappings(path)
    assert mapping.find_chebi_by_name(raw["compound"]) is None
    producer.run(show_status=False)
    assert _rows(producer) == []
