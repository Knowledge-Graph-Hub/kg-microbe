"""Evidence-backed semantic corrections preserve nearby invalid counterexamples."""

import csv
import json

import pandas as pd
import pytest

from kg_microbe.transform_utils.constants import ASSAY_HAS_INPUT_PREDICATE, ASSAY_HAS_OUTPUT_PREDICATE
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import RheaMappingsTransform
from kg_microbe.utils import foodon_classification
from kg_microbe.utils.graph_canonicalization import canonical_node_category
from kg_microbe.utils.transform_fingerprint import data_fingerprint
from tests.test_kg_model_review_domain_range import _load

EDGE_HEADER = [
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


def test_shared_curation_change_invalidates_even_undeclared_consumer(tmp_path):
    """Source-independent category curation is content-tracked for every transform consumer."""
    mapping = tmp_path / "mappings" / "foodon_model_dispositions.tsv"
    mapping.parent.mkdir()
    before = data_fingerprint(tmp_path, ())
    mapping.write_text("id\tdisposition\tevidence\nFOODON:1\torganism_class\tx\n")
    first = data_fingerprint(tmp_path, ())
    mapping.write_text("id\tdisposition\tevidence\nFOODON:2\torganism_class\tx\n")
    assert before != first != data_fingerprint(tmp_path, ())


@pytest.mark.parametrize("target", ["EC:3.5.1.50", "GO:0050168"])
def test_curated_rhea_activity_mapping_is_not_physical_enablement(target):
    """Both producer paths share complete, manual curated cross-reference metadata."""
    transform = RheaMappingsTransform.__new__(RheaMappingsTransform)
    transform.edge_header = EDGE_HEADER
    transform.knowledge_source = "infores:rhea"
    row = dict(zip(EDGE_HEADER, transform._curated_xref_row("RHEA:10000", target), strict=True))
    assert row == dict(
        zip(
            EDGE_HEADER,
            [
                "RHEA:10000",
                "biolink:close_match",
                target,
                "oboInOwl:hasDbXref",
                "infores:rhea",
                "knowledge_assertion",
                "manual_agent",
            ],
            strict=True,
        )
    )
    with pytest.raises(ValueError):
        transform._curated_xref_row("RHEA:10000", "UniProtKB:P12345")


def test_foodon_asserted_organism_branch_and_curated_kelp_preserve_food_parts(tmp_path, monkeypatch):
    """Whole-plant ancestry is positive evidence; in_taxon alone cannot change a fruit into a taxon."""
    raw = tmp_path / "foodon.json"
    raw.write_text(
        json.dumps(
            {
                "graphs": [
                    {
                        "edges": [
                            {"sub": "FOODON:1", "pred": "is_a", "obj": "PO:0000003"},
                            {"sub": "FOODON:2", "pred": "is_a", "obj": "FOODON:1"},
                            {"sub": "FOODON:3", "pred": "RO:0002162", "obj": "FOODON:2"},
                        ]
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(foodon_classification, "FOODON_GRAPH", raw)
    assert canonical_node_category("FOODON:2", "biolink:Food|biolink:OntologyClass") == "biolink:OrganismTaxon"
    assert canonical_node_category("FOODON:3", "biolink:Food") == "biolink:Food"
    assert canonical_node_category("FOODON:03411744", "biolink:Food") == "biolink:OrganismTaxon"
    assert canonical_node_category("FOODON:00003673", "biolink:Food") == "biolink:Food"


def test_foodon_quarantine_is_exact_lossless_and_does_not_drop_uncertain_taxa(tmp_path):
    """Only reviewed incompatible target assertions leave the entity graph; originals survive intact."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.node_header = ["id", "category", "name"]
    transform.edge_header = EDGE_HEADER
    edges = tmp_path / "foodon_edges.tsv"
    rows = [
        [
            "FOODON:1",
            "biolink:in_taxon",
            "FOODON:00003673",
            "RO:0002162",
            "foodon.json",
            "knowledge_assertion",
            "manual_agent",
            "raw-extra",
        ],
        [
            "FOODON:2",
            "biolink:in_taxon",
            "FOODON:unclassified",
            "RO:0002162",
            "foodon.json",
            "knowledge_assertion",
            "manual_agent",
            "keep-unknown",
        ],
        [
            "FOODON:3",
            "biolink:related_to",
            "FOODON:00003673",
            "RO:0002162",
            "foodon.json",
            "knowledge_assertion",
            "manual_agent",
            "different-predicate",
        ],
        [
            "CHEBI:1",
            "biolink:has_attribute",
            "CHEBI:50906",
            "RO:0000087",
            "foodon.json",
            "knowledge_assertion",
            "manual_agent",
            "role",
        ],
        [
            "CHEBI:2",
            "biolink:has_attribute",
            "PATO:1",
            "RO:0000086",
            "infores:other",
            "knowledge_assertion",
            "manual_agent",
            "quality",
        ],
    ]
    pd.DataFrame(rows, columns=EDGE_HEADER + ["raw_column"]).to_csv(edges, sep="\t", index=False)
    transform._normalize_schema(tmp_path / "missing_nodes.tsv", edges)
    kept = pd.read_csv(edges, sep="\t")
    assert len(kept) == 4
    assert kept.loc[kept.subject == "CHEBI:1", "predicate"].item() == "biolink:has_chemical_role"
    assert kept.loc[kept.subject == "CHEBI:2", "predicate"].item() == "biolink:has_attribute"
    assert set(kept.primary_knowledge_source) == {"infores:foodon", "infores:other"}
    report = pd.read_csv(tmp_path / "foodon_model_quarantine.tsv", sep="\t")
    assert report.iloc[0][EDGE_HEADER + ["raw_column"]].tolist() == rows[0]
    assert "fruit" in report.iloc[0]["reason"]


def test_native_assay_rules_are_typed_extensions_not_biological_process_typing():
    """Procedure→activity/reagent is explicit; swapping those ranges still fails."""
    review = _load()
    assert ASSAY_HAS_INPUT_PREDICATE == "MICRO:0000065"
    assert ASSAY_HAS_OUTPUT_PREDICATE == "MICRO:0001206"
    nodes = [
        {"id": "kgmicrobe.assay:1", "category": "biolink:Procedure"},
        {"id": "GO:1", "category": "biolink:MolecularActivity"},
    ]
    edge = {"subject": nodes[0]["id"], "predicate": ASSAY_HAS_OUTPUT_PREDICATE, "object": "GO:1"}
    assert not any(f.severity == "WARNING" for f in review.check_domain_range(nodes, [edge], True))
    edge["predicate"] = ASSAY_HAS_INPUT_PREDICATE
    assert any(f.severity == "WARNING" for f in review.check_domain_range(nodes, [edge], True))


@pytest.mark.parametrize(
    "subject_category,object_category,valid",
    [
        ("biolink:Procedure", "biolink:BiologicalProcess", True),
        ("biolink:Procedure", "biolink:MolecularActivity", False),
        ("biolink:MolecularActivity", "biolink:BiologicalProcess", False),
    ],
)
def test_assay_for_biological_process_has_an_explicit_typed_rule(subject_category, object_category, valid):
    """MICRO:0001215 is a native typed extension, not a generic excuse for arbitrary assay targets."""
    review = _load()
    nodes = [{"id": "kgmicrobe.assay:1", "category": subject_category}, {"id": "GO:1", "category": object_category}]
    edge = {"subject": nodes[0]["id"], "predicate": "MICRO:0001215", "object": "GO:1"}
    assert "MICRO:0001215" in review.KGMICROBE_EXTENSION_PREDICATES
    warnings = [finding for finding in review.check_domain_range(nodes, [edge], True) if finding.severity == "WARNING"]
    assert bool(warnings) is not valid


@pytest.mark.parametrize("change", [None, "wrong_relation", "instance", "unknown_category", "self"])
def test_ontology_class_house_rule_requires_structural_class_evidence(change):
    """A class axiom is allowed visibly; an instance, fallback, self-loop, or different relation is not."""
    review = _load()
    edge = {
        "subject": "CHEBI:1",
        "predicate": "biolink:subclass_of",
        "object": "CHEBI:2",
        "relation": "rdfs:subClassOf",
    }
    subject_cats, object_cats = ["biolink:ChemicalEntity"], ["biolink:ChemicalEntity"]
    if change == "wrong_relation":
        edge["relation"] = "RO:0000050"
    elif change == "instance":
        edge["subject"] = "sample:1"
    elif change == "unknown_category":
        subject_cats = ["biolink:NamedThing"]
    elif change == "self":
        edge["object"] = edge["subject"]
    reason = review._class_level_house_reason(edge, "subject", subject_cats, object_cats)
    assert bool(reason) == (change is None)


def test_phenotype_and_ec_conventions_do_not_allow_arbitrary_attributes_or_proteins():
    """Class-specific conventions cannot suppress chemical phenotype targets or unrelated Protein enablement."""
    review = _load()
    assert (
        review._class_level_house_reason(
            {"subject": "NCBITaxon:1", "object": "CHEBI:1", "predicate": "biolink:has_phenotype"},
            "object",
            ["biolink:OrganismTaxon"],
            ["biolink:Attribute"],
        )
        is None
    )
    assert (
        review._class_level_house_reason(
            {"subject": "UniProtKB:P1", "object": "GO:1", "predicate": "biolink:enables"},
            "subject",
            ["biolink:Protein"],
            ["biolink:MolecularActivity"],
        )
        is None
    )


def test_kgxval_distinguishes_native_assays_from_unknown_micro_predicates(tmp_path):
    """An explicit native extension is expected, but unknown MICRO properties remain actionable."""
    review = _load()
    result = tmp_path / "kgxval.csv"
    with result.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["ERROR", "PREDICATE"])
        writer.writeheader()
        writer.writerows({"ERROR": "BAD BIOLINK", "PREDICATE": pred} for pred in ["MICRO:0001206", "MICRO:unknown"])
    summary = review._summarize_kgxval_csv(result)
    assert "1 MICRO assay-native" in summary
    assert "1 actionable" in summary
