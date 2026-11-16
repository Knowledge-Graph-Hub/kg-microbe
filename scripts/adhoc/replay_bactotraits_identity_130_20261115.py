#!/usr/bin/env python3
"""
2026-11-15: prepare/replay one retained row for EdgeMech issue #130.

Inputs: unchanged June-2022 BactoTraits CSV, actual BacDive lookup, local METPO
templates, checked-out mappings and an existing read-only NCBITaxon SQLite DB.
Outputs: fresh ignored private subsets, actual transform outputs and a receipt.
Run --plan first, then one --run baseline, then a separately planned candidate.
This is a pre-finalization transform comparison, not a published graph release
or an independent scientific/model assessment. No provider calls are permitted.
2026-11-16, KG-Microbe #1866: confine import-time PyStow/OAK caches to the stage.
2026-11-16, KG-Microbe #1868: pin and consume the staged URI prefix registry.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
CANONICAL = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe")
BASELINE = Path("/Users/marcin/agent-work/EdgeMech/kgm-bactotraits-baseline-130-20261115")
BASE_REVISION = "ef27b97a0b450767da54235c6105b5250c178adc"
STAGING_ROOT = ROOT / "data/validation-bactotraits-130"
SOURCE_SHA = "18316d7a0b6c2bef6fcb96a7659c2e3f3734c14786f383c2a93fefe2ae226a4b"
ROW_SHA = "345fd2d00ee93334d975085716692dd4d4c530d5529f04c5b07af0766d5a512a"
SUBJECT = "NCBITaxon:1123071"
LABEL = "Rubritalea squalenifaciens DSM 18772"
AUDIT = "bactotraits_identity_quarantine.tsv"
PROFILE = "bactotraits-130-single-row-replay/v1"
GIT = str(Path(shutil.which("git") or "/usr/bin/git").resolve())


def require(condition, message):
    """Fail without relaxing a replay boundary."""
    if not condition:
        raise ValueError(message)


def digest(raw):
    """Hash retained bytes."""
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    """Serialize retained metadata deterministically."""
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def git(root, *arguments):
    """Read Git identity with no shell interpretation."""
    # Commands are fixed read-only Git operations chosen inside this launcher.
    return subprocess.check_output([GIT, "-C", str(root), *arguments], text=True).strip()  # noqa: S603


def safe_path(path):
    """Reject symlinked input/output paths, including their ancestors."""
    path = path.absolute()
    require(".." not in path.parts, "Parent traversal is not a replay path")
    require(all(not part.is_symlink() for part in (path, *path.parents)), "Symlinked replay path")
    return path


def bytes_at(path, maximum=128 * 1024 * 1024):
    """Read one bounded regular input without permitting a missing-file fallback."""
    path = safe_path(path)
    require(path.is_file() and path.stat().st_size <= maximum, f"Unavailable/big input: {path}")
    return path.read_bytes()


def source_pin(path, raw):
    """Record the exact original source path and content hash."""
    return {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}


def selected_record(raw, encoding, delimiter, preamble, key, value):
    """Keep original header/preamble and one complete CSV record byte-for-byte."""
    lines = list(io.BytesIO(raw))
    reader = csv.reader(io.StringIO(raw.decode(encoding), newline=""), delimiter=delimiter)
    for _ in range(preamble):
        require(next(reader, None) is not None, "Missing CSV preamble")
    header = next(reader, None)
    require(header and len(header) == len(set(header)) and key in header, "Invalid CSV header")
    header_end = reader.line_num
    previous, matches = header_end, []
    for ordinal, row in enumerate(reader, 1):
        end = reader.line_num
        if len(row) > header.index(key) and row[header.index(key)] == value:
            require(len(row) == len(header), "Selected CSV row has wrong field count")
            matches.append((ordinal, dict(zip(header, row, strict=True)), b"".join(lines[previous:end])))
        previous = end
    require(len(matches) == 1, "Selected CSV identifier must occur exactly once")
    ordinal, row, raw_record = matches[0]
    return b"".join(lines[:header_end]) + raw_record, row, ordinal


def database_stat(path):
    """Record source metadata; this explicitly is not a full-database content hash."""
    path = safe_path(path)
    require(path.is_file(), "NCBITaxon DB is unavailable")
    require(
        not Path(str(path) + "-wal").exists() and not Path(str(path) + "-journal").exists(),
        "NCBITaxon DB has an active journal; immutable read is unsafe",
    )
    item = path.stat()
    return {
        "path": str(path),
        "bytes": item.st_size,
        "mtime_ns": item.st_mtime_ns,
        "device": item.st_dev,
        "inode": item.st_ino,
        "whole_database_hashed": False,
    }


def authority_rows(path):
    """Read the actual requested label and ontology-version statements without writes."""
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        labels = connection.execute(
            "SELECT subject, predicate, value FROM statements "
            "WHERE subject=? AND predicate='rdfs:label' ORDER BY value",
            (SUBJECT,),
        ).fetchall()
        versions = connection.execute(
            "SELECT subject, predicate, value FROM statements WHERE predicate='owl:versionInfo' "
            "AND subject LIKE '%ncbitaxon%' AND value IS NOT NULL ORDER BY subject, value"
        ).fetchall()
    require(labels and {row[2] for row in labels} == {LABEL}, "Actual NCBI label is absent or differs")
    require(versions and len(versions) < 20, "NCBITaxon release metadata is missing or ambiguous")
    return {"labels": [list(row) for row in labels], "versions": [list(row) for row in versions]}


class ReadOnlyNCBILabels:
    """Supply real SemSQL label rows through the transform's existing labels interface."""

    def __init__(self, path, expected):
        """Bind the database and exact inspected statements, without an OAK rebuild path."""
        self.path, self.expected, self.lookups = path, expected, 0

    def labels(self, identifiers):
        """Query the existing authority; never synthesize a label or missing-term fallback."""
        for identifier in identifiers:
            require(identifier == SUBJECT, "Single-row replay requested another taxon")
            actual = authority_rows(self.path)
            require(actual == self.expected, "NCBITaxon statements changed during replay")
            self.lookups += 1
            yield identifier, actual["labels"][0][2]


def prepare(args):
    """Inspect all inputs and return an in-memory single-case plan without writes."""
    code_root = safe_path(args.code_root or (BASELINE if args.mode == "baseline" else ROOT))
    revision = git(code_root, "rev-parse", "HEAD")
    if args.mode == "baseline":
        require(revision == BASE_REVISION, "Wrong baseline commit")
        require(not git(code_root, "status", "--porcelain", "--untracked-files=no"), "Dirty baseline code")
    stage = safe_path(ROOT / args.staging)
    require(stage.parent == STAGING_ROOT and stage.name not in {"", ".", ".."}, "Invalid staging location")
    require(not stage.exists(), "Replay stage already exists; select a fresh directory")
    ignored = subprocess.run(  # noqa: S603 - fixed read-only Git command, no shell.
        [
            GIT,
            "-C",
            str(ROOT),
            "check-ignore",
            "--quiet",
            "--no-index",  # noqa: S603
            str(stage / "receipt.json"),
        ],
        check=False,
    )
    require(ignored.returncode == 0, "Replay staging must be gitignored")
    require(not git(ROOT, "ls-files", "--", str(stage)), "Replay destination contains tracked files")
    if STAGING_ROOT.exists():
        require(stat.S_IMODE(STAGING_ROOT.stat().st_mode) == 0o700, "Staging root must be private")
    raw_root = safe_path(args.input_root) / "data/raw"
    raw_path = raw_root / "BactoTraits_databaseV2_Jun2022.csv"
    original = bytes_at(raw_path)
    require(digest(original) == SOURCE_SHA, "Original BactoTraits source bytes differ")
    subset, row, ordinal = selected_record(original, "ISO-8859-1", ";", 2, "Bacdive_ID", "17851")
    row_sha = digest(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True).encode())
    require(ordinal == 8521 and row_sha == ROW_SHA, "Original selected source row differs")
    lookup_path = safe_path(args.input_root) / "kg_microbe/transform_utils/bacdive/tmp/bacdive.tsv"
    lookup = bytes_at(lookup_path)
    lookup_subset, lookup_row, _ = selected_record(lookup, "utf-8", "\t", 0, "bacdive_id", "bacdive:17851")
    require(lookup_row["ncbitaxon_id"] == SUBJECT, "Actual BacDive lookup target differs")
    staged = {"raw/BactoTraits_databaseV2_Jun2022.csv": subset, "lookup/bacdive.tsv": lookup_subset}
    sources = [source_pin(raw_path, original), source_pin(lookup_path, lookup)]
    for destination, path in (
        ("templates/metpo_sheet.tsv", raw_root / "metpo_sheet.tsv"),
        ("templates/metpo-properties.tsv", raw_root / "metpo-properties.tsv"),
        ("mappings/custom_curies.yaml", code_root / "kg_microbe/transform_utils/custom_curies.yaml"),
        ("mappings/prefixmap.json", code_root / "kg_microbe/transform_utils/prefixmap.json"),
        ("mappings/metpo_alias_mappings.tsv", code_root / "mappings/canonical/metpo_alias_mappings.tsv"),
    ):
        raw = bytes_at(path)
        staged[destination] = raw
        sources.append(source_pin(path, raw))
    database = safe_path(args.ncbi_db)
    db_before = database_stat(database)
    statements = authority_rows(database)
    require(database_stat(database) == db_before, "NCBITaxon database changed during inspection")
    owl_path = raw_root / "ncbitaxon.owl.gz"
    with gzip.open(safe_path(owl_path), "rb") as stream:
        owl_head = stream.read(2_000_000)
    release = re.search(rb"versionIRI[^>]{0,160}?(\d{4}-\d{2}-\d{2})", owl_head)
    require(release is not None, "NCBITaxon OWL release is unreadable")
    owl_release = release.group(1).decode()
    db_versions = [item[2] for item in statements["versions"]]
    authority = {
        "database_metadata": db_before,
        "queried_statements": statements,
        "queried_statements_sha256": digest(json_bytes(statements)),
        "owl_path": str(owl_path),
        "owl_head_sha256": digest(owl_head),
        "owl_head_bytes": len(owl_head),
        "owl_release": owl_release,
        "release_alignment": any(owl_release in value for value in db_versions),
    }
    staged["authority/ncbitaxon-label.json"] = json_bytes(authority)
    shared = {
        "source_sha256": SOURCE_SHA,
        "original_data_row": ordinal,
        "row_sha256": row_sha,
        "staged_inputs": {name: digest(raw) for name, raw in staged.items()},
        "python": {"executable": str(Path(sys.executable).resolve()), "version": sys.version},
        "packages": {name: importlib.metadata.version(name) for name in ("oaklib", "pandas", "PyYAML")},
        "helper_sha256": digest(Path(__file__).read_bytes()),
    }
    require(authority["release_alignment"], "NCBITaxon DB/OWL versions differ; resolve before this replay")
    code_inputs = {
        str(path.relative_to(code_root)): digest(bytes_at(path))
        for path in sorted((code_root / "kg_microbe").rglob("*.py"))
        if "tmp" not in path.relative_to(code_root).parts
    }
    policy = None
    if args.mode == "candidate":
        policy_path = code_root / "mappings/canonical/bactotraits_identity_quarantine.json"
        policy = source_pin(policy_path, bytes_at(policy_path))
    return {
        "code_root": code_root,
        "revision": revision,
        "stage": stage,
        "staged": staged,
        "sources": sources,
        "authority": authority,
        "shared": shared,
        "row": row,
        "code_inputs": code_inputs,
        "policy": policy,
    }


def write_new(path, raw):
    """Persist private bytes exclusively and verify their readback."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(path.read_bytes() == raw, "Saved replay bytes differ")


def graph_rows(path):
    """Read only the bounded single-case output, requiring a nonempty persisted table."""
    require(path.is_file() and path.stat().st_size > 0, f"Missing transform output: {path}")
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def baseline_data(args, shared):
    """Verify a real baseline receipt and its persisted artifacts before comparison."""
    require(args.baseline_receipt is not None, "Candidate requires a completed baseline receipt")
    path = safe_path(args.baseline_receipt)
    raw = bytes_at(path)
    receipt = json.loads(raw)
    require(
        receipt["profile"] == PROFILE and receipt["mode"] == "baseline" and receipt["git_revision"] == BASE_REVISION,
        "Invalid baseline identity",
    )
    require(receipt["shared_inputs"] == shared, "Baseline and candidate do not share exact inputs/runtime")
    for name, expected in receipt["artifacts"].items():
        artifact = safe_path(path.parent / name)
        require(artifact.is_relative_to(path.parent), "Escaping baseline artifact")
        require(digest(bytes_at(artifact)) == expected["sha256"], "Baseline artifact changed")
    edges = graph_rows(path.parent / "transformed/bactotraits/edges.tsv")
    require(
        any(row["subject"] == SUBJECT and row["object"] == "METPO:1000703" for row in edges),
        "Baseline did not actually emit the reviewed nonmotility assertion",
    )
    return path, digest(raw), edges


def install_guards(stage):
    """Block network access and Python-level writes outside this private replay directory."""

    def audit(event, arguments):
        if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen"}:
            raise RuntimeError("Network/subprocess use is forbidden during the actual transform replay")
        paths = []
        if event == "open":
            path, mode, flags = arguments
            writable = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writable and isinstance(path, (str, bytes, os.PathLike)):
                paths = [path]
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"}:
            paths = [arguments[0]]
        elif event == "os.rename":
            paths = list(arguments[:2])
        for value in paths:
            path = safe_path(Path(os.fsdecode(value)))
            require(path.is_relative_to(stage), f"Write outside replay stage refused: {path}")

    sys.addaudithook(audit)
    socket.setdefaulttimeout(10)


def configure_private_environment(stage):
    """Place dependency caches inside the stage before importing the real producer."""
    temporary = stage / "tmp"
    temporary.mkdir(mode=0o700)
    tempfile.tempdir = str(temporary)
    # PyStow writes README.md during import. OAK and Bioregistry also create
    # module directories, whose specific overrides take precedence over its home.
    # Disable appdirs mode so its platform-specific defaults cannot bypass this root.
    cache = stage / "cache/pystow"
    os.environ.update(
        {
            "PYSTOW_HOME": str(cache),
            "PYSTOW_CONFIG_HOME": str(stage / "cache/pystow-config"),
            "PYSTOW_USE_APPDIRS": "false",
            "OAKLIB_HOME": str(cache / "oaklib"),
            "BIOREGISTRY_HOME": str(cache / "bioregistry"),
            "KG_MICROBE_METPO_TEMPLATE_DIR": str(stage / "templates"),
            "KG_SEMSQL_BUILD": "off",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return temporary


def bind_staged_prefix_registry(stage):
    """Make actual URI conversion consume staged bytes before producer construction."""
    from kg_microbe.utils import graph_canonicalization

    graph_canonicalization.PREFIXMAP_JSON_FILEPATH = stage / "mappings/prefixmap.json"
    graph_canonicalization._uri_prefixes.cache_clear()


def verify_runtime_inputs(plan):
    """Reject original or staged input drift before use and before issuing a receipt."""
    for source in plan["sources"]:
        require(digest(bytes_at(Path(source["path"]))) == source["sha256"], "Original runtime input changed")
    for name, expected in plan["shared"]["staged_inputs"].items():
        require(digest(bytes_at(plan["stage"] / name)) == expected, "Staged runtime input changed")


def run(args, plan):
    """Run exactly one real producer and verify its emitted evidence and graph difference."""
    stage, code_root = plan["stage"], plan["code_root"]
    baseline = baseline_data(args, plan["shared"]) if args.mode == "candidate" else None
    os.umask(0o077)
    STAGING_ROOT.mkdir(mode=0o700, exist_ok=True)
    stage.mkdir(mode=0o700)
    for name, raw in plan["staged"].items():
        write_new(stage / name, raw)
    write_new(stage / "input-plan.json", json_bytes({key: plan[key] for key in ("sources", "authority", "shared")}))
    verify_runtime_inputs(plan)
    temporary = configure_private_environment(stage)
    sys.path.insert(0, str(code_root))
    install_guards(stage)
    with (stage / "transform.stdout.txt").open("x") as stdout, (stage / "transform.stderr.txt").open("x") as stderr:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from kg_microbe.transform_utils.bactotraits import bactotraits as module
            from kg_microbe.utils import mapping_file_utils
            from kg_microbe.utils.producer_audits import verify_producer_audits

            require(Path(module.__file__).resolve().is_relative_to(code_root), "Wrong imported transform checkout")
            module.BACTOTRAITS_TMP_DIR = temporary / "bactotraits"
            module.BACDIVE_TMP_DIR = stage / "lookup"
            module.CUSTOM_CURIES_YAML_FILE = stage / "mappings/custom_curies.yaml"
            mapping_file_utils.LOCAL_METPO_ALIAS_OVERRIDES_PATH = stage / "mappings/metpo_alias_mappings.tsv"
            bind_staged_prefix_registry(stage)
            producer = module.BactoTraitsTransform(stage / "raw", stage / "transformed")
            authority = ReadOnlyNCBILabels(
                Path(plan["authority"]["database_metadata"]["path"]), plan["authority"]["queried_statements"]
            )
            producer.ncbi_impl = authority
            producer.run(show_status=False)
            producer.verify_consumed_inputs()
            verify_producer_audits(producer)
    edges = graph_rows(producer.output_edge_file)
    nodes = graph_rows(producer.output_node_file)
    target_edges = [row for row in edges if row["subject"] == SUBJECT]
    other_edges = Counter(json.dumps(row, sort_keys=True) for row in edges if row["subject"] != SUBJECT)
    audit_rows = []
    if args.mode == "baseline":
        require(any(row["object"] == "METPO:1000703" for row in target_edges), "Baseline target edge absent")
        require(any(row["id"] == SUBJECT and row["name"] == LABEL for row in nodes), "Baseline real label absent")
        require(not producer.REQUIRED_AUDIT_FILES, "Baseline unexpectedly has quarantine audits")
    else:
        require(not target_edges, "Quarantined source row still emits taxon assertions")
        require(producer.REQUIRED_AUDIT_FILES == (AUDIT,), "Candidate audit declaration differs")
        audit_rows = graph_rows(producer.output_dir / AUDIT)
        require(len(audit_rows) == 1, "Candidate must persist exactly one quarantine disposition")
        item = audit_rows[0]
        require(
            item["bacdive_id"] == "17851"
            and item["ncbitaxon_id"] == SUBJECT
            and item["row_sha256"] == ROW_SHA
            and item["source_data_row"] == "1"
            and item["reviewed_source_data_row"] == "8521"
            and item["source_sha256"] == digest(plan["staged"]["raw/BactoTraits_databaseV2_Jun2022.csv"])
            and item["reviewed_source_sha256"] == SOURCE_SHA
            and item["policy_sha256"] == plan["policy"]["sha256"]
            and item["disposition"] == "quarantine_mixed_strain_row"
            and json.loads(item["raw_row_json"]) == plan["row"],
            "Candidate audit does not bind the actual raw row",
        )
        require(
            other_edges == Counter(json.dumps(row, sort_keys=True) for row in baseline[2] if row["subject"] != SUBJECT),
            "Unrelated/global combo edges changed",
        )
    verify_runtime_inputs(plan)
    if plan["policy"]:
        require(digest(bytes_at(Path(plan["policy"]["path"]))) == plan["policy"]["sha256"], "Policy changed")
    require(database_stat(Path(args.ncbi_db)) == plan["authority"]["database_metadata"], "NCBI DB metadata changed")
    require(
        authority_rows(Path(args.ncbi_db)) == plan["authority"]["queried_statements"], "NCBI authority rows changed"
    )
    artifacts = {}
    for path in sorted(stage.rglob("*")):
        safe_path(path)
        if path.is_file():
            raw = path.read_bytes()
            require(stat.S_IMODE(path.stat().st_mode) == 0o600, "Replay artifact is not private")
            artifacts[str(path.relative_to(stage))] = {"sha256": digest(raw), "bytes": len(raw)}
    code_inputs = plan["code_inputs"]
    for name, expected in code_inputs.items():
        require(digest(bytes_at(code_root / name)) == expected, "Implementation changed during replay")
    for name, loaded in sorted(sys.modules.items()):
        path = getattr(loaded, "__file__", None)
        if name.startswith("kg_microbe") and path and Path(path).suffix == ".py":
            source = Path(path).resolve()
            require(source.is_relative_to(code_root), "Mixed KG-Microbe implementation checkouts")
            require(
                code_inputs.get(str(source.relative_to(code_root))) == digest(source.read_bytes()),
                "Imported implementation was not pinned before replay",
            )
    result = {
        "profile": PROFILE,
        "mode": args.mode,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": plan["revision"],
        "code_root": str(code_root),
        "code_inputs": code_inputs,
        "shared_inputs": plan["shared"],
        "artifacts": artifacts,
        "target_edges": target_edges,
        "target_edge_count": len(target_edges),
        "all_edge_count": len(edges),
        "node_count": len(nodes),
        "quarantine_rows": len(audit_rows),
        "authority_label_queries": authority.lookups,
        "consumed_inputs": producer.consumed_input_snapshots,
        "producer_audits": producer.producer_audit_snapshots,
        "provider_calls": 0,
        "finalization_run": False,
        "published_release_verified": False,
        "scientific_claim_resolved": False,
        "scope": "One original source row through actual run(); no finalization, merge or wider source claims.",
    }
    if baseline:
        result["baseline_receipt"] = {"path": str(baseline[0]), "sha256": baseline[1]}
        result["removed_target_edge_count"] = sum(row["subject"] == SUBJECT for row in baseline[2])
        result["unrelated_edges_unchanged"] = True
    write_new(stage / "receipt.json", json_bytes(result))
    require(json.loads((stage / "receipt.json").read_text()) == result, "Receipt readback differs")
    return {
        "receipt": str(stage / "receipt.json"),
        "mode": args.mode,
        "target_edges": len(target_edges),
        "quarantine_rows": len(audit_rows),
        "provider_calls": 0,
        "finalization_run": False,
    }


def main():
    """Separate read-only planning from one explicitly requested live replay unit."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--mode", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--code-root", type=Path)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, default=CANONICAL)
    parser.add_argument("--ncbi-db", type=Path, default=CANONICAL / "data/raw/ncbitaxon.db")
    parser.add_argument("--baseline-receipt", type=Path)
    args = parser.parse_args()
    csv.field_size_limit(16 * 1024 * 1024)
    plan = prepare(args)
    if args.plan:
        if args.mode == "candidate":
            baseline_data(args, plan["shared"])
        result = {
            "action": "plan",
            "ready": True,
            "writes": 0,
            "provider_calls": 0,
            "mode": args.mode,
            "stage": str(plan["stage"]),
            "code_root": str(plan["code_root"]),
            "git_revision": plan["revision"],
            "shared_inputs": plan["shared"],
            "authority": plan["authority"],
            "scope": "Single-row transform before finalization",
        }
    else:
        result = run(args, plan)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
