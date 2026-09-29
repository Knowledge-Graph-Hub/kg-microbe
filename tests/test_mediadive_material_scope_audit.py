"""Preserve finite imported potato claims without inventing raw assertions (#1236)."""

import copy
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive import material_scope_audit as audit
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

RESOURCE = Path(__file__).parent / "resources"
FIXTURE = RESOURCE / "mediadive/potato_scope.json"


def _recipes():
    """Reconstruct exact raw positions without inventing a missing historical ingredient."""
    saved = json.loads(FIXTURE.read_text())
    recipes = {}
    for occurrence in saved["occurrences"]:
        identifier, position = occurrence["source_assertion_id"].split(":")[1].split("#recipe/")
        recipes[identifier] = {
            "recipe": [{"instruction": "synthetic noningredient position placeholder"}] * (int(position) - 1)
            + [occurrence["raw"]]
        }
    return recipes


def _write_mappings(root, *, unified=1, legacy=True):
    """Create tiny genuine parser inputs, including duplicate rows and extension columns."""
    mappings = root / "mappings"
    mappings.mkdir()
    row = json.loads(FIXTURE.read_text())["mapping_claims"]["unified"]["row"]
    path = mappings / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        stream.write("# synthetic test snapshot of the saved original row\n")
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerows([row] * unified)
    if legacy:
        for filename in (mod.MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE, mod.MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE):
            (root / "raw" / filename).write_text(
                'original\tmapped\tsource\textra\nPotato\tCAS-RN:93348-51-7\ttest\t"literal|pipe"\n'
            )
    return path


def _producer(tmp_path, monkeypatch, *, recipes=None, unified=1, legacy=True, embedded=None, selected=None):
    """Run the actual bulk readers and producer; replace only unrelated native/lookup services."""
    raw = tmp_path / "raw"
    raw.mkdir()
    recipes = _recipes() if recipes is None else recipes
    mapping_path = _write_mappings(tmp_path, unified=unified, legacy=legacy)
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    medium = {"id": 1, "name": "Scope fixture", "complex_medium": False}
    for field in (
        mod.MEDIADIVE_SOURCE_COLUMN,
        mod.MEDIADIVE_LINK_COLUMN,
        mod.MEDIADIVE_MIN_PH_COLUMN,
        mod.MEDIADIVE_MAX_PH_COLUMN,
        mod.MEDIADIVE_REF_COLUMN,
        mod.MEDIADIVE_DESC_COLUMN,
    ):
        medium[field] = ""
    (raw / "mediadive.json").write_text(json.dumps({"data": [medium]}))
    bulk = raw / "mediadive"
    bulk.mkdir()
    for filename, payload in (
        (
            "media_detailed.json",
            {"1": {"solutions": [{"id": int(key), "name": "Fixture"} for key in recipes]}},
        ),
        ("media_strains.json", {"1": {}}),
        ("solutions.json", recipes),
        ("compounds.json", embedded or {}),
    ):
        (bulk / filename).write_text(json.dumps(payload))
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", RESOURCE / "provenance_serialization")
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_roles", lambda self: None)
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_categories", lambda self: None)
    loader = SimpleNamespace(
        find_chebi_by_name=lambda name: selected,
        get_canonical_name=lambda identifier: "",
        get_node_enrichment=lambda identifier: {"xref": "", "synonym": ""},
        get_parents=lambda identifier: [],
        get_category=lambda identifier: "",
    )
    monkeypatch.setattr(mod, "ChemicalMappingLoader", lambda: loader)
    producer = mod.MediaDiveTransform(raw, tmp_path / "transformed")
    return producer, mapping_path


def _rows(producer):
    """Read the literal producer-owned audit schema."""
    with (producer.output_dir / audit.AUDIT_FILENAME).open() as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        assert tuple(reader.fieldnames) == audit.AUDIT_HEADER
        return list(reader)


def test_nine_original_occurrences_and_full_mapping_candidates_survive(tmp_path, monkeypatch):
    """Six explicit forms and three unqualified records stay distinct from imported CAS claims."""
    producer, mapping = _producer(tmp_path, monkeypatch, unified=2)
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 36  # two distinct unified rows + strict + hydrate, per occurrence
    assert Counter(row["reason"] for row in rows) == {
        "unsupported_material_form_identity": 24,
        "insufficient_material_specificity": 12,
    }
    expected = {row["source_assertion_id"]: row["raw"] for row in json.loads(FIXTURE.read_text())["occurrences"]}
    for row in rows:
        raw = json.loads(row["source_record"])
        assert raw == expected[row["source_assertion_id"]]
        assert "CAS-RN" not in raw
        assert row["retained_target"] == "mediadive.ingredient:1606"
        assert row["source_record_sha256"] == hashlib.sha256(row["source_record"].encode()).hexdigest()
        assert row["disposition"] == "quarantined_grounding_candidate"
        candidate = json.loads(row["candidate_record"])
        if row["candidate_route"] == audit.UNIFIED_ROLE:
            assert candidate == json.loads(FIXTURE.read_text())["mapping_claims"]["unified"]["row"]
            assert row["candidate_input_sha256"] == hashlib.sha256(mapping.read_bytes()).hexdigest()
        else:
            assert candidate["extra"] == "literal|pipe"
    before = (producer.output_dir / audit.AUDIT_FILENAME).read_bytes()
    producer.get_solution_recipe_occurrences("3653")
    producer._material_scope_audit.write()
    assert (producer.output_dir / audit.AUDIT_FILENAME).read_bytes() == before
    verify_producer_audits(producer)
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 9
    assert {row["source_assertion_id"]: json.loads(row["source_record"]) for row in edges} == expected


@pytest.mark.parametrize("kind", ["no_cohort", "no_candidate"])
def test_empty_or_removed_candidate_is_valid_header_only(tmp_path, monkeypatch, kind):
    """Absence of a historical held row must not make valid local observations fail."""
    kwargs = (
        {"recipes": {"1": {"recipe": [{"compound": "Unrelated", "compound_id": 7}]}}} if kind == "no_cohort" else {}
    )
    producer, _ = _producer(tmp_path, monkeypatch, unified=0, legacy=False, **kwargs)
    producer.run(show_status=False)
    assert _rows(producer) == []
    verify_producer_audits(producer)


@pytest.mark.parametrize("recipe", [None, "", {}, 0])
def test_metadata_only_solution_recipe_keeps_existing_empty_behavior(tmp_path, monkeypatch, recipe):
    """The audit does not turn a non-list recipe into a new producer schema requirement."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": recipe}})
    producer.run(show_status=False)
    assert _rows(producer) == []


@pytest.mark.parametrize("predicate", ["skos:broadMatch", "skos:narrowMatch", "rdfs:seeAlso"])
def test_weak_or_annotation_rows_are_not_grounding_candidates(tmp_path, monkeypatch, predicate):
    """Preserve nonidentity semantics instead of relabeling every Potato relation as identity."""
    producer, path = _producer(tmp_path, monkeypatch, legacy=False)
    row = json.loads(FIXTURE.read_text())["mapping_claims"]["unified"]["row"]
    row["predicate_id"] = predicate
    with gzip.open(path, "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
    producer.run(show_status=False)
    assert _rows(producer) == []


def test_actual_embedded_claim_is_preserved_without_inserting_it_in_recipe(tmp_path, monkeypatch):
    """An embedded compound record is its own claim origin, not a recipe field."""
    embedded = {"compound": "Potato", "CAS-RN": "93348-51-7", "note": None, "flag": False}
    producer, _ = _producer(tmp_path, monkeypatch, unified=0, legacy=False, embedded={"1606": embedded})
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 9
    assert {row["candidate_route"] for row in rows} == {"mediadive_compounds"}
    assert all(json.loads(row["candidate_record"]) == embedded for row in rows)
    assert all("CAS-RN" not in json.loads(row["source_record"]) for row in rows)


def test_retained_target_is_actual_independent_selection_not_assumed_local(tmp_path, monkeypatch):
    """The audit does not choose or invent a replacement for a separately selected target."""
    producer, _ = _producer(tmp_path, monkeypatch, selected="mediadive.ingredient:synthetic-reviewed-control")
    producer.run(show_status=False)
    assert {row["retained_target"] for row in _rows(producer)} == {"mediadive.ingredient:synthetic-reviewed-control"}


@pytest.mark.parametrize("damage", ["missing", "malformed", "duplicate_header"])
def test_selected_mapping_evidence_fails_before_graph_output(tmp_path, monkeypatch, damage):
    """Missing or ambiguous current claim evidence cannot be replaced by historical rows."""
    producer, path = _producer(tmp_path, monkeypatch)
    if damage == "missing":
        path.unlink()
    else:
        with gzip.open(path, "wt") as stream:
            stream.write(
                "subject_id\tsubject_label\tobject_id\n"
                if damage == "malformed"
                else "subject_id\tsubject_label\tobject_id\tobject_id\n"
            )
            stream.write("kgm.name:potato\tPotato\n")
    with pytest.raises((SourceFinalizationRequired, FileNotFoundError, ValueError)):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()
    assert producer.producer_audit_snapshots == {}


@pytest.mark.parametrize("damage", ["change", "delete", "symlink"])
def test_audit_bytes_are_bound_at_producer_time(tmp_path, monkeypatch, damage):
    """Generic mandatory-audit checks must reject mutation rather than restamp it."""
    producer, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    path = producer.output_dir / audit.AUDIT_FILENAME
    original = path.read_bytes()
    if damage == "change":
        path.write_bytes(original + b"changed\n")
    else:
        path.unlink()
        if damage == "symlink":
            replacement = tmp_path / "unowned.tsv"
            replacement.write_bytes(original)
            path.symlink_to(replacement)
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(producer)


def test_input_drift_or_repeated_occurrence_drift_never_gets_certified(tmp_path, monkeypatch):
    """Original inputs and occurrence evidence remain bound for the instance lifetime."""
    producer, path = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    original = copy.deepcopy(producer.solutions_data["3653"])
    producer.solutions_data["3653"]["recipe"][0]["amount"] = 999
    with pytest.raises(SourceFinalizationRequired, match="repeated visits"):
        producer.get_solution_recipe_occurrences("3653")
    producer.solutions_data["3653"] = original
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        producer._material_scope_audit.write()


def test_unknown_qualifier_does_not_infer_fresh_material():
    """Scope reasons are finite evidence classifications, not a fuzzy phenotype parser."""
    reason, evidence = audit._reason({"condition": "fresh extract, exact scope unreviewed", "attribute": None})
    assert reason == "insufficient_material_specificity"
    assert json.loads(evidence)["attribute"] is None


@pytest.mark.parametrize("name", ["Pot.ato", "(Potato)", " POTATO "])
def test_policy_equivalent_punctuation_retains_candidate_audit(tmp_path, monkeypatch, name):
    """The collector must not skip labels whose grounding the shared guard rejects."""
    recipes = {"1": {"recipe": [{"compound": name, "compound_id": 1606}]}}
    producer, _ = _producer(tmp_path, monkeypatch, recipes=recipes)
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 3
    assert all(json.loads(row["source_record"])["compound"] == name for row in rows)


@pytest.mark.parametrize("name", ["Potato flour", "Potato extract", "Sweet potato", "potato starch"])
def test_nonbare_material_names_do_not_enter_the_finite_hold(name):
    """No substring-wide potato policy is introduced by auditing."""
    assert not audit._potato(name)


@pytest.mark.parametrize("role", [audit.UNIFIED_ROLE, audit.POLICY_ROLE])
@pytest.mark.parametrize("damage", ["missing", "wrong_origin"])
def test_recorded_claims_require_both_original_evidence_origins(tmp_path, monkeypatch, role, damage):
    """A public source report cannot substitute a same-content arbitrary claim file."""
    producer, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    report = {"consumed_inputs": producer.consumed_input_snapshots}
    report_path = producer.output_dir / "source_finalization.json"
    audit.verify_recorded_material_inputs(report, report_path)
    if damage == "missing":
        del report["consumed_inputs"][role]
    else:
        report["consumed_inputs"][role]["path"] = str(tmp_path / "unreviewed-alias.tsv")
    with pytest.raises(SourceFinalizationRequired, match="input origin"):
        audit.verify_recorded_material_inputs(report, report_path)


def test_missing_policy_row_is_not_hidden_by_reader_cache(tmp_path, monkeypatch):
    """Actual policy bytes must retain the reviewed finite rule even with an old in-memory cache."""
    producer, _ = _producer(tmp_path, monkeypatch)
    policy = tmp_path / "empty-policy.tsv"
    policy.write_text("target_id\tauthority_label\tkind\tvalue\treason\n")
    monkeypatch.setattr(audit, "IDENTITY_POLICY", policy)
    monkeypatch.setattr(audit, "ingredient_mapping_allowed", lambda name, target: False)
    with pytest.raises(SourceFinalizationRequired, match="hold is missing"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_same_byte_unified_symlink_retarget_is_rejected(tmp_path, monkeypatch):
    """Original lexical origins remain guarded independently of equal file payloads."""
    producer, path = _producer(tmp_path, monkeypatch)
    first = path.with_name("original.gz")
    second = path.with_name("substitute.gz")
    first.write_bytes(path.read_bytes())
    second.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(first)
    producer.run(show_status=False)
    path.unlink()
    path.symlink_to(second)
    with pytest.raises(SourceFinalizationRequired, match="locator changed"):
        producer._material_scope_audit.write()


@pytest.mark.usefixtures("local_source_schema")
def test_finalization_repeat_and_public_admission_preserve_exact_audit(tmp_path, monkeypatch):
    """The existing finalization lifecycle carries producer bytes without restamping."""
    from kg_microbe.utils.source_finalization import verify_finalized_source_files
    from tests.test_mediadive_recipe_occurrences import _run_transform

    _write_mappings(tmp_path, legacy=False)
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    producer = _run_transform(tmp_path, monkeypatch, _recipes())
    path = producer.output_dir / audit.AUDIT_FILENAME
    identity = producer.producer_audit_snapshots[audit.AUDIT_FILENAME]
    before = path.read_bytes()
    report = producer.finalize(fresh_run=True)
    assert report["producer_audit_members"][audit.AUDIT_FILENAME] == identity
    assert report["audit_members"][audit.AUDIT_FILENAME] == identity
    assert path.read_bytes() == before
    assert producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
