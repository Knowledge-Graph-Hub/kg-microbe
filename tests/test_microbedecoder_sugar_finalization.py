"""Exercise the registered Sugar producer's actual finalization boundary offline (#1180)."""

import csv
import gzip
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _child(root):
    """Use copied registered code and real validators, with no production data or network."""
    if sys.flags.optimize:
        raise RuntimeError("fixture assertions require an unoptimized child interpreter")
    sys.path.insert(0, str(root))

    def offline(*args, **kwargs):
        """Reject accidental network access in the subprocess as well as the parent pytest."""
        raise RuntimeError("network forbidden in Sugar finalization regression")

    socket.socket.connect = offline
    socket.getaddrinfo = offline
    import kg_microbe.transform as dispatcher
    from kg_microbe.transform_utils.constants import GOLD_ORGANISM_FOLD_FILE
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
    from kg_microbe.utils import go_authority
    from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
    from kg_microbe.utils.graph_schema import validate_canonical_tsv
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
    from tests.microbedecoder_quarantine_fixtures import (
        bind_fixture_quarantine_policy,
        write_fixture_quarantine_policy,
    )
    from tests.test_microbedecoder_unresolved_sugar import OLD, _read, _records, _scoped_id, _substrates

    assert dispatcher.DATA_SOURCES["microbedecoder"].transform_class is MicrobeDecoderTransform
    assert Path(sys.modules[MicrobeDecoderTransform.__module__].__file__).resolve().is_relative_to(root)
    raw, output = root / "data/raw", root / "data/transformed"
    records = _records()
    source = raw / "database.csv"
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    for name, fixture in (("gold", GOLD_ORGANISM_FOLD_FILE), ("gtdb", "gtdb_nodes.tsv")):
        destination = output / name
        destination.mkdir(parents=True)
        shutil.copyfile(
            root / "tests/resources/microbedecoder" / fixture,
            destination / (fixture if name == "gold" else "nodes.tsv"),
        )

    # Fixed synthetic dependency declarations, not inferred from emitted rows.
    # These preserve the fixture's unrelated literal cross-references; they do
    # not assert that its NCBI/GOLD crosswalks are scientifically correct.
    authority = output / "ontologies/fixture_nodes.tsv"
    authority.parent.mkdir()
    shutil.copyfile(root / "tests/resources/microbedecoder/metpo_nodes.tsv", authority.parent / "metpo_nodes.tsv")
    shutil.copyfile(root / "tests/resources/microbedecoder/go_nodes.tsv", authority.parent / "go_nodes.tsv")
    shutil.copyfile(
        root / "tests/resources/microbedecoder/chebi_record_nodes.tsv", authority.parent / "chebi_nodes.tsv"
    )
    authority.write_text(
        "id\tcategory\tname\n"
        "NCBITaxon:38284\tbiolink:OrganismTaxon\tsynthetic declared taxon A\n"
        "NCBITaxon:935861\tbiolink:OrganismTaxon\tsynthetic declared taxon B\n"
        "gold:Go0004393\tbiolink:OrganismTaxon\tsynthetic declared organism A\n"
        "gold:Gp0004393\tbiolink:OrganismTaxon\tsynthetic declared project A\n"
        "gold:Go0012393\tbiolink:OrganismTaxon\tsynthetic declared organism B\n"
        "gold:Gp0012393\tbiolink:OrganismTaxon\tsynthetic declared project B\n"
    )
    mapping = root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    # The saved second sugar record reports xylanolysis. The reviewed default
    # mapping now references GO, so supply its actual minimal authority excerpt.
    # Only the production database-size/build gate is bypassed for this tiny
    # offline fixture; parsing, hashing, reference normalization and admission
    # all execute their real implementations against an actual SQLite database.
    with sqlite3.connect(raw / "go.db") as database:
        database.execute("CREATE TABLE statements(subject,predicate,object,value)")
        database.execute("CREATE TABLE edge(subject,predicate,object)")
        database.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [
                ("GO:0045493", "rdfs:label", None, "xylan catabolic process"),
                ("GO:0045493", "oio:hasOBONamespace", None, "biological_process"),
            ],
        )
    lookup = ChemicalMappingLoader(mapping)
    transform = MicrobeDecoderTransform(raw, output, chemical_loader=lookup)
    write_fixture_quarantine_policy(source, root / "mappings/canonical", canonical_names=True)
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source, show_status=False)
    before_nodes, before_edges = _read(transform.output_node_file), _read(transform.output_edge_file)
    scoped = {_scoped_id(record) for record in records[:2]}
    before_local = [row for row in before_nodes if row["id"] in scoped]
    assert len(before_local) == len(scoped) == 2
    selected = _substrates(before_edges)
    assert len(selected) == 3
    assert {row["object"] for row in selected if row["value"] == "sugar"} == scoped
    assert all(row["original_object"] == OLD for row in selected if row["value"] == "sugar")
    assert next(row for row in selected if row["value"] == "mucin")["object"] == "NCIT:C16883"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(go_authority, "_prepare_go_database", lambda selected: selected / "go.db")
        report = transform.finalize(fresh_run=True)
    paths = [transform.output_node_file, transform.output_edge_file]
    after_nodes, after_edges = map(_read, paths)
    before_fields = set(before_edges[0])
    extra_fields = set(after_edges[0]) - before_fields
    # No endpoints require authority replacement in this fixture, so only
    # canonical column ordering changes, not the declared field set.
    assert extra_fields == set(), extra_fields

    def rows(values, fields):
        """Compare full literal assertion multisets, never only SPO or selected evidence."""
        return Counter(tuple((key, row[key]) for key in sorted(fields)) for row in values)

    assert rows(before_edges, before_fields) == rows(after_edges, before_fields)
    assert set(before_nodes[0]) == set(after_nodes[0])
    added_go = [row for row in after_nodes if row["id"] == "GO:0045493"]
    assert len(added_go) == 1
    assert added_go[0]["name"] == "xylan catabolic process"
    assert added_go[0]["category"] == "biolink:BiologicalProcess"
    assert added_go[0]["provided_by"] == "infores:go"
    assert rows(before_nodes, before_nodes[0]) == rows(
        [row for row in after_nodes if row["id"] != "GO:0045493"], before_nodes[0]
    )
    assert [row for row in after_nodes if row["id"] in scoped] == before_local
    assert all(row["name"] == "sugar" and row["category"] == "biolink:ChemicalEntity" for row in before_local)
    assert all(not row[key] for row in before_local for key in ("xref", "same_as", "synonym"))
    assert validate_canonical_tsv(paths[0], is_node=True) == len(after_nodes)
    assert validate_canonical_tsv(paths[1], is_node=False) == len(after_edges)
    assert report["source"] == "microbedecoder"
    assert report["producer_code"]["directory"] == str(root / "kg_microbe/transform_utils/microbedecoder")
    assert report["declared_data_inputs"] == sorted(MicrobeDecoderTransform.DATA_INPUTS)
    inputs = {item["path"]: item["sha256"] for item in report["inputs"]}
    assert inputs[str(mapping)] == hashlib.sha256(mapping.read_bytes()).hexdigest()
    assert inputs[str(authority)] == hashlib.sha256(authority.read_bytes()).hexdigest()
    verify_finalized_source_files(paths)
    dispatcher._record_fingerprint(transform, "microbedecoder")
    marker = json.loads((transform.output_dir / "source_fingerprint.json").read_text())
    assert marker["schema"] is not None
    # No upstream completion receipts are fabricated: the stronger recursive
    # public-admission gate is outside this source-finalization regression.
    for changed in (paths[1], mapping, authority):
        original = changed.read_bytes()
        changed.write_bytes(original + b"\n")
        with pytest.raises(SourceFinalizationRequired):
            verify_finalized_source_files(paths)
        changed.write_bytes(original)
    verify_finalized_source_files(paths)
    print(
        "SUGAR_FINALIZATION_RESULT="
        + json.dumps(
            {
                "nodes": len(after_nodes),
                "edges": len(after_edges),
                "scoped_nodes": sorted(scoped),
                "original_edge_fields": sorted(before_fields),
                "before_edge_header": list(before_edges[0]),
                "final_edge_header": list(after_edges[0]),
                "added_blank_edge_fields": sorted(extra_fields),
                "all_original_fields_and_multiplicity_unchanged": True,
                "registered_finalization_and_record_verification": "PASS",
                "recursive_upstream_freshness": "NOT_RUN",
                "recorded_consumed_inputs": report["consumed_inputs"],
            },
            sort_keys=True,
        )
    )


def test_registered_sugar_finalization_preserves_full_observations(tmp_path):
    """Finalize real three-record output; verify recorded provenance and stale-input rejection."""
    root = tmp_path / "isolated"
    shutil.copytree(ROOT / "kg_microbe", root / "kg_microbe", ignore=shutil.ignore_patterns("__pycache__", "tmp"))
    for name in (
        "__init__.py",
        "microbedecoder_quarantine_fixtures.py",
        "test_microbedecoder_unresolved_sugar.py",
        "test_chemical_mapping_utils.py",
    ):
        target = root / "tests" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tests" / name, target)
    shutil.copytree(ROOT / "tests/resources/microbedecoder", root / "tests/resources/microbedecoder")
    from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

    for relative in SHARED_DATA_INPUTS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    process_table = Path("mappings/canonical/microbedecoder_process_mappings.tsv")
    (root / process_table).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / process_table, root / process_table)
    phenotype_table = Path("mappings/canonical/microbedecoder_phenotype_mappings.tsv")
    shutil.copyfile(ROOT / phenotype_table, root / phenotype_table)
    scope_table = Path("mappings/canonical/microbedecoder_process_scope_definitions.tsv")
    shutil.copyfile(ROOT / scope_table, root / scope_table)
    evidence = json.loads((root / "tests/resources/microbedecoder/bergey_unresolved_sugar.json").read_bytes())
    controls = evidence["sugar_mapping_controls"]
    # The only synthetic mapping control adds native Mucin; exact Sugar rows
    # above remain the saved immutable mapping projection.
    controls.append(
        {
            **controls[-1],
            "subject_id": "kgm.name:mucin",
            "subject_label": "Mucin",
            "object_id": "NCIT:C16883",
            "object_label": "Mucin",
            "source": "native_ontology:ncit",
        }
    )
    with gzip.open(root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(controls[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(controls)
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    for fixture, name in (
        ("biolink-model-minimal.yaml", "biolink-model.yaml"),
        ("predicate_mapping_minimal.yaml", "predicate_mapping.yaml"),
    ):
        shutil.copyfile(ROOT / "tests/resources" / fixture, raw / name)
    environment = dict(
        os.environ,
        PYTHONPATH=str(root),
        PYTHONDONTWRITEBYTECODE="1",
        KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
        KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
    )
    child = subprocess.run(  # noqa: S603 - exact interpreter and immutable local fixture runner
        [sys.executable, str(Path(__file__).resolve()), "--child", str(root)],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    result = json.loads(
        next(
            line.removeprefix("SUGAR_FINALIZATION_RESULT=")
            for line in child.stdout.splitlines()
            if line.startswith("SUGAR_FINALIZATION_RESULT=")
        )
    )
    assert result["registered_finalization_and_record_verification"] == "PASS"
    assert result["all_original_fields_and_multiplicity_unchanged"]
    print("SUGAR_FINALIZATION_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child":
        raise SystemExit("fixture subprocess only")
    _child(Path(sys.argv[2]).resolve())
