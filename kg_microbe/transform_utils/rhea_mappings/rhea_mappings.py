"""Transform one pinned native Rhea snapshot, preserving explicit reaction directions."""

import csv
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.constants import ID_COLUMN, RHEAMAPPINGS
from kg_microbe.transform_utils.rhea_mappings.label_inputs import (
    LABEL_CONTRACT,
    REQUIRED_LABEL_INPUTS,
    external_label_lookup,
    validate_label_contract,
    verify_label_bindings,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    AUDIT_FILE as LEGACY_AUDIT_FILE,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    AUDIT_HEADER as LEGACY_AUDIT_HEADER,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    DATA_INPUTS as LEGACY_DATA_INPUTS,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    POLICY_PATH as LEGACY_POLICY_PATH,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    REQUIRED_INPUTS as LEGACY_INPUTS,
)
from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    load_legacy_xref_audit,
)
from kg_microbe.transform_utils.rhea_mappings.native_graph import (
    EDGE_WITNESS_FIELDS,
    POLYMERIZATION_FIELD,
    SOURCE,
    curated_xref,
    family_rows,
)
from kg_microbe.transform_utils.rhea_mappings.native_inputs import POLICY_PATH, REQUIRED_INPUTS, load_pinned_inputs
from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
    RHEA_DIRECTION_FIELD,
    RHEA_MASTER_FIELD,
    RHEA_STATUS_FIELD,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_schema import canonical_header
from kg_microbe.utils.tsv_io import tsv_dict_writer

REACTION_AUDIT = "rhea_reaction_dispositions.tsv"


class RheaMappingsTransform(Transform):
    """Consume explicit local inputs; never infer directions from ID order or cache state."""

    DATA_INPUTS = ("mappings/rhea_release.json", *LEGACY_DATA_INPUTS)
    TSV_QUOTING = csv.QUOTE_NONE
    REQUIRED_CONSUMED_INPUTS = (*REQUIRED_INPUTS, *REQUIRED_LABEL_INPUTS, *LEGACY_INPUTS)
    REQUIRED_AUDIT_FILES = (REACTION_AUDIT, LEGACY_AUDIT_FILE)

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Prepare source headers without opening global ontology adapters or downloading data."""
        super().__init__(RHEAMAPPINGS, input_dir, output_dir)
        self.knowledge_source = SOURCE
        self.node_header = canonical_header(
            [*self.node_header, RHEA_DIRECTION_FIELD, RHEA_MASTER_FIELD, RHEA_STATUS_FIELD, POLYMERIZATION_FIELD], True
        )
        self.edge_header = canonical_header([*self.edge_header, *EDGE_WITNESS_FIELDS], False)

    @property
    def producer_native_inputs(self):
        """Version the label projection; exact DB identities live in consumed-input roles."""
        return dict(LABEL_CONTRACT)

    @producer_native_inputs.setter
    def producer_native_inputs(self, recorded):
        """Repeated finalization must retain the original label reader contract."""
        validate_label_contract(recorded)

    def verify_native_inputs(self, *, byte_verified=False, output_dir=None):
        """Reject unconsumed SQLite sidecars even when each main-file SHA remains unchanged."""
        verify_label_bindings(self.input_base_dir, self.consumed_input_snapshots)

    @classmethod
    def verify_recorded_native_inputs(cls, report, report_path, *, admission=None):
        """Enforce raw-root roles and quiescent SQLite state again at merge admission."""
        validate_label_contract(report.get("producer_native_inputs"))
        verify_label_bindings(report["raw_input_directory"], report["consumed_inputs"])
        return admission

    def _curated_xref_row(self, subject: str, target: str) -> list:
        """Retain the established manual activity-cross-reference row contract."""
        row = curated_xref(subject, target)
        return [row.get(column, "") for column in self.edge_header]

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Write canonical graph rows and audited statuses from coherent pinned native evidence."""
        if data_file is not None:
            raise ValueError(
                "Rhea requires its pinned directions/RDF pair under input_dir/rhea, not a single data_file"
            )
        policy, families, native, cohort = load_pinned_inputs(self, policy_path=POLICY_PATH)
        legacy_rows = load_legacy_xref_audit(self, policy, native, policy_path=LEGACY_POLICY_PATH)
        audit_header = ("reaction_id", "master_id", "direction", "native_status", "disposition", "snapshot_id")
        node_values, seen_edges = {}, set()
        with (
            atomic_write(self.output_node_file, encoding="utf-8", newline="") as nodes,
            atomic_write(self.output_edge_file, encoding="utf-8", newline="") as edges,
            atomic_write(self.output_dir / REACTION_AUDIT, encoding="utf-8", newline="") as audit,
            atomic_write(self.output_dir / LEGACY_AUDIT_FILE, encoding="utf-8", newline="") as legacy_audit,
            external_label_lookup(self) as label_lookup,
        ):
            options = {"quoting": csv.QUOTE_NONE, "quotechar": None}
            node_writer = tsv_dict_writer(nodes, self.node_header, **options)
            edge_writer = tsv_dict_writer(edges, self.edge_header, **options)
            audit_writer = tsv_dict_writer(audit, audit_header, **options)
            legacy_writer = tsv_dict_writer(legacy_audit, LEGACY_AUDIT_HEADER, **options)
            node_writer.writeheader()
            edge_writer.writeheader()
            audit_writer.writeheader()
            legacy_writer.writeheader()
            legacy_writer.writerows(legacy_rows)
            for family in families:
                for kind, row in family_rows(family, native, label_lookup):
                    if kind == "node":
                        identifier = row[ID_COLUMN]
                        previous = node_values.get(identifier)
                        if previous is not None and previous != row:
                            raise ValueError(f"Conflicting native Rhea node declarations: {identifier}")
                        if previous is None:
                            node_values[identifier] = row
                            node_writer.writerow(row)
                    else:
                        identity = tuple(row.get(column, "") for column in self.edge_header)
                        if identity not in seen_edges:
                            edge_writer.writerow(row)
                            seen_edges.add(identity)
                for identifier, direction in family.members:
                    audit_writer.writerow(
                        {
                            "reaction_id": identifier,
                            "master_id": family.master,
                            "direction": direction,
                            "native_status": node_values[identifier][RHEA_STATUS_FIELD],
                            "disposition": "retained_active",
                            "snapshot_id": policy["snapshot_id"],
                        }
                    )
            for identifier in cohort["obsolete_ids"]:
                audit_writer.writerow(
                    {
                        "reaction_id": identifier,
                        "native_status": "Obsolete",
                        "disposition": "excluded_obsolete",
                        "snapshot_id": policy["snapshot_id"],
                    }
                )
        self.record_producer_audit(REACTION_AUDIT)
        self.record_producer_audit(LEGACY_AUDIT_FILE)
        if show_status:
            print(
                f"[rhea_mappings] snapshot={policy['snapshot_id']} families={len(families):,} "
                f"statuses={cohort['family_status_counts']} nodes={len(node_values):,} edges={len(seen_edges):,} "
                f"obsolete_reactions_audited={len(cohort['obsolete_ids']):,} "
                f"historical_xrefs_audited={len(legacy_rows):,} "
                f"missing_external_labels={label_lookup.missing_counts}"
            )
