"""
Read-only native MIM validation child for the opt-in KG candidate adapter.

Run in the explicitly pinned maintained MIM interpreter. This file has no
third-party imports until the selected producer root has been installed on its
isolated import path. It never generates, saves, adopts or approves a record.
"""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import hashlib
import importlib.machinery
import io
import json
import sys
from pathlib import Path


def _require(value, message):
    if not value:
        raise ValueError("Stable native bridge: " + message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _table(path):
    # Only the leading metadata is outside the TSV stream. Quoted cells may
    # contain CRLF and continuation lines beginning with # (#1828).
    text = path.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    header = 0
    while header < len(lines) and lines[header].startswith("#"):
        header += 1
    return list(csv.DictReader(io.StringIO("".join(lines[header:]), newline=""), delimiter="\t"))


def _lineage(root, selection, policy, records, registry):
    """Carry a hold through verified migration, never through a shared external ID."""
    from mediaingredientmech import identity_projection as projection
    from mediaingredientmech.identity_projection_frozen import decode_frozen
    from mediaingredientmech.stable_ids import build_record_index, parse_registry

    legacy = policy["row"]["subject_id"]
    index = build_record_index(records)
    candidates = list(index.aliases.get(legacy, ()))
    # The exact historical record path is a hint requiring conservative review,
    # not authority to infer a stable ID after a rename or record replacement.
    if policy["decision"]["owner_record"] in records:
        candidates.append(policy["decision"]["owner_record"])
    candidates = sorted(set(candidates))
    result = {
        "policy": policy,
        "legacy_subject": legacy,
        "proof": None,
        "current_alias_candidates": candidates,
        "consumer_holds": [],
        "status": "NO_CURRENT_LEGACY_BINDING",
        "limitation": None,
    }
    lineage = selection["lineage"]
    if lineage is None:
        result["limitation"] = (
            "No native historical migration proof selected; absence of a legacy alias is not proof "
            "that a renamed predecessor is absent."
        )
        if candidates:
            result["status"] = "CONSUMER_LINEAGE_UNRESOLVED"
            result["consumer_holds"] = [
                {
                    "owner_id": records[path]["mim_id"],
                    "disposition": "CONSUMER_LINEAGE_UNRESOLVED",
                    "reason": (
                        "Current native owner retains the held legacy identifier or path; "
                        "historical lineage is not proved."
                    ),
                    "owner_record": path,
                    "legacy_subject": legacy,
                    "policy_row_sha256": policy["row_sha256"],
                }
                for path in candidates
            ]
        return result
    manifest_raw = (root / lineage["manifest"]["path"]).read_bytes()
    manifest = projection.document(manifest_raw)
    _require(manifest["source_commit"] == policy["source_commit"], "hold predecessor revision differs")
    names = projection.record_paths(root, historical=True)
    before = projection.git_files(root, [*names, projection.SOURCE])
    after, transition = decode_frozen(manifest_raw, before, (root / lineage["postimages"]["path"]).read_bytes())
    previous = parse_registry(after[projection.REGISTRY], after[projection.LIFECYCLE])
    _require(
        registry.entries[: len(previous.entries)] == previous.entries
        and registry.events[: len(previous.events)] == previous.events,
        "historical registry or lifecycle was rewritten",
    )
    _require(
        _sha(before[policy["decision"]["owner_record"]]) == policy["owner_sha256"], "held predecessor owner differs"
    )
    _require(policy["row"] in transition["old_rows"], "held predecessor full row absent")
    identifier = transition["aliases"][legacy]
    _require(identifier in registry.states, "held predecessor missing from current registry")
    lineage_ids = [identifier]
    while registry.states[identifier][0] != "active":
        identifier = registry.states[identifier][1]
        _require(identifier not in lineage_ids, "cyclic hold lineage")
        lineage_ids.append(identifier)
    path = index.stable_ids[identifier]
    result.update(
        status="DOWNSTREAM_HELD",
        proof={
            "kind": "native_complete_frozen_identity_migration",
            "manifest_sha256": _sha(manifest_raw),
            "predecessor_owner_sha256": policy["owner_sha256"],
            "stable_lineage": lineage_ids,
            "current_owner_record": path,
            "scientific_hold_release": False,
        },
    )
    result["consumer_holds"] = [
        {
            "owner_id": identifier,
            "disposition": "DOWNSTREAM_HELD",
            "reason": policy["reason"],
            "legacy_subject": legacy,
            "policy_row_sha256": policy["row_sha256"],
            "lineage": lineage_ids,
            "owner_record": path,
        }
    ]
    # The full independent old assertion remains in the policy; this overlay
    # does not relabel another owner merely because it shares CHEBI:86658.
    return result


def validate(request):
    """Replay native source, external and companion authorities on their actual inputs."""
    selection = request["selection"]
    producer = Path(selection["producer_root"])
    root = Path(selection["mim_root"])
    sys.path.insert(0, str(producer / "src"))

    # Fresh first-party imports compile the selected source, never a timestamp-
    # compatible stale pyc. Native source_bindings additionally uses its own
    # captured-module implementation and full producer/dependency verification.
    class SourceOnly(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return self.source_to_code(self.get_data(self.path), self.path)

    class NativeFinder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if fullname == "mediaingredientmech" or fullname.startswith("mediaingredientmech."):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path)
                if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
                    _require(
                        Path(spec.origin).is_relative_to(producer / "src"), "native import escaped selected producer"
                    )
                    spec.loader = SourceOnly(fullname, spec.origin)
                return spec
            return None

    sys.meta_path.insert(0, NativeFinder)
    from mediaingredientmech.export import reviewed_sssom as external
    from mediaingredientmech.export import source_bindings as native
    from mediaingredientmech.export import source_producer
    from mediaingredientmech.ingredient_bundle_contract import validate_bundle
    from mediaingredientmech.mapping_scope import _load_yaml
    from mediaingredientmech.stable_ids import MIM_PREFIX, parse_registry, validate_records

    _require(
        Path(native.__file__).absolute() == producer / "src/mediaingredientmech/export/source_bindings.py",
        "executing native source differs",
    )
    output = root / selection["source_output"]["path"]
    review_path = Path(selection["source_review"]["path"])
    # This native entry point performs complete reconstruction, source review
    # admission, all occurrences/owners, producer capture and strict SSSOM checks.
    claims = native.consumer_claims(root, review_path, output, capabilities={native.CAPABILITY})
    manifest = json.loads((output / "manifest.json").read_bytes())
    _require(
        manifest["production_authorized"] is False and manifest["semantic_status"] == "REVIEWED_CANDIDATE_ONLY",
        "native source is not a candidate",
    )
    _require(
        manifest["curie_map"] == {"MIM": MIM_PREFIX, "MIM.ingredient": MIM_PREFIX}, "stable namespace contract differs"
    )
    source_review = json.loads((root / review_path).read_bytes())
    mode = selection["companion_mode"]
    _require(mode in {"required/v1", "absent/v1"}, "explicit companion mode required")
    companion = companion_review = None
    if mode == "absent/v1":
        _require(
            selection["companion_output"] is None and selection["companion_review"] is None,
            "absence cannot replace a supplied companion",
        )
    else:
        companion_root = root / selection["companion_output"]["path"]
        companion = validate_bundle(
            companion_root, expected_manifest_sha256=selection["companion_output"]["manifest_sha256"]
        )
        for field, name in (
            ("exporter_sha256", "export/ingredient_bundle.py"),
            ("validator_sha256", "ingredient_bundle_contract.py"),
            ("sssom_metadata_sha256", "sssom_metadata.py"),
        ):
            _require(
                companion["manifest"]["provenance"][field]
                == _sha((producer / "src/mediaingredientmech" / name).read_bytes()),
                "companion producer provenance differs",
            )
        companion_review = json.loads((root / selection["companion_review"]["path"]).read_bytes())
        _require(
            (companion_root / "review.json").read_bytes()
            == (root / selection["companion_review"]["path"]).read_bytes(),
            "selected companion review differs",
        )
        _require(
            companion_review["base_review"] == source_review["external_review"]["path"]
            and companion_review["base_review_sha256"] == source_review["external_review"]["sha256"],
            "companion and source external authorities differ",
        )
        # Source validation already replays this exact external authority. Companion
        # archive replay additionally checks every scoped annotation and occurrence.
        for name, declaration in companion["manifest"]["members"].items():
            if name.startswith("sources/"):
                current = (root / name[len("sources/") :]).read_bytes()
                _require(
                    _sha(current) == declaration["sha256"] and current == (companion_root / name).read_bytes(),
                    "companion archived input is not current",
                )
    records = {name: _load_yaml((root / name).read_text()) for name in source_review["record_inputs"]}
    registry = parse_registry((root / native.REGISTRY_PATH).read_bytes(), (root / native.LIFECYCLE_PATH).read_bytes())
    validate_records(registry, records)
    lineage = _lineage(root, selection, request["hold_policy"], records, registry)
    rows = _table(output / "external-ingredient_mappings.sssom.tsv")
    withheld = _table(output / "external-withheld_mappings.sssom.tsv")
    holds = lineage["consumer_holds"]
    held_owners = {hold["owner_id"] for hold in holds}
    payload = {
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "selection_sha256": request["selection_sha256"],
        "profile_sha256": request["profile_sha256"],
        "production_authorized": False,
        "manifest_sha256": selection["source_output"]["manifest_sha256"],
        "runtime": source_producer.runtime(),
        "curie_map": manifest["curie_map"],
        "claims": claims,
        "source_decisions": json.loads((output / "source-decisions.json").read_bytes()),
        "external_supported": rows,
        "external_withheld": withheld,
        "external_dispositions": _table(output / "external-mapping-dispositions.tsv"),
        "companion_mode": mode,
        "companion": (
            {key: companion[key] for key in ("mappings", "identifiers", "products", "occurrences")}
            if companion is not None
            else None
        ),
        "owners": {
            record["mim_id"]: {
                "path": name,
                "sha256": source_review["record_inputs"][name],
                "record": {
                    key: record.get(key)
                    for key in ("mim_id", "identifier", "preferred_term", "mapping_status", "legacy_identifiers")
                },
                "record_yaml_utf8": (root / name).read_bytes().decode("utf-8"),
            }
            for name, record in records.items()
        },
        "registry": [dataclasses.asdict(value) for value in registry.entries],
        "lifecycle": [dataclasses.asdict(value) for value in registry.events],
        "lineage": lineage,
        "consumer_holds": holds,
        "consumer_admission": {
            "held_owners": sorted(held_owners),
            "held_external_supported_rows": sum(row["subject_id"] in held_owners for row in rows),
            "native_source_status_unchanged": True,
        },
        "provenance": {
            "source_manifest": manifest,
            "source_producer": json.loads((output / "producer.json").read_bytes()),
            "source_review": source_review,
            "companion_manifest": companion["manifest"] if companion is not None else None,
            "companion_review": companion_review,
            "external_review_sha256": source_review["external_review"]["sha256"],
            "native_external_row_hashes": [external.row_sha256(row) for row in [*rows, *withheld]],
        },
    }
    for claim in claims:
        _require(
            native.expand_mim(claim["original_object_id"]) == native.expand_mim(claim["object_id"]),
            "namespace expansion changed identity",
        )
    return payload


def main():
    """Keep genuine diagnostics on stderr and one complete result on stdout."""
    request = json.loads(sys.stdin.buffer.read())
    with contextlib.redirect_stdout(sys.stderr):
        result = validate(request)
    # ASCII transport preserves native-admitted Unicode without locale coupling.
    sys.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
