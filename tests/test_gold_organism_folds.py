"""GOLD exports its exact fold decisions so downstream crosswalks retain identity."""

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
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils.transform_fingerprint import upstream_fingerprint, write_fingerprint

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


def _microbedecoder(gold):
    """Supply the immutable empty GTDB authority and build the consumer in the temporary output tree."""
    gtdb_dir = gold.output_base_dir / "gtdb"
    gtdb_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES.parent / "microbedecoder" / "gtdb_nodes.tsv", gtdb_dir / "nodes.tsv")
    return MicrobeDecoderTransform(
        input_dir=gold.input_base_dir,
        output_dir=gold.output_base_dir,
        chemical_loader=object(),  # fixture contains only identity crosswalks
    )


def test_report_contains_only_actual_folds_with_final_taxids(transformed_gold):
    """Neither trim drops, retained strains nor multi-parent organisms become aliases."""
    report = transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE
    assert _read(report) == [
        {"original_id": "gold:Go1", "canonical_id": "NCBITaxon:10"},
        {"original_id": "gold:Go4", "canonical_id": "NCBITaxon:10"},
        {"original_id": "gold:Go7", "canonical_id": "NCBITaxon:20"},
    ]
    assert b"\r" not in report.read_bytes()
    nodes = {row["id"] for row in _read(transformed_gold.output_node_file)}
    assert "gold:Go1" not in nodes
    assert "gold:Go4" not in nodes
    assert "gold:Go2" in nodes
    assert "gold:Go5" in nodes
    assert "gold:Go6" in nodes


def test_consumer_repoints_known_folds_without_hiding_unknowns(transformed_gold):
    """Normalize uppercase IDs first, then apply only the producer's explicit decisions."""
    consumer = _microbedecoder(transformed_gold)
    consumer.run()
    edges = _read(consumer.output_edge_file)
    assert {row["subject"]: row["object"] for row in edges} == {
        "lpsn:101": "NCBITaxon:10",  # folded
        "lpsn:102": "gold:Go2",  # retained strain
        "lpsn:103": "gold:Go3",  # trimmed organism remains a reportable gap
        "lpsn:104": "NCBITaxon:10",  # folded after retired-taxid remapping
        "lpsn:105": "gold:Go5",  # multiple parents: producer refused to fold
        "lpsn:106": "gold:Go404",  # no source record: do not infer
    }
    assert {row["predicate"] for row in edges} == {"biolink:close_match"}
    assert {row["primary_knowledge_source"] for row in edges} == {MICROBEDECODER_KNOWLEDGE_SOURCE}
    assert not _read(consumer.output_node_file)


def test_missing_report_fails_before_overwriting_outputs(transformed_gold):
    """An old GOLD output cannot silently reintroduce the folded-ID stubs (#1051)."""
    consumer = _microbedecoder(transformed_gold)
    consumer.output_node_file.write_text("previous nodes\n")
    consumer.output_edge_file.write_text("previous edges\n")
    (transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE).unlink()
    with pytest.raises(FileNotFoundError, match="poetry run kg transform -s gold"):
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
def test_malformed_fold_report_is_rejected(transformed_gold, body):
    """A corrupt sidecar must not manufacture or ambiguously choose identity mappings."""
    (transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE).write_text(body)
    with pytest.raises(ValueError):
        _microbedecoder(transformed_gold).run()


def test_empty_fold_run_replaces_previous_report(transformed_gold, monkeypatch):
    """A legitimate zero-fold run publishes a header rather than leaving stale aliases."""
    monkeypatch.setattr(transformed_gold, "_organism_collapse", lambda *args: {})
    transformed_gold.run()
    report = transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE
    assert report.read_text() == "\t".join(GOLD_ORGANISM_FOLD_HEADER) + "\n"
    consumer = _microbedecoder(transformed_gold)
    consumer.run()
    assert all(row["object"].startswith("gold:") for row in _read(consumer.output_edge_file))


def test_consumer_reloads_report_on_a_second_run(transformed_gold):
    """Reusing a transform instance must not retain mappings from a prior GOLD run."""
    consumer = _microbedecoder(transformed_gold)
    consumer.run()
    (transformed_gold.output_dir / GOLD_ORGANISM_FOLD_FILE).write_text("\t".join(GOLD_ORGANISM_FOLD_HEADER) + "\n")
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
