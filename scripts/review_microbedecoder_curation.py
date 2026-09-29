"""
Inventory actual MicrobeDecoder assertions without calling every local value unmapped.

Run with ``--source-dir data/transformed/microbedecoder --output-dir <new directory>``.
All edge rows are streamed. Counts describe this exact source output, not unique
organisms, raw emission attempts, experimental confirmation or merged coverage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    ASSAY_CATEGORY,
    ATTRIBUTE_CATEGORY,
    ATTRIBUTE_TYPE_EVIDENCE_COLUMN,
    ATTRIBUTE_TYPE_RATIONALE_COLUMN,
    ATTRIBUTE_TYPE_SOURCE_COLUMN,
    BERGEY_KNOWLEDGE_SOURCE,
    CAPABLE_OF,
    CAPABLE_OF_PREDICATE,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    COMPOUND_PREFIX,
    COMPUTATIONAL_MODEL,
    FAPROTAX_KNOWLEDGE_SOURCE,
    GOLD_PREFIX,
    GTDB_PREFIX,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    HAS_OUTPUT_RELATION,
    IMG_PREFIX,
    KNOWLEDGE_ASSERTION,
    LITERATURE_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    MANUAL_AGENT,
    METABOLISM_CATEGORY,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    MOLECULAR_ACTIVITY_CATEGORY,
    NCBI_ASSEMBLY_PREFIX,
    NCBI_CATEGORY,
    NCBI_TO_SUBSTRATE_EDGE,
    NCBITAXON_PREFIX,
    PATHWAY_PREFIX,
    PHENOTYPIC_CATEGORY,
    PREDICTION,
    PRODUCES_PREDICATE,
    PROVIDED_BY_COLUMN,
    RDFS_SUBCLASS_OF,
    SOURCE_ATTRIBUTE_PREFIX,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    TROPHICALLY_INTERACTS_WITH,
    VPI_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS, ProcessCuration
from kg_microbe.transform_utils.microbedecoder.material_dispositions import (
    DEFAULT_MATERIAL_DISPOSITIONS,
    MaterialDispositionCuration,
)
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    ATTRIBUTE_TYPE_CURATION_SOURCE,
    DEFAULT_PHENOTYPE_MAPPINGS,
    PhenotypeCuration,
)
from kg_microbe.transform_utils.microbedecoder.process_scopes import (
    DEFAULT_PROCESS_SCOPE_DEFINITIONS,
    ProcessScopeCuration,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import is_reported_metabolism_annotation
from kg_microbe.transform_utils.microbedecoder.utils import BACDIVE_SNAPSHOT_COLUMNS, METABOLISM_GROUPS, slugify_label
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.tsv_io import tsv_dict_writer

# This classifies source field roles, NOT the biological meaning of their values.
ATTRIBUTE_ROLES = {
    **dict.fromkeys(
        (
            "BacDive_Cell_length",
            "BacDive_Cell_width",
            "BacDive_Colony_size",
            "BacDive_Incubation_period",
            "BacDive_pH_for_growth",
            "BacDive_Salt_concentration",
            "BacDive_Temperature_for_growth",
        ),
        "reported_measurement",
    ),
    "BacDive_Salt_concentration_unit": "reported_unit",
    **dict.fromkeys(
        ("BacDive_Isolation_category_1", "BacDive_Isolation_category_2", "BacDive_Isolation_category_3"),
        "reported_isolation_context",
    ),
    **dict.fromkeys(
        ("BacDive_Cell_shape", "BacDive_Flagellum_arrangement", "BacDive_Gram_stain", "BacDive_Oxygen_tolerance"),
        "reported_phenotype_description",
    ),
    **dict.fromkeys(
        (
            "BacDive_Motility",
            "BacDive_Spore_formation",
            "BacDive_Pathogenicity_animal",
            "BacDive_Pathogenicity_human",
            "BacDive_Pathogenicity_plant",
        ),
        "reported_phenotype_code",
    ),
    **dict.fromkeys(("BacDive_Indole_test", "BacDive_Voges_proskauer"), "reported_assay_result"),
    **dict.fromkeys(
        (
            "BacDive_Antibiotic_resistance",
            "BacDive_Antibiotic_sensitivity",
            "BacDive_Enzyme_activity",
            "BacDive_Metabolite_production",
            "BacDive_Metabolite_utilization",
        ),
        "reported_assay_label",
    ),
}

GROUP_ROLES = {
    column: (group["group_label"], role)
    for group in METABOLISM_GROUPS
    for role, column in group["columns"].items()
    if role in {"type_of_metabolism", "major_end_products", "minor_end_products", "substrates"}
}

_GROUP_PROVENANCE = {
    "bergey": (BERGEY_KNOWLEDGE_SOURCE, KNOWLEDGE_ASSERTION, MANUAL_AGENT),
    "vpi": (VPI_KNOWLEDGE_SOURCE, KNOWLEDGE_ASSERTION, MANUAL_AGENT),
    "literature": (LITERATURE_KNOWLEDGE_SOURCE, KNOWLEDGE_ASSERTION, MANUAL_AGENT),
    "faprotax": (FAPROTAX_KNOWLEDGE_SOURCE, PREDICTION, COMPUTATIONAL_MODEL),
}
_SCIENTIFIC_PROVENANCE = {
    **dict.fromkeys(ATTRIBUTE_ROLES, (MICROBEDECODER_KNOWLEDGE_SOURCE, KNOWLEDGE_ASSERTION, MANUAL_AGENT)),
    **{column: _GROUP_PROVENANCE[group] for column, (group, _) in GROUP_ROLES.items()},
}
# Reject clear representation contradictions without imposing a new identity
# policy on materials, mixtures, or the native generic OntologyClass category.
_NONMATERIAL_CATEGORIES = frozenset(
    {
        ATTRIBUTE_CATEGORY,
        PHENOTYPIC_CATEGORY,
        NCBI_CATEGORY,
        METABOLISM_CATEGORY,
        MOLECULAR_ACTIVITY_CATEGORY,
        ASSAY_CATEGORY,
    }
)

INVENTORY_FIELDS = [
    "facet",
    "source_column",
    "value",
    "value_encoding",
    "object",
    "object_category",
    "object_attribute_type",
    "predicate",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
    "disposition",
    "material_review_disposition",
    "material_identity_status",
    "material_review_evidence",
    "material_review_rationale",
]
_DERIVED_INVENTORY_FIELDS = {
    "facet",
    "object_category",
    "object_attribute_type",
    "disposition",
    "material_review_disposition",
    "material_identity_status",
    "material_review_evidence",
    "material_review_rationale",
}


def fingerprint(path: Path) -> dict:
    """Bind exact bytes and the selected lexical locator before and after a report."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path.absolute()),
        "resolved_path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
    }


def _rows(path: Path, required: set):
    """Stream literal TSV records, rejecting broken headers and malformed rows."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise ValueError(f"Missing or duplicate required fields in {path}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed TSV row {reader.line_num} in {path}")
            yield row


def classify(
    edge: dict,
    nodes: dict,
    curation: ProcessCuration,
    phenotypes: PhenotypeCuration | None = None,
    attribute_types: dict | None = None,
    attribute_metadata: dict | None = None,
    process_scopes: ProcessScopeCuration | None = None,
    scope_nodes: dict | None = None,
) -> tuple[str, str]:
    """Classify representation, never decode a source token or infer a negative phenotype."""
    column, target = edge["source_column"], edge["object"]
    local_scope = process_scopes.resolve(column, edge["value"]) if process_scopes is not None else None
    if target in (scope_nodes or {}) and (local_scope is None or target != local_scope.curie):
        raise ValueError(f"Source-defined process used outside its exact field/literal: {column}, {target}")
    literal_mapping = phenotypes.resolve(column, edge["value"]) if phenotypes is not None else None
    attribute_type = (attribute_types or {}).get(target, "")
    if attribute_type and (
        literal_mapping is None
        or attribute_type != literal_mapping.target_curie
        or not target.startswith(SOURCE_ATTRIBUTE_PREFIX)
        or nodes.get(target) != ATTRIBUTE_CATEGORY
    ):
        raise ValueError(f"Unsupported reported attribute type: {column}, {target}, {attribute_type}")
    if attribute_type:
        expected_metadata = {
            ATTRIBUTE_TYPE_SOURCE_COLUMN: ATTRIBUTE_TYPE_CURATION_SOURCE,
            ATTRIBUTE_TYPE_EVIDENCE_COLUMN: literal_mapping.evidence_uri,
            ATTRIBUTE_TYPE_RATIONALE_COLUMN: literal_mapping.curation_rationale.replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
            .replace("\n", "\\n"),
        }
        if (attribute_metadata or {}).get(target) != expected_metadata:
            raise ValueError(f"Reported attribute type lost its curation evidence: {column}, {target}")
    if column and (not edge["subject"].strip() or not target.strip()):
        raise ValueError(f"Missing scientific endpoint: {column}, {edge['subject']!r}, {target!r}")
    if column and not edge["source_record"].strip():
        raise ValueError(f"Missing source record for scientific assertion: {column}, {target}")
    expected_provenance = _SCIENTIFIC_PROVENANCE.get(column)
    if expected_provenance is not None:
        actual_provenance = (edge["primary_knowledge_source"], edge["knowledge_level"], edge["agent_type"])
        if actual_provenance != expected_provenance:
            raise ValueError(f"Scientific source provenance changed: {column}, {target}")
    if column == "Bergey_Substrates_for_end_products" and edge["value"] == "Not reported":
        if (
            edge["predicate"] == HAS_ATTRIBUTE_PREDICATE
            and edge["relation"] == HAS_ATTRIBUTE_RELATION
            and target.startswith(SOURCE_ATTRIBUTE_PREFIX)
            and nodes.get(target) == ATTRIBUTE_CATEGORY
        ):
            return "source_attribute", "reported_missing_value"
        return "chemical", "missing_value_misrepresented_as_chemical"
    if column in ATTRIBUTE_ROLES:
        if (
            edge["predicate"] != HAS_ATTRIBUTE_PREDICATE
            or edge["relation"] != HAS_ATTRIBUTE_RELATION
            or not target.startswith(SOURCE_ATTRIBUTE_PREFIX)
            or nodes.get(target) != ATTRIBUTE_CATEGORY
        ):
            raise ValueError(f"Reported source attribute lost its scoped representation: {column}, {target}")
        if literal_mapping is not None:
            return "source_attribute", (
                "reviewed_attribute_type" if attribute_type else "reviewed_attribute_type_not_applied"
            )
        return "source_attribute", ATTRIBUTE_ROLES[column]
    if column in GROUP_ROLES:
        group, role = GROUP_ROLES[column]
        if role == "type_of_metabolism":
            if literal_mapping is not None:
                if (
                    (edge["predicate"], edge["relation"]) == (HAS_ATTRIBUTE_PREDICATE, HAS_ATTRIBUTE_RELATION)
                    and target.startswith(SOURCE_ATTRIBUTE_PREFIX)
                    and nodes.get(target) == ATTRIBUTE_CATEGORY
                ):
                    return "source_attribute", (
                        "reviewed_attribute_type" if attribute_type else "reviewed_attribute_type_not_applied"
                    )
                if (
                    (edge["predicate"], edge["relation"]) == (CAPABLE_OF_PREDICATE, CAPABLE_OF)
                    and target.startswith(PATHWAY_PREFIX)
                    and nodes.get(target) == METABOLISM_CATEGORY
                ):
                    return "process", "reviewed_attribute_route_not_applied"
                raise ValueError(f"Reviewed attribute lost its scoped representation: {column}, {target}")
            if is_reported_metabolism_annotation(column, edge["value"]):
                if (
                    (edge["predicate"], edge["relation"]) == (HAS_ATTRIBUTE_PREDICATE, HAS_ATTRIBUTE_RELATION)
                    and target.startswith(SOURCE_ATTRIBUTE_PREFIX)
                    and nodes.get(target) == ATTRIBUTE_CATEGORY
                ):
                    return "source_attribute", "reported_group_or_unspecified_metabolism"
                if (edge["predicate"], edge["relation"]) == (CAPABLE_OF_PREDICATE, CAPABLE_OF) and nodes.get(
                    target
                ) == METABOLISM_CATEGORY:
                    return "process", "source_annotation_misrepresented_as_process"
                raise ValueError(f"Changed non-process source annotation: {column}, {target}")
            if (edge["predicate"], edge["relation"]) != (CAPABLE_OF_PREDICATE, CAPABLE_OF):
                raise ValueError(f"Unexpected process predicate/relation: {edge['predicate']}, {edge['relation']}")
            mapping = curation.resolve(f"{group}:{role}", edge["value"])
            if mapping is not None and target == mapping.target_curie:
                if (edge["relation"], edge["knowledge_level"], edge["agent_type"]) != (
                    mapping.relation,
                    mapping.knowledge_level,
                    mapping.agent_type,
                ):
                    raise ValueError(f"Reviewed process evidence or relation changed: {column}, {target}")
                return "process", "reviewed_process_normalization"
            if local_scope is not None:
                if target == local_scope.curie:
                    if (
                        target not in (scope_nodes or {})
                        or nodes.get(target) != METABOLISM_CATEGORY
                        or edge.get("original_object") != f"{PATHWAY_PREFIX}{slugify_label(edge['value'])}"
                    ):
                        raise ValueError(
                            f"Source-defined process lost its scope or original locator: {column}, {target}"
                        )
                    return "process", "reviewed_source_defined_process"
                if (
                    target == f"{PATHWAY_PREFIX}{slugify_label(edge['value'])}"
                    and nodes.get(target) == METABOLISM_CATEGORY
                ):
                    return "process", "reviewed_process_scope_not_applied"
                raise ValueError(f"Source-defined process has an unexpected identity: {column}, {target}")
            if target.startswith(PATHWAY_PREFIX):
                if nodes.get(target) != METABOLISM_CATEGORY:
                    raise ValueError(f"Missing or mistyped local process declaration: {target}")
                return "process", "needs_process_mapping" if mapping is None else "reviewed_mapping_not_applied"
            raise ValueError(f"Unreviewed external process normalization: {column}, {target}")
        expected_relation = (
            (NCBI_TO_SUBSTRATE_EDGE, TROPHICALLY_INTERACTS_WITH)
            if role == "substrates"
            else (PRODUCES_PREDICATE, HAS_OUTPUT_RELATION)
        )
        if (edge["predicate"], edge["relation"]) != expected_relation:
            raise ValueError(f"Unexpected chemical role predicate/relation: {column}, {target}")
        if target.startswith(
            (
                SOURCE_ATTRIBUTE_PREFIX,
                PATHWAY_PREFIX,
                NCBITAXON_PREFIX,
                LPSN_PREFIX,
                NCBI_ASSEMBLY_PREFIX,
                GTDB_PREFIX,
            )
        ):
            raise ValueError(f"Nonchemical target namespace in chemical role: {column}, {target}")
        if target.startswith(COMPOUND_PREFIX):
            if target not in nodes:
                raise ValueError(f"Missing local material declaration: {target}")
            categories = {value.strip() for value in nodes[target].split("|")}
            if "" in categories or categories & _NONMATERIAL_CATEGORIES:
                raise ValueError(f"Nonmaterial local declaration in chemical role: {column}, {target}")
            return "chemical", "retained_local_material"
        if target in nodes:
            categories = {value.strip() for value in nodes[target].split("|")}
            if categories & _NONMATERIAL_CATEGORIES:
                raise ValueError(f"Nonmaterial external declaration in chemical role: {column}, {target}")
        return "chemical", "existing_chemical_mapping"
    if not column:
        # Empty field context is reserved for the producer's identity crosswalks.
        # A scientific assertion with a lost source column must not disappear
        # from the detailed inventory by being counted as a crosswalk.
        close_match = (
            (edge["predicate"], edge["relation"]) == (CLOSE_MATCH_PREDICATE, CLOSE_MATCH_RELATION)
            and edge["subject"].startswith(LPSN_PREFIX)
            and target.startswith((NCBITAXON_PREFIX, GTDB_PREFIX, NCBI_ASSEMBLY_PREFIX, GOLD_PREFIX, IMG_PREFIX))
        )
        strain_subclass = (
            (edge["predicate"], edge["relation"]) == (SUBCLASS_PREDICATE, RDFS_SUBCLASS_OF)
            and edge["subject"].startswith(f"{STRAIN_PREFIX}bacdive_")
            and target.startswith(LPSN_PREFIX)
        )
        has_scientific_context = any(
            edge.get(name)
            for name in (
                "value",
                "value_encoding",
                "description",
                "publications",
                "source_citation",
                "source_citation_base64",
            )
        )
        expected_provenance = (MICROBEDECODER_KNOWLEDGE_SOURCE, KNOWLEDGE_ASSERTION, MANUAL_AGENT)
        actual_provenance = (edge["primary_knowledge_source"], edge["knowledge_level"], edge["agent_type"])
        if (
            not (close_match or strain_subclass)
            or has_scientific_context
            or not edge["source_record"].strip()
            or actual_provenance != expected_provenance
        ):
            raise ValueError(f"Missing source column or invalid native crosswalk: {edge['predicate']}, {target}")
        return "crosswalk", "existing_crosswalk"
    raise ValueError(f"Unclassified source column: {column}")


def review(
    source_dir: Path,
    output_dir: Path,
    mappings: Path,
    authority: Path,
    go_authority: Path | None = None,
    phenotype_mappings: Path = DEFAULT_PHENOTYPE_MAPPINGS,
    process_scopes: Path = DEFAULT_PROCESS_SCOPE_DEFINITIONS,
    material_dispositions: Path = DEFAULT_MATERIAL_DISPOSITIONS,
    require_reviewed_material_cohort: bool = False,
    reviewed_material_raw: Path | None = None,
) -> dict:
    """Account for every source edge and publish a byte-bound, complete role-aware inventory."""
    if set(ATTRIBUTE_ROLES) != set(BACDIVE_SNAPSHOT_COLUMNS):
        raise ValueError("Attribute role inventory does not cover the producer's exact configured fields")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to replace an existing inventory: {output_dir}")
    paths = {
        "nodes": source_dir / "nodes.tsv",
        "edges": source_dir / "edges.tsv",
        "process_mappings": mappings,
        "process_authority": authority,
        "process_go_authority": go_authority or authority.parent / "go_nodes.tsv",
        "phenotype_mappings": phenotype_mappings,
        "process_scope_definitions": process_scopes,
        "material_dispositions": material_dispositions,
    }
    if reviewed_material_raw is not None:
        paths["reviewed_material_raw"] = reviewed_material_raw
    before = {name: fingerprint(path) for name, path in paths.items()}
    curation = ProcessCuration(mappings, authority, paths["process_go_authority"])
    phenotypes = PhenotypeCuration(phenotype_mappings, authority)
    scopes = ProcessScopeCuration(process_scopes)
    materials = MaterialDispositionCuration(material_dispositions)
    material_raw_receipt = materials.validate_raw(reviewed_material_raw) if reviewed_material_raw is not None else None
    scoped_ids = {scope.curie: scope for scope in scopes.rules}
    for scope in scopes.rules:
        group, role = GROUP_ROLES[scope.source_column]
        if curation.resolve(f"{group}:{role}", scope.source_literal) or phenotypes.resolve(
            scope.source_column, scope.source_literal
        ):
            raise ValueError(f"Conflicting process scope disposition for {scope.source_literal!r}")
    nodes, attribute_types, attribute_metadata = {}, {}, {}
    scope_nodes = {}
    metadata_fields = (ATTRIBUTE_TYPE_SOURCE_COLUMN, ATTRIBUTE_TYPE_EVIDENCE_COLUMN, ATTRIBUTE_TYPE_RATIONALE_COLUMN)
    for row in _rows(paths["nodes"], {"id", "category"}):
        if not row["id"] or row["id"] in nodes:
            raise ValueError(f"Empty or duplicate source node id: {row['id']}")
        nodes[row["id"]] = row["category"]
        if row["id"] in scoped_ids:
            scope = scoped_ids[row["id"]]
            if (
                row["category"] != METABOLISM_CATEGORY
                or row.get(PROVIDED_BY_COLUMN) != MICROBEDECODER_KNOWLEDGE_SOURCE
                or row.get("description") != scope.description
                or row.get("name") != scope.source_literal
            ):
                raise ValueError(f"Source-defined process node lost its reviewed declaration: {row['id']}")
            scope_nodes[row["id"]] = scope
        metadata = {field: row.get(field, "") for field in metadata_fields}
        if row.get(HAS_ATTRIBUTE_TYPE_COLUMN):
            if row.get(PROVIDED_BY_COLUMN) != MICROBEDECODER_KNOWLEDGE_SOURCE:
                raise ValueError(f"Typed source Attribute node lost its provider: {row['id']}")
            attribute_types[row["id"]] = row[HAS_ATTRIBUTE_TYPE_COLUMN]
            attribute_metadata[row["id"]] = metadata
        elif any(metadata.values()):
            raise ValueError(f"Curation metadata without an attribute type: {row['id']}")
    inventory, facets, dispositions = Counter(), Counter(), Counter()
    required = (set(INVENTORY_FIELDS) - _DERIVED_INVENTORY_FIELDS) | {
        "subject",
        "source_record",
    }
    edge_count = 0
    validated_types = set()
    validated_scopes = set()
    validated_materials, material_counts = set(), Counter()
    for edge in _rows(paths["edges"], required):
        facet, disposition = classify(
            edge, nodes, curation, phenotypes, attribute_types, attribute_metadata, scopes, scope_nodes
        )
        material = materials.resolve_edge(edge)
        if material is not None:
            if facet != "chemical" or disposition != "retained_local_material":
                raise ValueError(f"Reviewed material use lost its unresolved representation: {material.key}")
            if material.key in validated_materials:
                raise ValueError(f"Duplicate reviewed material use: {material.key}")
            validated_materials.add(material.key)
            material_counts[material.disposition] += 1
        if edge["object"] in scope_nodes:
            validated_scopes.add(edge["object"])
        if edge["object"] in attribute_types:
            validated_types.add(edge["object"])
        edge_count += 1
        facets[facet] += 1
        dispositions[disposition] += 1
        if facet == "crosswalk":
            continue
        row = {
            **edge,
            "facet": facet,
            "disposition": disposition,
            "object_category": nodes.get(edge["object"], ""),
            "object_attribute_type": attribute_types.get(edge["object"], ""),
            "material_review_disposition": material.disposition if material else "",
            "material_identity_status": material.identity_status if material else "",
            "material_review_evidence": material.evidence_uri if material else "",
            "material_review_rationale": material.curation_rationale if material else "",
        }
        inventory[tuple(row[name] for name in INVENTORY_FIELDS)] += 1
    if set(attribute_types) != validated_types:
        raise ValueError("Typed attribute nodes lack validating source-field observations")
    if set(scope_nodes) != validated_scopes:
        raise ValueError("Source-defined process nodes lack validating source-field observations")
    missing_materials = {rule.key for rule in materials.rules} - validated_materials
    if require_reviewed_material_cohort and missing_materials:
        raise ValueError(f"Incomplete reviewed material cohort: {len(missing_materials)} source uses missing")
    after = {name: fingerprint(path) for name, path in paths.items()}
    if before != after:
        raise ValueError("Inputs changed during the curation inventory; no report published")
    output_dir.mkdir(parents=True)
    inventory_path = output_dir / "curation_inventory.tsv"
    with atomic_write(inventory_path, "w", encoding="utf-8", newline="") as stream:
        writer = tsv_dict_writer(stream, fieldnames=[*INVENTORY_FIELDS, "edge_rows"], quoting=csv.QUOTE_NONE)
        writer.writeheader()
        for key, count in sorted(inventory.items()):
            writer.writerow({**dict(zip(INVENTORY_FIELDS, key, strict=True)), "edge_rows": count})
    summary = {
        "report_version": 3,
        "inputs": before,
        "inputs_unchanged": True,
        "nodes": len(nodes),
        "typed_attribute_nodes": len(attribute_types),
        "source_defined_process_nodes": len(scope_nodes),
        "material_review": {
            "source_sha256": materials.source_sha256,
            "matched_source_uses": len(validated_materials),
            "missing_reviewed_uses": len(missing_materials),
            "cohort_complete": not missing_materials,
            "edge_rows_by_disposition": dict(sorted(material_counts.items())),
            "raw_record_validation": material_raw_receipt,
            "chemical_identity_approved": False,
        },
        "edges": edge_count,
        "edge_rows_by_facet": dict(sorted(facets.items())),
        "edge_rows_by_disposition": dict(sorted(dispositions.items())),
        "inventory_rows": len(inventory),
        "inventory": fingerprint(inventory_path),
        "scope": "All source edge rows; not merged coverage, unique taxa, or raw emission attempts.",
        "limitations": [
            "Reviewed Attribute node types are not additional graph phenotype assertions or universal taxon traits.",
            "Existing chemical mapping counts do not constitute a new chemical identity review.",
            "Retained local materials and unmapped processes still require source-specific curation.",
            "Process normalization preserves the evidence tier; predictions are not experiments.",
            "Source-defined local processes are reviewed meanings, not exact external ontology identities.",
            "Material dispositions describe an exact historical cohort; "
            "they do not approve chemical identities or rewrite edges.",
        ],
    }
    with atomic_write(output_dir / "summary.json", "w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return summary


def main() -> None:
    """Generate a complete source-level report at an explicitly new destination."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_PROCESS_MAPPINGS)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--go-authority", type=Path)
    parser.add_argument("--phenotype-mappings", type=Path, default=DEFAULT_PHENOTYPE_MAPPINGS)
    parser.add_argument("--process-scopes", type=Path, default=DEFAULT_PROCESS_SCOPE_DEFINITIONS)
    parser.add_argument("--material-dispositions", type=Path, default=DEFAULT_MATERIAL_DISPOSITIONS)
    parser.add_argument("--require-reviewed-material-cohort", action="store_true")
    parser.add_argument("--reviewed-material-raw", type=Path)
    args = parser.parse_args()
    summary = review(
        args.source_dir,
        args.output_dir,
        args.mappings,
        args.authority or args.source_dir.parent / "ontologies/metpo_nodes.tsv",
        args.go_authority,
        args.phenotype_mappings,
        args.process_scopes,
        args.material_dispositions,
        args.require_reviewed_material_cohort,
        args.reviewed_material_raw,
    )
    print(json.dumps({key: summary[key] for key in ("edges", "inventory_rows", "edge_rows_by_disposition")}, indent=2))


if __name__ == "__main__":
    main()
