"""Rejoin weakened GOLD crosswalks to complete literal native CSV observations (#1316)."""

import csv
import json
from collections import Counter
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import GOLD_PREFIX
from kg_microbe.transform_utils.gold.taxon_dispositions import verify_recorded_gold_declarations
from kg_microbe.transform_utils.microbedecoder.utils import crosswalk_curie
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

AUDIT_FILE = "gold_crosswalk_dispositions.tsv"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def verify_recorded_inputs(report, report_path, *, admission=None):
    """Require every emitted weakened observation to retain its exact source record and old claim."""
    admission = admission or SourceAdmission()
    admission = verify_recorded_gold_declarations(report, report_path, admission=admission)
    declarations = admission._gold_reference_record_guards[str(Path(report_path).absolute())]
    directory = Path(report_path).parent
    path = directory / AUDIT_FILE
    expected_identity = report.get("producer_audit_members", {}).get(AUDIT_FILE)
    if expected_identity is None or path.is_symlink() or admission.capture(path) != expected_identity:
        raise SourceFinalizationRequired("MicrobeDecoder GOLD disposition audit missing or changed")
    snapshot = report.get("consumed_inputs", {}).get("crosswalk_raw", {})
    native_path = Path(snapshot.get("path", ""))
    if admission.capture(native_path)["sha256"] != snapshot.get("sha256"):
        raise SourceFinalizationRequired("MicrobeDecoder GOLD source CSV changed")
    observations = {}
    with native_path.open(encoding="utf-8", errors="surrogateescape", newline="") as stream:
        for ordinal, row in enumerate(csv.DictReader(stream), 1):
            observations[f"sha256:{snapshot['sha256']}#record={ordinal}"] = row
    claims = Counter()
    with path.open(encoding="utf-8", newline="") as stream:
        for item in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
            native = observations.get(item["source_record"])
            emitted, original = json.loads(item["emitted_claim_json"]), json.loads(item["original_claim_json"])
            token = json.loads(item["source_token_json"])
            proof = declarations.declaration_for(emitted.get("object", ""))
            if (
                native is None
                or native != json.loads(item["native_record_json"])
                or item["source_column"] != "GOLD_Organism_ID"
                or native.get("GOLD_Organism_ID") != json.loads(item["source_cell_json"])
                or token not in [value.strip() for value in native["GOLD_Organism_ID"].split(",")]
                or emitted.get("predicate") != "biolink:related_to"
                or emitted.get("relation") != "biolink:related_to"
                or original.get("predicate") != "biolink:close_match"
                or original.get("relation") != "skos:closeMatch"
                or original.get("subject") != emitted.get("subject")
                or original.get("object") != emitted.get("object")
                or emitted.get("source_record") != item["source_record"]
                or emitted.get("source_column") != item["source_column"]
                or crosswalk_curie(token, GOLD_PREFIX) != original.get("object")
                or emitted.get("value") != token
                or proof is None
                or proof.declaration != json.loads(item["gold_declaration_json"])
                or proof.original_node != json.loads(item["gold_native_node_json"])
                or proof.evidence_sha256 != item["gold_evidence_sha256"]
            ):
                raise SourceFinalizationRequired("MicrobeDecoder GOLD disposition differs from its native field/claim")
            key = (emitted["subject"], emitted["object"], emitted["source_record"], emitted["value"])
            claims[key] += 1
    actual = Counter()
    edges = directory / "edges.tsv"
    if admission.capture(edges) != report.get("members", {}).get("edges.tsv"):
        raise SourceFinalizationRequired("MicrobeDecoder GOLD emitted graph changed")
    with edges.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row.get("source_column") == "GOLD_Organism_ID" and row["object"].startswith("gold:"):
                if row["predicate"] != "biolink:related_to" or row["relation"] != "biolink:related_to":
                    raise SourceFinalizationRequired(
                        "MicrobeDecoder unresolved GOLD crosswalk gained identity semantics"
                    )
                actual[(row["subject"], row["object"], row["source_record"], row["value"])] += 1
    # The producer deduplicates complete identical assertion rows. Repeated
    # identical source tokens remain individually represented in the audit.
    if set(actual) != set(claims) or any(count != 1 for count in actual.values()):
        raise SourceFinalizationRequired("MicrobeDecoder GOLD graph/audit observations are not conserved")
    admission.verify(metadata_only=True)
    return admission
