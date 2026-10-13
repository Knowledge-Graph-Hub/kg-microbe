"""Apply local native category decisions exclusively in source finalization."""

import csv
import json
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
    NAMED_THING_CATEGORY,
    NCBI_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
)
from kg_microbe.utils.graph_canonicalization import canonical_node_category
from kg_microbe.utils.ncit_eight_categories import FINITE_IDS as FINITE_NCIT_IDS
from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority


class SourceCategoryAuthority:
    """
    Own one run's immutable category authority snapshots, shared by all source files.

    The opener is the producer's consumed-input hook, not an ontology adapter or
    a remote resolver. Canonicalization audits preserve every changed row; input
    snapshots retain the exact native bytes behind each category/name decision.
    """

    def __init__(self, raw_dir, *, opener, gold_declarations=None):
        """Select raw authorities without consulting process-global caches."""
        self.raw_dir = Path(raw_dir)
        self.opener = opener
        self.ontology = OntologyCategoryAuthority(self.raw_dir, opener=opener)
        self.source_paths = set()
        self.gold_declarations = gold_declarations
        self._foodon = None
        self._foodon_kernel_evidence = None
        self._foodon_anatomical = {}
        self._genes = None
        self._temporal_policy = None
        self._temporal_categories = None
        self._clinical_mesh = None
        from kg_microbe.utils.finite_envo_po_categories import FiniteEnvoPoCategoryAuthority

        self._finite_envo_po = FiniteEnvoPoCategoryAuthority(self.raw_dir, opener=opener)
        from kg_microbe.utils.ncit_eight_categories import FiniteNcitCategoryAuthority

        self.ncit_eight = FiniteNcitCategoryAuthority(self.raw_dir, opener=opener)
        from kg_microbe.utils.mesh_finite_categories import FiniteMeshCategoryAuthority

        self.mesh_finite = FiniteMeshCategoryAuthority(self.raw_dir, opener=opener)

    def normalize(self, row):
        """Update only evidence-backed categories and blank authoritative gene names."""
        identifier = row[ID_COLUMN]
        gold_proof = (
            self.gold_declarations.declaration_for(identifier)
            if identifier.startswith("gold:") and self.gold_declarations is not None
            else None
        )
        if gold_proof is not None:
            original = set(row.get(CATEGORY_COLUMN, "").split("|")) - {""}
            if not original <= {NCBI_CATEGORY, NAMED_THING_CATEGORY, ONTOLOGY_CLASS_CATEGORY}:
                raise ValueError(f"Unreviewed imported GOLD category: {identifier}: {row.get(CATEGORY_COLUMN)}")
            if gold_proof.declaration[CATEGORY_COLUMN] != NAMED_THING_CATEGORY:
                raise ValueError(f"Unsupported GOLD declaration category: {identifier}")
            row[CATEGORY_COLUMN] = NAMED_THING_CATEGORY
            return
        finite = self.ontology.finite_evidence_for(identifier)
        if finite is not None:
            from kg_microbe.utils.finite_import_categories import apply_import_category

            row[CATEGORY_COLUMN] = apply_import_category(row[CATEGORY_COLUMN], finite)
        elif identifier in FINITE_NCIT_IDS:
            from kg_microbe.utils.ncit_eight_categories import apply_category

            row[CATEGORY_COLUMN] = apply_category(row[CATEGORY_COLUMN], self.ncit_eight.category_for(identifier))
            self.source_paths.update(self.ncit_eight.source_paths)
        elif identifier in {"ENVO:01001254", "ENVO:01001255", "PO:0007033"}:
            from kg_microbe.utils.finite_envo_po_categories import (
                apply_finite_category,
            )

            evidence = self._finite_envo_po.evidence_for(identifier)
            row[CATEGORY_COLUMN] = apply_finite_category(row[CATEGORY_COLUMN], evidence)
            self.source_paths.update(self._finite_envo_po.source_paths)
        elif identifier in self.mesh_finite.identifiers:
            from kg_microbe.utils.mesh_finite_categories import apply_category

            row[CATEGORY_COLUMN] = apply_category(row[CATEGORY_COLUMN], self.mesh_finite.category_for(identifier))
            self.source_paths.update(self.mesh_finite.source_paths)
        elif identifier in {"mesh:D000038", "mesh:D010514"}:
            from kg_microbe.utils.clinical_mesh_categories import (
                CLINICAL_MESH_POLICY_FILE,
                apply_clinical_mesh_category,
                load_clinical_mesh_evidence,
                load_clinical_mesh_policy,
            )

            if self._clinical_mesh is None:
                self.source_paths.add(CLINICAL_MESH_POLICY_FILE)
                with self.opener(CLINICAL_MESH_POLICY_FILE) as stream:
                    policy = load_clinical_mesh_policy(stream)
                path = self.raw_dir / policy["native_file"]
                self.source_paths.add(path)
                with self.opener(path) as stream:
                    self._clinical_mesh = load_clinical_mesh_evidence(policy, stream)
            row[CATEGORY_COLUMN] = apply_clinical_mesh_category(row[CATEGORY_COLUMN], self._clinical_mesh[identifier])
        elif identifier.startswith("UBERON:"):
            from kg_microbe.utils.uberon_temporal_categories import (
                TEMPORAL_DISPOSITIONS_FILE,
                apply_temporal_category,
                load_bound_temporal_evidence,
                load_temporal_category_policy,
            )

            if self._temporal_policy is None:
                self.source_paths.add(TEMPORAL_DISPOSITIONS_FILE)
                with self.opener(TEMPORAL_DISPOSITIONS_FILE) as stream:
                    self._temporal_policy = load_temporal_category_policy(stream)
            if identifier in self._temporal_policy["records"]:
                if self._temporal_categories is None:
                    self._temporal_categories = load_bound_temporal_evidence(
                        self._temporal_policy, self.raw_dir, self.opener, self.source_paths
                    )
                row[CATEGORY_COLUMN] = apply_temporal_category(
                    row[CATEGORY_COLUMN], self._temporal_categories[identifier]
                )
        elif identifier.startswith("FOODON:") or identifier in {"COB:0000022", "OBO:COB_0000022", "PO:0000003"}:
            if self._foodon is None:
                from kg_microbe.utils.foodon_classification import DISPOSITIONS_FILE, foodon_categories
                from kg_microbe.utils.foodon_kernel_quarantine import (
                    POLICY_FILE,
                    json_evidence,
                    load_policy,
                    reviewed_hierarchy,
                    unique_object,
                )

                path = self.raw_dir / "foodon.json"
                self.source_paths.update((path, DISPOSITIONS_FILE, POLICY_FILE))
                with self.opener(DISPOSITIONS_FILE) as stream:
                    dispositions = {entry["id"]: entry for entry in csv.DictReader(stream, delimiter="\t")}
                with self.opener(path) as stream:
                    graphs = json.load(stream, object_pairs_hook=unique_object).get("graphs")
                    if not isinstance(graphs, list) or not graphs or not any(graph.get("nodes") for graph in graphs):
                        raise ValueError(f"Missing FOODON ontology declarations: {path}")
                from kg_microbe.utils import foodon_anatomical_categories as anatomy
                from kg_microbe.utils import ontology_parent_quarantine as parent_evidence

                if anatomy.selected(graphs):
                    self.source_paths.update((anatomy.POLICY_FILE, parent_evidence.POLICY_FILE))
                    with self.opener(anatomy.POLICY_FILE) as stream:
                        anatomy_policy = anatomy.load_policy(stream)
                    with self.opener(parent_evidence.POLICY_FILE) as stream:
                        parent_policy = parent_evidence.load_policy(stream)
                    self._foodon_anatomical = anatomy.categories_for(
                        graphs, policy=anatomy_policy, parent_policy=parent_policy
                    )
                    owl = self.raw_dir / "foodon.owl"
                    self.source_paths.add(owl)
                    with self.opener(owl) as stream:
                        parent_evidence.owl_context(stream, parent_policy["sources"]["foodon"])
                with self.opener(POLICY_FILE) as stream:
                    kernel_policy = load_policy(stream)
                if json_evidence(graphs, kernel_policy) is not None:
                    owl = self.raw_dir / "foodon.owl"
                    self.source_paths.add(owl)
                    with self.opener(owl) as stream:
                        graphs, self._foodon_kernel_evidence = reviewed_hierarchy(
                            graphs, kernel_policy, native_owl=stream
                        )
                self._foodon = foodon_categories(
                    graphs, dispositions=dispositions, anatomical_categories=self._foodon_anatomical
                )
            from kg_microbe.utils.foodon_anatomical_categories import apply_category
            from kg_microbe.utils.foodon_kernel_quarantine import apply_kernel_category

            row[CATEGORY_COLUMN] = apply_kernel_category(identifier, row[CATEGORY_COLUMN], self._foodon_kernel_evidence)
            row[CATEGORY_COLUMN] = apply_category(identifier, row[CATEGORY_COLUMN], self._foodon_anatomical)
            row[CATEGORY_COLUMN] = canonical_node_category(
                identifier, row[CATEGORY_COLUMN], foodon_categories=self._foodon
            )
        elif identifier.startswith("NCBIGene:"):
            from kg_microbe.utils.imported_gene_authority import (
                GENE_AUTHORITY_FILE,
                GENE_NATIVE_EVIDENCE_FILE,
                load_imported_gene_records,
            )

            if self._genes is None:
                self.source_paths.update((GENE_AUTHORITY_FILE, GENE_NATIVE_EVIDENCE_FILE))
                with (
                    self.opener(GENE_AUTHORITY_FILE) as stream,
                    self.opener(GENE_NATIVE_EVIDENCE_FILE) as native_stream,
                ):
                    self._genes = load_imported_gene_records(stream, native_stream=native_stream)
            record = self._genes.get(identifier)
            if record is not None:
                categories = set(row[CATEGORY_COLUMN].split("|")) - {"", "biolink:OntologyClass", "biolink:NamedThing"}
                categories.add(record.category)
                row[CATEGORY_COLUMN] = "|".join(sorted(categories))
                if not row.get(NAME_COLUMN):
                    row[NAME_COLUMN] = record.name
                if DESCRIPTION_COLUMN in row and not row[DESCRIPTION_COLUMN]:
                    row[DESCRIPTION_COLUMN] = record.description
        else:
            row[CATEGORY_COLUMN] = canonical_node_category(
                identifier, row[CATEGORY_COLUMN], ontology_authority=self.ontology
            )
        self.source_paths.update(self.ontology.source_paths)
