"""Exercise #1831 native gate routing with private synthetic children, never MIM producers."""

import configparser
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_pr_gates import candidate as candidate
from tests.test_pr_gates import invoke, recorded_commands

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_pr_gates.py"
NAMES = ("MIM_STABLE_TEST_PRODUCTS", "MIM_STABLE_TEST_PRODUCER", "MIM_STABLE_TEST_PYTHON")


def selected_inputs(root, monkeypatch):
    """Prepare synthetic selector bytes solely for the runner's locator evidence checks."""
    products = root.parent / "native-products"
    for name in (
        "candidate/manifest.json",
        "companion-output/manifest.json",
        "source-review.json",
        "companion-review.json",
    ):
        path = products / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"synthetic_gate_transport_only": true}\n')
    for name in (
        "tests/test_source_bindings.py",
        "src/mediaingredientmech/export/source_bindings.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic routing bytes; never imported\n")
    values = (products, root, Path(sys.executable).resolve())
    for name, value in zip(NAMES, values, strict=True):
        monkeypatch.setenv(name, str(value))
    return products


def test_tox_forwards_exactly_the_three_native_selectors():
    """Native tox forwarding is explicit and cannot depend on an external TOX override."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / "tox.ini")
    assert config["testenv"]["pass_env"].split() == list(NAMES)
    assert config["testenv"]["commands"].strip() == "poetry run pytest {posargs}"


def test_explicit_mode_preserves_the_single_native_final_command():
    """Ordinary final gates stay unchanged; required mode adds only its pytest enforcement option."""
    runner = runpy.run_path(str(RUNNER))
    ordinary = runner["gate_commands"](require_stable_mim=False)
    required = runner["gate_commands"](require_stable_mim=True)
    assert ordinary == runner["COMMANDS"]
    assert required[:-1] == ordinary[:-1]
    assert required[-1] == (*ordinary[-1], "--require-stable-mim")
    assert required[-1].count("--require-stable-mim") == 1
    evidence = runner["native_fixture_inputs"]({}, required=False)
    assert evidence == {"acceptance": "NOT_REQUESTED", "selectors": dict.fromkeys(NAMES)}


@pytest.mark.parametrize("missing", NAMES)
def test_required_runner_refuses_missing_selector_before_any_command(candidate, monkeypatch, missing):
    """Missing prerequisites cannot produce an apparently accepted final-gate receipt."""
    selected_inputs(candidate, monkeypatch)
    monkeypatch.delenv(missing)
    result = invoke(candidate, "--require-stable-mim")
    assert result.returncode != 0
    assert missing in result.stderr and "GATES_COMPLETE" not in result.stdout
    assert not (candidate.parent / "commands.jsonl").exists()


def test_required_runner_records_exact_inputs_and_forwards_selectors(candidate, monkeypatch):
    """The real CLI routes fixed selectors and fingerprints to its one final pytest command."""
    products = selected_inputs(candidate, monkeypatch)
    poetry = candidate.parent / "bin/poetry"
    source = poetry.read_text().replace("names = [", "names = " + repr(list(NAMES)) + " + [")
    poetry.write_text(source)
    monkeypatch.setenv("TOX_OVERRIDE", "testenv.pass_env=FAKE_BYPASS")
    result = invoke(candidate, "--require-stable-mim")
    assert result.returncode == 0, result.stderr
    commands = recorded_commands(candidate)
    assert len(commands) == 4
    assert commands[-1] == ["run", "--", "tox", "-e", "py", "--", "tests", "--durations=50", "--require-stable-mim"]
    report = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text())
    evidence = report[-1]["native_mim"]
    assert evidence["acceptance"] == "REQUIRED_BY_PYTEST"
    assert evidence["selectors"] == {name: os.environ[name] for name in NAMES}
    assert (
        evidence["input_sha256"][str(products / "candidate/manifest.json")]
        == hashlib.sha256((products / "candidate/manifest.json").read_bytes()).hexdigest()
    )
    assert (
        evidence["input_sha256"][str(Path(sys.executable).resolve())]
        == hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    )
    assert len(evidence["producer_commit"]) == 40
    child_environment = json.loads(Path(report[-1]["log"]).read_text().splitlines()[-1])
    assert {name: child_environment[name] for name in NAMES} == evidence["selectors"]
    assert child_environment["TOX_OVERRIDE"] is None
    assert child_environment["TOX_USER_CONFIG_FILE"] == os.devnull
    # Fake Poetry tests routing only; it never claims to execute native scientific controls.
    assert "Locator/byte evidence only" in evidence["qualification"]


def test_required_runner_refuses_changed_native_input_before_the_next_gate(candidate, monkeypatch):
    """A preserved byte-change observation cannot be relabeled as final native input evidence."""
    products = selected_inputs(candidate, monkeypatch)
    target = products / "candidate/manifest.json"
    poetry = candidate.parent / "bin/poetry"
    source = poetry.read_text()
    source += (
        "\nif arguments == ['check', '--lock']:\n    pathlib.Path("
        + repr(str(target))
        + ").write_text('changed synthetic input')\n"
    )
    poetry.write_text(source)
    result = invoke(candidate, "--require-stable-mim")
    assert result.returncode != 0 and "GATES_COMPLETE" not in result.stdout
    assert recorded_commands(candidate) == [["check", "--lock"]]
    report = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text())
    assert "changed during validation" in report[0]["native_input_error"]
    assert target.read_text() == "changed synthetic input"


def synthetic_pytest(
    tmp_path, *, body="pass", fixture_body="return None", required=True, extra=(), missing=None, module=True, marker=""
):
    """Run only synthetic plugin controls in a fresh isolated test tree with coverage disabled."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts =\n")
    name = "test_stable_source_candidate.py" if module else "test_unrelated.py"
    (tmp_path / name).write_text(
        "import pytest\n\n@pytest.fixture\ndef native_selection():\n    "
        + fixture_body
        + "\n\n"
        + marker
        + "def test_one(native_selection):\n    "
        + body
        + "\n\ndef test_actual_native_variant_through_consumer():\n    pass\n"
    )
    environment = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTEST_ADDOPTS="",
    )
    for selector in NAMES:
        environment[selector] = "explicit-synthetic-routing-control"
    if missing:
        environment.pop(missing)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "no:cov",
        "-p",
        "no:cacheprovider",
        "-p",
        "tests.stable_mim_gate",
        "--confcutdir",
        str(tmp_path),
    ]
    if required:
        command.append("--require-stable-mim")
    command.extend(extra)
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)  # noqa: S603 - fixed pytest and private synthetic test inputs
    (tmp_path / "child-stdout.txt").write_text(result.stdout)
    (tmp_path / "child-stderr.txt").write_text(result.stderr)
    (tmp_path / "child-command.json").write_text(
        json.dumps({"argv": command, "exit_status": result.returncode, "synthetic_only": True})
    )
    return result


def test_required_plugin_records_each_actual_native_phase(tmp_path):
    """Only complete setup/call/teardown outcomes receive COMPLETE in the synthetic plugin control."""
    result = synthetic_pytest(tmp_path)
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("NATIVE_STABLE_MIM_ACCEPTANCE "))
    evidence = json.loads(line.split(" ", 1)[1])
    assert evidence["status"] == "COMPLETE" and len(evidence["selected"]) == 2
    assert evidence["selected"] == evidence["discovered"]
    assert all(
        value == {"setup": "passed", "call": "passed", "teardown": "passed"} for value in evidence["outcomes"].values()
    )


@pytest.mark.parametrize(
    "body,fixture_body",
    [
        ("pytest.skip('synthetic missing input')", "return None"),
        ("pytest.xfail('synthetic unresolved')", "return None"),
        ("pass", "pytest.skip('synthetic setup skip')"),
        ("pass", "yield None\n    pytest.skip('synthetic teardown skip')"),
        ("pytest.fail('synthetic failure')", "return None"),
    ],
)
def test_native_skip_xfail_or_missing_phase_cannot_count_as_acceptance(tmp_path, body, fixture_body):
    """Required mode refuses native skips and incomplete executions without changing test assertions."""
    result = synthetic_pytest(tmp_path, body=body, fixture_body=fixture_body)
    assert result.returncode != 0
    assert '"status": "INCOMPLETE"' in result.stdout
    assert '"status": "COMPLETE"' not in result.stdout


@pytest.mark.parametrize(
    "extra,module", [((), False), (("-k", "one"), True), (("-k", "no_such_control"), True), (("--collect-only",), True)]
)
def test_passing_unrelated_or_deselected_controls_cannot_claim_acceptance(tmp_path, extra, module):
    """Missing native collection, partial deselection and collection-only runs all fail closed."""
    result = synthetic_pytest(tmp_path, extra=extra, module=module)
    assert result.returncode != 0
    assert '"status": "COMPLETE"' not in result.stdout


@pytest.mark.parametrize("missing", NAMES)
def test_required_pytest_refuses_missing_selector_before_skips(tmp_path, missing):
    """The actual pytest plugin enforces prerequisites even outside the final runner."""
    result = synthetic_pytest(tmp_path, missing=missing)
    assert result.returncode != 0 and missing in result.stderr
    assert '"status": "COMPLETE"' not in result.stdout


def test_ordinary_optional_run_does_not_claim_native_acceptance(tmp_path):
    """Unrelated ordinary runs may remain green with a skip but emit no native acceptance result."""
    result = synthetic_pytest(tmp_path, body="pytest.skip('native prerequisites absent')", required=False)
    assert result.returncode == 0
    assert "1 skipped" in result.stdout and "NATIVE_STABLE_MIM_ACCEPTANCE" not in result.stdout


def test_non_strict_xpass_cannot_count_as_native_acceptance(tmp_path):
    """An expected-failure mark remains visible even when pytest reports a passing call."""
    result = synthetic_pytest(
        tmp_path, marker="@pytest.mark.xfail(reason='synthetic expected failure', strict=False)\n"
    )
    assert result.returncode != 0
    line = next(line for line in result.stdout.splitlines() if line.startswith("NATIVE_STABLE_MIM_ACCEPTANCE "))
    evidence = json.loads(line.split(" ", 1)[1])
    assert evidence["status"] == "INCOMPLETE"
    marked = next(nodeid for nodeid in evidence["xfail"] if nodeid.endswith("::test_one"))
    assert evidence["outcomes"][marked]["call"] == "passed"
    assert evidence["xfail"][marked]["call"] == "synthetic expected failure"
