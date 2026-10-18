"""Regression tests for deterministic BacDive predicate-to-relation mapping (#431)."""

import gzip
import json
from collections import defaultdict
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive.bacdive import (
    BACDIVE_PREDICATE_TO_RELATION,
    BacDiveTransform,
    relation_for_predicate,
)
from kg_microbe.transform_utils.constants import (
    ASSOCIATED_WITH,
    CAPABLE_OF,
    CLOSE_MATCH_RELATION,
    HAS_ATTRIBUTE_RELATION,
    HAS_INPUT_RELATION,
    HAS_PHENOTYPE,
    IN_TAXON_RELATION,
    INTERACTS_WITH_RELATION,
    LOCATION_OF,
    ORIGINAL_OBJECT_COLUMN,
    PRODUCES_RELATION,
    PUBLICATIONS_COLUMN,
    RDFS_SUBCLASS_OF,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.mapping_file_utils import MetpoTreeNode
from kg_microbe.utils.source_finalization import graph_rows

FIXTURE = Path(__file__).parent / "resources/bacdive_publications/run_records.json"


def test_relation_for_predicate_lookup_and_metpo_self_mapping():
    """Every METPO/MICRO predicate maps to itself and biolink predicates map deterministically (#431)."""
    for metpo_pred in (
        "METPO:2000006",
        "METPO:2000031",
        "METPO:2000102",
        "METPO:2000103",
        "METPO:2000202",
        "METPO:2000222",
        "METPO:2000302",
        "METPO:2000303",
        "METPO:2000511",
        "METPO:2000517",
        "METPO:2000518",
        "MICRO:0001206",
        "MICRO:0000065",
    ):
        assert relation_for_predicate(metpo_pred) == metpo_pred

    assert relation_for_predicate("biolink:has_phenotype") == HAS_PHENOTYPE
    assert relation_for_predicate("biolink:has_attribute") == HAS_ATTRIBUTE_RELATION
    assert relation_for_predicate("biolink:capable_of") == CAPABLE_OF
    assert relation_for_predicate("biolink:produces") == PRODUCES_RELATION
    assert relation_for_predicate("biolink:interacts_with") == INTERACTS_WITH_RELATION
    assert relation_for_predicate("biolink:location_of") == LOCATION_OF
    assert relation_for_predicate("biolink:associated_with") == ASSOCIATED_WITH
    assert relation_for_predicate("biolink:associated_with_resistance_to") == ASSOCIATED_WITH
    assert relation_for_predicate("biolink:associated_with_sensitivity_to") == ASSOCIATED_WITH
    assert relation_for_predicate("biolink:has_input") == HAS_INPUT_RELATION
    assert relation_for_predicate("biolink:in_taxon") == IN_TAXON_RELATION
    assert relation_for_predicate("biolink:close_match") == CLOSE_MATCH_RELATION
    assert relation_for_predicate("biolink:subclass_of") == RDFS_SUBCLASS_OF

    for invalid in ("", None, "biolink:unknown_predicate"):
        with pytest.raises(ValueError):
            relation_for_predicate(invalid)  # type: ignore[arg-type]


def test_bacdive_run_enforces_single_relation_per_predicate_and_no_negated_ro_affirmation(
    tmp_path, monkeypatch
):
    """Full BacDiveTransform.run() emits a single deterministic relation per predicate (#431)."""
    records = [
        {
            "General": {
                "BacDive-ID": 1,
                "keywords": ["aerobe", "spore-forming"],
            },
            "Morphology": {
                "cell morphology": {
                    "cell shape": "rod-shaped",
                    "gram stain": "positive",
                    "motility": "yes",
                }
            },
            "Physiology and metabolism": {
                "oxygen tolerance": {"oxygen tolerance": "aerobe"},
                "spore formation": {"spore formation": "no"},
                "enzymes": [
                    {"activity": "+", "ec": "1.1.1.1", "value": "alcohol dehydrogenase"},
                    {"activity": "-", "ec": "3.2.1.23", "value": "beta-galactosidase"},
                ],
                "metabolite utilization": [
                    {
                        "Chebi-ID": 17234,
                        "metabolite": "glucose",
                        "kind of utilization tested": "carbon source",
                        "utilization activity": "+",
                    },
                    {
                        "Chebi-ID": 15377,
                        "metabolite": "water",
                        "kind of utilization tested": "carbon source",
                        "utilization activity": "-",
                    },
                ],
                "metabolite production": [
                    {"Chebi-ID": 16236, "metabolite": "ethanol", "production": "yes"},
                    {"Chebi-ID": 15366, "metabolite": "acetic acid", "production": "no"},
                ],
                "API zym": {
                    "ALP": "+",
                    "EST": "-",
                },
                "API 20E": {
                    "GLU": "+",
                    "MAN": "-",
                },
            },
            "Safety information": {"risk assessment": {"biosafety level": "1"}},
        }
    ]
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bacdive_strains.json").write_text(json.dumps(records))
    native_mesh = FIXTURE.parent.parent / "bacdive_clinical_mesh/mesh2026-clinical-excerpt.nt"
    (raw / "mesh2026.nt.gz").write_bytes(gzip.compress(native_mesh.read_bytes(), mtime=0))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / module.BACDIVE_MAPPING_FILE).write_text("EC_ID\tCHEBI_ID\tsubstrate\n")
    custom = tmp_path / "custom.yaml"
    custom.write_text("{}\n")
    monkeypatch.setattr(module, "BACDIVE_TMP_DIR", scratch)
    monkeypatch.setattr(module, "CUSTOM_CURIES_YAML_FILE", custom)
    monkeypatch.setattr(module, "METABOLITE_MAP", {})
    monkeypatch.setattr(module, "resolve_adapter", lambda adapter: adapter)

    transform = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(transform, "bacdive", raw, tmp_path / "transformed")
    transform.edge_header.extend(["value", "unit", PUBLICATIONS_COLUMN, ORIGINAL_OBJECT_COLUMN])
    transform.ncbi_impl = object()
    transform.knowledge_source = "infores:bacdive"
    transform.chemical_loader = None
    transform.chebi_categories = {}
    transform.pathogenicity_mappings = {}
    transform._ncbitaxon_ancestry_failures = set()
    transform._lpsn_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}

    # Both keyword and structured phenotype routes emit METPO:2000103 and biolink:has_attribute
    transform.bacdive_metpo_mappings = {
        "aerobe": {
            "curie": "METPO:1000602",
            "label": "aerobic",
            "inferred_category": "https://biolink.github.io/biolink-model/PhenotypicQuality",
            "predicate_biolink_equivalent": "https://w3id.org/metpo/2000103",
        },
        "spore-forming": {
            "curie": "METPO:1000871",
            "label": "spore-forming",
            "inferred_category": "https://biolink.github.io/biolink-model/BiologicalProcess",
            "predicate_biolink_equivalent": "https://w3id.org/metpo/2000103",
        },
        "1": {
            "curie": "METPO:1001102",
            "label": "not pathovar",
            "inferred_category": "https://biolink.github.io/biolink-model/PhenotypicQuality",
            "predicate_biolink_equivalent": "https://biolink.github.io/biolink-model/has_attribute",
        },
    }
    oxy_parent = MetpoTreeNode(
        "METPO:1000600",
        "oxygen preference",
        bacdive_json_paths=["Physiology and metabolism.oxygen tolerance.oxygen tolerance"],
    )
    oxy_child = MetpoTreeNode("METPO:1000602", "aerobic")
    oxy_child.synonyms.append("aerobe")
    oxy_parent.add_child(oxy_child)

    bsl_parent = MetpoTreeNode(
        "METPO:1001100",
        "biosafety",
        bacdive_json_paths=["Safety information.risk assessment.biosafety level"],
    )
    bsl_child = MetpoTreeNode("METPO:1001102", "not pathovar")
    bsl_child.synonyms.append("1")
    bsl_parent.add_child(bsl_child)

    transform.bacdive_metpo_tree = {
        oxy_parent.iri: oxy_parent,
        oxy_child.iri: oxy_child,
        bsl_parent.iri: bsl_parent,
        bsl_child.iri: bsl_child,
    }
    transform.phenotype_routing = [
        {"metpo_parent_id": "METPO:1000600"},
        {"metpo_parent_id": "METPO:1001100"},
    ]
    transform.metpo_iri_to_mapping = {
        oxy_child.iri: transform.bacdive_metpo_mappings["aerobe"],
        bsl_child.iri: transform.bacdive_metpo_mappings["1"],
    }
    transform.metpo_enzyme_mappings = {
        "+": {"curie": "METPO:2000302"},
        "-": {"curie": "METPO:2000303"},
    }
    transform.metpo_metabolite_utilization_mappings = {
        "carbon source": {
            "+": {"curie": "METPO:2000006"},
            "-": {"curie": "METPO:2000031"},
        }
    }
    transform.metpo_metabolite_production_mappings = {
        "yes": {"curie": "METPO:2000202", "label": "produces"},
        "no": {"curie": "METPO:2000222", "label": "does not produce"},
    }
    transform.assay_kit_mappings = {
        "API zym": {
            "wells": {
                "ALP": {"type": "enzyme", "go_terms": ["GO:0004035"], "ec_number": ["3.1.3.1"]},
                "EST": {"type": "enzyme", "go_terms": ["GO:0004091"], "ec_number": ["3.1.1.1"]},
            },
            "metpo_predicates": {},
        },
        "API 20E": {
            "wells": {
                "GLU": {"type": "chemical", "chebi_id": ["CHEBI:17234"]},
                "MAN": {"type": "chemical", "chebi_id": ["CHEBI:29864"]},
            },
            "metpo_predicates": {
                "positive": {"id": "METPO:2000011"},
                "negative": {"id": "METPO:2000037"},
            },
        },
    }
    transform.assay_nodes_generated = []
    transform.assay_edges_generated = []
    transform.assay_target_nodes_generated = []
    monkeypatch.setattr(transform, "_prepare_assay_outputs", lambda: None)

    transform.run(show_status=False)
    edges = list(graph_rows(transform.output_edge_file))

    relations_by_predicate = defaultdict(set)
    for row in edges:
        relations_by_predicate[row["predicate"]].add(row["relation"])

    # Invariant 1: Every emitted predicate has exactly one relation across all call sites.
    for pred, rels in relations_by_predicate.items():
        assert len(rels) == 1, f"Predicate {pred} emitted multiple relations: {rels}"
        assert next(iter(rels)) == relation_for_predicate(pred)

    # Invariant 2: METPO:2000103 from both keyword and phenotype routes maps to METPO:2000103
    assert relations_by_predicate["METPO:2000103"] == {"METPO:2000103"}

    # Invariant 3: biolink:has_attribute maps to SIO:000008, never RO:0002200
    assert relations_by_predicate["biolink:has_attribute"] == {HAS_ATTRIBUTE_RELATION}

    # Invariant 4: Negated METPO predicates never pair with affirmative RO relations
    for negated_pred in ("METPO:2000031", "METPO:2000222", "METPO:2000303", "METPO:2000037"):
        assert relations_by_predicate[negated_pred] == {negated_pred}

    # Positive METPO predicates also self-map
    for positive_pred in ("METPO:2000006", "METPO:2000202", "METPO:2000302", "METPO:2000011", "METPO:2000511"):
        assert relations_by_predicate[positive_pred] == {positive_pred}
    assert set(BACDIVE_PREDICATE_TO_RELATION).issuperset(
        {"biolink:has_phenotype", "biolink:has_attribute", "biolink:capable_of"}
    )
