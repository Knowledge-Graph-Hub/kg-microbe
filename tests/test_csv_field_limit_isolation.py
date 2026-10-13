"""No test, and no module a test loads, can raise CSV's field limit for later tests (#1574)."""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.conftest import SESSION_CSV_FIELD_LIMIT

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


def test_the_session_starts_at_csvs_default():
    """Tests of readers that must cope with long cells run at the limit a fresh process has."""
    assert SESSION_CSV_FIELD_LIMIT == 131_072


def test_a_test_may_leave_the_limit_raised():
    """Stand in for a test, or a module it loads, that raises the limit and keeps it raised."""
    csv.field_size_limit(sys.maxsize)


def test_the_next_test_starts_from_the_session_limit():
    """The conftest guard resets the limit whatever ran before; it runs after the test above."""
    assert csv.field_size_limit() == SESSION_CSV_FIELD_LIMIT
