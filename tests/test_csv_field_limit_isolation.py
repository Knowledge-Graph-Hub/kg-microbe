"""No test, and no code a test runs, can carry a raised CSV field limit into a later test (#1574)."""

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import SESSION_CSV_FIELD_LIMIT, csv_field_limit_guard

SKILLS = Path(__file__).resolve().parents[1] / ".claude/skills"


@pytest.mark.parametrize("script", ["gtdb-phylo-diagram/gtdb_phylo_diagram.py", "kg-release-diff/kg_release_diff.py"])
def test_loading_a_skill_leaves_the_csv_field_limit_alone(monkeypatch, script):
    """The skills lift the limit in main(), for their own process, not when imported."""
    spec = importlib.util.spec_from_file_location(f"csv_limit_{Path(script).stem}", SKILLS / script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    before = csv.field_size_limit()
    spec.loader.exec_module(module)
    assert csv.field_size_limit() == before


def test_the_release_diff_still_reads_a_cell_over_the_default(tmp_path):
    """Its main() lifts the limit for the command: merged rows can be longer than 131,072 characters."""
    for release in ("old", "new"):
        directory = tmp_path / release
        directory.mkdir()
        (directory / "nodes.tsv").write_text(
            f"id\tcategory\tname\tdescription\nX:1\tbiolink:NamedThing\tx\t{'d' * 200_000}\n", encoding="utf-8"
        )
        (directory / "edges.tsv").write_text(
            "subject\tpredicate\tobject\nX:1\tbiolink:related_to\tX:1\n", encoding="utf-8"
        )
    arguments = ["--old", str(tmp_path / "old"), "--new", str(tmp_path / "new"), "--out", str(tmp_path / "diff.md")]
    child = subprocess.run(  # noqa: S603 - fixed interpreter and script, test-owned paths
        [sys.executable, str(SKILLS / "kg-release-diff/kg_release_diff.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert (tmp_path / "diff.md").is_file()


def test_the_session_starts_at_csvs_default():
    """Tests of readers that must cope with long cells run at the limit a fresh process has."""
    assert SESSION_CSV_FIELD_LIMIT == 131_072


def test_the_guard_undoes_a_raise_made_before_the_block():
    """A raise made earlier, while modules were imported for example, does not reach the block."""
    csv.field_size_limit(sys.maxsize)
    with csv_field_limit_guard():
        assert csv.field_size_limit() == SESSION_CSV_FIELD_LIMIT


def test_the_guard_fails_a_block_that_leaves_the_limit_raised():
    """A leak is reported rather than quietly repaired, and the limit is still put back."""
    with pytest.raises(pytest.fail.Exception, match="left at 1000000"), csv_field_limit_guard():
        csv.field_size_limit(1_000_000)
    assert csv.field_size_limit() == SESSION_CSV_FIELD_LIMIT


def test_the_guard_accepts_a_block_that_restores_the_limit():
    """Changing the limit on purpose is fine when the block puts it back."""
    with csv_field_limit_guard():
        previous = csv.field_size_limit(1_000_000)
        csv.field_size_limit(previous)


def test_the_guard_still_resets_when_the_block_fails():
    """A failing test does not leave its raise behind either."""
    with pytest.raises(ValueError, match="read failed"), csv_field_limit_guard():
        csv.field_size_limit(1_000_000)
        raise ValueError("read failed")
    assert csv.field_size_limit() == SESSION_CSV_FIELD_LIMIT


@pytest.fixture(scope="module")
def raised_before_the_test():
    """Raise the limit before the test's own fixtures run, as a raise at import would."""
    previous = csv.field_size_limit(sys.maxsize)
    yield
    csv.field_size_limit(previous)


def test_every_test_starts_at_the_session_limit(raised_before_the_test):
    """The guard is wired in for every test: a limit raised before the test does not reach it."""
    assert csv.field_size_limit() == SESSION_CSV_FIELD_LIMIT
