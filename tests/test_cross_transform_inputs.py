"""A transform that reads another's output must declare it (#845)."""

import re
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform import DATA_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSFORM_ROOT = REPO_ROOT / "kg_microbe" / "transform_utils"

#: The three path idioms used to reach another transform's output. Each is in
#: live use, which is why a single pattern misses dependencies: an earlier
#: version of this scan caught `gold` and `prego` but not `microbedecoder`,
#: because that one goes via ``output_dir.parent``.
_UPSTREAM_PATTERNS = re.compile(
    r"transformed/([a-z_]+)/"
    r'|output_base_dir\s*/\s*["\']([a-z_]+)["\']'
    r'|output_dir\.parent\s*/\s*["\']([a-z_]+)["\']'
)


def _observed_dependencies():
    """
    Derive, from the source, which transforms read which others' output.

    :return: ``{source: {upstream, ...}}`` for sources with any dependency.
    """
    observed = {}
    for source in DATA_SOURCES:
        code_dir = TRANSFORM_ROOT / source
        if not code_dir.is_dir():
            continue
        found = set()
        for path in code_dir.rglob("*.py"):
            for match in _UPSTREAM_PATTERNS.finditer(path.read_text(encoding="utf-8")):
                name = next(group for group in match.groups() if group)
                if name != source and name in DATA_SOURCES:
                    found.add(name)
        if found:
            observed[source] = found
    return observed


class CrossTransformDeclarationTest(TestCase):
    """Derived from the code, so the declaration cannot quietly fall behind."""

    def test_every_observed_dependency_is_declared(self):
        """
        The contract is worthless if it is remembered rather than checked.

        Three prior versions of this same contract were opt-in and each was
        forgotten: #812 (DATA_INPUTS invented), #839 (ontologies_stubs declared
        1 of 11 files), #876 (gold gained a curation file and declared none).
        Every one was caught by a human reading a diff. This one is caught by
        the suite.
        """
        for source, upstreams in _observed_dependencies().items():
            declared = set(getattr(DATA_SOURCES[source], "TRANSFORM_INPUTS", ()))
            self.assertEqual(
                upstreams - declared,
                set(),
                f"{source} reads {sorted(upstreams - declared)} but does not declare it in "
                "TRANSFORM_INPUTS, so re-running that upstream leaves this output silently stale",
            )

    def test_the_known_dependencies_are_present(self):
        """
        Pin the premise, so a scan that silently stops matching is caught.

        If `_UPSTREAM_PATTERNS` ever fails to match — a new path idiom, a
        refactor — `_observed_dependencies()` returns less and the check above
        passes vacuously. This fails instead.
        """
        observed = _observed_dependencies()
        self.assertIn("ontologies", observed.get("gold", set()))
        self.assertIn("gtdb", observed.get("lpsn", set()))
        self.assertIn("lpsn", observed.get("microbedecoder", set()))

    def test_no_transform_declares_an_unregistered_upstream(self):
        """A typo would fold an always-absent marker in and never clear."""
        for source in DATA_SOURCES:
            for upstream in getattr(DATA_SOURCES[source], "TRANSFORM_INPUTS", ()):
                self.assertIn(upstream, DATA_SOURCES, f"{source} declares unknown upstream {upstream!r}")

    def test_no_transform_declares_itself(self):
        """Self-reference would make a transform permanently stale against itself."""
        for source in DATA_SOURCES:
            self.assertNotIn(source, getattr(DATA_SOURCES[source], "TRANSFORM_INPUTS", ()))

    def test_declared_upstreams_run_first(self):
        """
        `DATA_SOURCES` order is the run order for a bare `kg transform`.

        An upstream declared but scheduled later would be read stale on every
        full run — the ordering comments in that dict ("Run gold after
        ontologies…") are exactly this constraint, previously unchecked.
        """
        order = list(DATA_SOURCES)
        for source in order:
            for upstream in getattr(DATA_SOURCES[source], "TRANSFORM_INPUTS", ()):
                self.assertLess(
                    order.index(upstream),
                    order.index(source),
                    f"{upstream} must be registered before {source} in DATA_SOURCES",
                )
