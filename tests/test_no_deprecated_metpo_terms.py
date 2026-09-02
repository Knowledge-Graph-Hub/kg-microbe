"""The graph must not assert METPO terms the pinned release has retired (#909)."""

import ast
import re
from pathlib import Path

import pytest

from kg_microbe.utils.metpo_liveness import (
    KNOWN_DEPRECATED,
    deprecated_metpo_terms,
    metpo_json_path,
    vendored_deprecated_terms,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = [REPO_ROOT / "kg_microbe"]
_CURIE = re.compile(r"\bMETPO:\d{6,7}\b")

#: The pinned release declares this many deprecated terms. A local metpo.json
#: with none is not that release — it is the pre-#900 cache, and #911 explains
#: why `kg download` leaves it in place. Skipping loudly beats passing quietly.
_EXPECTED_DEPRECATED_FLOOR = 1


def _require_pinned_ontology():
    path = metpo_json_path()
    if not path.is_file():
        pytest.skip(f"{path} not downloaded; run `kg download -i -t ontologies`")
    deprecated = deprecated_metpo_terms()
    if len(deprecated) < _EXPECTED_DEPRECATED_FLOOR:
        pytest.skip(
            f"{path} declares no deprecated terms, so it is not the pinned release "
            "(see #911: `kg download` skips existing files, so a changed pin does not "
            "refresh the cache). Run `kg download -i -t ontologies`."
        )
    return deprecated


def _curies_in_code(path: Path):
    """
    METPO CURIEs a module actually uses, ignoring comments and docstrings.

    Scanning raw text flags every mention — including a comment explaining why a
    term was removed, which would make the check fire on its own fix. Only string
    literals that are not docstrings can reach the graph.

    :param path: Python module to scan.
    :return: Set of CURIEs appearing in live code.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found.update(_CURIE.findall(node.value))
    return found


def test_the_vendored_list_matches_the_pinned_ontology():
    """
    The vendored set must not drift from the release it claims to describe.

    It exists so the scans run in CI (#924); reconciling it here is what stops it
    becoming a stale allowlist of its own. This is the only check that needs the
    ontology, so it is the only one that skips without it.
    """
    deprecated = _require_pinned_ontology()
    vendored = vendored_deprecated_terms()
    assert vendored == deprecated, (
        f"vendored list is stale ({len(vendored)} vs {len(deprecated)} in the ontology); "
        "run scripts/refresh_deprecated_metpo_curies.py"
    )


def _require_vendored():
    """
    Return the vendored deprecated set, which is committed and so available everywhere.

    :return: Set of deprecated CURIEs.
    """
    vendored = vendored_deprecated_terms()
    assert vendored, "tests/resources/metpo_deprecated_curies.txt is missing or empty"
    return vendored


def test_the_allowlist_only_holds_terms_that_are_actually_deprecated():
    """
    An entry that is no longer deprecated is debt that has silently been paid.

    Left in place it hides the next real one, because the reader assumes the
    allowlist is current.
    """
    deprecated = _require_vendored()
    stale = sorted(set(KNOWN_DEPRECATED) - deprecated)
    assert not stale, f"no longer deprecated upstream, drop from KNOWN_DEPRECATED: {stale}"


def test_every_allowlisted_term_names_its_tracking_issue():
    """An exemption without an issue is just a silenced check."""
    unreferenced = sorted(c for c, ref in KNOWN_DEPRECATED.items() if not re.fullmatch(r"#\d+", ref or ""))
    assert not unreferenced, f"allowlisted without a tracking issue: {unreferenced}"


def test_no_new_deprecated_metpo_term_is_referenced_in_code():
    """
    The check that would have caught #909 on the day the obsoletion landed.

    `METPO:2000511` reached 706,765 edges and `METPO:1001000` reached 503 node
    categories because both are hardcoded constants: the ontology changed under
    them and nothing compared what we emit against what it declares.
    """
    deprecated = _require_vendored()
    offenders = {}
    for root in CODE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            for curie in sorted(_curies_in_code(path)):
                if curie in deprecated and curie not in KNOWN_DEPRECATED:
                    offenders.setdefault(curie, []).append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, "deprecated METPO terms referenced in code: " + "; ".join(
        f"{c} in {', '.join(p)}" for c, p in sorted(offenders.items())
    )


def test_the_assay_category_no_longer_carries_the_obsolete_observation_class():
    """
    `METPO:1001000` was carried only to satisfy the range of `METPO:2000511`.

    Both are obsolete upstream, so the class was asserting a retired term on 503
    nodes and buying nothing — a range that no longer exists cannot be satisfied.
    """
    from kg_microbe.transform_utils.constants import ASSAY_CATEGORY

    assert ASSAY_CATEGORY == "biolink:Procedure"
    assert "METPO:1001000" not in ASSAY_CATEGORY


def test_transform_outputs_carry_no_unexpected_deprecated_term():
    """
    Guard the artifacts too, not just the source.

    A CURIE can reach the graph from a mapping TSV without appearing in any
    Python file, which the source scan above would miss entirely.

    Sweeps predicates, node categories and edge endpoints across every transform
    — not just bacdive's predicate column. `METPO:1001000` was deprecated while
    sitting in the *category* of 503 assay nodes, so a predicate-only scan of one
    transform would have missed the defect that motivated this check (#925).
    """
    deprecated = _require_vendored()
    transformed = REPO_ROOT / "data" / "transformed"
    if not transformed.is_dir():
        pytest.skip("no transform output present")
    offenders = {}

    def note(curie, where):
        if curie in deprecated and curie not in KNOWN_DEPRECATED:
            offenders.setdefault(curie, set()).add(where)

    for edges in sorted(transformed.glob("*/edges.tsv")):
        with edges.open(encoding="utf-8", errors="replace") as handle:
            handle.readline()
            for line in handle:
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 3:
                    continue
                note(fields[1], f"{edges.parent.name}/edges.tsv predicate")
                for endpoint in (fields[0], fields[2]):
                    note(endpoint, f"{edges.parent.name}/edges.tsv endpoint")
    for nodes in sorted(transformed.glob("*/nodes.tsv")):
        with nodes.open(encoding="utf-8", errors="replace") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            category_at = header.index("category") if "category" in header else 1
            for line in handle:
                fields = line.rstrip("\n").split("\t")
                if len(fields) <= category_at:
                    continue
                # Multi-category is exactly how METPO:1001000 was carried.
                for token in fields[category_at].split("|"):
                    note(token, f"{nodes.parent.name}/nodes.tsv category")
                note(fields[0], f"{nodes.parent.name}/nodes.tsv id")

    assert not offenders, (
        "deprecated METPO terms in transform output: "
        + "; ".join(f"{curie} in {sorted(where)}" for curie, where in sorted(offenders.items()))
        + ". If the code no longer references the term, the artifact predates the fix and the "
        "transform needs rerunning — this checks what was shipped, not what would be shipped now."
    )
