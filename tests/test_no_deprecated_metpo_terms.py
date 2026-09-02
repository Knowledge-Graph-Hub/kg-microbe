"""The graph must not assert METPO terms the pinned release has retired (#909)."""

import ast
import re
from pathlib import Path

import pytest

from kg_microbe.utils.metpo_liveness import (
    KNOWN_DEPRECATED,
    deprecated_metpo_terms,
    metpo_json_path,
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


def test_the_allowlist_only_holds_terms_that_are_actually_deprecated():
    """
    An entry that is no longer deprecated is debt that has silently been paid.

    Left in place it hides the next real one, because the reader assumes the
    allowlist is current.
    """
    deprecated = _require_pinned_ontology()
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
    deprecated = _require_pinned_ontology()
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


def test_transform_outputs_carry_no_unexpected_deprecated_term(tmp_path):
    """
    Guard the artifacts too, not just the source.

    A CURIE can reach the graph from a mapping TSV without appearing in any
    Python file, which the source scan above would miss entirely.
    """
    deprecated = _require_pinned_ontology()
    edges = REPO_ROOT / "data" / "transformed" / "bacdive" / "edges.tsv"
    if not edges.is_file():
        pytest.skip("bacdive transform output not present")
    seen = set()
    with edges.open(encoding="utf-8", errors="replace") as handle:
        handle.readline()
        for line in handle:
            fields = line.split("\t")
            if len(fields) > 2 and fields[1].startswith("METPO:"):
                seen.add(fields[1])
    offenders = sorted((seen & deprecated) - set(KNOWN_DEPRECATED))
    assert not offenders, f"deprecated METPO predicates in bacdive/edges.tsv: {offenders}"
