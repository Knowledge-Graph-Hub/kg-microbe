"""Regression tests for the compact generated-data ignore policy."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
GIT = shutil.which("git")
assert GIT is not None


def is_ignored(path: str) -> bool:
    """Return whether Git's current policy ignores a hypothetical path."""
    result = subprocess.run(  # noqa: S603 -- fixed executable and test paths
        [GIT, "check-ignore", "--quiet", "--no-index", path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def test_generated_data_is_ignored() -> None:
    """Large pipeline artifacts are covered by stable directory rules."""
    assert is_ignored("data/raw/example/source.owl")
    assert is_ignored("data/transformed/bacdive/nodes.tsv")
    assert is_ignored("data/merged/merged-kg.tar.gz")
    assert is_ignored("data/db/chebi.db")


def test_authored_inputs_remain_visible() -> None:
    """Curated mappings and test fixtures must remain available to Git."""
    assert not is_ignored("mappings/canonical/new_mapping.tsv")
    assert not is_ignored("tests/resources/new_fixture.tsv")
    assert not is_ignored("config/merge_variants.yaml")
    assert not is_ignored("data/raw/exclusion_branches.tsv")
    assert not is_ignored("data/raw/nlp/stopwords/stopWords.txt")
