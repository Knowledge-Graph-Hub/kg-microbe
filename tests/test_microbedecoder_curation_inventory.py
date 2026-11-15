"""Keep source curation accounting complete without decoding reported literals."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import HAS_ATTRIBUTE_RELATION
from kg_microbe.transform_utils.microbedecoder import faprotax_dispositions as fap
from kg_microbe.transform_utils.microbedecoder import observation_audit
from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    ATTRIBUTE_TYPE_CURATION_SOURCE,
    DEFAULT_PHENOTYPE_MAPPINGS,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import REPORTED_METABOLISM_ANNOTATIONS
from kg_microbe.transform_utils.microbedecoder.utils import BACDIVE_SNAPSHOT_COLUMNS
from scripts import review_microbedecoder_curation as inventory

AUTHORITY = Path(__file__).parent / "resources/microbedecoder/metpo_nodes.tsv"
EDGE_FIELDS = [
    "subject",
    "source_record",
    "source_column",
    "value",
    "value_encoding",
    "object",
    "predicate",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


def edge(column, value, target, **changes):
    """Build a literal assertion with the same source fields as the producer."""
    source = {
        "Bergey": "infores:bergey-manual",
        "VPI": "infores:vpi-anaerobe-manual",
        "Literature": "infores:microbedecoder-literature",
        "FAPROTAX": "infores:faprotax",
    }.get(column.split("_", 1)[0], "infores:microbedecoder")
    predicted = column == "FAPROTAX_Type_of_metabolism"
    row = {
        "subject": "lpsn:1",
        "source_record": "sha256:fixture#record=1",
        "source_column": column,
        "value": value,
        "value_encoding": "backslash",
        "object": target,
        "predicate": "biolink:has_attribute",
        "relation": HAS_ATTRIBUTE_RELATION,
        "primary_knowledge_source": source,
        "knowledge_level": "prediction" if predicted else "knowledge_assertion",
        "agent_type": "computational_model" if predicted else "manual_agent",
    }
    row.update(changes)
    return row


def process(value, target, column="FAPROTAX_Type_of_metabolism"):
    """Preserve the source's prediction evidence for FAPROTAX examples."""
    return edge(
        column,
        value,
        target,
        predicate="biolink:capable_of",
        relation="RO:0002215",
    )


def write_tsv(path, fields, rows):
    """Create small isolated source fixtures; never touch real transformed data."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def source(tmp_path, edges, nodes=()):
    """Create a finalized-source-shaped fixture."""
    directory = tmp_path / "source"
    directory.mkdir()
    write_tsv(directory / "edges.tsv", EDGE_FIELDS, edges)
    with DEFAULT_PHENOTYPE_MAPPINGS.open(newline="") as stream:
        rules = {(r["source_column"], r["source_literal"]): r for r in csv.DictReader(stream, delimiter="\t")}
    node_rows = []
    for node in nodes:
        row = {
            "id": node[0],
            "category": node[1],
            "provided_by": "infores:microbedecoder",
            "has_attribute_type": node[2] if len(node) > 2 else "",
        }
        if row["has_attribute_type"]:
            observations = [e for e in edges if e["object"] == node[0]]
            rule = rules.get((observations[0]["source_column"], observations[0]["value"])) if observations else None
            if rule:
                row.update(
                    {
                        "attribute_type_source": ATTRIBUTE_TYPE_CURATION_SOURCE,
                        "attribute_type_evidence": rule["evidence_uri"],
                        "attribute_type_rationale": rule["curation_rationale"],
                    }
                )
        if len(node) > 3:
            row.update(node[3])
        node_rows.append(row)
    write_tsv(
        directory / "nodes.tsv",
        [
            "id",
            "category",
            "provided_by",
            "has_attribute_type",
            "attribute_type_source",
            "attribute_type_evidence",
            "attribute_type_rationale",
        ],
        node_rows,
    )
    return directory


def legacy_review(*args, **kwargs):
    """Select historical diagnostic fixtures explicitly; this never claims current source admission."""
    return inventory.review(*args, **kwargs, faprotax_dispositions=None)


def run_review(source_dir, tmp_path):
    """Read the published inventory in addition to the returned summary."""
    output = tmp_path / "inventory"
    summary = legacy_review(source_dir, output, DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    with (output / "curation_inventory.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert json.loads((output / "summary.json").read_text()) == summary
    return summary, rows


def test_all_27_attribute_columns_remain_scoped_reported_values(tmp_path):
    """Zeros stay source attributes, distinguishing only field-specific reviewed coding."""
    edges, nodes = [], []
    for column in BACDIVE_SNAPSHOT_COLUMNS:
        target = "kgmicrobe.source_attribute:" + column
        edges.append(edge(column, "0", target))
        nodes.append((target, "biolink:Attribute"))
    summary, rows = run_review(source(tmp_path, edges, nodes), tmp_path)
    assert summary["edge_rows_by_facet"] == {"source_attribute": 27}
    assert len(rows) == len(BACDIVE_SNAPSHOT_COLUMNS) == 27
    assert {row["source_column"] for row in rows} == set(BACDIVE_SNAPSHOT_COLUMNS)
    assert {row["disposition"] for row in rows} == {
        "reported_measurement",
        "reported_unit",
        "reported_isolation_context",
        "reported_phenotype_description",
        "reported_phenotype_code",
        "reported_assay_result",
        "reported_assay_label",
        "reviewed_attribute_type_not_applied",
    }
    assert all(row["value"] == "0" and row["object_category"] == "biolink:Attribute" for row in rows)


def test_finalized_edge_rows_not_raw_report_attempts_or_unique_taxa(tmp_path):
    """Count all admitted rows even when identical inventory keys aggregate."""
    target = "kgmicrobe.source_attribute:motility_zero"
    first = edge("BacDive_Motility", "0", target)
    second = {**first, "subject": "lpsn:2", "source_record": "sha256:fixture#record=2"}
    crosswalk = edge(
        "", "", "NCBITaxon:1", predicate="biolink:close_match", relation="skos:closeMatch", value_encoding=""
    )
    source_dir = source(tmp_path, [first, second, second, crosswalk], [(target, "biolink:Attribute")])
    (source_dir / "unmapped_labels.tsv").write_text("occurrences\n999999\n")
    summary, rows = run_review(source_dir, tmp_path)
    assert summary["edges"] == 4
    assert summary["edge_rows_by_facet"] == {"crosswalk": 1, "source_attribute": 3}
    assert len(rows) == 1 and rows[0]["edge_rows"] == "3"
    assert "not merged coverage" in summary["scope"]
    assert "raw emission attempts" in summary["scope"]
    assert set(summary["inputs"]) == {
        "nodes",
        "edges",
        "process_mappings",
        "process_authority",
        "process_go_authority",
        "phenotype_mappings",
        "process_scope_definitions",
        "material_dispositions",
    }


def test_reviewed_applied_pending_and_unsupported_processes_are_distinct(tmp_path):
    """A known rule is not counted as applied while the source still uses a local target."""
    edges = [
        process("fermentation", "METPO:1002005"),
        process("nitrogen_fixation", "kgmicrobe.pathway:nitrogen_fixation"),
        process("unreviewed_process", "kgmicrobe.pathway:unreviewed_process"),
    ]
    nodes = [(row["object"], "biolink:BiologicalProcess") for row in edges if row["object"].startswith("kg")]
    summary, rows = run_review(source(tmp_path, edges, nodes), tmp_path)
    assert summary["edge_rows_by_disposition"] == {
        "needs_process_mapping": 1,
        "reviewed_mapping_not_applied": 1,
        "reviewed_process_normalization": 1,
    }
    assert all((row["knowledge_level"], row["agent_type"]) == ("prediction", "computational_model") for row in rows)


def test_mapped_chemicals_and_two_record_scoped_sugars_stay_distinct(tmp_path):
    """Identical material labels cannot merge distinct reviewed source identities."""
    targets = [
        "CHEBI:17234",
        "kgmicrobe.compound:microbedecoder_unresolved_a",
        "kgmicrobe.compound:microbedecoder_unresolved_b",
    ]
    edges = [
        edge(
            "Bergey_Substrates_for_end_products",
            "glucose" if index == 0 else "sugar",
            target,
            predicate="biolink:consumes",
            relation="RO:0002438",
            primary_knowledge_source="infores:bergey-manual",
        )
        for index, target in enumerate(targets)
    ]
    nodes = [(target, "biolink:ChemicalEntity") for target in targets[1:]]
    summary, rows = run_review(source(tmp_path, edges, nodes), tmp_path)
    assert summary["edge_rows_by_disposition"] == {"existing_chemical_mapping": 1, "retained_local_material": 2}
    assert {row["object"] for row in rows if row["value"] == "sugar"} == set(targets[1:])
    assert len(rows) == 3


@pytest.mark.parametrize("corrected", [False, True])
def test_not_reported_has_explicit_source_missing_value_disposition(tmp_path, corrected):
    """Expose the old literal-as-chemical route and recognize the bounded repair."""
    target = "kgmicrobe.source_attribute:missing" if corrected else "kgmicrobe.compound:not_reported"
    category = "biolink:Attribute" if corrected else "biolink:ChemicalEntity"
    row = edge(
        "Bergey_Substrates_for_end_products",
        "Not reported",
        target,
        predicate="biolink:has_attribute" if corrected else "biolink:consumes",
    )
    summary, rows = run_review(source(tmp_path, [row], [(target, category)]), tmp_path)
    expected = "reported_missing_value" if corrected else "missing_value_misrepresented_as_chemical"
    assert rows[0]["disposition"] == expected
    assert summary["edge_rows_by_disposition"] == {expected: 1}


@pytest.mark.parametrize("filename", ["edges.tsv", "nodes.tsv"])
@pytest.mark.parametrize("defect", ["duplicate_header", "missing_header", "short_row", "long_row"])
def test_malformed_input_aborts_without_publishing(tmp_path, filename, defect):
    """Do not silently reinterpret duplicate or ragged literal TSV fields."""
    target = "kgmicrobe.source_attribute:motility_zero"
    source_dir = source(tmp_path, [edge("BacDive_Motility", "0", target)], [(target, "biolink:Attribute")])
    path = source_dir / filename
    lines = path.read_text().splitlines()
    if defect == "duplicate_header":
        fields = lines[0].split("\t")
        fields[-1] = fields[0]
        lines[0] = "\t".join(fields)
    elif defect == "missing_header":
        fields = lines[0].split("\t")
        fields[0] = "unexpected" if filename == "nodes.tsv" else "unexpected_subject"
        if filename == "edges.tsv":
            fields[fields.index("object")] = "unexpected_object"
        lines[0] = "\t".join(fields)
    elif defect == "short_row":
        lines[1] = lines[1].rsplit("\t", 1)[0]
    else:
        lines[1] += "\textra"
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="Missing or duplicate|Malformed TSV"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("identifier", ["", "kgmicrobe.source_attribute:duplicate"])
def test_empty_or_duplicate_node_ids_abort(tmp_path, identifier):
    """An ambiguous declaration cannot certify the target's source category."""
    nodes = [(identifier, "biolink:Attribute"), (identifier, "biolink:ChemicalEntity")]
    source_dir = source(tmp_path, [], nodes)
    with pytest.raises(ValueError, match="Empty or duplicate source node"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_input_drift_aborts_without_touching_real_inputs(tmp_path, monkeypatch):
    """Simulate changed bytes at the second capture, without mutating input data."""
    source_dir = source(tmp_path, [])
    original = inventory.fingerprint
    calls = {}

    def changed_second_capture(path):
        """Simulate input drift on the second read without changing a real source."""
        result = original(path)
        calls[path] = calls.get(path, 0) + 1
        if path == source_dir / "edges.tsv" and calls[path] == 2:
            return {**result, "sha256": "changed-during-read"}
        return result

    monkeypatch.setattr(inventory, "fingerprint", changed_second_capture)
    with pytest.raises(ValueError, match="Inputs changed"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_existing_output_refused_before_reading_inputs(tmp_path):
    """Preserve previously published artifacts even when supplied input paths are bad."""
    output = tmp_path / "inventory"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("keep this existing artifact")
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        legacy_review(tmp_path / "absent", output, DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert marker.read_text() == "keep this existing artifact"


@pytest.mark.parametrize("kind", ["attribute_chemical", "unknown_column", "external_process", "missing_material"])
def test_unclassifiable_or_semantically_wrong_routes_abort(tmp_path, kind):
    """Fail closed instead of inflating the reviewed mapping count."""
    if kind == "attribute_chemical":
        row = edge("BacDive_Metabolite_utilization", "glucose", "CHEBI:17234")
    elif kind == "unknown_column":
        row = edge("BacDive_NotConfigured", "0", "kgmicrobe.source_attribute:unknown")
    elif kind == "external_process":
        row = process("unreviewed_process", "METPO:1002005")
    else:
        row = edge("Bergey_Substrates_for_end_products", "sugar", "kgmicrobe.compound:missing")
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("knowledge_level", "knowledge_assertion"),
        ("agent_type", "manual_agent"),
        ("relation", "RO:0002234"),
        ("predicate", "biolink:has_phenotype"),
    ],
)
def test_reviewed_target_does_not_hide_evidence_or_relation_changes(tmp_path, field, value):
    """A matching target cannot certify an upgraded prediction or wrong assertion."""
    row = process("fermentation", "METPO:1002005")
    row[field] = value
    source_dir = source(tmp_path, [row])
    with pytest.raises(
        ValueError, match="Reviewed process evidence|Unexpected process predicate|Scientific source provenance"
    ):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("category", [None, "biolink:Attribute"])
def test_fallback_process_needs_source_biological_process_declaration(tmp_path, category):
    """A pathway-looking prefix is insufficient evidence of a valid local declaration."""
    target = "kgmicrobe.pathway:unreviewed_process"
    nodes = [] if category is None else [(target, category)]
    source_dir = source(tmp_path, [process("unreviewed_process", target)], nodes)
    with pytest.raises(ValueError, match="Missing or mistyped local process"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("field", ["subject", "source_record"])
def test_record_context_headers_are_required(tmp_path, field):
    """Source accounting must not accept a table stripped of organism or record context."""
    source_dir = source(tmp_path, [])
    fields = [name for name in EDGE_FIELDS if name != field]
    write_tsv(source_dir / "edges.tsv", fields, [])
    with pytest.raises(ValueError, match="Missing or duplicate required fields"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("record", ["", "   "])
def test_scientific_assertions_require_nonempty_source_record(tmp_path, record):
    """A present header cannot substitute for the assertion's record locator."""
    row = process("fermentation", "METPO:1002005")
    row["source_record"] = record
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Missing source record"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("column", sorted(set(inventory.GROUP_ROLES) | set(BACDIVE_SNAPSHOT_COLUMNS)))
@pytest.mark.parametrize("field", ["subject", "object"])
@pytest.mark.parametrize("value", ["", "   "])
def test_every_scientific_route_requires_nonblank_endpoints(tmp_path, column, field, value):
    """Never certify an assertion with its organism or target missing (#1213)."""
    row = edge(column, "fixture", "CHEBI:17234")
    row[field] = value
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Missing scientific endpoint"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("literal", ["aerobic_chemoheterotrophy", "fermentation", "human_associated"])
@pytest.mark.parametrize("relation", ["", "RO:0002234", "RO:0002438"])
def test_fallback_processes_and_legacy_annotations_reject_wrong_relations(tmp_path, literal, relation):
    """Unmapped, unapplied and legacy process targets cannot bypass relation checks (#1214)."""
    target = f"kgmicrobe.pathway:{literal}"
    row = process(literal, target)
    row["relation"] = relation
    source_dir = source(tmp_path, [row], [(target, "biolink:BiologicalProcess")])
    with pytest.raises(ValueError, match="Unexpected process predicate/relation|Changed non-process source annotation"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_valid_legacy_source_annotation_keeps_explicit_misrepresentation_diagnostic(tmp_path):
    """Preserve visibility of the historical process-shaped annotation cohort (#1214)."""
    target = "kgmicrobe.pathway:human_associated"
    source_dir = source(
        tmp_path,
        [process("human_associated", target)],
        [(target, "biolink:BiologicalProcess")],
    )
    summary, rows = run_review(source_dir, tmp_path)
    assert summary["edge_rows_by_disposition"] == {"source_annotation_misrepresented_as_process": 1}
    assert rows[0]["disposition"] == "source_annotation_misrepresented_as_process"


@pytest.mark.parametrize(
    "target",
    [
        "kgmicrobe.source_attribute:glucose",
        "kgmicrobe.pathway:glucose",
        "NCBITaxon:1",
        "lpsn:1",
        "ncbi.assembly:GCF_000001.1",
        "GTDB:g__Example",
    ],
)
def test_chemical_roles_reject_known_nonchemical_namespaces(tmp_path, target):
    """A chemical column cannot certify an organism or reported attribute target."""
    row = edge(
        "Bergey_Substrates_for_end_products", "glucose", target, predicate="biolink:consumes", relation="RO:0002438"
    )
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Nonchemical target namespace"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize(
    "column,predicate,relation",
    [
        ("Bergey_Substrates_for_end_products", "biolink:produces", "RO:0002234"),
        ("Bergey_Substrates_for_end_products", "biolink:consumes", "RO:0002234"),
        ("Bergey_Major_end_products", "biolink:consumes", "RO:0002438"),
        ("Bergey_Minor_end_products", "biolink:produces", "RO:0002438"),
    ],
)
def test_chemical_predicate_and_relation_match_actual_source_role(tmp_path, column, predicate, relation):
    """Do not report a reversed substrate/product assertion as an existing mapping."""
    row = edge(column, "glucose", "CHEBI:17234", predicate=predicate, relation=relation)
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Unexpected chemical role predicate/relation"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("column", ["Bergey_Major_end_products", "Bergey_Minor_end_products"])
def test_product_roles_and_external_categories_are_reported_without_invented_declarations(tmp_path, column):
    """External chemical ontology categories remain owned by the ontology export."""
    row = edge(column, "acetate", "CHEBI:30089", predicate="biolink:produces", relation="RO:0002234")
    summary, rows = run_review(source(tmp_path, [row]), tmp_path)
    assert summary["edge_rows_by_disposition"] == {"existing_chemical_mapping": 1}
    assert rows[0]["object_category"] == ""


@pytest.mark.parametrize("category", ["biolink:ChemicalMixture", "biolink:OntologyClass"])
def test_local_material_inventory_preserves_native_category_without_new_chemical_policy(tmp_path, category):
    """Account for declared material without reapproving chemical identity."""
    target = "kgmicrobe.compound:reported_mixture"
    row = edge(
        "Bergey_Substrates_for_end_products",
        "complex medium",
        target,
        predicate="biolink:consumes",
        relation="RO:0002438",
    )
    summary, rows = run_review(source(tmp_path, [row], [(target, category)]), tmp_path)
    assert summary["edge_rows_by_disposition"] == {"retained_local_material": 1}
    assert rows[0]["object_category"] == category


def test_not_reported_requires_scoped_attribute_namespace(tmp_path):
    """A wrongly typed external target is not evidence that the missing-value repair applied."""
    row = edge("Bergey_Substrates_for_end_products", "Not reported", "CHEBI:17234")
    summary, rows = run_review(source(tmp_path, [row], [("CHEBI:17234", "biolink:Attribute")]), tmp_path)
    assert rows[0]["disposition"] == "missing_value_misrepresented_as_chemical"
    assert summary["edge_rows_by_disposition"] == {"missing_value_misrepresented_as_chemical": 1}


@pytest.mark.parametrize(
    "predicate,relation,target",
    [
        ("biolink:consumes", "RO:0002438", "CHEBI:17234"),
        ("biolink:produces", "RO:0002234", "CHEBI:30089"),
        ("biolink:capable_of", "RO:0002215", "METPO:1002005"),
        ("biolink:has_attribute", HAS_ATTRIBUTE_RELATION, "kgmicrobe.source_attribute:glucose"),
    ],
)
@pytest.mark.parametrize("value", ["glucose", ""])
def test_missing_scientific_source_column_never_becomes_crosswalk(tmp_path, predicate, relation, target, value):
    """Keep scientific rows with missing field context visible as a hard failure."""
    row = edge("", value, target, predicate=predicate, relation=relation, value_encoding="backslash" if value else "")
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Missing source column or invalid native crosswalk"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_all_native_crosswalk_shapes_remain_in_source_totals(tmp_path):
    """Retain baseline identities and the producer's supported GTDB taxonomy branch."""
    targets = ["NCBITaxon:1", "ncbi.assembly:GCF_000001.1", "IMG:123", "gold:Go000001", "GTDB:g__Example"]
    rows = [
        edge("", "", target, predicate="biolink:close_match", relation="skos:closeMatch", value_encoding="")
        for target in targets
    ]
    rows.append(
        edge(
            "",
            "",
            "lpsn:1",
            subject="kgmicrobe.strain:bacdive_1",
            predicate="biolink:subclass_of",
            relation="rdfs:subClassOf",
            value_encoding="",
        )
    )
    summary, detail = run_review(source(tmp_path, rows), tmp_path)
    assert summary["edges"] == 6
    assert summary["edge_rows_by_facet"] == {"crosswalk": 6}
    assert summary["edge_rows_by_disposition"] == {"existing_crosswalk": 6}
    assert detail == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", "glucose"),
        ("value_encoding", "backslash"),
        ("source_record", ""),
        ("relation", "RO:0002438"),
        ("object", "CHEBI:17234"),
        ("subject", "CHEBI:17234"),
        ("primary_knowledge_source", "infores:bergey-manual"),
        ("knowledge_level", "prediction"),
        ("agent_type", "computational_model"),
    ],
)
def test_native_crosswalk_context_and_shape_are_explicit(tmp_path, field, value):
    """Do not exempt malformed assertions merely because their predicate says close_match."""
    row = edge("", "", "NCBITaxon:1", predicate="biolink:close_match", relation="skos:closeMatch", value_encoding="")
    row[field] = value
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Missing source column or invalid native crosswalk"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("column,literal", sorted(REPORTED_METABOLISM_ANNOTATIONS))
@pytest.mark.parametrize("field", ["primary_knowledge_source", "knowledge_level", "agent_type"])
def test_all_seventeen_source_annotations_reject_changed_provenance(tmp_path, column, literal, field):
    """Group membership must not upgrade FAPROTAX predictions or impersonate another source."""
    target = "kgmicrobe.source_attribute:group"
    row = edge(column, literal, target)
    alternatives = {
        "primary_knowledge_source": "infores:wrong-source",
        "knowledge_level": "knowledge_assertion" if row["knowledge_level"] == "prediction" else "prediction",
        "agent_type": "manual_agent" if row["agent_type"] == "computational_model" else "computational_model",
    }
    row[field] = alternatives[field]
    source_dir = source(tmp_path, [row], [(target, "biolink:Attribute")])
    with pytest.raises(ValueError, match="Scientific source provenance"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_all_seventeen_annotations_preserve_legitimate_source_evidence(tmp_path):
    """Count the finite annotations as reported attributes, not normalized biological processes."""
    rows, nodes = [], []
    for index, (column, literal) in enumerate(sorted(REPORTED_METABOLISM_ANNOTATIONS)):
        target = f"kgmicrobe.source_attribute:group_{index}"
        rows.append(edge(column, literal, target))
        nodes.append((target, "biolink:Attribute"))
    summary, detail = run_review(source(tmp_path, rows, nodes), tmp_path)
    assert len(rows) == len(REPORTED_METABOLISM_ANNOTATIONS)
    assert summary["edges"] == len(rows)
    assert summary["edge_rows_by_facet"] == {"source_attribute": len(rows)}
    assert summary["edge_rows_by_disposition"] == {"reported_group_or_unspecified_metabolism": len(rows)}
    expected = {row["source_column"] + ":" + row["value"]: row for row in rows}
    for actual in detail:
        original = expected[actual["source_column"] + ":" + actual["value"]]
        assert all(actual[key] == original[key] for key in EDGE_FIELDS if key not in {"subject", "source_record"})


@pytest.mark.parametrize("column", sorted(set(inventory.GROUP_ROLES) | set(BACDIVE_SNAPSHOT_COLUMNS)))
def test_every_scientific_source_role_rejects_another_primary_source(tmp_path, column):
    """The source-column contract applies to products, substrates and unmapped roles too."""
    row = edge(column, "fixture value", "kgmicrobe.source_attribute:fixture", primary_knowledge_source="infores:wrong")
    source_dir = source(tmp_path, [row], [(row["object"], "biolink:Attribute")])
    with pytest.raises(ValueError, match="Scientific source provenance"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_reviewed_process_target_does_not_hide_wrong_primary_source(tmp_path):
    """An otherwise valid reviewed FAPROTAX mapping cannot adopt false provenance."""
    row = process("fermentation", "METPO:1002005")
    row["primary_knowledge_source"] = "infores:wrong-source"
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Scientific source provenance"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


@pytest.mark.parametrize(
    "category",
    [
        "",
        "biolink:Attribute",
        "biolink:PhenotypicQuality",
        "biolink:OrganismTaxon",
        "biolink:BiologicalProcess",
        "biolink:MolecularActivity",
        "biolink:Procedure",
        "biolink:ChemicalEntity|biolink:Attribute",
    ],
)
def test_local_compounds_reject_obviously_nonmaterial_declarations(tmp_path, category):
    """Do not classify a reported attribute, process, taxon or procedure as a retained material."""
    target = "kgmicrobe.compound:fixture"
    row = edge(
        "Bergey_Substrates_for_end_products",
        "fixture",
        target,
        predicate="biolink:consumes",
        relation="RO:0002438",
    )
    source_dir = source(tmp_path, [row], [(target, category)])
    with pytest.raises(ValueError, match="Nonmaterial local declaration"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("column", ["Bergey_Substrates_for_end_products", "Bergey_Major_end_products"])
@pytest.mark.parametrize(
    "category",
    [
        "biolink:Attribute",
        "biolink:PhenotypicQuality",
        "biolink:OrganismTaxon",
        "biolink:BiologicalProcess",
        "biolink:MolecularActivity",
        "biolink:Procedure",
        "biolink:ChemicalEntity|biolink:Attribute",
        "biolink:ChemicalMixture| biolink:OrganismTaxon ",
    ],
)
def test_external_chemical_roles_reject_explicit_nonmaterial_declarations(tmp_path, column, category):
    """An external-looking ID does not override its explicit contradictory category (#1215)."""
    substrate = column == "Bergey_Substrates_for_end_products"
    row = edge(
        column,
        "glucose",
        "CHEBI:17234",
        predicate="biolink:consumes" if substrate else "biolink:produces",
        relation="RO:0002438" if substrate else "RO:0002234",
    )
    source_dir = source(tmp_path, [row], [(row["object"], category)])
    with pytest.raises(ValueError, match="Nonmaterial external declaration"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize(
    "category", [None, "", "biolink:ChemicalEntity", "biolink:ChemicalMixture", "biolink:OntologyClass"]
)
def test_external_chemical_inventory_does_not_invent_or_narrow_authority_categories(tmp_path, category):
    """Reject contradictions without requiring external declarations or reviewing identity (#1215)."""
    row = edge(
        "Bergey_Substrates_for_end_products",
        "reported material",
        "CHEBI:17234",
        predicate="biolink:consumes",
        relation="RO:0002438",
    )
    nodes = [] if category is None else [(row["object"], category)]
    summary, rows = run_review(source(tmp_path, [row], nodes), tmp_path)
    assert summary["edge_rows_by_disposition"] == {"existing_chemical_mapping": 1}
    assert rows[0]["object_category"] == (category or "")


@pytest.mark.parametrize("applied", [False, True])
def test_reviewed_phenotype_groundings_are_inventory_annotations_not_extra_graph_edges(tmp_path, applied):
    """Account for every reviewed literal while preserving its actual source Attribute assertion."""
    with DEFAULT_PHENOTYPE_MAPPINGS.open(newline="") as stream:
        mappings = list(csv.DictReader(stream, delimiter="\t"))
    rows, nodes = [], []
    for index, mapping in enumerate(mappings):
        target = f"kgmicrobe.source_attribute:phenotype_{index}"
        rows.append(edge(mapping["source_column"], mapping["source_literal"], target))
        nodes.append((target, "biolink:Attribute", mapping["target_curie"] if applied else ""))
    source_dir = source(tmp_path, rows, nodes)
    summary, detail = run_review(source_dir, tmp_path)
    assert summary["edges"] == len(mappings)
    assert summary["edge_rows_by_facet"] == {"source_attribute": len(mappings)}
    disposition = "reviewed_attribute_type" if applied else "reviewed_attribute_type_not_applied"
    assert summary["edge_rows_by_disposition"] == {disposition: len(mappings)}
    assert summary["typed_attribute_nodes"] == (len(mappings) if applied else 0)
    assert all(row["predicate"] == "biolink:has_attribute" for row in detail)
    assert all(row["object"].startswith("kgmicrobe.source_attribute:") for row in detail)
    assert all(row["object_category"] == "biolink:Attribute" for row in detail)
    for row in detail:
        predicted = row["source_column"] == "FAPROTAX_Type_of_metabolism"
        assert row["primary_knowledge_source"] == ("infores:faprotax" if predicted else "infores:microbedecoder")
        assert row["knowledge_level"] == ("prediction" if predicted else "knowledge_assertion")
        assert bool(row["object_attribute_type"]) == applied
    assert "not additional graph phenotype assertions" in summary["limitations"][0]


def test_report_only_phenotype_mapping_does_not_authorize_has_phenotype(tmp_path):
    """Reject replacing a preserved snapshot attribute with an unapproved phenotype edge."""
    row = edge("BacDive_Gram_stain", "positive", "METPO:1000698", predicate="biolink:has_phenotype")
    source_dir = source(tmp_path, [row])
    with pytest.raises(ValueError, match="Reported source attribute lost"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


@pytest.mark.parametrize("attribute_type", ["METPO:1000699", " METPO:1000698", "METPO:1000698|METPO:1000699"])
def test_inventory_rejects_unreviewed_conflicting_or_multivalued_attribute_type(tmp_path, attribute_type):
    """A node slot must express exactly the field/literal mapping, not a guessed type."""
    target = "kgmicrobe.source_attribute:gram_positive"
    row = edge("BacDive_Gram_stain", "positive", target)
    source_dir = source(tmp_path, [row], [(target, "biolink:Attribute", attribute_type)])
    with pytest.raises(ValueError, match="Unsupported reported attribute type"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_attribute_type_requires_matching_field_on_every_observation(tmp_path):
    """A shared reported node may not leak a typed Gram result into an unrelated field."""
    target = "kgmicrobe.source_attribute:shared_wrongly"
    rows = [edge("BacDive_Gram_stain", "positive", target), edge("BacDive_Cell_shape", "positive", target)]
    source_dir = source(tmp_path, rows, [(target, "biolink:Attribute", "METPO:1000698")])
    with pytest.raises(ValueError, match="Unsupported reported attribute type"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


def test_orphan_or_nonattribute_type_metadata_cannot_escape_inventory(tmp_path):
    """No unused node property can be silently counted as a validated grounding."""
    source_dir = source(tmp_path, [], [("kgmicrobe.source_attribute:orphan", "biolink:Attribute", "METPO:1000698")])
    with pytest.raises(ValueError, match="lack validating source-field observations"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


@pytest.mark.parametrize("field", ["attribute_type_source", "attribute_type_evidence", "attribute_type_rationale"])
def test_type_grounding_requires_its_exact_curation_provenance(tmp_path, field):
    """A correct target cannot launder missing or altered curation evidence."""
    target = "kgmicrobe.source_attribute:gram_positive"
    row = edge("BacDive_Gram_stain", "positive", target)
    source_dir = source(tmp_path, [row], [(target, "biolink:Attribute", "METPO:1000698", {field: ""})])
    with pytest.raises(ValueError, match="lost its curation evidence"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


@pytest.mark.parametrize(
    "provider",
    [None, "", "infores:bacdive", "Graph", "infores:microbedecoder|infores:bacdive", " infores:microbedecoder"],
)
def test_typed_source_nodes_require_original_node_provider(tmp_path, provider):
    """Type-curation metadata and edge provenance cannot mask lost node ownership (#1219)."""
    target = "kgmicrobe.source_attribute:gram_positive"
    row = edge("BacDive_Gram_stain", "positive", target)
    source_dir = source(
        tmp_path,
        [row],
        [(target, "biolink:Attribute", "METPO:1000698", {"provided_by": provider or ""})],
    )
    if provider is None:
        with (source_dir / "nodes.tsv").open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields = [field for field in reader.fieldnames if field != "provided_by"]
            nodes = [{key: value for key, value in node.items() if key != "provided_by"} for node in reader]
        write_tsv(source_dir / "nodes.tsv", fields, nodes)
    with pytest.raises(ValueError, match="Typed source Attribute node lost its provider"):
        legacy_review(source_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_untyped_legacy_inventory_does_not_require_new_node_provenance_field(tmp_path):
    """Restrict the new ownership guard to the typed-source contract under review."""
    target = "kgmicrobe.source_attribute:motility_unreviewed"
    source_dir = source(tmp_path, [edge("BacDive_Motility", "unreviewed", target)])
    write_tsv(source_dir / "nodes.tsv", ["id", "category"], [{"id": target, "category": "biolink:Attribute"}])
    summary, _ = run_review(source_dir, tmp_path)
    assert summary["typed_attribute_nodes"] == 0
    assert summary["edge_rows_by_disposition"] == {"reported_phenotype_code": 1}


def test_real_producer_typed_node_provider_survives_inventory(monkeypatch, tmp_path):
    """Validate actual producer ownership separately from FAPROTAX prediction provenance."""
    from tests.test_microbedecoder_context import read_tsv, run_fixture

    transform, nodes, _ = run_fixture(tmp_path, "typed_source_attributes.csv", monkeypatch=monkeypatch)
    typed = [row for row in nodes if row["has_attribute_type"]]
    assert typed and all(row["provided_by"] == "infores:microbedecoder" for row in typed)
    authority = transform.output_dir.parent / "ontologies/metpo_nodes.tsv"
    summary = inventory.review(transform.output_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
    assert summary["typed_attribute_nodes"] == len(typed)
    assert summary["faprotax_scope"] == "current_finite_policy"
    assert summary["source_admission_claimed"] is False
    # A correct curation provider and unchanged edge tier do not excuse loss of
    # the source node's owner after serialization or another processing step.
    typed[0]["provided_by"] = "infores:bacdive"
    write_tsv(transform.output_node_file, list(nodes[0]), nodes)
    with pytest.raises(ValueError, match="Typed source Attribute node lost its provider"):
        inventory.review(
            transform.output_dir,
            tmp_path / "corrupted-inventory",
            DEFAULT_PROCESS_MAPPINGS,
            authority,
        )
    assert not (tmp_path / "corrupted-inventory").exists()
    assert read_tsv(tmp_path / "inventory" / "curation_inventory.tsv")


def current_authority(tmp_path):
    """Combine immutable native excerpts privately without altering the historical authority."""
    directory = tmp_path / "current-authority"
    directory.mkdir(exist_ok=True)
    target = directory / "metpo_nodes.tsv"
    target.write_bytes(
        AUTHORITY.read_bytes() + (AUTHORITY.parent / "faprotax_1847_metpo_nodes.tsv").read_bytes().split(b"\n", 1)[1]
    )
    (directory / "go_nodes.tsv").write_bytes((AUTHORITY.parent / "go_nodes.tsv").read_bytes())
    return target


def current_source(tmp_path, literal="chemoheterotrophy"):
    """Build a small current-policy source declaration with independently mutable serialized cells."""
    with fap.DEFAULT_DISPOSITIONS.open(newline="") as stream:
        rule = next(row for row in csv.DictReader(stream, delimiter="\t") if row["source_literal"] == literal)
    target = observation_audit.source_attribute_curie(fap.COLUMN, literal)
    row = edge(fap.COLUMN, literal, target)
    metadata = {
        "attribute_type_source": ATTRIBUTE_TYPE_CURATION_SOURCE,
        "attribute_type_evidence": rule["evidence_uri"],
        "attribute_type_rationale": rule["curation_rationale"],
    }
    nodes = (
        [(target, "biolink:Attribute", rule["target_curie"], metadata)] if rule["disposition"] == "prediction" else []
    )
    return source(tmp_path, [row], nodes), current_authority(tmp_path)


@pytest.mark.parametrize("literal", sorted(fap.REVIEWED_LITERALS))
def test_current_finite_inventory_distinguishes_all_thirty_dispositions(tmp_path, literal):
    """Only the twenty reviewed qualified Attribute types can be counted as graph assertions."""
    from tests.test_microbedecoder_faprotax_dispositions import AUDIT_ONLY, TARGETS

    directory, authority = current_source(tmp_path, literal)
    if literal in AUDIT_ONLY:
        with pytest.raises(ValueError, match="audit-only FAPROTAX"):
            inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
        assert not (tmp_path / "inventory").exists()
    else:
        summary = inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
        assert summary["edge_rows_by_disposition"] == {"reviewed_attribute_type": 1}
        assert summary["typed_attribute_nodes"] == 1
        assert summary["faprotax_scope"] == "current_finite_policy"
        assert summary["source_admission_claimed"] is False
        assert (
            summary["inputs"]["faprotax_dispositions"]["sha256"]
            == hashlib.sha256(fap.DEFAULT_DISPOSITIONS.read_bytes()).hexdigest()
        )
        rows = list(inventory._rows(tmp_path / "inventory/curation_inventory.tsv", {"object_attribute_type"}))
        assert rows[0]["object_attribute_type"] == TARGETS[literal]
        assert rows[0]["value"] == literal
        assert rows[0]["knowledge_level"] == "prediction"
        assert rows[0]["agent_type"] == "computational_model"


@pytest.mark.parametrize(
    "field,value",
    [
        ("attribute_type_source", "https://example.org/wrong"),
        ("attribute_type_evidence", "https://example.org/wrong"),
        ("attribute_type_rationale", "different claim"),
        ("has_attribute_type", "METPO:1000656"),
        ("category", "biolink:PhenotypicQuality"),
        ("provided_by", "infores:faprotax"),
        ("legacy_metadata", ""),
    ],
)
def test_current_faprotax_typing_refuses_changed_or_legacy_proof(tmp_path, field, value):
    """A matching CURIE cannot excuse stale curation proof, wrong type or node ownership."""
    directory, authority = current_source(tmp_path)
    rows = list(inventory._rows(directory / "nodes.tsv", {"id"}))
    if field == "legacy_metadata":
        with DEFAULT_PHENOTYPE_MAPPINGS.open(newline="") as stream:
            old = next(
                row for row in csv.DictReader(stream, delimiter="\t") if row["source_literal"] == "chemoheterotrophy"
            )
        assert rows[0]["has_attribute_type"] == old["target_curie"]
        rows[0]["attribute_type_evidence"] = old["evidence_uri"]
        rows[0]["attribute_type_rationale"] = old["curation_rationale"]
    else:
        rows[0][field] = value
    write_tsv(directory / "nodes.tsv", list(rows[0]), rows)
    with pytest.raises(ValueError, match="Unsupported reported|lost its curation evidence|lost its provider"):
        inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_column", "Bergey_Type_of_metabolism"),
        ("value", "aerobic_chemoheterotrophy"),
        ("predicate", "biolink:has_phenotype"),
        ("relation", "RO:0002215"),
        ("knowledge_level", "knowledge_assertion"),
        ("agent_type", "manual_agent"),
        ("primary_knowledge_source", "infores:microbedecoder"),
        ("source_record", ""),
        ("subject", "CHEBI:17234"),
    ],
)
def test_current_faprotax_inventory_preserves_scientific_assertion_context(tmp_path, field, value):
    """A reviewed type never licenses another field, literal, predicate or evidence tier."""
    directory, authority = current_source(tmp_path)
    rows = list(inventory._rows(directory / "edges.tsv", {"subject"}))
    rows[0][field] = value
    write_tsv(directory / "edges.tsv", list(rows[0]), rows)
    with pytest.raises(ValueError):
        inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("mode", ["node", "foreign_forward", "foreign_inverse"])
def test_current_audit_only_attribute_cannot_reenter_inventory(tmp_path, mode):
    """Known audit-only Attribute identities remain protected independently of edge metadata."""
    target = observation_audit.source_attribute_curie(fap.COLUMN, "phototrophy")
    row = edge("BacDive_Motility", "0", target)
    if mode == "foreign_inverse":
        row["subject"], row["object"] = row["object"], row["subject"]
    directory = source(
        tmp_path, [] if mode == "node" else [row], [(target, "biolink:Attribute")] if mode == "node" else []
    )
    with pytest.raises(ValueError, match="Current .*FAPROTAX"):
        inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, current_authority(tmp_path))


@pytest.mark.parametrize("shape", ["contract", "null_contract", "consumed_role_only"])
def test_legacy_inventory_refuses_current_epoch_even_if_contract_is_damaged(tmp_path, shape):
    """Historical diagnostic selection cannot bypass an explicitly recorded current producer epoch."""
    directory = source(tmp_path, [])
    report = {"producer_native_inputs": {}, "consumed_inputs": {}}
    if shape == "consumed_role_only":
        report["consumed_inputs"][fap.ROLE] = {"sha256": "f" * 64}
    else:
        report["producer_native_inputs"][fap.CONTRACT_KEY] = {} if shape == "contract" else None
    (directory / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Legacy inventory cannot review"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("changed", [None, "policy", "authority", "contract"])
def test_current_inventory_binds_recorded_policy_and_authority(tmp_path, changed):
    """Selected policy and native authority must equal the producer's actual consumed identities."""
    directory, authority = current_source(tmp_path)
    policy_sha = hashlib.sha256(fap.DEFAULT_DISPOSITIONS.read_bytes()).hexdigest()
    report = {
        "producer_native_inputs": {fap.CONTRACT_KEY: {"policy_sha256": policy_sha}},
        "consumed_inputs": {
            fap.ROLE: {"sha256": policy_sha},
            "process_authority": {"sha256": hashlib.sha256(authority.read_bytes()).hexdigest()},
        },
    }
    if changed == "contract":
        report["producer_native_inputs"][fap.CONTRACT_KEY]["policy_sha256"] = "f" * 64
    elif changed is not None:
        report["consumed_inputs"][fap.ROLE if changed == "policy" else "process_authority"]["sha256"] = "f" * 64
    path = directory / "source_finalization.json"
    path.write_text(json.dumps(report))
    if changed is None:
        summary = inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
        assert summary["inputs"]["source_finalization"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert summary["source_admission_claimed"] is False
    else:
        with pytest.raises(ValueError, match="differs from"):
            inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)


def test_explicit_legacy_scope_remains_diagnostics_only(tmp_path):
    """Preserve older reports without presenting their accepted metadata as the current policy."""
    target = "kgmicrobe.source_attribute:old_phototrophy"
    directory = source(tmp_path, [edge(fap.COLUMN, "phototrophy", target)], [(target, "biolink:Attribute")])
    summary, _ = run_review(directory, tmp_path)
    assert summary["faprotax_scope"] == "historical_diagnostics_only"
    assert summary["source_admission_claimed"] is False
    assert "faprotax_dispositions" not in summary["inputs"]


def img_source(tmp_path):
    """Declare the exact source Genome and taxon separately from its membership assertion."""
    row = edge(
        "", "", "lpsn:1", subject="IMG:123", predicate="biolink:in_taxon", relation="RO:0002162", value_encoding=""
    )
    directory = source(tmp_path, [row], [("IMG:123", "biolink:Genome"), ("lpsn:1", "biolink:OrganismTaxon")])
    return directory


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing_genome",
        "wrong_genome",
        "wrong_taxon",
        "inverse",
        "equivalence",
        "context",
        "provenance",
        "record",
    ],
)
def test_img_inventory_requires_declared_genome_membership(tmp_path, mutation):
    """Only declared Genome-to-taxon membership enters the new crosswalk inventory branch."""
    directory = img_source(tmp_path)
    edges = list(inventory._rows(directory / "edges.tsv", {"subject"}))
    nodes = list(inventory._rows(directory / "nodes.tsv", {"id"}))
    if mutation == "missing_genome":
        nodes.pop(0)
    elif mutation == "wrong_genome":
        nodes[0]["category"] = "biolink:OrganismTaxon"
    elif mutation == "wrong_taxon":
        nodes[1]["category"] = "biolink:Genome"
    elif mutation == "inverse":
        edges[0]["subject"], edges[0]["object"] = edges[0]["object"], edges[0]["subject"]
    elif mutation == "equivalence":
        edges[0]["predicate"], edges[0]["relation"] = "biolink:close_match", "skos:closeMatch"
    elif mutation == "context":
        edges[0]["value"] = "new assertion"
    elif mutation == "provenance":
        edges[0]["knowledge_level"] = "prediction"
    elif mutation == "record":
        edges[0]["source_record"] = ""
    write_tsv(directory / "edges.tsv", EDGE_FIELDS, edges)
    write_tsv(directory / "nodes.tsv", list(nodes[0]), nodes)
    if mutation is None:
        summary, rows = run_review(directory, tmp_path)
        assert summary["edge_rows_by_facet"] == {"crosswalk": 1} and rows == []
    else:
        with pytest.raises(ValueError, match="invalid native crosswalk"):
            legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


def test_real_producer_img_declarations_can_be_inventoried(tmp_path, monkeypatch):
    """Exercise the real producer, including an explicitly unsupplied named LPSN stub."""
    from tests.microbedecoder_inactive_join_fixtures import bind_inactive_join_policy
    from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
    from tests.test_microbedecoder_curation_integration import _transform, _write_source

    transform = _transform(tmp_path)
    lpsn = tmp_path / "lpsn"
    lpsn.mkdir()
    write_tsv(lpsn / "nodes.tsv", ["id", "category"], [{"id": "lpsn:999", "category": "biolink:OrganismTaxon"}])
    path = _write_source(
        tmp_path, [{"LPSN_ID": "101", "IMG_Genome_ID": "123", "LPSN_Genus": "Example", "LPSN_Species": "species"}]
    )
    bind_fixture_quarantine_policy(transform, path)
    bind_inactive_join_policy(transform, path, monkeypatch)
    transform.run(path)
    summary = inventory.review(
        transform.output_dir, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, tmp_path / "ontologies/metpo_nodes.tsv"
    )
    assert summary["edges"] == 1 and summary["edge_rows_by_facet"] == {"crosswalk": 1}
    assert summary["source_admission_claimed"] is False


def gold_source(tmp_path, gold_identifier="Go1", *, duplicate_observation=False):
    """Retain full native GOLD before/after claims in the producer's literal audit dialect."""
    original = {field: "" for field in inventory._GOLD_NATIVE_FIELDS}
    original.update(
        edge("", "", "gold:Go1", predicate="biolink:close_match", relation="skos:closeMatch", value_encoding="")
    )
    emitted = {
        **original,
        "predicate": "biolink:related_to",
        "relation": "biolink:related_to",
        "source_column": "GOLD_Organism_ID",
        "value": gold_identifier,
        "value_encoding": "backslash",
    }
    native_cell = gold_identifier + "," + gold_identifier if duplicate_observation else gold_identifier
    audit = {
        "source_record": original["source_record"],
        "source_column": "GOLD_Organism_ID",
        "source_cell_json": json.dumps(native_cell),
        "source_token_json": json.dumps(gold_identifier),
        "native_record_json": json.dumps({"GOLD_Organism_ID": native_cell}),
        "original_claim_json": json.dumps(original),
        "emitted_claim_json": json.dumps(emitted),
        "gold_declaration_json": json.dumps({"id": "gold:Go1", "category": "biolink:NamedThing"}),
        "gold_native_node_json": json.dumps({"row": {"id": "gold:Go1"}}),
        "gold_evidence_sha256": "a" * 64,
    }
    directory = source(tmp_path, [], [("gold:Go1", "biolink:NamedThing"), ("lpsn:1", "biolink:OrganismTaxon")])
    literal_tsv(directory / "edges.tsv", [{**emitted, "original_subject": ""}])
    literal_tsv(directory / "gold_crosswalk_dispositions.tsv", [audit] * (2 if duplicate_observation else 1))
    return directory


def literal_tsv(path, rows):
    """Write complete JSON-bearing audit cells with the actual source QUOTE_NONE dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            quotechar=None,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("token", ["Go1", "gold:Go1", "GOLD:Go1"])
def test_gold_association_inventory_requires_complete_audit_and_keeps_native_token(tmp_path, token):
    """Native prefix normalization does not invent an identity assertion or erase the original token."""
    directory = gold_source(tmp_path, token, duplicate_observation=True)
    summary, detail = run_review(directory, tmp_path)
    assert summary["edges"] == 1 and detail == []
    assert summary["edge_rows_by_disposition"] == {"audited_unresolved_gold_association": 1}
    assert (
        summary["inputs"]["gold_crosswalk_dispositions"]["sha256"]
        == hashlib.sha256((directory / "gold_crosswalk_dispositions.tsv").read_bytes()).hexdigest()
    )
    assert summary["source_admission_claimed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_audit",
        "target",
        "predicate",
        "provenance",
        "record",
        "value",
        "extension",
        "unknown_field",
        "missing_field",
        "duplicate_graph",
        "missing_graph",
        "changed_audit",
        "wrong_category",
    ],
)
def test_gold_inventory_refuses_missing_or_mismatched_complete_audit(tmp_path, mutation):
    """A generic related_to edge, equal counts or partial tuple match cannot substitute for retained claims."""
    directory = gold_source(tmp_path)
    path = directory / "edges.tsv"
    rows = list(inventory._rows(path, {"subject"}))
    if mutation == "missing_audit":
        (directory / "gold_crosswalk_dispositions.tsv").unlink()
    elif mutation == "changed_audit":
        audit_path = directory / "gold_crosswalk_dispositions.tsv"
        audits = list(inventory._rows(audit_path, {"source_record"}))
        emitted = json.loads(audits[0]["emitted_claim_json"])
        emitted["source_record"] = "sha256:other#record=1"
        audits[0]["emitted_claim_json"] = json.dumps(emitted)
        literal_tsv(audit_path, audits)
    elif mutation == "wrong_category":
        nodes = list(inventory._rows(directory / "nodes.tsv", {"id"}))
        nodes[0]["category"] = "biolink:OrganismTaxon"
        write_tsv(directory / "nodes.tsv", list(nodes[0]), nodes)
    else:
        if mutation == "target":
            rows[0]["object"] = "gold:Go2"
        elif mutation == "predicate":
            rows[0]["predicate"] = "biolink:close_match"
        elif mutation == "provenance":
            rows[0]["knowledge_level"] = "prediction"
        elif mutation == "record":
            rows[0]["source_record"] = "sha256:other#record=1"
        elif mutation == "value":
            rows[0]["value"] = "Go2"
        elif mutation == "extension":
            rows[0]["original_subject"] = "lpsn:2"
        elif mutation == "unknown_field":
            rows[0]["unknown"] = ""
        elif mutation == "missing_field":
            rows[0].pop("source_citation_base64")
        elif mutation == "duplicate_graph":
            rows.append(dict(rows[0]))
        elif mutation == "missing_graph":
            path.write_text(path.read_text().splitlines()[0] + "\n")
        if mutation != "missing_graph":
            literal_tsv(path, rows)
    with pytest.raises(ValueError, match="GOLD"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_current_inventory_policy_drift_refuses_publication(tmp_path, monkeypatch):
    """The selected finite policy remains byte-bound through the final report boundary."""
    directory, authority = current_source(tmp_path)
    original = inventory.fingerprint
    reads = 0

    def changed_policy(path):
        """Simulate only a changed second fingerprint without mutating tracked policy bytes."""
        nonlocal reads
        result = original(path)
        if path == fap.DEFAULT_DISPOSITIONS:
            reads += 1
            if reads == 2:
                return {**result, "sha256": "f" * 64}
        return result

    monkeypatch.setattr(inventory, "fingerprint", changed_policy)
    with pytest.raises(ValueError, match="Inputs changed"):
        inventory.review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, authority)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("name", ["source_finalization.json", "gold_crosswalk_dispositions.tsv"])
def test_optional_inventory_input_appearing_during_read_refuses_publication(tmp_path, monkeypatch, name):
    """Absent completion/audit evidence cannot arrive unbound and change the selected review epoch."""
    directory = source(tmp_path, [])
    original = inventory.fingerprint
    created = False

    def create_after_selection(path):
        """Introduce only an owned fixture file after optional-input selection, without touching production."""
        nonlocal created
        result = original(path)
        if path == directory / "edges.tsv" and not created:
            (directory / name).write_text(json.dumps({"producer_native_inputs": {fap.CONTRACT_KEY: None}}))
            created = True
        return result

    monkeypatch.setattr(inventory, "fingerprint", create_after_selection)
    with pytest.raises(ValueError, match="Optional inventory input presence changed"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize(
    "local_category,upstream_category,accepted",
    [
        ("biolink:OrganismTaxon", None, True),
        (None, "biolink:OrganismTaxon", True),
        ("biolink:OrganismTaxon", "biolink:OrganismTaxon", True),
        (None, None, False),
        ("biolink:Genome", None, False),
        (None, "biolink:Genome", False),
        ("biolink:Genome", "biolink:OrganismTaxon", False),
        ("biolink:OrganismTaxon", "biolink:Genome", False),
    ],
)
def test_img_inventory_resolves_only_explicit_local_or_fixed_sibling_taxa(
    tmp_path, local_category, upstream_category, accepted
):
    """Respect delegated LPSN ownership without hiding absent, wrong or conflicting declarations."""
    directory = img_source(tmp_path)
    nodes = [{"id": "IMG:123", "category": "biolink:Genome"}]
    if local_category is not None:
        nodes.append({"id": "lpsn:1", "category": local_category})
    write_tsv(directory / "nodes.tsv", ["id", "category"], nodes)
    sibling = tmp_path / "lpsn/nodes.tsv"
    if upstream_category is not None:
        sibling.parent.mkdir()
        write_tsv(sibling, ["id", "category"], [{"id": "lpsn:1", "category": upstream_category}])
    if not accepted:
        with pytest.raises(ValueError, match="invalid native crosswalk"):
            legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
        assert not (tmp_path / "inventory").exists()
        return
    summary, rows = run_review(directory, tmp_path)
    assert summary["edges"] == 1 and rows == []
    assert summary["lpsn_declaration_scope"] == {
        "selector": str(sibling.absolute()),
        "present": upstream_category is not None,
        "binding": "direct_inventory_dependency_capture",
        "finalizer_consumed_role_claimed": False,
    }
    if upstream_category is not None:
        assert summary["inputs"]["lpsn_declarations"] == inventory.fingerprint(sibling)
    else:
        assert "lpsn_declarations" not in summary["inputs"]
    assert summary["source_admission_claimed"] is False


@pytest.mark.parametrize("category", ["biolink:OrganismTaxon", "biolink:Genome"])
def test_img_inventory_refuses_duplicate_sibling_declarations(tmp_path, category):
    """Even duplicate apparently agreeing IDs cannot create an ambiguous authority lookup."""
    directory = img_source(tmp_path)
    sibling = tmp_path / "lpsn/nodes.tsv"
    sibling.parent.mkdir()
    write_tsv(
        sibling,
        ["id", "category"],
        [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}, {"id": "lpsn:1", "category": category}],
    )
    with pytest.raises(ValueError, match="duplicate sibling LPSN"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


def test_img_inventory_does_not_search_alternative_upstream_directories(tmp_path):
    """An unrelated same-named declaration cannot stand in for the producer's selected sibling."""
    directory = img_source(tmp_path)
    write_tsv(directory / "nodes.tsv", ["id", "category"], [{"id": "IMG:123", "category": "biolink:Genome"}])
    alternative = tmp_path / "elsewhere/lpsn/nodes.tsv"
    alternative.parent.mkdir(parents=True)
    write_tsv(alternative, ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    with pytest.raises(ValueError, match="invalid native crosswalk"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)


def test_img_inventory_refuses_sibling_appearing_during_read(tmp_path, monkeypatch):
    """Capture dependency absence as well as bytes so a late authority cannot enter unbound."""
    directory = img_source(tmp_path)
    sibling = tmp_path / "lpsn/nodes.tsv"
    original = inventory.fingerprint
    created = False

    def create_dependency_after_selection(path):
        """Introduce a private fixture sibling after presence selection and before row classification."""
        nonlocal created
        result = original(path)
        if path == directory / "edges.tsv" and not created:
            sibling.parent.mkdir()
            write_tsv(sibling, ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
            created = True
        return result

    monkeypatch.setattr(inventory, "fingerprint", create_dependency_after_selection)
    with pytest.raises(ValueError, match="Optional inventory input presence changed: lpsn_declarations"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_img_inventory_refuses_changed_sibling_bytes(tmp_path, monkeypatch):
    """A still-correct target category cannot conceal any change to captured upstream bytes."""
    directory = img_source(tmp_path)
    sibling = tmp_path / "lpsn/nodes.tsv"
    sibling.parent.mkdir()
    write_tsv(sibling, ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    original = inventory.fingerprint
    changed = False

    def change_dependency_after_capture(path):
        """Append a different valid declaration after the original private file is fingerprinted."""
        nonlocal changed
        result = original(path)
        if path == sibling and not changed:
            with sibling.open("a") as stream:
                stream.write("lpsn:2\tbiolink:OrganismTaxon\n")
            changed = True
        return result

    monkeypatch.setattr(inventory, "fingerprint", change_dependency_after_capture)
    with pytest.raises(ValueError, match="Inputs changed"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_img_inventory_refuses_linked_selected_sibling(tmp_path):
    """The actual sibling selector cannot be redirected through a linked declaration table."""
    directory = img_source(tmp_path)
    replacement = tmp_path / "replacement.tsv"
    write_tsv(replacement, ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    sibling = tmp_path / "lpsn/nodes.tsv"
    sibling.parent.mkdir()
    sibling.symlink_to(replacement)
    with pytest.raises(ValueError, match="Linked optional inventory input"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def test_img_inventory_refuses_sibling_disappearing_after_classification(tmp_path, monkeypatch):
    """A declaration used successfully must still exist unchanged at the publication boundary."""
    directory = img_source(tmp_path)
    write_tsv(directory / "nodes.tsv", ["id", "category"], [{"id": "IMG:123", "category": "biolink:Genome"}])
    sibling = tmp_path / "lpsn/nodes.tsv"
    sibling.parent.mkdir()
    write_tsv(sibling, ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    original = inventory.classify

    def remove_after_successful_lookup(*args, **kwargs):
        """Remove only the private authority after its exact declaration has validated the fixture edge."""
        result = original(*args, **kwargs)
        assert result == ("crosswalk", "existing_crosswalk")
        sibling.unlink()
        return result

    monkeypatch.setattr(inventory, "classify", remove_after_successful_lookup)
    with pytest.raises(ValueError, match="Optional inventory input presence changed: lpsn_declarations"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


def assembly_source(tmp_path, identifier="ncbi.assembly:GCA_000007325.1"):
    """Represent one exact versioned native assembly membership without changing its accession."""
    directory = img_source(tmp_path)
    rows = list(inventory._rows(directory / "edges.tsv", {"subject"}))
    rows[0]["subject"] = identifier
    write_tsv(directory / "edges.tsv", EDGE_FIELDS, rows)
    write_tsv(
        directory / "nodes.tsv",
        ["id", "category"],
        [{"id": identifier, "category": "biolink:Genome"}, {"id": "lpsn:1", "category": "biolink:OrganismTaxon"}],
    )
    return directory


@pytest.mark.parametrize(
    "local_category,upstream_category,accepted",
    [
        ("biolink:Genome", None, True),
        (None, "biolink:Genome", True),
        ("biolink:Genome", "biolink:Genome", True),
        (None, None, False),
        ("biolink:OrganismTaxon", None, False),
        (None, "biolink:OrganismTaxon", False),
        ("biolink:OrganismTaxon", "biolink:Genome", False),
        ("biolink:Genome", "biolink:OrganismTaxon", False),
    ],
)
def test_assembly_inventory_requires_exact_local_or_selected_gtdb_genome(
    tmp_path, local_category, upstream_category, accepted
):
    """Neither a namespace nor a correct other declaration masks a missing or conflicting Genome."""
    identifier = "ncbi.assembly:GCA_000007325.1"
    directory = assembly_source(tmp_path, identifier)
    nodes = [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}]
    if local_category is not None:
        nodes.append({"id": identifier, "category": local_category})
    write_tsv(directory / "nodes.tsv", ["id", "category"], nodes)
    sibling = tmp_path / "gtdb/nodes.tsv"
    if upstream_category is not None:
        sibling.parent.mkdir()
        write_tsv(sibling, ["id", "category"], [{"id": identifier, "category": upstream_category}])
    if not accepted:
        with pytest.raises(ValueError, match="ncbi.assembly:GCA_000007325.1 biolink:in_taxon lpsn:1"):
            legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
        assert not (tmp_path / "inventory").exists()
        return
    summary, rows = run_review(directory, tmp_path)
    assert summary["edges"] == 1 and rows == []
    assert summary["gtdb_declaration_scope"] == {
        "selector": str(sibling.absolute()),
        "present": upstream_category is not None,
        "binding": "direct_inventory_dependency_capture",
        "finalizer_consumed_role_claimed": False,
        "aliases_inferred": False,
    }
    if upstream_category is not None:
        assert summary["inputs"]["gtdb_declarations"] == inventory.fingerprint(sibling)
    assert summary["source_admission_claimed"] is False


@pytest.mark.parametrize(
    "identifier,accepted",
    [
        ("ncbi.assembly:GCA_000007325.1", True),
        ("ncbi.assembly:GCF_000007325.2", True),
        ("ncbi.assembly:GCA_000007325", False),
        ("ncbi.assembly:unreviewed", False),
        ("other.assembly:GCA_000007325.1", False),
    ],
)
def test_assembly_inventory_keeps_native_accession_versions_and_prefix(tmp_path, identifier, accepted):
    """Do not invent a version or accept an arbitrary genome namespace as a native assembly."""
    directory = assembly_source(tmp_path, identifier)
    if accepted:
        summary, _ = run_review(directory, tmp_path)
        assert summary["edge_rows_by_facet"] == {"crosswalk": 1}
    else:
        with pytest.raises(ValueError, match="invalid native crosswalk") as error:
            legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
        assert identifier in str(error.value)
        assert "source_record=sha256:fixture#record=1" in str(error.value)


@pytest.mark.parametrize("mutation", ["version", "namespace", "alternative_path", "duplicate", "conflicting_duplicate"])
def test_assembly_inventory_rejects_wrong_or_ambiguous_selected_gtdb_declaration(tmp_path, mutation):
    """Only the fixed sibling's unique exact canonical ID can supply a missing local Genome."""
    identifier = "ncbi.assembly:GCA_000007325.1"
    directory = assembly_source(tmp_path, identifier)
    write_tsv(directory / "nodes.tsv", ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    sibling = tmp_path / ("alternative/gtdb/nodes.tsv" if mutation == "alternative_path" else "gtdb/nodes.tsv")
    sibling.parent.mkdir(parents=True)
    declared = identifier.replace(".1", ".2") if mutation == "version" else identifier
    if mutation == "namespace":
        declared = identifier.replace("GCA", "GCF")
    rows = [{"id": declared, "category": "biolink:Genome"}]
    if mutation in {"duplicate", "conflicting_duplicate"}:
        rows.append(
            {"id": identifier, "category": "biolink:Genome" if mutation == "duplicate" else "biolink:OrganismTaxon"}
        )
    write_tsv(sibling, ["id", "category"], rows)
    with pytest.raises(ValueError, match="invalid native crosswalk|duplicate sibling GTDB"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("mutation", ["appearance", "bytes", "disappearance"])
def test_assembly_inventory_binds_selected_gtdb_presence_and_bytes(tmp_path, monkeypatch, mutation):
    """A valid membership cannot publish if its selected GTDB dependency changes while read."""
    identifier = "ncbi.assembly:GCA_000007325.1"
    directory = assembly_source(tmp_path, identifier)
    sibling = tmp_path / "gtdb/nodes.tsv"
    if mutation != "appearance":
        sibling.parent.mkdir()
        write_tsv(sibling, ["id", "category"], [{"id": identifier, "category": "biolink:Genome"}])
    original_fingerprint, original_classify = inventory.fingerprint, inventory.classify
    changed = False

    def mutate_during_capture(path):
        """Change only private dependency state after initial selection or byte capture."""
        nonlocal changed
        result = original_fingerprint(path)
        if mutation == "appearance" and path == directory / "edges.tsv" and not changed:
            sibling.parent.mkdir()
            write_tsv(sibling, ["id", "category"], [{"id": identifier, "category": "biolink:Genome"}])
            changed = True
        elif mutation == "bytes" and path == sibling and not changed:
            with sibling.open("a") as stream:
                stream.write("ncbi.assembly:GCF_000000002.1\tbiolink:Genome\n")
            changed = True
        return result

    def remove_after_classification(*args, **kwargs):
        """Retain successful actual classification, then remove only the private fixture authority."""
        result = original_classify(*args, **kwargs)
        if mutation == "disappearance":
            sibling.unlink()
        return result

    monkeypatch.setattr(inventory, "fingerprint", mutate_during_capture)
    monkeypatch.setattr(inventory, "classify", remove_after_classification)
    with pytest.raises(ValueError, match="Inputs changed|Optional inventory input presence changed: gtdb_declarations"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert not (tmp_path / "inventory").exists()


@pytest.mark.parametrize("identifier", ["IMG:123", "ncbi.assembly:GCA_000007325.1"])
def test_current_inventory_rejects_obsolete_genome_equivalence_but_preserves_historical_diagnostics(
    tmp_path, identifier
):
    """Current membership semantics never license legacy LPSN-to-genome identity-style assertions."""
    directory = assembly_source(tmp_path, identifier)
    rows = list(inventory._rows(directory / "edges.tsv", {"subject"}))
    rows[0].update(subject="lpsn:1", object=identifier, predicate="biolink:close_match", relation="skos:closeMatch")
    write_tsv(directory / "edges.tsv", EDGE_FIELDS, rows)
    with pytest.raises(ValueError, match="invalid native crosswalk"):
        inventory.review(
            directory, tmp_path / "current-inventory", DEFAULT_PROCESS_MAPPINGS, current_authority(tmp_path)
        )
    assert not (tmp_path / "current-inventory").exists()
    summary, _ = run_review(directory, tmp_path)
    assert summary["faprotax_scope"] == "historical_diagnostics_only"
    assert summary["source_admission_claimed"] is False
    assert summary["edges"] == 1


def test_img_inventory_still_requires_local_genome_despite_selected_gtdb(tmp_path):
    """The assembly dependency cannot stand in for the producer's mandatory IMG declaration."""
    directory = img_source(tmp_path)
    write_tsv(directory / "nodes.tsv", ["id", "category"], [{"id": "lpsn:1", "category": "biolink:OrganismTaxon"}])
    sibling = tmp_path / "gtdb/nodes.tsv"
    sibling.parent.mkdir()
    write_tsv(sibling, ["id", "category"], [{"id": "IMG:123", "category": "biolink:Genome"}])
    with pytest.raises(ValueError, match="IMG:123 biolink:in_taxon lpsn:1"):
        legacy_review(directory, tmp_path / "inventory", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
