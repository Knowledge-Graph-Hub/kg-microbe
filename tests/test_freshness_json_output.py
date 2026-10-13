"""kgm-freshness-check --json keeps stdout for the JSON payload alone (#1576)."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"


def _checker(monkeypatch):
    """Load the standalone skill script as a module, without installing it."""
    spec = importlib.util.spec_from_file_location("freshness_json_output_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _run_main(monkeypatch, checker, *flags):
    """Run main() on one stand-in source whose check prints the way BacDive's verification does."""

    def noisy_check(source, ref):
        """Write to stdout from Python, at the descriptor and from a child process, then report."""
        print("  Detected '(not further classified)' pattern")
        os.write(1, b"descriptor-level noise\n")
        subprocess.run([sys.executable, "-c", "print('child-process noise')"], check=True)
        return checker.SourceReport(source, "FRESH", None, None, None, False)

    monkeypatch.setattr(checker, "check_source", noisy_check)
    monkeypatch.setattr(
        checker, "check_merge", lambda reports, ref: checker.MergeReport("FRESH", None, None, None, None, None, None)
    )
    monkeypatch.setattr(checker, "_git", lambda args, cwd=None: "0123abc")
    monkeypatch.setattr(sys, "argv", ["kgm_freshness_check.py", "--skip-fetch", "--source", "fixture", *flags])
    return checker.main()


def test_json_mode_sends_what_the_checks_print_to_stderr(monkeypatch, capfd):
    """The payload parses even when a source's verification prints, by any route."""
    checker = _checker(monkeypatch)
    assert _run_main(monkeypatch, checker, "--json") == 0
    out, err = capfd.readouterr()
    payload = json.loads(out)
    assert [row["source"] for row in payload["sources"]] == ["fixture"]
    assert payload["merge"]["status"] == "FRESH"
    for noise in ("not further classified", "descriptor-level noise", "child-process noise"):
        assert noise in err
    # Descriptor 1 is stdout again afterwards (print would not show it: pytest swaps sys.stdout).
    os.write(1, b"after main\n")
    assert capfd.readouterr() == ("after main\n", "")


def test_the_table_mode_still_prints_to_stdout(monkeypatch, capfd):
    """Only --json moves the checks' output; the human table keeps everything on stdout."""
    checker = _checker(monkeypatch)
    assert _run_main(monkeypatch, checker) == 0
    out, _ = capfd.readouterr()
    assert "not further classified" in out
    assert "SUMMARY" in out
