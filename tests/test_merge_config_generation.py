"""Regression tests for canonical merge variant generation."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.generate_merge_configs import generate

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [
    "merge.yaml",
    "merge.minimal.yaml",
    "merge.no_metatraits.yaml",
    "merge.noprego.yaml",
    "merge.prego-full.yaml",
    "merge_bakta.yaml",
]


def test_generated_merge_configs_are_current() -> None:
    """Committed runtime YAML must match the canonical spec and deltas."""
    assert generate(check=True) == 0


def test_every_merge_variant_has_unique_outputs_and_stats() -> None:
    """One variant must never silently overwrite another variant's artifacts."""
    outputs = []
    stats = []
    for filename in CONFIGS:
        config = yaml.safe_load((REPO_ROOT / filename).read_text(encoding="utf-8"))
        graph = config["merged_graph"]
        outputs.append(graph["destination"]["merged-kg-tsv"]["filename"])
        stats.append(graph["operations"][0]["args"]["filename"])
    assert len(outputs) == len(set(outputs))
    assert len(stats) == len(set(stats))
