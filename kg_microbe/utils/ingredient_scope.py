"""Versioned ingredient scope contract, independent of identifier preference."""

from __future__ import annotations

import csv
import io
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

import yaml

PROFILE_ID = "https://w3id.org/mediaingredientmech/sssom/ingredient-scope/v1"
PROFILE_CURIE = "mimprofile:ingredient-scope/v1"


@lru_cache(maxsize=1)
def _profile() -> dict:
    profile = yaml.safe_load(
        files(__package__.split(".")[0]).joinpath("profiles/ingredient_scope_v1.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(profile, dict):
        raise ValueError("Scope profile must be a mapping")
    return profile


def scope_profile() -> dict:
    """Return the public, serializable profile without exposing cached mutable state."""
    return deepcopy(_profile())


def profile_metadata(metadata: dict, *, default_profile: bool = True) -> dict:
    """Declare extension meanings, rejecting conflicting prefix or slot definitions."""
    result = deepcopy(metadata)
    prefixes = result.setdefault("curie_map", {})
    for prefix, iri in _profile()["curie_map"].items():
        if prefix in prefixes and prefixes[prefix] != iri:
            raise ValueError(f"Conflicting scope profile prefix: {prefix}")
        prefixes[prefix] = iri
    definitions = result.setdefault("extension_definitions", [])
    if not isinstance(definitions, list):
        raise ValueError("extension_definitions must be a list")
    indexed = {}
    properties = set()
    for definition in definitions:
        slot = definition.get("slot_name")
        if not slot or slot in indexed:
            raise ValueError("Duplicate or unnamed SSSOM extension definition")
        indexed[slot] = definition
        if definition.get("property"):
            prop = _expand(definition["property"], prefixes)
            if prop in properties:
                raise ValueError(f"Duplicate SSSOM extension property: {prop}")
            properties.add(prop)
    for definition in _profile()["extension_definitions"]:
        slot = definition["slot_name"]
        if slot in indexed:
            if indexed[slot] != definition:
                raise ValueError(f"Conflicting scope extension definition: {slot}")
        else:
            prop = _expand(definition["property"], prefixes)
            if prop in properties:
                raise ValueError(f"Duplicate SSSOM extension property: {prop}")
            properties.add(prop)
            definitions.append(deepcopy(definition))
    if default_profile:
        if _expand(result.get("ext_scope_profile", PROFILE_CURIE), prefixes) != PROFILE_ID:
            raise ValueError("Unsupported ingredient scope profile")
        result["ext_scope_profile"] = PROFILE_CURIE
    return result


def _expand(value: str, prefixes: dict) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"Expected scope IRI or declared CURIE: {value!r}")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("urn:") and len(value.split(":")) > 2 and value.split(":", 2)[2]:
        return value
    prefix, sep, local = value.partition(":")
    if sep and local and prefix in prefixes:
        base = prefixes[prefix]
        if not isinstance(base, str):
            raise ValueError(f"CURIE prefix must resolve to a string: {prefix}")
        return base + local
    raise ValueError(f"Undeclared scope/evidence CURIE: {value}")


def validate_scope_row(row: dict, metadata: dict) -> bool | None:
    """
    Validate scope declarations and return identity permission, or None for legacy.

    SUPPORTED and authorization are asserted review outcomes. A release consumer
    must additionally verify the bundle's content/owner-bound review evidence.
    Equal scope vocabulary values alone never establish chemical equivalence.
    """
    fields = {item["slot_name"] for item in _profile()["extension_definitions"]}
    prefixes = metadata.get("curie_map", {})
    declared_value = metadata.get("ext_scope_profile", "")
    explicit_value = row.get("ext_scope_profile", "")
    declared = _expand(declared_value, prefixes) if declared_value else ""
    explicit = _expand(explicit_value, prefixes) if explicit_value else ""
    if declared and explicit and declared != explicit:
        raise ValueError("Conflicting row and mapping-set scope profiles")
    profile = explicit or declared
    if not profile:
        if any(row.get(field) for field in fields - {"ext_scope_profile"}):
            raise ValueError("Scope fields require a declared scope profile")
        return None
    if profile != PROFILE_ID:
        raise ValueError(f"Unsupported ingredient scope profile: {profile}")
    expected = profile_metadata(metadata, default_profile=False)
    if expected.get("extension_definitions") != metadata.get("extension_definitions"):
        raise ValueError("Scope extension definitions are missing or inconsistent")
    if any(prefixes.get(key) != value for key, value in _profile()["curie_map"].items()):
        raise ValueError("Scope profile prefixes are missing or inconsistent")

    scopes = []
    compositions = []
    for side in ("subject", "object"):
        scope = _expand(row.get(f"ext_{side}_scope", ""), prefixes)
        allowed = {prefixes["mimscope"] + value for value in _profile()["scope_values"]}
        if scope not in allowed:
            raise ValueError(f"Unknown {side} scope: {scope}")
        scopes.append(scope)
        composition = _expand(row.get(f"ext_{side}_composition", ""), prefixes)
        allowed = {prefixes["mimscope"] + value for value in _profile()["composition_values"]}
        if composition not in allowed:
            raise ValueError(f"Unknown {side} composition: {composition}")
        compositions.append(composition)
    status = row.get("ext_scope_review_status")
    if status not in _profile()["review_status_values"]:
        raise ValueError(f"Invalid scope review status: {status}")
    authorized = row.get("ext_identity_authorized")
    if authorized not in {"true", "false"}:
        raise ValueError("ext_identity_authorized must be TSV boolean true or false")
    evidence = row.get("ext_scope_evidence", "")
    if evidence:
        _expand(evidence, prefixes)
    if status in {"SUPPORTED", "WITHHOLD"} and not evidence:
        raise ValueError("Reviewed scope requires explicit evidence")
    predicate = row.get("predicate_id", "")
    if predicate not in _profile()["identity_predicates"] + _profile()["nonidentity_predicates"]:
        raise ValueError(f"Unsupported profiled mapping predicate: {predicate}")
    if authorized == "true":
        if (
            row.get("predicate_modifier", "").strip()
            or not row.get("subject_id", "").strip()
            or not row.get("object_id", "").strip()
            or status != "SUPPORTED"
            or predicate not in _profile()["identity_predicates"]
            or scopes[0] != scopes[1]
            or scopes[0] == prefixes["mimscope"] + "unknown"
            or compositions[0] != compositions[1]
        ):
            raise ValueError("Identity authorization requires supported matching scope/composition and exactMatch")
        return True
    return False


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicate metadata keys instead of accepting the last authorization."""


def _unique_mapping(loader, node):
    pairs = loader.construct_pairs(node, deep=True)
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate SSSOM metadata key: {key}")
        result[key] = value
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _load_yaml(content: str):
    loader = _UniqueLoader(content)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def read_scope_metadata(header: str) -> dict:
    """Parse declared scope metadata without accepting duplicate YAML keys."""
    if "ext_scope_profile" not in header:
        return {}
    metadata = _load_yaml(header)
    if not isinstance(metadata, dict):
        raise ValueError("Scope profile metadata must be a mapping")
    return metadata


def _compact(value: str, prefixes: dict) -> str:
    expanded = _expand(value, prefixes)
    if value.partition(":")[0] in prefixes:
        return value
    choices = [
        (len(base), prefix, expanded[len(base) :])
        for prefix, base in prefixes.items()
        if expanded.startswith(base) and expanded[len(base) :]
    ]
    if not choices:
        raise ValueError(f"SSSOM/TSV requires a declared CURIE prefix for {value}")
    _, prefix, local = max(choices)
    return f"{prefix}:{local}"


def _validate_profile_table(metadata: dict, fields: list[str], rows: list[dict]) -> None:
    if not isinstance(metadata, dict) or not metadata.get("mapping_set_id") or not metadata.get("license"):
        raise ValueError("Profiled SSSOM requires mapping_set_id and license")
    required = {"subject_id", "predicate_id", "object_id", "mapping_justification"}
    if len(fields) != len(set(fields)) or not required.issubset(fields):
        raise ValueError("Invalid profiled SSSOM columns")
    if not rows:
        raise ValueError("Profiled SSSOM requires at least one mapping")
    prefixes = metadata.get("curie_map", {})
    for definition in metadata.get("extension_definitions", []):
        for key in ("property", "type_hint"):
            value = definition.get(key, "")
            if not value or value.partition(":")[0] not in prefixes:
                raise ValueError(f"SSSOM/TSV extension {key} must be a declared CURIE")
            _expand(value, prefixes)
    for position, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed profiled SSSOM row {position}")
        if validate_scope_row(row, metadata) is None:
            raise ValueError(f"Required scope profile lost at row {position}")
        for field in required:
            if not row.get(field):
                raise ValueError(f"Missing {field} at row {position}")
            if row[field].partition(":")[0] not in prefixes:
                raise ValueError(f"SSSOM/TSV {field} must be a declared CURIE")
            _expand(row[field], prefixes)
        for definition in metadata["extension_definitions"]:
            if definition["type_hint"] == "linkml:Uriorcurie":
                value = row.get(definition["slot_name"], "")
                if value and value.partition(":")[0] not in prefixes:
                    raise ValueError(f"SSSOM/TSV {definition['slot_name']} must be a declared CURIE")


def read_profile_table(content: bytes) -> tuple[dict, list[str], list[dict]]:
    """Read a required-profile TSV without losing extensions or accepting legacy fallback."""
    stream = io.StringIO(content.decode("utf-8"))
    header = []
    for line in stream:
        if not line.startswith("#"):
            first = line
            break
        header.append(line[1:].removeprefix(" "))
    else:
        raise ValueError("Missing SSSOM table")
    metadata = _load_yaml("".join(header))
    reader = csv.DictReader(io.StringIO(first + stream.read()), delimiter="\t", strict=True)
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    _validate_profile_table(metadata, fields, rows)
    return metadata, fields, rows


def write_profile_table(metadata: dict, fields: list[str], rows: list[dict]) -> bytes:
    """Serialize declared profile extensions deterministically as standard SSSOM/TSV."""
    metadata, rows = deepcopy(metadata), deepcopy(rows)
    prefixes = metadata.get("curie_map", {})
    curie_fields = {"subject_id", "predicate_id", "object_id", "mapping_justification"}
    for definition in metadata.get("extension_definitions", []):
        for key in ("property", "type_hint"):
            definition[key] = _compact(definition[key], prefixes)
        if definition["type_hint"] == "linkml:Uriorcurie":
            field = definition["slot_name"]
            curie_fields.add(field)
            if metadata.get(field):
                metadata[field] = _compact(metadata[field], prefixes)
    for row in rows:
        for field in curie_fields:
            if row.get(field):
                row[field] = _compact(row[field], prefixes)
    _validate_profile_table(metadata, fields, rows)
    stream = io.StringIO(newline="")
    for line in yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).splitlines():
        stream.write(f"# {line}\n")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")
