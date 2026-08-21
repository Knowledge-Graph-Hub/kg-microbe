"""Generate merge variants from canonical ``merge.yaml`` and explicit deltas."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = REPO_ROOT / "merge.yaml"
VARIANTS_PATH = REPO_ROOT / "config" / "merge_variants.yaml"
GENERATED_HEADER = "# GENERATED from merge.yaml + config/merge_variants.yaml; do not edit directly.\n"


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load one required YAML mapping."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _render_variant(base: Dict[str, Any], name: str, spec: Dict[str, Any]) -> str:
    """Apply one small variant delta and serialize it deterministically."""
    config = copy.deepcopy(base)
    merged_graph = config["merged_graph"]
    sources = merged_graph["source"]

    include_only = spec.get("include_only")
    if include_only:
        unknown = set(include_only) - set(sources)
        if unknown:
            raise ValueError(f"{name}: unknown include_only sources: {sorted(unknown)}")
        merged_graph["source"] = {key: sources[key] for key in include_only}
        sources = merged_graph["source"]

    for source in spec.get("remove_sources", []):
        if source not in sources:
            raise ValueError(f"{name}: cannot remove missing source {source!r}")
        del sources[source]

    for source, override in spec.get("source_overrides", {}).items():
        if source not in sources:
            raise ValueError(f"{name}: cannot override missing source {source!r}")
        sources[source] = override

    for source, definition in spec.get("add_sources", {}).items():
        if source in sources:
            raise ValueError(f"{name}: added source already exists: {source!r}")
        sources[source] = definition

    merged_graph["destination"]["merged-kg-tsv"]["filename"] = spec["output_filename"]
    operations = merged_graph.get("operations", [])
    if not operations:
        raise ValueError(f"{name}: canonical config has no graph statistics operation")
    operations[0]["args"]["filename"] = spec["stats_filename"]

    description = spec.get("description", name)
    return (
        GENERATED_HEADER
        + f"# {description}\n"
        + yaml.safe_dump(config, sort_keys=False, width=120, allow_unicode=True)
    )


def generate(check: bool = False) -> int:
    """Write variants, or return nonzero when committed files are stale."""
    base = _load_yaml(BASE_PATH)
    variant_data = _load_yaml(VARIANTS_PATH).get("variants", {})
    stale = []
    for filename, spec in variant_data.items():
        output_path = REPO_ROOT / filename
        rendered = _render_variant(base, filename, spec)
        if check:
            if not output_path.is_file() or output_path.read_text(encoding="utf-8") != rendered:
                stale.append(filename)
        else:
            output_path.write_text(rendered, encoding="utf-8")
    if stale:
        print("Stale generated merge configs: " + ", ".join(stale), file=sys.stderr)
        print("Run: poetry run python scripts/generate_merge_configs.py", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files differ")
    args = parser.parse_args()
    return generate(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
