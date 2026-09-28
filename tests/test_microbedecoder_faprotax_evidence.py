"""Keep taxonomy-derived FAPROTAX predictions distinct from manual assertions (#1209)."""

import csv
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    CAPABLE_OF_PREDICATE,
    COMPUTATIONAL_MODEL,
    FAPROTAX_KNOWLEDGE_SOURCE,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    PREDICTION,
)
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.test_microbedecoder_transform import FIXTURE_DIR, _NoChebi, _supply_gold_fold_report

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    """Read the tiny literal output without treating quotes as TSV syntax."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _run(tmp_path, mapped):
    """Exercise real reviewed mapping and explicit unmapped fixture-table branches."""
    _supply_gold_fold_report(tmp_path)
    process_table = None
    if not mapped:
        from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS

        process_table = tmp_path / "empty_process_mappings.tsv"
        rows = DEFAULT_PROCESS_MAPPINGS.read_text().splitlines()
        process_table.write_text("\n".join([rows[0], *[row for row in rows[1:] if "nitrogen_fixation" in row]]) + "\n")
    transform = MicrobeDecoderTransform(
        FIXTURE_DIR, tmp_path, chemical_loader=_NoChebi(), process_mappings=process_table
    )
    transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv", show_status=False)
    return transform


def _check(edges, mapped):
    """Check both evidence tiers and complete occurrence/context preservation."""
    assert len(edges) == 18
    fap = [row for row in edges if row["source_column"] == "FAPROTAX_Type_of_metabolism"]
    assert len(fap) == 4
    assert {row["primary_knowledge_source"] for row in fap} == {FAPROTAX_KNOWLEDGE_SOURCE}
    assert {row["predicate"] for row in fap} == {CAPABLE_OF_PREDICATE}
    assert {row["relation"] for row in fap} == {"RO:0002215"}
    assert {(row["knowledge_level"], row["agent_type"]) for row in fap} == {(PREDICTION, COMPUTATIONAL_MODEL)}
    assert {row["object"] for row in fap} == {
        "METPO:1002005" if mapped else "kgmicrobe.pathway:fermentation",
        "kgmicrobe.pathway:unknown_process",
    }
    assert Counter(row["value"] for row in fap) == {"fermentation": 2, "unknown_process": 2}
    raw_sha = hashlib.sha256((FIXTURE_DIR / "faprotax_evidence.csv").read_bytes()).hexdigest()
    assert {row["source_record"] for row in fap} == {f"sha256:{raw_sha}#record=1", f"sha256:{raw_sha}#record=2"}
    assert all(row["value_encoding"] == "backslash" for row in fap)
    assert all(not row[column] for row in fap for column in ("description", "publications", "source_citation"))
    controls = [row for row in edges if row not in fap]
    assert len(controls) == 14
    assert {(row["knowledge_level"], row["agent_type"]) for row in controls} == {(KNOWLEDGE_ASSERTION, MANUAL_AGENT)}
    assert {row["primary_knowledge_source"] for row in controls} == {
        "infores:bergey-manual",
        "infores:vpi-anaerobe-manual",
        "infores:microbedecoder-literature",
        "infores:microbedecoder",
    }
    # Other groups resolve to the same object but retain their own evidence tier.
    manual_capabilities = [row for row in controls if row["predicate"] == CAPABLE_OF_PREDICATE]
    assert len(manual_capabilities) == 6
    assert {row["object"] for row in manual_capabilities} == {
        "METPO:1002005" if mapped else "kgmicrobe.pathway:fermentation"
    }
    assert {row["predicate"] for row in controls} == {
        CAPABLE_OF_PREDICATE,
        "biolink:produces",
        "biolink:consumes",
        "biolink:has_attribute",
        "biolink:subclass_of",
    }


@pytest.mark.parametrize("mapped", [False, True])
def test_faprotax_capability_metadata_uses_source_context(tmp_path, mapped):
    """All FAPROTAX labels are predictions, independent of mapped/fallback object identity."""
    transform = _run(tmp_path, mapped)
    _check(_read(transform.output_edge_file), mapped)


def _finalize_child(root, mapped):
    """Run the normal registered finalizer with only copied code and immutable fixtures."""
    import socket

    from kg_microbe.utils.source_finalization import verify_finalized_source_files

    def offline(*args, **kwargs):
        """Block network access in the child, which does not inherit pytest fixtures."""
        raise RuntimeError("network forbidden in FAPROTAX finalization regression")

    socket.socket.connect = offline
    socket.getaddrinfo = offline
    assert Path(sys.modules[MicrobeDecoderTransform.__module__].__file__).resolve().is_relative_to(root)
    transform = _run(root / "data/transformed", mapped)
    before = _read(transform.output_edge_file)
    _check(before, mapped)
    report = transform.finalize(fresh_run=True)
    after = _read(transform.output_edge_file)
    _check(after, mapped)
    # Compare every literal field and duplicate occurrence, not merely SPO/tier.
    assert Counter(tuple(sorted(row.items())) for row in before) == Counter(tuple(sorted(row.items())) for row in after)
    assert report["source"] == "microbedecoder"
    assert report["producer_code"]["directory"] == str(root / "kg_microbe/transform_utils/microbedecoder")
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    print("FAPROTAX_FINALIZATION_PASS", mapped, len(after))


@pytest.mark.parametrize("mapped", [False, True])
def test_registered_finalization_preserves_faprotax_evidence(tmp_path, mapped):
    """Finalize real output without replacing any admission, normalization or fingerprint function."""
    root = tmp_path / "isolated"
    shutil.copytree(ROOT / "kg_microbe", root / "kg_microbe", ignore=shutil.ignore_patterns("__pycache__", "tmp"))
    for name in ("__init__.py", "test_microbedecoder_transform.py", Path(__file__).name):
        target = root / "tests" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tests" / name, target)
    shutil.copytree(FIXTURE_DIR, root / "tests/resources/microbedecoder")
    from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

    for relative in SHARED_DATA_INPUTS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    process_table = Path("mappings/canonical/microbedecoder_process_mappings.tsv")
    (root / process_table).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / process_table, root / process_table)
    phenotype_table = Path("mappings/canonical/microbedecoder_phenotype_mappings.tsv")
    shutil.copyfile(ROOT / phenotype_table, root / phenotype_table)
    # The injected resolver never reads unified mappings; give the real finalizer
    # an immutable declared-input fixture, not a production mapping symlink.
    (root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz").write_bytes(
        gzip.compress(b"subject_id\tpredicate_id\tobject_id\n", mtime=0)
    )
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.run(  # noqa: S603 - fixed interpreter and copied local regression module
        [sys.executable, "-B", "-m", "tests.test_microbedecoder_faprotax_evidence", str(root), str(int(mapped))],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert f"FAPROTAX_FINALIZATION_PASS {mapped} 18" in child.stdout


if __name__ == "__main__":
    if sys.flags.optimize or len(sys.argv) != 3:
        raise SystemExit("unoptimized fixture subprocess only")
    _finalize_child(Path(sys.argv[1]).resolve(), bool(int(sys.argv[2])))
