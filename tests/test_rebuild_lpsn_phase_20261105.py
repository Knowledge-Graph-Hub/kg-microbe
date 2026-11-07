"""Offline controls for canonical prerequisite binding and scoped launch evidence."""

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.adhoc import kgm_rebuild_admission_20261105 as planner

SCRIPT = Path(__file__).parents[1] / "scripts/adhoc/kgm_rebuild_lpsn_phase_20261105.py"
SPEC = importlib.util.spec_from_file_location("lpsn_phase_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture
def launch_case(tmp_path, monkeypatch):
    """Supply a synthetic canonical plan and intercept the fixed child command without executing it."""
    root = SCRIPT.parents[2]
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "prefix", str(root / ".venv"))
    monkeypatch.setattr(GATE, "EVIDENCE", tmp_path)
    canonical = {
        "phases": [["ontologies"], ["bacdive"], ["mediadive"], ["lpsn_api", "microbedecoder"]],
        "raw_directory": str(root / "data/raw"),
        "transformed_directory": str(root / "data/transformed"),
        "merged_directory": str(root / "data/merged"),
        "merge_config": str(root / "merge.yaml"),
    }
    monkeypatch.setattr(planner, "build_plan", lambda *args: copy.deepcopy(canonical))
    monkeypatch.setenv("LPSN_USERNAME", "synthetic-offline-username")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-offline-password")
    calls = []

    def launch(command, **kwargs):
        """Record only an offline launch request; never start a child or contact a service."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(GATE.subprocess, "run", launch)
    receipt = {
        "root": str(root),
        "status": "pass",
        "command": "verify-sources",
        "plan": copy.deepcopy(canonical),
        "verification": {"sources": {name: {} for name in ("ontologies", "bacdive", "mediadive")}},
    }
    source, output = tmp_path / "synthetic-phase3.json", tmp_path / "launch.json"

    def invoke(value):
        """Hash the submitted receipt exactly, including any adversarial change."""
        source.write_text(json.dumps(value))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                str(SCRIPT),
                "--label",
                "offline-fixture",
                "--phase3-receipt",
                str(source),
                "--phase3-sha256",
                digest,
                "--receipt",
                str(output),
            ],
        )
        return GATE.main()

    return SimpleNamespace(receipt=receipt, invoke=invoke, output=output, calls=calls)


@pytest.mark.parametrize("mutation", ["self_attested_empty", "foreign_root", "foreign_raw", "missing_source"])
def test_rehashed_receipt_cannot_change_canonical_prerequisites(launch_case, mutation):
    """Even a caller-provided valid digest cannot replace canonical predecessor scope or locations."""
    receipt = copy.deepcopy(launch_case.receipt)
    if mutation == "self_attested_empty":
        receipt["plan"]["phases"][:3] = [[], [], []]
        receipt["verification"]["sources"] = {}
    elif mutation == "foreign_root":
        receipt["root"] = "/synthetic/foreign-checkout"
    elif mutation == "foreign_raw":
        receipt["plan"]["raw_directory"] = "/synthetic/foreign-raw"
    else:
        del receipt["verification"]["sources"]["bacdive"]
    with pytest.raises(RuntimeError):
        launch_case.invoke(receipt)
    assert launch_case.calls == [] and not launch_case.output.exists()


def test_missing_environment_refuses_without_launch_or_evidence(launch_case, monkeypatch):
    """Missing credentials are a hold, never a file-search fallback."""
    monkeypatch.delenv("LPSN_PASSWORD")
    with pytest.raises(RuntimeError, match="already be available"):
        launch_case.invoke(launch_case.receipt)
    assert launch_case.calls == [] and not launch_case.output.exists()


def test_valid_prerequisites_keep_values_out_of_scoped_receipt(launch_case):
    """Exact canonical prerequisites launch only the fixed phase and serialize boolean availability."""
    assert launch_case.invoke(launch_case.receipt) == 0
    assert len(launch_case.calls) == 1
    command, options = launch_case.calls[0]
    assert command[-5:] == ["-s", "lpsn_api", "-s", "microbedecoder", "--no-show-status"]
    assert options == {"cwd": SCRIPT.parents[2], "check": False}
    text = launch_case.output.read_text()
    assert "synthetic-offline-username" not in text and "synthetic-offline-password" not in text
    record = json.loads(text)
    assert record["helper_credential_files_read"] is False
    assert record["helper_credential_values_recorded"] is False
    assert "load_dotenv" in record["child_credential_file_access"]
