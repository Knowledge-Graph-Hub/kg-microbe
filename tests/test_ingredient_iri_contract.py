"""Ingredient IRIs cannot reacquire Biolink's unrelated MIM/OMIM graph prefix."""

import csv
import io
import json
import tarfile
from multiprocessing.pool import ThreadPool

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.ingredient_kgx import ingredient_kgx_profile, json_scalar
from kg_microbe.utils.source_finalization import graph_rows
from tests.test_ingredient_bundle import producer_bundle as producer_bundle
from tests.test_merge_source_freshness import merge_config, prepare_source, record_source

pytestmark = pytest.mark.usefixtures("local_source_schema")

INGREDIENT_IRI = "https://github.com/CultureBotAI/MediaIngredientMech/blob/main/data/ingredients/mapped/Xanthine"
INGREDIENT_ID = "MIM.ingredient:Xanthine"


@pytest.mark.parametrize(
    "identifier,expected",
    [(INGREDIENT_IRI, INGREDIENT_ID), (INGREDIENT_ID, INGREDIENT_ID), ("MIM:123456", "MIM:123456")],
)
def test_ingredient_iri_compaction_preserves_namespace(identifier, expected):
    """Expanded ingredient IDs compact consistently without rewriting unrelated MIM CURIEs."""
    assert compact_identifier(identifier) == expected
    assert compact_identifier(expected) == expected


def test_ingredient_iri_survives_finalization_and_public_archive(tmp_path, monkeypatch, producer_bundle):
    """Finalize expanded graph endpoints while retaining original MIM IDs inside source evidence."""
    source = prepare_source(tmp_path, "ontologies")
    source.TSV_QUOTING = csv.QUOTE_NONE
    # This software-only graph describes a real, unchanged mapping claim. It
    # does not assert chemical equivalence or add a new scientific disposition.
    claim = next(row for row in producer_bundle.mappings() if row["subject_id"] == "MIM:Xanthine")
    source.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        f"{INGREDIENT_IRI}\tbiolink:ChemicalEntity\tXanthine\tinfores:mediaingredientmech\n"
        "fixture:mapping\tbiolink:InformationContentEntity\tMapping evidence\tinfores:mediaingredientmech\n",
        encoding="utf-8",
    )
    edge = {
        "subject": "fixture:mapping",
        "predicate": "biolink:related_to",
        "object": INGREDIENT_IRI,
        "relation": "IAO:0000136",
        "primary_knowledge_source": "infores:mediaingredientmech",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
        "ingredient_profile": ingredient_kgx_profile()["profile_id"],
        "ingredient_bundle_sha256": producer_bundle.fingerprint,
        "ingredient_mapping_json": json_scalar(claim),
    }
    with source.output_edge_file.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, list(edge), delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow(edge)
    source.finalize(fresh_run=True)
    record_source(source)
    assert {row["id"] for row in graph_rows(source.output_node_file)} == {INGREDIENT_ID, "fixture:mapping"}
    prepared_edge = next(graph_rows(source.output_edge_file))
    assert prepared_edge["object"] == INGREDIENT_ID
    assert json.loads(prepared_edge["ingredient_mapping_json"]) == claim

    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    config = merge_config(tmp_path, [source])
    settings = yaml.safe_load(config.read_text())
    settings["merged_graph"]["destination"]["tsv"]["compression"] = "tar.gz"
    config.write_text(yaml.safe_dump(settings))
    merge_kg.load_and_merge(str(config), processes=1)
    with tarfile.open(tmp_path / "published/fixture.tar.gz") as archive:
        nodes_text = archive.extractfile("fixture_nodes.tsv").read().decode()
        edges_text = archive.extractfile("fixture_edges.tsv").read().decode()
    nodes = list(csv.DictReader(io.StringIO(nodes_text), delimiter="\t", quoting=csv.QUOTE_NONE))
    edges = list(csv.DictReader(io.StringIO(edges_text), delimiter="\t", quoting=csv.QUOTE_NONE))
    assert {row["id"] for row in nodes} == {INGREDIENT_ID, "fixture:mapping"}
    assert len(edges) == 1 and edges[0]["object"] == INGREDIENT_ID
    assert json.loads(edges[0]["ingredient_mapping_json"]) == claim
    assert claim["subject_id"] == "MIM:Xanthine"
