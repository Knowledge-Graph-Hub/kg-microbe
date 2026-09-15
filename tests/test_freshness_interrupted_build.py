"""Finalized sources cannot fall back to timestamp freshness after an interrupted rebuild."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/resources/consumed_input_fingerprint/finalization.json"


@pytest.fixture
def checker(tmp_path, monkeypatch):
    """Load the actual skill against isolated output directories with benign current timestamps."""
    script = ROOT / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("freshness_interrupted_test", script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TRANSFORMED_DIR", tmp_path)
    monkeypatch.setattr(module, "_latest_commit", lambda *args: (1, "fixture"))
    monkeypatch.setattr(module, "_has_local_diff", lambda *args: False)
    monkeypatch.setattr(module, "_latest_data_input_commit", lambda *args: (None, None))
    return module


@pytest.mark.parametrize("record", ["source_finalization.json", "go_source_finalization.json"])
def test_missing_success_marker_blocks_timestamp_fallback(checker, tmp_path, record):
    """Neither old whole-source nor scoped completion records prove a stopped producer finished."""
    output = tmp_path / "metatraits"
    output.mkdir()
    shutil.copyfile(FIXTURE, output / record)
    (output / "edges.tsv").write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    report = checker.check_source("metatraits", "HEAD")
    assert report.status == "MISSING_BUILD_RECORD"
    assert "rerun" in report.note


@pytest.mark.parametrize("contents", ["invalid JSON", '{"version": 999}'])
def test_unreadable_or_unsupported_marker_is_not_legacy_fresh(checker, tmp_path, contents):
    """Unusable explicit build evidence must not be downgraded into a successful timestamp check."""
    output = tmp_path / "metatraits"
    output.mkdir()
    (output / "source_fingerprint.json").write_text(contents, encoding="utf-8")
    (output / "edges.tsv").write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    assert checker.check_source("metatraits", "HEAD").status == "MISSING_BUILD_RECORD"


def test_unselected_alias_cannot_supply_a_missing_marker(checker, tmp_path, monkeypatch):
    """The selected habitat directory cannot borrow completion evidence from the all-shapes graph."""
    from kg_microbe.utils import transform_fingerprint as fingerprint

    selected = tmp_path / "prego_habitat"
    alternate = tmp_path / "prego"
    selected.mkdir()
    alternate.mkdir()
    shutil.copyfile(FIXTURE, selected / "source_finalization.json")
    monkeypatch.setattr(checker, "_dirs_referenced_by_merge_config", lambda: {"prego_habitat"})

    def read_selected_only(path):
        """Fail if the diagnostic consults a marker outside its actual merge scope."""
        assert Path(path) == selected
        return None

    monkeypatch.setattr(fingerprint, "read_fingerprint", read_selected_only)
    status, _ = checker._fingerprint_verdict("prego", ROOT / "kg_microbe/transform_utils/prego")
    assert status == "MISSING_BUILD_RECORD"


def test_unmarked_legacy_output_is_unverified_not_completed(checker, tmp_path):
    """Old files and an interrupted first finalized rebuild are indistinguishable by timestamp."""
    output = tmp_path / "metatraits"
    output.mkdir()
    (output / "edges.tsv").write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    assert checker._fingerprint_verdict("metatraits", ROOT / "kg_microbe/transform_utils/metatraits") is None
    report = checker.check_source("metatraits", "HEAD")
    assert report.status == "UNVERIFIED_BUILD"
    assert "interrupted" in report.note


def test_missing_selected_alias_cannot_borrow_existing_output(checker, tmp_path, monkeypatch):
    """A missing configured output stays missing even when another graph for that producer exists."""
    selected = tmp_path / "prego_habitat"
    alternate = tmp_path / "prego"
    alternate.mkdir()
    (alternate / "edges.tsv").write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    monkeypatch.setattr(checker, "_dirs_referenced_by_merge_config", lambda: {"prego_habitat"})
    assert checker._output_dirs("prego") == [selected]
    assert checker._output_mtime("prego") is None
    assert checker.check_source("prego", "HEAD").status == "MISSING_OUTPUT"
