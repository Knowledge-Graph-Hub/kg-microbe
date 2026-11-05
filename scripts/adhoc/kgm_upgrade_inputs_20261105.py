#!/usr/bin/env python3
"""
Acquire independent upgrade candidates for the approved 2026-11-05 rebuild.

Inputs: fixed official Biolink 4.4.6, ROBOT 1.9.11, and Rhea 143 HTTPS URLs.
Outputs: new candidate files, HTTP evidence, and measured identities beneath
data/rebuild-evidence/20261105/upgrades/candidates. Default operation is a read-only
plan; execute downloads candidates without activating raw inputs or changing pins.
Acquisition receipts establish downloaded bytes, not scientific release admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "data/rebuild-evidence/20261105/upgrades/candidates"
CURL = "/usr/bin/curl"
ROBOT_SHA256 = "53cd275c8e4c0dad1fc2c1c34174876795cd7d6b6926e1444adcbb0cb3c7ab26"
DOWNLOADS = (
    {
        "key": "biolink-model",
        "url": "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/biolink-model.yaml",
        "relative_path": "biolink446/biolink-model.yaml",
    },
    {
        "key": "biolink-predicates",
        "url": "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/predicate_mapping.yaml",
        "relative_path": "biolink446/predicate_mapping.yaml",
    },
    {
        "key": "biolink-attributes",
        "url": "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/attributes.yaml",
        "relative_path": "biolink446/attributes.yaml",
    },
    {
        "key": "robot-jar",
        "url": "https://github.com/ontodev/robot/releases/download/v1.9.11/robot.jar",
        "relative_path": "robot1911/robot.jar",
        "expected_sha256": ROBOT_SHA256,
    },
    {
        "key": "robot-wrapper",
        "url": "https://raw.githubusercontent.com/ontodev/robot/v1.9.11/bin/robot",
        "relative_path": "robot1911/robot",
    },
    {
        "key": "rhea-archive",
        "url": "https://ftp.expasy.org/databases/rhea/old_releases/143.tar.bz2",
        "relative_path": "rhea143/143.tar.bz2",
    },
)
RHEA_MEMBERS = {
    "143/tsv/rhea-directions.tsv": "rhea-directions.tsv",
    "143/rdf/rhea.rdf.gz": "rhea.rdf.gz",
}


def require(condition: bool, message: str) -> None:
    """Refuse incomplete acquisition or unsafe publication."""
    if not condition:
        raise ValueError(message)


def now() -> str:
    """Return an explicit UTC timestamp for retained evidence."""
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    """Hash complete bytes in bounded blocks."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def publish_new(partial: Path, destination: Path) -> None:
    """Atomically publish a new name without replacing any existing evidence."""
    require(partial.parent == destination.parent, "Atomic publication requires the same directory")
    status = partial.lstat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1, "Partial must be an independent regular file")
    # link() is an atomic no-replace operation; the temporary alias is removed
    # immediately, leaving one candidate inode with one name. No raw file is linked.
    os.link(partial, destination, follow_symlinks=False)
    partial.unlink()


def write_json(path: Path, payload: object) -> None:
    """Flush a complete receipt before publishing its new name atomically."""
    partial = path.with_name(path.name + ".partial")
    require(not os.path.lexists(path), f"Refusing to replace evidence: {path}")
    with partial.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    publish_new(partial, path)


def validate_layout() -> None:
    """Reject existing candidates and symlinked paths before any acquisition writes."""
    require(CANDIDATES.is_relative_to(ROOT), "Candidates must be inside the owned checkout")
    require(CANDIDATES.resolve().is_relative_to(ROOT), "Resolved candidates escape the owned checkout")
    for path in (CANDIDATES, *CANDIDATES.parents):
        if path == ROOT:
            break
        require(not path.is_symlink(), f"Candidate path traverses a symlink: {path}")
    require(not os.path.lexists(CANDIDATES), f"Refusing to reuse candidate directory: {CANDIDATES}")


def plan() -> dict:
    """Describe the fixed acquisition without creating files or contacting upstreams."""
    validate_layout()
    return {
        "worktree": str(ROOT),
        "candidate_directory": str(CANDIDATES),
        "downloads": list(DOWNLOADS),
        "rhea_members": RHEA_MEMBERS,
        "workers": 3,
        "curl": CURL,
        "retry_count": 3,
        "activates_raw_inputs": False,
    }


def download(candidate_dir: Path, spec: dict) -> dict:
    """Download one candidate through curl and retain headers, metadata, and byte identity."""
    relative = PurePosixPath(spec["relative_path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe candidate relative path")
    require(urlsplit(spec["url"]).scheme == "https", "Candidate source must use HTTPS")
    destination = candidate_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not os.path.lexists(destination), f"Refusing to replace candidate: {destination}")
    partial = destination.with_name(destination.name + ".partial")
    with partial.open("xb"):
        pass
    evidence = candidate_dir / "http" / spec["key"]
    evidence.mkdir(parents=True, exist_ok=False)
    headers = evidence / "headers.txt"
    metadata_path = evidence / "curl-metadata.json"
    command = [
        CURL,
        "--disable",
        "--fail",
        "--location",
        "--retry",
        "3",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--connect-timeout",
        "30",
        "--silent",
        "--show-error",
        "--dump-header",
        str(headers),
        "--output",
        str(partial),
        "--write-out",
        "%{json}\n",
        spec["url"],
    ]
    result = {"source_url": spec["url"], "candidate": str(destination), "started": now()}
    write_json(evidence / "command.json", {"argv": command, "started": result["started"]})
    try:
        with metadata_path.open("xb") as metadata_stream, (evidence / "stderr.log").open("xb") as errors:
            process = subprocess.run(  # noqa: S603 - fixed curl and official URLs, no shell
                command, stdout=metadata_stream, stderr=errors, stdin=subprocess.DEVNULL, check=False
            )
        result["curl_exit_code"] = process.returncode
        result["bytes"] = partial.stat().st_size
        result["sha256"] = digest(partial)
        require(process.returncode == 0, f"curl failed for {spec['key']}: exit {process.returncode}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        result["actual_url"] = metadata.get("url_effective")
        result["http_code"] = metadata.get("http_code")
        require(urlsplit(result["actual_url"] or "").scheme == "https", "Effective URL is not HTTPS")
        require(result["http_code"] == 200, f"Expected full HTTP 200 response for {spec['key']}")
        require(result["bytes"] > 0, f"Downloaded candidate is empty: {spec['key']}")
        require(metadata.get("size_download") == result["bytes"], "curl byte count differs from persisted bytes")
        require(headers.is_file() and headers.stat().st_size > 0, "HTTP response headers were not persisted")
        result["headers_sha256"] = digest(headers)
        if spec.get("expected_sha256"):
            result["expected_sha256"] = spec["expected_sha256"]
            require(result["sha256"] == spec["expected_sha256"], f"Official SHA-256 mismatch: {spec['key']}")
        publish_new(partial, destination)
        result.update(status="downloaded", finished=now())
        write_json(evidence / "receipt.json", result)
        return result
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}", finished=now())
        write_json(evidence / "failure.json", result)
        raise


def extract_rhea(archive_path: Path, output_dir: Path) -> dict:
    """Stream exactly the two selected regular members without interpreting archive paths as destinations."""
    require(archive_path.is_file() and not archive_path.is_symlink(), "Rhea archive must be an independent file")
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in RHEA_MEMBERS.values():
        for suffix in ("", ".partial"):
            path = output_dir / (filename + suffix)
            require(not os.path.lexists(path), f"Refusing to replace extracted candidate: {path}")
    require(not os.path.lexists(output_dir / "extraction.json"), "Rhea extraction evidence already exists")
    found, seen = {}, set()
    started = now()
    with tarfile.open(archive_path, mode="r|bz2") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and ".." not in name.parts, f"Unsafe tar member name: {member.name}")
            require(member.name not in seen, f"Duplicate tar member name: {member.name}")
            seen.add(member.name)
            if member.name not in RHEA_MEMBERS:
                continue
            require(member.isreg(), f"Selected Rhea member is not a regular file: {member.name}")
            destination = output_dir / RHEA_MEMBERS[member.name]
            partial = destination.with_name(destination.name + ".partial")
            checksum, copied = hashlib.sha256(), 0
            source = archive.extractfile(member)
            require(source is not None, f"Cannot read selected Rhea member: {member.name}")
            with source, partial.open("xb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
                    checksum.update(block)
                    copied += len(block)
                target.flush()
                os.fsync(target.fileno())
            require(copied == member.size and copied > 0, f"Incomplete selected Rhea member: {member.name}")
            found[member.name] = {"path": str(destination), "bytes": copied, "sha256": checksum.hexdigest()}
    require(set(found) == set(RHEA_MEMBERS), "Rhea archive is missing selected members")
    # Both files remain partial until the entire tar has passed member validation.
    for result in found.values():
        destination = Path(result["path"])
        publish_new(destination.with_name(destination.name + ".partial"), destination)
    result = {
        "archive": str(archive_path),
        "archive_sha256": digest(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "members": found,
        "started": started,
        "finished": now(),
    }
    write_json(output_dir / "extraction.json", result)
    return result


def execute() -> dict:
    """Acquire the fixed candidate set and publish success only after downloads and extraction pass."""
    request = plan()
    require(Path.cwd().resolve() == ROOT, "Execute only from the owned rebuild checkout")
    require(Path(sys.prefix).resolve() == (ROOT / ".venv").resolve(), "Execute with the isolated rebuild Python")
    CANDIDATES.mkdir(parents=True, exist_ok=False)
    request.update(
        started=now(),
        python=sys.executable,
        helper_sha256=digest(Path(__file__)),
        argv=sys.argv,
    )
    write_json(CANDIDATES / "plan.json", request)
    downloaded, failures = {}, {}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(download, CANDIDATES, spec): spec["key"] for spec in DOWNLOADS}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    downloaded[key] = future.result()
                except Exception as error:
                    failures[key] = f"{type(error).__name__}: {error}"
        require(not failures, f"Candidate acquisition failed: {failures}")
        extracted = extract_rhea(CANDIDATES / "rhea143/143.tar.bz2", CANDIDATES / "rhea143")
        result = {
            "status": "acquired_not_activated",
            "started": request["started"],
            "finished": now(),
            "helper_sha256": request["helper_sha256"],
            "downloads": downloaded,
            "rhea_extraction": extracted,
            "scientific_release_admission": False,
        }
        write_json(CANDIDATES / "receipt.json", result)
        return result
    except Exception as error:
        write_json(
            CANDIDATES / "failure.json",
            {"error": f"{type(error).__name__}: {error}", "downloads": downloaded, "finished": now()},
        )
        raise


def main(argv=None) -> int:
    """Print a read-only plan by default or explicitly acquire independent candidates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "execute"), nargs="?", default="plan")
    args = parser.parse_args(argv)
    result = execute() if args.action == "execute" else plan()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
