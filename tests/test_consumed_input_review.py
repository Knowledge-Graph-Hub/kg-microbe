"""Independent parser-snapshot and producer-read identity checks for generated lookups."""

import csv
import hashlib
import io
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

FIXTURE = Path(__file__).parent / "resources/consumed_input_fingerprint/lookup.tsv"


@pytest.fixture
def consumer(tmp_path):
    """Construct only the real required-read protocol and copy immutable local input bytes."""
    cls = DATA_SOURCES["mediadive"].transform_class
    transform = cls.__new__(cls)
    Transform.__init__(transform, "mediadive", tmp_path / "raw", tmp_path / "transformed")
    lookup = tmp_path / "lookup.tsv"
    shutil.copyfile(FIXTURE, lookup)
    return transform, lookup


def test_parser_stream_cannot_modify_the_snapshot_it_certifies(consumer):
    """A read-only parser cannot create different assertions while keeping the original digest."""
    transform, lookup = consumer
    with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
        with pytest.raises(io.UnsupportedOperation):
            reader.write("bacdive_id\tncbitaxon_id\n1\tNCBITaxon:2\n")
        with pytest.raises(io.UnsupportedOperation):
            reader.buffer.write(b"different unrecorded parser bytes")
        rows = list(csv.DictReader(reader, delimiter="\t"))
    assert rows == [{"bacdive_id": "1", "ncbitaxon_id": "NCBITaxon:1"}]
    transform.verify_consumed_inputs()


def test_parser_reads_copied_bytes_and_changed_source_invalidates_exit(consumer):
    """The actual parser sees its original snapshot even if another writer replaces the source."""
    transform, lookup = consumer
    original = lookup.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="changed or missing"):
        with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
            lookup.write_bytes(original.replace(b"NCBITaxon:1", b"NCBITaxon:2"))
            assert reader.read() == original.decode("utf-8")
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


def test_second_read_cannot_replace_original_expected_hash(consumer):
    """Within one run, rereading different current bytes never updates the earlier evidence."""
    transform, lookup = consumer
    expected = hashlib.sha256(lookup.read_bytes()).hexdigest()
    with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
        reader.read()
    lookup.write_bytes(lookup.read_bytes().replace(b"NCBITaxon:1", b"NCBITaxon:2"))
    with pytest.raises(SourceFinalizationRequired, match="changed within one producer run"):
        with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
            reader.read()
    assert transform.consumed_input_snapshots["bacdive_taxon_lookup"]["sha256"] == expected
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


def test_returned_snapshot_metadata_does_not_mutate_original_evidence(consumer):
    """Caller edits to the exported metadata cannot restamp an already-consumed input."""
    transform, lookup = consumer
    expected = hashlib.sha256(lookup.read_bytes()).hexdigest()
    with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
        reader.read()
    exported = transform.consumed_input_snapshots
    exported["bacdive_taxon_lookup"]["sha256"] = "different claimed evidence"
    exported.clear()
    assert transform.consumed_input_snapshots["bacdive_taxon_lookup"]["sha256"] == expected
    transform.verify_consumed_inputs()


def test_caught_parser_failure_cannot_certify_partial_consumption(consumer):
    """A partial parse remains failed even if application code catches the original exception."""
    transform, lookup = consumer
    with pytest.raises(ValueError, match="fixture parse failed"):
        with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
            reader.readline()
            raise ValueError("fixture parse failed")
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        transform.verify_consumed_inputs()
    transform.begin_consumed_inputs()
    with transform.consume_input("bacdive_taxon_lookup", lookup) as reader:
        reader.read()
    transform.verify_consumed_inputs()
