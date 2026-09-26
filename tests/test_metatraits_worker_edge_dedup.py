"""Worker merging deduplicates full graph rows, not evidence or raw diagnostics."""

import csv
import importlib
from collections import Counter

import pytest

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    ID_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    ORIGINAL_OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
    UNIT_COLUMN,
    VALUE_COLUMN,
)

MODULE = importlib.import_module("kg_microbe.transform_utils.metatraits.metatraits")
HEADER = (
    SUBJECT_COLUMN,
    PREDICATE_COLUMN,
    OBJECT_COLUMN,
    RELATION_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    AGENT_TYPE_COLUMN,
    "has_percentage",
    ORIGINAL_OBJECT_COLUMN,
    "original_subject",
    PUBLICATIONS_COLUMN,
    UNIT_COLUMN,
    VALUE_COLUMN,
)
BASE_ROW = (
    "NCBITaxon:1462",
    "METPO:2000044",
    "CHEBI:29125",
    "RO:0002215",
    "infores:metatraits",
    "observation",
    "automated_agent",
    "80.0",
    "",
    "",
    "",
    "",
    "",
)
DIAGNOSTIC = b'{"majority_label":"No robust majority","summary_index":1}\n'


def _write_rows(path, header, rows):
    """Write a synthetic TSV only beneath the test's temporary directory."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _merge(tmp_path, monkeypatch, batches, chunk_size):
    """Run the real merger, optionally reducing I/O chunks without changing parsing."""
    workers = tmp_path / "workers"
    workers.mkdir()
    transform = MODULE.MetaTraitsTransform.__new__(MODULE.MetaTraitsTransform)
    transform.output_dir = tmp_path
    for attribute, filename in (
        ("output_node_file", "nodes.tsv"),
        ("output_edge_file", "edges.tsv"),
        ("unmapped_traits_file", "unmapped.tsv"),
        ("measurement_traits_file", "measurements.tsv"),
        ("unresolved_taxa_file", "unresolved.tsv"),
    ):
        setattr(transform, attribute, tmp_path / filename)
    results = []
    for index, rows in enumerate(batches):
        nodes = workers / f"nodes-{index}.tsv"
        edges = workers / f"edges-{index}.tsv"
        diagnostics = workers / f"indeterminate-{index}.jsonl"
        _write_rows(
            nodes, (ID_COLUMN, CATEGORY_COLUMN, NAME_COLUMN), [("NCBITaxon:1462", "biolink:OrganismTaxon", "taxon")]
        )
        _write_rows(edges, HEADER, rows)
        diagnostics.write_bytes(DIAGNOSTIC * 2)
        results.append(
            {
                "nodes_file": nodes,
                "edges_file": edges,
                "indeterminate_traits_file": diagnostics,
                "unmapped_traits": [],
                "measurement_traits": [],
                "unresolved_taxa": [],
            }
        )
    read_csv = MODULE.pd.read_csv

    def read_small_chunks(*args, **kwargs):
        """Keep the actual Pandas parser and alter only fixture chunk boundaries."""
        if chunk_size is not None and "chunksize" in kwargs:
            kwargs["chunksize"] = chunk_size
        return read_csv(*args, **kwargs)

    monkeypatch.setattr(MODULE.pd, "read_csv", read_small_chunks)
    transform._merge_worker_outputs(results, workers)
    with transform.output_edge_file.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        assert next(reader) == list(HEADER)
        rows = list(map(tuple, reader))
    assert transform.indeterminate_traits_file.read_bytes() == DIAGNOSTIC * (2 * len(batches))
    assert not workers.exists()
    return rows


@pytest.mark.parametrize("chunk_size", [None, 1, 2])
@pytest.mark.parametrize("separate_workers", [False, True])
@pytest.mark.parametrize("blank_metadata", [False, True])
def test_worker_edge_duplicates_across_chunks_and_files(
    tmp_path, monkeypatch, chunk_size, separate_workers, blank_metadata
):
    """Exact duplicates collapse within/across chunks and workers, including blanks."""
    row = (
        BASE_ROW
        if blank_metadata
        else (*BASE_ROW[:8], "CHEBI:29125", "NCBITaxon:1462", "doi:10.1234/test", "unit:test", "1")
    )
    filler = ("NCBITaxon:1", *row[1:])
    batches = [[row, filler], [row, row]] if separate_workers else [[row, filler, row, row]]
    actual = _merge(tmp_path, monkeypatch, batches, chunk_size)
    assert actual == [row, filler]


@pytest.mark.parametrize("chunk_size", [None, 1, 2])
def test_worker_edge_full_field_distinctions_survive(tmp_path, monkeypatch, chunk_size):
    """Sharing an SPO never erases differing evidence, scalar values or provenance."""
    variants = []
    for index, column in enumerate(HEADER):
        row = list(BASE_ROW)
        row[index] = f"different:{column}"
        variants.append(tuple(row))
    actual = _merge(tmp_path, monkeypatch, [[BASE_ROW, *variants, BASE_ROW], variants], chunk_size)
    assert Counter(actual) == Counter([BASE_ROW, *variants])
    assert len(actual) == len(HEADER) + 1
