"""Bind finite archived material-name claims without making them active mappings (#1262)."""

import copy
import csv
import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.mediadive import material_scope_audit as audit
from kg_microbe.utils import ingredient_identity as identity
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests import test_mediadive_material_scope_audit as existing

TARGET = "CHEBI:1387"
NAME = "SL10"
NATIVE = "3,4-dihydroxyphenylethyleneglycol"
BASELINE_SHA = "a" * 64


def _catalogue():
    """Provide a tiny explicit synthetic archive, not a replacement production cohort."""
    row = {
        "subject_id": "kgm.name:sl10",
        "subject_label": NAME,
        "predicate_id": "skos:closeMatch",
        "object_id": TARGET,
        "object_label": NATIVE,
        "mapping_justification": "semapv:LexicalMatching",
        "comment": "synonym",
        "source": "fixture|historical",
        "extra_evidence": 'original "literal" | untouched',
    }
    return {
        "version": 1,
        "baseline": {
            "path": "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
            "sha256": BASELINE_SHA,
            "fields": list(row),
        },
        "dispositions": [
            {
                "id": "finite-sl10",
                "target_id": TARGET,
                "authority_label": NATIVE,
                "reason": "material_name_not_native_molecule",
                "evidence_uri": "https://example.org/immutable-fixture",
                "source_names": [NAME],
            }
        ],
        "historical_claims": [{"disposition_id": "finite-sl10", "data_row_ordinal": 42, "row": row}],
    }


def _prepare(
    tmp_path, monkeypatch, *, alternate=None, current=False, duplicate=False, legacy=False, embedded=False, recipes=None
):
    """Exercise real producer input/audit machinery with only unrelated lookup services isolated."""
    catalogue = _catalogue()
    original = catalogue["historical_claims"][0]["row"]
    previous = existing._write_mappings

    def mappings(root, **kwargs):
        """Select ordinary tiny files before the constructor snapshots optional inputs."""
        path = previous(root, unified=0, legacy=legacy)
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(original), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            if current:
                writer.writerows([original] * (2 if duplicate else 1))
        if legacy:
            for filename in (
                existing.mod.MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE,
                existing.mod.MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE,
            ):
                (root / "raw" / filename).write_text(
                    f"original\tmapped\textra\n{NAME}\t{TARGET}\tfull original\n"
                    f"{NAME}\tingredient:1387\tlocal is not a false molecular claim\n"
                )
        return path

    monkeypatch.setattr(existing, "_write_mappings", mappings)
    policy = tmp_path / "identity.tsv"
    policy.write_text(
        "target_id\tauthority_label\tkind\tvalue\treason\n"
        f"{TARGET}\t{NATIVE}\tname_pattern\t(?i)^sl10$\tReviewed fixture pair only\n"
    )
    monkeypatch.setattr(identity, "IDENTITY_POLICY", policy)
    monkeypatch.setattr(audit, "IDENTITY_POLICY", policy)
    identity.ingredient_identity_policy.cache_clear()
    raw = {
        "compound": NAME,
        "compound_id": 1387,
        "amount": 0,
        "unit": "ml",
        "g_l": None,
        "mmol_l": 0,
        "attribute": 'original "quote" | pipe',
        "optional": False,
    }
    nested = {"solution": NAME, "solution_id": 777, "amount": 1.5, "unit": "ml", "note": None}
    source = recipes or {"1": {"recipe": [raw, copy.deepcopy(raw), nested, dict(nested, solution_id=4172)]}}
    producer, mapping = existing._producer(
        tmp_path,
        monkeypatch,
        recipes=source,
        legacy=legacy,
        selected=alternate or TARGET,
        embedded={"1387": {"compound": NAME, "ChEBI": "1387", "PubChem": 999}} if embedded else None,
    )
    path = tmp_path / audit.REVIEWED_PATH
    path.write_text(json.dumps(catalogue))
    return producer, path, catalogue, source, mapping


@pytest.fixture(autouse=True)
def clear_identity_cache():
    """Prevent a tiny test policy from surviving monkeypatch restoration."""
    identity.ingredient_identity_policy.cache_clear()
    yield
    identity.ingredient_identity_policy.cache_clear()


def test_historical_rows_survive_removed_unified_claim_with_exact_raw_occurrences(tmp_path, monkeypatch):
    """Archived evidence is unmistakably historical and every source occurrence remains distinct."""
    producer, path, catalogue, source, _ = _prepare(tmp_path, monkeypatch)
    producer.run(show_status=False)
    rows = existing._rows(producer)
    assert len(rows) == 4
    assert Counter(row["retained_target"] for row in rows) == {
        "mediadive.ingredient:1387": 2,
        "mediadive.solution:777": 1,
        "mediadive.solution:4172": 1,
    }
    for position, row in enumerate(rows, 1):
        assert row["source_assertion_id"] == f"mediadive.solution:1#recipe/{position}"
        assert json.loads(row["source_record"]) == source["1"]["recipe"][position - 1]
        assert row["source_record_sha256"] == hashlib.sha256(row["source_record"].encode()).hexdigest()
        assert json.loads(row["candidate_record"]) == catalogue["historical_claims"][0]["row"]
        assert row["candidate_record_locator"] == f"historical-baseline-sha256={BASELINE_SHA};data-record=42"
        assert row["candidate_route"] == audit.REVIEWED_ROLE
        assert row["candidate_input_path"] == str(path.resolve())
        assert row["candidate_input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert row["disposition"] == "historical_quarantined_grounding_claim"
    with producer.output_edge_file.open() as stream:
        edges = [
            row
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if row.get("source_assertion_id")
        ]
    assert len(edges) == 4
    assert (edges[0]["value"], edges[0]["unit"], edges[0]["g_l"], edges[0]["mmol_l"]) == ("0.0", "ml", "", "0.0")
    assert {
        (row["predicate"], row["relation"], row["primary_knowledge_source"], row["knowledge_level"], row["agent_type"])
        for row in edges
    } == {("biolink:has_part", "BFO:0000051", "infores:mediadive", "observation", "manual_agent")}


def test_current_candidates_and_archived_duplicates_remain_distinct(tmp_path, monkeypatch):
    """Only held target pairs are audited; local legacy and unrelated embedded claims are not false."""
    producer, path, catalogue, _, _ = _prepare(
        tmp_path, monkeypatch, current=True, duplicate=True, legacy=True, embedded=True
    )
    duplicate = copy.deepcopy(catalogue["historical_claims"][0])
    duplicate["data_row_ordinal"] = 43
    catalogue["historical_claims"].append(duplicate)
    path.write_text(json.dumps(catalogue))
    producer.run(show_status=False)
    rows = existing._rows(producer)
    assert Counter(row["candidate_route"] for row in rows) == {
        audit.REVIEWED_ROLE: 8,
        audit.UNIFIED_ROLE: 8,
        "micromediaparam_strict": 4,
        "micromediaparam_hydrate": 4,
        "mediadive_compounds": 2,
    }
    assert {row["candidate_target"] for row in rows} == {TARGET}
    assert len(
        {(row["source_assertion_id"], row["candidate_route"], row["candidate_record_locator"]) for row in rows}
    ) == len(rows)


def test_independently_available_alternative_is_not_a_name_wide_hold(tmp_path, monkeypatch):
    """The audit retains the actual alternate selection without declaring new scientific approval."""
    producer, _, _, _, _ = _prepare(tmp_path, monkeypatch, alternate="CHEBI:2")
    producer.run(show_status=False)
    assert {row["retained_target"] for row in existing._rows(producer)} == {"CHEBI:2"}


@pytest.mark.parametrize(
    "damage",
    [
        "version",
        "unknown",
        "baseline_path",
        "baseline_hash",
        "fields",
        "null",
        "ordinal_zero",
        "ordinal_duplicate",
        "disposition_duplicate",
        "target",
        "route",
        "name",
        "orphan",
        "ambiguous_name",
    ],
)
def test_malformed_catalogue_cannot_reach_graph_output(tmp_path, monkeypatch, damage):
    """Finite evidence has no malformed-row, duplicate-key or unreviewed association escape."""
    producer, path, catalogue, _, _ = _prepare(tmp_path, monkeypatch)
    claim = catalogue["historical_claims"][0]
    if damage == "version":
        catalogue["version"] = True
    elif damage == "unknown":
        catalogue["guess_replacement"] = TARGET
    elif damage == "baseline_path":
        catalogue["baseline"]["path"] = "../unreviewed.gz"
    elif damage == "baseline_hash":
        catalogue["baseline"]["sha256"] = "invalid"
    elif damage == "fields":
        catalogue["baseline"]["fields"].append("missing_cell")
    elif damage == "null":
        claim["row"]["source"] = None
    elif damage == "ordinal_zero":
        claim["data_row_ordinal"] = 0
    elif damage == "ordinal_duplicate":
        catalogue["historical_claims"].append(copy.deepcopy(claim))
    elif damage == "disposition_duplicate":
        catalogue["dispositions"].append(copy.deepcopy(catalogue["dispositions"][0]))
    elif damage == "target":
        claim["row"]["object_id"] = "CHEBI:2"
    elif damage == "route":
        claim["row"]["predicate_id"] = "skos:broadMatch"
    elif damage == "name":
        claim["row"]["subject_label"] = "Other name"
    elif damage == "orphan":
        catalogue["historical_claims"] = []
    else:
        catalogue["dispositions"].append(dict(catalogue["dispositions"][0], id="other", target_id="CHEBI:2"))
    path.write_text(json.dumps(catalogue))
    with pytest.raises(SourceFinalizationRequired, match="catalogue"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


def test_duplicate_json_keys_are_rejected():
    """Object parsing cannot silently replace evidence before validation."""
    with pytest.raises(SourceFinalizationRequired, match="Duplicate"):
        audit._reviewed_catalogue(io.StringIO('{"version":1,"version":1}'))


@pytest.mark.parametrize("damage", ["missing_policy", "wrong_native_label", "cached_permission"])
def test_selected_policy_must_agree_with_actual_bytes_and_runtime(tmp_path, monkeypatch, damage):
    """A stale in-memory policy cannot certify removed or changed on-disk exclusions."""
    producer, _, _, _, _ = _prepare(tmp_path, monkeypatch)
    assert not identity.ingredient_mapping_allowed(NAME, TARGET)
    if damage == "cached_permission":
        monkeypatch.setattr(audit, "ingredient_mapping_allowed", lambda name, target: True)
    elif damage == "missing_policy":
        audit.IDENTITY_POLICY.write_text("target_id\tauthority_label\tkind\tvalue\treason\n")
    else:
        audit.IDENTITY_POLICY.write_text(audit.IDENTITY_POLICY.read_text().replace(NATIVE, "Unrelated molecule"))
    with pytest.raises(SourceFinalizationRequired, match="policy"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


@pytest.mark.parametrize("damage", ["missing", "wrong_origin"])
def test_recorded_catalogue_origin_is_required_even_for_empty_cohort(tmp_path, monkeypatch, damage):
    """No selected claims does not permit silently omitting the selection catalogue read."""
    producer, _, _, _, _ = _prepare(tmp_path, monkeypatch, recipes={"1": {"recipe": []}})
    producer.run(show_status=False)
    assert existing._rows(producer) == []
    report = {"consumed_inputs": producer.consumed_input_snapshots}
    audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")
    if damage == "missing":
        del report["consumed_inputs"][audit.REVIEWED_ROLE]
    else:
        report["consumed_inputs"][audit.REVIEWED_ROLE]["path"] = str(tmp_path / "lookalike.json")
    with pytest.raises(SourceFinalizationRequired, match="input origin"):
        audit.verify_recorded_material_inputs(report, producer.output_dir / "source_finalization.json")


@pytest.mark.parametrize("damage", ["bytes", "symlink"])
def test_catalogue_drift_cannot_republish_audit(tmp_path, monkeypatch, damage):
    """Original lexical and content identity are guarded through producer publication."""
    producer, path, _, _, _ = _prepare(tmp_path, monkeypatch)
    original = path.with_name("original.json")
    original.write_bytes(path.read_bytes())
    if damage == "symlink":
        path.unlink()
        path.symlink_to(original)
    producer.run(show_status=False)
    if damage == "bytes":
        path.write_text(path.read_text() + "\n")
    else:
        replacement = path.with_name("same-bytes.json")
        replacement.write_bytes(original.read_bytes())
        path.unlink()
        path.symlink_to(replacement)
    with pytest.raises(SourceFinalizationRequired):
        producer._material_scope_audit.write()


def test_original_289_occurrences_preserve_quantities_and_seven_distinct_nested_solutions(tmp_path, monkeypatch):
    """Replay only the immutable reviewed cohort through the real writer and finite audit."""
    resource = Path(__file__).parent / "resources/mediadive/material_aliases_1262.json"
    payload = resource.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "e6db6174173a12101875104c33478f1868f4454ddd296db8e46b47ab6119f126"
    evidence = json.loads(payload)
    recipes, expected = {}, {}
    for item in evidence["occurrences"]:
        identifier, position = item["source_assertion_id"].removeprefix("mediadive.solution:").split("#recipe/")
        recipe = recipes.setdefault(identifier, {"recipe": []})["recipe"]
        while len(recipe) < int(position):
            recipe.append({"instruction": "synthetic ordinal placeholder"})
        recipe[int(position) - 1] = item["raw"]
        expected[item["source_assertion_id"]] = item
    producer, _ = existing._producer(tmp_path, monkeypatch, recipes=recipes, unified=0, legacy=False)
    catalogue = json.loads((tmp_path / audit.REVIEWED_PATH).read_text())
    targets = {
        audit.normalize_name(name): decision["target_id"]
        for decision in catalogue["dispositions"]
        for name in decision["source_names"]
    }
    producer.chemical_loader.find_chebi_by_name = lambda name: targets.get(audit.normalize_name(name))
    producer.run(show_status=False)
    rows = existing._rows(producer)
    assert {row["source_assertion_id"] for row in rows} == set(expected)
    claims = {claim["data_row_ordinal"]: claim["row"] for claim in catalogue["historical_claims"]}
    for row in rows:
        original = expected[row["source_assertion_id"]]
        assert json.loads(row["source_record"]) == original["raw"]
        assert row["retained_target"] == original["local_identity"]
        assert row["candidate_input_path"] == str((tmp_path / audit.REVIEWED_PATH).resolve())
        ordinal = int(row["candidate_record_locator"].split(";data-record=")[1])
        assert json.loads(row["candidate_record"]) == claims[ordinal]
    with producer.output_edge_file.open() as stream:
        # This is the producer's pre-finalization CSV-quoted TSV, not the
        # finalizer's canonical QUOTE_NONE output saved in the source fixture.
        edges = {
            row["source_assertion_id"]: row
            for row in csv.DictReader(stream, delimiter="\t")
            if row.get("source_assertion_id")
        }
    assert len(edges) == len(expected) == 289
    for assertion, current in edges.items():
        original = expected[assertion]
        assert current == dict(original["edge"], object=original["local_identity"])
    nested = {item["local_identity"] for item in expected.values() if item["raw"].get("solution_id") is not None}
    assert nested == {f"mediadive.solution:{identifier}" for identifier in (777, 4172, 1725, 1915, 2804, 3177, 5543)}


@pytest.mark.usefixtures("local_source_schema")
def test_real_finalization_binds_historical_audit_and_catalogue_without_restamping(tmp_path, monkeypatch):
    """Use the real native closure and public source validator for the new audited profile."""
    from kg_microbe.utils.source_finalization import verify_finalized_source_files
    from tests.test_mediadive_recipe_occurrences import _run_transform

    existing._write_mappings(tmp_path, unified=0, legacy=False)
    monkeypatch.setattr(audit, "_repo_root", lambda: tmp_path)
    raw = {"compound": NAME, "compound_id": 1387, "amount": 1, "unit": "ml"}
    producer = _run_transform(tmp_path, monkeypatch, {"1": {"recipe": [raw]}})
    audit_path = producer.output_dir / audit.AUDIT_FILENAME
    original = audit_path.read_bytes()
    identity = producer.producer_audit_snapshots[audit.AUDIT_FILENAME]
    report = producer.finalize(fresh_run=True)
    assert report["producer_audit_members"][audit.AUDIT_FILENAME] == identity
    assert report["audit_members"][audit.AUDIT_FILENAME] == identity
    assert report["consumed_inputs"][audit.REVIEWED_ROLE] == producer.consumed_input_snapshots[audit.REVIEWED_ROLE]
    assert audit_path.read_bytes() == original
    assert producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    del producer._consumed_input_snapshots[audit.REVIEWED_ROLE]
    with pytest.raises(SourceFinalizationRequired, match="material_scope_reviewed_claims"):
        producer.verify_consumed_inputs()


@pytest.mark.parametrize("name", ["SL-10", "SL 10", "SL_10", "SL__--  10"])
def test_exact_associated_policy_separator_forms_retain_historical_evidence(tmp_path, monkeypatch, name):
    """The finite selected policy—not a global identifier blacklist—defines equivalent held spellings."""
    raw = {"compound": name, "compound_id": 1387, "amount": 1, "unit": "ml"}
    producer, _, _, _, _ = _prepare(tmp_path, monkeypatch, recipes={"1": {"recipe": [raw]}})
    audit.IDENTITY_POLICY.write_text(audit.IDENTITY_POLICY.read_text().replace("(?i)^sl10$", "(?i)^sl[ _-]*10$"))
    identity.ingredient_identity_policy.cache_clear()
    producer.run(show_status=False)
    rows = existing._rows(producer)
    assert len(rows) == 1
    assert rows[0]["retained_target"] == "mediadive.ingredient:1387"
    assert json.loads(rows[0]["source_record"]) == raw


@pytest.mark.parametrize("name", ["SL10 extra", "prefix SL10", NATIVE, "Other excluded name"])
def test_unrelated_exclusion_for_same_target_does_not_expand_catalogue(tmp_path, monkeypatch, name):
    """Only patterns covering a saved finite name may select a historical disposition."""
    raw = {"compound": name, "compound_id": 1387, "amount": 1, "unit": "ml"}
    producer, _, _, _, _ = _prepare(tmp_path, monkeypatch, recipes={"1": {"recipe": [raw]}})
    audit.IDENTITY_POLICY.write_text(
        audit.IDENTITY_POLICY.read_text()
        + f"{TARGET}\t{NATIVE}\tname_pattern\t^Other excluded name$\tUnrelated synthetic exclusion\n"
    )
    identity.ingredient_identity_policy.cache_clear()
    producer.run(show_status=False)
    assert existing._rows(producer) == []


def test_ambiguous_policy_association_fails_before_graph_output(tmp_path, monkeypatch):
    """An overlap across two reviewed dispositions cannot pick a winner by row order."""
    producer, path, catalogue, _, _ = _prepare(tmp_path, monkeypatch)
    catalogue["dispositions"].append(
        dict(
            catalogue["dispositions"][0],
            id="second",
            target_id="CHEBI:2",
            authority_label="Native second",
            source_names=["Other saved name"],
        )
    )
    catalogue["historical_claims"].append(
        {
            "disposition_id": "second",
            "data_row_ordinal": 43,
            "row": dict(
                catalogue["historical_claims"][0]["row"], subject_label="Other saved name", object_id="CHEBI:2"
            ),
        }
    )
    path.write_text(json.dumps(catalogue))
    audit.IDENTITY_POLICY.write_text(
        audit.IDENTITY_POLICY.read_text()
        + "CHEBI:2\tNative second\tname_pattern\t^(?:Other saved name|SL10)$\tSynthetic overlapping scope\n"
    )
    identity.ingredient_identity_policy.cache_clear()
    with pytest.raises(SourceFinalizationRequired, match="Ambiguous"):
        producer.run(show_status=False)
    assert not producer.output_edge_file.exists()


@pytest.mark.parametrize("route", ["identity", "attribute", "canonical_name", "synonym"])
def test_current_target_boundary_whitespace_and_duplicate_ordinals_are_retained(tmp_path, monkeypatch, route):
    """Comparison strips exactly what the reader strips, while the original row stays untouched."""
    producer, _, catalogue, _, mapping = _prepare(tmp_path, monkeypatch)
    row = dict(catalogue["historical_claims"][0]["row"], object_id=f" {TARGET} ", object_label=NAME)
    if route in {"identity", "attribute"}:
        row.update(
            subject_id="CHEBI:999" if route == "identity" else TARGET, predicate_id="skos:exactMatch", comment=""
        )
    elif route == "canonical_name":
        row.update(predicate_id="skos:exactMatch", comment="canonical_name")
    with gzip.open(mapping, "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerows([row, row])
    producer.run(show_status=False)
    current = [item for item in existing._rows(producer) if item["candidate_route"] == audit.UNIFIED_ROLE]
    assert len(current) == 8
    assert all(
        json.loads(item["candidate_record"]) == row and item["candidate_target"] == row["object_id"] for item in current
    )
    assert len({(item["source_assertion_id"], item["candidate_record_locator"]) for item in current}) == 8
