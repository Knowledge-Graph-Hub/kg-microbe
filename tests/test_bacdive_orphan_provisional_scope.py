"""Reject extra taxonomy parents of source-derived orphan provisional genera."""

import copy
import csv
import hashlib
import json
from collections import Counter

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.bacdive_fallback_fixtures import records_by_id
from tests.test_bacdive_fallback_producer import produce


def _identity(path):
    """Identify actual output bytes without changing any native evidence receipt."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _signature(row):
    """Conserve full original graph row multiplicities during an addition-only attack."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("direction", ["forward", "reverse"])
@pytest.mark.parametrize("route", ["producer_recorded", "generic_public"])
def test_selected_orphan_provisional_parent_addition_refused(
    tmp_path, monkeypatch, local_source_schema, direction, route
):
    """Keep all real claims/audits while adding one unproved parent at a selected orphan genus."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [records_by_id()["24851"]["record"]])
    report = transform.finalize()
    paths = [transform.output_node_file, transform.output_edge_file]
    verify_finalized_source_files(paths)
    before = list(graph_rows(transform.output_edge_file))
    native = copy.deepcopy(report["producer_native_inputs"])
    consumed = copy.deepcopy(report["consumed_inputs"])
    inputs = copy.deepcopy(report["inputs"])
    audit = transform.output_dir / taxonomy.AUDIT_FILE
    audit_bytes = audit.read_bytes()
    links = [
        row
        for row in before
        if row["subject"] == "kgmicrobe.strain:bacdive_24851"
        and row["object"].startswith("kgmicrobe.genus:")
        and row["predicate"] == "biolink:subclass_of"
    ]
    assert len(links) == 1
    provisional = links[0]["object"]
    assert provisional == "kgmicrobe.genus:Proactinomyces"
    plans = native["taxonomy"]["fallback_native_evidence"]["plans"]
    selected = [plan for plan in plans.values() if plan["native_record"]["record_id"] == "24851"]
    assert len(selected) == 1
    assert any(node["id"] == provisional and node["kind"] == "genus" for node in selected[0]["provisional_nodes"])
    assert all(subject != provisional for subject, _ in selected[0]["parent_pairs"])
    added = dict.fromkeys(before[0], "")
    added.update(
        subject=provisional if direction == "forward" else "NCBITaxon:2",
        predicate="biolink:subclass_of",
        object="NCBITaxon:2" if direction == "forward" else provisional,
        relation="kgmicrobe:inferred_subClassOf",
        primary_knowledge_source="infores:bacdive",
        knowledge_level="prediction",
        agent_type="automated_agent",
    )
    after = [*before, added]
    assert Counter(map(_signature, before)) <= Counter(map(_signature, after))
    assert len(after) == len(before) + 1
    with transform.output_edge_file.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(before[0]),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            quotechar=None,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(after)
    report["members"][transform.output_edge_file.name] = _identity(transform.output_edge_file)
    assert all(report["members"][path.name] == _identity(path) for path in paths)
    assert report["producer_native_inputs"] == native
    assert report["consumed_inputs"] == consumed
    assert report["inputs"] == inputs
    assert audit.read_bytes() == audit_bytes
    assert report["audit_members"][audit.name] == report["producer_audit_members"][audit.name] == _identity(audit)
    report_path = transform.output_dir / "source_finalization.json"
    report_path.write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="unexpected or changed scoped taxonomy row"):
        if route == "generic_public":
            verify_finalized_source_files(paths)
        else:
            BacDiveTransform.verify_recorded_native_inputs(report, report_path, admission=SourceAdmission())
