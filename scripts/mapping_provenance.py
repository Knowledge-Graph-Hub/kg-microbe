"""Report mapping exporter drift without regenerating or modifying mappings."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import yaml

EXPORTERS = {
    "kg-microbe/scripts/consolidate_chemical_mappings.py": "scripts/consolidate_chemical_mappings.py",
    "kg-microbe/scripts/mim_conservative_refresh.py": "scripts/mim_conservative_refresh.py",
}


def file_sha256(path: Path) -> str:
    """Hash a file incrementally without decoding its contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def context_paths(repo_root: Path) -> tuple[Path, ...]:
    """Select an explicit conservative code/config superset, not a guessed import graph."""
    paths = set()
    for directory in ("scripts", "kg_microbe/utils", "kg_microbe/profiles"):
        base = repo_root / directory
        paths.update(path for path in base.rglob("*") if path.is_file() and path.suffix in {".py", ".json", ".yaml"})
    for relative in ("pyproject.toml", "poetry.lock", "kg_microbe/transform_utils/constants.py"):
        path = repo_root / relative
        if not path.is_file():
            raise ValueError(f"Missing mapping reproducibility input: {relative}")
        paths.add(path)
    return tuple(sorted(paths))


def reproducibility_context(repo_root: Path) -> dict:
    """Record actual libraries and portable source hashes, separately from scientific evidence."""
    root = repo_root.resolve()
    code = {str(path.relative_to(root)): file_sha256(path) for path in context_paths(root)}
    libraries = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            libraries.setdefault(name.casefold().replace("_", "-"), set()).add(distribution.version)
    environment = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "installed_distributions": {name: sorted(versions) for name, versions in sorted(libraries.items())},
    }
    payload = {"code_and_config_sha256": code, "environment": environment}
    return {
        "schema_version": 1,
        **payload,
        "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "scope": "Explicit scripts/utils/profiles superset, dependency lock, constants, installed package versions; "
        "selected scientific inputs are fingerprinted separately. Not an exhaustive operating-system snapshot.",
    }


def exporter_agreement(artifact: Path, repo_root: Path) -> dict:
    """Compare a bounded SSSOM header to a recognized local exporter without importing it."""
    opener = gzip.open if artifact.suffix == ".gz" else open
    lines = []
    size = 0
    with opener(artifact, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            size += len(line)
            if size > 1024 * 1024:
                raise ValueError("SSSOM metadata exceeds the 1 MiB diagnostic limit")
            lines.append(line[1:].removeprefix(" "))
    metadata = yaml.safe_load("".join(lines))
    if not isinstance(metadata, dict):
        raise ValueError("Missing or invalid SSSOM metadata")
    tool = metadata.get("mapping_tool")
    recorded = metadata.get("mapping_tool_version")
    relative = EXPORTERS.get(tool) if isinstance(tool, str) else None
    current = "sha256:" + file_sha256(repo_root / relative) if relative else None
    status = "MATCH" if current and recorded == current else "DRIFT" if current else "UNRECOGNIZED_EXPORTER"
    return {
        "schema_version": 1,
        "status": status,
        "artifact": str(artifact),
        "mapping_tool": tool,
        "recorded_exporter": recorded,
        "current_exporter": current,
        "blocking": False,
        "note": "Exporter drift is a provenance observation, not proof of incorrect mappings. "
        "Do not regenerate through the blocked legacy additive workflow to silence this report.",
    }


def main(argv=None) -> None:
    """Print a read-only, nonblocking provenance report; malformed inputs still fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--context", action="store_true", help="Include current code/config and environment inventory.")
    args = parser.parse_args(argv)
    artifact = args.artifact or args.repo_root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    report = exporter_agreement(artifact, args.repo_root)
    if args.context:
        report["current_context"] = reproducibility_context(args.repo_root)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
