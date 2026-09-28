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
    RDFS_SUBCLASS_OF,
    SOURCE_ATTRIBUTE_PREFIX,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    TROPHICALLY_INTERACTS_WITH,
    VPI_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS, ProcessCuration
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    DEFAULT_PHENOTYPE_MAPPINGS,
    PhenotypeCuration,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import is_reported_metabolism_annotation
from kg_microbe.transform_utils.microbedecoder.utils import BACDIVE_SNAPSHOT_COLUMNS, METABOLISM_GROUPS
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
    "predicate",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
    "disposition",
]


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
) -> tuple[str, str]:
    """Classify representation, never decode a source token or infer a negative phenotype."""
    column, target = edge["source_column"], edge["object"]
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
        if phenotypes is not None and phenotypes.resolve(column, edge["value"]) is not None:
            return "source_attribute", "reported_phenotype_with_reviewed_literal_grounding"
        return "source_attribute", ATTRIBUTE_ROLES[column]
    if column in GROUP_ROLES:
        group, role = GROUP_ROLES[column]
        if role == "type_of_metabolism":
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
    }
    before = {name: fingerprint(path) for name, path in paths.items()}
    curation = ProcessCuration(mappings, authority, paths["process_go_authority"])
    phenotypes = PhenotypeCuration(phenotype_mappings, authority)
    nodes = {}
    for row in _rows(paths["nodes"], {"id", "category"}):
        if not row["id"] or row["id"] in nodes:
            raise ValueError(f"Empty or duplicate source node id: {row['id']}")
        nodes[row["id"]] = row["category"]
    inventory, facets, dispositions = Counter(), Counter(), Counter()
    required = (set(INVENTORY_FIELDS) - {"facet", "object_category", "disposition"}) | {"subject", "source_record"}
    edge_count = 0
    for edge in _rows(paths["edges"], required):
        facet, disposition = classify(edge, nodes, curation, phenotypes)
        edge_count += 1
        facets[facet] += 1
        dispositions[disposition] += 1
        if facet == "crosswalk":
            continue
        row = {**edge, "facet": facet, "disposition": disposition, "object_category": nodes.get(edge["object"], "")}
        inventory[tuple(row[name] for name in INVENTORY_FIELDS)] += 1
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
        "report_version": 2,
        "inputs": before,
        "inputs_unchanged": True,
        "nodes": len(nodes),
        "edges": edge_count,
        "edge_rows_by_facet": dict(sorted(facets.items())),
        "edge_rows_by_disposition": dict(sorted(dispositions.items())),
        "inventory_rows": len(inventory),
        "inventory": fingerprint(inventory_path),
        "scope": "All source edge rows; not merged coverage, unique taxa, or raw emission attempts.",
        "limitations": [
            "Reviewed phenotype literal groundings are not additional graph phenotype assertions.",
            "Existing chemical mapping counts do not constitute a new chemical identity review.",
            "Retained local materials and unmapped processes still require source-specific curation.",
            "Process normalization preserves the evidence tier; predictions are not experiments.",
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
    args = parser.parse_args()
    summary = review(
        args.source_dir,
        args.output_dir,
        args.mappings,
        args.authority or args.source_dir.parent / "ontologies/metpo_nodes.tsv",
        args.go_authority,
        args.phenotype_mappings,
    )
    print(json.dumps({key: summary[key] for key in ("edges", "inventory_rows", "edge_rows_by_disposition")}, indent=2))


if __name__ == "__main__":
    main()
