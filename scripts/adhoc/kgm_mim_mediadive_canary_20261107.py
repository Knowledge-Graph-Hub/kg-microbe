#!/usr/bin/env python3
"""
Observe one real MediaDive writer iteration without certifying a partial source (#1798).

Plan by default. Execute only through the owned production launcher after native
upstreams and the reviewed mapping pair are ready. The full sealed catalogue is
never replaced or reduced. Only the progress observer interrupts the dispatcher.
"""

import argparse
import csv
import hashlib
import importlib
import json
import os
import re
import socket
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/mim-1788-20261107/mediadive-canary"
SUMMARY = Path("kg_microbe/transform_utils/mediadive/tmp/mediadive.tsv")
STOP_MESSAGE = "Bounded interruption after the first complete native MediaDive medium"
DESCRIPTION = "Processing mediadive: mediadive.medium:1"
FIRST_NAMES = ("Peptone", "Meat extract", "Agar", "Distilled water")
GENERATION_ID = "resolution-admitted-r2"
MANIFEST_SHA256 = "fa3c9e47bad5ff298b35e32382de7bd642e6be6ed95540db128d7d674058924f"
CATALOGUE_COUNT = 3344


def require(condition, message):
    """Refuse an unproved canary without changing source inputs or old evidence."""
    if not condition:
        raise ValueError(message)


def digest(path):
    """Hash source or partial-output bytes with bounded memory."""
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def save(path, value):
    """Create new evidence exclusively, preserving any existing attempt."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def owned(path):
    """Reject linked or escaping locators before inspecting or moving an owned path."""
    path = Path(path).absolute()
    require(path.is_relative_to(ROOT), "Locator is outside the owned checkout")
    for member in (path, *path.parents):
        require(not member.is_symlink(), "Linked canary locator")
        if member == ROOT:
            break
    require(path.resolve().is_relative_to(ROOT), "Resolved locator escapes the owned checkout")
    return path


def plan(label):
    """Describe fixed production paths without invoking a producer or creating evidence."""
    require(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", label) is not None, "Invalid unique canary label")
    directory = owned(EVIDENCE / label)
    output = owned(ROOT / "data/transformed/mediadive")
    summary = owned(ROOT / SUMMARY)
    require(not os.path.lexists(directory), "Canary evidence label already exists")
    require(not os.path.lexists(output), "Refusing preexisting MediaDive output directory")
    require(not os.path.lexists(summary), "Refusing preexisting MediaDive summary")
    return {
        "label": label,
        "evidence": str(directory),
        "output": str(output),
        "summary": str(summary),
        "dispatcher": "kg_microbe.transform.transform",
        "sources": ["mediadive"],
        "show_status": False,
        "first_medium": "mediadive.medium:1",
        "source_completed": False,
        "source_admitted": False,
        "meaning": (
            "One bounded writer interruption; scientific target review and full source completion remain separate"
        ),
    }


class BoundedStop(BaseException):
    """Escape native batch error isolation after exactly one completed medium."""


class NetworkAttempt(BaseException):
    """Escape any ordinary per-record handler on an attempted network operation."""


class FirstMediumObserver:
    """Observe the existing progress callback without selecting or editing native records."""

    def __init__(self, expected_total, *, total, desc):
        """Bind the untouched catalogue size and exact native progress initialization."""
        require(type(total) is int and total == expected_total, "Native progress catalogue count changed")
        require(desc == "Processing files", "Unexpected progress initialization")
        self.total = total
        self.description = None
        self.updates = 0
        self.exited = False

    def __enter__(self):
        """Use the native writer's existing context-manager boundary."""
        return self

    def __exit__(self, kind, value, traceback):
        """Record unwinding without swallowing the dedicated interruption."""
        self.exited = True
        return False

    def set_description(self, desc=None):
        """Require the first completed medium, never searching ahead for a convenient one."""
        require(self.description is None and desc == DESCRIPTION, "Unexpected first completed native medium")
        self.description = desc

    def update(self, n=1):
        """Interrupt only the first complete native medium callback."""
        require(type(n) is int and n == 1 and self.updates == 0, "Unexpected progress update")
        require(self.description == DESCRIPTION, "Completion callback lacks the exact first medium")
        self.updates += 1
        raise BoundedStop(STOP_MESSAGE)


@contextmanager
def no_network():
    """Fail every request or socket connection attempt without recording URLs or payloads."""
    import requests

    counts = {"requests": 0, "connections": 0}

    def refuse_request(*args, **kwargs):
        """Count even an intercepted logical request as a failed canary."""
        counts["requests"] += 1
        raise NetworkAttempt("Network request attempted during offline transform canary")

    def refuse_connect(*args, **kwargs):
        """Block lower-level outbound connections too."""
        counts["connections"] += 1
        raise NetworkAttempt("Network connection attempted during offline transform canary")

    with (
        patch.object(requests.sessions.Session, "request", refuse_request),
        patch.object(socket.socket, "connect", refuse_connect),
        patch.object(socket.socket, "connect_ex", refuse_connect),
    ):
        yield counts


def observed_instance(error, dispatcher, module):
    """Inspect only exact native traceback frames; never serialize frames or arbitrary locals."""
    run_instances, dispatch_instances = [], []
    trace = error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code is module.MediaDiveTransform.run.__code__:
            run_instances.append(trace.tb_frame.f_locals.get("self"))
        if trace.tb_frame.f_code is dispatcher._run_one.__code__:
            dispatch_instances.append(trace.tb_frame.f_locals.get("t"))
        trace = trace.tb_next
    require(len(run_instances) == len(dispatch_instances) == 1, "Missing exact native dispatcher/run witness")
    instance = run_instances[0]
    require(instance is dispatch_instances[0] and type(instance) is module.MediaDiveTransform, "Wrong native instance")
    require(instance._consumed_input_error == STOP_MESSAGE, "Native interruption is not sticky")
    return instance


def dispatch_first(dispatcher, module, raw, transformed, total):
    """Invoke the unchanged dispatcher; replace only its otherwise-no-op progress observer."""
    observers = []

    def observer(*args, **kwargs):
        """Create exactly one observer for the unmodified native catalogue."""
        require(not args and not observers, "Unexpected additional progress observer")
        value = FirstMediumObserver(total + 1, **kwargs)
        observers.append(value)
        return value

    with no_network() as attempts, patch.object(module, "DummyTqdm", observer):
        try:
            dispatcher.transform(raw, transformed, sources=["mediadive"], show_status=False)
        except BoundedStop as error:
            require(str(error) == STOP_MESSAGE, "Unexpected bounded interruption")
            instance = observed_instance(error, dispatcher, module)
        else:
            raise ValueError("Native dispatcher returned without the required bounded interruption")
    require(len(observers) == 1 and observers[0].updates == 1 and observers[0].exited, "Incomplete observer witness")
    require(not any(attempts.values()) and instance.api_calls_made == 0, "Canary attempted HTTP")
    require(instance._http is None, "Native HTTP session did not close")
    return instance, {"updates": 1, "description": observers[0].description, "network_attempts": attempts}


def regular_members(directory):
    """List all regular input members, including ignored files, and reject links."""
    result = []
    for path in sorted(Path(directory).rglob("*")):
        owned(path)
        require(path.is_dir() or path.is_file(), "Nonregular input member")
        if path.is_file():
            result.append(path)
    return tuple(result)


def prepare_inputs(module):
    """Bind curation, upstream witnesses and the full first-medium native context before dispatch."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import strict_json
    from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

    guard = SourceAdmission()
    for directory in (ROOT / "mappings", ROOT / "kg_microbe/profiles"):
        for path in guard.capture_resolution(regular_members, directory):
            guard.capture(path)
    for directory in (ROOT / "kg_microbe", ROOT / "scripts"):
        guard.capture_tree(directory)
    for path in (
        module.CHEBI_NODES_FILE,
        module.CHEBI_EDGES_FILE,
        module.BACDIVE_TMP_DIR / "bacdive.tsv",
        *(
            ROOT / "data/transformed" / upstream / FINGERPRINT_FILE
            for upstream in module.MediaDiveTransform.TRANSFORM_INPUTS
        ),
    ):
        guard.capture(owned(path))
    raw = ROOT / "data/raw/mediadive"
    pointer = strict_json(guard.capture(owned(raw / "current.json"), retain=True))
    require(
        pointer == {"schema_version": 1, "generation_id": GENERATION_ID, "manifest_sha256": MANIFEST_SHA256},
        "Previously admitted generation binding changed",
    )
    name = pointer.get("generation_id")
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name), "Unsafe generation identifier")
    generation = raw / "generations" / name
    manifest = owned(generation / "manifest.json")
    guard.capture(manifest)
    require(
        guard.identities[manifest.resolve()]["sha256"] == pointer.get("manifest_sha256"), "Manifest binding changed"
    )
    catalogue = strict_json(guard.capture(owned(generation / "catalogue.json"), retain=True))
    detail = strict_json(guard.capture(owned(generation / "media_detailed.json"), retain=True))
    solutions = strict_json(guard.capture(owned(generation / "solutions.json"), retain=True))
    require(isinstance(catalogue, dict) and isinstance(catalogue.get("data"), list), "Missing native catalogue")
    require(catalogue["data"] and catalogue["data"][0].get("id") == 1, "Native first medium is not 1")
    require(len(catalogue["data"]) == CATALOGUE_COUNT, "Complete admitted catalogue scope changed")
    first = catalogue["data"][0]
    require(type(first["id"]) is int and first.get("name") == "NUTRIENT AGAR", "Native first-medium context changed")
    references = detail["1"].get("solutions")
    require(
        isinstance(references, list) and len(references) == 1 and references[0].get("id") == 1, "First solution changed"
    )
    recipe = solutions["1"].get("recipe")
    require(isinstance(recipe, list) and len(recipe) == 4, "First native recipe occurrence count changed")
    require(tuple(row.get("compound") for row in recipe) == FIRST_NAMES, "First native recipe order/names changed")
    require(references[0].get("recipe") == recipe, "Native expanded and selected recipe disagree")
    return guard, {
        "catalogue_count": len(catalogue["data"]),
        "first_medium": first,
        "recipe": recipe,
        "pointer": pointer,
    }


def retained_inputs(instance, guard):
    """Verify original read guards directly while preserving the native sticky failure."""
    from kg_microbe.transform_utils.mediadive.bulk_inputs import REQUIRED_BULK_INPUTS, _bound_payload, _payload_digest

    require(instance._consumed_input_error == STOP_MESSAGE, "Sticky interruption changed")
    snapshots = instance.consumed_input_snapshots
    require(set(instance.REQUIRED_CONSUMED_INPUTS) <= set(snapshots), "Native required reads are incomplete")
    for role, record in snapshots.items():
        require(digest(record["path"]) == record["sha256"], "Original native consumed bytes changed: " + role)
    bindings = instance._bulk_payload_bindings
    require(set(bindings) == set(REQUIRED_BULK_INPUTS), "Native parsed payload binding scope changed")
    for role, binding in bindings.items():
        require(
            snapshots[role] == {"path": binding.source_path, "sha256": binding.source_sha256}, "Read binding changed"
        )
        require(_payload_digest(_bound_payload(instance, role)) == binding.sha256, "Native cached payload changed")
    guards = {
        "pre_dispatch": guard,
        "endpoint_and_bulk": instance._bulk_input_admission,
        "recipe": instance._recipe_identity_guard.admission,
        "material": instance._material_scope_audit.guard,
        "optional": instance._optional_input_admission,
        "dependencies": instance._dependency_admission,
    }
    identities = {}
    for name, original in guards.items():
        if original is not None:
            original.verify()
            identities[name] = {str(path): dict(value) for path, value in original.identities.items()}
    instance._endpoint_consumer.verify()
    instance._recipe_identity_guard.verify()
    require(not instance._endpoint_consumer.contract()["sealed"], "Unexpected completed endpoint audit")
    require(not instance._recipe_identity_guard.sealed, "Unexpected completed recipe audit")
    require(instance._consumed_input_error == STOP_MESSAGE, "Canary cleared or replaced sticky failure")
    return {
        "consumed_roles": snapshots,
        "original_guard_identities": identities,
        "native_contract": instance.producer_native_inputs,
    }


def tsv_rows(path):
    """Read the native, still quoted writer dialect and its optional trailing cells."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", restval="")
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "Invalid TSV header")
        rows = list(reader)
    require(all(None not in row for row in rows), "Extra native TSV fields")
    return rows


def partial_graph(instance, native, summary):
    """Check exact first-medium occurrence conservation without approving mapping targets globally."""
    from kg_microbe.transform_utils.constants import MEDIADIVE_MEDIUM_PREFIX, MEDIADIVE_SOLUTION_PREFIX
    from kg_microbe.transform_utils.mediadive.recipe_identity import encoded
    from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE

    require(
        set(path.name for path in instance.output_dir.iterdir()) == {"nodes.tsv", "edges.tsv"},
        "Unexpected partial output cohort",
    )
    for name in ("source_finalization.json", FINGERPRINT_FILE, *instance.REQUIRED_AUDIT_FILES):
        require(not os.path.lexists(instance.output_dir / name), "Partial source published a completion claim")
    nodes, edges, rows = tsv_rows(instance.output_node_file), tsv_rows(instance.output_edge_file), tsv_rows(summary)
    require(len(rows) == 1 and rows[0].get("mediadive_id") == "mediadive.medium:1", "Not exactly one completed summary")
    medium_ids = {row["id"] for row in nodes if row["id"].startswith(MEDIADIVE_MEDIUM_PREFIX)}
    require(medium_ids == {"mediadive.medium:1"}, "Unexpected medium graph scope")
    solution_ids = {row["id"] for row in nodes if row["id"].startswith(MEDIADIVE_SOLUTION_PREFIX)}
    require(solution_ids == {"mediadive.solution:1"}, "Unexpected native solution scope")
    for edge in edges:
        for column in ("subject", "object"):
            if edge[column].startswith(MEDIADIVE_MEDIUM_PREFIX):
                require(edge[column] == "mediadive.medium:1", "Another medium was written")
    occurrences = [row for row in edges if row.get("source_assertion_id")]
    expected = {f"mediadive.solution:1#recipe/{number}": raw for number, raw in enumerate(native["recipe"], 1)}
    require(
        len(occurrences) == len(expected) and {row["source_assertion_id"] for row in occurrences} == set(expected),
        "Native occurrence scope changed",
    )
    for row in occurrences:
        raw = expected[row["source_assertion_id"]]
        require(
            row["subject"] == "mediadive.solution:1" and row["predicate"] == "biolink:has_part",
            "Wrong native recipe assertion",
        )
        require(row["source_record"] == encoded(raw), "Native recipe context changed")
        for field, source in (("value", "amount"), ("unit", "unit"), ("g_l", "g_l"), ("mmol_l", "mmol_l")):
            value = raw.get(source)
            require(row.get(field, "") == ("" if value is None else str(value)), "Native quantity changed")
        require(any(node["id"] == row["object"] for node in nodes), "Ingredient target lacks a native node")
    require(set(instance._recipe_identity_guard.observed) == set(expected), "Observed occurrence scope changed")
    return {
        "node_rows": len(nodes),
        "edge_rows": len(edges),
        "summary_rows": 1,
        "native_occurrences": occurrences,
        "target_scientific_review": "pending independent review; no all-mapping approval",
    }


def output_identities(output, summary):
    """Identify only the exact newly created source directory and summary file."""
    require(set(path.name for path in output.iterdir()) == {"nodes.tsv", "edges.tsv"}, "Unexpected output member")
    result = {}
    for path in (output / "nodes.tsv", output / "edges.tsv", summary):
        owned(path)
        require(path.is_file() and path.stat().st_nlink == 1, "Partial output is not independently owned")
        result[str(path)] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return result


def preserve_partial(output, summary, directory, expected):
    """Move only proved new partial outputs; never clean unrelated data or finalize them."""
    require(output_identities(output, summary) == expected, "Partial output changed before preservation")
    preserved = owned(directory / "partial-output")
    saved_summary = owned(directory / "partial-summary.tsv")
    require(not os.path.lexists(preserved) and not os.path.lexists(saved_summary), "Preservation destination exists")
    output.rename(preserved)
    summary.rename(saved_summary)
    actual = output_identities(preserved, saved_summary)
    for source, target in (
        (output / "nodes.tsv", preserved / "nodes.tsv"),
        (output / "edges.tsv", preserved / "edges.tsv"),
        (summary, saved_summary),
    ):
        require(actual[str(target)] == expected[str(source)], "Preserved partial output differs")
    return actual


def runtime():
    """Require the owned launcher, checkout and isolated interpreter without reading credentials."""
    require(Path.cwd().resolve() == ROOT and sys.dont_write_bytecode, "Owned cwd and disabled bytecode required")
    require(Path(sys.prefix).resolve() == ROOT / ".venv", "Owned isolated interpreter required")
    launcher = ROOT / "scripts/adhoc/kgm_rebuild_20261105.py"
    require(os.environ.get("KGM_REBUILD_LAUNCHER") == str(launcher), "Saved production launcher required")
    dispatcher = importlib.import_module("kg_microbe.transform")
    module = importlib.import_module("kg_microbe.transform_utils.mediadive.mediadive")
    registered = dispatcher.DATA_SOURCES["mediadive"]
    require(
        getattr(registered, "transform_class", registered) is module.MediaDiveTransform, "Wrong registered producer"
    )
    return dispatcher, module


def origins():
    """Retain only owned first-party module locations and actual source hashes."""
    result = {}
    for name, module in list(sys.modules.items()):
        if name == "kg_microbe" or name.startswith("kg_microbe."):
            path = getattr(module, "__file__", None)
            if path is not None:
                path = Path(path).resolve()
                require(path.is_relative_to(ROOT), "First-party module came from another checkout")
                result[name] = {"path": str(path), "sha256": digest(path)}
    return result


def execute(label):
    """Retain one bounded actual dispatcher attempt and preserve its incomplete outputs."""
    planned = plan(label)
    directory = Path(planned["evidence"])
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "plan.json", planned)
    record = {
        **planned,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "source_completed": False,
        "source_admitted": False,
    }
    try:
        with no_network() as outer_attempts:
            dispatcher, module = runtime()
            require(Path(module.MEDIADIVE_TMP_DIR).resolve() == (ROOT / SUMMARY).parent, "Unexpected summary locator")
            guard, native = prepare_inputs(module)
            save(directory / "native-first-context.json", native)
            output, summary = Path(planned["output"]), Path(planned["summary"])
            # Claim only absent fixed output paths, immediately before the real dispatcher.
            output.mkdir(parents=True, exist_ok=False)
            summary.parent.mkdir(parents=True, exist_ok=True)
            with summary.open("x"):
                pass
            reservations = {str(path): (path.stat().st_dev, path.stat().st_ino) for path in (output, summary)}
            record["new_output_reservations"] = reservations
            instance, observation = dispatch_first(
                dispatcher, module, ROOT / "data/raw", ROOT / "data/transformed", native["catalogue_count"]
            )
            output, summary = Path(planned["output"]), Path(planned["summary"])
            require(
                all(
                    (Path(path).stat().st_dev, Path(path).stat().st_ino) == stamp
                    for path, stamp in reservations.items()
                ),
                "Owned partial output path was replaced",
            )
            graph = partial_graph(instance, native, summary)
            original = retained_inputs(instance, guard)
            require(not any(outer_attempts.values()), "Canary attempted HTTP outside dispatcher")
            save(directory / "original-input-identities.json", original)
            record.update(
                observation=observation,
                graph=graph,
                native_generation=instance._endpoint_consumer.view.contract(),
                qualification=instance._endpoint_consumer.view.qualification,
                owned_module_origins=origins(),
            )
            before = output_identities(output, summary)
            save(directory / "partial-output-before.json", before)
            record["preserved_outputs"] = preserve_partial(output, summary, directory, before)
            guard.verify(metadata_only=True)
            record.update(
                status="bounded_interruption_verified",
                sticky_failure=STOP_MESSAGE,
                input_identities_sha256=digest(directory / "original-input-identities.json"),
                helper_sha256=digest(__file__),
                api_calls_made=instance.api_calls_made,
            )
    except BaseException as error:
        record["failure_type"] = type(error).__name__
        save(directory / "result.json", record)
        raise
    save(directory / "result.json", record)
    return record


def main(argv=None):
    """Print the plan unless explicit execution of a unique owned attempt was requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = execute(args.label) if args.execute else plan(args.label)
    print(
        json.dumps(
            result
            if not args.execute
            else {"status": result["status"], "source_completed": False, "source_admitted": False},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
