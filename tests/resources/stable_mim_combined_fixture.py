"""
Build a tiny genuine native combined candidate using explicitly pinned MIM code.

All scientific records and decisions are synthetic controls. The actual archived
CM producer, historical prepare/finalize, source assembler, paired native reviews
and export/reconstruction run without an active campaign or a release assertion.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_MIM = "68bba8a68c79049e7602e4b10a12b1baf700d840"
CAPABILITIES = {
    "reviewed-source-bindings-v1",
    "culturemech-intake-v3-replay-v1",
    "cm-v3-kgm-source-conservation-v1",
}
FIXTURES = {
    "tests/__init__.py",
    "tests/test_source_bindings.py",
    "tests/test_source_assembly.py",
    "tests/test_source_input_writer.py",
    "tests/test_combined_source_conservation.py",
    "tests/culturemech_replay_fixture.py",
    "scripts/record_review.py",
    "scripts/assemble_source_inputs.py",
    "schema/record_review.yaml",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
}


def require(condition, message):
    """Reject unsafe or mismatched fixture selection even under optimized Python."""
    if not condition:
        raise ValueError("Combined native fixture: " + message)


def digest(raw):
    """Hash exact selected bytes."""
    return hashlib.sha256(raw).hexdigest()


def pin(raw):
    """Return the native size/hash declaration without path substitution."""
    return {"sha256": digest(raw), "bytes": len(raw)}


def encoded(value):
    """Write deterministic JSON with literal types and finite numbers preserved."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def write_json(path, value):
    """Write only newly constructed fixture metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def git(root, *arguments):
    """Use fixed argv and a clean Git environment inside the owned fixture."""
    command = shutil.which("git")
    require(command is not None, "Git is required")
    return subprocess.run(  # noqa: S603 - fixed Git executable and owned fixture arguments
        [command, "-C", str(root), *arguments],
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
        check=True,
        capture_output=True,
    ).stdout


def selected_code(args):
    """Authenticate the exact upstream package, fixture code and interpreter before import."""
    root, executable = args.mim_root.absolute(), args.python.absolute()
    require(root == root.resolve(), "producer root is aliased")
    require(args.mim_head == EXPECTED_MIM, "unsupported fixture producer revision")
    require(git(root, "rev-parse", "HEAD").decode().strip() == args.mim_head, "producer HEAD differs")
    require(sys.version_info[:2] == (3, 13), "maintained native Python 3.13 required")
    require(Path(sys.executable).resolve() == executable.resolve(), "interpreter path differs")
    require(digest(executable.resolve().read_bytes()) == args.python_sha256, "interpreter bytes differ")
    require(digest(Path(__file__).read_bytes()) == args.helper_sha256, "constructor bytes differ")
    require(
        digest((root / "tests/test_source_bindings.py").read_bytes()) == args.fixture_sha256,
        "upstream fixture bytes differ",
    )
    tracked = git(root, "ls-tree", "-r", "--name-only", args.mim_head).decode().splitlines()
    names = {
        name
        for name in tracked
        if name in FIXTURES
        or name.startswith("src/mediaingredientmech/")
        or name.startswith("tests/fixtures/native_cm_v3_replay/")
    }
    require(FIXTURES - {"tests/__init__.py"} <= names, "fixture dependency missing")
    snapshots = {}
    for name in sorted(names):
        path = root / name
        require(not any(part.is_symlink() for part in (path, *path.parents)), "aliased producer input")
        raw = path.read_bytes()
        require(raw == git(root, "show", args.mim_head + ":" + name), "uncommitted producer input: " + name)
        snapshots[name] = pin(raw)
    sys.path[:0] = [str(root), str(root / "src")]
    modules = {
        name: importlib.import_module(name)
        for name in (
            "mediaingredientmech.export.source_bindings",
            "mediaingredientmech.export.source_assembly",
            "mediaingredientmech.export.source_conservation",
            "mediaingredientmech.export.source_input_selection",
            "tests.test_source_bindings",
            "tests.test_combined_source_conservation",
            "tests.test_source_assembly",
            "tests.culturemech_replay_fixture",
        )
    }
    for name, module in modules.items():
        prefix = root / ("src" if name.startswith("mediaingredientmech.") else "")
        require(Path(module.__file__).resolve() == prefix / (name.replace(".", "/") + ".py"), "module origin differs")
    return root, modules, snapshots


def current_water(current, binding, external):
    """Add one explicit permanent water owner without altering existing synthetic owners."""
    import yaml

    owner = "data/ingredients/mapped/Water.yaml"
    record = {
        "mim_id": "MIM:0000006",
        "identifier": "CHEBI:15377",
        "preferred_term": "water",
        "mapping_status": "MAPPED",
        "legacy_identifiers": ["MIM:Water"],
        "synonyms": [],
    }
    current.records[owner] = record
    (current.root / owner).write_text(yaml.safe_dump(record))
    with (current.root / binding.REGISTRY_PATH).open("a") as stream:
        stream.write("MIM:0000006\tWater\t2026-01-01\tactive\t\n")
    current.make_external()
    current.review["record_inputs"] = {path: external.digest(current.root / path) for path in current.records}
    current.review["ledger_inputs"] = {
        str(path): external.digest(current.root / path) for path in (binding.REGISTRY_PATH, binding.LIFECYCLE_PATH)
    }
    current.review["external_review"]["sha256"] = external.digest(current.root / "external-review.json")
    return owner


def synthetic_kg(current, captures, scope, packet, raw_table, rows):
    """Construct tiny literal graph witnesses and a committed prior-pin fixture."""
    refs = scope["authorities"]
    owner = json.loads(captures[refs["kg_source_selection"]["path"]])
    receipt = json.loads(captures[refs["kg_source_manifest"]["path"]])
    proof = json.loads(captures[refs["kg_row_reconciliation"]["path"]])
    receipt_base = Path(refs["kg_source_manifest"]["path"]).parent
    kg_root = current.root / "kg-source-origin"
    kg_root.mkdir()
    source_raw = b"# Synthetic historical source only\nsubject_id\tpredicate_id\tobject_id\n"
    review_raw = encoded({"status": "SYNTHETIC_ONLY", "scientific_approval": False})
    prior_products = {
        "ingredient_mappings.sssom.tsv": source_raw,
        "withheld_mappings.sssom.tsv": source_raw,
        "mapping-dispositions.tsv": b"source_position\tdisposition\n",
    }
    manifest = {
        "schema_version": 1,
        "semantic_status": "PASS_SUPPORTED_SUBSET",
        "source_sssom": "mappings/ingredient_mappings.sssom.tsv",
        "source_sha256": digest(source_raw),
        "review_sha256": digest(review_raw),
        "files": {name: digest(value) for name, value in prior_products.items()},
    }
    prior_products["manifest.json"] = encoded(manifest)
    prior_revision = git(current.root, "rev-parse", "HEAD").decode().strip()
    consumed = {
        "source_commit": prior_revision,
        "directory": "prior",
        "files": {name: digest(value) for name, value in prior_products.items()},
        "manifest_sha256": digest(prior_products["manifest.json"]),
    }
    release_record = encoded(
        {
            "schema_version": 2,
            "origin": "immutable_commit_export",
            "source_commit": prior_revision,
            "source_archive": {
                "url": "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + prior_revision,
                "sha256": digest(b"Synthetic archive identity; never downloaded or published"),
            },
            "export_recipe": "synthetic-source-conservation-fixture",
            "validation_run_url": "https://example.invalid/synthetic-native-validation",
            "manifest_sha256": consumed["manifest_sha256"],
            "files": manifest["files"],
            "mode": "candidate_only",
        }
    )
    for name, value in prior_products.items():
        member = "prior/" + name
        captures[(receipt_base / member).as_posix()] = value
        receipt["files"][member] = pin(value)
    member = "snapshots/mappings/mim_reviewed_release.json"
    captures[(receipt_base / member).as_posix()] = release_record
    receipt["files"][member] = pin(release_record)
    for member in receipt["files"]:
        if member.startswith("snapshots/"):
            destination = kg_root / member.removeprefix("snapshots/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(captures[(receipt_base / member).as_posix()])
    for args in (
        ("init",),
        ("config", "user.name", "Synthetic native fixture"),
        ("config", "user.email", "fixture@example.invalid"),
        ("add", "mappings/mim_reviewed_release.json"),
        ("commit", "-m", "Synthetic committed prior input; no real release"),
    ):
        git(kg_root, *args)
    revision = git(kg_root, "rev-parse", "HEAD").decode().strip()
    receipt.update(upstream_revision=revision, mim_revision=prior_revision, consumed_reviewed=consumed)
    owner["selected_kgm"] = {"root": str(kg_root), "revision": revision}
    owner["consumed_prior_mim"] = {
        "source_commit": prior_revision,
        "partition_pins": consumed,
        "committed_pin_record": {
            "path": str(kg_root / "mappings/mim_reviewed_release.json"),
            **pin(release_record),
        },
    }
    node_rows = rows(captures[refs["kg_nodes"]["path"]])
    node_ledger = json.loads(captures[refs["kg_full_node_ledger"]["path"]])
    for row, entry in zip(node_rows, node_ledger, strict=True):
        witnesses = json.loads(row["current_graph_node_rows_json"])
        for witness in witnesses:
            relative = witness["input"]["path"].split("/data/transformed/", 1)[1]
            witness["input"]["path"] = str(kg_root / "data/transformed" / relative)
        row["current_graph_node_rows_json"] = json.dumps(witnesses, sort_keys=True, separators=(",", ":"))
        entry["node"] = copy.deepcopy(row)
        entry["combined_row"] = {**row, "historical_only": "retained old positions, not new CM offsets"}
    captures[refs["kg_nodes"]["path"]] = raw_table(list(node_rows[0]), node_rows)
    captures[refs["kg_full_node_ledger"]["path"]] = encoded(node_ledger)
    transport = json.loads(captures[refs["kg_transport_manifest"]["path"]])
    transport["files"]["source-nodes.tsv"] = digest(captures[refs["kg_nodes"]["path"]])
    captures[refs["kg_transport_manifest"]["path"]] = encoded(transport)
    proof["kgm_revision"] = revision
    proof["kg_manifest_sha256"] = digest(captures[refs["kg_transport_manifest"]["path"]])
    for role, name in (
        ("kg_full_node_ledger", "full-node-ledger.json"),
        ("kg_full_row_ledger_json", "full-row-ledger.json"),
        ("kg_full_row_ledger_tsv", "full-row-ledger.tsv"),
    ):
        raw = captures[refs[role]["path"]]
        proof["outputs"][name].update(pin(raw))
        owner["ledgers"][name].update(pin(raw))
    captures[refs["kg_source_manifest"]["path"]] = encoded(receipt)
    captures[refs["kg_row_reconciliation"]["path"]] = encoded(proof)
    owner["source_receipt"].update(pin(captures[refs["kg_source_manifest"]["path"]]))
    owner["row_reconciliation"].update(pin(captures[refs["kg_row_reconciliation"]["path"]]))
    owner["kg_transport_manifest_sha256"] = digest(captures[refs["kg_transport_manifest"]["path"]])
    package_index = json.loads((packet["package"] / "package.json").read_bytes())
    package_root = packet["package"]
    proof_paths = {
        "source_manifest": "consumer/" + package_index["intake_path"] + "/source/bundle/manifest.json",
        "prepared_intake": "consumer/" + package_index["intake_path"] + "/intake.json",
        "reviewed_intake": "consumer/" + package_index["reviewed_path"] + "/reviewed-intake.json",
        "binding_review": "consumer/" + package_index["review_path"],
    }
    owner["intended_accepted_cm_v3"] = {
        "transport_package": {
            "path": str(package_root / "package.json"),
            **pin((package_root / "package.json").read_bytes()),
        },
        "selected": {
            role: {"path": str(package_root / path), **pin((package_root / path).read_bytes())}
            for role, path in proof_paths.items()
        },
        "expected_counts": {
            "positive_inventory": 2,
            "context_only": 1,
            "held": 1,
            "supported_bindings": 2,
            "withheld_bindings": 2,
        },
    }
    captures[refs["kg_source_selection"]["path"]] = encoded(owner)
    for ref in refs.values():
        ref["sha256"] = digest(captures[ref["path"]])
    return owner, proof_paths


def combined_inputs(current, package, modules):
    """Assemble new combined tables from genuine CM replay and a tiny preserved KG cohort."""
    binding = modules["mediaingredientmech.export.source_bindings"]
    assembly = modules["mediaingredientmech.export.source_assembly"]
    selector = modules["mediaingredientmech.export.source_input_selection"]
    upstream = modules["tests.test_combined_source_conservation"]
    tables = modules["tests.test_source_assembly"]
    initial, _, scope, _, _ = upstream.combined_fixture()
    captures, scope = copy.deepcopy(initial.bytes), copy.deepcopy(scope)
    # The pure upstream fixture's fake CM package is not a native replay proof.
    captures = {name: value for name, value in captures.items() if not name.startswith("cm/")}
    for path in package["package"].rglob("*"):
        if path.is_file():
            captures[path.relative_to(current.root).as_posix()] = path.read_bytes()
    scope["authorities"]["culturemech_package"] = copy.deepcopy(package["reference"])
    owner, proof_paths = synthetic_kg(current, captures, scope, package, tables.raw_table, tables.rows)
    refs = scope["authorities"]
    declaration_path = "output/projection-declaration.json"
    declaration = json.loads(captures[declaration_path])
    declaration["original_source_scope"] = copy.deepcopy(scope)
    declaration_raw = tables.canonical(declaration).encode()
    originals = {
        "cases": {item["case_id"]: item for item in json.loads(captures[refs["original_case_ledger"]["path"]])},
        "origins": {item["origin_id"]: item for item in json.loads(captures[refs["original_origin_ledger"]["path"]])},
    }
    crosswalk = {
        group: {
            key: {
                "original_sha256": binding.payload_sha256(payload),
                "targets": [],
                "evidence": ["primary-source.txt: synthetic historical obligation retained without inferred identity"],
                "unresolved_reason": "Synthetic original remains independently retained; no current identity inferred.",
            }
            for key, payload in values.items()
        }
        for group, values in originals.items()
    }
    prefixes = copy.deepcopy(current.review["source"]["curie_map"])
    prefixes.update(
        {
            "MIMCMREFv1": modules["mediaingredientmech.export.source_conservation"].CM_URI,
            "kgmicrobe.compound": "https://w3id.org/kg-microbe/compound/",
            "mediadive.ingredient": "https://mediadive.dsmz.de/ingredient/",
        }
    )
    data = selector.select_source_inputs(
        captures,
        selected_scope=scope,
        declaration=declaration_raw,
        declaration_path=declaration_path,
        reviewed_crosswalk=encoded(crosswalk),
        curie_map=encoded(prefixes),
    )
    arguments = {
        key: data[key]
        for key in ("cm", "kg", "family_paths", "curie_map", "historical_obligations", "reviewed_crosswalk")
    }
    candidate = assembly.combine_sources(assembly.project_culturemech(arguments["cm"]), **arguments)
    artifacts = {
        "cm_nodes": candidate["cm"]["nodes"],
        "cm_occurrences": candidate["cm"]["occurrences"],
        "cm_raw_row_map": encoded(candidate["cm"]["raw_row_map"]),
        "cm_case_crosswalk": encoded(candidate["cm"]["case_crosswalk"]),
        "combined_nodes": candidate["nodes"],
        "combined_occurrences": candidate["occurrences"],
        "combined_position_map": encoded(candidate["position_map"]),
        "cm_reconciliation": candidate["reconciliation"],
        "kg_provider_cases": encoded(candidate["kg_provider_cases"]),
        "historical_obligations": encoded(candidate["historical_obligations"]),
        "obligation_crosswalk": encoded(candidate["obligation_crosswalk"]),
    }
    captures.update({scope["artifacts"][role]: value for role, value in artifacts.items()})
    captures[declaration_path] = declaration_raw
    # Capture only actual selected originals, their closure, and generated artifacts.
    required = set(data["consumed_inputs"]) | set(scope["artifacts"].values()) | {declaration_path}
    # Native replay consumes only its execution inputs. Final KGM conservation
    # additionally selects every immutable package member in both reports (#1894).
    package_reference = refs["culturemech_package"]["path"]
    package_index = json.loads(captures[package_reference])
    required.update((Path(package_reference).parent / member).as_posix() for member in package_index["files"])
    receipt = json.loads(captures[refs["kg_source_manifest"]["path"]])
    required.update(
        (Path(refs["kg_source_manifest"]["path"]).parent / member).as_posix() for member in receipt["files"]
    )
    for name in sorted(required):
        destination = current.root / name
        raw = captures[name]
        if destination.exists():
            require(destination.read_bytes() == raw, "fixture would overwrite selected input: " + name)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
    current.review["inputs"] = {name: digest(captures[name]) for name in sorted(required)}
    current.review["culturemech_intake_replay"] = copy.deepcopy(package["reference"])
    current.review["source"] = {
        "nodes": scope["artifacts"]["combined_nodes"],
        "nodes_sha256": digest(candidate["nodes"]),
        "occurrences": scope["artifacts"]["combined_occurrences"],
        "occurrences_sha256": digest(candidate["occurrences"]),
        "id_column": "source_id",
        "label_column": "source_label",
        "occurrence_id_column": "source_id",
        "curie_map": prefixes,
    }
    return scope, declaration_path, owner, proof_paths, candidate, data


def reviewed_transitions(current, package, inspection, withheld, proof_paths, binding, rows):
    """Bind literal historical rows to current payloads in a synthetic review input."""
    historical = {
        item["case_id"]: item
        for name in ("supported-bindings.tsv", "withheld-bindings.tsv")
        for item in rows((package["reviewed"] / name).read_bytes())
    }
    decisions = {
        item["case_id"]: item
        for item in json.loads((package["package"] / proof_paths["binding_review"]).read_bytes())["decisions"]
    }
    evidence_path = "transition-source.txt"
    (current.root / evidence_path).write_text(
        "Synthetic captured identity control; no real material or scientific release claim.\n"
        "Historical Water and current Water both denote water/CHEBI:15377. Current Water acquires "
        "permanent ID MIM:0000006; old and new byte identities remain independently retained.\n"
        "The historical REMOVE context and identity-form-held ADD remain withheld. Their current "
        "source decisions have no identity owner and preserve original literals and holds.\n"
    )
    evidence = {"path": evidence_path, "sha256": digest((current.root / evidence_path).read_bytes())}
    entries = []
    for payload in inspection["payloads"]:
        case_id = payload["source_row"].get("original_case_id")
        if case_id not in historical:
            continue
        previous = historical[case_id]
        disposition = "WITHHOLD" if payload["source_position"] in withheld else "SUPPORTED"
        if all(
            previous[field] == (disposition if field == "disposition" else payload[field])
            for field in ("disposition", "owner_record", "owner_record_sha256")
        ):
            continue
        entries.append(
            {
                "case_id": case_id,
                "before": {
                    "binding_row_sha256": binding.payload_sha256(previous),
                    "binding_decision_sha256": binding.payload_sha256(decisions[case_id]),
                    **{key: previous[key] for key in ("disposition", "owner_record", "owner_record_sha256")},
                },
                "after": {
                    "source_id": payload["source_id"],
                    "source_position": payload["source_position"],
                    "payload_sha256": binding.payload_sha256(payload),
                    "disposition": disposition,
                    "owner_record": payload["owner_record"],
                    "owner_record_sha256": payload["owner_record_sha256"],
                },
                "evidence": [evidence],
            }
        )
    require(len(entries) == 4, "synthetic historical transition inventory differs")
    document = {
        "contract": "kg-microbe-cm-binding-transitions/v1",
        "culturemech": {
            role: {"path": "cm-package/" + path, "sha256": digest((package["package"] / path).read_bytes())}
            for role, path in proof_paths.items()
        },
        "native_source": {
            role: {"path": current.review["source"][role], "sha256": current.review["source"][role + "_sha256"]}
            for role in ("nodes", "occurrences")
        },
        "entries": entries,
    }
    name = "reviewed-owner-transitions.json"
    write_json(current.root / name, document)
    declaration = {"path": name, "sha256": digest((current.root / name).read_bytes())}
    for item in (declaration, evidence):
        current.review["inputs"][item["path"]] = item["sha256"]
    current.save()
    return declaration, evidence, {entry["after"]["source_position"]: entry for entry in entries}


def seal_combined(current, package, candidate, water_owner, modules, proof_paths, *, review_transitions=False):
    """Create genuine paired native reports retaining every combined request input."""
    import yaml

    binding = modules["mediaingredientmech.export.source_bindings"]
    conservation = modules["mediaingredientmech.export.source_conservation"]
    rows = modules["tests.test_source_assembly"].rows
    raw_cases = json.loads((package["prepared"] / "review-packet.json").read_bytes())["cases"]
    accepted = {item["case_id"]: item for item in raw_cases}
    native_rows = rows(candidate["nodes"])
    cases, withheld = [], set()
    for position, row in enumerate(native_rows, 1):
        raw = (
            accepted.get(row.get("original_case_id"))
            if row["source_id"].startswith(conservation.CM_PREFIX + ":")
            else None
        )
        supported = (
            raw is not None
            and raw["positive_occurrences"] > 0
            and raw["context"]["preferred_term"] == "water"
            and not set(raw["context"].get("held_fields", [])) & {"SOURCE_CLAIM", "IDENTITY_FORM"}
        )
        holds = [] if supported else ["Synthetic identity remains explicitly unresolved"]
        if raw is not None:
            holds.extend(field for field in raw["context"].get("held_fields", []) if field not in holds)
        cases.append(
            {
                "source_position": position,
                "owner_record": water_owner if supported else None,
                "holds": holds,
                "primary": None,
                "skeptic": None,
            }
        )
        if not supported:
            withheld.add(position)
    templates = copy.deepcopy(current.reports)
    current.review["cases"] = cases
    current.save()
    inspection = binding.inspect_candidates(current.root, current.review_path)
    transition_declaration, transition_evidence, transitions = None, None, {}
    if review_transitions:
        transition_declaration, transition_evidence, transitions = reviewed_transitions(
            current, package, inspection, withheld, proof_paths, binding, rows
        )
        refreshed = binding.inspect_candidates(current.root, current.review_path)
        require(refreshed["payloads"] == inspection["payloads"], "review input changed native payloads")
        inspection = refreshed
    reports = []
    for role, template in zip(("primary", "skeptic"), templates, strict=True):
        report = copy.deepcopy(template)
        targets = inspection["targets"]
        report["source"] = current.native.inspect_source(
            current.root, targets, [*inspection["inputs"], "primary-source.txt"]
        )["source"]
        report["targets"] = targets
        report["title"] = "Synthetic complete combined source identity contract"
        report["summary"] = "Synthetic combined qualification only; no production or scientific release acceptance"
        report["verdict"] = "needs_curation"
        report["scope"].update(
            description="Complete genuine synthetic CM replay and KG cohort",
            population_size=len(targets),
            reviewed_target_ids=[target["target_id"] for target in targets],
        )
        report["checks"][0]["target_ids"] = [target["target_id"] for target in targets]
        if review_transitions:
            for evidence_id, kind, declaration in (
                ("transition-ledger", "validation", transition_declaration),
                ("transition-source", "primary_source", transition_evidence),
            ):
                report["evidence"].append(
                    {
                        "evidence_id": evidence_id,
                        "kind": kind,
                        "reference": declaration["path"],
                        "snapshot_sha256": declaration["sha256"],
                        "accessed_at": "2026-01-01T00:00:00Z",
                        "support": "supports",
                        "summary": "Synthetic captured historical/current identity transition control",
                    }
                )
        original_assessment = copy.deepcopy(report["assessments"][0])
        report["assessments"] = []
        for position, target in enumerate(targets, 1):
            assessment = copy.deepcopy(original_assessment)
            held = position in withheld
            assessment.update(
                assessment_id="identity-" + str(position),
                target_ids=[target["target_id"]],
                outcome="unknown" if held else "supported",
                summary="Synthetic complete occurrence identity unresolved"
                if held
                else "Synthetic water material across complete captured occurrences",
            )
            for dimension in assessment["dimensions"]:
                if dimension["name"] == "source_identity_disposition":
                    dimension["value"] = "withhold" if held else "same_material"
            if position in transitions:
                ids = ["transition-ledger", "transition-source"]
                assessment["evidence_ids"].extend(ids)
                assessment["dimensions"].append(
                    {
                        "name": "cm_binding_transition_sha256",
                        "value": binding.payload_sha256(transitions[position]),
                        "definition": "Complete synthetic historical row/decision to current payload transition",
                        "evidence_ids": ids,
                    }
                )
            report["assessments"].append(assessment)
        relative = "reviews/structured/" + report["review_id"] + "/review.yaml"
        destination = current.root / relative
        destination.write_text(yaml.safe_dump(report, sort_keys=False))
        destination.with_name("review.md").write_text(current.native.render_markdown(report))
        for path in (destination, destination.with_name("review.md")):
            current.review["inputs"][path.relative_to(current.root).as_posix()] = digest(path.read_bytes())
        for position, case in enumerate(cases, 1):
            case[role] = {
                "path": relative,
                "target_id": "source-" + str(position),
                "assessment_id": "identity-" + str(position),
            }
        reports.append(report)
    current.reports = reports
    current.save()
    return transition_declaration


def build(args):
    """Construct one new fixture and let the actual native producer validate it."""
    producer, modules, snapshots = selected_code(args)
    output = args.output.absolute()
    require(not output.exists(), "output already exists")
    require(not any(path.is_symlink() for path in (output, *output.parents)), "aliased output path")
    require(not output.is_relative_to(producer), "fixture output cannot enter producer checkout")
    output.mkdir(parents=True)
    binding = modules["mediaingredientmech.export.source_bindings"]
    fixture = modules["tests.test_source_bindings"]
    replay_fixture = modules["tests.culturemech_replay_fixture"]
    current = fixture.Fixture(output)
    water_owner = current_water(current, binding, fixture.external)
    package = replay_fixture.make_package(current.root)
    scope, declaration_path, owner, proof_paths, candidate, selected = combined_inputs(current, package, modules)
    transitions = seal_combined(
        current, package, candidate, water_owner, modules, proof_paths, review_transitions=args.review_transitions
    )
    manifest = binding.export_candidate(current.root, current.review_path, current.output)
    require(set(manifest["required_capabilities"]) == CAPABILITIES, "genuine combined capability missing")
    require(
        binding.validate_candidate(current.root, current.review_path, current.output) == manifest,
        "native reload differs",
    )
    require(
        manifest["culturemech_intake_replay"]["counts"]
        == {"positive_inventory": 2, "context_only": 1, "held": 1, "supported_bindings": 2, "withheld_bindings": 2},
        "CM replay counts differ",
    )
    require(manifest["counts"]["supported"] == 2, "supported water source identities lost")
    require(manifest["production_authorized"] is False, "synthetic candidate gained production authority")
    require(git(producer, "rev-parse", "HEAD").decode().strip() == args.mim_head, "producer HEAD changed")
    for name, expected in snapshots.items():
        require(pin((producer / name).read_bytes()) == expected, "selected producer input changed: " + name)
    result = {
        "status": "SYNTHETIC_NATIVE_COMBINED_PRODUCTS_COMPLETE",
        "synthetic_only": True,
        "production_authorized": False,
        "final_artifact_acceptance": False,
        "producer_root": str(producer),
        "producer_revision": args.mim_head,
        "producer_inputs": snapshots,
        "constructor_sha256": args.helper_sha256,
        "runtime": {
            "path": str(args.python.absolute()),
            "realpath": str(args.python.resolve()),
            "sha256": args.python_sha256,
            "version": sys.version,
        },
        "root": str(output),
        "companion_mode": "absent/v1",
        "source_review": {"path": "source-review.json", **pin(current.review_path.read_bytes())},
        "source_output": {
            "path": "candidate",
            "manifest_sha256": digest((current.output / "manifest.json").read_bytes()),
        },
        "manifest": manifest,
        "combined_source_scope": scope,
        "combined_source_declaration": {
            "path": declaration_path,
            "sha256": digest((output / declaration_path).read_bytes()),
        },
        "current_kgm": owner["selected_kgm"],
        "kgm_source_receipt": scope["authorities"]["kg_source_manifest"],
        "culturemech": {
            role: {"path": "cm-package/" + path, "sha256": digest((package["package"] / path).read_bytes())}
            for role, path in proof_paths.items()
        },
        "expected_counts": owner["intended_accepted_cm_v3"]["expected_counts"],
        "culturemech_replay_proof": manifest["culturemech_intake_replay"],
        "kg_transport_manifest": scope["authorities"]["kg_transport_manifest"],
        "owner_transitions": transitions,
        "synthetic_transition_reviews_constructed": bool(transitions),
        "historical_owner_transitions_not_approved_by_fixture": True,
        "required_next": (
            "KGM admission/reload and explicitly reviewed synthetic transition reconciliation; "
            "no final-release authority"
        ),
    }
    write_json(output / "combined-fixture.json", result)
    return result


def main():
    """Parse fixed explicit source/runtime/output pins and run the bounded constructor."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mim-root", type=Path, required=True)
    parser.add_argument("--mim-head", required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-transitions", action="store_true")
    args = parser.parse_args()
    for value in (args.fixture_sha256, args.helper_sha256, args.python_sha256):
        require(re.fullmatch("[a-f0-9]{64}", value) is not None, "invalid byte pin")
    for key in list(os.environ):
        if key.startswith("GIT_") or key in {"LPSN_USERNAME", "LPSN_PASSWORD"}:
            os.environ.pop(key, None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    with contextlib.redirect_stdout(sys.stderr):
        result = build(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "root": result["root"],
                "receipt": str(Path(result["root"]) / "combined-fixture.json"),
                "production_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
