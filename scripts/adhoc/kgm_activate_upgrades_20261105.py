#!/usr/bin/env python3
"""Activate only the reviewed 2026-11-05 upgrade candidates; default is a read-only plan."""

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
from pathlib import Path

ROOT = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe-rebuild-20261105")
MODULE_ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
UPGRADES = ROOT / "data/rebuild-evidence/20261105/upgrades"
ACTIVATION = UPGRADES / "activation"
SOURCES = ("ncbitaxon", "chebi", "go", "ec", "upa", "metpo", "uberon", "foodon", "pato", "ro", "taxrank")
OUTPUTS = {name: ("ncbitaxon_removed_subset.json" if name == "ncbitaxon" else name + ".json") for name in SOURCES}
INPUTS = {name: name + (".owl.gz" if name in {"ncbitaxon", "chebi", "ec"} else ".owl") for name in SOURCES}
HTTP = {
    "biolink-model.yaml": (
        "biolink-model",
        "biolink446",
        "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/biolink-model.yaml",
    ),
    "predicate_mapping.yaml": (
        "biolink-predicates",
        "biolink446",
        "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/predicate_mapping.yaml",
    ),
    "attributes.yaml": (
        "biolink-attributes",
        "biolink446",
        "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/attributes.yaml",
    ),
    "robot.jar": ("robot-jar", "robot1911", "https://github.com/ontodev/robot/releases/download/v1.9.11/robot.jar"),
    "robot": ("robot-wrapper", "robot1911", "https://raw.githubusercontent.com/ontodev/robot/v1.9.11/bin/robot"),
}
POLICIES = (
    "finite_import_category_dispositions.json",
    "foodon_anatomical_category_dispositions.json",
    "foodon_kernel_quarantine.json",
    "native_ro_predicate_dispositions.json",
    "ontology_parent_dispositions.json",
    "uberon_temporal_category_dispositions.json",
)
LOADERS = (
    "finite_import_categories.py",
    "foodon_anatomical_categories.py",
    "foodon_kernel_quarantine.py",
    "native_ro_retention.py",
    "ontology_parent_quarantine.py",
    "uberon_temporal_categories.py",
)
EXCEPTION = UPGRADES / "robot-bindings/uberon-1737-disposition.json"


def require(condition, message):
    """Fail before mutation instead of inferring authorization from missing evidence."""
    if not condition:
        raise ValueError(message)


def identity(path):
    """Stream exact file bytes; reject links and shared inodes in the owned tree."""
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), f"Not a regular file: {path}")
    require(info.st_nlink == 1, f"Shared hard-linked file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    end = path.lstat()
    require(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        == (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns),
        f"File changed during read: {path}",
    )
    return {"sha256": digest.hexdigest(), "bytes": info.st_size}


def owned(path):
    """Require a literal descendant of this fixed worktree with no symlink ancestor."""
    path = Path(path).absolute()
    require(path.is_relative_to(ROOT) and ".." not in path.parts, f"Outside owned worktree: {path}")
    for current in (path, *path.parents):
        if not current.is_relative_to(ROOT):
            break
        require(not current.is_symlink(), f"Symlink in owned path: {current}")
    return path


def checked(path, expected=None):
    """Validate one exact finite identity without trusting paths carried by a receipt."""
    actual = identity(owned(path))
    if expected is not None:
        require(type(expected.get("bytes")) is int and expected["bytes"] > 0, f"Invalid expected size: {path}")
        require(actual == {key: expected[key] for key in ("sha256", "bytes")}, f"Identity mismatch: {path}")
    return actual


def unique_object(pairs):
    """Reject duplicate receipt fields."""
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate evidence key: {key}")
        result[key] = value
    return result


def read(path, guards):
    """Bind each parsed receipt/policy to the bytes rechecked immediately before mutation."""
    guards[str(path)] = checked(path)
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def bind(path, guards, expected=None):
    """Track a source or code identity in the activation guard set."""
    guards[str(path)] = checked(path, expected)
    return guards[str(path)]


def record_path(record, expected):
    """Require a receipt to describe only its explicitly selected path."""
    declared = record.get("path", record.get("source", record.get("candidate", record.get("output"))))
    require(declared == str(expected), f"Receipt path mismatch: {expected}")


def validate_layout():
    """Forbid arbitrary-root activation from the saved helper."""
    require(MODULE_ROOT == ROOT, "Activation helper is not in the fixed owned worktree")
    for path in (ROOT, RAW, UPGRADES):
        require(owned(path).is_dir(), f"Missing real directory: {path}")
    require(RAW.stat().st_dev == UPGRADES.stat().st_dev, "Preservation must use atomic moves on one filesystem")


def tree_identity(directory):
    """Inventory the complete old Rhea directory, including hidden files and traversal failures."""
    require(owned(directory).is_dir(), f"Missing Rhea directory: {directory}")
    files, directories = {}, []

    def fail(error):
        raise error

    for parent, names, filenames in os.walk(directory, followlinks=False, onerror=fail):
        for name in names:
            path = owned(Path(parent) / name)
            require(path.is_dir(), f"Non-directory Rhea entry: {path}")
            directories.append(str(path.relative_to(directory)))
        for name in filenames:
            path = Path(parent) / name
            files[str(path.relative_to(directory))] = checked(path)
    return {"files": files, "directories": sorted(directories)}


def check_http(name, guards, acquisition, details=None):
    """Require the recorded official request, successful transport, and exact acquired bytes."""
    label, folder, url = HTTP[name] if details is None else details
    candidate = UPGRADES / "candidates" / folder / name
    base = UPGRADES / "candidates/http" / label
    receipt = read(base / "receipt.json", guards)
    require(receipt == acquisition["downloads"][label], f"Acquisition receipts disagree: {name}")
    require(
        receipt["status"] == "downloaded" and receipt["curl_exit_code"] == 0 and receipt["http_code"] == 200,
        f"Failed HTTP acquisition: {name}",
    )
    require(receipt["source_url"] == url, f"Unexpected official source URL: {name}")
    record_path(receipt, candidate)
    bind(candidate, guards, receipt)
    headers = bind(base / "headers.txt", guards)
    require(headers["sha256"] == receipt["headers_sha256"], f"HTTP header receipt changed: {name}")
    metadata = read(base / "curl-metadata.json", guards)
    require(metadata.get("http_code") == 200 or metadata.get("response_code") == 200, f"HTTP metadata failed: {name}")
    require(metadata.get("url_effective") == receipt["actual_url"], f"HTTP effective URL changed: {name}")
    if name == "robot.jar":
        require(receipt.get("expected_sha256") == receipt["sha256"], "ROBOT official checksum differs")
    return candidate


def check_current_bindings(guards):
    """Require current finite-policy admission while retaining the exact known source omission."""
    base = UPGRADES / "robot-bindings"
    review_path = base / "review-5/binding-review.json"
    review = read(review_path, guards)
    admission = read(base / "current-policy-admission.json", guards)
    require(
        admission.get("version") == 1
        and admission.get("status") == "passed"
        and admission.get("current_policy_checks_passed") is True,
        "Current ROBOT policy admission is pending",
    )
    record_path(admission["review5"], review_path)
    bind(review_path, guards, admission["review5"])
    inputs_path = base / "review-5/inputs.json"
    record_path(admission["review5_inputs"], inputs_path)
    bind(inputs_path, guards, admission["review5_inputs"])
    require(set(admission["canonical_suppliers"]) == {"envo", "mondo"}, "Canonical supplier cohort changed")
    for name, record in admission["canonical_suppliers"].items():
        path = RAW / (name + ".json")
        record_path(record, path)
        bind(path, guards, record)
    expected = {"mappings/" + name for name in POLICIES} | {"kg_microbe/utils/" + name for name in LOADERS}
    expected |= {
        "scripts/adhoc/kgm_robot_binding_review_20261105.py",
        "scripts/adhoc/kgm_robot_annotation_review_20261105.py",
        "scripts/adhoc/kgm_robot_binding_acceptance_20261105.py",
    }
    require(expected <= set(admission["identities"]), "Current policy admission omits a finite policy or loader")
    for relative, expected_identity in admission["identities"].items():
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "Unsafe admission identity path")
        bind(ROOT / relative, guards, expected_identity)
    for name in ("foodon", "pato", "ro", "uberon"):
        records = admission["candidates"][name]
        for role, path in {
            "json": UPGRADES / "robot-conversions" / (name + ".json"),
            "source": RAW / (name + ".owl"),
            "receipt": UPGRADES / "robot-conversions/receipts" / (name + ".json"),
        }.items():
            # The source may name its identical conversion-side OWL copy.
            selected = (
                UPGRADES / "robot-conversions" / (name + ".owl")
                if role == "source"
                and records[role].get("path") == str(UPGRADES / "robot-conversions" / (name + ".owl"))
                else path
            )
            record_path(records[role], selected)
            bind(selected, guards, records[role])
            if role == "source":
                bind(path, guards, records[role])
    for key in (
        "all_added_annotation_values_source_backed",
        "removing_only_source_backed_additions_recovers_prepared_original",
    ):
        require(admission.get(key) is True, f"Current annotation proof incomplete: {key}")
    require(
        admission.get("complete_source_annotation_equality") is False,
        "Do not relabel the known source omission as complete equality",
    )
    exceptions = admission["source_completeness_exceptions"]
    reviewed = review["annotation_completeness_assessment"]["uberon"]["explicit_source_completeness_exceptions"]
    require(exceptions == reviewed and len(exceptions) == 1, "Source completeness exception changed")
    exception = exceptions[0]
    require(
        exception["node"] == "http://purl.obolibrary.org/obo/CL_0009080"
        and exception["annotated_property"] == "http://xmlns.com/foaf/0.1/depiction"
        and exception["annotated_target"] == "http://purl.obolibrary.org/obo/cl/images/Small-intestine-cells.png",
        "Unreviewed exception subject/property/target",
    )
    require(
        exception["source_annotations_newly_lost"] == []
        and exception["source_annotations_still_unserialized_in_candidate"]
        == [["http://www.geneontology.org/formats/oboInOwl#hasDbXref", "doi:10.1186/s13619-020-00061-5"]],
        "Unreviewed annotation loss",
    )
    record_path(admission["source_completeness_disposition"], EXCEPTION)
    bind(EXCEPTION, guards, admission["source_completeness_disposition"])
    from scripts.adhoc.kgm_robot_binding_acceptance_20261105 import validate_disposition

    disposition = read(EXCEPTION, guards)
    validate_disposition(
        disposition,
        exception,
        admission["review5"]["sha256"],
        admission["candidates"]["uberon"]["source"]["sha256"],
        admission["review5_inputs"]["sha256"],
    )
    return {
        "current_policy_admission": guards[str(base / "current-policy-admission.json")],
        "complete_source_annotation_equality": False,
        "source_exception": exception,
    }


def build_plan():
    """Read all authority chains, yielding exactly16 selected files and the separately staged Rhea pair."""
    validate_layout()
    guards, replacements = {}, []
    acquisition = read(UPGRADES / "candidates/receipt.json", guards)
    require(acquisition.get("status") == "acquired_not_activated", "Candidate acquisition is incomplete")
    candidates = {name: check_http(name, guards, acquisition) for name in HTTP}
    import yaml

    model = yaml.safe_load(candidates["biolink-model.yaml"].read_text())
    require(str(model.get("version")) == "4.4.6", "Candidate Biolink version is not4.4.6")
    from kg_microbe.utils import mesh_finite_categories, ncit_eight_categories

    for module, name in (
        (ncit_eight_categories, "ncit_eight_categories.json"),
        (mesh_finite_categories, "mesh_finite_category_dispositions.json"),
    ):
        policy = read(ROOT / "mappings" / name, guards)
        policy = module.load_policy(io.StringIO(json.dumps(policy)))
        module.validate_model(model, policy)
        bind(Path(module.__file__), guards)
        require(
            policy["model_version"] == "4.4.6"
            and policy["model_sha256"] == guards[str(candidates["biolink-model.yaml"])]["sha256"],
            f"Current model policy not ready: {name}",
        )
    canary = read(UPGRADES / "upa-canary/conversion.json", guards)
    require(
        canary["converter"] == "kg_microbe.utils.robot_utils.convert_to_json",
        "UPA was not converted through production path",
    )
    for name in ("robot", "robot.jar", "upa.owl"):
        source = RAW / name if name == "upa.owl" else candidates[name]
        record_path(canary["input_identities"][name], source)
        bind(source, guards, canary["input_identities"][name])
        bind(UPGRADES / "upa-canary" / name, guards, canary["input_identities"][name])
    version_path = UPGRADES / "upa-canary/robot-version.txt"
    bind(version_path, guards)
    require(version_path.read_text().splitlines()[0] == "ROBOT version 1.9.11", "Canary ROBOT version mismatch")
    batch = read(UPGRADES / "robot-conversions/receipt.json", guards)
    require(batch["converted_sources"] == list(SOURCES), "Conversion batch has missing/extra/reordered suppliers")
    for name, filename in OUTPUTS.items():
        receipt = read(UPGRADES / "robot-conversions/receipts" / (name + ".json"), guards)
        candidate = UPGRADES / "robot-conversions" / filename
        record_path(receipt, candidate)
        bind(candidate, guards, receipt)
        source = RAW / INPUTS[name]
        record_path(receipt["input"], source)
        bind(source, guards, receipt["input"])
        require(
            receipt["robot_sha256"] == guards[str(candidates["robot.jar"])]["sha256"]
            and receipt["robot_wrapper_sha256"] == guards[str(candidates["robot"])]["sha256"],
            f"Conversion toolchain differs: {name}",
        )
        candidates[filename] = candidate
    from kg_microbe.utils import upa_route_review as upa

    require(
        upa.POLICY_FILE == ROOT / "mappings/upa_reaction_projection_dispositions.json",
        "UPA policy import is outside the owned checkout",
    )
    policy = upa.load_policy(upa.POLICY_FILE.read_bytes())
    bind(upa.POLICY_FILE, guards)
    bind(Path(upa.__file__), guards)
    require(
        policy["sources"]["upa.json"]["sha256"]
        == guards[str(candidates["upa.json"])]["sha256"]
        == canary["candidate_json_sha256"],
        "Current UPA declaration binding differs from actual canary",
    )
    bind(
        UPGRADES / "upa-canary/upa.json",
        guards,
        {"sha256": canary["candidate_json_sha256"], "bytes": canary["candidate_json_bytes"]},
    )
    current = read(UPGRADES / "robot-rhea/current-reviewed-policy-check/result.json", guards)
    require(
        current["upa"]["passed"] is True and current["upa_semantic_policy_sha256"] == upa.digest(policy),
        "Actual current UPA finite-policy check differs",
    )
    binding_admission = check_current_bindings(guards)
    release = read(ROOT / "mappings/rhea_release.json", guards)
    legacy = read(ROOT / "mappings/rhea_legacy_xref_dispositions.json", guards)
    require(
        release["release_label"] == "143" and release["snapshot_id"] == "rhea-release-143-20261105",
        "Rhea current policy is not143",
    )
    require(
        legacy["selected_snapshot"] == {"snapshot_id": release["snapshot_id"], "rdf": release["files"]["rhea.rdf.gz"]}
        and legacy["expected_count"] == 6
        and len(legacy["preserved_directional_go_annotations"]) == 7,
        "Rhea current legacy policy differs",
    )
    archive = check_http(
        "143.tar.bz2", guards, acquisition, details=("rhea-archive", "rhea143", release["archive"]["url"])
    )
    extraction = read(UPGRADES / "candidates/rhea143/extraction.json", guards)
    require(extraction == acquisition["rhea_extraction"], "Rhea extraction receipts differ")
    require(
        extraction["archive"] == str(archive)
        and extraction["archive_sha256"] == guards[str(archive)]["sha256"]
        and extraction["archive_bytes"] == guards[str(archive)]["bytes"],
        "Rhea archive identity differs",
    )
    require(
        current["rhea"]["release_snapshot"] == release["snapshot_id"]
        and len(current["rhea"]["rows"]) == 6
        and len(current["rhea"]["directional_witnesses"]) == 7,
        "Actual current Rhea policy check differs",
    )
    for role, path in {
        "rhea_release_manifest": ROOT / "mappings/rhea_release.json",
        "rhea_legacy_xref_dispositions": ROOT / "mappings/rhea_legacy_xref_dispositions.json",
    }.items():
        require(
            current["rhea"]["consumed_inputs"][role]["sha256"] == guards[str(path)]["sha256"],
            "Actual Rhea check consumed another policy",
        )
    rhea = {}
    for name, expected in release["files"].items():
        candidate = UPGRADES / "candidates/rhea143" / name
        bind(candidate, guards, expected)
        record = extraction["members"][release["archive"]["members"][name]]
        record_path(record, candidate)
        require(
            {key: record[key] for key in ("sha256", "bytes")} == expected,
            "Rhea member is not the reviewed archive member",
        )
        rhea[name] = str(candidate)
    for filename, source in candidates.items():
        destination = RAW / filename
        old = checked(destination) if os.path.lexists(destination) else None
        replacements.append({"name": filename, "source": str(source), "candidate": guards[str(source)], "before": old})
    require(
        set(candidates) == set(HTTP) | set(OUTPUTS.values()) and len(replacements) == 16,
        "Activation file selection changed",
    )
    previous_rhea = tree_identity(RAW / "rhea")
    prior = read(ROOT / "tests/resources/rhea/reviewed_release_142/rhea_release.json", guards)
    for name, pin in prior["files"].items():
        require(previous_rhea["files"].get(name) == pin, "Current staged Rhea is not the preserved142 pair")
    for relative in (
        "kg_microbe/transform_utils/rhea_mappings/stage_snapshot.py",
        "kg_microbe/transform_utils/rhea_mappings/native_inputs.py",
        "kg_microbe/transform_utils/rhea_mappings/native_rdf.py",
        "kg_microbe/transform_utils/rhea_mappings/legacy_xrefs.py",
        "kg_microbe/transform_utils/transform.py",
        "scripts/adhoc/kgm_activate_upgrades_20261105.py",
        "scripts/adhoc/kgm_robot_rhea_review_20261105.py",
    ):
        bind(ROOT / relative, guards)
    return {
        "version": 1,
        "ready": True,
        "worktree": str(ROOT),
        "raw": str(RAW),
        "evidence": str(ACTIVATION),
        "replacements": replacements,
        "rhea_candidates": rhea,
        "rhea_before": previous_rhea,
        "rhea_policy": release,
        "guards": guards,
        "binding_admission": binding_admission,
        "production_admission": False,
        "database_receipts_rewritten": False,
    }


def write_json(path, value, *, replace=False):
    """Retain receipts atomically without accepting a pre-existing activation directory."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if not replace:
        require(not os.path.lexists(path), f"Receipt collision: {path}")
    os.replace(temporary, path)


def copy_verified(source, destination, expected):
    """Build one exclusive unpublished copy; never move or edit a candidate."""
    checked(source, expected)
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    os.chmod(destination, stat.S_IMODE(source.stat().st_mode))
    checked(destination, expected)


def recheck(plan):
    """Refuse guard, candidate, policy or original raw drift before the first atomic move."""
    validate_layout()
    for path, expected in plan["guards"].items():
        checked(Path(path), expected)
    for entry in plan["replacements"]:
        path = RAW / entry["name"]
        if entry["before"] is None:
            require(not os.path.lexists(path), f"Unexpected raw file appeared: {path}")
        else:
            checked(path, entry["before"])
    require(tree_identity(RAW / "rhea") == plan["rhea_before"], "Staged Rhea changed before activation")


def activate_rhea(generation, evidence):
    """Use production staging plus actual immutable native/legacy readers; never run a producer."""
    from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import INPUT_ROLE, load_legacy_xref_audit
    from kg_microbe.transform_utils.rhea_mappings.native_inputs import REQUIRED_INPUTS, load_pinned_inputs
    from kg_microbe.transform_utils.rhea_mappings.stage_snapshot import stage_snapshot
    from kg_microbe.transform_utils.transform import Transform
    from kg_microbe.utils.source_finalization import verify_consumed_inputs
    from scripts.adhoc.kgm_robot_rhea_review_20261105 import precheck_legacy

    staged = stage_snapshot(generation / "rhea-inputs", RAW, policy_path=ROOT / "mappings/rhea_release.json")

    class Reader(Transform):
        REQUIRED_CONSUMED_INPUTS = (*REQUIRED_INPUTS, INPUT_ROLE)

    reader = Reader("rhea_activation_audit", RAW, evidence / "rhea-reader")
    release, _, native, _ = load_pinned_inputs(reader, policy_path=ROOT / "mappings/rhea_release.json")
    rows = load_legacy_xref_audit(
        reader, release, native, policy_path=ROOT / "mappings/rhea_legacy_xref_dispositions.json"
    )
    verify_consumed_inputs(reader)
    legacy = json.loads((ROOT / "mappings/rhea_legacy_xref_dispositions.json").read_text())
    checked_legacy = precheck_legacy(legacy, native)
    require(
        len(rows) == 6 and checked_legacy["passed"] and len(checked_legacy["directional_annotations"]) == 7,
        "Rhea activation legacy gate failed",
    )
    return {
        "stage": staged,
        "legacy_rows": rows,
        "directional_witnesses": checked_legacy["directional_annotations"],
        "consumed_inputs": reader.consumed_input_snapshots,
        "production_transform_run": False,
        "label_authority_admission": False,
    }


def validate_selection(plan):
    """Reassert the fixed write allowlist even when execute is called as a Python function."""
    require(plan["raw"] == str(RAW) and plan["evidence"] == str(ACTIVATION), "Plan roots changed")
    entries = plan["replacements"]
    require(
        len(entries) == 16 and {row["name"] for row in entries} == set(HTTP) | set(OUTPUTS.values()),
        "Activation file selection changed",
    )
    for row in entries:
        name = row["name"]
        expected = (
            UPGRADES / "candidates" / HTTP[name][1] / name if name in HTTP else UPGRADES / "robot-conversions" / name
        )
        require(row["source"] == str(expected), "Candidate source path changed")
        require(Path(name).name == name, "Unsafe destination name")
    require(set(plan["rhea_candidates"]) == {"rhea.rdf.gz", "rhea-directions.tsv"}, "Rhea pair selection changed")
    for name, path in plan["rhea_candidates"].items():
        require(path == str(UPGRADES / "candidates/rhea143" / name), "Rhea candidate path changed")


def execute(plan):
    """Preserve every replaced input and leave an explicit failed receipt after any partial mutation."""
    validate_layout()
    require(
        plan.get("ready") is True and plan["worktree"] == str(ROOT), "Activation plan is not ready for this worktree"
    )
    validate_selection(plan)
    require(not os.path.lexists(ACTIVATION), f"Activation evidence collision: {ACTIVATION}")
    ACTIVATION.mkdir()
    generation, preserved = ACTIVATION / "generation", ACTIVATION / "preserved"
    generation.mkdir()
    preserved.mkdir()
    progress = {"status": "preparing", "activation_complete": False, "events": [], "production_admission": False}
    try:
        write_json(ACTIVATION / "before.json", plan)
        for entry in plan["replacements"]:
            copy_verified(Path(entry["source"]), generation / entry["name"], entry["candidate"])
        (generation / "rhea-inputs").mkdir()
        for name, source in plan["rhea_candidates"].items():
            copy_verified(Path(source), generation / "rhea-inputs" / name, plan["rhea_policy"]["files"][name])
        recheck(plan)
        for entry in plan["replacements"]:
            checked(generation / entry["name"], entry["candidate"])
        for name, expected in plan["rhea_policy"]["files"].items():
            checked(generation / "rhea-inputs" / name, expected)
        progress["status"] = "activating"
        write_json(ACTIVATION / "progress.json", progress)
        for entry in plan["replacements"]:
            destination, old = RAW / entry["name"], preserved / entry["name"]
            checked(generation / entry["name"], entry["candidate"])
            if entry["before"] is not None:
                checked(destination, entry["before"])
                require(not os.path.lexists(old), f"Preservation collision: {old}")
                os.replace(destination, old)
                checked(old, entry["before"])
                progress["events"].append(
                    {"name": entry["name"], "action": "original_preserved", "identity": entry["before"]}
                )
                write_json(ACTIVATION / "progress.json", progress, replace=True)
            require(not os.path.lexists(destination), f"Raw destination appeared: {destination}")
            # Atomic exclusive publication: never overwrite an unexpected file.
            os.link(generation / entry["name"], destination, follow_symlinks=False)
            (generation / entry["name"]).unlink()
            checked(destination, entry["candidate"])
            progress["events"].append(
                {"name": entry["name"], "action": "candidate_published", "identity": entry["candidate"]}
            )
            write_json(ACTIVATION / "progress.json", progress, replace=True)
        require(tree_identity(RAW / "rhea") == plan["rhea_before"], "Rhea changed before preservation")
        require(not os.path.lexists(preserved / "rhea"), "Rhea preservation collision")
        os.replace(RAW / "rhea", preserved / "rhea")
        require(tree_identity(preserved / "rhea") == plan["rhea_before"], "Preserved Rhea differs")
        progress["events"].append({"name": "rhea", "action": "original_directory_preserved"})
        write_json(ACTIVATION / "progress.json", progress, replace=True)
        rhea_result = activate_rhea(generation, ACTIVATION)
        after = {entry["name"]: checked(RAW / entry["name"], entry["candidate"]) for entry in plan["replacements"]}
        for name, pin in plan["rhea_policy"]["files"].items():
            checked(RAW / "rhea" / name, pin)
        # The guarded inputs are candidate sources, unchanged OWLs, policies/code,
        # and evidence, not raw targets whose replacement this helper just owned.
        for path, expected in plan["guards"].items():
            checked(Path(path), expected)
        progress.update(
            status="activated_pending_production_admission", activation_complete=True, after=after, rhea=rhea_result
        )
        write_json(
            ACTIVATION / "progress.json",
            {**progress, "activation_complete": False, "status": "verified_pending_final_receipt"},
            replace=True,
        )
        write_json(ACTIVATION / "after.json", progress)
    except BaseException as error:
        progress.update(status="failed", activation_complete=False, error_type=type(error).__name__, error=str(error))
        write_json(ACTIVATION / "failure.json", progress)
        raise
    return progress


def main(argv=None):
    """Plan by default; only an explicit execute switch may mutate the fixed staged raw root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_plan()
        require(not os.path.lexists(ACTIVATION), f"Activation evidence collision: {ACTIVATION}")
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"ready": False, "activation_executed": False, "error": str(error)}, indent=2))
        return 1
    result = execute(plan) if args.execute else plan
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
