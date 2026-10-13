"""Bind finite Madin corrections to the exact bytes consumed by the producer."""

import csv
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from kg_microbe.transform_utils import constants as C
from kg_microbe.transform_utils.madin_etal import madin_etal
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from kg_microbe.utils.transform_fingerprint import data_fingerprint, declared_data_inputs

FIXTURE = Path(__file__).parent / "resources" / "madin_foodon_retirement"
CORRECTION_DECLARATION = "mappings/madin_environment_id_corrections.tsv"
CONSUMED_NAME = "madin_environment_id_corrections"


@pytest.fixture
def producer(tmp_path, monkeypatch):
    """Isolate native producer emission from unrelated chemical and NER services."""
    correction = tmp_path / "corrections.tsv"
    correction.write_bytes(madin_etal.ENVIRONMENT_ID_CORRECTIONS_FILE.read_bytes())
    monkeypatch.setattr(madin_etal, "ENVIRONMENT_ID_CORRECTIONS_FILE", correction)
    monkeypatch.setattr(madin_etal, "load_metpo_mappings", lambda *_args: {})
    monkeypatch.setattr(madin_etal, "ChemicalMappingLoader", lambda: None)
    monkeypatch.setattr(madin_etal, "get_exclusion_token_list", lambda *_args: [])
    monkeypatch.setattr(madin_etal, "get_chebi_adapter", lambda: SimpleNamespace(relationships=lambda **_kwargs: []))
    monkeypatch.setattr(madin_etal, "cache_is_complete", lambda *_args: True)
    for prefix in ("chebi", "go"):
        pd.DataFrame(
            columns=[C.OBJECT_ID_COLUMN, C.OBJECT_LABEL_COLUMN, C.SUBJECT_LABEL_COLUMN, C.TRAITS_DATASET_LABEL_COLUMN]
        ).to_csv(tmp_path / f"{prefix}_ner.tsv", sep="\t", index=False)
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("environments.csv", "madin_etal.csv"):
        shutil.copyfile(FIXTURE / name, raw / name)
    transform = madin_etal.MadinEtAlTransform(raw, tmp_path / "output", nlp=False)
    transform.nlp_output_dir = tmp_path
    transform.nlp_stopwords_dir = tmp_path
    return transform, correction


def _edges(transform):
    """Read the small native fixture's emitted assertions."""
    with transform.output_edge_file.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def test_correction_only_edit_changes_madin_data_fingerprint(tmp_path):
    """A curation-only fix must invalidate the source even when code is unchanged."""
    declarations = declared_data_inputs(madin_etal.MadinEtAlTransform, tmp_path)
    correction = tmp_path / CORRECTION_DECLARATION
    correction.parent.mkdir()
    original = madin_etal.ENVIRONMENT_ID_CORRECTIONS_FILE.read_text()
    correction.write_text(original)
    before = data_fingerprint(tmp_path, declarations)
    correction.write_text(original.replace("PO:0009011", "PO:0025131"))
    assert data_fingerprint(tmp_path, declarations) != before
    assert CORRECTION_DECLARATION in declarations


def test_producer_records_exact_correction_snapshot(producer):
    """Actual producer invocation, not a helper call, establishes consumption."""
    transform, correction = producer
    transform.run(show_status=False)
    assert transform.consumed_input_snapshots[CONSUMED_NAME] == {
        "path": str(correction.resolve()),
        "sha256": hashlib.sha256(correction.read_bytes()).hexdigest(),
    }
    assert CONSUMED_NAME in transform.REQUIRED_CONSUMED_INPUTS
    assert len([row for row in _edges(transform) if row[C.SUBJECT_COLUMN] == "PO:0009011"]) == 4


def test_changed_curation_before_read_is_consumed_without_stale_cache(producer):
    """The snapshot records actual current input, not earlier cached correction data."""
    transform, correction = producer
    correction.write_text(correction.read_text().replace("PO:0009011", "PO:0025131"))
    transform.run(show_status=False)
    assert (
        transform.consumed_input_snapshots[CONSUMED_NAME]["sha256"]
        == hashlib.sha256(correction.read_bytes()).hexdigest()
    )
    assert len([row for row in _edges(transform) if row[C.SUBJECT_COLUMN] == "PO:0025131"]) == 4
    assert not any(row[C.SUBJECT_COLUMN] == "PO:0009011" for row in _edges(transform))


def test_correction_mutation_during_parse_aborts_before_output_replacement(producer, monkeypatch):
    """Changing the selected table after parsing cannot publish mixed-input output."""
    transform, correction = producer
    transform.output_node_file.write_text("prior native nodes\n")
    transform.output_edge_file.write_text("prior native edges\n")
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original = madin_etal._apply_environment_id_corrections

    def mutate_after_read(*args, **kwargs):
        """Alter only the isolated test mapping after the helper consumes its stream."""
        result = original(*args, **kwargs)
        correction.write_text(correction.read_text().replace("PO:0009011", "PO:0025131"))
        return result

    monkeypatch.setattr(madin_etal, "_apply_environment_id_corrections", mutate_after_read)
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        transform.run(show_status=False)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_correction_mutation_after_run_refuses_finalization(producer):
    """An edited mapping may not be restamped as authority for earlier native rows."""
    transform, correction = producer
    transform.run(show_status=False)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    correction.write_text(correction.read_text().replace("PO:0009011", "PO:0025131"))
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        transform.finalize()
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_finalized_correction_snapshot_rejects_later_mapping_edit(producer, monkeypatch):
    """A finalized producer stays bound to its original correction bytes at merge admission."""
    from kg_microbe.utils import go_authority

    transform, correction = producer
    # The native records also emit metabolic-process ancestry. Supply the
    # existing hermetic GO authority instead of requiring the production DB.
    authority_path = transform.input_base_dir / "go-statements.tsv"
    shutil.copyfile(FIXTURE.parent / "go_authority" / "statements.tsv", authority_path)
    with authority_path.open() as stream:
        statements = [
            tuple(row[key] or None for key in ("subject", "predicate", "object", "value"))
            for row in csv.DictReader(stream, delimiter="\t")
        ]
    authority = go_authority.GoAuthority.from_statements(statements, authority_path=str(authority_path))
    monkeypatch.setattr(go_authority, "load_go_authority", lambda _raw_dir: authority)
    transform.run(show_status=False)
    report = transform.finalize()
    assert report["consumed_inputs"][CONSUMED_NAME] == transform.consumed_input_snapshots[CONSUMED_NAME]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    correction.write_text(correction.read_text().replace("PO:0009011", "PO:0025131"))
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_missing_production_curation_aborts_instead_of_silently_disabling_repair(producer, monkeypatch):
    """Direct helper compatibility does not permit an ungrounded production run."""
    transform, correction = producer
    monkeypatch.setattr(madin_etal, "ENVIRONMENT_ID_CORRECTIONS_FILE", correction.with_name("missing.tsv"))
    with pytest.raises(FileNotFoundError):
        transform.run(show_status=False)
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()


@pytest.mark.parametrize(
    "header",
    [
        "wrong_header\n",
        "environment_type\twrong_object_id\n",
        "environment_type\twrong_object_id\twrong_object_label\tobject_id\tobject_label\tnotes\tobject_id\n",
    ],
)
def test_malformed_empty_correction_schema_aborts_producer(producer, header):
    """An incomplete or duplicate header is not an explicitly empty valid cohort."""
    transform, correction = producer
    correction.write_text(header)
    with pytest.raises(ValueError, match="correction.*schema"):
        transform.run(show_status=False)
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()


@pytest.mark.parametrize(
    "column,value",
    [
        ("environment_type", ""),
        ("wrong_object_id", ""),
        ("object_id", ""),
        ("object_label", ""),
        ("environment_type", " host_plant_vasculature"),
        ("object_id", "PO:0009011,UBERON:0002049"),
        ("wrong_object_id", "FOODON:03420174 suffix"),
    ],
)
def test_malformed_populated_correction_rule_aborts_producer(producer, column, value):
    """Incomplete identity or composite targets cannot create silently broken replacements."""
    transform, correction = producer
    rules = pd.read_csv(correction, sep="\t", comment="#", dtype=str).fillna("")
    rules.loc[rules.environment_type == "host_plant_vasculature", column] = value
    rules.to_csv(correction, sep="\t", index=False)
    with pytest.raises(ValueError, match="correction row"):
        transform.run(show_status=False)
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
