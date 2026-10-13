"""Source finalization reads the ontologies output only for a source that declares it (#1511)."""

from pathlib import Path

import pytest

from kg_microbe.transform import DATA_SOURCES, transform
from kg_microbe.utils.source_finalization import (
    FINALIZATION_FILE,
    SourceFinalizationRequired,
    _dependency_declarations,
)
from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE
from tests.ontologies_output_fixtures import write_completed_ontologies_output

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


NODES = "id\tcategory\tname\nCHEBI:2509\tbiolink:ChemicalEntity\tagar\nCHEBI:1\tbiolink:NamedThing\t\n"


def test_a_source_that_does_not_declare_ontologies_reads_nothing_beside_it(tmp_path):
    """The bytes of an undeclaring source cannot depend on what else was built beside it."""
    write_completed_ontologies_output(tmp_path / "ontologies", NODES)
    used = set()
    assert _dependency_declarations(_Producer(tmp_path, "cog"), used) == set()
    assert used == set()


def test_a_declaring_source_reads_exactly_the_recorded_node_files(tmp_path):
    """Named rows count as declared; a node file the record does not list is not read."""
    path = write_completed_ontologies_output(tmp_path / "ontologies", NODES)
    (tmp_path / "ontologies" / "stray_nodes.tsv").write_text(
        "id\tcategory\tname\nCHEBI:60004\tbiolink:ChemicalEntity\tmixture\n"
    )
    used = set()
    assert _dependency_declarations(_Dependent(tmp_path, "gtdb"), used) == {"CHEBI:2509"}
    assert used == {path}


def test_a_declaring_source_with_no_ontologies_output_reads_nothing(tmp_path):
    """Its marker records the absent upstream; kg transform and the merge refuse it, not finalization."""
    used = set()
    assert _dependency_declarations(_Dependent(tmp_path, "ontologies_stubs"), used) == set()
    assert used == set()


@pytest.mark.parametrize(
    "damage",
    [
        "no_record",  # a single-ontology run's files, or an interrupted run
        "no_marker",  # a single-ontology run removes the whole output's marker
        "changed_member",  # a node file rewritten after finalization
    ],
)
def test_a_declaring_source_refuses_a_partial_ontologies_output(tmp_path, damage):
    """Part of the declarations would make the source quietly declare the rest itself (#1554)."""
    directory = tmp_path / "ontologies"
    path = write_completed_ontologies_output(directory, NODES)
    if damage == "no_record":
        (directory / FINALIZATION_FILE).unlink()
    elif damage == "no_marker":
        (directory / FINGERPRINT_FILE).unlink()
    else:
        path.write_text(NODES + "CHEBI:60004\tbiolink:ChemicalEntity\tmixture\n")
    expected = "incomplete ontologies output" if damage != "changed_member" else "differs from its finalization record"
    with pytest.raises(SourceFinalizationRequired, match=expected):
        _dependency_declarations(_Dependent(tmp_path, "ontologies_stubs"), set())


@pytest.mark.parametrize("source", ["gtdb", "lpsn", "madin_etal", "rhea_mappings", "ontologies_stubs"])
def test_kg_transform_refuses_a_declaring_source_without_the_ontologies_output(tmp_path, source):
    """The run stops before any producer starts, and names what to build first."""
    with pytest.raises(FileNotFoundError, match=rf"{source}: needs a completed ontologies output"):
        transform(tmp_path / "raw", tmp_path / "out", sources=[source])


def test_every_source_that_relies_on_the_ontologies_declarations_declares_them():
    """An undeclared reliance would make the source declare those nodes itself, silently."""
    declaring = {name for name in DATA_SOURCES if "ontologies" in getattr(DATA_SOURCES[name], "TRANSFORM_INPUTS", ())}
    assert sorted(RELIES_ON_ONTOLOGIES - declaring) == []
