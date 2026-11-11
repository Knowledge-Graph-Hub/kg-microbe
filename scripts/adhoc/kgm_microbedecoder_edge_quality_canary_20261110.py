"""Run one complete native MicrobeDecoder canary after genuine owned GOLD completion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/Users/marcin/agent-work/kg-microbe/transform-edge-quality-20261110")
EVIDENCE = ROOT / "data/edge-quality-20261110"
NATIVE = EVIDENCE / "microbedecoder-canary/native"
RAW = NATIVE / "raw"
OUTPUT = NATIVE / "transformed"
RECEIPT_DIRECTORY = EVIDENCE / "microbedecoder-canary/microbedecoder-run-r1"
OLD = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe")


def identity(path):
    """Hash a regular unlinked selected file without changing its bytes."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked selected canary input: " + str(path))
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("Canary input changed during hashing")
    return {"path": str(path), "bytes": before.st_size, "sha256": digest.hexdigest()}


def write_json(path, value):
    """Publish only a fresh bounded execution receipt; never replace prior evidence."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def table_counts(path, kind, *, enforce_current=True):
    """Recount explicit MicrobeDecoder cohorts with a streaming literal TSV reader."""
    counts = {"rows": 0}
    digest = hashlib.sha256()
    before = path.stat()
    identifiers, img_subjects = set(), set()
    with path.open("rb") as stream:
        first = stream.readline()
        digest.update(first)
        header = first.decode("utf-8").rstrip("\r\n").split("\t")
        if len(set(header)) != len(header):
            raise ValueError("Duplicate TSV columns")
        for line in stream:
            digest.update(line)
            cells = line.decode("utf-8").rstrip("\r\n").split("\t")
            if len(cells) != len(header):
                raise ValueError("Malformed literal TSV row")
            row = dict(zip(header, cells, strict=True))
            counts["rows"] += 1
            if kind == "edges":
                column = row.get("source_column", "")
                for label, selected in (
                    ("bacdive_snapshot_edges", column.startswith("BacDive_")),
                    ("bergey_other", column == "Bergey_Type_of_metabolism" and row.get("value") == "Other"),
                    (
                        "bergey_not_reported",
                        column == "Bergey_Substrates_for_end_products" and row.get("value") == "Not reported",
                    ),
                    ("faprotax_edges", column == "FAPROTAX_Type_of_metabolism"),
                    ("img_subject_edges", row.get("subject", "").startswith("IMG:")),
                    ("source_attribute_edges", row.get("object", "").startswith("kgmicrobe.source_attribute:")),
                ):
                    counts[label] = counts.get(label, 0) + int(selected)
                if row.get("subject", "").startswith("IMG:"):
                    if (row["predicate"], row["relation"]) != ("biolink:in_taxon", "RO:0002162"):
                        counts["img_membership_semantics_violations"] = (
                            counts.get("img_membership_semantics_violations", 0) + 1
                        )
                        if enforce_current:
                            raise ValueError("IMG membership gained unexpected semantics")
                    img_subjects.add(row["subject"])
            elif kind == "nodes" and row.get("id", "").startswith("IMG:"):
                if row["id"] in identifiers or row["category"] != "biolink:Genome":
                    counts["img_declaration_violations"] = counts.get("img_declaration_violations", 0) + 1
                    if enforce_current:
                        raise ValueError("IMG declaration missing category or duplicated")
                identifiers.add(row["id"])
            elif kind == "audit":
                label = row["disposition"]
                counts[label] = counts.get(label, 0) + 1
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("Canary TSV changed while counting")
    return {
        "identity": {"path": str(path), "bytes": before.st_size, "sha256": digest.hexdigest()},
        "header": header,
        "counts": counts,
        "img_ids": sorted(identifiers or img_subjects),
    }


def plan():
    """Expose concrete immutable inputs and required owned authority without executing imports."""
    paths = [
        RAW / "microbedecoder_database.zip",
        RAW / "lpsn_gss.csv",
        OUTPUT / "gold/source_finalization.json",
        OUTPUT / "gtdb/nodes.tsv",
        OUTPUT / "lpsn/nodes.tsv",
        *[OUTPUT / "ontologies" / f"{name}_nodes.tsv" for name in ("metpo", "go", "chebi")],
    ]
    return {
        "scope": "complete native single-source canary; not a full graph rebuild",
        "raw": str(RAW),
        "output": str(OUTPUT / "microbedecoder"),
        "inputs": [identity(path) if path.is_file() else {"path": str(path), "pending": True} for path in paths],
        "snapshot_graph_mode": False,
        "execute": False,
    }


def execute():
    """Invoke the real constructor, full run, finalization and retained native guards once."""
    if Path.cwd().resolve() != ROOT or Path(sys.prefix).resolve() != ROOT / ".venv":
        raise ValueError("Canary requires the owned Python and working directory")
    if any(os.environ.get(key) for key in ("LPSN_USERNAME", "LPSN_PASSWORD")):
        raise ValueError("This offline source canary must not inherit LPSN credentials")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Dotenv loading must be disabled")
    if os.environ.get("MICROBEDECODER_INCLUDE_BACDIVE_SNAPSHOT", "false").lower() not in {"false", "0"}:
        raise ValueError("The selected canary is the default snapshot-off mode")
    initial = plan()
    if any(item.get("pending") for item in initial["inputs"]):
        raise ValueError("Native canary prerequisites remain pending")
    if (OUTPUT / "microbedecoder").exists():
        raise ValueError("Refusing to replace any earlier MicrobeDecoder canary output")
    RECEIPT_DIRECTORY.mkdir()
    write_json(RECEIPT_DIRECTORY / "before.json", initial)
    started = time.monotonic()
    try:
        from kg_microbe.merge_utils.source_admission import SourceAdmission
        from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

        origins = Path(sys.modules[MicrobeDecoderTransform.__module__].__file__).resolve()
        if not origins.is_relative_to(ROOT / "kg_microbe"):
            raise ValueError("Foreign MicrobeDecoder module origin")
        guard = SourceAdmission()
        guard.capture_tree(ROOT / "kg_microbe")
        for relative in MicrobeDecoderTransform.DATA_INPUTS:
            guard.capture(ROOT / relative)
        transform = MicrobeDecoderTransform(RAW, OUTPUT)
        transform.run(data_file=RAW / "microbedecoder_database.zip", show_status=False)
        report = transform.finalize(fresh_run=True)
        transform.verify_consumed_inputs()
        transform.verify_native_inputs()
        current = {
            kind: table_counts(OUTPUT / "microbedecoder" / name, kind)
            for kind, name in (("nodes", "nodes.tsv"), ("edges", "edges.tsv"), ("audit", "reported_observations.tsv"))
        }
        if set(current["edges"]["img_ids"]) != set(current["nodes"]["img_ids"]):
            raise ValueError("Not every IMG subject has its source-owned Genome declaration")
        if any(
            current["edges"]["counts"].get(key, 0)
            for key in ("bacdive_snapshot_edges", "bergey_other", "bergey_not_reported")
        ):
            raise ValueError("Audit-only source observations leaked into graph assertions")
        for kind in ("nodes", "edges"):
            item = current[kind]["identity"]
            if {key: item[key] for key in ("bytes", "sha256")} != report["members"][kind + ".tsv"]:
                raise ValueError("Canary completion changed during recount")
        historical = {}
        for kind in ("nodes", "edges"):
            old = OLD / "data/transformed/microbedecoder" / (kind + ".tsv")
            historical[kind] = table_counts(old, kind, enforce_current=False)
        old_report = OLD / "data/transformed/microbedecoder/source_finalization.json"
        old_document = json.loads(old_report.read_text())
        for kind in ("nodes", "edges"):
            old_identity = historical[kind]["identity"]
            if {key: old_identity[key] for key in ("bytes", "sha256")} != old_document["members"][kind + ".tsv"]:
                raise ValueError("Historical source graph no longer matches its retained completion")
        guard.verify()
        for item in initial["inputs"]:
            if identity(item["path"]) != item:
                raise ValueError("Original selected input changed across the canary")
        if (OUTPUT / "microbedecoder/source_fingerprint.json").exists():
            raise ValueError("Direct finalization unexpectedly wrote a dispatcher source marker")
        result = {
            "status": "PASS_COMPLETE_NATIVE_SINGLE_SOURCE_CANARY",
            "elapsed_seconds": time.monotonic() - started,
            "head_scope": "current owned working source; no whole graph or historical artifact regeneration claim",
            "actual_current": current,
            "historical_reference": historical,
            "historical_report": identity(old_report),
            "historical_raw_sha256": old_document.get("consumed_inputs", {}).get("crosswalk_raw", {}).get("sha256"),
            "actual_raw": transform.consumed_input_snapshots["crosswalk_raw"],
            "producer_native_inputs": report["producer_native_inputs"],
            "source_finalization": identity(OUTPUT / "microbedecoder/source_finalization.json"),
            "source_marker_written": False,
            "reviewed_scope_observations_preserved": True,
            "whole_graph_admission": False,
            "inputs_unchanged": True,
            "producer_origin": str(origins),
        }
        write_json(RECEIPT_DIRECTORY / "result.json", result)
    except BaseException as error:
        write_json(
            RECEIPT_DIRECTORY / "failure.json",
            {
                "status": "FAILED",
                "exception_type": type(error).__name__,
                "message": str(error),
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        raise


def main():
    """Default to read-only prerequisite planning; execution requires an explicit flag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        execute()
    else:
        print(json.dumps(plan(), indent=2))


if __name__ == "__main__":
    main()
