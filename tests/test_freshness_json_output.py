"""kgm-freshness-check --json keeps stdout for the JSON payload alone (#1576)."""

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"

#: What the stand-in checks write to stdout, one string per route.
NOISE = ("ref-check noise", "not further classified", "descriptor-level noise", "child-process noise", "merge noise")


def _checker(monkeypatch):
    """Load the standalone skill script as a module, without installing it."""
    spec = importlib.util.spec_from_file_location("freshness_json_output_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _run_main(monkeypatch, checker, *flags):
    """Run main() with a ref check, one source check and a merge check that each print, as BacDive's does."""

    def noisy_ref_check(ref):
        """Stand in for the ref check, which can start `git fetch`."""
        print("ref-check noise")

    def noisy_check(source, ref):
        """Write to stdout from Python, at the descriptor and from a child process, then report."""
        print("  Detected '(not further classified)' pattern")
        os.write(1, b"descriptor-level noise\n")
        subprocess.run([sys.executable, "-c", "print('child-process noise')"], check=True)
        return checker.SourceReport(source, "FRESH", None, None, None, False)

    def noisy_merge_check(reports, ref):
        """Stand in for the merge check."""
        print("merge noise")
        return checker.MergeReport("FRESH", None, None, None, None, None, None)

    monkeypatch.setattr(checker, "_ensure_ref", noisy_ref_check)
    monkeypatch.setattr(checker, "check_source", noisy_check)
    monkeypatch.setattr(checker, "check_merge", noisy_merge_check)
    monkeypatch.setattr(sys, "argv", ["kgm_freshness_check.py", "--source", "fixture", *flags])
    return checker.main()


def test_json_mode_sends_what_the_checks_print_to_stderr(monkeypatch, capfd):
    """The payload parses even when the checks print, by any route."""
    checker = _checker(monkeypatch)
    assert _run_main(monkeypatch, checker, "--json") == 0
    out, err = capfd.readouterr()
    payload = json.loads(out)
    assert [row["source"] for row in payload["sources"]] == ["fixture"]
    assert payload["merge"]["status"] == "FRESH"
    for noise in NOISE:
        assert noise in err
    # Descriptor 1 is stdout again afterwards (print would not show it: pytest swaps sys.stdout).
    os.write(1, b"after main\n")
    assert capfd.readouterr() == ("after main\n", "")


def test_the_table_mode_keeps_everything_on_stdout(monkeypatch, capfd):
    """Only --json moves the checks' output; the human table keeps every route on stdout."""
    checker = _checker(monkeypatch)
    assert _run_main(monkeypatch, checker) == 0
    out, err = capfd.readouterr()
    for noise in NOISE:
        assert noise in out
    assert "SUMMARY" in out
    assert err == ""


def test_json_mode_in_a_real_process_flushes_buffered_writes_to_stderr(tmp_path):
    """
    With real pipes, writes still buffered when the checks end go to stderr, not before or after the payload.

    pytest's capture writes sys.stdout straight to its file, so only a separate
    process shows a write through a stream captured before main(), or C stdio's
    buffer, which nothing else flushes before the descriptor is restored.
    """
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import ctypes
            import importlib.util
            import sys

            spec = importlib.util.spec_from_file_location("freshness_json_driver", {str(SCRIPT)!r})
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            earlier = sys.stdout  # a stream captured before main(), as a logging handler would be

            def check(source, ref):
                earlier.write("stale-stream noise")  # no newline: still buffered when the block ends
                ctypes.CDLL(None).printf(b"c-stdio noise\\n")  # C stdio buffers a pipe fully
                return module.SourceReport(source, "FRESH", None, None, None, False)

            module.check_source = check
            module.check_merge = lambda reports, ref: module.MergeReport("FRESH", None, None, None, None, None, None)
            module._git = lambda args, cwd=None: "0123abc"
            sys.argv = ["kgm_freshness_check.py", "--skip-fetch", "--source", "fixture", "--json"]
            sys.exit(module.main())
            """
        )
    )
    child = subprocess.run(  # noqa: S603 - fixed interpreter and a driver this test wrote
        [sys.executable, "-B", str(driver)], capture_output=True, text=True, check=False
    )
    assert child.returncode == 0, child.stderr
    assert [row["source"] for row in json.loads(child.stdout)["sources"]] == ["fixture"]
    assert "stale-stream noise" in child.stderr
    assert "c-stdio noise" in child.stderr
