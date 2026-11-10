"""
Construct explicitly synthetic products using the selected real MIM producers.

Adapted from MediaIngredientMech's native test_source_bindings.Fixture and the
native-product-counting-helper-v2 recipe. See stable_mim_native_fixture/README.md
for provenance and the upstream BSD-3-Clause notice. This is test code only.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

GIT = shutil.which("git")

VARIANTS = (
    "baseline",
    "narrow",
    "legacy-held",
    "held",
    "empty",
    "all-withheld",
    "rename",
    "terminal-invalid",
    "multiline",
    "multiline-withheld",
)


def sha(path):
    """Bind actual file bytes rather than a success flag or mutable branch name."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *arguments):
    """Read the selected repository through fixed, shell-free Git queries."""
    if GIT is None:
        raise ValueError("Git is required by the real native fixture")
    return (
        subprocess.run(  # noqa: S603 - fixed Git executable and internal argv; no shell
            [GIT, *arguments], cwd=root, check=True, capture_output=True
        )
        .stdout.decode()
        .strip()
    )


def write_json(path, value):
    """Write an explicit synthetic test input with human-readable provenance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _selected_code(root, expected_head, fixture_sha256, python, python_sha256):
    """Require the supplied native source revision and maintained interpreter before construction."""
    if sys.version_info[:2] != (3, 13):
        raise ValueError("Native MIM fixture requires the maintained Python 3.13 runtime")
    executable = Path(sys.executable).resolve()
    if executable != python.resolve() or sha(executable) != python_sha256:
        raise ValueError("Native fixture interpreter differs from its explicit pin")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Expected an exact full native code commit")
    if root != root.resolve() or git(root, "rev-parse", "HEAD") != expected_head:
        raise ValueError("Selected native MIM root or revision differs from its pin")
    fixture = root / "tests/test_source_bindings.py"
    if sha(fixture) != fixture_sha256:
        raise ValueError("Native source fixture differs from its explicit pin")
    sys.path.insert(0, str(root / "src"))
    from mediaingredientmech.export import source_bindings

    if Path(source_bindings.__file__).resolve() != root / "src/mediaingredientmech/export/source_bindings.py":
        raise ValueError("Imported native producer differs from the selected code root")
    names = {
        "tests/test_source_bindings.py",
        source_bindings.HELPER,
        source_bindings.SCHEMA,
        *source_bindings.PRODUCER_PATHS,
        *source_bindings.PRODUCER_AUXILIARY,
        "src/mediaingredientmech/export/ingredient_bundle.py",
        "src/mediaingredientmech/ingredient_bundle_contract.py",
        "src/mediaingredientmech/profiles/ingredient_bundle_v1.schema.json",
        "src/mediaingredientmech/profiles/ingredient_scope_v1.yaml",
    }
    snapshots = {}
    for name in sorted(names):
        raw = (root / name).read_bytes()
        committed = subprocess.run(  # noqa: S603 - exact selected commit and fixed native file list
            [GIT, "show", expected_head + ":" + name], cwd=root, capture_output=True, check=True
        ).stdout
        if raw != committed:
            raise ValueError("Selected native input differs from its committed bytes: " + name)
        snapshots[name] = hashlib.sha256(raw).hexdigest()
    spec = importlib.util.spec_from_file_location("kg_native_mim_source_fixture", fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, snapshots, {"executable": str(executable), "sha256": python_sha256, "version": sys.version}


def _refresh_external(fixture, rows, owner_paths, external, binding, *, disposition="SUPPORTED"):
    """Create explicit synthetic external decisions independently of source identity reviews."""
    import yaml

    root = fixture.root
    metadata, fields, _ = external.read_sssom(root / binding.EXTERNAL_SOURCE)
    (root / binding.EXTERNAL_SOURCE).write_bytes(
        "".join("# " + line + "\n" for line in yaml.safe_dump(metadata).splitlines()).encode()
        + external._tsv(fields, rows)
    )
    entries, decisions, owners = {}, [], {}
    for position, (row, owner) in enumerate(zip(rows, owner_paths, strict=True), 1):
        owners[owner] = external.digest(root / owner)
        decision = {
            "source_position": position,
            "owner_record": owner,
            "row_sha256": external.row_sha256(row),
            "disposition": disposition,
            "review_reason": (
                "Synthetic negative external evidence: supplied-form correspondence remains unresolved; "
                "withhold this external mapping independently of source identity"
                if disposition == "WITHHOLD"
                else "Explicit synthetic external judgment; independent of source identity"
            ),
            "review_evidence": "external-evidence.json",
            "evidence_key": str(position),
        }
        decisions.append(decision)
        entries[str(position)] = {key: decision[key] for key in ("row_sha256", "disposition", "review_reason")}
        entries[str(position)]["owner_record_sha256"] = owners[owner]
    write_json(root / "external-evidence.json", {"entries": entries})
    write_json(
        root / "external-review.json",
        {
            "schema_version": 1,
            "source_sssom": binding.EXTERNAL_SOURCE,
            "source_sha256": external.digest(root / binding.EXTERNAL_SOURCE),
            "inputs": {"external-evidence.json": external.digest(root / "external-evidence.json")},
            "record_inputs": owners,
            "decisions": decisions,
        },
    )
    fixture.review["external_review"]["sha256"] = external.digest(root / "external-review.json")


def _variant(fixture, variant, external, binding):
    """Apply only explicit synthetic fixture changes before fresh native scientific reports."""
    import yaml

    root = fixture.root
    withheld = set()
    if variant == "held":
        fixture.review["cases"][0]["holds"] = ["Synthetic conflicting preparation identities remain unresolved"]
        fixture.review["cases"][3]["owner_record"] = None
        withheld = {1, 4}
    elif variant == "rename":
        old = list(fixture.records)[3]
        new = "data/ingredients/unmapped/Renamed_material.yaml"
        record = copy.deepcopy(fixture.records.pop(old))
        record["preferred_term"] = "Renamed material"
        record["legacy_identifiers"].append("MIM:Another_old_name")
        (root / old).unlink()
        (root / new).write_text(yaml.safe_dump(record), encoding="utf-8")
        fixture.records[new] = record
        fixture.review["record_inputs"].pop(old)
        fixture.review["record_inputs"][new] = external.digest(root / new)
        fixture.review["cases"][3]["owner_record"] = new
    elif variant == "empty":
        _refresh_external(fixture, [], [], external, binding)
    elif variant in {"all-withheld", "multiline", "multiline-withheld"}:
        _, _, rows = external.read_sssom(root / binding.EXTERNAL_SOURCE)
        review = json.loads((root / "external-review.json").read_bytes())
        owner_paths = [decision["owner_record"] for decision in review["decisions"]]
        if variant.startswith("multiline"):
            rows[0]["comment"] = "Synthetic first line\r\n# literal quoted annotation line\r\nSynthetic last line"
        disposition = "SUPPORTED" if variant == "multiline" else "WITHHOLD"
        _refresh_external(fixture, rows, owner_paths, external, binding, disposition=disposition)
    elif variant in {"narrow", "legacy-held"}:
        if variant == "legacy-held":
            # Synthetic unresolved predecessor lineage, never a real P3556 claim.
            owner = list(fixture.records)[0]
            fixture.records[owner]["legacy_identifiers"].append("MIM:L-alpha-Phosphatidylcholine")
            (root / owner).write_text(yaml.safe_dump(fixture.records[owner]), encoding="utf-8")
            fixture.review["record_inputs"][owner] = external.digest(root / owner)
        nodes, occurrences = root / "nodes.tsv", root / "occurrences.tsv"
        nodes.write_text(nodes.read_text() + "SOURCE:5\traw shared\tanhydrous\n", encoding="utf-8")
        occurrences.write_text(occurrences.read_text() + "SOURCE:5\tF\t1 g\n", encoding="utf-8")
        fixture.review["source"].update(
            nodes_sha256=external.digest(nodes), occurrences_sha256=external.digest(occurrences)
        )
        fixture.review["cases"].append(
            {
                "source_position": 5,
                "owner_record": list(fixture.records)[4],
                "holds": [],
                "primary": None,
                "skeptic": None,
            }
        )
        _, _, rows = external.read_sssom(root / binding.EXTERNAL_SOURCE)
        review = json.loads((root / "external-review.json").read_bytes())
        owner_paths = [decision["owner_record"] for decision in review["decisions"]]
        for owner, predicate, target in (
            (list(fixture.records)[1], "skos:narrowMatch", "CHEBI:4"),
            (list(fixture.records)[4], "skos:exactMatch", "CHEBI:1"),
        ):
            record = fixture.records[owner]
            row = dict(
                rows[0],
                subject_id=record["mim_id"],
                subject_label=record["preferred_term"],
                predicate_id=predicate,
                object_id=target,
                comment="Explicit independent synthetic external assertion; no subclass inference",
            )
            rows.append(row)
            owner_paths.append(owner)
        _refresh_external(fixture, rows, owner_paths, external, binding)
    elif variant == "terminal-invalid":
        ledger = root / binding.LIFECYCLE_PATH
        ledger.write_text(
            ledger.read_text() + "MIM:0000004\tretired\tMIM:0000001\t2026-11-10T00:00:00Z\t"
            "Explicit synthetic negative; terminal owner remains current\n",
            encoding="utf-8",
        )
        fixture.review["ledger_inputs"][str(binding.LIFECYCLE_PATH)] = external.digest(ledger)
    fixture.seal(withheld=withheld)


def _companion(fixture, variant, external, binding):
    """Build the genuine native scope recipe only for explicit required-companion variants."""
    from mediaingredientmech.ingredient_bundle_contract import stable_id

    if variant in {"empty", "all-withheld", "multiline-withheld"}:
        raise ValueError("Explicit absent-companion fixtures must not construct companion claims")

    root = fixture.root
    base = json.loads((root / "external-review.json").read_bytes())
    evidence = root / "scope-evidence.txt"
    evidence.write_text(
        "Explicit synthetic companion judgment only; no campaign scientific approval.\n", encoding="utf-8"
    )
    payload = external.read_sssom(root / binding.EXTERNAL_SOURCE)[2][0].copy()
    payload.update(
        ext_subject_scope="mimscope:defined_substance",
        ext_object_scope="mimscope:defined_substance",
        ext_subject_composition="mimscope:single_component",
        ext_object_composition="mimscope:single_component",
        ext_scope_profile="mimprofile:ingredient-scope/v1",
        ext_scope_review_status="SUPPORTED",
        ext_identity_authorized="true",
        ext_scope_evidence="sha256:" + external.digest(evidence),
    )
    owner = base["decisions"][0]["owner_record"]
    claim = {
        "claim_id": stable_id("mapping", [payload[key] for key in ("subject_id", "predicate_id", "object_id")]),
        "kind": "mapping",
        "owner_record": owner,
        "payload": payload,
    }
    disposition = "SUPPORTED"
    owner_sha = external.digest(root / owner)
    decision = {
        "claim_id": claim["claim_id"],
        "row_sha256": external.row_sha256(claim),
        "owner_record": owner,
        "disposition": disposition,
        "review_reason": "Explicit synthetic companion judgment; independent of source review",
        "review_evidence": "scope-proof.json",
        "evidence_key": "1",
    }
    proof = {key: decision[key] for key in ("row_sha256", "owner_record", "disposition", "review_reason")}
    proof["owner_record_sha256"] = owner_sha
    write_json(root / "scope-proof.json", {"entries": {"1": proof}})
    write_json(root / "claims.json", {"schema_version": 1, "claims": [claim]})
    write_json(
        root / "companion-review.json",
        {
            "schema_version": 1,
            "base_review": "external-review.json",
            "base_review_sha256": external.digest(root / "external-review.json"),
            "claims_file": "claims.json",
            "claims_sha256": external.digest(root / "claims.json"),
            "record_inputs": {owner: owner_sha},
            "decisions": [decision],
            "inputs": {
                str(name): external.digest(root / name)
                for name in (
                    binding.EXTERNAL_SOURCE,
                    "external-evidence.json",
                    "scope-proof.json",
                    "scope-evidence.txt",
                )
            },
        },
    )


def construct(*, mim_root, mim_head, fixture_sha256, python, python_sha256, output, variant):
    """Create fresh real native products for one fully disclosed synthetic scenario."""
    mim_root, output = mim_root.absolute(), output.absolute()
    if variant not in VARIANTS or output.exists() or output.is_symlink():
        raise ValueError("Select a supported variant and a fresh output directory")
    if output != output.resolve() or output.is_relative_to(mim_root):
        raise ValueError("Fixture output must be isolated outside the selected MIM code root")
    module, snapshots, runtime = _selected_code(mim_root, mim_head, fixture_sha256, python, python_sha256)
    from mediaingredientmech.export import reviewed_sssom as external
    from mediaingredientmech.export import source_bindings as binding
    from mediaingredientmech.export.ingredient_bundle import export_bundle

    output.mkdir()
    fixture = module.Fixture(output)
    provenance = {
        "synthetic": True,
        "scientific_scope": "Explicit test judgments only; no campaign science or publication authorization",
        "variant": variant,
        "mim_code_root": str(mim_root),
        "mim_code_head": mim_head,
        "selected_source_sha256": snapshots,
        "runtime": runtime,
        "fixture_root": str(output),
        "fixture_git_head": git(output, "rev-parse", "HEAD"),
        "fixture_git_revision_is_synthetic": True,
    }
    try:
        _variant(fixture, variant, external, binding)
    except ValueError as error:
        if variant != "terminal-invalid" or "unknown or retired MIM ID" not in str(error):
            raise
        result = {
            **provenance,
            "status": "EXPECTED_NATIVE_REFUSAL",
            "refusal": {"type": type(error).__name__, "message": str(error)},
        }
    else:
        if variant == "terminal-invalid":
            raise ValueError("Terminal record negative unexpectedly passed native admission")
        absent_companion = variant in {"empty", "all-withheld", "multiline-withheld"}
        companion_result = None
        companion_pin = None
        if absent_companion:
            if any((output / name).exists() for name in ("companion-review.json", "companion-output", "claims.json")):
                raise ValueError("Explicit absent companion cannot hide supplied companion inputs")
        else:
            _companion(fixture, variant, external, binding)
        external_result = external.export_reviewed(output, Path("external-review.json"), output / "external-output")
        if not absent_companion:
            companion_result = export_bundle(output, Path("companion-review.json"), output / "companion-output")
            companion_pin = external.digest(output / "companion-output/manifest.json")
        source_result = binding.export_candidate(output, Path("source-review.json"), output / "candidate")
        result = {
            **provenance,
            "status": "SYNTHETIC_NATIVE_PRODUCTS_COMPLETE",
            "source_review": "source-review.json",
            "source_output": "candidate",
            "source_pin": external.digest(output / "candidate/manifest.json"),
            "source_manifest": source_result,
            "external_review": "external-review.json",
            "external_output": "external-output",
            "external_pin": external.digest(output / "external-output/manifest.json"),
            "external_manifest": external_result,
            "companion_mode": "absent/v1" if absent_companion else "required/v1",
            "companion_review": None if absent_companion else "companion-review.json",
            "companion_output": None if absent_companion else "companion-output",
            "companion_pin": companion_pin,
            "companion_result": companion_result,
        }
    if git(mim_root, "rev-parse", "HEAD") != mim_head or any(
        sha(mim_root / name) != expected for name, expected in snapshots.items()
    ):
        raise ValueError("Selected native source changed during fixture construction")
    if Path(sys.executable).resolve() != python.resolve() or sha(python.resolve()) != python_sha256:
        raise ValueError("Native runtime changed during fixture construction")
    write_json(output / "FIXTURE-RESULT.json", result)
    return result


def main():
    """Use the explicitly selected native Python runtime and preserve diagnostics on stderr."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mim-root", type=Path, required=True)
    parser.add_argument("--mim-head", required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        result = construct(**vars(args))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
