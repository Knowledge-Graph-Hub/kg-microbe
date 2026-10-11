"""Separate finite ingredient-material admission from native authority metadata (#1290)."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from kg_microbe.utils.graph_canonicalization import compact_identifier

ROOT = Path(__file__).resolve().parents[2]
CONTEXT_POLICY = ROOT / "mappings/ingredient_context_dispositions.json"
NATIVE_AUTHORITY = ROOT / "mappings/catalase_native_authority.json"
CONTEXT_ROLE = "ingredient_material_context"
NATIVE_ROLE = "ingredient_material_native_authority"
HISTORICAL_CLAIMS = ROOT / "mappings/catalase_historical_groundings.json"
HISTORICAL_ROLE = "catalase_historical_groundings"
HISTORICAL_SHA256 = "6ef70a20e5a7206daa49b2ea10bf2d2aefee44879627a7a64de5d6017e260df2"
CONTEXT_SHA256 = "c1035fa5fac058b3a21c5ee815092020ee6811db659faa29666542d1a3872e8e"
NATIVE_SHA256 = "b95f503a2d75f162c110bd624e6e09bb29ad2d921901058d53ec01fdb1b801ac"
CATALASE_TARGET = "NCIT:C61062"
AUTHORITY_COMMENT = "native_authority_metadata_only"
QUARANTINE_COMMENT = "ingredient_identity_context_quarantine"


def validate_context_bytes(policy_bytes, native_bytes):
    """Require the reviewed finite decision and independently pinned native excerpt bytes."""
    if (
        hashlib.sha256(policy_bytes).hexdigest() != CONTEXT_SHA256
        or hashlib.sha256(native_bytes).hexdigest() != NATIVE_SHA256
    ):
        raise ValueError("Ingredient material context/native authority differs from reviewed bytes")
    policy, native = json.loads(policy_bytes), json.loads(native_bytes)
    if policy["authority_witness_sha256"] != NATIVE_SHA256 or native["target_id"] != policy["target_id"]:
        raise ValueError("Ingredient material context/native authority binding disagrees")
    return policy


@lru_cache(maxsize=1)
def ingredient_context_policy():
    """Cache one reviewed decision; producers additionally bind actual consumed snapshots."""
    return validate_context_bytes(CONTEXT_POLICY.read_bytes(), NATIVE_AUTHORITY.read_bytes())


def _context_identifier(identifier):
    """Compare the same registered identifier spellings that source finalization compacts."""
    return compact_identifier(str(identifier or "").strip()).casefold()


def ingredient_context_allowed(target):
    """Deny unscoped material identity, not declarations or metadata for the native concept."""
    if _context_identifier(target) != CATALASE_TARGET.casefold():
        return True
    ingredient_context_policy()
    return False


def ingredient_context_pair_allowed(subject, target):
    """Reject unscoped identity substitutions in either xref direction."""
    return ingredient_context_allowed(subject) and ingredient_context_allowed(target)


def catalase_material(raw, name=None, native_id=None):
    """Retain reviewed reagent forms locally; reject drift of the selected native catalog ID."""
    raw = raw if isinstance(raw, dict) else {}
    source_name = raw.get("compound", raw.get("solution", name))
    identifier = raw.get("compound_id", native_id)
    key = " ".join(source_name.split()).casefold() if isinstance(source_name, str) else ""
    # Fast path for unrelated graph-scale ingredients; this creates no identity.
    if str(identifier) != "270" and key not in {
        "catalase",
        "catalase (sigma c--10)",
        "catalase (sigma c-10)",
        "catalase (beef)",
    }:
        return False
    policy = ingredient_context_policy()
    if native_id is not None and "compound_id" in raw and str(raw["compound_id"]) != str(native_id):
        raise ValueError("Catalase occurrence and supplied native compound ID disagree")
    if name is not None and source_name != name:
        raise ValueError("Catalase occurrence and supplied source name disagree")
    if str(identifier) == policy["mediadive_compound_id"]:
        if key != "catalase" or ("attribute" in raw and raw["attribute"] not in policy["native_occurrence_attributes"]):
            raise ValueError("Reviewed MediaDive Catalase catalog/occurrence scope changed")
    if key not in {value.casefold() for value in policy["reviewed_material_names"]}:
        raise ValueError("Reviewed Catalase material spelling changed")
    # Source ownership is required before minting an ingredient or solution ID.
    identity = raw.get("compound_id", raw.get("solution_id", native_id))
    if identity is None or not re.fullmatch(r"[1-9][0-9]*", str(identity)):
        raise ValueError("Catalase material requires a canonical positive native ID")
    return True


def context_metadata_row(row):
    """Recognize only finite native annotations, never arbitrary imported metadata claims."""
    return (
        _context_identifier(row.get("object_id")) == CATALASE_TARGET.casefold()
        and row.get("predicate_id") == "skos:relatedMatch"
        and row.get("comment") == AUTHORITY_COMMENT
        and "native_ontology:ncit" in str(row.get("source", "")).split("|")
        and row.get("object_label") == "Catalase"
        and row.get("subject_label") in {"Catalase", "CAT", "CAT Protein", "EC 1.11.1.6"}
        and str(row.get("subject_id", "")).startswith("kgm.name:")
    )


def contextualize_ingredient_row(row):
    """Preserve unsupported identity candidates as nonidentity annotations during reconstruction."""
    subject, target = row.get("subject_id", ""), row.get("object_id", "")
    if (
        ingredient_context_pair_allowed(subject, target)
        or _context_identifier(subject) == _context_identifier(target)
        or row.get("predicate_id") not in {"skos:exactMatch", "skos:closeMatch"}
    ):
        return row
    result = dict(row)
    result["predicate_id"] = "skos:relatedMatch"
    result["comment"] = AUTHORITY_COMMENT
    if not context_metadata_row(result):
        result["comment"] = QUARANTINE_COMMENT
    return result
