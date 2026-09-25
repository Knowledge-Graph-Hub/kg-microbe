"""Preserve reviewed raw trait observations without inventing chemical identity."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.constants import AUTOMATED_AGENT, CHEMICAL_CATEGORY, OBSERVATION
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings

FIXTURE = Path(__file__).parent / "resources/metatraits_mim_source_local.tsv"
CANONICAL = Path(__file__).resolve().parents[1] / "mappings/canonical"


def _reviewed_rows():
    """Read the finite source-label and predicate regression fixture."""
    with FIXTURE.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
def test_finite_local_trait_overrides_cover_real_source_patterns(transform_type):
    """Actual special/manual readers agree even if a stale loader supplies UDP."""
    transform = transform_type.__new__(transform_type)
    transform.special_chemical_mappings = transform._load_special_chemical_mappings()
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: "CHEBI:17659")
    manual = load_microbial_trait_mappings(CANONICAL)
    for row in _reviewed_rows():
        resolved = transform._resolve_chemical_trait(row["trait"])
        assert resolved == {
            "curie": row["object_id"],
            "category": CHEMICAL_CATEGORY,
            "name": row["object_label"],
            "predicate": row["positive"],
        }
        for key in [row["trait"], row["trait"].lower()]:
            assert manual[key]["object_id"] == row["object_id"]
            assert manual[key]["biolink_predicate"] == row["positive"]
    assert len({row["object_id"] for row in _reviewed_rows()}) == 3
    assert "assimilation: unreviewed source compound" not in manual


@pytest.mark.parametrize(
    "transform_type,source",
    [(MetaTraitsTransform, "infores:metatraits"), (MetaTraitsGTDBTransform, "infores:gtdb-metatraits")],
)
def test_worker_preserves_polarity_percentage_provenance_and_local_nodes(transform_type, source, tmp_path, monkeypatch):
    """Exercise real streaming worker output for both source producers and polarities."""
    rows = _reviewed_rows()
    # Native-ontology identity is deliberately unavailable. The reviewed local
    # mappings must preserve observations without manufacturing external xrefs.
    loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: None,
        get_node_enrichment=lambda curie: {"xref": "", "synonym": ""},
    )
    monkeypatch.setattr(metatraits, "ChemicalMappingLoader", lambda: loader)
    transform = transform_type.__new__(transform_type)
    shared = {
        "input_base_dir": str(tmp_path),
        "output_dir": str(tmp_path),
        "knowledge_source": source,
        "microbial_mappings": load_microbial_trait_mappings(CANONICAL),
        "special_chemical_mappings": transform._load_special_chemical_mappings(),
        "metpo_pattern_to_predicate": {
            row["trait"].split(":", 1)[0]: {"positive": row["positive"], "negative": row["negative"]} for row in rows
        },
    }
    for key in [
        "ncbitaxon_name_to_id",
        "trait_mapping",
        "metpo_mappings",
        "metpo_binned_ranges",
        "metpo_label_to_class",
        "metpo_synonym_to_class",
        "ec_to_go",
        "enzyme_name_to_go",
        "ncbi_to_gtdb_mappings",
    ]:
        shared[key] = {}
    transform._init_from_shared_data(shared)
    monkeypatch.setattr(
        transform,
        "_search_ncbitaxon_by_label",
        lambda label: "NCBITaxon:562" if label == "positive fixture" else "NCBITaxon:1423",
    )
    input_path = tmp_path / "reviewed_traits.jsonl"
    records = []
    for polarity in ["true", "false"]:
        records.append(
            {
                "tax_name": "positive fixture" if polarity == "true" else "negative fixture",
                "summaries": [
                    {
                        "name": row["trait"],
                        "is_discrete": True,
                        "num_observations": 5,
                        "unique_databases": 1,
                        "majority_label": f"{polarity}: (100%)",
                        "percentages": {"true": 100.0 if polarity == "true" else 0.0},
                    }
                    for row in rows
                ],
            }
        )
    input_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    result = transform._process_single_file(input_path, tmp_path, show_status=False)
    assert not result["unmapped_traits"]
    assert not result["unresolved_taxa"]
    with result["edges_file"].open() as handle:
        edges = list(csv.DictReader(handle, delimiter="\t"))
    expected = {
        (taxon, row[polarity], row["object_id"], pct)
        for row in rows
        for taxon, polarity, pct in [("NCBITaxon:562", "positive", "100.0"), ("NCBITaxon:1423", "negative", "0.0")]
    }
    assert len(edges) == 18
    assert {(r["subject"], r["predicate"], r["object"], r["has_percentage"]) for r in edges} == expected
    for edge in edges:
        assert edge["primary_knowledge_source"] == source
        assert edge["knowledge_level"] == OBSERVATION
        assert edge["agent_type"] == AUTOMATED_AGENT
        assert edge["object"].startswith("kgmicrobe.compound:")
    with result["nodes_file"].open() as handle:
        local_nodes = [row for row in csv.DictReader(handle, delimiter="\t") if row["id"].startswith("kgmicrobe.")]
    assert len(local_nodes) == 3
    assert {(node["id"], node["name"]) for node in local_nodes} == {
        (row["object_id"], row["object_label"]) for row in rows
    }
    for node in local_nodes:
        assert node["category"] == CHEMICAL_CATEGORY
        assert node["provided_by"] == source
        assert not node["xref"]
        assert not node["same_as"]
