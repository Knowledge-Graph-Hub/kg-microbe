"""Consume a pinned reviewed ingredient cohort without deriving identity from xrefs."""

from __future__ import annotations

import re
import shutil
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.ingredient_bundle_contract import (
    canonical_json,
    content_sha256,
    read_json,
    safe_member,
    validate_bundle,
    validate_member_hashes,
)
from kg_microbe.utils.ingredient_identity import ingredient_cas_annotations


class ReviewedIngredientBundle:
    """Hold one immutable, verified snapshot with explicit source-context lookup."""

    def __init__(self, directory: Path, *, manifest_sha256: str):
        """Validate the complete producer bundle against an independently selected pin."""
        if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256):
            raise ValueError("Reviewed ingredient bundle requires an explicit SHA-256 manifest pin")
        self.directory = Path(directory).resolve()
        self.fingerprint = manifest_sha256
        self._loaded = validate_bundle(self.directory, expected_manifest_sha256=manifest_sha256)
        self._manifest = self._loaded["manifest"]
        self._identities = dict(self._loaded["identities"])
        self._mappings = {row["subject_id"]: row for row in self._loaded["mappings"]}
        self._products = {row["product_id"]: row for row in self._loaded["products"]}
        self._occurrences = {row["occurrence_id"]: row for row in self._loaded["occurrences"]}
        self._covered = set(self._mappings) | set(self._identities.values()) | set(self._products)
        self._claims = defaultdict(list)
        self._xrefs = defaultdict(set)
        self._annotation_owners = defaultdict(set)
        self._history_owners = defaultdict(set)
        for claim in self._loaded["identifiers"]:
            owner = self.canonical_owner(claim["owner_id"])
            self._claims[owner].append(claim)
            if claim["identifier"]:
                self._history_owners[claim["identifier"]].add(owner)
            if claim["xref_eligible"]:
                self._xrefs[owner].add(claim["identifier"])
                self._annotation_owners[claim["identifier"]].add(owner)
        self._snapshots = {
            "manifest.json": manifest_sha256,
            **{name: expected["sha256"] for name, expected in self._manifest["members"].items()},
        }
        self.verify_current()

    def canonical_owner(self, owner_id: str) -> str:
        """Replace only explicitly authorized scoped source concepts; products stay distinct."""
        return self._identities.get(owner_id, owner_id)

    def resolve_source(self, source_id: str, *, occurrence_id: str | None = None) -> str | None:
        """
        Resolve a source concept or verified occurrence before any label preference.

        Native generic trait identifiers are not inferred to be MIM ingredients.
        Unknown source IDs return None; mismatched occurrence ownership is an error.
        """
        if occurrence_id is not None:
            occurrence = self._occurrences.get(occurrence_id)
            if occurrence is None or occurrence["ingredient_id"] != source_id:
                raise ValueError("Ingredient source and occurrence context do not agree")
            if occurrence["review_status"] != "SUPPORTED":
                return None
        if source_id not in self._mappings:
            return None
        return self.canonical_owner(source_id)

    def active_xrefs(self, owner_id: str) -> list[str]:
        """Return reviewed current references for this owner, never equivalence candidates."""
        return sorted(self._xrefs.get(self.canonical_owner(owner_id), ()))

    def identifier_owners(self, identifier: str, *, include_history: bool = False) -> list[str]:
        """Query all annotation owners without selecting a synonym-clique representative."""
        index = self._history_owners if include_history else self._annotation_owners
        return sorted(index.get(identifier, ()))

    def identifier_claims(self, owner_id: str | None = None) -> list[dict]:
        """Return intact source/status/evidence tuples; original owners are never rewritten."""
        claims = (
            self._loaded["identifiers"] if owner_id is None else self._claims.get(self.canonical_owner(owner_id), [])
        )
        return deepcopy(sorted(claims, key=lambda claim: claim["annotation_id"]))

    def mappings(self) -> list[dict]:
        """Return every scoped mapping, including reviewed nonidentity relations."""
        return deepcopy(self._loaded["mappings"])

    def occurrences(self) -> list[dict]:
        """Return structured source occurrences with their unselected alternative groups."""
        return deepcopy(self._loaded["occurrences"])

    def products(self) -> list[dict]:
        """Return product specifications without attaching their qualifiers to generic ingredients."""
        return deepcopy(self._loaded["products"])

    def enrich_node(self, owner_id: str, existing: dict[str, str]) -> dict[str, str]:
        """
        Use this cohort's reviewed CAS set on covered nodes and preserve other fields.

        An omitted legacy CAS is outside this selected bundle's active evidence,
        not a global rejection of its use by another independent source. Product
        catalog values, preparations and historical claims never become synonyms.
        """
        result = dict(existing)
        if owner_id not in self._covered:
            return result
        xrefs = {value for value in result.get("xref", "").split("|") if value and not value.lower().startswith("cas:")}
        xrefs.update(self.active_xrefs(owner_id))
        result["xref"] = "|".join(sorted(xrefs))
        return result

    def policy_parity(self) -> dict:
        """Compare the existing case-specific CAS annotations before any policy migration."""
        compared, differences = [], []
        for target in sorted(set(self._identities.values())):
            legacy = ingredient_cas_annotations(target)
            current = self.active_xrefs(target)
            compared.append(target)
            if legacy != current:
                differences.append({"owner_id": target, "legacy": legacy, "bundle": current})
        return {
            "compared_owners": compared,
            "differences": differences,
            "status": "PASS" if not differences else "REVIEW_REQUIRED",
        }

    def audit(self) -> dict:
        """Account for every input claim without silently consuming deferred products/history."""
        identifiers = self._loaded["identifiers"]
        return {
            "manifest_sha256": self.fingerprint,
            "mapping_rows": len(self._loaded["mappings"]),
            "authorized_source_identities": len(self._identities),
            "nonidentity_mapping_rows": sum(
                row["ext_identity_authorized"] != "true" for row in self._loaded["mappings"]
            ),
            "identifier_claims": len(identifiers),
            "active_identifier_claims": sum(claim["xref_eligible"] for claim in identifiers),
            "identifier_currentness": dict(Counter(claim["source_currentness"] for claim in identifiers)),
            "identifier_review_status": dict(Counter(claim["review_status"] for claim in identifiers)),
            "retained_product_records": len(self._products),
            "retained_occurrence_records": len(self._occurrences),
            "shared_active_identifiers": {
                identifier: sorted(owners) for identifier, owners in self._annotation_owners.items() if len(owners) > 1
            },
            "unsupported_claims": 0,
            "policy_parity": self.policy_parity(),
        }

    def annotation_document(self) -> dict:
        """Project owners alongside intact claims and resolvable bundled evidence references."""
        documents = {
            "urn:sha256:" + expected["sha256"]: name
            for name, expected in self._manifest["members"].items()
            if name.startswith("sources/")
        }
        return {
            "schema_version": 1,
            "ingredient_bundle_manifest_sha256": self.fingerprint,
            "evidence_members": documents,
            "claims": [
                {"canonical_owner_id": self.canonical_owner(claim["owner_id"]), "claim": claim}
                for claim in self.identifier_claims()
            ],
        }

    def write_annotations(self, path: Path) -> dict:
        """Write a deterministic graph-associated annotation artifact with its source pin."""
        self.verify_current()
        content = canonical_json(self.annotation_document()) + b"\n"
        with atomic_write(Path(path), mode="wb") as stream:
            stream.write(content)
            self.verify_current()
        return {
            "path": str(path),
            "sha256": content_sha256(content),
            "ingredient_bundle_manifest_sha256": self.fingerprint,
        }

    def verify_current(self) -> None:
        """Reject changed, deleted or undeclared bundle members before reusing a snapshot."""
        if content_sha256((self.directory / "manifest.json").read_bytes()) != self.fingerprint:
            raise ValueError("Ingredient bundle manifest changed after validation")
        validate_member_hashes(self.directory, self._manifest)

    def bind_to_transform(self, transform) -> None:
        """Register exactly the bytes already validated for this producer's finalization."""
        try:
            self.verify_current()
            pending = {}
            for name, expected in self._snapshots.items():
                key = "ingredient_bundle/" + name
                snapshot = {"path": str(safe_member(self.directory, name)), "sha256": expected}
                previous = transform._consumed_input_snapshots.get(key)
                if previous is not None and previous != snapshot:
                    raise ValueError("Ingredient bundle changed within one producer run")
                pending[key] = snapshot
            transform._consumed_input_snapshots.update(pending)
        except (OSError, ValueError) as error:
            transform._consumed_input_error = str(error)
            raise


def build_ingredient_lookup_bundle(consolidator, bundle: ReviewedIngredientBundle, output: Path) -> dict:
    """
    Publish explicit legacy and scoped inputs together without flattening their semantics.

    The existing consolidator handles its established native/legacy sources. The
    reviewed scoped cohort stays intact as a separate required input, resolved by
    source concept/occurrence before the legacy name index is consulted.
    """
    output = Path(output)
    if output.exists():
        raise ValueError("Ingredient lookup bundle output must be a new directory")
    bundle.verify_current()
    missing = sorted(set(bundle._identities.values()) - set(consolidator.chemicals))
    if missing:
        raise ValueError(f"Scoped ingredient targets are missing from the explicit legacy/native inputs: {missing}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".ingredient-lookup-", dir=output.parent))
    try:
        consolidator.export_unified_sssom(staging / "legacy.sssom.tsv.gz")
        shutil.copytree(bundle.directory, staging / "ingredient_bundle")
        copied = ReviewedIngredientBundle(staging / "ingredient_bundle", manifest_sha256=bundle.fingerprint)
        copied.write_annotations(staging / "ingredient_identifier_annotations.json")
        (staging / "audit.json").write_bytes(canonical_json(copied.audit()) + b"\n")
        members = {}
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                members[path.relative_to(staging).as_posix()] = content_sha256(path.read_bytes())
        manifest = {
            "schema_version": 1,
            "mode": "candidate_only",
            "legacy_mappings": "legacy.sssom.tsv.gz",
            "ingredient_bundle": "ingredient_bundle",
            "ingredient_bundle_manifest_sha256": bundle.fingerprint,
            "members": members,
        }
        (staging / "lookup_manifest.json").write_bytes(canonical_json(manifest) + b"\n")
        fingerprint = content_sha256((staging / "lookup_manifest.json").read_bytes())
        load_ingredient_lookup_bundle(staging, manifest_sha256=fingerprint)
        bundle.verify_current()
        if output.exists():
            raise ValueError("Ingredient lookup output appeared during export")
        staging.rename(output)
        return {"manifest_sha256": fingerprint, "ingredient_bundle_manifest_sha256": bundle.fingerprint}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_ingredient_lookup_bundle(directory: Path, *, manifest_sha256: str):
    """Verify both explicit lookup inputs and every companion artifact before index use."""
    directory = Path(directory).resolve()
    content = (directory / "lookup_manifest.json").read_bytes()
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256) or content_sha256(content) != manifest_sha256:
        raise ValueError("Ingredient lookup manifest does not match its selected pin")
    manifest = read_json(content)
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("mode") != "candidate_only"
        or manifest.get("legacy_mappings") != "legacy.sssom.tsv.gz"
        or manifest.get("ingredient_bundle") != "ingredient_bundle"
    ):
        raise ValueError("Unsupported ingredient lookup bundle layout or activation mode")
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
    if actual != {"lookup_manifest.json", *manifest["members"]}:
        raise ValueError("Ingredient lookup members are missing or undeclared")
    for name, expected in manifest["members"].items():
        if content_sha256(safe_member(directory, name).read_bytes()) != expected:
            raise ValueError(f"Ingredient lookup member changed: {name}")
    bundle = ReviewedIngredientBundle(
        directory / "ingredient_bundle", manifest_sha256=manifest["ingredient_bundle_manifest_sha256"]
    )
    expected_members = {
        "legacy.sssom.tsv.gz",
        "ingredient_identifier_annotations.json",
        "audit.json",
        *("ingredient_bundle/" + name for name in bundle._snapshots),
    }
    if set(manifest["members"]) != expected_members:
        raise ValueError("Ingredient lookup contains unsupported companion artifacts")
    if (directory / "ingredient_identifier_annotations.json").read_bytes() != canonical_json(
        bundle.annotation_document()
    ) + b"\n":
        raise ValueError("Lookup annotation artifact differs from reviewed claims")
    if (directory / "audit.json").read_bytes() != canonical_json(bundle.audit()) + b"\n":
        raise ValueError("Lookup audit differs from reviewed inputs")
    _verify_serialized_targets(directory / "legacy.sssom.tsv.gz", bundle)
    return directory / "legacy.sssom.tsv.gz", bundle, manifest["members"]["legacy.sssom.tsv.gz"]


def _verify_serialized_targets(path: Path, bundle: ReviewedIngredientBundle) -> None:
    """Stream actual usable declarations; metadata-only and nonidentity rows cannot create endpoints."""
    from kg_microbe.utils.chemical_mapping_utils import _iter_sssom_rows, _scope_metadata
    from kg_microbe.utils.sssom_identity_policy import classify_mapping_row

    required = set(bundle._identities.values())
    metadata = _scope_metadata(path)
    if metadata:
        raise ValueError("Legacy lookup member cannot substitute another profiled mapping set")
    present = set()
    nonidentity_pairs = set()
    for row in _iter_sssom_rows(path):
        route, _ = classify_mapping_row(row)
        if route == "broader" or (route == "nonidentity" and row["predicate_id"].strip() == "skos:relatedMatch"):
            nonidentity_pairs.add(tuple(sorted(row[key].strip() for key in ("subject_id", "object_id"))))
        target = row["object_id"].strip()
        if route in {"attribute", "identity", "canonical_name", "synonym"} and target in required:
            present.add(target)
    # Keep only nonidentity pairs in memory; a second streaming pass makes the
    # decision independent of row order without retaining every identity row.
    if nonidentity_pairs:
        for row in _iter_sssom_rows(path):
            if (
                classify_mapping_row(row)[0] == "identity"
                and tuple(sorted(row[key].strip() for key in ("subject_id", "object_id"))) in nonidentity_pairs
            ):
                raise ValueError(
                    f"Conflicting exact/nonidentity mappings require review: {row['subject_id']} / {row['object_id']}"
                )
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"Scoped ingredient targets are missing from serialized lookup inputs: {missing}")
