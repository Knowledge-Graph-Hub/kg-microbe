"""Source finalization reads the ontologies output only for a source that declares it (#1511)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from kg_microbe.transform import DATA_SOURCES, transform
from kg_microbe.utils.source_finalization import _dependency_declarations
from kg_microbe.utils.transform_fingerprint import write_fingerprint

#: Sources whose finalized output changes when the ontologies output's
#: declarations are not read: each references NCBITaxon or CHEBI nodes that only
#: the ontologies output declares. Measured on the 2026-10-11 build: gtdb
#: 117,988 such references, lpsn 26,644, rhea_mappings 14,259, microbedecoder
#: 10,071, bacdive 4,263, metatraits_gtdb 1,920, metatraits 710, madin_etal 34,
#: ontologies_stubs 3, mediadive 1. gold and prego also read that output in
#: their producers. Pinned so that dropping one is a deliberate change: the
#: source would then declare those nodes itself from chebi.db or taxdump, or
#: drop its edges to taxa outside the prokaryote trim.
RELIES_ON_ONTOLOGIES = {
    "bacdive",
    "gold",
    "gtdb",
    "lpsn",
    "madin_etal",
    "mediadive",
    "metatraits",
    "metatraits_gtdb",
    "microbedecoder",
    "ontologies_stubs",
    "prego",
    "rhea_mappings",
}

NODES = "id\tcategory\tname\nCHEBI:2509\tbiolink:ChemicalEntity\tagar\nCHEBI:1\tbiolink:NamedThing\t\n"


class _Producer:
    """The attributes finalization reads from a transform, and no others."""

    TRANSFORM_INPUTS = ()

    def __init__(self, base: Path, name: str):
        """Place this producer's output under ``base``, beside any other source's."""
        self.source_name = name
        self.output_base_dir = str(base)
        self.output_dir = str(base / name)


class _Dependent(_Producer):
    """A producer that declares the ontologies output as an input."""

    TRANSFORM_INPUTS = ("ontologies",)


def _ontologies_output(base: Path) -> Path:
    """Write an ontologies node file declaring one named node and one unnamed one."""
    directory = base / "ontologies"
    directory.mkdir(parents=True)
    path = directory / "chebi_nodes.tsv"
    path.write_text(NODES)
    return path


def test_a_source_that_does_not_declare_ontologies_reads_nothing_beside_it(tmp_path):
    """The bytes of an undeclaring source cannot depend on what else was built beside it."""
    _ontologies_output(tmp_path)
    used = set()
    assert _dependency_declarations(_Producer(tmp_path, "cog"), used) == set()
    assert used == set()


def test_a_declaring_source_reads_the_named_declarations_and_records_them(tmp_path):
    """Named rows count as declared, and the files read become consumed inputs."""
    path = _ontologies_output(tmp_path)
    used = set()
    assert _dependency_declarations(_Dependent(tmp_path, "gtdb"), used) == {"CHEBI:2509"}
    assert used == {path}


def test_a_declaring_source_with_no_ontologies_output_reads_nothing(tmp_path):
    """Finalization does not judge the upstream; kg transform, freshness and the merge do."""
    used = set()
    assert _dependency_declarations(_Dependent(tmp_path, "ontologies_stubs"), used) == set()
    assert used == set()


@pytest.mark.parametrize("source", ["gtdb", "lpsn", "madin_etal", "rhea_mappings", "ontologies_stubs"])
def test_kg_transform_refuses_a_declaring_source_without_the_ontologies_output(tmp_path, source):
    """The run stops before any producer starts, and names what to build first."""
    with pytest.raises(FileNotFoundError, match=rf"{source}: needs a completed ontologies output"):
        transform(tmp_path / "raw", tmp_path / "out", sources=[source])


def test_kg_transform_refuses_what_a_single_ontology_run_leaves(tmp_path):
    """One ontology's files and no marker are part of the declarations, not all of them (#1554)."""
    leftover = tmp_path / "out" / "ontologies" / "ec_nodes.tsv"
    leftover.parent.mkdir(parents=True)
    leftover.write_text(NODES)
    with pytest.raises(FileNotFoundError, match="gtdb: needs a completed ontologies output"):
        transform(tmp_path / "raw", tmp_path / "out", sources=["gtdb"])


def _freshness_checker(monkeypatch, repo: Path, transformed: Path):
    """Load kgm-freshness-check against an isolated tree whose fixture source declares ontologies."""
    script = Path(__file__).parents[1] / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("freshness_upstream_fixture", script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", repo)
    monkeypatch.setattr(module, "TRANSFORMED_DIR", transformed)
    monkeypatch.setattr(module, "_declared_data_inputs", lambda source: ())
    monkeypatch.setattr(module, "_declared_transform_inputs", lambda source: ("ontologies",))
    return module


def test_freshness_never_calls_a_source_built_without_its_upstream_fresh(tmp_path, monkeypatch):
    """Absent when built and absent now digest alike, but the output was built on nothing (#1565)."""
    code = tmp_path / "kg_microbe" / "transform_utils" / "fixture"
    code.mkdir(parents=True)
    (code / "fixture.py").write_text("X = 1\n")
    transformed = tmp_path / "data" / "transformed"
    output = transformed / "fixture"
    output.mkdir(parents=True)
    write_fingerprint(output, code, tmp_path, (), ("ontologies",))
    checker = _freshness_checker(monkeypatch, tmp_path, transformed)
    status, note = checker._fingerprint_verdict("fixture", code)
    assert status == "STALE_VS_UPSTREAM"
    assert "ontologies has no completed output" in note
    (transformed / "ontologies").mkdir()
    write_fingerprint(transformed / "ontologies", code, tmp_path, ())
    assert checker._fingerprint_verdict("fixture", code)[0] == "STALE_VS_UPSTREAM"
    write_fingerprint(output, code, tmp_path, (), ("ontologies",))
    assert checker._fingerprint_verdict("fixture", code)[0] == "FRESH"


def test_every_source_that_relies_on_the_ontologies_declarations_declares_them():
    """An undeclared reliance would make the source declare those nodes itself, silently."""
    declaring = {name for name in DATA_SOURCES if "ontologies" in getattr(DATA_SOURCES[name], "TRANSFORM_INPUTS", ())}
    assert sorted(RELIES_ON_ONTOLOGIES - declaring) == []
