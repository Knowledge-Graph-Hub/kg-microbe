"""Hold only two unsupported digest/CID identities while retaining complete observations (#1248)."""

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
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed, ingredient_xref_allowed
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests import test_mediadive_material_scope_audit as audit_tests
from tests.test_consolidate_chemical_mappings import _load_module
from tests.test_mediadive_recipe_occurrences import _resolver, _run_transform
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

FIXTURE = Path(__file__).parent / "resources/mediadive/peptone_scope.json"
TARGETS = ("pubchem.compound:167312541", "PubChem:167312541")
NAMES = ("Soy peptone", "Vitamin-free casamino acids")


def _saved():
    """Pin the complete original 26-occurrence and ten-claim excerpt."""
    payload = FIXTURE.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "41a556f70cc0ae696d01895371214af7f25bb62c9d7a7b9a73c0fe589fed1fa3"
    return json.loads(payload)


def _recipes():
    """Reconstruct exact original array positions with explicitly synthetic noningredient gaps."""
    result = {}
    for occurrence in _saved()["occurrences"]:
        solution, position = occurrence["source_assertion_id"].split(":", 1)[1].split("#recipe/")
        result[solution] = {
            "recipe": [{"instruction": "synthetic position placeholder"}] * (int(position) - 1) + [occurrence["raw"]]
        }
    return result


def _unified_rows(target=TARGETS[0]):
    """Declare one synthetic target and two stale aliases without endorsing their identity."""
    return [
        _row(
            "kgm.name:authority",
            target,
            audit.PEPTONE_AUTHORITY_LABEL,
            name=audit.PEPTONE_AUTHORITY_LABEL,
            comment="canonical_name",
        ),
        *[
            _row(
                "kgm.name:" + str(index),
                target,
                audit.PEPTONE_AUTHORITY_LABEL,
                name=name,
                comment="synonym",
                predicate="skos:closeMatch",
            )
            for index, name in enumerate(NAMES)
        ],
    ]


def _mapping_files(root, rows):
    """Write only tiny test-owned unified claims, not the real mapping artifact."""
    directory = root / "mappings"
    directory.mkdir(exist_ok=True)
    path = directory / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _producer(tmp_path, monkeypatch, *, recipes=None, unified=(), legacy=True, **kwargs):
    """Install full immutable legacy excerpts before the real transform consumes its inputs."""
    original_writer = audit_tests._write_mappings

    def write(root, **ignored):
        """Keep complete original columns/physical rows, including duplicate-name claims."""
        original_writer(root, unified=0, legacy=False)
        path = _mapping_files(root, unified)
        if legacy:
            claims = _saved()["mapping_claims"]
            for name in ("compound_mappings_strict.tsv", "compound_mappings_strict_hydrate.tsv"):
                selected = [item for item in claims if item["input"].endswith("/" + name)]
                (root / "raw" / name).write_bytes(
                    (
                        selected[0]["header_original_line_utf8"]
                        + "".join(item["original_line_utf8"] for item in selected)
                    ).encode()
                )
        return path

    monkeypatch.setattr(audit_tests, "_write_mappings", write)
    return audit_tests._producer(
        tmp_path, monkeypatch, recipes=_recipes() if recipes is None else recipes, legacy=False, **kwargs
    )


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    "name", [*NAMES, " SOY_PEPTONE ", "Soy (peptone)", "Vitamin_free_casamino_acids", " vitamin free casamino acids "]
)
def test_two_name_scopes_hold_all_existing_policy_normalizations(name, target):
    """Legacy namespace and normalization variants cannot resurrect the exact reviewed claims."""
    assert not ingredient_mapping_allowed(name, target)
    assert audit._peptone(name)
    assert ingredient_mapping_allowed(name, "mediadive.ingredient:independent-control")


@pytest.mark.parametrize(
    "name",
    [
        "Peptone",
        "Soytone",
        "Soy protein",
        "Casein",
        "Casamino acids",
        "Soy peptone extract",
        "Vitamin-free casamino acids solution",
        *TARGETS,
        audit.PEPTONE_AUTHORITY_LABEL,
    ],
)
def test_unreviewed_names_and_direct_identifiers_are_not_globally_banned(name):
    """Neither a CID-wide blacklist nor a substring-wide material policy is introduced."""
    assert ingredient_mapping_allowed(name, TARGETS[0])
    assert not audit._peptone(name)
    assert ingredient_xref_allowed(TARGETS[1], TARGETS[0])


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("synonyms", [True, False])
def test_actual_cold_reader_rejects_stale_names_and_retains_target(tmp_path, monkeypatch, target, synonyms):
    """Both indexes enforce finite exclusions without deleting the declared structure."""
    path = tmp_path / "tiny.tsv"
    _table(path, FIELDS, _unified_rows(target), _metadata())
    monkeypatch.setattr(mapping, "_LOADED", False)
    monkeypatch.setattr(mapping, "_CACHED_PATH", None)
    mapping.load_unified_mappings(path)
    assert all(mapping.find_chebi_by_name(name, synonyms=synonyms) is None for name in NAMES)
    assert mapping.find_chebi_by_name(audit.PEPTONE_AUTHORITY_LABEL, synonyms=synonyms) == target
    assert mapping.get_canonical_name(target) == audit.PEPTONE_AUTHORITY_LABEL


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_every_compound_fallback_and_nested_solution_keeps_local(name, target, route):
    """All old fallback entry points consult the policy, without a new hardcoded material guard."""
    raw = {"compound": name, "compound_id": 75, "amount": 0, "unit": "g", "g_l": 0, "mmol_l": None}
    nested = {"solution": name, "solution_id": 17, "amount": 2, "unit": "ml", "note": False}
    resolver = _resolver({"1": {"recipe": [raw, nested]}})
    if route == "unified":
        resolver.chemical_loader.find_chebi_by_name = lambda query: target
    elif route == "legacy":
        resolver.compound_mappings = {name.lower(): target}
    else:
        # The embedded schema's key is PubChem; its value is the unprefixed CID.
        resolver.compounds_data = {"75": {"compound": name, "PubChem": 167312541}}
    actual = resolver.get_solution_recipe_occurrences("1")
    assert [item["id"] for item in actual] == ["mediadive.ingredient:75", "mediadive.solution:17"]
    assert [json.loads(item["source_record"]) for item in actual] == [raw, nested]
    assert actual[0]["amount"] == actual[0]["g_l"] == 0 and actual[0]["mmol_l"] is None
    assert resolver.standardize_compound_id("75", name, source_record=raw) == "mediadive.ingredient:75"


@pytest.mark.parametrize("name", [*TARGETS, "Unrelated material"])
def test_explicit_cid_and_other_name_fallbacks_remain_unchanged(name):
    """An available unrelated route is not suppressed by the two-name source audit profile."""
    resolver = _resolver({})
    resolver.compound_mappings = {name.lower(): TARGETS[1]}
    assert resolver.standardize_compound_id("7", name) == TARGETS[1]


def test_all26_occurrences_and_all10_legacy_claims_survive(tmp_path, monkeypatch):
    """Eight original soy claims per use and two vitamin-free claims remain losslessly auditable."""
    producer, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    rows = audit_tests._rows(producer)
    assert len(rows) == 202
    expected = {item["source_assertion_id"]: item["raw"] for item in _saved()["occurrences"]}
    claim_rows = [item["row"] for item in _saved()["mapping_claims"]]
    assert Counter(row["retained_target"] for row in rows) == {
        "mediadive.ingredient:75": 200,
        "mediadive.ingredient:654": 2,
    }
    assert {row["reason"] for row in rows} == {audit.PEPTONE_REASON}
    for row in rows:
        assert json.loads(row["source_record"]) == expected[row["source_assertion_id"]]
        assert json.loads(row["candidate_record"]) in claim_rows
        assert row["candidate_target"] == TARGETS[1]
        assert row["source_record_sha256"] == hashlib.sha256(row["source_record"].encode()).hexdigest()
        assert json.loads(row["qualifier_evidence"]) == {
            key: expected[row["source_assertion_id"]][key]
            for key in ("condition", "attribute")
            if key in expected[row["source_assertion_id"]]
        }
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 26
    for edge in edges:
        raw = expected[edge["source_assertion_id"]]
        assert json.loads(edge["source_record"]) == raw
        assert edge["object"] == "mediadive.ingredient:" + str(raw["compound_id"])
        original = next(
            item for item in _saved()["occurrences"] if item["source_assertion_id"] == edge["source_assertion_id"]
        )
        assert edge == dict(original["observed_edge_rows"][0]["row"], object=edge["object"])
    before = (producer.output_dir / audit.AUDIT_FILENAME).read_bytes()
    for identifier in _recipes():
        producer.get_solution_recipe_occurrences(identifier)
    producer._material_scope_audit.write()
    assert (producer.output_dir / audit.AUDIT_FILENAME).read_bytes() == before
    verify_producer_audits(producer)


@pytest.mark.parametrize("route", ["identity", "attribute", "canonical_name", "synonym"])
@pytest.mark.parametrize("target", TARGETS)
def test_audit_collects_only_reader_eligible_held_target_claims(tmp_path, monkeypatch, route, target):
    """Match actual primary-label indexing, not all imported annotations or other targets."""
    row = _row("MIM:independent", target, NAMES[0], name="Other subject spelling")
    if route == "attribute":
        row["subject_id"] = target
    elif route in {"canonical_name", "synonym"}:
        row.update(subject_id="kgm.name:alias", comment=route)
    if route == "synonym":
        row.update(subject_label=NAMES[0], object_label=audit.PEPTONE_AUTHORITY_LABEL)
    unrelated = dict(row, object_id="CHEBI:16110")
    weak = dict(row, predicate_id="skos:broadMatch")
    producer, _ = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [{"compound": NAMES[0], "compound_id": 75}]}},
        unified=[row, row, unrelated, weak],
        legacy=False,
    )
    producer.run(show_status=False)
    rows = audit_tests._rows(producer)
    assert len(rows) == 2 and len({item["candidate_record_locator"] for item in rows}) == 2
    assert all(json.loads(item["candidate_record"]) == row for item in rows)


def test_embedded_target_only_claim_and_independent_replacement_are_preserved(tmp_path, monkeypatch):
    """Do not quarantine an unrelated embedded claim or insist on a local target unnecessarily."""
    embedded = {"compound": NAMES[0], "PubChem": 167312541, "ChEBI": 16110, "note": None, "flag": False}
    producer, _ = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [{"compound": NAMES[0], "compound_id": 75}]}},
        legacy=False,
        embedded={"75": embedded},
        selected="mediadive.ingredient:reviewed-control",
    )
    producer.run(show_status=False)
    rows = audit_tests._rows(producer)
    assert len(rows) == 1 and rows[0]["candidate_target"] == TARGETS[1]
    assert json.loads(rows[0]["candidate_record"]) == embedded
    assert rows[0]["retained_target"] == "mediadive.ingredient:reviewed-control"


def test_repeated_raw_occurrences_are_not_collapsed(tmp_path, monkeypatch):
    """Equal payloads and quantities remain different original source positions."""
    raw = {"compound": NAMES[0], "compound_id": 75, "amount": 0, "unit": "g", "g_l": 0, "mmol_l": None}
    producer, _ = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [raw, copy.deepcopy(raw)]}},
        unified=_unified_rows(),
        legacy=False,
    )
    producer.run(show_status=False)
    rows = audit_tests._rows(producer)
    assert len(rows) == 2 and {row["source_assertion_id"] for row in rows} == {
        "mediadive.solution:1#recipe/1",
        "mediadive.solution:1#recipe/2",
    }
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 2 and all(json.loads(row["source_record"]) == raw for row in edges)
    assert all(float(row["value"]) == float(row["g_l"]) == 0 and row["mmol_l"] == "" for row in edges)


def test_no_current_held_claim_does_not_invent_an_audit_row(tmp_path, monkeypatch):
    """A reviewed name is not itself evidence that a quarantined mapping still exists."""
    producer, _ = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [{"compound": NAMES[0], "compound_id": 75}]}},
        unified=[],
        legacy=False,
    )
    producer.run(show_status=False)
    assert audit_tests._rows(producer) == []
    verify_producer_audits(producer)


@pytest.mark.parametrize("damage", ["missing_rule", "missing_origin", "wrong_origin", "tampered_audit"])
def test_required_policy_and_audit_evidence_never_get_restamped(tmp_path, monkeypatch, damage):
    """The same producer/finalizer authority rules apply to the new finite profile."""
    producer, _ = _producer(tmp_path, monkeypatch)
    if damage == "missing_rule":
        policy = tmp_path / "policy.tsv"
        lines = audit.IDENTITY_POLICY.read_text().splitlines(keepends=True)
        policy.write_text("".join(line for line in lines if "^soy[ _-]+peptone$" not in line))
        monkeypatch.setattr(audit, "IDENTITY_POLICY", policy)
        with pytest.raises(SourceFinalizationRequired, match="holds are missing"):
            producer.run(show_status=False)
        assert not producer.output_edge_file.exists()
        return
    producer.run(show_status=False)
    report = {"consumed_inputs": copy.deepcopy(producer.consumed_input_snapshots)}
    report_path = producer.output_dir / "source_finalization.json"
    audit.verify_recorded_material_inputs(report, report_path)
    if damage == "tampered_audit":
        (producer.output_dir / audit.AUDIT_FILENAME).write_text("replaced")
        with pytest.raises(SourceFinalizationRequired):
            verify_producer_audits(producer)
        return
    if damage == "missing_origin":
        del report["consumed_inputs"][audit.POLICY_ROLE]
    else:
        report["consumed_inputs"][audit.POLICY_ROLE]["path"] = str(tmp_path / "wrong-policy.tsv")
    with pytest.raises(SourceFinalizationRequired, match="input origin"):
        audit.verify_recorded_material_inputs(report, report_path)


@pytest.mark.usefixtures("local_source_schema")
def test_real_finalization_keeps_raw_rows_quantities_and_bound_audit(tmp_path, monkeypatch):
    """Finalization and public admission retain distinct observations and original audit bytes."""
    _mapping_files(tmp_path, _unified_rows())
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    producer = _run_transform(tmp_path, monkeypatch, _recipes())
    path = producer.output_dir / audit.AUDIT_FILENAME
    before, identity = path.read_bytes(), producer.producer_audit_snapshots[audit.AUDIT_FILENAME]
    report = producer.finalize(fresh_run=True)
    assert report["producer_audit_members"][audit.AUDIT_FILENAME] == identity
    assert report["audit_members"][audit.AUDIT_FILENAME] == identity
    assert path.read_bytes() == before and producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    assert {row["object"] for row in graph_rows(producer.output_edge_file) if row.get("source_assertion_id")} == {
        "mediadive.ingredient:75",
        "mediadive.ingredient:654",
    }


def test_tiny_identity_export_is_stable_and_keeps_unrelated_direct_rows(tmp_path, monkeypatch):
    """The existing bounded writer enforces new names without rewriting supported MIM or a real export."""
    module = _load_module()
    metadata = _metadata()
    metadata["curie_map"]["pubchem.compound"] = "https://pubchem.ncbi.nlm.nih.gov/compound/"
    rows = [*_unified_rows(), _row("MIM:unrelated", TARGETS[0], audit.PEPTONE_AUTHORITY_LABEL)]
    source, first, second = (tmp_path / name for name in ("source.tsv", "first.tsv.gz", "second.tsv.gz"))
    _table(source, FIELDS, rows, metadata)
    before = source.read_bytes()
    result = module.refresh_identity_policy(source, first)
    assert result == {"rows_read": 4, "rows_removed": 2, "rows_relabelled": 0}
    assert module.refresh_identity_policy(first, second) == {"rows_read": 2, "rows_removed": 0, "rows_relabelled": 0}
    assert first.read_bytes() == second.read_bytes() and source.read_bytes() == before
