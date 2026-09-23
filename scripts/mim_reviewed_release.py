"""
Validate a pinned MIM reviewed SSSOM release without accessing the network.

This checks the publisher's complete partition and preserves its decisions; it
does not repeat the scientific review or treat withheld rows as false mappings.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SUPPORTED_FILE = "ingredient_mappings.sssom.tsv"
WITHHELD_FILE = "withheld_mappings.sssom.tsv"
DISPOSITIONS_FILE = "mapping-dispositions.tsv"
PRODUCT_FILES = frozenset((SUPPORTED_FILE, WITHHELD_FILE, DISPOSITIONS_FILE))
DISPOSITION_FIELDS = (
    "source_position",
    "row_sha256",
    "subject_id",
    "predicate_id",
    "object_id",
    "owner_record",
    "owner_record_sha256",
    "disposition",
    "review_reason",
    "review_evidence",
    "evidence_key",
)
_TRIPLE_FIELDS = ("subject_id", "predicate_id", "object_id")
_SCOPE = "MIM-only reviewed SSSOM; no KGX dependency"


@dataclass(frozen=True)
class ReviewedBundle:
    """Contain verified rows and the publisher's hash-bound provenance claims."""

    directory: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    source_sha256: str
    review_sha256: str
    supported_metadata: dict[str, Any]
    withheld_metadata: dict[str, Any]
    supported_rows: tuple[dict[str, str], ...]
    withheld_rows: tuple[dict[str, str], ...]
    disposition_rows: tuple[dict[str, str], ...]


def _unique_object(pairs):
    """Reject duplicate manifest and YAML keys instead of silently replacing them."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key in release metadata: {key}")
        result[key] = value
    return result


class _UniqueSafeLoader(yaml.SafeLoader):
    """Read ordinary YAML while rejecting duplicate mapping keys."""


def _yaml_mapping(loader, node):
    """Construct a duplicate-free mapping with the safe YAML loader."""
    loader.flatten_mapping(node)
    return _unique_object((loader.construct_object(key), loader.construct_object(value)) for key, value in node.value)


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _sha256(value: Any, label: str) -> str:
    """Require a canonical SHA-256 digest string."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid SHA-256 for {label}")
    return value


def _safe_relative(value: Any, label: str) -> None:
    """Check provenance paths without opening the referenced upstream files."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or "\\" in value
    ):
        raise ValueError(f"Invalid relative path for {label}")


def _snapshot(directory: Path, name: str) -> bytes:
    """Read only a fixed regular bundle file, never a symbolic link."""
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe release file: {name}")
    return path.read_bytes()


def _table(text: str, label: str) -> tuple[list[str], tuple[dict[str, str], ...]]:
    """Read a TSV without tolerating duplicate columns or malformed row widths."""
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t", strict=True)
    fields = list(reader.fieldnames or ())
    if not fields or any(not field for field in fields) or len(fields) != len(set(fields)):
        raise ValueError(f"Invalid TSV columns in {label}")
    rows = tuple(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Malformed TSV row width in {label}")
    return fields, rows


def _sssom(content: bytes, label: str):
    """Parse verified bytes and apply installed SSSOM schema/prefix validation."""
    from sssom.parsers import parse_sssom_table
    from sssom.validators import SchemaValidationType, check_all_prefixes_in_curie_map, validate

    text = content.decode("utf-8")
    lines = text.splitlines(keepends=True)
    end = 0
    while end < len(lines) and lines[end].startswith("#"):
        end += 1
    loader = _UniqueSafeLoader("".join(line[1:].removeprefix(" ") for line in lines[:end]))
    try:
        metadata = loader.get_single_data()
    finally:
        loader.dispose()
    if not isinstance(metadata, dict) or metadata.get("predicate_semantics") != "skos":
        raise ValueError(f"SSSOM needs predicate_semantics: skos in {label}")
    fields, rows = _table("".join(lines[end:]), label)
    required = {*_TRIPLE_FIELDS, "subject_label", "object_label", "mapping_justification", "other"}
    if not required.issubset(fields):
        raise ValueError(f"Missing SSSOM columns in {label}: {sorted(required - set(fields))}")
    for row in rows:
        if any(not row[field].strip() for field in _TRIPLE_FIELDS) or not re.fullmatch(r"MIM:\S+", row["subject_id"]):
            raise ValueError(f"Non-MIM or incomplete mapping in {label}")
        confidence = row.get("confidence", "").strip()
        if confidence and not math.isfinite(float(confidence)):
            raise ValueError(f"SSSOM confidence must be finite in {label}")
    # Use the same verified bytes for both parsers; never reread a mutable path.
    mapping_set = parse_sssom_table(io.StringIO(text))
    validate(mapping_set, [SchemaValidationType.JsonSchema], fail_on_error=True)
    check_all_prefixes_in_curie_map(mapping_set)
    return metadata, fields, rows


def row_sha256(row: dict[str, str]) -> str:
    """
    Hash exactly as MIM's reviewed_sssom.py at revision 484082707b2a175c.

    Upstream hashes every parsed column, including empty strings and Unicode:
    https://github.com/CultureBotAI/MediaIngredientMech/blob/484082707b2a175cffebad3cbf46f3b39f66ca3d/src/mediaingredientmech/export/reviewed_sssom.py
    """
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assertion_key(row: dict[str, str], digest: str) -> tuple[str, ...]:
    """Bind the assertion triple to the complete original row payload."""
    return (*(row[field] for field in _TRIPLE_FIELDS), digest)


def _validate_partition(supported, withheld, dispositions, source_count):
    """Require one valid disposition per source position and exact row coverage."""
    positions = set()
    actual = {"SUPPORTED": Counter(), "WITHHOLD": Counter()}
    for row in dispositions:
        position = row["source_position"]
        if re.fullmatch(r"[1-9][0-9]*", position) is None or int(position) in positions:
            raise ValueError("Invalid or duplicate source_position in dispositions")
        positions.add(int(position))
        status = row["disposition"]
        if status not in actual:
            raise ValueError(f"Invalid mapping disposition: {status}")
        digest = _sha256(row["row_sha256"], "disposition row")
        _sha256(row["owner_record_sha256"], "owner record")
        for field in ("review_reason", "review_evidence", "evidence_key", "owner_record"):
            if not row[field].strip():
                raise ValueError(f"Missing disposition {field}")
        _safe_relative(row["owner_record"], "owner_record")
        _safe_relative(row["review_evidence"], "review_evidence")
        actual[status][_assertion_key(row, digest)] += 1
    if positions != set(range(1, source_count + 1)):
        raise ValueError("Dispositions must have gap-free source_position coverage")
    for status, rows in (("SUPPORTED", supported), ("WITHHOLD", withheld)):
        expected = Counter(_assertion_key(row, row_sha256(row)) for row in rows)
        if actual[status] != expected:
            raise ValueError(f"{status} partition disagrees with disposition triples or row hashes")
    if actual["SUPPORTED"].keys() & actual["WITHHOLD"].keys():
        raise ValueError("The same complete assertion appears in both dispositions")


def validate_reviewed_bundle(directory: Path, *, expected_manifest_sha256: str) -> ReviewedBundle:
    """
    Validate a complete pinned release before callers perform integration writes.

    The manifest pin must come from the selected release, not from this bundle.
    Source/review hashes are checked for shape and returned as publisher claims;
    their original upstream files are not part of this four-file distribution.
    No network requests or filesystem writes are performed.
    """
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Missing or unsafe release directory: {directory}")
    directory = directory.resolve()
    expected_manifest_sha256 = _sha256(expected_manifest_sha256, "expected manifest")
    manifest_bytes = _snapshot(directory, "manifest.json")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("Release manifest SHA-256 does not match the pinned release")
    manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict):
        raise ValueError("Release manifest must be a JSON object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported release schema_version")
    if manifest.get("semantic_status") != "PASS_SUPPORTED_SUBSET" or manifest.get("scope") != _SCOPE:
        raise ValueError("Expected a MIM-only PASS_SUPPORTED_SUBSET release")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != PRODUCT_FILES:
        raise ValueError("Release files must match the three fixed product filenames")
    snapshots = {}
    for name in sorted(PRODUCT_FILES):
        expected = _sha256(files[name], name)
        content = _snapshot(directory, name)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Release SHA-256 mismatch: {name}")
        snapshots[name] = content
    source_sha256 = _sha256(manifest.get("source_sha256"), "source")
    review_sha256 = _sha256(manifest.get("review_sha256"), "review")
    _safe_relative(manifest.get("source_sssom"), "source_sssom")
    counts = manifest.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != {"source", "supported", "withhold"}
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["source"] != counts["supported"] + counts["withhold"]
        or not counts["supported"]
    ):
        raise ValueError("Invalid source/supported/withhold release counts")
    identifiers = manifest.get("mapping_set_ids")
    if (
        not isinstance(identifiers, dict)
        or set(identifiers) != {"supported", "withhold"}
        or any(not isinstance(value, str) or not value.strip() for value in identifiers.values())
        or identifiers["supported"] == identifiers["withhold"]
    ):
        raise ValueError("Release needs distinct supported and withheld mapping_set_ids")
    supported_metadata, supported_fields, supported = _sssom(snapshots[SUPPORTED_FILE], SUPPORTED_FILE)
    withheld_metadata, withheld_fields, withheld = _sssom(snapshots[WITHHELD_FILE], WITHHELD_FILE)
    if supported_fields != withheld_fields:
        raise ValueError("Supported and withheld SSSOM columns differ")
    for group, metadata, rows in (
        ("supported", supported_metadata, supported),
        ("withhold", withheld_metadata, withheld),
    ):
        if metadata.get("mapping_set_id") != identifiers[group]:
            raise ValueError(f"SSSOM mapping_set_id disagrees with manifest: {group}")
        if len(rows) != counts[group]:
            raise ValueError(f"SSSOM row count disagrees with manifest: {group}")
    if supported_metadata.get("mapping_set_version") != withheld_metadata.get("mapping_set_version"):
        raise ValueError("Supported and withheld mapping_set_version differ")
    if any(row["predicate_id"] != "skos:exactMatch" for row in supported):
        raise ValueError("Supported MIM mappings must all use skos:exactMatch")
    fields, dispositions = _table(snapshots[DISPOSITIONS_FILE].decode("utf-8"), DISPOSITIONS_FILE)
    if tuple(fields) != DISPOSITION_FIELDS or len(dispositions) != counts["source"]:
        raise ValueError("Invalid disposition columns or source row count")
    _validate_partition(supported, withheld, dispositions, counts["source"])
    return ReviewedBundle(
        directory=directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        source_sha256=source_sha256,
        review_sha256=review_sha256,
        supported_metadata=supported_metadata,
        withheld_metadata=withheld_metadata,
        supported_rows=supported,
        withheld_rows=withheld,
        disposition_rows=dispositions,
    )
