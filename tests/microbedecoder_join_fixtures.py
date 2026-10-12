"""Authentic tiny consumed inputs for the six-link protocol, not scientific authority evidence."""

import csv
import hashlib
import json
from pathlib import Path

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_transform import _NoChebi, _supply_gold_fold_report


def _json(value):
    """Use the production decoded-source hashing convention."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value):
    """Hash literal fixture bytes."""
    return hashlib.sha256(value).hexdigest()


def prepare(tmp_path, monkeypatch, *, selected=(1,), empty=False, native_cases=None):
    """Use an actual producer, immutable snapshot readers and isolated literal native rows."""
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    raw.mkdir(parents=True)
    output.mkdir()
    source = raw / "database.csv"
    fields = ["LPSN_ID", "BacDive_ID", "BacDive_Oxygen_tolerance", "FAPROTAX_Type_of_metabolism", "Species"]
    rows = (
        []
        if empty
        else [
            dict(zip(fields, ("103", "42", "aerobic", "chemoheterotrophy", "selected literal record"), strict=False)),
            dict(
                zip(fields, ("101", "42", "aerobic", "chemoheterotrophy", "same IDs, independent record"), strict=False)
            ),
            dict(zip(fields, ("", "42", "", "", "blank LPSN remains skipped"), strict=False)),
        ]
    )
    if native_cases is not None:
        rows = [item["native_row"] for item in native_cases]
        fields = list(rows[0])
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    gss_rows = [
        {"record_no": "101", "record_lnk": "", "status": "correct name"},
        {"record_no": "103", "record_lnk": "101", "status": "synonym"},
    ]
    if native_cases is not None:
        gss_rows = [{"record_no": row["LPSN_ID"], "record_lnk": "", "status": "correct name"} for row in rows]
    gss = raw / "lpsn_gss.csv"
    with gss.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(gss_rows[0]))
        writer.writeheader()
        writer.writerows(gss_rows)
    _supply_gold_fold_report(output)
    (output / "ontologies/fixture_nodes.tsv").write_text(
        "id\tcategory\tname\n"
        "lpsn:101\tbiolink:OrganismTaxon\tSynthetic accepted name\n"
        "kgmicrobe.strain:bacdive_42\tbiolink:OrganismTaxon\tSynthetic named strain\n"
    )
    directory = tmp_path / "join-policy"
    directory.mkdir()
    evidence_path = directory / "evidence.json"
    decisions, witnesses = [], []
    for ordinal in selected:
        row = rows[ordinal - 1]
        bacdive_id = row["BacDive_ID"]
        accepted = row["LPSN_ID"] if native_cases is not None else "101"
        gss_row = next(item for item in gss_rows if item["record_no"] == accepted)
        record = {"General": {"BacDive-ID": int(bacdive_id), "doi": "synthetic offline fixture"}}
        family = "incorrect_deposit_number"
        decisions.append(
            {
                "ordinal": ordinal,
                "raw_record_sha256": _hash(_json(row).encode()),
                "raw_lpsn_id": row["LPSN_ID"],
                "accepted_lpsn_id": accepted,
                "source_cell": bacdive_id,
                "source_token": bacdive_id,
                "bacdive_id": bacdive_id,
                "witness_family": family,
                "disposition": "quarantine_contradicted_record_join",
            }
        )
        witnesses.append(
            {
                "ordinal": ordinal,
                "native_md_row": row,
                "md_accepted_gss_row": {"full_row": gss_row},
                "bacdive_complete_decoded_record": {
                    "bacdive_id": int(bacdive_id),
                    "record": record,
                    "canonical_record_sha256": _hash(_json(record).encode()),
                },
                "primary_witness": {"witness_family": family},
                "fixture_boundary": "Synthetic protocol perturbation, not reviewed biological primary evidence.",
                "snapshot_projection": _projection(row, accepted, native_cases[ordinal - 1] if native_cases else None),
            }
        )
    evidence = {
        "version": 1,
        "cases": witnesses,
        "snapshot_observation_disposition": joins.SNAPSHOT_DISPOSITION,
    }
    evidence_path.write_text(_json(evidence))
    policy = {
        "version": 1,
        "source_sha256": _hash(source.read_bytes()),
        "source_records": len(rows),
        "lpsn_gss_sha256": _hash(gss.read_bytes()),
        "evidence_file": evidence_path.name,
        "evidence_sha256": _hash(evidence_path.read_bytes()),
        "decisions": decisions,
        "snapshot_observation_disposition": joins.SNAPSHOT_DISPOSITION,
    }
    policy_path = directory / "policy.json"
    policy_path.write_text(_json(policy))
    # Only the tests replace trusted immutable scientific anchors with the
    # explicit fixture anchors. There is no runtime bypass/profile/skip switch.
    monkeypatch.setattr(joins, "POLICY_SHA256", _hash(policy_path.read_bytes()))
    monkeypatch.setattr(joins, "EVIDENCE_SHA256", _hash(evidence_path.read_bytes()))
    monkeypatch.setattr(joins, "DECISIONS_SHA256", _hash(_json(decisions).encode()))
    transform = MicrobeDecoderTransform(raw, output, chemical_loader=_NoChebi(), bacdive_join_policy=policy_path)
    bind_fixture_quarantine_policy(transform, source, selected=())
    return transform, source, gss, policy_path, rows


def _projection(row, accepted, saved):
    """Use saved native expectations, or finite independently built synthetic expectations."""
    if saved is not None:
        return {
            "source_values": [[item["source_column"], item["value"]] for item in saved["snapshot_rows"]],
            "phenotype_audits": [{**item, "subject": "lpsn:" + accepted} for item in saved["phenotype_audits"]],
        }
    with (Path(__file__).parents[1] / "mappings/canonical/microbedecoder_phenotype_mappings.tsv").open() as stream:
        rules = {
            (item["source_column"], item["source_literal"]): item for item in csv.DictReader(stream, delimiter="\t")
        }
    audits = []
    for column, label in (
        ("BacDive_Oxygen_tolerance", "aerobic"),
        ("FAPROTAX_Type_of_metabolism", "chemoheterotrophy"),
    ):
        if row.get(column) != label or (column, label) not in rules:
            continue
        mapping = rules[column, label]
        prediction = column.startswith("FAPROTAX_")
        audits.append(
            {
                "subject": "lpsn:" + accepted,
                "source_record": "fixture-original",
                "source_column": column,
                "value": label,
                "value_encoding": "backslash",
                "primary_knowledge_source": "infores:faprotax" if prediction else "infores:microbedecoder",
                "knowledge_level": "prediction" if prediction else "knowledge_assertion",
                "agent_type": "computational_model" if prediction else "manual_agent",
                **{
                    key: mapping[key]
                    for key in ("target_curie", "target_label", "target_category", "evidence_uri", "curation_rationale")
                },
                "disposition": "reviewed_literal_grounding_not_graph_assertion",
            }
        )
    return {"source_values": [["BacDive_Oxygen_tolerance", "aerobic"]], "phenotype_audits": audits}
