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

#: `constants.py` defines module-level paths into another transform's output
#: directory, e.g.
#:
#:     ONTOLOGIES_TRANSFORMED_DIR = TRANSFORMED_DATA_DIR / ONTOLOGIES
#:     NCBITAXON_NODES_FILE = ONTOLOGIES_TRANSFORMED_DIR / "ncbitaxon_nodes.tsv"
#:
#: A transform that imports `NCBITAXON_NODES_FILE` writes no path of its own, so
#: the scan above cannot see the dependency: bacdive, mediadive and metatraits
#: each read `ontologies/` this way and the guard passed for months (#1035).
#: Resolve the constants first, then look for their *names* in each transform.
_CONSTANTS_FILE = TRANSFORM_ROOT / "constants.py"
_DIR_CONSTANT = re.compile(
    r"^([A-Z][A-Z0-9_]*) *= *TRANSFORMED_DATA_DIR *(?:/ *([A-Z][A-Z0-9_]*)|/ *[\"\']([a-z_]+)[\"\'])", re.M
)
_FILE_CONSTANT = re.compile(r"^([A-Z][A-Z0-9_]*) *= *([A-Z][A-Z0-9_]*) *//? *[\"\']", re.M)


def _constants_naming_a_transform_output():
    """
    Map every constant in ``constants.py`` that points into a transform's output.

    :return: ``{constant name: source name}``.
    """
    text = _CONSTANTS_FILE.read_text(encoding="utf-8")
    # Which source each *directory* constant names. The source may be spelled as
    # a literal or as the SOURCE-name constant (ONTOLOGIES = "ontologies").
    literals = dict(re.findall(r"^([A-Z][A-Z0-9_]*) *= *[\"\']([a-z_]+)[\"\'] *(?:#.*)?$", text, re.M))
    dirs = {}
    for name, via_constant, via_literal in _DIR_CONSTANT.findall(text):
        source = via_literal or literals.get(via_constant)
        if source in DATA_SOURCES:
            dirs[name] = source
    # Then every file constant built on one of those directories.
    resolved = dict(dirs)
    for name, parent in _FILE_CONSTANT.findall(text):
        if parent in resolved:
            resolved[name] = resolved[parent]
    return resolved


def _observed_dependencies():
    """
    Derive, from the source, which transforms read which others' output.

    :return: ``{source: {upstream, ...}}`` for sources with any dependency.
    """
    constants = _constants_naming_a_transform_output()
    observed = {}
    for source in DATA_SOURCES:
        code_dir = TRANSFORM_ROOT / source
        if not code_dir.is_dir():
            continue
        found = set()
        for path in code_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in _UPSTREAM_PATTERNS.finditer(text):
                name = next(group for group in match.groups() if group)
                if name != source and name in DATA_SOURCES:
                    found.add(name)
            for constant, upstream in constants.items():
                if upstream != source and re.search(rf"\b{constant}\b", text):
                    found.add(upstream)
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
        # Reached only through a constants.py path; see _constants_naming_a_transform_output (#1035).
        self.assertIn("ontologies", observed.get("bacdive", set()))
        self.assertIn("ontologies", observed.get("mediadive", set()))
        self.assertIn("ontologies", observed.get("metatraits", set()))

    def test_a_constant_pointing_into_a_transform_output_is_resolved(self):
        """The premise of the constants scan, pinned so a refactor cannot quietly empty it."""
        resolved = _constants_naming_a_transform_output()
        self.assertEqual(resolved.get("NCBITAXON_NODES_FILE"), "ontologies")
        self.assertEqual(resolved.get("CHEBI_NODES_FILE"), "ontologies")
        self.assertEqual(resolved.get("ONTOLOGIES_TRANSFORMED_DIR"), "ontologies")

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
