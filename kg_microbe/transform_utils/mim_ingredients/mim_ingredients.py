"""Project reviewed ingredient context without general CultureMech ingestion."""

import csv
import os
import tempfile
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    BROAD_MATCH_PREDICATE,
    BROAD_MATCH_RELATION,
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    INFORMATION_CONTENT_ENTITY_CATEGORY,
    INGREDIENT_ANNOTATION_JSON,
    INGREDIENT_BUNDLE_SHA256,
    INGREDIENT_CATEGORY,
    INGREDIENT_MAPPING_JSON,
    INGREDIENT_OCCURRENCE_ID,
    INGREDIENT_OCCURRENCE_JSON,
    INGREDIENT_PRODUCT_ID,
    INGREDIENT_PRODUCT_JSON,
    INGREDIENT_PROFILE_COLUMN,
    INGREDIENT_RECORD_KIND,
    IS_ABOUT_RELATION,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    MIM_INGREDIENTS,
    MIM_KNOWLEDGE_SOURCE,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATED_TO_PREDICATE,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.graph_schema import canonical_header, validate_canonical_tsv
from kg_microbe.utils.ingredient_bundle import load_ingredient_lookup_bundle
from kg_microbe.utils.ingredient_bundle_contract import content_sha256, read_json, stable_id
from kg_microbe.utils.ingredient_kgx import ingredient_graph_id, ingredient_kgx_profile, json_scalar
from kg_microbe.utils.tsv_io import tsv_dict_writer


class MIMIngredientsTransform(Transform):
    """Keep source claims on assertions and catalog specifications as distinct records."""

    TSV_QUOTING = csv.QUOTE_NONE
    SSSOM_CONSUMED_INPUT = "ingredient_lookup/legacy.sssom.tsv.gz"
    REQUIRED_CONSUMED_INPUTS = (
        "ingredient_selection",
        "ingredient_lookup/lookup_manifest.json",
        SSSOM_CONSUMED_INPUT,
        "ingredient_bundle/manifest.json",
    )

    def __init__(self, input_dir=None, output_dir=None):
        """Use an explicit selection file; no global activation or default production pin."""
        super().__init__(MIM_INGREDIENTS, input_dir, output_dir)

    def run(self, data_file=None, show_status=True):
        """Consume a pinned candidate lookup and retain every reviewed claim disposition."""
        del show_status
        self.begin_consumed_inputs()
        try:
            return self._run(data_file)
        except BaseException as error:
            self._consumed_input_error = str(error)
            raise

    def _run(self, data_file):
        """Validate and stage one attempt; the public boundary records any failure."""
        selection_path = Path(data_file) if data_file else self.input_base_dir / MIM_INGREDIENTS / "selection.json"
        with self.consume_input("ingredient_selection", selection_path) as stream:
            selection = read_json(stream.read().encode("utf-8"))
        if (
            not isinstance(selection, dict)
            or set(selection) != {"mode", "lookup_directory", "lookup_manifest_sha256"}
            or selection["mode"] != "candidate_only"
            or not isinstance(selection["lookup_directory"], str)
            or not selection["lookup_directory"]
        ):
            raise ValueError("Ingredient ingestion requires an explicit candidate_only lookup selection")
        directory = (selection_path.parent / selection["lookup_directory"]).resolve()
        manifest_path = directory / "lookup_manifest.json"
        with self.consume_input("ingredient_lookup/lookup_manifest.json", manifest_path) as stream:
            manifest_bytes = stream.read().encode("utf-8")
        if content_sha256(manifest_bytes) != selection["lookup_manifest_sha256"]:
            raise ValueError("Ingredient lookup selection manifest mismatch")
        manifest = read_json(manifest_bytes)
        legacy, bundle, legacy_digest = load_ingredient_lookup_bundle(
            directory, manifest_sha256=selection["lookup_manifest_sha256"]
        )
        # Record every validated wrapper input, including binary legacy mappings.
        # The bundle's own binding records its original proof/evidence members.
        for name, digest in manifest["members"].items():
            self._consumed_input_snapshots["ingredient_lookup/" + name] = {
                "path": str(directory / name),
                "sha256": digest,
            }
        bundle.bind_to_transform(self)
        self.verify_consumed_inputs()
        loader = ChemicalMappingLoader(legacy, ingredient_bundle=bundle, mappings_sha256=legacy_digest)
        nodes, edges = project_ingredient_context(bundle, loader)
        with tempfile.TemporaryDirectory(prefix=".ingredient-kgx-", dir=self.output_dir) as temporary:
            staged = Path(temporary)
            for records, name, is_node in ((nodes, "nodes.tsv", True), (edges, "edges.tsv", False)):
                header = canonical_header({key for row in records for key in row}, is_node)
                path = staged / name
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = tsv_dict_writer(stream, header, quoting=csv.QUOTE_NONE, quotechar=None)
                    writer.writeheader()
                    writer.writerows(records)
                validate_canonical_tsv(path, is_node=is_node)
            self.verify_consumed_inputs()
            for name in ("nodes.tsv", "edges.tsv"):
                os.replace(staged / name, self.output_dir / name)
        return {"nodes": len(nodes), "edges": len(edges), "bundle_sha256": bundle.fingerprint}


def project_ingredient_context(bundle, loader):
    """Build a reviewed cohort graph; nested original payloads remain scalar JSON."""
    nodes, edges = {}, []
    profile = ingredient_kgx_profile()["profile_id"]

    def node(identifier, label, kind=None):
        """Declare one ID without moving source qualifications onto its ingredient."""
        graph_id = ingredient_graph_id(identifier)
        if graph_id in nodes:
            return
        row = {
            ID_COLUMN: graph_id,
            NAME_COLUMN: " ".join(label.split()),
            CATEGORY_COLUMN: INFORMATION_CONTENT_ENTITY_CATEGORY if kind else INGREDIENT_CATEGORY,
            DESCRIPTION_COLUMN: "",
            PROVIDED_BY_COLUMN: MIM_KNOWLEDGE_SOURCE,
        }
        if kind:
            row.update({INGREDIENT_PROFILE_COLUMN: profile, INGREDIENT_RECORD_KIND: kind})
            if kind == "catalog_record":
                row[XREF_COLUMN] = "|".join(bundle.active_xrefs(identifier))
        else:
            row.update({key: value for key, value in loader.get_node_enrichment(identifier).items() if value})
        nodes[graph_id] = row

    def assertion(subject, obj, column, payload, *, predicate=RELATED_TO_PREDICATE, relation=IS_ABOUT_RELATION):
        """Retain source-specific evidence and data together in one merge assertion."""
        edge = {
            SUBJECT_COLUMN: ingredient_graph_id(subject),
            PREDICATE_COLUMN: predicate,
            OBJECT_COLUMN: ingredient_graph_id(obj),
            RELATION_COLUMN: relation,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: MIM_KNOWLEDGE_SOURCE,
            KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
            AGENT_TYPE_COLUMN: MANUAL_AGENT,
            INGREDIENT_PROFILE_COLUMN: profile,
            INGREDIENT_BUNDLE_SHA256: bundle.fingerprint,
            column: json_scalar(payload),
        }
        source = payload.get("source_id")
        if source:
            edge[PUBLICATIONS_COLUMN] = source
        if column == INGREDIENT_OCCURRENCE_JSON:
            edge[INGREDIENT_OCCURRENCE_ID] = payload["occurrence_id"]
            edge[INGREDIENT_PRODUCT_ID] = payload["product_id"] or ""
        edges.append(edge)

    for row in sorted(
        bundle.mappings(), key=lambda item: (item["subject_id"], item["predicate_id"], item["object_id"])
    ):
        owner = bundle.canonical_owner(row["subject_id"])
        node(owner, row["object_label"] if owner == row["object_id"] else row["subject_label"])
        record = stable_id("mapping", [row[key] for key in ("subject_id", "predicate_id", "object_id")])
        node(record, f"Mapping review for {row['subject_label']}", "mapping_record")
        assertion(record, owner, INGREDIENT_MAPPING_JSON, row)
        # Canonical replacement has already been explicitly reviewed. Nonidentity
        # scope does not gain equivalence merely by appearing in a mapping table.
        if row["ext_scope_review_status"] != "SUPPORTED" or row.get("predicate_modifier"):
            continue
        if row["predicate_id"] in {"skos:broadMatch", "skos:narrowMatch"}:
            node(row["object_id"], row["object_label"])
            subject, obj = owner, row["object_id"]
            if row["predicate_id"] == "skos:narrowMatch":
                subject, obj = obj, subject
            assertion(
                subject,
                obj,
                INGREDIENT_MAPPING_JSON,
                row,
                predicate=BROAD_MATCH_PREDICATE,
                relation=BROAD_MATCH_RELATION,
            )

    for row in sorted(bundle.products(), key=lambda item: item["product_id"]):
        node(row["product_id"], row["label"], "catalog_record")
        assertion(row["product_id"], bundle.canonical_owner(row["ingredient_id"]), INGREDIENT_PRODUCT_JSON, row)

    for row in bundle.identifier_claims():
        node(row["annotation_id"], f"Identifier claim: {row['raw_identifier']}", "identifier_annotation")
        # Aboutness records the claim's subject even when the identifier is
        # historical, invalid or withheld. It asserts no chemical equivalence.
        assertion(row["annotation_id"], bundle.canonical_owner(row["owner_id"]), INGREDIENT_ANNOTATION_JSON, row)

    for row in sorted(bundle.occurrences(), key=lambda item: item["occurrence_id"]):
        record = stable_id("source", row["source_id"])
        node(record, row["source_id"], "source_record")
        nodes[record][XREF_COLUMN] = row["source_id"]
        # The edge describes the reported occurrence, including its review state.
        # Alternatives remain one_of/UNSPECIFIED inside the source payload; no
        # confirmed-use edges are generated for the unselected product options.
        assertion(record, bundle.canonical_owner(row["ingredient_id"]), INGREDIENT_OCCURRENCE_JSON, row)
    return [nodes[key] for key in sorted(nodes)], sorted(edges, key=json_scalar)
