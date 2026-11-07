"""
Prepare and verify the narrowly authorized 2026-11-05 raw refresh.

Inputs: canonical download.yaml and independently staged data/raw.
Outputs: task-specific download config, before/after checksum evidence, archive receipt.
Downloads themselves run separately through the production CLI and saved launcher.
"""

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/20261105/refresh"
RAW = ROOT / "data/raw"
URLS = {
    "taxdump.tar.gz": "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
    "mediadive.json": "https://mediadive.dsmz.de/rest/media",
}
TAGS = {"taxdump.tar.gz": "refresh-taxdump", "mediadive.json": "refresh-mediadive-list"}


def save(path, value):
    """Write a new evidence document without overwriting prior observations."""
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def identity(path):
    """Measure full-byte identity without materializing an archive."""
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
            md5.update(block)
    return {"sha256": sha.hexdigest(), "md5": md5.hexdigest(), "bytes": path.stat().st_size}


def checksum(label):
    """Retain one fresh official taxdump checksum and HTTP evidence."""
    path = EVIDENCE / f"taxdump-{label}.md5"
    for evidence_path in (path, path.with_suffix(".headers")):
        if os.path.lexists(evidence_path):
            raise RuntimeError(f"Refusing checksum evidence overwrite: {evidence_path}")
    command = [
        "/usr/bin/curl",
        "--disable",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "3",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--dump-header",
        str(path.with_suffix(".headers")),
        "--output",
        str(path),
        URLS["taxdump.tar.gz"] + ".md5",
    ]
    subprocess.run(command, check=True)  # noqa: S603 - fixed public HTTPS checksum URL
    cells = path.read_text().split()
    if len(cells) != 2 or cells[1].lstrip("*") != "taxdump.tar.gz" or len(cells[0]) != 32:
        raise RuntimeError("Unexpected official taxdump checksum format")
    int(cells[0], 16)
    return cells[0].lower()


def prepare():
    """Select exactly the two authorized canonical inputs with private refresh tags."""
    entries = yaml.safe_load((ROOT / "download.yaml").read_text())
    selected = []
    for name, url in URLS.items():
        matches = [entry for entry in entries if entry.get("local_name") == name]
        if len(matches) != 1 or matches[0]["url"] != url:
            raise RuntimeError(f"Canonical refresh identity differs: {name}")
        selected.append({**matches[0], "tag": TAGS[name]})
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    save(EVIDENCE / "before-inputs.json", {name: identity(RAW / name) for name in URLS})
    with (EVIDENCE / "download.yaml").open("x") as handle:
        yaml.safe_dump(selected, handle, sort_keys=False)
    save(EVIDENCE / "before-checksum.json", {"official_md5": checksum("before")})
    print(EVIDENCE / "download.yaml", flush=True)


def verify_taxdump():
    """Verify stable official checksum, complete gzip integrity and required tar members."""
    before = json.loads((EVIDENCE / "before-checksum.json").read_text())["official_md5"]
    after = checksum("after")
    actual = identity(RAW / "taxdump.tar.gz")
    if before != after or actual["md5"] != after:
        raise RuntimeError("Taxdump checksum changed during acquisition or downloaded bytes differ")
    members = {}
    with gzip.open(RAW / "taxdump.tar.gz", "rb") as stream:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                if member.name in members or not member.isreg():
                    raise RuntimeError(f"Unexpected taxdump member: {member.name}")
                members[member.name] = member.size
                with archive.extractfile(member) as data:
                    for _ in iter(lambda: data.read(1024 * 1024), b""):
                        pass
        for _ in iter(lambda: stream.read(1024 * 1024), b""):
            pass
    required = {"nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"}
    if not required <= members.keys() or any(members[name] <= 0 for name in required):
        raise RuntimeError("Taxdump lacks required nonempty authority members")
    save(
        EVIDENCE / "taxdump-receipt.json",
        {
            "identity": actual,
            "official_md5": after,
            "members": members,
            "gzip_integrity": True,
            "stable_upstream_checksum": True,
        },
    )
    print(json.dumps(actual), flush=True)


def main():
    """Execute only one explicit preparation or verification action."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify-taxdump"))
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT or RAW.is_symlink() or not RAW.is_dir():
        raise RuntimeError("Use the owned worktree with independently staged raw inputs")
    if args.action == "prepare":
        prepare()
    else:
        verify_taxdump()


if __name__ == "__main__":
    main()
