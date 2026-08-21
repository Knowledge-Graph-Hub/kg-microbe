"""Focused tests for MetaTraits file I/O primitives."""

import csv

from kg_microbe.transform_utils.metatraits.io import StreamingRowWriter


def test_streaming_writer_emits_header_and_rows(tmp_path) -> None:
    """Emission is incremental and preserves ordered TSV columns."""
    output = tmp_path / "nested" / "nodes.tsv"
    with StreamingRowWriter(output, ["id", "name"]) as writer:
        writer.write_row(["NCBITaxon:1", "root"])

    with output.open(newline="") as stream:
        assert list(csv.reader(stream, delimiter="\t")) == [
            ["id", "name"],
            ["NCBITaxon:1", "root"],
        ]
