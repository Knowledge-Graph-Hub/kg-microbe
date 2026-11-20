"""Capture a complete historical KG source closure without producing or admitting a release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

SOURCES = ("mediadive", "metatraits", "metatraits_gtdb", "microbedecoder")
UPSTREAM = {
    "mediadive": ("ontologies", "bacdive"),
    "metatraits": ("ontologies",),
    "metatraits_gtdb": ("ontologies", "gtdb"),
    "microbedecoder": ("lpsn", "gold", "gtdb", "ontologies"),
    "bacdive": ("ontologies",),
    "lpsn": ("ontologies", "gtdb"),
    "gold": ("ontologies", "ontologies_stubs"),
    "gtdb": ("ontologies",),
    "ontologies": (),
    "ontologies_stubs": ("ontologies",),
}
PRODUCTS = {"ingredient_mappings.sssom.tsv", "withheld_mappings.sssom.tsv", "mapping-dispositions.tsv"}
PIN_PATH = "mappings/mim_reviewed_release.json"
UNIFIED_PATH = "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
LEDGERS = {"full-row-ledger.json": 5740, "full-row-ledger.tsv": 5740, "full-node-ledger.json": 507}
RESERVED = {
    "source-manifest.json",
    "closure-audit.json",
    "evidence/parent-source-manifest.json",
    "evidence/row-reconciliation.json",
    "evidence/row-reconciliation",
}


def require(value, message):
    """Stop before publication whenever a selected binding fails."""
    if not value:
        raise ValueError(message)


def digest(value, length=64):
    """Require a complete immutable SHA declaration."""
    require(isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value), "invalid digest")
    return value


def relative(value):
    """Refuse aliases, traversal, ambiguous separators and control characters."""
    require(isinstance(value, str) and value, "invalid relative member")
    path = Path(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and ".." not in path.parts
        and value != "."
        and "\\" not in value
        and all(ord(c) >= 32 for c in value),
        "unsafe relative member: " + value,
    )
    return path


def physical(path, directory=False):
    """Require an absolute physical input without symlink ancestors."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(strict=True), "unresolved or aliased path")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink input")
    require(path.is_dir() if directory else path.is_file(), "missing or nonregular input: " + str(path))
    return path


def identity(path):
    """Capture file identity before and after bounded streaming reads."""
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def unique(pairs):
    """Reject duplicate JSON keys instead of silently replacing evidence."""
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def parse(raw):
    """Decode evidence without executing source code."""
    return json.loads(raw, object_pairs_hook=unique)


def git(root, *args):
    """Read the selected checkout with ambient Git configuration disabled."""
    root = physical(root, directory=True)
    locator = root / ".git"
    require(not locator.is_symlink() and (locator.is_file() or locator.is_dir()), "missing owned Git locator")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(  # noqa: S603 - fixed read-only commands, validated full revision
        ["git", "--no-optional-locks", "--no-replace-objects", *args],  # noqa: S607
        cwd=root,
        env=env,
        timeout=30,
    )


def head(root):
    """Verify physical checkout ownership before reading its revision."""
    require(Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).samefile(root), "Git root differs")
    return git(root, "rev-parse", "HEAD").decode().strip()


class Capture:
    """Read selected bytes and create independent, exclusive copies only."""

    def __init__(self, output):
        """Reserve a new directory without replacing existing evidence."""
        self.output = output
        output.mkdir()
        self.files = {}
        self.reads = {}
        self.copies = {}
        self.graphs = {}
        self.created = {}

    def read(self, path, expected=None):
        """Read small metadata while retaining its physical identity."""
        path = physical(path)
        before = identity(path)
        raw = path.read_bytes()
        require(identity(path) == before, "input changed during metadata read")
        actual = hashlib.sha256(raw).hexdigest()
        if expected is not None:
            require(actual == digest(expected), "metadata hash differs: " + str(path))
        previous = self.reads.setdefault(str(path), before)
        require(previous == before, "input changed between reads")
        return raw

    def copy(self, path, name, expected, size=None, *, graph=False):
        """Hash all bytes while copying, preserving the source and detecting drift."""
        path = physical(path)
        name = relative(name).as_posix()
        expected = digest(expected)
        before = identity(path)
        require(self.reads.get(str(path), before) == before, "input changed between reads")
        destination = self.output / name
        exists = name in self.files
        if not exists:
            destination.parent.mkdir(parents=True, exist_ok=True)
            physical(destination.parent, directory=True)
        h = hashlib.sha256()
        count = 0
        output = None
        lines, columns = 0, []
        try:
            if not exists:
                output = destination.open("xb")
            with path.open("rb") as source:
                blocks = source if graph else iter(lambda: source.read(1024 * 1024), b"")
                for block in blocks:
                    if graph:
                        values = block.rstrip(b"\r\n").decode("utf-8").split("\t")
                        if lines == 0:
                            columns = values
                            require(columns and len(columns) == len(set(columns)), "invalid graph header")
                        else:
                            require(len(values) == len(columns), "malformed graph row")
                        lines += 1
                    h.update(block)
                    count += len(block)
                    if output is not None:
                        output.write(block)
        finally:
            if output is not None:
                output.close()
        require(identity(path) == before, "input changed during copy")
        require(h.hexdigest() == expected, "input hash differs: " + str(path))
        require(size is None or type(size) is int and count == size, "input byte count differs")
        metadata = {"bytes": count, "sha256": h.hexdigest()}
        require(not exists or self.files[name] == metadata, "conflicting closure member")
        require(identity(destination)[:2] != before[:2], "copy aliases source")
        if graph:
            require(lines > 0, "missing graph header")
            self.graphs[name] = {**metadata, "row_count": lines - 1, "columns": columns}
        self.files[name] = metadata
        self.reads[str(path)] = before
        record = self.copies.setdefault(
            name,
            {
                **metadata,
                "source": str(path),
                "copy": identity(destination),
                "source_observations": [],
            },
        )
        record["source_observations"].append({"source": str(path), "before": before, "after": identity(path)})
        return metadata

    def snapshot(self, root, name, expected, size=None, *, graph=False):
        """Capture a current root-relative input under the existing snapshot layout."""
        return self.copy(root / relative(name), "snapshots/" + name, expected, size, graph=graph)

    def write(self, name, value):
        """Write one new evidence document exclusively and register its bytes."""
        path = self.output / relative(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        with path.open("xb") as stream:
            stream.write(raw)
        self.files[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self.created[name] = identity(path)
        return self.files[name]

    def unchanged(self):
        """Keep input and output physical identities stable through publication checks."""
        for name, before in self.reads.items():
            require(identity(physical(Path(name))) == before, "input changed before publication")
        for name, before in self.created.items():
            require(identity(physical(self.output / name)) == before, "created evidence changed")
        for name, record in self.copies.items():
            require(identity(physical(self.output / name)) == record["copy"], "copied member changed")

    def verify(self):
        """Independently hash retained output bytes and bracket that work with identity guards."""
        self.unchanged()
        verified = {}
        for name, expected in self.files.items():
            path = physical(self.output / name)
            before = identity(path)
            h = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                    size += len(block)
            require(identity(path) == before, "destination changed during readback")
            require({"bytes": size, "sha256": h.hexdigest()} == expected, "destination bytes or hash differ: " + name)
            verified[name] = {**expected, "before": before, "after": identity(path)}
        self.unchanged()
        return verified


def metadata(value):
    """Require the historical byte-and-hash member shape."""
    require(isinstance(value, dict) and set(value) == {"bytes", "sha256"}, "invalid member metadata")
    require(type(value["bytes"]) is int and value["bytes"] >= 0, "invalid member size")
    digest(value["sha256"])
    return value


def dependency_bindings(value, root, bindings, location="receipt"):
    """Collect every nested exact input declaration, retaining all declaration roles."""
    if isinstance(value, dict):
        if "sha256" in value:
            for key in ("path", "resolved", "lexical_path", "locator"):
                if key not in value:
                    continue
                path = Path(value[key])
                require(path.is_absolute() and path.is_relative_to(root), "dependency outside selected root")
                name = relative(path.relative_to(root).as_posix()).as_posix()
                pin = digest(value["sha256"])
                existing = bindings.setdefault(name, {"sha256": pin, "declarations": []})
                require(existing["sha256"] == pin, "conflicting dependency pins")
                existing["declarations"].append(location + "." + key)
        for key, item in value.items():
            dependency_bindings(item, root, bindings, location + "." + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            dependency_bindings(item, root, bindings, location + f"[{index}]")


def prior_release(capture, root, revision, historical):
    """Bind only the prior consumed release, independent of future release canaries."""
    consumed = historical["consumed_reviewed"]
    directory = relative(consumed["directory"])
    proposed = (directory.parent / "proposed-immutable-pin-r1.json").as_posix()
    require(proposed in historical["files"], "missing historical proposed release pin")
    old_raw = capture.read(capture.output / proposed, historical["files"][proposed]["sha256"])
    current = capture.read(root / PIN_PATH)
    require(current == old_raw == git(root, "show", revision + ":" + PIN_PATH), "prior committed release pin differs")
    pin = parse(current)
    require(pin.get("schema_version") == 2 and pin.get("mode") == "candidate_only", "unsupported prior release pin")
    require(
        pin.get("source_commit") == consumed["source_commit"] == historical.get("mim_revision"),
        "prior MIM commit differs",
    )
    require(pin.get("origin") == "immutable_commit_export", "unsupported prior release origin")
    require(
        pin["source_archive"]["url"]
        == "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/"
        + digest(consumed["source_commit"], 40),
        "prior archive commit differs",
    )
    require(set(consumed["files"]) == PRODUCTS | {"manifest.json"}, "incomplete prior partitions")
    require(
        pin["manifest_sha256"] == consumed["manifest_sha256"] == consumed["files"]["manifest.json"],
        "prior manifest pin differs",
    )
    require(pin["files"] == {name: consumed["files"][name] for name in PRODUCTS}, "prior product pins differ")
    for name, expected in consumed["files"].items():
        member_name = (directory / relative(name)).as_posix()
        require(capture.files[member_name]["sha256"] == expected, "prior consumed member differs")
    manifest = parse(capture.read(capture.output / directory / "manifest.json", pin["manifest_sha256"]))
    require(manifest.get("files") == pin["files"], "prior manifest products differ")
    require(manifest.get("source_sssom") == "mappings/ingredient_mappings.sssom.tsv", "prior source SSSOM differs")
    require(manifest.get("semantic_status") == "PASS_SUPPORTED_SUBSET", "prior export status differs")
    for field in ("source_sha256", "review_sha256"):
        digest(manifest[field])
    capture.snapshot(root, PIN_PATH, hashlib.sha256(current).hexdigest(), len(current))
    require(
        capture.files["snapshots/mappings/ingredient_mappings.sssom.tsv"]["sha256"]
        == pin["files"]["ingredient_mappings.sssom.tsv"],
        "consumed supported input differs",
    )
    require("snapshots/" + UNIFIED_PATH in historical["files"], "missing historical unified pin")
    return {
        "pin": capture.files["snapshots/" + PIN_PATH],
        "source_commit": pin["source_commit"],
        "supported": capture.files["snapshots/mappings/ingredient_mappings.sssom.tsv"],
        "unified": capture.files["snapshots/" + UNIFIED_PATH],
        "scope": "prior_consumed_input_only",
    }


def verify_upstream_markers(capture, root):
    """Verify every captured dependency marker recursively, including ontology stubs."""
    verified, active = {}, set()

    def visit(source):
        """Check a marker only after recursively checking its exact upstream markers."""
        if source in verified:
            return verified[source]
        require(source in UPSTREAM and source not in active, "unknown or cyclic fingerprint dependency")
        active.add(source)
        name = "data/transformed/" + source + "/source_fingerprint.json"
        raw = capture.read(root / name)
        capture.snapshot(root, name, hashlib.sha256(raw).hexdigest(), len(raw))
        marker = parse(raw)
        h = hashlib.sha256()
        for dependency in sorted(UPSTREAM[source]):
            upstream = visit(dependency)
            h.update(dependency.encode() + b"\0" + json.dumps(upstream, sort_keys=True).encode() + b"\0")
        require(marker.get("upstream") == h.hexdigest(), "recursive upstream fingerprint changed: " + source)
        verified[source] = marker
        active.remove(source)
        return marker

    for source in SOURCES:
        visit(source)
    return {
        source: capture.files["snapshots/data/transformed/" + source + "/source_fingerprint.json"]
        for source in verified
    }


def ledger_rows(path, expected):
    """Count bounded JSON-array entries or quoted TSV rows without loading a complete ledger."""
    path = physical(path)
    before = identity(path)
    count = 0
    with path.open(encoding="utf-8", newline="") as stream:
        if path.suffix == ".tsv":
            previous_limit = csv.field_size_limit()
            try:
                csv.field_size_limit(sys.maxsize)
                reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_MINIMAL, strict=True)
                fields = next(reader, None)
                require(fields and len(fields) == len(set(fields)), "invalid row ledger header")
                for row in reader:
                    require(len(row) == len(fields), "malformed row ledger")
                    count += 1
                    require(count <= expected, "too many row ledger entries")
            finally:
                csv.field_size_limit(previous_limit)
        else:
            require(path.suffix == ".json", "unsupported row ledger format")
            decoder = json.JSONDecoder(object_pairs_hook=unique)
            buffer = ""
            ended = False

            def more():
                """Read one bounded text chunk while retaining an incomplete JSON record."""
                nonlocal buffer, ended
                chunk = stream.read(65536)
                ended = not chunk
                buffer += chunk
                return bool(chunk)

            def token():
                """Find the next non-whitespace token without loading the entire ledger."""
                nonlocal buffer
                buffer = buffer.lstrip(" \t\r\n")
                while not buffer and not ended:
                    more()
                    buffer = buffer.lstrip(" \t\r\n")
                require(buffer, "truncated JSON ledger")

            token()
            require(buffer[0] == "[", "JSON ledger must be an array")
            buffer = buffer[1:]
            need_value, allow_end = True, True
            while True:
                token()
                if buffer[0] == "]":
                    require(allow_end, "trailing comma in JSON ledger")
                    buffer = buffer[1:]
                    require(not buffer.strip(" \t\r\n"), "trailing JSON ledger data")
                    while more():
                        require(not buffer.strip(" \t\r\n"), "trailing JSON ledger data")
                        buffer = ""
                    break
                if not need_value:
                    require(buffer[0] == ",", "missing JSON ledger delimiter")
                    buffer = buffer[1:]
                    need_value, allow_end = True, False
                    continue
                while True:
                    try:
                        value, end = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        require(more(), "malformed JSON ledger")
                    else:
                        # A JSON number can be extended by the next chunk; do not
                        # accept it before a delimiter or EOF has actually arrived.
                        if (
                            not ended
                            and isinstance(value, (int, float))
                            and (end == len(buffer) or re.fullmatch(r"[.eE+0-9-]+", buffer[end:]))
                        ):
                            more()
                            continue
                        buffer = buffer[end:]
                        break
                count += 1
                require(count <= expected, "too many row ledger entries")
                need_value, allow_end = False, True
    require(identity(path) == before, "row ledger changed while counting")
    return count


def collect(
    *, root, revision, historical_manifest, historical_sha256, row_reconciliation, row_reconciliation_sha256, output
):
    """Expand a pinned historical snapshot only after every selected input verifies."""
    root = physical(root, directory=True)
    historical_manifest = physical(historical_manifest)
    row_reconciliation = physical(row_reconciliation)
    digest(revision, 40)
    require(head(root) == revision, "selected revision differs")
    output = Path(output)
    require(output.is_absolute() and not output.exists() and not output.is_symlink(), "output must not exist")
    physical(output.parent, directory=True)
    require(
        not output.is_relative_to(root) and not output.is_relative_to(historical_manifest.parent),
        "output is inside an input root",
    )
    capture = Capture(output)
    historical_raw = capture.read(historical_manifest, historical_sha256)
    historical = parse(historical_raw)
    require(historical.get("schema_version") == 1, "unsupported historical manifest")
    require(
        historical.get("upstream_root") == str(root) and historical.get("upstream_revision") == revision,
        "historical root or revision differs",
    )
    require(isinstance(historical.get("files"), dict) and historical["files"], "empty historical closure")
    for name in historical["files"]:
        relative(name)
        require(
            not any(
                name == reserved or name.startswith(reserved + "/") or reserved.startswith(name + "/")
                for reserved in RESERVED
            ),
            "reserved historical member: " + name,
        )
    snapshot_count = 0
    for name, declaration in historical["files"].items():
        relative(name)
        declaration = metadata(declaration)
        capture.copy(historical_manifest.parent / name, name, declaration["sha256"], declaration["bytes"])
        if name.startswith("snapshots/"):
            capture.snapshot(root, name[len("snapshots/") :], declaration["sha256"], declaration["bytes"])
            snapshot_count += 1
    prior = prior_release(capture, root, revision, historical)
    bindings, members, receipts, fingerprints = {}, {}, {}, {}
    for source in SOURCES:
        base = "data/transformed/" + source + "/"
        receipt_name, marker_name = base + "source_finalization.json", base + "source_fingerprint.json"
        require("snapshots/" + receipt_name in historical["files"], "missing selected historical finalization")
        receipt = parse(capture.read(root / receipt_name))
        require(
            receipt.get("version") == 2 and receipt.get("source") == source and receipt.get("tsv_quoting") == "none",
            "unsupported source finalization",
        )
        require(set(receipt.get("members", {})) == {"nodes.tsv", "edges.tsv"}, "incomplete selected graph members")
        require(receipt.get("audit_members"), "missing selected audit closure")
        receipts[source] = capture.files["snapshots/" + receipt_name]
        for group in ("members", "audit_members", "producer_audit_members"):
            for name, declaration in receipt.get(group, {}).items():
                relative(name)
                require(len(Path(name).parts) == 1, "nonlocal generated member")
                declaration = metadata(declaration)
                key = base + name
                capture.snapshot(root, key, declaration["sha256"], declaration["bytes"], graph=group == "members")
                if group == "members":
                    require(
                        capture.graphs["snapshots/" + key]["row_count"]
                        == receipt["summaries"]["rows"][name.removesuffix(".tsv")],
                        "graph row count differs from finalization",
                    )
                previous = members.setdefault(key, {**declaration, "roles": []})
                require(
                    all(previous[k] == declaration[k] for k in ("bytes", "sha256")), "conflicting member declarations"
                )
                previous["roles"].append(group)
        dependency_bindings(receipt, root, bindings, source)
        marker = parse(capture.read(root / marker_name))
        expected = sorted(Path(x["path"]).relative_to(root).as_posix() for x in receipt["inputs"])
        require(marker.get("finalization_inputs") == expected, "fingerprint input declarations differ")
        require(
            marker.get("code") == receipt["producer_code"]["fingerprint"]
            and marker.get("shared") == receipt["finalizer_code"],
            "fingerprint code binding differs",
        )
        fingerprints[source] = {"marker": marker, "path": marker_name}
    for name, binding in bindings.items():
        capture.snapshot(root, name, binding["sha256"])
    for item in fingerprints.values():
        marker = item["marker"]
        h = hashlib.sha256()
        for name in sorted(set(marker["finalization_inputs"])):
            h.update(name.encode() + b"\0" + bytes.fromhex(capture.files["snapshots/" + name]["sha256"]) + b"\0")
        require(h.hexdigest() == marker["finalization_data"], "actual finalization dependency digest differs")
    upstream_markers = verify_upstream_markers(capture, root)
    proof = parse(capture.read(row_reconciliation, row_reconciliation_sha256))
    validate_row_proof(proof, root, revision, historical_sha256, capture.graphs)
    for name, declaration in proof["outputs"].items():
        require(len(relative(name).parts) == 1, "nonlocal reconciliation output")
        capture.copy(
            row_reconciliation.parent / name,
            "evidence/row-reconciliation/" + name,
            declaration["sha256"],
            declaration["bytes"],
        )
        observed = ledger_rows(capture.output / "evidence/row-reconciliation" / name, LEDGERS[name])
        require(observed == declaration["row_count"], "parsed row ledger count differs")
    capture.copy(historical_manifest, "evidence/parent-source-manifest.json", historical_sha256)
    capture.copy(row_reconciliation, "evidence/row-reconciliation.json", row_reconciliation_sha256)
    inventory = []
    for path in sorted((root / "data/transformed").rglob("*source_finalization.json")):
        raw = capture.read(path)
        record = parse(raw)
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source": record.get("source"),
                "version": record.get("version"),
                "declared_graph_members": record.get("members"),
                "declared_rows": record.get("summaries", {}).get("rows"),
                "selection": "selected_chemical_candidate"
                if path.parent.name in SOURCES
                else "diagnostic_only_unselected",
            }
        )
    audit = {
        "schema_version": 1,
        "status": "HISTORICAL_CLOSURE_ONLY_NOT_RELEASE_ADMISSION",
        "selected_sources": list(SOURCES),
        "source_inventory": inventory,
        "inventory_limit": "Unselected graph byte identities are declarations only; no additional source admission",
        "prego_habitat": "diagnostic_only_unselected",
        "other_sources": "excluded_from_chemical_selection",
        "historical_files": len(historical["files"]),
        "historical_current_snapshots": snapshot_count,
        "members": members,
        "dependencies": bindings,
        "finalization_receipts": receipts,
        "upstream_fingerprint_markers": upstream_markers,
        "prior_consumed_release": prior,
        "copy_evidence": capture.copies,
        "limits": [
            "No transform, fresh production, full scientific admission, release or future pin promotion",
            "External row proof is separate pinned evidence; inventory is not medium-presence authority",
        ],
    }
    capture.write("closure-audit.json", audit)
    destination_verification = capture.verify()
    require(head(root) == revision, "selected revision changed before publication")
    result = deepcopy(historical)
    result.update(
        captured_at=datetime.now(timezone.utc).isoformat(),
        destination_verification=destination_verification,
        files=deepcopy(capture.files),
        scope="Four chemical candidates; historical source closure only; PREGO diagnostic-only; no release admission",
        parent_manifest={"path": "evidence/parent-source-manifest.json", "sha256": historical_sha256},
        row_reconciliation={"path": "evidence/row-reconciliation.json", "sha256": row_reconciliation_sha256},
        closure_audit={"path": "closure-audit.json", "sha256": capture.files["closure-audit.json"]["sha256"]},
    )
    capture.write("source-manifest.json", result)
    return result


def validate_row_proof(proof, root, revision, historical_sha256, graphs):
    """Require separately selected row evidence to describe these exact captured graph bytes."""
    require(
        proof.get("schema_version") == 1 and proof.get("status") == "PASS_HISTORICAL_SOURCE_ROW_RECONCILIATION",
        "row proof status differs",
    )
    require(
        proof.get("historical_manifest_sha256") == historical_sha256
        and proof.get("kgm_root") == str(root)
        and proof.get("kgm_revision") == revision,
        "row proof source selection differs",
    )
    require(proof.get("selected_sources") == list(SOURCES), "row proof chemical scope differs")
    require(
        proof.get("counts")
        == {"kg_source_ids": 507, "provider_cases": 549, "kg_occurrences": 5740, "shared_metatraits_gtdb_ids": 42},
        "row proof bounded counts differ",
    )
    require(
        proof.get("provider_counts")
        == {
            "mediadive": {"cases": 415, "occurrences": 5332},
            "metatraits": {"cases": 82, "occurrences": 120},
            "metatraits_gtdb": {"cases": 42, "occurrences": 63},
            "microbedecoder": {"cases": 10, "occurrences": 225},
        },
        "row proof provider counts differ",
    )
    for key in ("all_native_kg_rows_accounted", "exact_combined_projection", "all_inputs_unchanged"):
        require(proof.get(key) is True, "row proof reconciliation check failed")
    require(
        proof.get("production_admission") is False and proof.get("scientific_approval") is False,
        "row proof grants unsupported authority",
    )
    require(isinstance(proof.get("graph_members"), dict), "invalid row proof graph map")
    for value in proof["graph_members"].values():
        require(
            isinstance(value, dict) and set(value) == {"sha256", "bytes", "row_count", "columns"},
            "invalid row proof graph metadata",
        )
        metadata({key: value[key] for key in ("bytes", "sha256")})
        require(
            type(value["row_count"]) is int
            and value["row_count"] >= 0
            and isinstance(value["columns"], list)
            and all(isinstance(x, str) for x in value["columns"]),
            "invalid row proof graph shape",
        )
    require(
        proof.get("graph_members") == {name.removeprefix("snapshots/"): value for name, value in graphs.items()},
        "row proof graph closure differs",
    )
    require(
        isinstance(proof.get("inputs_before"), dict)
        and proof["inputs_before"]
        and proof.get("inputs_before") == proof.get("inputs_after"),
        "row proof input guard differs",
    )
    for value in proof["inputs_before"].values():
        metadata(value)
    require(
        isinstance(proof.get("outputs"), dict) and set(proof["outputs"]) == set(LEDGERS),
        "row proof supporting ledger closure differs",
    )
    for name, value in proof["outputs"].items():
        require(
            isinstance(value, dict) and set(value) == {"bytes", "sha256", "row_count"}, "invalid row ledger metadata"
        )
        metadata({key: value[key] for key in ("bytes", "sha256")})
        require(type(value["row_count"]) is int and value["row_count"] == LEDGERS[name], "invalid row ledger count")


def main():
    """Collect a new snapshot with explicit independently selected evidence pins."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "root",
        "revision",
        "historical-manifest",
        "historical-sha256",
        "row-reconciliation",
        "row-reconciliation-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = collect(
        root=Path(args.root),
        revision=args.revision,
        historical_manifest=Path(args.historical_manifest),
        historical_sha256=args.historical_sha256,
        row_reconciliation=Path(args.row_reconciliation),
        row_reconciliation_sha256=args.row_reconciliation_sha256,
        output=Path(args.output),
    )
    print(
        json.dumps(
            {
                "manifest": str(Path(args.output) / "source-manifest.json"),
                "files": len(result["files"]),
                "status": "HISTORICAL_CLOSURE_ONLY_NOT_RELEASE_ADMISSION",
            }
        )
    )


if __name__ == "__main__":
    main()
