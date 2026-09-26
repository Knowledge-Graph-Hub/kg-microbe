"""Exact generated-input consumption without early-preflight or stale-cache loopholes."""

import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

from kg_microbe.transform import _missing_declared_inputs
from kg_microbe.transform_utils.bactotraits import bactotraits as bacto
from kg_microbe.transform_utils.mediadive import mediadive as media
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import source_finalization as finalizer
from kg_microbe.utils.atomic_io import atomic_write, cache_is_complete
from kg_microbe.utils.transform_fingerprint import finalization_inputs_current, write_fingerprint

FIXTURES = Path(__file__).parent / "resources" / "consumed_inputs"
MEDIA_FIXTURES = Path(__file__).parent / "resources" / "provenance_serialization"
ROLE = "bacdive_taxon_lookup"


class LookupTransform(Transform):
    """Minimal graph producer with the same required consumption role as the real consumers."""

    REQUIRED_CONSUMED_INPUTS = (ROLE,)


def _lookup(tmp_path, changed=False):
    """Copy immutable lookup evidence into a mutable isolated producer-output location."""
    path = tmp_path / "bacdive" / "bacdive.tsv"
    path.parent.mkdir(exist_ok=True)
    shutil.copyfile(FIXTURES / ("lookup_changed.tsv" if changed else "lookup.tsv"), path)
    return path


def _producer(tmp_path):
    """Use generic named endpoints so finalization needs no ontology service."""
    result = LookupTransform("fixture", tmp_path / "raw", tmp_path / "out")
    result.input_base_dir.mkdir(exist_ok=True)
    result.output_node_file.write_text(
        "id\tcategory\tname\nfixture:1\tbiolink:NamedThing\tOne\nfixture:2\tbiolink:NamedThing\tTwo\n"
    )
    result.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\n"
        "fixture:1\tbiolink:related_to\tfixture:2\tskos:related\tinfores:test\tobservation\tmanual_agent\n"
    )
    return result


def _consume(transform, path):
    """Actually read the immutable source snapshot rather than fabricate marker metadata."""
    with transform.consume_input(ROLE, path) as stream:
        return stream.read()


def _rows(path):
    """Read only small fixture outputs."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _media(tmp_path, monkeypatch):
    """Prepare the real MediaDive run with fixture responses, no network or authority reads."""
    monkeypatch.setattr(media, "BACDIVE_TMP_DIR", tmp_path / "bacdive")
    monkeypatch.setattr(media, "MEDIADIVE_TMP_DIR", tmp_path)
    with (
        mock.patch.object(media.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(media.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(media.MediaDiveTransform, "_load_micromediaparam_mappings"),
        mock.patch.object(media.MediaDiveTransform, "_load_bulk_data"),
        mock.patch.object(media, "ChemicalMappingLoader"),
    ):
        result = media.MediaDiveTransform(input_dir=MEDIA_FIXTURES, output_dir=tmp_path / "out")
    result.using_bulk_data = True
    strains = json.loads((MEDIA_FIXTURES / "medium_strains.json").read_text())

    def response(path, endpoint, directory):
        """Return immutable fixture growth records and no recipe solutions."""
        return strains if endpoint.startswith(media.MEDIUM_STRAINS) else {}

    monkeypatch.setattr(result, "get_json_object", response)
    return result


def _bacto(tmp_path, monkeypatch):
    """Prepare the actual BactoTraits emitter with an explicit fixture ontology boundary."""
    monkeypatch.setattr(bacto, "BACDIVE_TMP_DIR", tmp_path / "bacdive")
    monkeypatch.setattr(bacto, "BACTOTRAITS_TMP_DIR", tmp_path / "bactotraits")
    monkeypatch.setattr(bacto, "CUSTOM_CURIES_YAML_FILE", FIXTURES / "curies.yaml")
    monkeypatch.setattr(bacto, "resolve_adapter", lambda adapter: adapter)
    monkeypatch.setattr(bacto, "get_label", lambda adapter, identifier: "Fixture organism")
    result = bacto.BactoTraitsTransform.__new__(bacto.BactoTraitsTransform)
    Transform.__init__(result, "bactotraits", FIXTURES, tmp_path / "out")
    result.knowledge_source = "infores:bactotraits"
    result.ncbi_impl = object()
    result.bactotraits_metpo_mappings = {}
    return result


def test_snapshot_is_immutable_and_changed_source_is_rejected(tmp_path):
    """The parser sees captured bytes even if the producer's path changes mid-read."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    original = path.read_text()
    with pytest.raises(finalizer.SourceFinalizationRequired, match="changed or missing"):
        with transform.consume_input(ROLE, path) as stream:
            shutil.copyfile(FIXTURES / "lookup_changed.tsv", path)
            assert stream.read() == original
    assert transform.consumed_input_snapshots[ROLE]["sha256"] == hashlib.sha256(original.encode()).hexdigest()
    with pytest.raises(finalizer.SourceFinalizationRequired, match="changed or missing"):
        transform.finalize(fresh_run=True)


def test_required_read_missing_fails_and_snapshot_property_is_not_mutable(tmp_path):
    """Required reads cannot be inferred from file existence or mutated through a getter."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    with pytest.raises(finalizer.SourceFinalizationRequired, match="were not read"):
        transform.finalize(fresh_run=True)
    _consume(transform, path)
    transform.consumed_input_snapshots[ROLE]["sha256"] = "fake"
    transform.verify_consumed_inputs()


def test_caught_parser_failure_cannot_certify_partial_consumption(tmp_path):
    """A producer must restart after a failed parser, even when original bytes stayed current."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    with pytest.raises(ValueError, match="parse failure"):
        with transform.consume_input(ROLE, path) as stream:
            stream.read(1)
            raise ValueError("parse failure")
    with pytest.raises(finalizer.SourceFinalizationRequired, match="read failed"):
        transform.finalize(fresh_run=True)
    assert sorted(path.name for path in transform.output_dir.iterdir()) == ["edges.tsv", "nodes.tsv"]
    transform.begin_consumed_inputs()
    _consume(transform, path)
    transform.finalize(fresh_run=True)


@pytest.mark.parametrize("mutation", ["replace", "delete", "same_size_mtime"])
def test_changed_lookup_before_finalization_does_not_publish(tmp_path, mutation):
    """Exact byte identity survives equal length and restored timestamps, not merely metadata."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    _consume(transform, path)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    if mutation == "delete":
        path.unlink()
    else:
        stat = path.stat()
        shutil.copyfile(FIXTURES / "lookup_changed.tsv", path)
        if mutation == "same_size_mtime":
            assert path.stat().st_size == stat.st_size
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(finalizer.SourceFinalizationRequired, match="changed or missing"):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_change_at_final_publication_boundary_does_not_publish(tmp_path, monkeypatch):
    """A mutation after staging cannot acquire a finalized source record."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    _consume(transform, path)
    original = finalizer._publish_finalization

    def mutate_then_publish(producer, prepared):
        """Model an upstream replacement immediately before source publication."""
        shutil.copyfile(FIXTURES / "lookup_changed.tsv", path)
        return original(producer, prepared)

    monkeypatch.setattr(finalizer, "_publish_finalization", mutate_then_publish)
    with pytest.raises(finalizer.SourceFinalizationRequired, match="changed or missing"):
        transform.finalize(fresh_run=True)
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_consumed_identity_reaches_report_fingerprint_and_repeat(tmp_path):
    """Repeat uses verified original consumption; a new run must actually read again."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    _consume(transform, path)
    report = transform.finalize(fresh_run=True)
    expected = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert report["consumed_inputs"] == {ROLE: expected}
    assert expected in report["inputs"]
    marker = write_fingerprint(
        transform.output_dir, tmp_path / "code", tmp_path, (), finalization_inputs=transform.finalization_inputs
    )
    assert finalization_inputs_current(marker, tmp_path)
    before = (transform.output_dir / "source_finalization.json").read_bytes()
    transform.begin_consumed_inputs()
    assert transform.finalize() == report
    assert (transform.output_dir / "source_finalization.json").read_bytes() == before
    transform.begin_consumed_inputs()
    with pytest.raises(finalizer.SourceFinalizationRequired, match="were not read"):
        transform.finalize(fresh_run=True)
    _consume(transform, path)
    shutil.copyfile(FIXTURES / "lookup_changed.tsv", path)
    assert not finalization_inputs_current(marker, tmp_path)
    with pytest.raises(finalizer.SourceFinalizationRequired, match="changed"):
        transform.finalize()


def test_same_role_cannot_change_within_run_but_fresh_tracking_can(tmp_path):
    """A subsequent real run can consume new bytes; one run cannot mix lookup versions."""
    transform, path = _producer(tmp_path), _lookup(tmp_path)
    _consume(transform, path)
    shutil.copyfile(FIXTURES / "lookup_changed.tsv", path)
    with pytest.raises(finalizer.SourceFinalizationRequired, match="within one producer run"):
        _consume(transform, path)
    transform.begin_consumed_inputs()
    assert "NCBITaxon:2" in _consume(transform, path)
    transform.verify_consumed_inputs()


def test_clean_preflight_allows_upstream_to_create_lookup_then_real_media_reads_it(tmp_path, monkeypatch):
    """Generated lookup absence is checked at consumption, not before the upstream batch runs."""
    curated = tmp_path / media.MediaDiveTransform.DATA_INPUTS[0]
    curated.parent.mkdir(parents=True)
    curated.write_text("fixture curation\n")
    assert not (tmp_path / "bacdive/bacdive.tsv").exists()
    assert _missing_declared_inputs(["mediadive", "bactotraits"], tmp_path) == []
    transform = _media(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        transform.run(show_status=False)
    path = _lookup(tmp_path, changed=True)
    transform.run(show_status=False)
    assert transform.consumed_input_snapshots[ROLE]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert any(row["subject"] == "NCBITaxon:2" for row in _rows(transform.output_edge_file))
    transform.verify_consumed_inputs()


def test_real_bactotraits_refreshes_complete_cache_and_resets_on_second_run(tmp_path, monkeypatch):
    """A certified older projection never overrides changed BacDive bytes on an actual run."""
    path = _lookup(tmp_path, changed=True)
    transform = _bacto(tmp_path, monkeypatch)
    cache = tmp_path / "bactotraits/bactotraits_mapping.tsv"
    with atomic_write(cache, mark_complete=True) as stream:
        stream.write((FIXTURES / "stale_mapping.tsv").read_text())
    assert cache_is_complete(cache)
    transform.run(data_file="bactotraits.csv", show_status=False)
    assert {row["ncbitaxon_id"] for row in _rows(cache)} == {"NCBITaxon:2"}
    assert {row["subject"] for row in _rows(transform.output_edge_file)} == {"NCBITaxon:2"}
    first = transform.consumed_input_snapshots[ROLE]
    shutil.copyfile(FIXTURES / "lookup.tsv", path)
    transform.run(data_file="bactotraits.csv", show_status=False)
    assert {row["subject"] for row in _rows(transform.output_edge_file)} == {"NCBITaxon:1"}
    assert transform.consumed_input_snapshots[ROLE] != first
    transform.verify_consumed_inputs()
