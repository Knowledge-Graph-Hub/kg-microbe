"""Keep finite generic antibiotic observations separate from specific native members (#1153)."""

import csv
import json
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.constants import AUTOMATED_AGENT, CHEMICAL_CATEGORY, OBSERVATION
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table
from tests.test_mim_source_local_traits import CANONICAL

# Exact generic source patterns and historical local IDs from commit 4617f84b6.
CASES = [
    ("angustmycin", "kgmicrobe.compound:angustmycin", "CHEBI:8612", "psicofuranin"),
    ("rubradirin", "kgmicrobe.compound:rubradirin", "CHEBI:223718", "Rubradirin B"),
]


@pytest.mark.parametrize("mode", [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}])
@pytest.mark.parametrize("stale_canonical", [False, True])
def test_stale_unified_generic_names_cannot_narrow_native_specific_identities(
    tmp_path, monkeypatch, mode, stale_canonical
):
    """Finite exclusions protect old unified inputs without blocking explicit member names."""
    rows = []
    for name, _, target, native in CASES:
        label = name if stale_canonical else native
        rows.extend(
            [
                _row(
                    "kgm.name:" + name,
                    target,
                    label,
                    name=name,
                    comment="canonical_name" if stale_canonical else "synonym",
                ),
                _row(
                    "kgm.name:" + native.replace(" ", "_"),
                    target,
                    label,
                    name=native,
                    comment="synonym" if stale_canonical else "canonical_name",
                ),
            ]
        )
    rows.append(
        _row(
            "kgm.name:angustmycin_c",
            "CHEBI:8612",
            "angustmycin" if stale_canonical else "psicofuranin",
            name="Angustmycin C",
            comment="synonym",
        )
    )
    path = tmp_path / "stale-antibiotics.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    for name, _, _, _ in CASES:
        assert runtime.find_chebi_by_name(name, **mode) is None
        assert runtime.find_chebi_by_name("produces: " + name, **mode) is None
    assert runtime.find_chebi_by_name("Angustmycin C", **mode) == "CHEBI:8612"
    assert runtime.find_chebi_by_name("psicofuranin", **mode) == "CHEBI:8612"
    assert runtime.find_chebi_by_name("Rubradirin B", **mode) == "CHEBI:223718"


@pytest.mark.parametrize("name,local,wrong,native", CASES)
@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
def test_generic_antibiotic_scopes_do_not_select_specific_members(name, local, wrong, native, transform_type):
    """Every finite special/manual route retains the local source identity."""
    assert not ingredient_mapping_allowed(name, wrong)
    assert not ingredient_mapping_allowed("produces: " + name, wrong)
    assert ingredient_mapping_allowed(native, wrong)
    assert ingredient_mapping_allowed("Angustmycin C", "CHEBI:8612")
    transform = transform_type.__new__(transform_type)
    transform.special_chemical_mappings = transform._load_special_chemical_mappings()
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: wrong)
    resolved = transform._resolve_chemical_trait("produces: " + name)
    assert resolved == {"curie": local, "category": CHEMICAL_CATEGORY, "name": name, "predicate": "METPO:2000202"}
    manual = load_microbial_trait_mappings(CANONICAL)
    assert manual["produces: " + name]["object_id"] == local


@pytest.mark.parametrize(
    "transform_type,source",
    [
        (MetaTraitsTransform, "infores:metatraits"),
        (MetaTraitsGTDBTransform, "infores:gtdb-metatraits"),
    ],
)
def test_generic_antibiotic_worker_preserves_observations_without_external_identity(
    transform_type, source, tmp_path, monkeypatch
):
    """Real producer workers preserve positive/negative production, counts, labels and provenance."""
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
        "metpo_pattern_to_predicate": {"produces": {"positive": "METPO:2000202", "negative": "METPO:2000222"}},
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
    records = []
    for polarity in ["true", "false"]:
        records.append(
            {
                "tax_name": "positive fixture" if polarity == "true" else "negative fixture",
                "summaries": [
                    {
                        "name": "produces: " + name,
                        "is_discrete": True,
                        "num_observations": 5,
                        "unique_databases": 1,
                        "majority_label": polarity + ": (100%)",
                        "percentages": {"true": 100.0 if polarity == "true" else 0.0},
                    }
                    for name, _, _, _ in CASES
                ],
            }
        )
    path = tmp_path / "source-antibiotics.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    result = transform._process_single_file(path, tmp_path, show_status=False)
    assert not result["unmapped_traits"] and not result["unresolved_taxa"]
    with result["edges_file"].open() as handle:
        edges = list(csv.DictReader(handle, delimiter="\t"))
    expected = {
        (taxon, predicate, local, percentage)
        for _, local, _, _ in CASES
        for taxon, predicate, percentage in [
            ("NCBITaxon:562", "METPO:2000202", "100.0"),
            ("NCBITaxon:1423", "METPO:2000222", "0.0"),
        ]
    }
    assert len(edges) == 4
    assert {(row["subject"], row["predicate"], row["object"], row["has_percentage"]) for row in edges} == expected
    assert all(
        row["primary_knowledge_source"] == source
        and row["knowledge_level"] == OBSERVATION
        and row["agent_type"] == AUTOMATED_AGENT
        for row in edges
    )
    with result["nodes_file"].open() as handle:
        nodes = [row for row in csv.DictReader(handle, delimiter="\t") if row["id"].startswith("kgmicrobe.compound:")]
    assert {(row["id"], row["name"]) for row in nodes} == {(local, name) for name, local, _, _ in CASES}
    assert all(
        row["category"] == CHEMICAL_CATEGORY and row["provided_by"] == source and not row["xref"] and not row["same_as"]
        for row in nodes
    )
