"""Project only thirty reviewed, source-qualified FAPROTAX predictions (#1847)."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlsplit

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    ATTRIBUTE_CATEGORY,
    ATTRIBUTE_TYPE_EVIDENCE_COLUMN,
    ATTRIBUTE_TYPE_RATIONALE_COLUMN,
    ATTRIBUTE_TYPE_SOURCE_COLUMN,
    CATEGORY_COLUMN,
    COMPUTATIONAL_MODEL,
    DESCRIPTION_COLUMN,
    FAPROTAX_KNOWLEDGE_SOURCE,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    ID_COLUMN,
    LPSN_PREFIX,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICTION,
    PROVIDED_BY_COLUMN,
    SOURCE_COLUMN,
    VALUE_COLUMN,
)
from kg_microbe.transform_utils.microbedecoder import observation_audit
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    ATTRIBUTE_TYPE_CURATION_SOURCE,
    PhenotypeCuration,
    PhenotypeMapping,
)
from kg_microbe.transform_utils.microbedecoder.utils import LPSN_ID_COLUMN, is_empty_cell, split_multivalue
from kg_microbe.utils.lpsn_utils import resolve_accepted_records

DEFAULT_DISPOSITIONS = (
    Path(__file__).resolve().parents[3] / "mappings/canonical/microbedecoder_faprotax_dispositions.tsv"
)
ROLE = "faprotax_dispositions"
CONTRACT_KEY = "faprotax_prediction_dispositions"
COLUMN = "FAPROTAX_Type_of_metabolism"
PREDICTION_DISPOSITION = "reviewed_faprotax_prediction_attribute_typing"
AUDIT_DISPOSITION = "unsupported_faprotax_assertion_preserved_observation"
REVIEWED_LITERALS = frozenset(
    {
        "chemoheterotrophy",
        "aerobic_chemoheterotrophy",
        "phototrophy",
        "photoautotrophy",
        "oxygenic_photoautotrophy",
        "photosynthetic_cyanobacteria",
        "animal_parasites_or_symbionts",
        "human_associated",
        "human_pathogens_all",
        "methylotrophy",
        "photoheterotrophy",
        "intracellular_parasites",
        "mammal_gut",
        "human_gut",
        "anoxygenic_photoautotrophy",
        "anoxygenic_photoautotrophy_S_oxidizing",
        "aerobic_anoxygenic_phototrophy",
        "plant_pathogen",
        "invertebrate_parasites",
        "anoxygenic_photoautotrophy_Fe_oxidizing",
        "human_pathogens_meningitis",
        "human_pathogens_septicemia",
        "predatory_or_exoparasitic",
        "human_pathogens_gastroenteritis",
        "human_pathogens_pneumonia",
        "oil_bioremediation",
        "anoxygenic_photoautotrophy_H2_oxidizing",
        "human_pathogens_diarrhea",
        "human_pathogens_nosocomia",
        "fish_parasites",
    }
)


def encoded(value):
    """Preserve native JSON types, source pairing and complete claim cells."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


class FaprotaxDispositions:
    """Validate finite field/literal dispositions against the consumed native METPO export."""

    def __init__(self, policy, authority):
        """Reject missing, duplicate, malformed or unsupported scope before graph writes."""
        mapping_fields = [field.name for field in fields(PhenotypeMapping)]
        reader = csv.DictReader(policy, delimiter="\t", quoting=csv.QUOTE_NONE)
        expected = ["source_column", "source_literal", "disposition", *mapping_fields[2:]]
        if reader.fieldnames != expected:
            raise ValueError("Invalid FAPROTAX disposition columns")
        self.rules = {}
        positive = io.StringIO()
        writer = csv.DictWriter(positive, fieldnames=mapping_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in reader:
            if None in row or any(value is None or value != value.strip() for value in row.values()):
                raise ValueError("Malformed FAPROTAX disposition row")
            literal = row["source_literal"]
            if row["source_column"] != COLUMN or literal not in REVIEWED_LITERALS or literal in self.rules:
                raise ValueError("Invalid or repeated FAPROTAX disposition scope")
            if not row["curation_rationale"] or not row["evidence_uri"]:
                raise ValueError("FAPROTAX disposition lacks reviewed evidence")
            for reference in row["evidence_uri"].split("|"):
                parsed = urlsplit(reference)
                if parsed.scheme != "https" or not parsed.netloc or any(char.isspace() for char in reference):
                    raise ValueError("Invalid FAPROTAX evidence URI")
            if row["disposition"] == "prediction":
                writer.writerow({key: row[key] for key in mapping_fields})
            elif row["disposition"] != "audit_only" or any(row[key] for key in mapping_fields[2:5]):
                raise ValueError("Unsupported FAPROTAX disposition or audit-only target")
            self.rules[literal] = row
        if set(self.rules) != REVIEWED_LITERALS:
            raise ValueError("Incomplete thirty-literal FAPROTAX disposition scope")
        positive.seek(0)
        self.authority = PhenotypeCuration(positive, authority)

    def resolve(self, column, literal):
        """Apply exact reviewed source fields; never create a global label synonym."""
        return self.rules.get(literal) if column == COLUMN else None


def projected_claim(original, rule):
    """Keep the original prediction edge; reviewed ontology typing belongs on its Attribute."""
    if rule["disposition"] == "audit_only":
        return None
    return dict(original)


def attribute_declaration(literal, rule):
    """Retain the exact source Attribute category and its native ontology classification slot."""
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

    return {
        ID_COLUMN: observation_audit.source_attribute_curie(COLUMN, literal),
        CATEGORY_COLUMN: ATTRIBUTE_CATEGORY,
        NAME_COLUMN: f"reported FAPROTAX Type of metabolism: {literal} (source value)",
        DESCRIPTION_COLUMN: (
            f"Reported MicrobeDecoder {COLUMN} field value. "
            "has_attribute_type is KG-Microbe's reviewed classification of this exact source value, "
            "not an independently observed phenotype or a claim that every member of the taxon has a trait. "
            "Source record, field, literal token and evidence tier remain on the original asserting edge."
        ),
        PROVIDED_BY_COLUMN: MICROBEDECODER_KNOWLEDGE_SOURCE,
        HAS_ATTRIBUTE_TYPE_COLUMN: rule["target_curie"],
        ATTRIBUTE_TYPE_SOURCE_COLUMN: ATTRIBUTE_TYPE_CURATION_SOURCE,
        ATTRIBUTE_TYPE_EVIDENCE_COLUMN: rule["evidence_uri"],
        ATTRIBUTE_TYPE_RATIONALE_COLUMN: MicrobeDecoderTransform._escape_literal(rule["curation_rationale"]),
    }


def observation(original, native, rule):
    """Retain the complete original and emitted predictions, even for unsupported biology."""
    emitted = projected_claim(original, rule)
    return {
        **observation_audit.audit_row(original, native, PREDICTION_DISPOSITION if emitted else AUDIT_DISPOSITION),
        "emitted_claim_json": encoded(emitted),
        "evidence_uri": rule["evidence_uri"],
        "curation_rationale": rule["curation_rationale"],
    }


def verify_outputs(snapshots, directory, edge_fields, *, admission=None):
    """Independently replay all reviewed native observations and complete emitted graph rows."""
    from kg_microbe.transform_utils.microbedecoder.bacdive_join_dispositions import _field_limit_for
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

    admission = admission or SourceAdmission()
    paths = {}
    for role in ("crosswalk_raw", "bacdive_join_lpsn_gss", ROLE, "process_authority"):
        saved = snapshots.get(role)
        if not isinstance(saved, dict) or set(saved) != {"path", "sha256"}:
            raise ValueError("Missing FAPROTAX consumed input: " + role)
        path = Path(saved["path"])
        if admission.capture(path)["sha256"] != saved["sha256"]:
            raise ValueError("FAPROTAX consumed input changed: " + role)
        paths[role] = path
    if paths[ROLE].resolve() != DEFAULT_DISPOSITIONS.resolve():
        raise ValueError("FAPROTAX selected policy changed")
    with (
        paths[ROLE].open(encoding="utf-8", newline="") as policy,
        paths["process_authority"].open(encoding="utf-8", newline="") as authority,
    ):
        curation = FaprotaxDispositions(policy, authority)
    with paths["bacdive_join_lpsn_gss"].open(encoding="utf-8", newline="") as stream:
        records = {}
        for row in csv.DictReader(stream):
            key = row["record_no"]
            if key in records:
                raise ValueError("Duplicate consumed GSS record")
            records[key] = row
    accepted = resolve_accepted_records(records)
    expected_audit, expected_edges, expected_nodes = [], set(), {}
    builder = MicrobeDecoderTransform.__new__(MicrobeDecoderTransform)
    builder.edge_header = list(edge_fields)
    with (
        paths["crosswalk_raw"].open(encoding="utf-8", errors="surrogateescape", newline="") as stream,
        _field_limit_for(stream),
    ):
        for ordinal, native in enumerate(csv.DictReader(stream), 1):
            source_id = native.get(LPSN_ID_COLUMN)
            if is_empty_cell(source_id):
                continue
            source_id = str(source_id).strip()
            subject = LPSN_PREFIX + accepted.get(source_id, source_id)
            builder._source_record = f"sha256:{snapshots['crosswalk_raw']['sha256']}#record={ordinal}"
            for literal in split_multivalue(native.get(COLUMN)):
                rule = curation.resolve(COLUMN, literal)
                if rule is None:
                    continue
                values = builder._make_edge_row(
                    subject,
                    HAS_ATTRIBUTE_PREDICATE,
                    observation_audit.source_attribute_curie(COLUMN, literal),
                    HAS_ATTRIBUTE_RELATION,
                    FAPROTAX_KNOWLEDGE_SOURCE,
                    source_column=COLUMN,
                    value=literal,
                    knowledge_level=PREDICTION,
                    agent_type=COMPUTATIONAL_MODEL,
                )
                original = dict(zip(edge_fields, (value or "" for value in values), strict=True))
                expected_audit.append(observation(original, native, rule))
                emitted = projected_claim(original, rule)
                if emitted:
                    expected_edges.add(encoded(emitted))
                    declaration = attribute_declaration(literal, rule)
                    expected_nodes[declaration[ID_COLUMN]] = declaration
    audit_path = Path(directory) / observation_audit.AUDIT_FILE
    edge_path = Path(directory) / "edges.tsv"
    node_path = Path(directory) / "nodes.tsv"
    for path in (audit_path, edge_path, node_path):
        admission.capture(path)
    with audit_path.open(encoding="utf-8", newline="") as stream, _field_limit_for(stream):
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if reader.fieldnames != list(observation_audit.AUDIT_FIELDS):
            raise ValueError("FAPROTAX audit header changed")
        actual = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed FAPROTAX audit row")
            if row[SOURCE_COLUMN] == COLUMN:
                actual.append(row)
        if actual != expected_audit:
            raise ValueError("FAPROTAX audit differs from complete native observations")
    actual_edges = Counter()
    targets = {observation_audit.source_attribute_curie(COLUMN, literal) for literal in REVIEWED_LITERALS}
    with edge_path.open(encoding="utf-8", newline="") as stream, _field_limit_for(stream):
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if (
            not reader.fieldnames
            or not set(edge_fields).issubset(reader.fieldnames)
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
        ):
            raise ValueError("FAPROTAX graph header changed")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed FAPROTAX graph row")
            if row[OBJECT_COLUMN] in targets or (
                row[SOURCE_COLUMN] == COLUMN and row[VALUE_COLUMN] in REVIEWED_LITERALS
            ):
                if any(value for key, value in row.items() if key not in edge_fields):
                    raise ValueError("Unexpected FAPROTAX finalized provenance extension")
                actual_edges[encoded({key: row[key] for key in edge_fields})] += 1
    if actual_edges != Counter(dict.fromkeys(expected_edges, 1)):
        raise ValueError("FAPROTAX graph differs from complete reviewed predictions")
    actual_nodes = {}
    with node_path.open(encoding="utf-8", newline="") as stream, _field_limit_for(stream):
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        required = set(attribute_declaration("chemoheterotrophy", curation.rules["chemoheterotrophy"]))
        if (
            not reader.fieldnames
            or not required.issubset(reader.fieldnames)
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
        ):
            raise ValueError("FAPROTAX Attribute node header changed")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed FAPROTAX Attribute node")
            identifier = row[ID_COLUMN]
            if identifier not in targets:
                continue
            if identifier in actual_nodes or any(value for key, value in row.items() if key not in required):
                raise ValueError("Duplicate or unexpected FAPROTAX Attribute declaration")
            actual_nodes[identifier] = {key: row[key] for key in required}
    if actual_nodes != expected_nodes:
        raise ValueError("FAPROTAX Attribute typing differs from the native field/ontology declaration")
    admission.verify()
    return admission, {
        "version": 1,
        "policy_sha256": snapshots[ROLE]["sha256"],
        "source_observations": len(expected_audit),
        "prediction_assertions": len(expected_edges),
        "representation": "reported_attribute_with_native_has_attribute_type",
        "typed_attribute_nodes": len(expected_nodes),
        "audit_only_observations": sum(row["disposition"] == AUDIT_DISPOSITION for row in expected_audit),
    }


def verify_recorded(report, directory, edge_fields, *, admission=None):
    """Rejoin the recorded source against current curation and exact native observations."""
    admission, actual = verify_outputs(report.get("consumed_inputs", {}), directory, edge_fields, admission=admission)
    if encoded(report.get("producer_native_inputs", {}).get(CONTRACT_KEY)) != encoded(actual):
        raise ValueError("FAPROTAX native contract changed")
    return admission
