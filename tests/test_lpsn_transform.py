"""Tests for the LPSN transform."""

import csv
from pathlib import Path

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import (
    DEPRECATED_STATUSES,
    LPSN_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    LPSNTransform,
)

FIXTURE_DIR = Path(__file__).parent / "resources" / "lpsn"


@pytest.fixture()
def lpsn_transform(tmp_path):
    """
    Return an ``LPSNTransform`` configured to read the fixture CSV.

    The transform's ``input_base_dir`` is set to ``tests/resources/lpsn``
    so that ``lpsn_gss.csv`` resolves via the base ``Transform`` class,
    and ``output_dir`` is set to a per-test temp dir so nodes.tsv /
    edges.tsv land in isolation.
    """
    return LPSNTransform(input_dir=FIXTURE_DIR, output_dir=tmp_path)


def _read_tsv(path: Path) -> list[dict]:
    """Read a TSV into a list of dicts (header row → per-row dicts)."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_nodes_emitted_for_every_valid_row(lpsn_transform):
    """One node per LPSN record (fixture has 6 rows, all with record_no)."""
    lpsn_transform.run()
    nodes = _read_tsv(lpsn_transform.output_node_file)
    assert len(nodes) == 6
    ids = {n["id"] for n in nodes}
    assert ids == {
        f"{LPSN_PREFIX}1001",
        f"{LPSN_PREFIX}1002",
        f"{LPSN_PREFIX}1003",
        f"{LPSN_PREFIX}1010",
        f"{LPSN_PREFIX}1011",
        f"{LPSN_PREFIX}1099",
    }


def test_node_fields_are_shaped_correctly(lpsn_transform):
    """A species row emits id/category/name/description/xref/provided_by."""
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    ecoli = nodes[f"{LPSN_PREFIX}1002"]
    assert ecoli["category"] == "biolink:OrganismTaxon"
    assert ecoli["name"] == "Escherichia coli"
    assert "Migula" in ecoli["description"]
    assert ecoli["xref"].startswith("https://lpsn.dsmz.de/species/")
    assert ecoli["provided_by"] == LPSN_KNOWLEDGE_SOURCE


def test_illegitimate_row_is_marked_deprecated(lpsn_transform):
    """`status = "illegitimate name"` sets deprecated=True."""
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    subsp = nodes[f"{LPSN_PREFIX}1003"]
    assert subsp["deprecated"] == "True"
    # Sanity: correct-name rows are NOT deprecated.
    assert nodes[f"{LPSN_PREFIX}1002"]["deprecated"] == ""


def test_synonym_status_is_deprecated(lpsn_transform):
    """`status = "synonym"` also flags deprecated (per DEPRECATED_STATUSES)."""
    assert "synonym" in DEPRECATED_STATUSES
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    assert nodes[f"{LPSN_PREFIX}1099"]["deprecated"] == "True"


def test_species_gets_subclass_edge_to_genus(lpsn_transform):
    """Escherichia coli (1002) → Escherichia (1001)."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["object"] == f"{LPSN_PREFIX}1001"]
    assert len(hits) == 1
    assert hits[0]["predicate"] == "biolink:subclass_of"
    assert hits[0]["relation"] == "rdfs:subClassOf"
    assert hits[0]["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_subspecies_gets_subclass_edge_to_species(lpsn_transform):
    """Escherichia coli inactive (1003) → Escherichia coli (1002)."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1003" and e["object"] == f"{LPSN_PREFIX}1002"]
    assert len(hits) == 1


def test_orphan_species_produces_no_edge(lpsn_transform):
    """Notgenus orphan (1099) has no matching genus row → no subclass edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    orphan_edges = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1099"]
    assert orphan_edges == []


def test_missing_csv_raises_file_not_found(tmp_path):
    """Instantiating with an empty input dir and calling run() raises FNFE."""
    xform = LPSNTransform(input_dir=tmp_path, output_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="LPSN GSS CSV not found"):
        xform.run()


def test_species_gets_close_match_edges_for_each_type_strain_deposit(lpsn_transform):
    """
    Emit one close_match edge per culture-collection deposit for a species row.

    E. coli (1002) has ``ATCC 11775 = DSM 30083 = JCM 1649`` and should emit
    one edge per deposit to the shared strain CURIE that BacDive
    also uses (``kgmicrobe.strain:<code>``).
    """
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["predicate"] == "biolink:close_match"
    ]
    objects = {e["object"] for e in close_matches}
    assert objects == {
        "kgmicrobe.strain:ATCC-11775",
        "kgmicrobe.strain:DSM-30083",
        "kgmicrobe.strain:JCM-1649",
    }
    for e in close_matches:
        assert e["relation"] == "skos:closeMatch"
        assert e["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_subspecies_gets_close_match_edge(lpsn_transform):
    """Subspecies row (1003) with ``DSM 30083`` emits one close_match edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1003" and e["predicate"] == "biolink:close_match"
    ]
    assert len(close_matches) == 1
    assert close_matches[0]["object"] == "kgmicrobe.strain:DSM-30083"


def test_genus_row_does_not_emit_close_match(lpsn_transform):
    """
    Genus rows must not emit close_match edges.

    Their ``nomenclatural_type`` carries the type species name, not a
    culture-collection deposit.
    """
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1001" and e["predicate"] == "biolink:close_match"
    ]
    assert close_matches == []


def test_row_with_no_nomenclatural_type_emits_no_close_match(lpsn_transform):
    """The synonym row (1099) has blank ``nomenclatural_type`` → no edges."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1099" and e["predicate"] == "biolink:close_match"
    ]
    assert close_matches == []
