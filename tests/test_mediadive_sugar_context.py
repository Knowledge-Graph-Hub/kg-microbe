"""Preserve the explicitly qualified mixed-sugar stock without changing generic Sugar (#1245)."""

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
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests import test_mediadive_material_scope_audit as audit_tests
from tests.test_mediadive_material_scope_audit import _producer, _rows
from tests.test_mediadive_recipe_occurrences import _resolver

FIXTURE = Path(__file__).parent / "resources/mediadive/sugar_context.json"
POLICY = Path(__file__).resolve().parents[1] / audit.CONTEXT_POLICY
TARGET = "NCIT:C71939"


def _saved():
    """Read exact saved raw and full imported evidence, not a live endpoint or mapping table."""
    payload = FIXTURE.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "09784226fecea0f2b8fc5b3d80748c5a58031c0aa3398e60c292c53a2ff9202f"
    return json.loads(payload)


def _claims(table):
    """Select full immutable native mapping rows without interpreting identity."""
    return [item["row"] for item in _saved()["mapping_claims"] if item["table"] == table]


def _files(root, *, unified=None, supported=None):
    """Create ordinary tiny selected inputs at canonical locations in the test repository."""
    directory = root / "mappings"
    directory.mkdir(exist_ok=True)
    context = root / audit.CONTEXT_POLICY
    context.parent.mkdir(exist_ok=True)
    context.write_bytes(POLICY.read_bytes())
    for table, filename, data in (
        (
            "unified",
            "kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
            _claims("unified") if unified is None else unified,
        ),
        ("supported", "ingredient_mappings.sssom.tsv", _claims("supported") if supported is None else supported),
    ):
        path = directory / filename
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, tuple(_claims(table)[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)
    return context


@pytest.mark.parametrize("kind", ["compound", "solution"])
@pytest.mark.parametrize("target", [TARGET, "CHEBI:17992", "CAS-RN:57-50-1", "KEGG:C00089", "PubChem:5988"])
def test_reviewed_context_wins_all_candidate_targets_without_inventing_components(kind, target):
    """Source context wins before all candidates, retaining original quantity and no inferred components."""
    raw = _saved()["raw"]
    if kind == "solution":
        raw["solution"] = raw.pop("compound")
        raw["solution_id"] = raw.pop("compound_id")
    transform = _resolver({"4338": {"recipe": [raw]}})
    calls = []
    transform.chemical_loader.find_chebi_by_name = lambda name: calls.append(name) or target
    transform.compound_mappings = {"sugar": target}
    transform.compounds_data = {
        "1795": {"ChEBI": "17992", "KEGG-Compound": "C00089", "PubChem": 5988, "CAS-RN": "57-50-1"}
    }
    actual = transform.get_solution_recipe_occurrences("4338")
    assert len(actual) == 1 and calls == []
    assert actual[0]["id"] == f"mediadive.{'ingredient' if kind == 'compound' else 'solution'}:1795"
    assert (actual[0]["amount"], actual[0]["unit"], actual[0]["g_l"], actual[0]["mmol_l"]) == (0.1, "ml", None, None)
    assert json.loads(actual[0]["source_record"]) == raw


@pytest.mark.parametrize(
    "name,attribute,held",
    [
        ("Sugar", audit.SUGAR_ATTRIBUTE, True),
        ("  SUGAR  ", " 250  mM each of xylose, maltose AND cellobiose ", True),
        ("Sugar", None, False),
        ("Sugar", "", False),
        ("Sugar", "250 mM xylose", False),
        ("Sugar", audit.SUGAR_ATTRIBUTE + ".", False),
        ("S.u.g.a.r", audit.SUGAR_ATTRIBUTE, False),
        ("Sucrose", audit.SUGAR_ATTRIBUTE, False),
        ("Food Sugar", audit.SUGAR_ATTRIBUTE, False),
    ],
)
def test_exact_case_whitespace_scope_not_ingredient_id_or_generic_name(name, attribute, held):
    """Other qualifiers and spellings remain ordinary lookup routes, including unrelated food context."""
    raw = dict(_saved()["raw"], compound=name, attribute=attribute)
    transform = _resolver({"1": {"recipe": [raw]}})
    transform.chemical_loader.find_chebi_by_name = lambda _: TARGET
    expected = "mediadive.ingredient:1795" if held else TARGET
    assert transform.get_solution_recipe_occurrences("1")[0]["id"] == expected


def test_direct_call_does_not_borrow_embedded_qualifier_when_occurrence_supplied():
    """Explicit empty and differently qualified occurrence evidence outranks cached compound context."""
    transform = _resolver({})
    transform.compounds_data = {"1795": dict(_saved()["raw"], ChEBI="17992")}
    transform.chemical_loader.find_chebi_by_name = lambda _: TARGET
    assert transform.standardize_compound_id("1795", "Sugar") == "mediadive.ingredient:1795"
    for raw in ({}, {"compound": "Sugar"}, {"compound": "Sugar", "attribute": "food sweetener"}):
        assert transform.standardize_compound_id("1795", "Sugar", source_record=raw) == TARGET


def test_actual_writer_binds_new_policy_and_full_original_claims(tmp_path, monkeypatch):
    """Preserve the reviewed raw-list ordinal, full candidates, source amount and seven-field profile."""
    raw = _saved()["raw"]
    recipe = [{"instruction": "synthetic ordinal placeholder"}] * 15 + [raw]
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"4338": {"recipe": recipe}}, legacy=False, selected=TARGET)
    policy = _files(tmp_path)
    supported = tmp_path / "mappings/ingredient_mappings.sssom.tsv"
    supported_before = supported.read_bytes()
    producer.run(show_status=False)
    actual = _rows(producer)
    assert len(actual) == 3
    originals = Counter(audit._json(row) for row in _claims("unified") + _claims("supported"))
    assert Counter(row["candidate_record"] for row in actual) == originals
    assert audit.POLICY_ROLE not in producer.consumed_input_snapshots
    for row in actual:
        assert row["policy_input_path"] == str(policy.resolve())
        assert row["policy_input_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
        assert row["source_assertion_id"] == _saved()["source_assertion_id"]
        assert json.loads(row["source_record"]) == raw and "CAS-RN" not in raw
        assert row["retained_target"] == "mediadive.ingredient:1795"
        assert row["reason"] == audit.SUGAR_REASON and row["authority_uri"] == audit.SUGAR_URI
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 1
    edge = edges[0]
    assert (
        edge["subject"],
        edge["predicate"],
        edge["object"],
        edge["relation"],
        edge["primary_knowledge_source"],
        edge["knowledge_level"],
        edge["agent_type"],
    ) == (
        "mediadive.solution:4338",
        "biolink:has_part",
        "mediadive.ingredient:1795",
        "BFO:0000051",
        "infores:mediadive",
        "observation",
        "manual_agent",
    )
    assert (edge["value"], edge["unit"], edge["g_l"], edge["mmol_l"]) == ("0.1", "ml", "", "")
    with producer.output_node_file.open() as stream:
        nodes = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    node = next(row for row in nodes if row["id"] == "mediadive.ingredient:1795")
    assert (node["name"], node["category"], node["provided_by"]) == (
        "Sugar",
        "biolink:ChemicalEntity",
        "infores:mediadive",
    )
    assert not node["xref"] and not node["synonym"]
    assert supported.read_bytes() == supported_before
    verify_producer_audits(producer)


def test_actual_reader_generic_sugar_identity_still_available(tmp_path, monkeypatch):
    """The source-context fix is not a global NCIT/Sugar or immutable MIM exclusion."""
    _files(tmp_path)
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)
    mapping.load_unified_mappings(tmp_path / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz")
    assert mapping.find_chebi_by_name("Sugar") == TARGET
    assert mapping.find_chebi_by_xref("MIM:Sugar") == TARGET


@pytest.mark.parametrize("removed", [False, True])
def test_removed_candidates_keep_original_supported_or_header_only(tmp_path, monkeypatch, removed):
    """Absent candidates do not erase selected-context policy or invent grounded identities."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _files(tmp_path, unified=[], supported=[] if removed else None)
    producer.run(show_status=False)
    assert len(_rows(producer)) == (0 if removed else 1)
    assert audit.CONTEXT_ROLE in producer.consumed_input_snapshots
    assert audit.SUPPORTED_ROLE in producer.consumed_input_snapshots
    verify_producer_audits(producer)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "source_name",
        "source_attribute",
        "disposition",
        "reason",
        "evidence_uri",
        "withheld_target_example",
    ],
)
def test_missing_or_changed_selected_context_policy_fails_before_output(tmp_path, monkeypatch, damage):
    """A missing reviewed decision is never silently adopted as a new source rule."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    policy = _files(tmp_path)
    if damage == "missing":
        policy.unlink()
    else:
        with policy.open() as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields, rows = reader.fieldnames, list(reader)
        if damage == "duplicate":
            rows.append(dict(rows[0]))
        else:
            rows[0][damage] = "wrong"
        with policy.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    with pytest.raises((FileNotFoundError, SourceFinalizationRequired, ValueError), match="Sugar|Missing|missing"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_context_drift_and_same_byte_symlink_retarget_cannot_publish_audit(tmp_path, monkeypatch):
    """Selected origin and bytes remain guarded after the exact record has been resolved."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    policy = _files(tmp_path)
    first, second = tmp_path / "first.tsv", tmp_path / "second.tsv"
    first.write_bytes(policy.read_bytes())
    second.write_bytes(policy.read_bytes())
    policy.unlink()
    policy.symlink_to(first)
    producer.run(show_status=False)
    policy.unlink()
    policy.symlink_to(second)
    with pytest.raises(Exception, match="changed|binding|resolved|retarget"):
        producer._material_scope_audit.write()


@pytest.mark.parametrize("role", [audit.CONTEXT_ROLE, audit.SUPPORTED_ROLE])
def test_public_origin_verifier_requires_actual_policy_and_supported_roles(tmp_path, monkeypatch, role):
    """A generic ingredient policy or wrong MIM locator cannot masquerade as the context decision."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _files(tmp_path)
    producer.run(show_status=False)
    report = {"consumed_inputs": copy.deepcopy(producer.consumed_input_snapshots)}
    report["consumed_inputs"][role]["path"] = "/wrong/context-or-supported-file"
    with pytest.raises(SourceFinalizationRequired, match="origin"):
        audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")


@pytest.mark.usefixtures("local_source_schema")
def test_real_finalization_repeat_and_public_admission_preserve_context_audit(tmp_path, monkeypatch):
    """Validate a tiny actual graph and finalized audit through normal admission, without live data."""
    from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
    from tests.test_mediadive_recipe_occurrences import _run_transform

    policy = _files(tmp_path)
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    producer = _run_transform(tmp_path, monkeypatch, {"4338": {"recipe": [_saved()["raw"]]}})
    before = (producer.output_dir / audit.AUDIT_FILENAME).read_bytes()
    report = producer.finalize(fresh_run=True)
    assert report["consumed_inputs"][audit.CONTEXT_ROLE]["path"] == str(policy.resolve())
    assert producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    assert (producer.output_dir / audit.AUDIT_FILENAME).read_bytes() == before
    edges = [row for row in graph_rows(producer.output_edge_file) if row.get("source_assertion_id")]
    assert len(edges) == 1 and edges[0]["object"] == "mediadive.ingredient:1795"
    assert json.loads(edges[0]["source_record"]) == _saved()["raw"]


@pytest.mark.parametrize("route", ["unified", "legacy", "ChEBI", "KEGG-Compound", "PubChem", "CAS-RN"])
@pytest.mark.parametrize("held", [True, False])
def test_each_original_fallback_is_protected_only_for_qualified_occurrence(route, held):
    """An alternative namespace cannot evade context, while the original ordinary fallback stays available."""
    transform = _resolver({})
    transform.compounds_data = {"1795": dict(_saved()["raw"])}
    if route == "unified":
        transform.chemical_loader.find_chebi_by_name = lambda _: TARGET
        expected = TARGET
    elif route == "legacy":
        transform.compound_mappings["sugar"] = TARGET
        expected = TARGET
    else:
        literal, expected = {
            "ChEBI": ("17992", "CHEBI:17992"),
            "KEGG-Compound": ("C00089", "KEGG:C00089"),
            "PubChem": (5988, "PubChem:5988"),
            "CAS-RN": ("57-50-1", "CAS-RN:57-50-1"),
        }[route]
        transform.compounds_data["1795"][route] = literal
    actual = transform.standardize_compound_id("1795", "Sugar", source_record=_saved()["raw"] if held else {})
    assert actual == ("mediadive.ingredient:1795" if held else expected)


def test_mixed_occurrences_and_duplicate_original_candidate_rows_stay_separate(tmp_path, monkeypatch):
    """Same compound ID and repeated recipe order cannot transfer qualifiers or merge source records."""
    original_write = audit_tests._write_mappings

    def selected_legacy(root, **kwargs):
        """Install duplicate original legacy rows before ordinary optional-input selection."""
        path = original_write(root, **kwargs)
        for filename in (
            audit_tests.mod.MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE,
            audit_tests.mod.MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE,
        ):
            with (root / "raw" / filename).open("a") as stream:
                stream.write('Sugar\tNCIT:C71939\toriginal legacy\t"full|claim"\n' * 2)
        return path

    monkeypatch.setattr(audit_tests, "_write_mappings", selected_legacy)
    qualified = _saved()["raw"]
    unqualified = dict(qualified)
    unqualified.pop("attribute")
    another = dict(qualified, amount=0, optional=False, nullable=None)
    producer, _ = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [qualified, unqualified, another]}},
        embedded={"1795": dict(qualified, **{"CAS-RN": "57-50-1"})},
        selected=TARGET,
    )
    _files(tmp_path, unified=[*_claims("unified"), _claims("unified")[0]])
    producer.run(show_status=False)
    rows = _rows(producer)
    assert len(rows) == 18  # 3 unified + 1 supported + 4 legacy + 1 real embedded, on two occurrences.
    assert Counter(row["source_assertion_id"] for row in rows) == {
        "mediadive.solution:1#recipe/1": 9,
        "mediadive.solution:1#recipe/3": 9,
    }
    assert all(row["retained_target"] == "mediadive.ingredient:1795" for row in rows)
    assert (
        len({(row["source_assertion_id"], row["candidate_route"], row["candidate_record_locator"]) for row in rows})
        == 18
    )
    assert all("CAS-RN" not in json.loads(row["source_record"]) for row in rows)
    assert {
        json.loads(row["candidate_record"])["extra"] for row in rows if row["candidate_route"].startswith("micromedia")
    } == {"full|claim"}
    occurrences = producer.get_solution_recipe_occurrences("1")
    assert [row["id"] for row in occurrences] == ["mediadive.ingredient:1795", TARGET, "mediadive.ingredient:1795"]
    assert json.loads(occurrences[-1]["source_record"]) == another


@pytest.mark.parametrize("role", [audit.CONTEXT_ROLE, audit.SUPPORTED_ROLE])
def test_header_only_selected_context_cannot_drop_required_origin(tmp_path, monkeypatch, role):
    """No remaining imported claim still requires the producer's actual selected decision input."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _files(tmp_path, unified=[], supported=[])
    producer.run(show_status=False)
    assert _rows(producer) == []
    snapshots = copy.deepcopy(producer.consumed_input_snapshots)
    report = {"consumed_inputs": snapshots, "inputs": list(copy.deepcopy(snapshots).values())}
    snapshots.pop(role)
    with pytest.raises(SourceFinalizationRequired, match="origin"):
        audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")


def test_unrelated_context_does_not_require_sugar_decision_or_supported_input(tmp_path, monkeypatch):
    """Ordinary unqualified Sugar does not acquire a source-specific hold or new audit dependency."""
    raw = {"compound": "Sugar", "compound_id": 1795, "amount": 1, "unit": "g"}
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [raw]}}, legacy=False, selected=TARGET)
    producer.run(show_status=False)
    assert _rows(producer) == []
    assert audit.CONTEXT_ROLE not in producer.consumed_input_snapshots
    assert audit.SUPPORTED_ROLE not in producer.consumed_input_snapshots


@pytest.mark.parametrize("route", ["identity", "attribute", "canonical_name", "synonym"])
def test_sugar_candidate_object_metadata_and_duplicate_locators(tmp_path, monkeypatch, route):
    """All four eligible object-label routes remain auditable without claiming lookups were attempted."""
    row = dict(
        _claims("unified")[0], subject_id="MIM:other", subject_label="Different spelling", object_id="CHEBI:17992"
    )
    if route == "attribute":
        row["subject_id"] = row["object_id"]
    if route in {"canonical_name", "synonym"}:
        row.update(subject_id="kgm.name:other", comment=route)
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _files(tmp_path, unified=[row, row], supported=[])
    producer.run(show_status=False)
    actual = _rows(producer)
    assert len(actual) == 2
    assert len({item["candidate_record_locator"] for item in actual}) == 2
    assert all(json.loads(item["candidate_record"]) == row for item in actual)


@pytest.mark.parametrize("predicate", ["skos:broadMatch", "skos:narrowMatch", "rdfs:seeAlso"])
def test_sugar_does_not_turn_weak_or_annotation_rows_into_identity_candidates(tmp_path, monkeypatch, predicate):
    """Matching source display does not change the scientific relation of an original row."""
    producer, _ = _producer(tmp_path, monkeypatch, recipes={"1": {"recipe": [_saved()["raw"]]}}, legacy=False)
    _files(tmp_path, unified=[dict(row, predicate_id=predicate) for row in _claims("unified")], supported=[])
    producer.run(show_status=False)
    assert _rows(producer) == []


def test_three_material_profiles_keep_their_actual_policy_origins(tmp_path, monkeypatch):
    """Sugar never labels its decision as the preexisting P3556/Potato identity exclusions."""
    pc = json.loads(FIXTURE.with_name("p3556_scope.json").read_text())
    potato = json.loads(FIXTURE.with_name("potato_scope.json").read_text())
    recipes = {"1": {"recipe": [_saved()["raw"], pc["raw"], {"compound": "Potato", "compound_id": 1606}]}}
    producer, _ = _producer(tmp_path, monkeypatch, recipes=recipes, legacy=False)
    _files(
        tmp_path,
        unified=[
            *_claims("unified"),
            *(item["row"] for item in pc["mapping_claims"] if item["table"] == "unified"),
            potato["mapping_claims"]["unified"]["row"],
        ],
        supported=[
            *_claims("supported"),
            *(item["row"] for item in pc["mapping_claims"] if item["table"] == "supported"),
        ],
    )
    producer.run(show_status=False)
    actual = _rows(producer)
    assert len(actual) == 12  # three Sugar, eight P3556, one Potato original.
    for row in actual:
        selected = tmp_path / audit.CONTEXT_POLICY if row["reason"] == audit.SUGAR_REASON else audit.IDENTITY_POLICY
        assert row["policy_input_path"] == str(selected.resolve())
        assert row["policy_input_sha256"] == hashlib.sha256(selected.read_bytes()).hexdigest()
