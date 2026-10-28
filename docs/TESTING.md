# Testing policy

Use focused tests during development and one full suite for final PR validation.
This changes when tests run, not their assertions, markers or coverage. Repository
validation remains separate from source freshness and graph-release acceptance.

## While editing

Run the tests for the changed behavior, affected downstream contracts and previous
failures. Name the relevant files or node IDs explicitly, for example:

```bash
poetry run pytest tests/test_bacdive_provenance.py -q
```

Expand the selection when changes affect shared behavior or a failure exposes
another dependency. A full suite is not required for every commit. Do not rerun
unrelated tests merely to produce a progress update.

## Prepare the final candidate

Run the explicit source-editing tools before final validation:

```bash
poetry run tox -e format,codespell-write
```

Review the diff and commit the intended changes. Preserve unrelated work; never
discard all diffs to obtain a clean tree. Use an isolated worktree when needed.
The final gate requires a clean tracked candidate, including the staging area.

## Validate once

On the prepared, committed candidate, choose a descriptive run label and run:

```bash
poetry run python scripts/run_pr_gates.py <label>
```

The runner checks the Poetry lock and generated merge configuration, runs the
read-only formatting, lint, spelling and docstring checks, then invokes the full
pytest suite once through `tox -e py -- tests --durations=50`. Naming `tests/`
prevents discovery in scratch worktrees and generated data. Cheap checks fail
before the expensive suite starts. The runner uses explicit tox environments,
clears inherited `TOX*` and `PYTEST_ADDOPTS` settings, and disables tox's per-user
configuration so development overrides cannot silently skip final checks.
It records the candidate and gate results for review.

Do not run a separate full `poetry run pytest` before or after this command.
Default `poetry run tox` also contains one full test run and checks source files
without rewriting them; the runner additionally provides lock/config checks and
the final-candidate record. Test outputs and tool caches may still be written.

Reuse successful evidence only for the unchanged candidate and environment.
Changed code, dependencies or test inputs require validation appropriate to that
change; do not relabel an earlier run as evidence for a new candidate. Fix failures
with focused tests, prepare the new candidate, and complete its final gate before
handoff. A failed gate is not a passing result.

## CI and release checks

CI continues to run the test suite across supported Python versions. Those
environment checks remain necessary even after a local pass. Source freshness,
transform replay, graph/model/path review and release checks retain their own
requirements; a green code test suite does not establish graph-release readiness.

Use the final run's duration report to identify expensive tests before proposing
fixture or test changes. Do not remove cases, weaken assertions, exclude markers
or reduce coverage merely to shorten validation. Historical reports retain the
commands and results actually used at the time.
