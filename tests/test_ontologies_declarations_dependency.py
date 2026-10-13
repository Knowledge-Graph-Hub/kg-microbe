"""Source finalization reads the ontologies output only for a source that declares it (#1511)."""

from pathlib import Path

import pytest

from kg_microbe.transform import DATA_SOURCES
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, _dependency_declarations

#: Sources whose finalized output changes when the ontologies output's
#: declarations are not read: each references NCBITaxon or CHEBI nodes that only
#: the ontologies output declares. Measured on the 2026-10-11 build: gtdb
#: 117,988 such references, lpsn 26,644, rhea_mappings 14,259, microbedecoder
#: 10,071, bacdive 4,263, metatraits_gtdb 1,920, metatraits 710, madin_etal 34,
#: ontologies_stubs 3, mediadive 1. gold and prego also read that output in
#: their producers. Pinned so that dropping one is a deliberate change: the
#: source would then declare those nodes itself from chebi.db or taxdump.
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
    """Write an ontologies output declaring one named node and one unnamed one."""
    directory = base / "ontologies"
    directory.mkdir(parents=True)
    path = directory / "chebi_nodes.tsv"
    path.write_text("id\tcategory\tname\nCHEBI:2509\tbiolink:ChemicalEntity\tagar\nCHEBI:1\tbiolink:NamedThing\t\n")
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


@pytest.mark.parametrize("make_directory", [False, True])
def test_a_declaring_source_fails_without_the_ontologies_output(tmp_path, make_directory):
    """Without the output it declares, a source fails rather than declaring those nodes itself."""
    if make_directory:
        (tmp_path / "ontologies").mkdir()
    expected = r"ontologies_stubs declares ontologies.*kg transform -s ontologies"
    with pytest.raises(SourceFinalizationRequired, match=expected):
        _dependency_declarations(_Dependent(tmp_path, "ontologies_stubs"), set())


def test_the_ontologies_source_does_not_read_its_own_output(tmp_path):
    """A single-ontology run writes into the ontologies directory and reads nothing from it."""
    _ontologies_output(tmp_path)
    used = set()
    assert _dependency_declarations(_Producer(tmp_path, "ontologies"), used) == set()
    assert used == set()


def test_every_source_that_relies_on_the_ontologies_declarations_declares_them():
    """An undeclared reliance would make the source declare those nodes itself, silently."""
    declaring = {name for name in DATA_SOURCES if "ontologies" in getattr(DATA_SOURCES[name], "TRANSFORM_INPUTS", ())}
    assert sorted(RELIES_ON_ONTOLOGIES - declaring) == []
