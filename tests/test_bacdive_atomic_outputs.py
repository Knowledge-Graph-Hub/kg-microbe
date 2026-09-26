"""bacdive publishes nodes.tsv/edges.tsv atomically, or not at all (#1036)."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACDIVE = REPO_ROOT / "kg_microbe" / "transform_utils" / "bacdive" / "bacdive.py"


def _write_opens_of(attr: str):
    """Return line numbers where ``self.<attr>`` is opened for writing with the builtin ``open``."""
    found = []
    for node in ast.walk(ast.parse(BACDIVE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "open":
            continue
        if not node.args:
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Attribute) and target.attr == attr):
            continue
        mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else ""
        if "w" in str(mode):
            found.append(node.lineno)
    return found


def test_the_graph_outputs_are_not_opened_for_truncating_writes():
    """
    A SIGTERM during the 2026-09-10 rebuild left 173 MB of a 633 MB build.

    Nothing marked it partial, and the merge reads whatever pair is on disk.
    The later `drop_duplicates` rewrite was already atomic; the big csv.writer
    block before it was the gap.
    """
    for attr in ("output_node_file", "output_edge_file"):
        bare = _write_opens_of(attr)
        assert not bare, f"self.{attr} is opened with a truncating open() at line(s) {bare}; use atomic_write"


def test_both_outputs_go_through_atomic_write():
    """Pin the positive, so deleting the writes entirely would not pass the check above."""
    source = BACDIVE.read_text(encoding="utf-8")
    assert 'atomic_write(self.output_node_file, newline="")' in source
    assert 'atomic_write(self.output_edge_file, newline="")' in source


def test_appending_stubs_is_still_allowed():
    """
    The stub pass appends to a file the atomic write has already published.

    That is deliberate and must not be mistaken for the defect: it runs after
    the context manager closes, so it never sees a partial file.
    """
    source = BACDIVE.read_text(encoding="utf-8")
    assert 'open(self.output_node_file, "a"' in source
