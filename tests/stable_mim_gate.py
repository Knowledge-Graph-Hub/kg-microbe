"""Require actual native MIM control outcomes only when acceptance is explicitly selected."""

from __future__ import annotations

import json
import os

import pytest

SELECTORS = ("MIM_STABLE_TEST_PRODUCTS", "MIM_STABLE_TEST_PRODUCER", "MIM_STABLE_TEST_PYTHON")
_STATE = pytest.StashKey[dict]()


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
    config.stash[_STATE] = {"required": required, "discovered": set(), "selected": set(), "outcomes": {}, "xfail": {}}
    if required:
        missing = [name for name in SELECTORS if not os.environ.get(name)]
        if missing:
            raise pytest.UsageError("Required native MIM prerequisites missing: " + ", ".join(missing))


def _native(item):
    """Select existing native-fixture controls, including every parameterized variant."""
    return item.path.name == "test_stable_source_candidate.py" and (
        "native_selection" in item.fixturenames or item.originalname == "test_actual_native_variant_through_consumer"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Remember native controls before standard -k/-m deselection can hide them."""
    state = config.stash[_STATE]
    if state["required"]:
        state["discovered"].update(item.nodeid for item in items if _native(item))


def pytest_collection_finish(session):
    """Require a nonempty, undeselected native scope for a run claiming acceptance."""
    state = session.config.stash[_STATE]
    if not state["required"]:
        return
    state["selected"] = {item.nodeid for item in session.items if _native(item)}
    if not state["selected"] or state["selected"] != state["discovered"]:
        raise pytest.UsageError("Required native MIM controls were not collected or were deselected")


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
        "selected": sorted(state["selected"]),
        "outcomes": state["outcomes"],
        "xfail": state["xfail"],
    }
    terminalreporter.write_line("NATIVE_STABLE_MIM_ACCEPTANCE " + json.dumps(evidence, sort_keys=True))
