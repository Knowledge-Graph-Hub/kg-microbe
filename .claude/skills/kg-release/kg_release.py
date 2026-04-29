#!/usr/bin/env python3
"""KG-Microbe release skill — bundle merged-KG + transformed + raw + review report into a GitHub release.

See SKILL.md in this directory for usage and design rationale (notably the Plan A
split / Plan B Zenodo fork for assets that exceed GitHub's 2 GiB per-file limit).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
GIB = 1024 ** 3
GITHUB_ASSET_LIMIT = 2 * GIB  # GitHub release single-file cap
SPLIT_CHUNK_BYTES = int(1.9 * GIB)  # comfortably under the 2 GiB cap


def log(msg: str) -> None:
    """Write a timestamped log line to stderr."""
    print(f"[kg-release] {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], *, check: bool = True, cwd: Optional[Path] = None,
        env: Optional[dict] = None, capture: bool = False) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run with logging."""
    log("$ " + " ".join(cmd))
    return subprocess.run(
        cmd,
        check=check,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=capture,
    )


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Compute sha256 hex digest of a file, streaming."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


@dataclass
class ReviewArtifact:
    """A saved review report from one of the review skills."""

    skill: str
    path: Path
    mtime: datetime
    verdict: str = "unknown"  # "ok", "needs-attention", "unknown"


@dataclass
class AssetEntry:
    """One asset in the release manifest."""

    name: str
    sha256: str
    size_bytes: int
    parts: list[dict] = field(default_factory=list)  # populated for split assets
    zenodo_doi: Optional[str] = None
    note: str = ""


# -----------------------------------------------------------------------------
# Pre-flight
# -----------------------------------------------------------------------------


def check_gh_auth() -> None:
    """Abort if `gh` CLI is missing or not logged in."""
    if shutil.which("gh") is None:
        sys.exit("[kg-release] gh CLI not found on PATH; install from https://cli.github.com/")
    res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"[kg-release] gh auth status failed:\n{res.stderr}\nRun `gh auth login` first.")


def detect_repo() -> str:
    """Return OWNER/NAME for the current repo via `gh repo view`."""
    res = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
              capture=True)
    return res.stdout.strip()


def check_working_tree_clean() -> None:
    """Warn if the working tree has uncommitted changes."""
    res = run(["git", "status", "--porcelain"], capture=True, cwd=REPO_ROOT)
    if res.stdout.strip():
        log("WARNING: working tree is not clean. Release will be cut anyway, but assets may not "
            "match HEAD. Pass --ignore-dirty to suppress this warning.")


def check_tag_unused(repo: str, tag: str) -> None:
    """Abort if a release with this tag already exists on the remote."""
    res = subprocess.run(
        ["gh", "release", "view", tag, "-R", repo],
        capture_output=True, text=True,
    )
    if res.returncode == 0:
        sys.exit(f"[kg-release] release '{tag}' already exists on {repo}. "
                 f"Pass --replace to delete and recreate, or pick a new --release name.")


def replace_existing_release(repo: str, tag: str) -> None:
    """Delete an existing release + tag on the remote so we can recreate it."""
    log(f"deleting existing release {tag} on {repo} (--replace was set)")
    run(["gh", "release", "delete", tag, "-R", repo, "--yes", "--cleanup-tag"], check=False)


# -----------------------------------------------------------------------------
# Review gate
# -----------------------------------------------------------------------------


def find_recent_review(skill: str, max_age_days: int) -> Optional[ReviewArtifact]:
    """Return the newest review artifact from <skill>/reviews/ within max_age_days."""
    review_dir = SKILLS_DIR / skill / "reviews"
    if not review_dir.is_dir():
        return None
    cutoff = datetime.now() - timedelta(days=max_age_days)
    candidates = []
    for p in review_dir.iterdir():
        if not p.is_file():
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        if mtime < cutoff:
            continue
        candidates.append((mtime, p))
    if not candidates:
        return None
    mtime, path = max(candidates)
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    verdict = "ok"
    if "needs-attention" in text or "no-ship" in text or "[error]" in text:
        verdict = "needs-attention"
    return ReviewArtifact(skill=skill, path=path, mtime=mtime, verdict=verdict)


def run_review(skill: str, args_extra: list[str]) -> Optional[ReviewArtifact]:
    """Invoke a review skill's CLI and pick up the artifact it just wrote."""
    script = SKILLS_DIR / skill / f"{skill.replace('-', '_')}.py"
    if not script.is_file():
        log(f"skill script not found: {script}; skipping {skill}")
        return None
    log(f"running {skill}")
    proc = subprocess.run(
        ["poetry", "run", "python", str(script), *args_extra],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        log(f"WARN: {skill} exited {proc.returncode}; stderr tail: {proc.stderr[-400:]}")
    # Skills save with default-on; we just look up the newest artifact under reviews/.
    return find_recent_review(skill, max_age_days=1)


def gate_on_reviews(merged_dir: Path, max_age_days: int, ignore: bool,
                    skip_review: bool) -> list[ReviewArtifact]:
    """Run/load the three review skills and return their artifacts.

    Aborts when any verdict is `needs-attention` and `--ignore-review` is not set.
    """
    if skip_review:
        log("--skip-review set: not running or loading review artifacts")
        return []
    artifacts: list[ReviewArtifact] = []
    for skill, extra in (
        ("kg-model-review", ["--merged-dir", str(merged_dir), "--format", "md"]),
        ("kg-path-review", ["archetype", "self-loops"]),
    ):
        art = find_recent_review(skill, max_age_days)
        if art is None:
            art = run_review(skill, extra)
        if art:
            artifacts.append(art)
    bad = [a for a in artifacts if a.verdict == "needs-attention"]
    if bad and not ignore:
        names = ", ".join(a.skill for a in bad)
        sys.exit(f"[kg-release] review verdict 'needs-attention' from: {names}. "
                 f"Inspect the artifact(s), fix issues, or pass --ignore-review.")
    return artifacts


# -----------------------------------------------------------------------------
# Tarball + split
# -----------------------------------------------------------------------------


def build_merged_tarball(merged_dir: Path, release: str, out: Path) -> Path:
    """Pack the two merged-KG TSVs into a single .tar.gz under out/."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"merged-kg_{release}.tar.gz"
    if target.exists():
        log(f"reusing existing {target.name}")
        return target
    nodes = merged_dir / "merged-kg_nodes.tsv"
    edges = merged_dir / "merged-kg_edges.tsv"
    if not nodes.is_file() or not edges.is_file():
        sys.exit(f"[kg-release] expected merged-kg_nodes.tsv + merged-kg_edges.tsv under "
                 f"{merged_dir}; got {sorted(p.name for p in merged_dir.iterdir())}")
    run(["tar", "czf", str(target), "-C", str(merged_dir),
         "merged-kg_nodes.tsv", "merged-kg_edges.tsv"])
    return target


def build_dir_tarball(src: Path, asset_name: str, out: Path) -> Path:
    """tar+gzip a directory tree into out/<asset_name>."""
    target = out / asset_name
    if target.exists():
        log(f"reusing existing {target.name}")
        return target
    if not src.is_dir():
        sys.exit(f"[kg-release] source directory missing: {src}")
    out.mkdir(parents=True, exist_ok=True)
    log(f"packing {src} → {target.name} (this can take many minutes for large trees)")
    # Use `gzip -1` for speed; releases compress raw data not source code.
    cmd = ["tar", "-c", "-I", "gzip -1", "-f", str(target),
           "-C", str(src.parent), src.name]
    run(cmd)
    return target


def split_if_too_large(asset: Path, chunk: int = SPLIT_CHUNK_BYTES) -> list[Path]:
    """Split asset into <chunk>-byte parts. Returns the list of part paths.

    If the asset is already small enough, returns [asset] unchanged.
    """
    if asset.stat().st_size <= GITHUB_ASSET_LIMIT:
        return [asset]
    log(f"{asset.name} is {asset.stat().st_size / GIB:.2f} GiB > 2 GiB; splitting "
        f"into {chunk / GIB:.1f} GiB parts")
    prefix = str(asset) + ".part-"
    # gnu split: -d numeric suffixes, -a 2 → 2 digits → up to 100 parts
    run(["split", "-b", str(chunk), "-d", "-a", "2", str(asset), prefix])
    parts = sorted(asset.parent.glob(asset.name + ".part-*"))
    if not parts:
        sys.exit(f"[kg-release] split produced no parts for {asset}")
    log(f"  produced {len(parts)} parts")
    return parts


def asset_entry_for(asset: Path, parts: list[Path]) -> AssetEntry:
    """Build a manifest entry for an asset (single file or split parts)."""
    sha = sha256_file(asset)
    size = asset.stat().st_size
    if len(parts) == 1 and parts[0] == asset:
        return AssetEntry(name=asset.name, sha256=sha, size_bytes=size)
    part_records = []
    for p in parts:
        part_records.append({
            "name": p.name,
            "sha256": sha256_file(p),
            "size_bytes": p.stat().st_size,
        })
    return AssetEntry(
        name=asset.name,
        sha256=sha,
        size_bytes=size,
        parts=part_records,
        note=f"reassemble: cat {asset.name}.part-* > {asset.name}",
    )


# -----------------------------------------------------------------------------
# Plan B: Zenodo
# -----------------------------------------------------------------------------


def upload_to_zenodo(asset: Path, release: str, sandbox: bool, repo: str) -> str:
    """Upload one tarball to Zenodo, publish, and return the DOI."""
    try:
        import requests  # noqa: F401
    except ImportError:
        sys.exit("[kg-release] requests not installed; `poetry add requests` and retry")
    import requests

    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        sys.exit("[kg-release] --zenodo-raw set but ZENODO_TOKEN is not in env")
    base = "https://sandbox.zenodo.org/api" if sandbox else "https://zenodo.org/api"
    headers = {"Authorization": f"Bearer {token}"}

    log(f"creating Zenodo deposit on {base}")
    r = requests.post(f"{base}/deposit/depositions", json={}, headers=headers, timeout=60)
    r.raise_for_status()
    deposit = r.json()
    deposit_id = deposit["id"]
    bucket_url = deposit["links"]["bucket"]

    log(f"uploading {asset.name} → bucket {bucket_url}")
    with asset.open("rb") as fh:
        r = requests.put(f"{bucket_url}/{asset.name}", data=fh, headers=headers, timeout=None)
    r.raise_for_status()

    metadata = {
        "metadata": {
            "title": f"KG-Microbe {release} — raw source data",
            "upload_type": "dataset",
            "description": (
                f"<p>Raw source data snapshot accompanying the {release} release of "
                f"<a href=\"https://github.com/{repo}\">KG-Microbe</a>. "
                f"Contains every file under <code>data/raw/</code> at release time. "
                f"Companion merged KG and transformed data are available on the GitHub "
                f"release page.</p>"
            ),
            "version": release,
            "creators": [{"name": "KG-Microbe contributors"}],
            "keywords": ["knowledge graph", "microbiology", "BacDive", "KG-Microbe"],
            "license": "cc-by-4.0",
            "access_right": "open",
        }
    }
    r = requests.put(f"{base}/deposit/depositions/{deposit_id}",
                     json=metadata, headers=headers, timeout=60)
    r.raise_for_status()

    log(f"publishing deposit {deposit_id}")
    r = requests.post(f"{base}/deposit/depositions/{deposit_id}/actions/publish",
                      headers=headers, timeout=60)
    r.raise_for_status()
    doi = r.json()["doi"]
    log(f"Zenodo DOI: {doi}")
    return doi


# -----------------------------------------------------------------------------
# Release notes + manifest
# -----------------------------------------------------------------------------


def build_release_notes(release: str, repo: str, assets: list[AssetEntry],
                        artifacts: list[ReviewArtifact]) -> str:
    """Compose the markdown body for the GitHub release."""
    lines = [
        f"# KG-Microbe {release}",
        "",
        f"_Cut on {datetime.now().strftime('%Y-%m-%d')}_",
        "",
        "## Review verdicts",
        "",
    ]
    if not artifacts:
        lines.append("- _no review artifacts attached_")
    else:
        for a in artifacts:
            badge = "✅" if a.verdict == "ok" else "⚠️"
            lines.append(f"- {badge} `{a.skill}` — {a.verdict} "
                         f"(report: `{a.path.relative_to(REPO_ROOT)}`)")
    lines += ["", "## Assets", ""]
    for a in assets:
        if a.parts:
            lines.append(f"- **{a.name}** ({a.size_bytes / GIB:.2f} GiB) — split into "
                         f"{len(a.parts)} parts; reassemble with "
                         f"`cat {a.name}.part-* > {a.name}`")
        elif a.zenodo_doi:
            lines.append(f"- **{a.name}** ({a.size_bytes / GIB:.2f} GiB) — "
                         f"hosted on Zenodo: https://doi.org/{a.zenodo_doi}")
        else:
            size_mib = a.size_bytes / (1024 ** 2)
            lines.append(f"- **{a.name}** ({size_mib:.1f} MiB)")
    lines += [
        "",
        "## How to consume",
        "",
        "```bash",
        f"# Merged KG (drops in as data/merged/{release}/)",
        f"curl -L https://github.com/{repo}/releases/download/{release}/merged-kg_{release}.tar.gz \\",
        f"     | tar xz",
        "```",
        "",
        "Full sha256s and reassembly recipes are in `MANIFEST_<release>.json` "
        "(also attached to this release).",
        "",
    ]
    return "\n".join(lines)


def write_manifest(release: str, repo: str, assets: list[AssetEntry], out: Path) -> Path:
    """Write MANIFEST_<release>.json with sha256s + Zenodo DOIs."""
    manifest = {
        "release": release,
        "repo": repo,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "assets": {a.name: {
            "sha256": a.sha256,
            "size_bytes": a.size_bytes,
            "parts": a.parts,
            "zenodo_doi": a.zenodo_doi,
            "note": a.note,
        } for a in assets},
    }
    target = out / f"MANIFEST_{release}.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


# -----------------------------------------------------------------------------
# gh release publish
# -----------------------------------------------------------------------------


def publish_release(repo: str, release: str, notes_path: Path,
                    upload_paths: list[Path], prerelease: bool, draft: bool) -> str:
    """Run `gh release create` with all assets. Returns the release URL."""
    cmd = ["gh", "release", "create", release,
           "--repo", repo,
           "--title", f"KG-Microbe {release}",
           "--notes-file", str(notes_path)]
    if prerelease:
        cmd.append("--prerelease")
    if draft:
        cmd.append("--draft")
    cmd += [str(p) for p in upload_paths]
    res = run(cmd, capture=True)
    return res.stdout.strip()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> int:
    """CLI entry point — parses args and orchestrates the release."""
    p = argparse.ArgumentParser(description="Cut a KG-Microbe GitHub release.")
    p.add_argument("--release", required=True, help="Release name and git tag, e.g. v20260428")
    p.add_argument("--merged-dir", required=True, type=Path,
                   help="data/merged/<dir> with merged-kg_nodes.tsv + merged-kg_edges.tsv")
    p.add_argument("--repo", default=None, help="OWNER/NAME (defaults to current gh repo)")
    p.add_argument("--prerelease", action="store_true")
    p.add_argument("--draft", action="store_true")
    p.add_argument("--skip-raw", action="store_true",
                   help="Don't bundle data/raw/ — users can regenerate with `kg download`")
    p.add_argument("--skip-transformed", action="store_true",
                   help="Don't bundle data/transformed/")
    p.add_argument("--zenodo-raw", action="store_true",
                   help="Plan B: upload data_raw_<release>.tar.gz to Zenodo, link from release notes")
    p.add_argument("--zenodo-sandbox", action="store_true",
                   help="Use sandbox.zenodo.org for testing (test DOIs)")
    p.add_argument("--max-parts", type=int, default=6,
                   help="If a split would exceed this many parts, suggest --zenodo-raw")
    p.add_argument("--ignore-review", action="store_true",
                   help="Proceed past `needs-attention` review verdicts")
    p.add_argument("--skip-review", action="store_true",
                   help="Don't run or load review reports at all (use sparingly)")
    p.add_argument("--review-max-age-days", type=int, default=7)
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Stage tarballs here (default: <repo>/releases/<release>)")
    p.add_argument("--ignore-dirty", action="store_true",
                   help="Suppress the working-tree-not-clean warning")
    p.add_argument("--replace", action="store_true",
                   help="Delete an existing release with this tag before recreating")
    p.add_argument("--dry-run", action="store_true",
                   help="Build everything locally but don't `gh release create`")
    args = p.parse_args()

    out_dir = args.out_dir or (REPO_ROOT / "releases" / args.release)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pre-flight
    check_gh_auth()
    repo = args.repo or detect_repo()
    log(f"target repo: {repo}")
    if not args.ignore_dirty:
        check_working_tree_clean()
    if args.replace:
        replace_existing_release(repo, args.release)
    elif not args.dry_run:
        check_tag_unused(repo, args.release)

    # Review gate
    artifacts = gate_on_reviews(
        merged_dir=args.merged_dir,
        max_age_days=args.review_max_age_days,
        ignore=args.ignore_review,
        skip_review=args.skip_review,
    )

    # Stage assets
    asset_entries: list[AssetEntry] = []
    upload_paths: list[Path] = []

    log("building merged-KG tarball")
    merged_tar = build_merged_tarball(args.merged_dir, args.release, out_dir)
    parts = split_if_too_large(merged_tar)
    asset_entries.append(asset_entry_for(merged_tar, parts))
    upload_paths.extend(parts)

    if not args.skip_transformed:
        log("building data/transformed tarball")
        transformed_tar = build_dir_tarball(
            REPO_ROOT / "data" / "transformed",
            f"data_transformed_{args.release}.tar.gz", out_dir)
        parts = split_if_too_large(transformed_tar)
        if len(parts) > args.max_parts:
            sys.exit(f"[kg-release] data_transformed split would be {len(parts)} parts > "
                     f"--max-parts={args.max_parts}; pass --zenodo-raw or raise --max-parts")
        asset_entries.append(asset_entry_for(transformed_tar, parts))
        upload_paths.extend(parts)

    if not args.skip_raw:
        log("building data/raw tarball (this is the slow one)")
        raw_tar = build_dir_tarball(
            REPO_ROOT / "data" / "raw",
            f"data_raw_{args.release}.tar.gz", out_dir)

        if args.zenodo_raw:
            doi = "DRYRUN" if args.dry_run else upload_to_zenodo(
                raw_tar, args.release, args.zenodo_sandbox, repo)
            entry = AssetEntry(
                name=raw_tar.name,
                sha256=sha256_file(raw_tar),
                size_bytes=raw_tar.stat().st_size,
                zenodo_doi=doi,
                note=f"hosted on Zenodo (sandbox={args.zenodo_sandbox})",
            )
            asset_entries.append(entry)
            # Don't upload to GitHub release — Zenodo holds the bytes.
        else:
            parts = split_if_too_large(raw_tar)
            if len(parts) > args.max_parts:
                sys.exit(f"[kg-release] data_raw split would be {len(parts)} parts > "
                         f"--max-parts={args.max_parts}; pass --zenodo-raw, raise "
                         f"--max-parts, or --skip-raw and document `kg download`")
            asset_entries.append(asset_entry_for(raw_tar, parts))
            upload_paths.extend(parts)

    # Manifest + release notes
    manifest_path = write_manifest(args.release, repo, asset_entries, out_dir)
    notes = build_release_notes(args.release, repo, asset_entries, artifacts)
    notes_path = out_dir / f"release_notes_{args.release}.md"
    notes_path.write_text(notes, encoding="utf-8")
    upload_paths.extend([manifest_path, notes_path])

    log("staged assets:")
    for p in upload_paths:
        log(f"  {p.relative_to(REPO_ROOT)} ({p.stat().st_size / (1024 ** 2):.1f} MiB)")

    if args.dry_run:
        log("--dry-run set: skipping `gh release create`")
        log(f"manifest: {manifest_path.relative_to(REPO_ROOT)}")
        log(f"notes:    {notes_path.relative_to(REPO_ROOT)}")
        return 0

    log(f"publishing release {args.release} on {repo}")
    url = publish_release(repo, args.release, notes_path,
                          upload_paths, args.prerelease, args.draft)
    log(f"release URL: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
