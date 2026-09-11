r"""KG-Microbe writes LF, not CRLF, in every TSV another tool parses (#1041)."""

import ast
import io
from pathlib import Path

import pytest

from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSFORMED = REPO_ROOT / "data" / "transformed"

#: Every module that can write a graph TSV, enumerated rather than listed.
#: The first version of this guard carried a hand-written list of seven files
#: and silently missed `prego`, `rhea_mappings`, `metatraits`,
#: `metatraits_gtdb` and `microbedecoder` -- 11 CRLF files still shipped. A
#: list someone has to remember to extend is the same failure mode #1035 was
#: about, so the scan now walks the trees.
SCANNED_TREES = ("kg_microbe/transform_utils", "kg_microbe/merge_utils")


def _modules():
    """Yield every Python module under the scanned trees."""
    for tree in SCANNED_TREES:
        yield from sorted((REPO_ROOT / tree).rglob("*.py"))


def _bare_csv_writers(path: Path):
    """Return line numbers of ``csv.writer``/``csv.DictWriter`` calls without an explicit terminator."""
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


@pytest.mark.parametrize("module", list(_modules()), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_module_uses_a_bare_csv_writer(module):
    r"""
    csv.writer defaults to lineterminator="\r\n" on every platform.

    `newline=""` does not change it -- gold, lpsn and lpsn_api all passed
    `newline=""` and still emitted CRLF, which is how every line of the shipped
    merged graph ended with a carriage return.
    """
    bare = _bare_csv_writers(module)
    assert not bare, (
        f"{module.relative_to(REPO_ROOT)} constructs csv.writer/DictWriter without lineterminator "
        f"at line(s) {bare}; use kg_microbe.utils.tsv_io.tsv_writer / tsv_dict_writer"
    )


def test_the_scan_actually_covers_the_transforms():
    """A glob that silently matches nothing would make every check above vacuous."""
    modules = list(_modules())
    assert len(modules) > 30, f"only {len(modules)} modules scanned"
    names = {m.name for m in modules}
    for expected in ("prego.py", "rhea_mappings.py", "metatraits.py", "merge_kg.py", "gtdb.py"):
        assert expected in names, f"{expected} is not being scanned"


@pytest.mark.skipif(not TRANSFORMED.is_dir(), reason="no transform output on this checkout")
def test_no_transform_output_on_disk_has_crlf():
    r"""
    Enumerate the files; never guess their paths.

    Both misses in the first pass came from guessing: the survey looked for
    `data/transformed/prego/nodes.tsv` when PREGO writes to `prego_habitat`
    (`PREGO_SHAPES=habitat` changes the output directory, #885), and it tested
    only `nodes.tsv` for sources whose `edges.tsv` was the CRLF one. A
    `find`-shaped check cannot make either mistake.
    """
    offenders = []
    for tsv in sorted(TRANSFORMED.rglob("*.tsv")):
        with tsv.open("rb") as handle:
            chunk = handle.read(200_000)
        if b"\r\n" in chunk:
            offenders.append(str(tsv.relative_to(REPO_ROOT)))
    assert not offenders, "CRLF in transform output (rerun these sources): " + ", ".join(offenders)


def test_the_helper_writes_lf_where_a_bare_writer_writes_crlf():
    r"""The premise, pinned: this is the difference the whole change rests on."""
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
    r"""
    The corruption this prevents: a trailing CR lands in the last column.

    An "empty" last field then holds "\r", so a truthiness test on it inverts --
    which is how a count of gtdb nodes carrying a `same_as` read 901,341 instead
    of 447,137.
    """
    buf = io.StringIO()
    tsv_writer(buf).writerow(["ncbi.assembly:GCA_1.1", "biolink:Genome", ""])
    assert buf.getvalue().split("\n")[0].split("\t")[-1] == ""
