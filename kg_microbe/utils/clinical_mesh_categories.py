"""Finite clinical MeSH projections grounded in reviewed native definitions, not edge tests."""

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    DISEASE_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
    PATHOLOGICAL_ANATOMICAL_STRUCTURE_CATEGORY,
    PHYSICAL_ENTITY_CATEGORY,
)
from kg_microbe.utils.native_rdf import decoded_iri_subject

CLINICAL_MESH_POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/bacdive_clinical_mesh_policy.json"
CLINICAL_MESH_IDENTIFIERS = frozenset({"mesh:D000038", "mesh:D010514"})
# Advance only through a reviewed code/policy change. A restamped policy cannot
# authenticate changed native definitions or enlarge this finite source scope.
POLICY_SHA256 = "1aab5c3e38f2ed239eb4a301addb8e6b8f7956948d69e1f9b66de8aede56b7a0"
NATIVE_STATEMENTS_SHA256 = "b24b583e924202be000211b0727638c41b08100fffb89d296b7a71c42c49c761"


def _json(value):
    """Canonicalize policy structure without treating JSON whitespace as scientific evidence."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _unique_object(pairs):
    """Reject overwritten rules or authority claims before digest verification."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate clinical MeSH policy key")
        result[key] = value
    return result


def load_clinical_mesh_policy(stream):
    """Require the complete, code-pinned four-rule reviewed policy."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    if hashlib.sha256(_json(policy).encode()).hexdigest() != POLICY_SHA256:
        raise ValueError("Clinical MeSH policy changed; complete native review required")
    return policy


@dataclass(frozen=True)
class ClinicalMeshEvidence:
    """Manual finite denotational projection; neither an OWL axiom nor a validation waiver."""

    identifier: str
    category: str
    disposition: str
    native_statements_sha256: str
    rationale: str


def _decoded_subject(subject):
    """
    Decode N-Triples IRI UCHAR escapes before finite semantic membership tests.

    The original assertion bytes remain in the evidence digest. Decoding here is
    only for identity selection: escaped spellings cannot hide additional claims
    on a reviewed descriptor or preferred concept (#1295).
    """
    return decoded_iri_subject(subject, authority="Clinical MeSH")


def load_clinical_mesh_evidence(policy, native_stream):
    """
    Verify complete selected native subject records from actual immutable gzip bytes.

    The consumed-input opener separately binds the whole gzip. This semantic
    digest binds all statements of four descriptors and their preferred concepts;
    a faithful tiny excerpt has the same selected evidence, not the same file hash.
    Never reopen the mutable original path behind the admitted snapshot.
    """
    if hashlib.sha256(_json(policy).encode()).hexdigest() != POLICY_SHA256:
        raise ValueError("Unverified clinical MeSH policy")
    wanted = {
        token
        for rule in policy["rules"]
        for token in (rule["original_mapping"]["object_id"].split(":", 1)[1], rule["concept"])
    }
    selected = []
    binary = getattr(native_stream, "buffer", native_stream)
    with gzip.GzipFile(fileobj=binary, mode="rb") as stream:
        for raw in stream:
            # Only decode selected records; graph-scale native RDF stays streamed.
            tokens = raw.split(None, 1)
            if not tokens:
                continue
            subject = _decoded_subject(tokens[0])
            token = subject.rsplit(b"/", 1)[-1].rstrip(b">").decode("ascii", errors="replace")
            if token not in wanted:
                continue
            if subject != f"<{policy['native_namespace']}{token}>".encode():
                raise ValueError("Clinical MeSH native release namespace changed")
            selected.append(raw.decode("utf-8").rstrip("\n"))
    digest = hashlib.sha256(("\n".join(sorted(selected)) + "\n").encode()).hexdigest()
    if (
        len(selected) != policy["selected_native_statement_count"]
        or len(selected) != len(set(selected))
        or digest != NATIVE_STATEMENTS_SHA256
    ):
        raise ValueError("Clinical MeSH native statements changed, absent or duplicated; review required")
    return {
        rule["original_mapping"]["object_id"]: ClinicalMeshEvidence(
            rule["original_mapping"]["object_id"],
            rule["projection"],
            rule["action"],
            digest,
            rule["reason"],
        )
        for rule in policy["rules"]
        if rule["projection"] is not None
    }


def apply_clinical_mesh_category(category, evidence):
    """Replace only reviewed disease/fallback typing; refuse incompatible substantive claims."""
    expected = {
        "mesh:D000038": PHYSICAL_ENTITY_CATEGORY,
        "mesh:D010514": PATHOLOGICAL_ANATOMICAL_STRUCTURE_CATEGORY,
    }
    if (
        evidence.identifier not in expected
        or evidence.category != expected[evidence.identifier]
        or evidence.native_statements_sha256 != NATIVE_STATEMENTS_SHA256
    ):
        raise ValueError("Unreviewed clinical MeSH category evidence")
    allowed = {DISEASE_CATEGORY, ONTOLOGY_CLASS_CATEGORY, "biolink:NamedThing", evidence.category}
    if set(category.split("|")) - {""} - allowed:
        raise ValueError(f"Unexpected substantive category for clinical MeSH {evidence.identifier}: {category}")
    return evidence.category
