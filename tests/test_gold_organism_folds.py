"""Historical lexical folds are audited but cannot replace source-owned GOLD identity."""

import csv
import io
import shutil
import tarfile
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    GOLD_ORGANISM_FOLD_FILE,
    GOLD_ORGANISM_FOLD_HEADER,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.gold.fold_restoration import AUDIT_FILE as RESTORATION_AUDIT_FILE
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils.transform_fingerprint import upstream_fingerprint, write_fingerprint
from tests.microbedecoder_inactive_join_fixtures import bind_inactive_join_policy, write_empty_join_gss
from tests.microbedecoder_quarantine_fixtures import write_fixture_quarantine_policy

FIXTURES = Path(__file__).parent / "resources" / "gold_folds"


@pytest.fixture
def transformed_gold(tmp_path, monkeypatch):
    """Stage immutable raw inputs, remap a retired taxid, and run GOLD offline."""
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "true")
    raw, out = tmp_path / "raw", tmp_path / "transformed"
    (raw / "gold").mkdir(parents=True)
    (out / "ontologies").mkdir(parents=True)
    for name in ("GOLD_nodes.tsv", "GOLD_edges.tsv"):
        shutil.copyfile(FIXTURES / name, raw / "gold" / name)
    shutil.copyfile(FIXTURES / "ncbitaxon_nodes.tsv", out / "ontologies" / "ncbitaxon_nodes.tsv")
    shutil.copyfile(FIXTURES / "database.csv", raw / "database.csv")
    merged = b"100\t|\t10\t|\n"
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("merged.dmp")
        info.size = len(merged)
        archive.addfile(info, io.BytesIO(merged))
    transform = GOLDTransform(input_dir=raw, output_dir=out)
    transform.run()
    return transform


def _read(path):
    """Read a small fixture output, never a graph-scale production TSV."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _microbedecoder(gold, *, monkeypatch):
    """Supply immutable GTDB/METPO authorities and build the consumer in the temporary output tree."""
    gtdb_dir = gold.output_base_dir / "gtdb"
    gtdb_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES.parent / "microbedecoder" / "gtdb_nodes.tsv", gtdb_dir / "nodes.tsv")
    ontology_dir = gold.output_base_dir / "ontologies"
    ontology_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES.parent / "microbedecoder" / "metpo_nodes.tsv", ontology_dir / "metpo_nodes.tsv")
    shutil.copyfile(FIXTURES.parent / "microbedecoder" / "go_nodes.tsv", ontology_dir / "go_nodes.tsv")
    shutil.copyfile(FIXTURES.parent / "microbedecoder" / "chebi_record_nodes.tsv", ontology_dir / "chebi_nodes.tsv")
    gold.finalize(fresh_run=True)
    consumer = MicrobeDecoderTransform(
        input_dir=gold.input_base_dir,
        output_dir=gold.output_base_dir,
        chemical_loader=object(),  # fixture contains only identity crosswalks
        crosswalk_quarantine_policy=write_fixture_quarantine_policy(
            gold.input_base_dir / "database.csv", gold.output_base_dir / "fixture-crosswalk-policy"
        ),
    )
    write_empty_join_gss(consumer.input_base_dir)
    bind_inactive_join_policy(consumer, consumer.input_base_dir / "database.csv", monkeypatch)
    return consumer


def test_legacy_report_is_empty_and_all_historical_records_are_restored(transformed_gold):
    """Equality and a retired parent ID cannot silently remove native source referents."""
    report = transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE
    assert _read(report) == []
    assert {
        row["id"]: row["historical_fold_target"] for row in _read(transformed_gold.output_dir / RESTORATION_AUDIT_FILE)
    } == {"gold:Go1": "NCBITaxon:10", "gold:Go4": "NCBITaxon:10", "gold:Go7": "NCBITaxon:20"}
    assert b"\r" not in report.read_bytes()
    nodes = {row["id"] for row in _read(transformed_gold.output_node_file)}
    assert "gold:Go1" in nodes
    assert "gold:Go4" in nodes
    assert "gold:Go2" in nodes
    assert "gold:Go5" in nodes
    assert "gold:Go6" in nodes


def test_actual_consumer_finalization_rejoins_retained_gold_audit(monkeypatch, transformed_gold):
    """Exercise the registered producer and finalizer on a labelled synthetic routing fixture."""
    raw = transformed_gold.input_base_dir / "database.csv"
    raw.write_text("LPSN_ID,GOLD_Organism_ID,BacDive_ID\n102,Go2,\n", encoding="utf-8")
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.run()
    consumer.finalize(fresh_run=True)
    from kg_microbe.utils.source_finalization import verify_finalized_source_files

    verify_finalized_source_files([consumer.output_node_file, consumer.output_edge_file])
    audit = _read(consumer.output_dir / "gold_crosswalk_dispositions.tsv")
    assert len(audit) == 1
    assert {row["category"] for row in _read(consumer.output_node_file)} == {"biolink:NamedThing"}


def test_consumer_retains_original_gold_ids_without_hiding_unknowns(monkeypatch, transformed_gold):
    """No lexical alias may replace the original CSV's declared GOLD field."""
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.run()
    edges = _read(consumer.output_edge_file)
    assert {row["subject"]: row["object"] for row in edges} == {
        "lpsn:101": "gold:Go1",  # historically folded, now source-owned
        "lpsn:102": "gold:Go2",  # unresolved native referent
        "lpsn:103": "gold:Go3",  # trimmed organism remains a reportable gap
        "lpsn:104": "gold:Go4",  # parent remap does not replace the source ID
        "lpsn:105": "gold:Go5",  # multiple parents: producer refused to fold
        "lpsn:106": "gold:Go404",  # no source record: do not infer
    }
    admitted = {"gold:Go1", "gold:Go2", "gold:Go4", "gold:Go5"}
    assert {row["predicate"] for row in edges if row["object"] in admitted} == {"biolink:related_to"}
    assert {row["predicate"] for row in edges if row["object"] not in admitted} == {"biolink:close_match"}
    assert {row["primary_knowledge_source"] for row in edges} == {MICROBEDECODER_KNOWLEDGE_SOURCE}
    assert {row["id"] for row in _read(consumer.output_node_file)} == admitted


def test_missing_report_fails_before_overwriting_outputs(monkeypatch, transformed_gold):
    """A missing mandatory native restoration audit rejects before consumer emission."""
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.output_node_file.write_text("previous nodes\n")
    consumer.output_edge_file.write_text("previous edges\n")
    (transformed_gold.output_dir / RESTORATION_AUDIT_FILE).unlink()
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    with pytest.raises((FileNotFoundError, SourceFinalizationRequired)):
        consumer.run()
    assert consumer.output_node_file.read_text() == "previous nodes\n"
    assert consumer.output_edge_file.read_text() == "previous edges\n"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "wrong\theader\n",
        "original_id\tcanonical_id\ngold:Go1\n",
        "original_id\tcanonical_id\nGOLD:Go1\tNCBITaxon:10\n",
        "original_id\tcanonical_id\ngold:Go1\tNCBITaxon:not_a_taxid\n",
        "original_id\tcanonical_id\ngold:Go1\tNCBITaxon:10\ngold:Go1\tNCBITaxon:20\n",
    ],
)
def test_retired_fold_report_cannot_redirect_native_gold_ids(monkeypatch, transformed_gold, body):
    """The retired identity table is no longer consumed, regardless of its stale contents."""
    (transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE).write_text(body)
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.run()
    assert all(row["object"].startswith("gold:") for row in _read(consumer.output_edge_file))


def test_empty_fold_run_replaces_previous_report(monkeypatch, transformed_gold):
    """A legitimate zero-fold run publishes a header rather than leaving stale aliases."""
    # This synthetic routing fixture changes the actual selected labels, rather
    # than bypassing the emitter while its independently audited policy still folds.
    labels = transformed_gold.output_base_dir / "ontologies/ncbitaxon_nodes.tsv"
    rows = _read(labels)
    for row in rows:
        row["name"] += " synthetic authority label changed"
    with labels.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    transformed_gold.run()
    report = transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE
    assert report.read_text() == "\t".join(GOLD_ORGANISM_FOLD_HEADER) + "\n"
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.run()
    assert all(row["object"].startswith("gold:") for row in _read(consumer.output_edge_file))


def test_consumer_never_reloads_retired_aliases_on_a_second_run(monkeypatch, transformed_gold):
    """Reusing a transform instance must not acquire mappings from a stale legacy table."""
    consumer = _microbedecoder(transformed_gold, monkeypatch=monkeypatch)
    consumer.run()
    (transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE).write_text(
        "\t".join(GOLD_ORGANISM_FOLD_HEADER) + "\ngold:Go1\tNCBITaxon:10\n"
    )
    consumer.run()
    assert all(row["object"].startswith("gold:") for row in _read(consumer.output_edge_file))


def test_gold_dependency_participates_in_existing_fingerprint_contract(tmp_path):
    """A new GOLD marker invalidates the consumer through TRANSFORM_INPUTS (#845)."""
    code = tmp_path / "gold_code"
    code.mkdir()
    source = code / "gold.py"
    source.write_text("folds = 1\n")
    out = tmp_path / "transformed"
    (out / "gold").mkdir(parents=True)
    write_fingerprint(out / "gold", code, tmp_path, ())
    before = upstream_fingerprint(out, MicrobeDecoderTransform.TRANSFORM_INPUTS)
    source.write_text("folds = 2\n")
    write_fingerprint(out / "gold", code, tmp_path, ())
    assert upstream_fingerprint(out, MicrobeDecoderTransform.TRANSFORM_INPUTS) != before
