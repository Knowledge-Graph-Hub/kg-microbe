"""KG-Microbe writes LF, not CRLF, in every TSV another tool parses (#1041)."""

import ast
import io
from pathlib import Path

import pytest

from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules that write a nodes/edges TSV or a report beside one. A bare
#: ``csv.writer`` here reintroduces CRLF into the shipped graph.
GRAPH_WRITERS = (
    "kg_microbe/merge_utils/merge_kg.py",
    "kg_microbe/merge_utils/invariants.py",
    "kg_microbe/transform_utils/gtdb/gtdb.py",
    "kg_microbe/transform_utils/lpsn/lpsn.py",
    "kg_microbe/transform_utils/lpsn_api/lpsn_api.py",
    "kg_microbe/transform_utils/gold/gold.py",
)


def _bare_csv_writers(path: Path):
    """Return the line numbers of ``csv.writer``/``csv.DictWriter`` calls without an explicit terminator."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"writer", "DictWriter"}:
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "csv"):
            continue
        if any(kw.arg == "lineterminator" for kw in node.keywords):
            continue
        found.append(node.lineno)
    return found


@pytest.mark.parametrize("relpath", GRAPH_WRITERS)
def test_graph_writers_do_not_use_a_bare_csv_writer(relpath):
    """
    csv.writer defaults to lineterminator="\\r\\n" on every platform.

    `newline=""` does not change it -- gold, lpsn and lpsn_api all passed
    `newline=""` and still emitted CRLF, which is how every line of the shipped
    merged graph ended with a carriage return.
    """
    bare = _bare_csv_writers(REPO_ROOT / relpath)
    assert not bare, (
        f"{relpath} constructs csv.writer/DictWriter without lineterminator at line(s) {bare}; "
        "use kg_microbe.utils.tsv_io.tsv_writer / tsv_dict_writer"
    )


def test_the_helper_writes_lf_where_a_bare_writer_writes_crlf():
    """The premise, pinned: this is the difference the whole change rests on."""
    import csv

    bare = io.StringIO()
    csv.writer(bare, delimiter="\t").writerow(["a", "b"])
    assert bare.getvalue() == "a\tb\r\n", "if this ever changes, the guard above is obsolete"

    ours = io.StringIO()
    tsv_writer(ours).writerow(["a", "b"])
    assert ours.getvalue() == "a\tb\n"


def test_the_dict_helper_writes_lf_too():
    """Header and rows both, since gtdb writes its nodes file through DictWriter."""
    buf = io.StringIO()
    writer = tsv_dict_writer(buf, ["id", "name"])
    writer.writeheader()
    writer.writerow({"id": "X:1", "name": "n"})
    assert buf.getvalue() == "id\tname\nX:1\tn\n"


def test_an_empty_last_field_is_empty_not_a_carriage_return():
    """
    The corruption this prevents: a trailing CR lands in the last column.

    An "empty" last field then holds "\\r", so a truthiness test on it inverts --
    which is how a count of gtdb nodes carrying a `same_as` read 901,341 instead
    of 447,137.
    """
    buf = io.StringIO()
    tsv_writer(buf).writerow(["ncbi.assembly:GCA_1.1", "biolink:Genome", ""])
    assert buf.getvalue().split("\n")[0].split("\t")[-1] == ""
