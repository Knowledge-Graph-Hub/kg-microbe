"""Portable, versioned validation for registry and occurrence companion claims."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .ingredient_scope import (
    profile_metadata,
    read_profile_table,
    scope_profile,
    validate_scope_row,
    write_profile_table,
)
from .review_claims import validate_review_decision

BUNDLE_VERSION = 1
CAPABILITIES = frozenset(
    {
        "ingredient-scope-v1",
        "owner-bound-review-v1",
        "identifier-annotations-v1",
        "ingredient-occurrences-v1",
        "catalog-products-v1",
    }
)
REQUIRED_CAPABILITIES = frozenset({"ingredient-scope-v1", "owner-bound-review-v1", "identifier-annotations-v1"})
ANNOTATION_FIELDS = (
    "annotation_id",
    "owner_id",
    "identifier",
    "raw_identifier",
    "identifier_scope",
    "identifier_validity",
    "source_status",
    "source_currentness",
    "source_id",
    "source_version",
    "retrieved_at",
    "evidence",
    "review_status",
    "xref_eligible",
)
SCHEMA_NAME = "ingredient_bundle_v1.schema.json"
PROFILE_NAME = "ingredient_scope_v1.yaml"
HISTORICAL_STATUSES = frozenset({"SUPERSEDED", "HISTORICAL", "DEPRECATED", "WITHDRAWN"})


def canonical_json(value) -> bytes:
    """Encode a deterministic JSON value, rejecting non-finite numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def content_sha256(content: bytes) -> str:
    """Identify exact bytes, without trusting a caller-supplied digest."""
    return hashlib.sha256(content).hexdigest()


def stable_id(kind: str, key) -> str:
    """Identify a source claim or entity by its documented natural key."""
    return f"MIM.{kind}:" + content_sha256(canonical_json(key))


def annotation_id(payload: dict) -> str:
    """Keep source/version/status claims distinct while binding revisions separately."""
    return stable_id(
        "annotation",
        [
            payload[k]
            for k in (
                "owner_id",
                "identifier",
                "raw_identifier",
                "source_id",
                "source_status",
                "source_version",
                "retrieved_at",
            )
        ],
    )


def product_id(supplier: str, catalog_number: str) -> str:
    """Identify a supplier/catalog product specification, never an individual lot."""
    return stable_id("product", [supplier.strip().casefold(), catalog_number.strip()])


def occurrence_id(source_id: str, source_occurrence_key: str) -> str:
    """Keep an explicitly named source occurrence stable across payload corrections."""
    return stable_id("occurrence", [source_id, source_occurrence_key])


def alternative_id(occurrence: str, group_key: str) -> str:
    """Identify an alternatives group independently of its current option payloads."""
    return stable_id("alternative", [occurrence, group_key])


def valid_cas(identifier: str) -> bool:
    """Validate normalized CAS syntax and checksum without guessing a replacement."""
    if not re.fullmatch(r"cas:[1-9][0-9]{1,6}-[0-9]{2}-[0-9]", identifier):
        return False
    digits = identifier.removeprefix("cas:").replace("-", "")
    return sum(i * int(value) for i, value in enumerate(reversed(digits[:-1]), 1)) % 10 == int(digits[-1])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate bundle JSON key: {key}")
        result[key] = value
    return result


def read_json(content: bytes):
    """Read JSON without silently choosing between duplicate keys or NaN values."""

    def invalid_number(value):
        """Reject JSON's nonstandard NaN and infinity tokens."""
        raise ValueError(f"Non-finite bundle JSON number: {value}")

    return json.loads(content, object_pairs_hook=_unique_object, parse_constant=invalid_number)


@lru_cache(maxsize=2)
def contract_resource(name: str) -> bytes:
    """Read the pinned packaged schema/profile, not a remote default."""
    if name not in {SCHEMA_NAME, PROFILE_NAME}:
        raise ValueError(f"Unknown ingredient bundle contract resource: {name}")
    return files(__package__.split(".")[0]).joinpath("profiles/" + name).read_bytes()


@lru_cache(maxsize=3)
def _validator(kind: str):
    if kind not in {"identifier", "product", "occurrence"}:
        raise ValueError(f"Unknown companion claim kind: {kind}")
    schema = read_json(contract_resource(SCHEMA_NAME))
    return Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]})


def validate_payload(kind: str, payload: dict) -> None:
    """Validate claim shape and nonidentity rules before review or graph use."""
    canonical_json(payload)
    errors = sorted(_validator(kind).iter_errors(payload), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError(f"Invalid {kind} claim: {errors[0].message}")
    if kind == "identifier":
        if payload["annotation_id"] != annotation_id(payload):
            raise ValueError("Identifier annotation ID does not match its source/owner tuple")
        identifier = payload["identifier"]
        validity = payload["identifier_validity"]
        if identifier and (
            not re.fullmatch(r"\S+:\S+", identifier)
            or (identifier.lower().startswith("cas:") and not valid_cas(identifier))
        ):
            raise ValueError("Invalid normalized identifier; preserve rejected raw evidence instead")
        if validity == "VALID" and not identifier:
            raise ValueError("Valid identifier claim requires an identifier")
        if validity == "INVALID" and (identifier or not payload["raw_identifier"]):
            raise ValueError("Invalid source value must stay raw; no inferred replacement identifier")
        if (
            payload["source_status"].strip().upper() in HISTORICAL_STATUSES
            and payload["source_currentness"] != "HISTORICAL"
        ):
            raise ValueError("A historical source claim cannot be relabeled current")
        date.fromisoformat(payload["retrieved_at"])
        if payload["xref_eligible"] and (
            payload["review_status"] != "SUPPORTED"
            or validity != "VALID"
            or payload["source_currentness"] != "CURRENT"
            or payload["identifier_scope"] == "unknown"
        ):
            raise ValueError("Active xref requires a supported, current, valid and scoped claim")
    elif kind == "product":
        if not payload["supplier"].strip() or not payload["catalog_number"].strip():
            raise ValueError("Product specification requires a nonblank supplier and catalog key")
        if payload["product_id"] != product_id(payload["supplier"], payload["catalog_number"]):
            raise ValueError("Product ID does not match supplier/catalog specification")
    else:
        if not payload["source_occurrence_key"].strip():
            raise ValueError("Occurrence requires a nonblank source key")
        occurrence = occurrence_id(payload["source_id"], payload["source_occurrence_key"])
        if payload["occurrence_id"] != occurrence:
            raise ValueError("Occurrence ID does not match its source key")
        groups = set()
        for group in payload["alternatives"]:
            group_id = alternative_id(occurrence, group["group_key"])
            if group["alternative_group_id"] != group_id or group_id in groups:
                raise ValueError("Invalid or duplicate occurrence alternative group")
            groups.add(group_id)
            products = [member["product_id"] for member in group["members"]]
            if len(products) != len(set(products)):
                raise ValueError("Duplicate product alternative")
        if groups and payload["product_id"] is not None:
            raise ValueError("An unresolved alternative group cannot assert a selected product")


def annotation_table(rows: list[dict]) -> bytes:
    """Serialize one complete source claim per TSV row; evidence is one JSON cell."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: item["annotation_id"]):
        validate_payload("identifier", row)
        encoded = dict(
            row,
            evidence=canonical_json(row["evidence"]).decode(),
            xref_eligible=str(row["xref_eligible"]).lower(),
        )
        writer.writerow(encoded)
    return stream.getvalue().encode()


def read_annotation_table(content: bytes) -> list[dict]:
    """Restore exact identifier/source/status tuples with strict column and boolean types."""
    reader = csv.DictReader(io.StringIO(content.decode()), delimiter="\t", strict=True)
    if reader.fieldnames != list(ANNOTATION_FIELDS):
        raise ValueError("Unsupported identifier-annotation columns")
    result = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed identifier-annotation row")
        if row["xref_eligible"] not in {"true", "false"}:
            raise ValueError("Annotation xref_eligible must be a TSV boolean")
        payload = dict(
            row,
            evidence=read_json(row["evidence"].encode()),
            xref_eligible=row["xref_eligible"] == "true",
        )
        validate_payload("identifier", payload)
        result.append(payload)
    if len({row["annotation_id"] for row in result}) != len(result):
        raise ValueError("Duplicate identifier annotation ID")
    return result


def safe_member(root: Path, name: str) -> Path:
    """Confine manifest members to the bundle directory, including resolved symlinks."""
    path = Path(name)
    if not name or path.as_posix() != name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe ingredient bundle member: {name}")
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Ingredient bundle member escapes its root: {name}")
    return result


def validate_member_hashes(root: Path, manifest: dict, capabilities=CAPABILITIES) -> dict[str, bytes]:
    """Reject unsupported versions, capabilities, changed bytes and undeclared files."""
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != BUNDLE_VERSION:
        raise ValueError("Unsupported ingredient bundle version")
    required = manifest.get("required_capabilities")
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise ValueError("Missing ingredient bundle capabilities")
    if len(set(required)) != len(required) or not REQUIRED_CAPABILITIES.issubset(required):
        raise ValueError("Required ingredient bundle capability was lost")
    if set(required) - set(capabilities):
        raise ValueError("Consumer lacks required ingredient bundle capabilities")
    members = manifest.get("members")
    if not isinstance(members, dict) or not members:
        raise ValueError("Ingredient bundle has no declared members")
    contents = {}
    for name, expected in members.items():
        if not isinstance(expected, dict) or set(expected) != {"sha256", "bytes"}:
            raise ValueError(f"Invalid bundle member declaration: {name}")
        content = safe_member(root, name).read_bytes()
        if content_sha256(content) != expected["sha256"] or len(content) != expected["bytes"]:
            raise ValueError(f"Ingredient bundle member digest/size mismatch: {name}")
        contents[name] = content
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != {"manifest.json", *members}:
        raise ValueError("Ingredient bundle contains missing or undeclared members")
    for name in (SCHEMA_NAME, PROFILE_NAME):
        if contents.get(name) != contract_resource(name):
            raise ValueError(f"Unsupported or modified ingredient bundle contract: {name}")
    return contents


ARTIFACTS = {
    "mappings": "ingredient_mappings.sssom.tsv",
    "identifiers": "ingredient_identifier_annotations.tsv",
    "products": "ingredient_products.json",
    "occurrences": "ingredient_occurrences.json",
}


def _owner_id(owner: str) -> str:
    stem = Path(owner).stem
    safe = re.sub(r"[^A-Za-z0-9_\-.]", lambda m: f"~{ord(m.group(0)):02X}", stem)
    if not owner.startswith("data/ingredients/") or not owner.endswith(".yaml"):
        raise ValueError("Claim owner must be an ingredient record")
    return f"MIM:{safe}"


def _base_table(content: bytes) -> tuple[dict, list[str], list[dict]]:
    """Read original source rows losslessly; only reviewed selections can be exported."""
    stream = io.StringIO(content.decode())
    header = []
    for line in stream:
        if not line.startswith("#"):
            first = line
            break
        header.append(line[1:].removeprefix(" "))
    else:
        raise ValueError("Missing original SSSOM table")
    metadata = yaml.safe_load("".join(header))
    reader = csv.DictReader(io.StringIO(first + stream.read()), delimiter="\t", strict=True)
    fields = list(reader.fieldnames or [])
    if len(fields) != len(set(fields)) or not {
        "subject_id",
        "object_id",
        "predicate_id",
        "subject_label",
    }.issubset(fields):
        raise ValueError("Invalid original SSSOM columns")
    rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("Malformed original SSSOM row")
    return metadata, fields, rows


def reviewed_products(review: dict, sources: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    """
    Reconstruct artifacts from complete, independently owned reviewed claims.

    The original mapping review format supplies each base disposition; companion
    decisions use the same verifier and additionally bind the explicit owner path.
    A consumer trusts a pinned bundle/review revision, never a self-issued checksum.
    """
    if type(review.get("schema_version")) is not int or review["schema_version"] != BUNDLE_VERSION:
        raise ValueError("Unsupported companion review version")
    declared: dict[str, str] = {}
    for group in ("inputs", "record_inputs"):
        if not isinstance(review.get(group), dict):
            raise ValueError(f"Missing companion review {group}")
        for name, expected in review[group].items():
            if name in declared and declared[name] != expected:
                raise ValueError("Conflicting companion input hashes")
            declared[name] = expected
    for name_key, hash_key in (
        ("claims_file", "claims_sha256"),
        ("base_review", "base_review_sha256"),
    ):
        name, expected = review[name_key], review[hash_key]
        if name in declared and declared[name] != expected:
            raise ValueError("Conflicting companion control-file hash")
        declared[name] = expected
    if set(sources) != set(declared):
        raise ValueError("Bundle sources must exactly cover declared review inputs")
    for name, expected in declared.items():
        if content_sha256(sources[name]) != expected:
            raise ValueError(f"Stale companion review input: {name}")
    claims_document = read_json(sources[review["claims_file"]])
    if set(claims_document) != {"schema_version", "claims"} or claims_document["schema_version"] != BUNDLE_VERSION:
        raise ValueError("Unsupported companion claims document")
    claims = claims_document["claims"]
    if not isinstance(claims, list) or not claims:
        raise ValueError("Missing companion claims")
    base = read_json(sources[review["base_review"]])
    if base.get("schema_version") != 1 or content_sha256(sources[base["source_sssom"]]) != base["source_sha256"]:
        raise ValueError("Stale original mapping review/source")
    metadata, fields, original_rows = _base_table(sources[base["source_sssom"]])
    extensions = [item["slot_name"] for item in scope_profile()["extension_definitions"]]
    if set(fields) & set(extensions):
        raise ValueError("Base source must precede scope extensions")
    metadata = profile_metadata(metadata)
    metadata["curie_map"]["sha256"] = "urn:sha256:"
    decisions = review.get("decisions", [])
    indexed = {decision.get("claim_id"): decision for decision in decisions}
    if len(indexed) != len(decisions) or len(decisions) != len(claims):
        raise ValueError("Companion review must uniquely and completely cover claims")
    proofs: dict = {}
    owners: dict[str, str] = {}
    seen: set[str] = set()
    mappings: list[dict] = []
    annotations: list[dict] = []
    products: list[dict] = []
    occurrences: list[dict] = []
    verified = {name: sources[name] for name in review["inputs"]}
    documents = {"urn:sha256:" + content_sha256(content) for content in verified.values()}
    base_decisions = {}
    for decision in base["decisions"]:
        position = decision.get("source_position")
        if type(position) is not int or not 1 <= position <= len(original_rows) or position in base_decisions:
            raise ValueError("Invalid original review position")
        base_decisions[position] = decision
    original_index = {content_sha256(canonical_json(row)): i for i, row in enumerate(original_rows, 1)}
    for claim in claims:
        if set(claim) != {"claim_id", "kind", "owner_record", "payload"}:
            raise ValueError("Unsupported companion claim envelope")
        claim_id, kind, owner, payload = (claim[key] for key in ("claim_id", "kind", "owner_record", "payload"))
        if claim_id in seen or claim_id not in indexed or owner not in review["record_inputs"]:
            raise ValueError("Duplicate, unreviewed or unowned companion claim")
        seen.add(claim_id)
        owner_id = _owner_id(owner)
        record = yaml.safe_load(sources[owner])
        if not isinstance(record, dict) or record.get("mapping_status") != "MAPPED":
            raise ValueError("Claim owner is not a mapped ingredient record")
        owners[owner_id] = owner
        decision = indexed[claim_id]
        validate_review_decision(
            decision,
            claim,
            owner,
            review["record_inputs"][owner],
            verified,
            proofs,
            require_owner_path=True,
        )
        if kind == "mapping":
            if claim_id != stable_id("mapping", [payload[key] for key in ("subject_id", "predicate_id", "object_id")]):
                raise ValueError("Mapping claim ID differs from its scoped endpoints")
            if (
                set(payload) != set(fields + extensions)
                or payload["subject_id"] != owner_id
                or payload["subject_label"] != record.get("preferred_term")
            ):
                raise ValueError("Scoped mapping does not describe its independent source owner")
            original = {key: payload[key] for key in fields}
            position = original_index.get(content_sha256(canonical_json(original)))
            base_decision = base_decisions.get(position) if position is not None else None
            if not base_decision or base_decision["disposition"] != "SUPPORTED":
                raise ValueError("Scoped mapping must retain an existing supported complete source row")
            evidence = base_decision["review_evidence"]
            if evidence not in base["inputs"] or content_sha256(sources[evidence]) != base["inputs"][evidence]:
                raise ValueError("Original mapping review evidence is missing or changed")
            if base["record_inputs"].get(owner) != review["record_inputs"][owner]:
                raise ValueError("Scoped mapping owner changed since base review")
            validate_review_decision(base_decision, original, owner, review["record_inputs"][owner], verified, proofs)
            if decision["disposition"] != "SUPPORTED" or payload["ext_scope_review_status"] != "SUPPORTED":
                raise ValueError("Exported scoped mapping requires supported scope review")
            validate_scope_row(payload, metadata)
            evidence_id = payload["ext_scope_evidence"].replace("sha256:", "urn:sha256:", 1)
            if evidence_id not in documents:
                raise ValueError("Scope evidence document is not bundled")
            mappings.append(payload)
        else:
            validate_payload(kind, payload)
            owner_field = "owner_id" if kind == "identifier" else "ingredient_id"
            if payload[owner_field] != owner_id and not (
                kind == "identifier" and payload[owner_field].startswith("MIM.product:")
            ):
                raise ValueError("Companion payload belongs to another ingredient")
            identity_field = {
                "identifier": "annotation_id",
                "product": "product_id",
                "occurrence": "occurrence_id",
            }[kind]
            if claim_id != payload[identity_field]:
                raise ValueError("Companion claim ID differs from its payload identity")
            if payload["review_status"] != decision["disposition"]:
                raise ValueError("Companion claim status disagrees with reviewed disposition")
            if any(item["document_id"] not in documents for item in payload["evidence"]):
                raise ValueError("Companion evidence document is not bundled")
            target = {"identifier": annotations, "product": products, "occurrence": occurrences}[kind]
            target.append(payload)
    if set(review["record_inputs"]) != set(owners.values()):
        raise ValueError("Companion record inputs include unrelated owners")
    identities: dict[str, str] = {}
    scoped_owners: dict[str, str] = {}
    for row in mappings:
        subject = row["subject_id"]
        scope = row["ext_subject_scope"].removeprefix("mimscope:")
        if subject in scoped_owners and scoped_owners[subject] != scope:
            raise ValueError("Conflicting scopes require distinct source concepts")
        scoped_owners[subject] = scope
        if validate_scope_row(row, metadata):
            if subject in identities and identities[subject] != row["object_id"]:
                raise ValueError("Competing authorized identities require source-context resolution")
            identities[subject] = row["object_id"]
    product_map = {row["product_id"]: row for row in products}
    if len(product_map) != len(products) or len({r["occurrence_id"] for r in occurrences}) != len(occurrences):
        raise ValueError("Duplicate product or occurrence identity")
    if len({r["annotation_id"] for r in annotations}) != len(annotations):
        raise ValueError("Duplicate registry claim identity")
    for payload in products + occurrences:
        if payload["ingredient_id"] not in scoped_owners:
            raise ValueError("Product/occurrence ingredient lacks a reviewed scoped mapping")
    for claim in claims:
        payload = claim["payload"]
        if claim["kind"] == "identifier":
            identifier_owner = payload["owner_id"]
            if identifier_owner.startswith("MIM.product:"):
                if identifier_owner not in product_map or product_map[identifier_owner]["ingredient_id"] != _owner_id(
                    claim["owner_record"]
                ):
                    raise ValueError("Registry product claim has the wrong ingredient owner")
            elif identifier_owner not in scoped_owners:
                raise ValueError("Registry owner lacks a reviewed scoped mapping")
            if (
                identifier_owner in product_map
                and payload["xref_eligible"]
                and product_map[identifier_owner]["review_status"] != "SUPPORTED"
            ):
                raise ValueError("Active registry xref refers to a withheld product")
            # Specific identifier claims may be retained on a broader owner as
            # evidence, but cannot become active xrefs of that owner.
            expected_scope = scoped_owners.get(identifier_owner)
            if (
                payload["xref_eligible"]
                and expected_scope is not None
                and payload["identifier_scope"] != expected_scope
            ):
                raise ValueError("Active registry annotation scope differs from its owner")
    for occurrence in occurrences:
        references = [occurrence["product_id"]] if occurrence["product_id"] else []
        references += [member["product_id"] for group in occurrence["alternatives"] for member in group["members"]]
        for product in references:
            if product not in product_map or product_map[product]["ingredient_id"] != occurrence["ingredient_id"]:
                raise ValueError("Occurrence refers to a missing or differently owned product")
            if occurrence["review_status"] == "SUPPORTED" and product_map[product]["review_status"] != "SUPPORTED":
                raise ValueError("Supported occurrence refers to a withheld product")
    mappings.sort(key=lambda r: (r["subject_id"], r["predicate_id"], r["object_id"]))
    products.sort(key=lambda r: r["product_id"])
    occurrences.sort(key=lambda r: r["occurrence_id"])
    artifacts = {
        ARTIFACTS["mappings"]: write_profile_table(metadata, fields + extensions, mappings),
        ARTIFACTS["identifiers"]: annotation_table(annotations),
    }
    if products:
        artifacts[ARTIFACTS["products"]] = canonical_json(products) + b"\n"
    if occurrences:
        artifacts[ARTIFACTS["occurrences"]] = canonical_json(occurrences) + b"\n"
    return artifacts, {
        "metadata": metadata,
        "mappings": mappings,
        "identifiers": annotations,
        "products": products,
        "occurrences": occurrences,
        "identities": identities,
        "owners": owners,
    }


def validate_bundle(root: Path, *, expected_manifest_sha256: str | None = None, capabilities=CAPABILITIES) -> dict:
    """Replay reviews and every projection before any consumer builds its indexes."""
    manifest_bytes = (root / "manifest.json").read_bytes()
    fingerprint = content_sha256(manifest_bytes)
    if expected_manifest_sha256 is not None and fingerprint != expected_manifest_sha256:
        raise ValueError("Ingredient bundle manifest does not match its activation pin")
    manifest = read_json(manifest_bytes)
    contents = validate_member_hashes(root, manifest, capabilities)
    if manifest.get("review") != "review.json" or manifest.get("source_root") != "sources":
        raise ValueError("Unsupported bundle review layout")
    sources = {name.removeprefix("sources/"): value for name, value in contents.items() if name.startswith("sources/")}
    expected, loaded = reviewed_products(read_json(contents["review.json"]), sources)
    review = read_json(contents["review.json"])
    provenance = manifest.get("provenance", {})
    if (
        manifest.get("cohort") != sorted(loaded["owners"])
        or manifest.get("coverage") != "reviewed_scoped_cohort"
        or manifest.get("legacy_compatibility") != "separate_explicit_input_only"
        or provenance.get("review_sha256") != content_sha256(contents["review.json"])
        or provenance.get("base_review_sha256") != review["base_review_sha256"]
    ):
        raise ValueError("Bundle provenance or cohort differs from reviewed inputs")
    declared = {key: name if name in expected else None for key, name in ARTIFACTS.items()}
    if manifest.get("artifacts") != declared:
        raise ValueError("Missing or mismatched explicit bundle artifacts")
    required = set(REQUIRED_CAPABILITIES)
    for key, capability in (
        ("products", "catalog-products-v1"),
        ("occurrences", "ingredient-occurrences-v1"),
    ):
        if declared[key]:
            required.add(capability)
    if set(manifest["required_capabilities"]) != required:
        raise ValueError("Artifact capabilities disagree with bundle requirements")
    for name, value in expected.items():
        if contents.get(name) != value:
            raise ValueError(f"Bundle artifact differs from reviewed reconstruction: {name}")
    allowed = {
        "review.json",
        PROFILE_NAME,
        SCHEMA_NAME,
        *expected,
        *("sources/" + name for name in sources),
    }
    if set(contents) != allowed:
        raise ValueError("Bundle includes unexpected artifacts")
    # Exercise the transport reader, including required-profile enforcement.
    read_profile_table(contents[ARTIFACTS["mappings"]])
    read_annotation_table(contents[ARTIFACTS["identifiers"]])
    loaded.update(manifest=manifest, fingerprint=fingerprint)
    return loaded
