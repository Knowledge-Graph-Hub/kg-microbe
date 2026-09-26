"""Grandfathered lint debt in scripts/ must stay honest (#950, #968)."""

import re
import shutil
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO = Path(__file__).resolve().parent.parent

#: Ruff needs its own config ignored, or the per-file-ignores under test would
#: suppress the very findings this asks it to report.
ISOLATED = ["--isolated", "--line-length", "120", "--target-version", "py310"]


def _debt():
    """
    Return the per-file ignores declared for ``scripts/``.

    :return: ``{path: {rule, ...}}``.
    """
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    return {path: set(rules) for path, rules in ignores.items() if path.startswith("scripts/")}


def _findings(rules):
    """
    Run ruff over ``scripts/`` for ``rules``, bypassing the repo config.

    :param rules: Rule codes to select.
    :return: ``{path: {rule, ...}}`` actually reported.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            shutil.which("ruff") or "ruff",
            "check",
            "scripts/",
            *ISOLATED,
            "--select",
            ",".join(sorted(rules)),
            "--no-cache",
            "--output-format",
            "concise",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    found = defaultdict(set)
    for line in result.stdout.splitlines():
        match = re.match(r"(scripts/\S+?):\d+:\d+: ([A-Z]+\d{3})", line)
        if match:
            found[match.group(1)].add(match.group(2))
    return found


class ScriptsLintDebtTests(unittest.TestCase):
    """An exemption nobody needs is permission nobody asked for."""

    def test_no_exemption_is_dead(self):
        """
        Every grandfathered rule must still fire on the file that claims it.

        Otherwise the list only grows: a rule fixed in passing keeps its
        exemption, nothing distinguishes real debt from long-paid debt, and the
        block reads as load-bearing forever. Checking it by hand is exactly the
        kind of check that stops being run (#968).
        """
        if shutil.which("ruff") is None:
            self.skipTest("ruff not on PATH")
        debt = _debt()
        self.assertTrue(debt, "no scripts/ entries found; this guard needs rewriting")
        found = _findings({rule for rules in debt.values() for rule in rules})
        dead = {path: sorted(rules - found.get(path, set())) for path, rules in debt.items()}
        dead = {path: rules for path, rules in dead.items() if rules}
        self.assertEqual(dead, {}, f"exemptions that no longer fire — delete them: {dead}")

    def test_the_debt_is_scoped_per_file_not_to_the_directory(self):
        """
        A `scripts/*` entry would exempt the clean scripts and every future one.

        That is the difference between grandfathering the debt and abandoning
        the directory, and it is invisible once written (#968).
        """
        config = tomllib.loads((REPO / "pyproject.toml").read_text())
        ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
        wildcards = [path for path in ignores if path.startswith("scripts/") and "*" in path]
        self.assertEqual(wildcards, [], f"scripts/ debt must be listed per file, not as {wildcards}")

    def test_every_listed_file_exists(self):
        """A path that no longer exists is debt recorded against nothing."""
        missing = [path for path in _debt() if not (REPO / path).is_file()]
        self.assertEqual(missing, [], f"per-file-ignores name files that are gone: {missing}")


if __name__ == "__main__":
    unittest.main()
