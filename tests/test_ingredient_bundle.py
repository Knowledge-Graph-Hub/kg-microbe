"""Exercise the actual producer export through KG-Microbe's scoped consumer."""

import csv
import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import chemical_mapping_utils as cmu
from kg_microbe.utils.ingredient_bundle import (
    ReviewedIngredientBundle,
    build_ingredient_lookup_bundle,
    load_ingredient_lookup_bundle,
)
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, content_sha256, safe_member
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.transform_fingerprint import data_fingerprint
from scripts.consolidate_chemical_mappings import ChemicalMappingConsolidator

RESOURCE = Path(__file__).parent / "resources/ingredient_bundle"


@pytest.fixture(scope="module")
def producer_bundle(tmp_path_factory):
    """Unpack immutable bytes exported by the pinned producer commit, never handwritten TSVs."""
    origin = json.loads((RESOURCE / "origin.json").read_text())
    archive = RESOURCE / "reviewed-cases-v1.tar.gz"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == origin["archive_sha256"]
    root = tmp_path_factory.mktemp("producer-ingredient-bundle")
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            assert member.isfile()
            path = safe_member(root, member.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with stream.extractfile(member) as source:
                path.write_bytes(source.read())
    return ReviewedIngredientBundle(root, manifest_sha256=origin["bundle_manifest_sha256"])


@pytest.fixture(autouse=True)
def reset_lookup_cache(monkeypatch):
    """Keep global legacy lookup state independent across tests."""
    monkeypatch.setattr(cmu, "_LOADED", False)
    monkeypatch.setattr(cmu, "_CACHED_PATH", None)
    monkeypatch.setattr(cmu, "_CACHED_DIGEST", None)
    yield
    cmu._LOADED, cmu._CACHED_PATH, cmu._CACHED_DIGEST = False, None, None


@pytest.fixture(scope="module")
def lookup_bundle(producer_bundle, tmp_path_factory):
    """Use the real consolidator to publish explicit native/legacy and scoped inputs."""
    consolidator = ChemicalMappingConsolidator()
    for row in producer_bundle.mappings():
        consolidator.add_chemical(
            row["object_id"], canonical_name=row["object_label"], source="test_declared_native", priority=1
        )
    consolidator.add_chemical("CHEBI:15318", canonical_name="xanthine", source="test_generic_trait", priority=1)
    directory = tmp_path_factory.mktemp("ingredient-lookup") / "candidate"
    receipt = build_ingredient_lookup_bundle(consolidator, producer_bundle, directory)
    return directory, receipt


def test_real_producer_scope_history_and_policy_parity(producer_bundle):
    """Current annotations agree with the existing cases while history remains source qualified."""
    bundle = producer_bundle
    assert bundle.resolve_source("MIM:Rifamycin") == "CHEBI:26580"
    assert bundle.resolve_source("MIM:Rifamycin_Sv") == "CHEBI:29673"
    assert bundle.resolve_source("MIM:Xanthine") == "CHEBI:17712"
    assert bundle.resolve_source("CHEBI:15318") is None
    assert bundle.active_xrefs("CHEBI:26580") == []
    assert bundle.active_xrefs("CHEBI:29673") == ["cas:6998-60-3"]
    assert bundle.active_xrefs("CHEBI:15318") == []
    assert bundle.active_xrefs("CHEBI:17712") == ["cas:69-89-6"]
    assert bundle.active_xrefs("NCIT:C76253") == ["cas:65589-70-0"]
    assert bundle.identifier_owners("cas:8048-52-0") == []
    assert bundle.identifier_owners("cas:8048-52-0", include_history=True) == ["NCIT:C76253"]
    historical = [claim for claim in bundle.identifier_claims("NCIT:C76253") if claim["identifier"] == "cas:8048-52-0"]
    assert {claim["source_status"] for claim in historical} == {"SUPERSEDED", "REPORTED"}
    assert len(bundle.identifier_owners("cas:9048-46-8")) == 2
    assert bundle.policy_parity()["status"] == "PASS"
    audit = bundle.audit()
    assert (audit["mapping_rows"], audit["identifier_claims"], audit["active_identifier_claims"]) == (20, 18, 15)
    assert (audit["retained_product_records"], audit["retained_occurrence_records"]) == (3, 10)
    assert audit["identifier_review_status"] == {"SUPPORTED": 17, "WITHHOLD": 1}


def test_occurrence_context_is_resolved_before_identifier_choice(producer_bundle):
    """A source occurrence cannot be rebound to another generic ingredient."""
    bundle = producer_bundle
    occurrence = next(row for row in bundle.occurrences() if row["source_id"] == "CultureMech:015191")
    assert bundle.resolve_source("MIM:Bovine_Serum_Albumin", occurrence_id=occurrence["occurrence_id"]) == "NCIT:C85253"
    with pytest.raises(ValueError, match="do not agree"):
        bundle.resolve_source("MIM:Xanthine", occurrence_id=occurrence["occurrence_id"])
    assert occurrence["product_id"] is None
    assert occurrence["alternatives"][0]["operator"] == "one_of"
    assert occurrence["alternatives"][0]["selection_status"] == "UNSPECIFIED"
    assert bundle.resolve_source("MIM:Lysozyme") == "kgmicrobe.ingredient:lysozyme"
    assert bundle.active_xrefs("MIM:Lysozyme") == []
    assert bundle.active_xrefs("MIM:Sorbitan_Monooleate") == []


def test_consolidation_and_actual_lookup_keep_context_separate(lookup_bundle):
    """Qualified MIM resolution and generic trait lookup coexist after serialization/reload."""
    directory, receipt = lookup_bundle
    loader = cmu.ChemicalMappingLoader.from_ingredient_lookup_bundle(
        directory, manifest_sha256=receipt["manifest_sha256"]
    )
    assert loader.find_chebi_by_name("Xanthine") == "CHEBI:15318"
    assert loader.find_chebi_by_xref("MIM:Xanthine") == "CHEBI:17712"
    assert loader.resolve_ingredient_source("MIM:Rifamycin") == "CHEBI:26580"
    assert loader.get_node_enrichment("CHEBI:26580")["xref"] == ""
    assert loader.get_node_enrichment("CHEBI:29673")["xref"] == "cas:6998-60-3"
    owners = loader.get_identifier_annotation_owners("cas:9048-46-8")
    assert "NCIT:C85253" in owners and len(owners) == 2
    assert all(not value.startswith("MIM.product:") for value in cmu._XREF_INDEX.values())
    assert "cas:9048-46-8" not in cmu._XREF_INDEX
    assert loader.get_identifier_annotation_owners("cas:8048-52-0") == []


def test_bare_profile_cannot_bypass_bundle_review(producer_bundle):
    """Neither raw lookup nor the legacy additive consolidator accepts a stripped bundle."""
    path = producer_bundle.directory / "ingredient_mappings.sssom.tsv"
    with pytest.raises(ValueError, match="verified complete ingredient bundle"):
        cmu.load_unified_mappings(path)
    assert not cmu._LOADED
    with pytest.raises(ValueError, match="verified ingredient bundle"):
        ChemicalMappingConsolidator().load_mediaingredientmech_sssom(path)


def test_missing_target_prevents_scoped_consolidation(producer_bundle, tmp_path):
    """A missing ontology/local endpoint is reported rather than silently discarded."""
    with pytest.raises(ValueError, match="targets are missing"):
        build_ingredient_lookup_bundle(ChemicalMappingConsolidator(), producer_bundle, tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()


def test_annotation_artifact_reconstructs_original_tuples(producer_bundle, tmp_path):
    """Projection adds a canonical owner alongside the complete original source assertion."""
    path = tmp_path / "annotations.json"
    result = producer_bundle.write_annotations(path)
    document = json.loads(path.read_text())
    assert result["sha256"] == content_sha256(path.read_bytes())
    assert [entry["claim"] for entry in document["claims"]] == producer_bundle.identifier_claims()
    for entry in document["claims"]:
        assert entry["canonical_owner_id"] == producer_bundle.canonical_owner(entry["claim"]["owner_id"])
        for evidence in entry["claim"]["evidence"]:
            assert evidence["document_id"] in document["evidence_members"]
    assert document["ingredient_bundle_manifest_sha256"] == producer_bundle.fingerprint


@pytest.mark.parametrize(
    "member", ["manifest.json", "ingredient_identifier_annotations.tsv", "ingredient_occurrences.json"]
)
def test_changed_bundle_cannot_be_reused_or_finalized(producer_bundle, tmp_path, member):
    """Every behavior input is recorded, including history and occurrence detail."""
    directory = tmp_path / "bundle"
    shutil.copytree(producer_bundle.directory, directory)
    bundle = ReviewedIngredientBundle(directory, manifest_sha256=producer_bundle.fingerprint)
    transform = Transform("ingredient-fixture", input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    bundle.bind_to_transform(transform)
    transform.verify_consumed_inputs()
    path = directory / member
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed|mismatch"):
        bundle.verify_current()
    with pytest.raises(SourceFinalizationRequired, match="changed or missing"):
        transform.verify_consumed_inputs()
    with pytest.raises(ValueError):
        bundle.bind_to_transform(transform)
    assert transform._consumed_input_error


def test_changed_legacy_mapping_pin_invalidates_cached_success(tmp_path):
    """An unchanged path cannot reuse a lookup built from different selected bytes."""
    path = tmp_path / "legacy.tsv"
    header = b"subject_id\tpredicate_id\tobject_id\tobject_label\n"
    path.write_bytes(header + b"source:one\tskos:exactMatch\tCHEBI:999991\talpha\n")
    first = content_sha256(path.read_bytes())
    cmu.load_unified_mappings(path, expected_sha256=first)
    assert cmu.find_chebi_by_xref("source:one") == "CHEBI:999991"
    path.write_bytes(header + b"source:two\tskos:exactMatch\tCHEBI:999992\tbeta\n")
    with pytest.raises(ValueError, match="selected lookup bundle"):
        cmu.load_unified_mappings(path, expected_sha256=first)
    assert not cmu._LOADED
    cmu.load_unified_mappings(path, expected_sha256=content_sha256(path.read_bytes()))
    assert cmu.find_chebi_by_xref("source:one") is None
    assert cmu.find_chebi_by_xref("source:two") == "CHEBI:999992"


def test_rehashed_lookup_annotations_cannot_override_review(lookup_bundle, tmp_path):
    """The graph-associated history is reconstructed, not trusted just because its hash matches."""
    directory = tmp_path / "changed"
    shutil.copytree(lookup_bundle[0], directory)
    path = directory / "ingredient_identifier_annotations.json"
    document = json.loads(path.read_text())
    document["claims"][0]["canonical_owner_id"] = "CHEBI:15318"
    path.write_bytes(canonical_json(document) + b"\n")
    manifest = json.loads((directory / "lookup_manifest.json").read_text())
    manifest["members"][path.name] = content_sha256(path.read_bytes())
    content = canonical_json(manifest) + b"\n"
    (directory / "lookup_manifest.json").write_bytes(content)
    with pytest.raises(ValueError, match="differs from reviewed"):
        load_ingredient_lookup_bundle(directory, manifest_sha256=content_sha256(content))


@pytest.mark.parametrize(
    "member",
    [
        "mappings/ingredient_name_scopes.tsv",
        "kg_microbe/profiles/ingredient_scope_v1.yaml",
        "kg_microbe/profiles/ingredient_bundle_v1.schema.json",
    ],
)
def test_scope_and_annotation_policy_files_change_data_fingerprint(tmp_path, member):
    """Non-Python behavior inputs participate in freshness checks even with no custom source inputs."""
    before = data_fingerprint(tmp_path, ())
    path = tmp_path / member
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("changed behavior")
    assert data_fingerprint(tmp_path, ()) != before


def test_returned_claims_do_not_mutate_verified_snapshot(producer_bundle):
    """A caller cannot silently alter the evidence held by a successful validated load."""
    claims = producer_bundle.identifier_claims()
    claims[0]["xref_eligible"] = not claims[0]["xref_eligible"]
    assert claims != producer_bundle.identifier_claims()


def test_rehashed_lookup_cannot_remove_a_required_scoped_target(lookup_bundle, tmp_path):
    """A fresh wrapper hash cannot legitimize a missing endpoint in the selected legacy/native input."""
    directory = tmp_path / "missing-target"
    shutil.copytree(lookup_bundle[0], directory)
    path = directory / "legacy.sssom.tsv.gz"
    with gzip.open(path, "rt") as stream:
        lines = stream.readlines()
    header = []
    while lines and lines[0].startswith("#"):
        header.append(lines.pop(0))
    reader = csv.DictReader(io.StringIO("".join(lines)), delimiter="\t")
    rows = [row for row in reader if row["object_id"] != "CHEBI:29673"]
    with gzip.open(path, "wt", newline="") as stream:
        stream.write("".join(header))
        writer = csv.DictWriter(stream, fieldnames=reader.fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((directory / "lookup_manifest.json").read_text())
    manifest["members"][path.name] = content_sha256(path.read_bytes())
    content = canonical_json(manifest) + b"\n"
    (directory / "lookup_manifest.json").write_bytes(content)
    with pytest.raises(ValueError, match="targets are missing"):
        load_ingredient_lookup_bundle(directory, manifest_sha256=content_sha256(content))


@pytest.mark.parametrize("changed_pin", [False, True])
def test_scoped_loader_cannot_reuse_another_global_lookup(lookup_bundle, tmp_path, changed_pin):
    """An unrelated legacy caller cannot replace the pinned loader's selected name index."""
    selected = tmp_path / "selected"
    shutil.copytree(lookup_bundle[0], selected)
    loader = cmu.ChemicalMappingLoader.from_ingredient_lookup_bundle(
        selected, manifest_sha256=lookup_bundle[1]["manifest_sha256"]
    )
    other = tmp_path / "other.tsv"
    other.write_text(
        "subject_id\tpredicate_id\tobject_id\tobject_label\n"
        "kgm.name:other\tskos:exactMatch\tCHEBI:999\tOther chemical\n"
    )
    cmu.load_unified_mappings(other)
    if changed_pin:
        with (selected / "legacy.sssom.tsv.gz").open("ab") as stream:
            stream.write(b"changed")
        with pytest.raises(ValueError, match="do not match"):
            loader.find_chebi_by_name("xanthine")
        return
    assert loader.find_chebi_by_name("xanthine") == "CHEBI:15318"
    assert loader.get_canonical_name("CHEBI:15318") == "xanthine"
