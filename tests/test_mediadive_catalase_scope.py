"""Keep all native Catalase reagent observations without asserting human CAT identity (#1290)."""

import copy
import csv
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils import ingredient_context as context
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from scripts import consolidate_chemical_mappings as consolidation
from scripts import mim_conservative_refresh as refresh
from tests import test_mediadive_material_scope_audit as material
from tests import test_mim_conservative_refresh as candidate
from tests.test_mim_conservative_refresh import inputs as candidate_inputs
from tests.test_mim_reviewed_release import bundle as release_bundle

inputs = candidate_inputs
bundle = release_bundle
FIXTURE = Path(__file__).parent / "resources/mediadive/catalase_scope.json"
FIXTURE_SHA256 = "9508981c607e26e93747c7ef8fd939d6048bbbf398dbcf17a0ca299c2886823d"


def _saved():
    """Require the independently extracted immutable eight-observation native cohort."""
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    return json.loads(raw)


def _producer(tmp_path, monkeypatch, *, records=None, mapped=True, embedded=None):
    """Use actual bulk readers, source occurrence resolver, graph writer and mandatory audit."""
    records = _saved()["occurrences"] if records is None else records
    recipes = {}
    for occurrence in records:
        identifier, position = occurrence["source_assertion_id"].split(":")[1].split("#recipe/")
        # Padding is explicitly synthetic and is ignored by the producer. Every
        # ingredient-bearing item itself is the exact native fixture record.
        recipe = recipes.setdefault(identifier, {"recipe": []})["recipe"]
        while len(recipe) < int(position):
            recipe.append({"instruction": "synthetic noningredient position placeholder"})
        recipe[int(position) - 1] = occurrence["raw"]
    original = material._write_mappings

    def mappings(root, **kwargs):
        """Select the saved native mapping rows or the explicit unmapped control."""
        path = original(root, **kwargs)
        rows = _saved()["native_mapping_rows"] if mapped else []
        with gzip.open(path, "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=candidate.FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return path

    monkeypatch.setattr(material, "_write_mappings", mappings)
    return material._producer(
        tmp_path,
        monkeypatch,
        recipes=recipes,
        legacy=False,
        embedded={"270": _saved()["catalog"]} if embedded is None else embedded,
        selected="NCIT:C61062",
    )


def test_all_eight_native_observations_keep_source_owned_identity_and_full_evidence(tmp_path, monkeypatch):
    """Beef, supplier and unspecified observations retain their own exact quantity/optional evidence."""
    producer, mapping = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    expected = {row["source_assertion_id"]: row["raw"] for row in _saved()["occurrences"]}
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 8
    assert {row["source_assertion_id"]: json.loads(row["source_record"]) for row in edges} == expected
    assert {row["object"] for row in edges} == {"mediadive.ingredient:270"}
    with producer.output_node_file.open() as stream:
        nodes = {row["id"]: row for row in csv.DictReader(stream, delimiter="\t")}
    assert nodes["mediadive.ingredient:270"]["category"] == "biolink:ChemicalEntity"
    assert "NCIT:C61062" not in nodes
    rows = material._rows(producer)
    assert len(rows) == 88  # six historical + four consumed current + one retention per source assertion
    assert {row["source_assertion_id"] for row in rows} == set(expected)
    for row in rows:
        assert json.loads(row["source_record"]) == expected[row["source_assertion_id"]]
        assert row["retained_target"] == "mediadive.ingredient:270"
        assert row["source_record_sha256"] == hashlib.sha256(row["source_record"].encode()).hexdigest()
        assert row["policy_input_sha256"] == context.CONTEXT_SHA256
        if row["candidate_route"] == material.audit.UNIFIED_ROLE:
            assert row["candidate_input_sha256"] == hashlib.sha256(mapping.read_bytes()).hexdigest()
            assert json.loads(row["candidate_record"]) in _saved()["native_mapping_rows"]
        if row["candidate_route"] == context.HISTORICAL_ROLE:
            assert row["disposition"] == "historical_quarantined_grounding_claim"
    retained = [row for row in rows if row["disposition"] == "source_owned_material_retained"]
    assert len(retained) == 8
    verify_producer_audits(producer)


def test_no_current_grounding_candidate_still_preserves_each_observation(tmp_path, monkeypatch):
    """Rebuilding consolidated mappings never makes the actual source observations disappear."""
    producer, _ = _producer(tmp_path, monkeypatch, mapped=False)
    producer.run(show_status=False)
    rows = material._rows(producer)
    assert len(rows) == 56
    assert sum(row["disposition"] == "source_owned_material_retained" for row in rows) == 8


@pytest.mark.parametrize("namespace", [None, "ChEBI", "KEGG-Compound", "PubChem", "CAS-RN"])
def test_unified_legacy_and_every_embedded_route_cannot_replace_actual_catalase(tmp_path, monkeypatch, namespace):
    """Injected stale candidates test route safety; they are not claimed as native evidence."""
    embedded = dict(_saved()["catalog"])
    if namespace:
        embedded[namespace] = "injected-route-control"
    producer, _ = _producer(tmp_path, monkeypatch, embedded={"270": embedded})
    producer.compound_mappings["catalase"] = "NCIT:C61062"
    for occurrence in _saved()["occurrences"]:
        assert producer.standardize_compound_id("270", "Catalase", source_record=occurrence["raw"]) == (
            "mediadive.ingredient:270"
        )
    producer.chemical_loader.find_chebi_by_name = lambda name: None
    assert producer.standardize_compound_id("270", "Catalase") == "mediadive.ingredient:270"


def test_nested_solution_owns_its_identity_and_repeated_list_positions_remain_distinct(tmp_path, monkeypatch):
    """Synthetic nested-route negative controls cannot become catalog compound 270 or a human protein."""
    raw = {"solution_id": 919, "solution": "Catalase", "amount": 1, "unit": "ml"}
    records = [
        {"source_assertion_id": "mediadive.solution:991#recipe/1", "raw": raw},
        {"source_assertion_id": "mediadive.solution:991#recipe/2", "raw": dict(raw)},
    ]
    producer, _ = _producer(tmp_path, monkeypatch, records=records)
    producer.run(show_status=False)
    occurrences = producer.get_solution_recipe_occurrences("991")
    assert len(occurrences) == 2
    assert {row["id"] for row in occurrences} == {"mediadive.solution:919"}
    assert len({row["source_assertion_id"] for row in occurrences}) == 2
    assert {row["retained_target"] for row in material._rows(producer)} == {"mediadive.solution:919"}


@pytest.mark.parametrize(
    "change",
    [
        {"compound": "Unreviewed catalog rename"},
        {"attribute": "human recombinant protein"},
        {"compound_id": None},
        {"compound_id": "0270"},
        {"compound_id": True},
    ],
)
def test_native_catalog_drift_or_noncanonical_identity_cannot_enter_reviewed_scope(change):
    """An exact reviewed policy cannot silently certify a changed qualifier or ID."""
    raw = dict(_saved()["catalog"], **change)
    with pytest.raises(ValueError):
        context.catalase_material(raw, native_id="270")


@pytest.mark.parametrize("file_kind", ["policy", "native"])
def test_exact_policy_and_native_witness_bytes_are_required(file_kind):
    """A syntactically plausible replacement hash does not establish native authority."""
    policy, native = context.CONTEXT_POLICY.read_bytes(), context.NATIVE_AUTHORITY.read_bytes()
    if file_kind == "policy":
        parsed = json.loads(policy)
        parsed["authority_witness_sha256"] = "0" * 64
        policy = json.dumps(parsed).encode()
    else:
        native += b"\n"
    with pytest.raises(ValueError, match="reviewed bytes"):
        context.validate_context_bytes(policy, native)


@pytest.mark.parametrize("damage", ["audit", "source"])
def test_actual_catalase_audit_and_raw_source_are_bound(tmp_path, monkeypatch, damage):
    """A successful source run cannot be restamped after its evidence is changed."""
    producer, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    if damage == "audit":
        path = producer.output_dir / material.audit.AUDIT_FILENAME
        path.write_bytes(path.read_bytes() + b"changed\n")
        with pytest.raises(SourceFinalizationRequired):
            verify_producer_audits(producer)
    else:
        producer.solutions_data["269"]["recipe"][8]["amount"] = 999
        with pytest.raises(SourceFinalizationRequired):
            producer.get_solution_recipe_occurrences("269")


def _load_runtime(path, monkeypatch):
    """Isolate the shared cache from other tests and retain the real row classifier/indexer."""
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)


@pytest.mark.parametrize("project", [False, True])
def test_native_human_metadata_survives_without_ingredient_lexical_xref_or_formula_identity(
    tmp_path, monkeypatch, project
):
    """All four actual native lexical rows are metadata, not general ingredient identities."""
    rows = copy.deepcopy(_saved()["native_mapping_rows"])
    if project:
        rows = [context.contextualize_ingredient_row(row) for row in rows]
    metadata = candidate._metadata()
    metadata["curie_map"]["NCIT"] = "http://purl.obolibrary.org/obo/NCIT_"
    path = tmp_path / "scope.tsv"
    candidate._table(path, candidate.FIELDS, rows, metadata)
    _load_runtime(path, monkeypatch)
    for label in ("Catalase", "CAT", "CAT Protein", "EC 1.11.1.6"):
        assert runtime.find_chebi_by_name(label) is None
    assert runtime.get_canonical_name("NCIT:C61062") == "Catalase"
    assert set(runtime.get_synonyms("NCIT:C61062")) == {"CAT", "CAT Protein", "EC 1.11.1.6"}
    assert runtime.find_chebi_by_xref("NCIT:C61062") is None


def test_identity_only_refresh_preserves_four_native_rows_as_nonidentity_metadata(tmp_path, monkeypatch):
    """The supported rewrite is a fixed point and never changes the original selected artifact."""
    metadata = candidate._metadata()
    metadata["curie_map"]["NCIT"] = "http://purl.obolibrary.org/obo/NCIT_"
    source, first, second = (tmp_path / name for name in ("source.tsv", "first.tsv", "second.tsv"))
    candidate._table(source, candidate.FIELDS, _saved()["native_mapping_rows"], metadata)
    original = source.read_bytes()
    stats = consolidation.refresh_identity_policy(source, first)
    assert stats["rows_context_scoped"] == 4
    assert stats["rows_removed"] == 0
    consolidation.refresh_identity_policy(first, second)
    assert first.read_bytes() == second.read_bytes()
    assert source.read_bytes() == original
    rows = list(refresh._rows(first))
    assert len(rows) == 4
    assert all(context.context_metadata_row(row) for row in rows)
    _load_runtime(first, monkeypatch)
    assert runtime.find_chebi_by_name("Catalase") is None
    assert runtime.get_canonical_name("NCIT:C61062") == "Catalase"


def test_conservative_refresh_preserved_and_rebuilt_native_routes_cannot_reinject_human_identity(inputs, monkeypatch):
    """Current supported candidate generation preserves exact original claims in its quarantine."""
    metadata = candidate._metadata()
    metadata["curie_map"]["NCIT"] = "http://purl.obolibrary.org/obo/NCIT_"
    originals = _saved()["native_mapping_rows"]
    candidate._table(inputs["baseline"], candidate.FIELDS, [*refresh._rows(inputs["baseline"]), *originals], metadata)
    original = inputs["baseline"].read_bytes()
    first = refresh.build_conservative_candidate(**inputs)
    held = [row for row in candidate._read(first.quarantine_path) if row["object_id"] == "NCIT:C61062"]
    assert len(held) == 4
    assert all(row.pop("quarantine_reason") == "ingredient_material_identity_context" for row in held)
    assert held == originals
    assert first.report["counts"]["ingredient_context_scoped_rows"] == 4
    assert inputs["baseline"].read_bytes() == original
    _load_runtime(first.candidate_path, monkeypatch)
    assert runtime.find_chebi_by_name("Catalase") is None
    assert runtime.get_canonical_name("NCIT:C61062") == "Catalase"
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    # Exercise fresh reconstruction separately: its row builder still describes
    # native authority, and the shared insertion gate limits ingredient use.
    evidence = refresh._Evidence(set(metadata["curie_map"]))
    evidence.add("NCIT:C61062", "Catalase", source="native_ontology:ncit", priority=100)
    fresh = list(refresh._fresh_rows("NCIT:C61062", evidence.records["NCIT:C61062"], candidate.FIELDS, "2026-09-30"))
    assert fresh
    assert all(context.context_metadata_row(context.contextualize_ingredient_row(row)) for row in fresh)


def test_conservative_refresh_full_native_rebuild_cannot_reinject_catalase(inputs, monkeypatch):
    """An injected historical component forces the actual current-native reconstruction route."""
    metadata = candidate._metadata()
    metadata["curie_map"]["NCIT"] = "http://purl.obolibrary.org/obo/NCIT_"
    rows = _saved()["native_mapping_rows"]
    # Explicit adversarial control, not a newly alleged native MIM assertion.
    poisoned = dict(rows[2], source="culturebotai_reviewed")
    candidate._table(
        inputs["baseline"], candidate.FIELDS, [*refresh._rows(inputs["baseline"]), *rows, poisoned], metadata
    )
    native = inputs["baseline"].with_name("ncit_nodes.tsv")
    candidate._table(
        native, candidate.NODE_FIELDS, [candidate._node("NCIT:C61062", "Catalase", "CAT|CAT Protein|EC 1.11.1.6")]
    )
    result = refresh.build_conservative_candidate(**dict(inputs, ontology_paths=(*inputs["ontology_paths"], native)))
    scoped = [row for row in candidate._read(result.candidate_path) if row["object_id"] == "NCIT:C61062"]
    assert len(scoped) == 4
    assert all(context.context_metadata_row(row) for row in scoped)
    assert result.report["counts"]["ingredient_context_scoped_rows"] == 4
    _load_runtime(result.candidate_path, monkeypatch)
    assert runtime.find_chebi_by_name("Catalase") is None
    assert runtime.get_canonical_name("NCIT:C61062") == "Catalase"


def test_actual_native_catalase_assays_keep_activity_targets(tmp_path, monkeypatch):
    """All three literal native CAT wells remain enzyme activities, not human-protein ingredients."""
    from kg_microbe.utils.mapping_file_utils import generate_assay_entity_edges, generate_assay_entity_nodes
    from tests.test_assay_reference_repairs import authority, transform

    path = FIXTURE.with_name("catalase_native_assays.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "44a62fad552f0029273ee0b9ac0aaf5bbd159a32dbc69c89d1f8fa743dc32c87"
    )
    assays = json.loads(path.read_bytes())
    producer = transform.__wrapped__(tmp_path)
    native = authority.__wrapped__()
    edges = [
        dict(zip(producer.edge_header, row, strict=True))
        for row in generate_assay_entity_edges(assays, producer.edge_header, go_authority=native)
    ]
    assert sum(row["object"] == "EC:1.11.1.6" for row in edges) == 3
    assert sum(row["object"] == "GO:0004096" for row in edges) == 3
    assert all(row["predicate"] == "MICRO:0001206" for row in edges)
    nodes = {
        row[0]: dict(zip(producer.node_header, row, strict=True))
        for row in generate_assay_entity_nodes(assays, producer.node_header, go_authority=native)
    }
    assert nodes["GO:0004096"]["category"] == "biolink:MolecularActivity"
    assert "NCIT:C61062" not in nodes
