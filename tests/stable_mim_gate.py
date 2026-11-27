"""Require actual native MIM control outcomes only when acceptance is explicitly selected."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

SELECTORS = ("MIM_STABLE_TEST_PRODUCTS", "MIM_STABLE_TEST_PRODUCER", "MIM_STABLE_TEST_PYTHON")
_STATE = pytest.StashKey[dict]()
# The committed pyproject uses these pytest defaults; changing them changes
# the acceptance inventory and requires an explicit policy update.
COLLECTION_PATTERNS = {
    "python_files": ["test_*.py", "*_test.py"],
    "python_classes": ["Test"],
    "python_functions": ["test"],
}


def pytest_addoption(parser):
    """Keep explicit native acceptance separate from ordinary optional local test coverage."""
    parser.addoption(
        "--require-stable-mim",
        action="store_true",
        default=False,
        help="fail unless native MIM prerequisites exist and all native controls actually pass",
    )


def pytest_configure(config):
    """Reject missing required selectors before any native prerequisite can be skipped."""
    required = config.getoption("--require-stable-mim")
    config.addinivalue_line("markers", "native_mim_combined: genuine native combined-source reconstruction control")
    config.stash[_STATE] = {
        "required": required,
        "discovered": set(),
        "selected": set(),
        "outcomes": {},
        "xfail": {},
        "groups": set(),
    }
    if required:
        missing = [name for name in SELECTORS if not os.environ.get(name)]
        if missing:
            raise pytest.UsageError("Required native MIM prerequisites missing: " + ", ".join(missing))
        _require_full_tests_root(config)


def _require_full_tests_root(config):
    """Reject precollection subsets that could hide required native controls."""
    arguments = config.args
    expected = (config.rootpath / "tests").resolve()
    complete = len(arguments) == 1 and (config.invocation_params.dir / Path(arguments[0])).resolve() == expected
    exclusions = ("ignore", "ignore_glob", "deselect", "lf", "pyargs", "inifilename", "override_ini", "rootdir")
    default_patterns = all(config.getini(name) == patterns for name, patterns in COLLECTION_PATTERNS.items())
    if not complete or not default_patterns or any(config.getoption(name, default=None) for name in exclusions):
        raise pytest.UsageError(
            "Required native MIM acceptance requires the complete tests root without file/node selection "
            "or collection/configuration overrides; use ordinary pytest mode for focused checks"
        )


def _native_group(item):
    """Collect both existing source controls and explicitly marked combined controls."""
    if item.get_closest_marker("native_mim_combined") is not None:
        return "combined"
    if item.path.name == "test_stable_source_candidate.py" and (
        "native_selection" in item.fixturenames or item.originalname == "test_actual_native_variant_through_consumer"
    ):
        return "source"
    return None


def _native(item):
    """Identify every required native control without weakening historical coverage."""
    return _native_group(item) is not None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Remember native controls before standard -k/-m deselection can hide them."""
    state = config.stash[_STATE]
    if state["required"]:
        state["discovered"].update(item.nodeid for item in items if _native(item))
        state["groups"].update(_native_group(item) for item in items if _native(item))


def pytest_collection_finish(session):
    """Require a nonempty, undeselected native scope for a run claiming acceptance."""
    state = session.config.stash[_STATE]
    if not state["required"]:
        return
    state["selected"] = {item.nodeid for item in session.items if _native(item)}
    if not state["selected"] or state["selected"] != state["discovered"] or state["groups"] != {"source", "combined"}:
        raise pytest.UsageError(
            "Required native MIM source and combined controls were not collected or were deselected"
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Retain actual setup/call/teardown outcomes, including skips and xfails."""
    outcome = yield
    state = item.config.stash[_STATE]
    if state["required"] and item.nodeid in state["selected"]:
        report = outcome.get_result()
        state["outcomes"].setdefault(item.nodeid, {})[report.when] = report.outcome
        if hasattr(report, "wasxfail"):
            state["xfail"].setdefault(item.nodeid, {})[report.when] = report.wasxfail


def pytest_sessionfinish(session, exitstatus):
    """Fail closed when any native control skipped or lacks a complete passing execution."""
    state = session.config.stash.get(_STATE, None)
    if not state or not state["required"]:
        return
    complete = (
        bool(state["selected"])
        and state["groups"] == {"source", "combined"}
        and not state["xfail"]
        and state["selected"] == state["discovered"]
        and all(
            state["outcomes"].get(nodeid) == {"setup": "passed", "call": "passed", "teardown": "passed"}
            for nodeid in state["selected"]
        )
    )
    if not complete:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    state["status"] = "COMPLETE" if complete and exitstatus == 0 else "INCOMPLETE"


def pytest_terminal_summary(terminalreporter):
    """Publish exact native control outcomes; passing unrelated tests is not native acceptance."""
    state = terminalreporter.config.stash.get(_STATE, None)
    if not state or not state["required"]:
        return
    evidence = {
        "status": state.get("status", "INCOMPLETE"),
        "selectors": {name: os.environ.get(name) for name in SELECTORS},
        "discovered": sorted(state["discovered"]),
        "groups": sorted(state["groups"]),
        "selected": sorted(state["selected"]),
        "outcomes": state["outcomes"],
        "xfail": state["xfail"],
    }
    terminalreporter.write_line("NATIVE_STABLE_MIM_ACCEPTANCE " + json.dumps(evidence, sort_keys=True))
