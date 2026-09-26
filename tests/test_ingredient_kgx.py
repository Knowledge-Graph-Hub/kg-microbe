"""Reviewed occurrences and registry claims survive the real finalized KGX merge."""

import csv
import hashlib
import io
import json
import shutil
import tarfile
from copy import deepcopy
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform_utils.mim_ingredients.mim_ingredients import (
    MIMIngredientsTransform,
    project_ingredient_context,
)
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.ingredient_kgx import ingredient_kgx_profile, json_scalar, validate_ingredient_fields
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows
from tests.test_ingredient_bundle import lookup_bundle as lookup_bundle
from tests.test_ingredient_bundle import producer_bundle as producer_bundle
from tests.test_ingredient_bundle import reset_lookup_cache as reset_lookup_cache
from tests.test_merge_source_freshness import merge_config, record_source

pytestmark = pytest.mark.usefixtures("local_source_schema")


@pytest.fixture
def prepared_ingredients(tmp_path, lookup_bundle):
    """Run the registered producer over actual MIM export bytes and an explicit lookup selection."""
    raw = tmp_path / "raw"
    selection_dir = raw / "mim_ingredients"
    selection_dir.mkdir(parents=True)
    authority = Path(__file__).parent / "resources/ingredient_bundle/native/foodon-authority.json"
    origin = json.loads(authority.with_name("foodon-origin.json").read_text())
    assert hashlib.sha256(authority.read_bytes()).hexdigest() == origin["fixture_sha256"]
    shutil.copyfile(authority, raw / "foodon.json")
    selection = {
        "mode": "candidate_only",
        "lookup_directory": str(lookup_bundle[0]),
        "lookup_manifest_sha256": lookup_bundle[1]["manifest_sha256"],
    }
    (selection_dir / "selection.json").write_bytes(canonical_json(selection) + b"\n")
    transform = MIMIngredientsTransform(raw, tmp_path / "transformed")
    counts = transform.run()
    assert counts == {"nodes": 71, "edges": 51, "bundle_sha256": producer_pin()}
    transform.finalize(fresh_run=True)
    record_source(transform)
    return transform


def producer_pin():
    """Read the immutable producer origin, rather than repeating its digest in assertions."""
    return json.loads((Path(__file__).parent / "resources/ingredient_bundle/origin.json").read_text())[
        "bundle_manifest_sha256"
    ]


@pytest.mark.parametrize("compressed", [False, True])
def test_actual_occurrences_and_history_roundtrip(
    prepared_ingredients, producer_bundle, tmp_path, monkeypatch, compressed
):
    """Compare all 51 structured source claims after finalization, real KGX merge and reload."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    source = prepared_ingredients
    before = list(graph_rows(source.output_edge_file))
    config = merge_config(tmp_path, [source])
    if compressed:
        payload = yaml.safe_load(config.read_text())
        payload["merged_graph"]["destination"]["tsv"]["compression"] = "tar.gz"
        config.write_text(yaml.safe_dump(payload))
    merge_kg.load_and_merge(str(config), processes=1)
    if compressed:
        with tarfile.open(tmp_path / "published/fixture.tar.gz") as archive:
            nodes_text = archive.extractfile("fixture_nodes.tsv").read().decode()
            edges_text = archive.extractfile("fixture_edges.tsv").read().decode()
    else:
        nodes_text = (tmp_path / "published/fixture_nodes.tsv").read_text()
        edges_text = (tmp_path / "published/fixture_edges.tsv").read_text()
    nodes = {row["id"]: row for row in csv.DictReader(io.StringIO(nodes_text), delimiter="\t", quoting=csv.QUOTE_NONE)}
    rows = list(csv.DictReader(io.StringIO(edges_text), delimiter="\t", quoting=csv.QUOTE_NONE))
    assert len(nodes) == 71 and len(rows) == 51
    for field in (
        "ingredient_mapping_json",
        "ingredient_product_json",
        "ingredient_occurrence_json",
        "ingredient_annotation_json",
    ):
        assert sorted(row[field] for row in rows if row.get(field)) == sorted(
            row[field] for row in before if row.get(field)
        )
    occurrences = [json.loads(row["ingredient_occurrence_json"]) for row in rows if row["ingredient_occurrence_json"]]
    assert sorted(occurrences, key=json_scalar) == sorted(producer_bundle.occurrences(), key=json_scalar)
    bsa = [row for row in occurrences if row["ingredient_id"] == "MIM:Bovine_Serum_Albumin"]
    assert len([row for row in bsa if row["source_id"].startswith("CultureMech:")]) == 7
    alternative = next(row for row in bsa if row["source_id"] == "CultureMech:015191")
    assert alternative["product_id"] is None
    assert alternative["alternatives"][0]["selection_status"] == "UNSPECIFIED"
    assert len(alternative["alternatives"][0]["members"]) == 2
    selected = [row for row in bsa if row["product_id"]]
    assert len(selected) == 1 and selected[0]["source_id"] == "CultureBotHT:compounds-to-cas"
    generic = nodes["NCIT:C85253"]
    assert generic["xref"] == "cas:9048-46-8"
    assert not any(product["catalog_number"] in json.dumps(generic) for product in producer_bundle.products())
    assert nodes["NCIT:C76253"]["xref"] == "cas:65589-70-0"
    claims = [json.loads(row["ingredient_annotation_json"]) for row in rows if row["ingredient_annotation_json"]]
    historical = next(row for row in claims if row["source_status"] == "SUPERSEDED")
    assert historical["identifier"] == "cas:8048-52-0" and not historical["xref_eligible"]
    rejected = next(row for row in claims if row["identifier_validity"] == "INVALID")
    assert rejected["raw_identifier"] == "2650-88-3" and rejected["identifier"] == ""
    assert not nodes["kgmicrobe.ingredient:lysozyme"]["xref"]
    assert not nodes["kgmicrobe.ingredient:sorbitan_monooleate"]["xref"]
    assert not any(row["predicate"] in {"biolink:same_as", "biolink:subclass_of"} for row in rows)
    for row in rows:
        assert row["primary_knowledge_source"] == "infores:mediaingredientmech"
        assert row["ingredient_bundle_sha256"] == producer_pin()


def test_row_order_does_not_change_projection(producer_bundle, lookup_bundle):
    """Input ordering cannot alter IDs, product alternatives or output assertion order."""
    loader = ChemicalMappingLoader.from_ingredient_lookup_bundle(
        lookup_bundle[0], manifest_sha256=lookup_bundle[1]["manifest_sha256"]
    )
    expected = project_ingredient_context(producer_bundle, loader)
    reversed_bundle = deepcopy(producer_bundle)
    for key in ("mappings", "identifiers", "products", "occurrences"):
        reversed_bundle._loaded[key].reverse()
    assert project_ingredient_context(reversed_bundle, loader) == expected


def test_structured_transport_preserves_control_characters_and_types(producer_bundle):
    """A source's tabs, newlines, literal pipes, quotes and nulls retain their JSON meaning."""
    payload = producer_bundle.occurrences()[0]
    payload["preparation"] = 'fraction | "V"\tline one\nline two\r\n'
    payload["source_payload"]["nested"] = {"choices": ["a|b", None, True, 1.25]}
    row = {
        "ingredient_profile": ingredient_kgx_profile()["profile_id"],
        "ingredient_bundle_sha256": producer_pin(),
        "ingredient_occurrence_json": json_scalar(payload),
        "ingredient_occurrence_id": payload["occurrence_id"],
        "ingredient_product_id": payload["product_id"] or "",
    }
    validate_ingredient_fields(row, is_node=False)
    assert json.loads(row["ingredient_occurrence_json"]) == payload
    assert not any(char in row["ingredient_occurrence_json"] for char in "\t\r\n")
    row["ingredient_product_id"] = "MIM.product:invented"
    with pytest.raises(ValueError, match="Selected product"):
        validate_ingredient_fields(row, is_node=False)


@pytest.mark.parametrize("value", ["[]", "{}|{}", '{"same":1,"same":2}', '{"value":NaN}'])
def test_invalid_structured_fields_are_rejected(value):
    """Unknown extensions cannot turn malformed structured history into a scalar string."""
    row = {
        "ingredient_profile": ingredient_kgx_profile()["profile_id"],
        "ingredient_bundle_sha256": producer_pin(),
        "ingredient_annotation_json": value,
    }
    with pytest.raises(ValueError):
        validate_ingredient_fields(row, is_node=False)


def test_failed_or_missing_selection_cannot_finalize(prepared_ingredients):
    """A failed new run must not certify old graph bytes under an unconsumed selection."""
    source = prepared_ingredients
    selection = source.input_base_dir / "mim_ingredients/selection.json"
    selection.write_text('{"mode":"production"}')
    with pytest.raises(ValueError, match="candidate_only"):
        source.run()
    with pytest.raises(SourceFinalizationRequired, match="candidate_only"):
        source.finalize(fresh_run=True)


def test_projection_failure_cannot_finalize_previous_output(prepared_ingredients, monkeypatch):
    """A failure after input validation cannot certify an older graph under the new run."""
    from kg_microbe.transform_utils.mim_ingredients import mim_ingredients

    def fail_projection(*args):
        """Fail after the new run has successfully bound all of its required inputs."""
        raise OSError("injected projection failure")

    source = prepared_ingredients
    previous = source.output_node_file.read_bytes(), source.output_edge_file.read_bytes()
    monkeypatch.setattr(mim_ingredients, "project_ingredient_context", fail_projection)
    with pytest.raises(OSError, match="injected projection failure"):
        source.run()
    assert previous == (source.output_node_file.read_bytes(), source.output_edge_file.read_bytes())
    with pytest.raises(SourceFinalizationRequired, match="injected projection failure"):
        source.finalize(fresh_run=True)


def test_ingredient_candidate_is_explicit_only(tmp_path, monkeypatch):
    """Registering freshness metadata cannot activate a candidate in the default production batch."""
    import kg_microbe.transform as dispatcher

    selected = []
    monkeypatch.setattr(dispatcher, "_missing_declared_inputs", lambda *args: [])
    monkeypatch.setattr(dispatcher, "_run_one", lambda source, *args: selected.append(source))
    dispatcher.transform(input_dir=tmp_path, output_dir=tmp_path)
    assert "mim_ingredients" not in selected
    dispatcher.transform(sources=["mim_ingredients"], input_dir=tmp_path, output_dir=tmp_path)
    assert selected[-1] == "mim_ingredients"


@pytest.mark.parametrize("predicate", ["skos:broadMatch", "skos:narrowMatch"])
@pytest.mark.parametrize("reverse_rows", [False, True])
def test_broad_mapping_uses_declared_canonical_endpoint(producer_bundle, lookup_bundle, predicate, reverse_rows):
    """An authorized identity and a separate broader mapping cannot leave a dangling MIM node."""
    bundle = deepcopy(producer_bundle)
    broad = next(row for row in bundle.mappings() if row["subject_id"] == "MIM:Xanthine")
    broad.update(
        predicate_id=predicate,
        object_id="CHEBI:15318",
        object_label="xanthine",
        ext_identity_authorized="false",
    )
    # Software-only policy probe: this extra row is not exported as new scientific evidence.
    bundle._loaded["mappings"].append(broad)
    if reverse_rows:
        bundle._loaded["mappings"].reverse()
    loader = ChemicalMappingLoader.from_ingredient_lookup_bundle(
        lookup_bundle[0], manifest_sha256=lookup_bundle[1]["manifest_sha256"]
    )
    nodes, edges = project_ingredient_context(bundle, loader)
    declared = {node["id"] for node in nodes}
    broader = [edge for edge in edges if edge["predicate"] == "biolink:broad_match"]
    assert len(broader) == 1
    expected = ("CHEBI:17712", "CHEBI:15318")
    if predicate == "skos:narrowMatch":
        expected = expected[::-1]
    assert (broader[0]["subject"], broader[0]["object"]) == expected
    assert all(edge[end] in declared for edge in edges for end in ("subject", "object"))


def test_nonidentity_source_has_unambiguous_graph_namespace(producer_bundle, lookup_bundle):
    """Retain original MIM IDs in payloads while separating graph IDs from Biolink's MIM."""
    bundle = deepcopy(producer_bundle)
    bundle._identities.pop("MIM:Xanthine")
    row = next(row for row in bundle._loaded["mappings"] if row["subject_id"] == "MIM:Xanthine")
    row["ext_identity_authorized"] = "false"
    loader = ChemicalMappingLoader.from_ingredient_lookup_bundle(
        lookup_bundle[0], manifest_sha256=lookup_bundle[1]["manifest_sha256"]
    )
    nodes, edges = project_ingredient_context(bundle, loader)
    declared = {row["id"] for row in nodes}
    assert "MIM.ingredient:Xanthine" in declared
    assert "MIM:Xanthine" not in declared
    assert all(edge[end] in declared for edge in edges for end in ("subject", "object"))
    mapping = next(
        json.loads(edge["ingredient_mapping_json"])
        for edge in edges
        if edge.get("ingredient_mapping_json") and edge["object"] == "MIM.ingredient:Xanthine"
    )
    assert mapping["subject_id"] == "MIM:Xanthine"
