"""Generic finalized-files admission must rejoin native fallback scope after outer receipt restamping."""

import copy
import csv
import hashlib
import json
from collections import Counter

import pytest

from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.fallback_evidence import SELECTED_ROLE
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.bacdive_fallback_fixtures import records_by_id
from tests.test_bacdive_fallback_producer import produce


def _identity(path):
    """Restamp outer bytes only, never scientific contracts or native authority bindings."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, rows, header):
    """Preserve the actual finalized QUOTE_NONE dialect, including an honest header-only audit."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _signature(row):
    """Compare complete row multiplicities, not merely endpoints."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def test_generic_public_admission_accepts_real_native_fallback_baseline(tmp_path, monkeypatch, local_source_schema):
    """The public entry point is reached on an unchanged real finalized source before negatives."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [records_by_id()["175523"]["record"]])
    report = transform.finalize()
    paths = [transform.output_node_file, transform.output_edge_file]
    assert all(report["members"][path.name] == _identity(path) for path in paths)
    verify_finalized_source_files(paths)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_child",
        "zero_child",
        "drop_audit",
        "changed_audit",
        "native_role",
        "record_parent",
        "deposit_parent",
        "reversed_record",
        "reversed_provisional",
        "filled_qualifier",
    ],
)
def test_generic_public_admission_rejoins_scope_after_outer_receipt_restamping(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """A graph hash mismatch is not accepted as proof of scientific scope enforcement."""
    identifier = "134696" if damage == "filled_qualifier" else "24851" if damage == "reversed_provisional" else "175523"
    transform, _, _, _ = produce(tmp_path, monkeypatch, [records_by_id()[identifier]["record"]])
    report = transform.finalize()
    paths = [transform.output_node_file, transform.output_edge_file]
    # Positive control must exercise exactly the same generic route.
    verify_finalized_source_files(paths)
    original_native = copy.deepcopy(report["producer_native_inputs"])
    original_inputs = copy.deepcopy(report["inputs"])
    original_roles = copy.deepcopy(report["consumed_inputs"])
    audit = transform.output_dir / taxonomy.AUDIT_FILE
    original_audit_bytes = audit.read_bytes()
    original_graph_rows = list(graph_rows(transform.output_edge_file))
    report_path = transform.output_dir / "source_finalization.json"
    if damage == "missing_child":
        report["producer_native_inputs"]["taxonomy"].pop("fallback_native_evidence")
    elif damage == "zero_child":
        child = report["producer_native_inputs"]["taxonomy"]["fallback_native_evidence"]
        child.update(plans={}, eligible_record_count=0, native_queries=None, selected_input=None)
        report["producer_native_inputs"]["taxonomy"]["fallback_choices"] = []
    elif damage == "native_role":
        report["consumed_inputs"].pop(SELECTED_ROLE)
    elif damage in {"drop_audit", "changed_audit"}:
        rows = list(graph_rows(audit))
        if damage == "drop_audit":
            rows = [row for row in rows if row["kind"] != "fallback"]
        else:
            next(row for row in rows if row["kind"] == "fallback")["native_evidence_json"] = "{}"
        _write(audit, rows, taxonomy.AUDIT_FIELDS)
        report["producer_audit_members"][audit.name] = _identity(audit)
        report["audit_members"][audit.name] = _identity(audit)
    else:
        rows = copy.deepcopy(original_graph_rows)
        if damage == "filled_qualifier":
            chosen = [
                row
                for row in rows
                if row["subject"] == "kgmicrobe.strain:bacdive_134696"
                and row["predicate"] == "biolink:subclass_of"
                and row["object"].startswith("NCBITaxon:")
            ]
            assert len(chosen) == 1
            chosen[0]["publications"] = "doi:10.9999/unsupported"
        else:
            row = dict.fromkeys(rows[0], "")
            row.update(
                subject="kgmicrobe.strain:DSM-116161"
                if damage == "deposit_parent"
                else "kgmicrobe.strain:bacdive_175523",
                predicate="biolink:subclass_of",
                object="NCBITaxon:216400",
                relation="kgmicrobe:inferred_subClassOf",
                primary_knowledge_source="infores:bacdive",
                knowledge_level="prediction",
                agent_type="automated_agent",
            )
            if damage in {"reversed_record", "reversed_provisional"}:
                row["subject"] = "NCBITaxon:2"
                row["object"] = (
                    "kgmicrobe.genus:Proactinomyces"
                    if damage == "reversed_provisional"
                    else "kgmicrobe.strain:bacdive_175523"
                )
            rows.append(row)
            # Addition-only controls keep every original complete row and all
            # original audit evidence. No swap/loss may cause the rejection.
            assert Counter(map(_signature, original_graph_rows)) <= Counter(map(_signature, rows))
            assert len(rows) == len(original_graph_rows) + 1
        _write(transform.output_edge_file, rows, list(rows[0]))
        report["members"][transform.output_edge_file.name] = _identity(transform.output_edge_file)
        assert audit.read_bytes() == original_audit_bytes
    assert report["inputs"] == original_inputs
    if damage != "native_role":
        assert report["consumed_inputs"] == original_roles
    if damage not in {"missing_child", "zero_child"}:
        assert report["producer_native_inputs"] == original_native
    assert all(report["members"][path.name] == _identity(path) for path in paths)
    assert report["audit_members"][audit.name] == _identity(audit)
    assert report["producer_audit_members"][audit.name] == _identity(audit)
    report_path.write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match=r"BacDive (taxonomy|fallback) evidence:"):
        verify_finalized_source_files(paths)
