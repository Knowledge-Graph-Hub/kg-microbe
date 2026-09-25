"""Typed scalar transport for reviewed ingredient assertions in finalized KGX."""

import re
from functools import lru_cache
from importlib.resources import files

import yaml

from kg_microbe.transform_utils.constants import (
    INGREDIENT_ANNOTATION_JSON,
    INGREDIENT_BUNDLE_SHA256,
    INGREDIENT_MAPPING_JSON,
    INGREDIENT_OCCURRENCE_ID,
    INGREDIENT_OCCURRENCE_JSON,
    INGREDIENT_PRODUCT_ID,
    INGREDIENT_PRODUCT_JSON,
    INGREDIENT_PROFILE_COLUMN,
    INGREDIENT_RECORD_KIND,
)
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json, validate_payload


@lru_cache(maxsize=1)
def ingredient_kgx_profile():
    """Read the packaged application profile paired with the pinned Biolink model."""
    return yaml.safe_load(files("kg_microbe").joinpath("profiles/ingredient_kgx_v1.yaml").read_text())


def json_scalar(value):
    """Keep JSON arrays and source text inside one scalar, never a KGX pipe list."""
    return canonical_json(value).decode("utf-8")


def validate_ingredient_fields(row, *, is_node):
    """Reject malformed, pooled or unversioned extension values at graph boundaries."""
    present = {key for key, value in row.items() if key.startswith("ingredient_") and value not in (None, "")}
    if not present:
        return
    profile = ingredient_kgx_profile()
    if present - profile["columns"].keys() or row.get(INGREDIENT_PROFILE_COLUMN) != profile["profile_id"]:
        raise ValueError("Unknown or unversioned ingredient KGX extension")
    for key in present:
        if not isinstance(row[key], str):
            raise ValueError(f"Ingredient KGX field must remain scalar: {key}")
        record = profile["columns"][key].get("record")
        if record and record != ("node" if is_node else "edge"):
            raise ValueError(f"Ingredient KGX field is on the wrong record: {key}")
    if is_node:
        if row.get(INGREDIENT_RECORD_KIND) not in profile["record_kinds"]:
            raise ValueError("Unknown ingredient record kind")
        return
    if not re.fullmatch(r"[a-f0-9]{64}", row.get(INGREDIENT_BUNDLE_SHA256, "")):
        raise ValueError("Ingredient assertion requires its source bundle digest")
    payloads = {
        INGREDIENT_MAPPING_JSON: None,
        INGREDIENT_PRODUCT_JSON: "product",
        INGREDIENT_OCCURRENCE_JSON: "occurrence",
        INGREDIENT_ANNOTATION_JSON: "identifier",
    }
    selected = present & payloads.keys()
    if len(selected) != 1:
        raise ValueError("Ingredient assertion requires exactly one structured claim")
    key = next(iter(selected))
    payload = read_json(row[key].encode("utf-8"))
    if not isinstance(payload, dict) or json_scalar(payload) != row[key]:
        raise ValueError("Ingredient claim must be a canonical scalar JSON object")
    if payloads[key]:
        validate_payload(payloads[key], payload)
    if key == INGREDIENT_OCCURRENCE_JSON:
        if row.get(INGREDIENT_OCCURRENCE_ID) != payload["occurrence_id"]:
            raise ValueError("Occurrence ID does not match its structured claim")
        if row.get(INGREDIENT_PRODUCT_ID, "") != (payload["product_id"] or ""):
            raise ValueError("Selected product does not match its source occurrence")
    elif row.get(INGREDIENT_OCCURRENCE_ID) or row.get(INGREDIENT_PRODUCT_ID):
        raise ValueError("Occurrence references require an occurrence claim")
