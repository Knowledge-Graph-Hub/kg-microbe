"""Retain independent review regressions for non-self-authenticating archive evidence."""

import copy
import hashlib
import io
import json
import tarfile

import pytest

from kg_microbe.transform_utils.prego.native_inputs import archive_payload_identity, verify_native_contract
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows
from tests.test_prego_envo_identity import _producer


def test_cached_payload_and_self_reported_receipt_cannot_substitute_archive_bytes(tmp_path):
    """A coherently edited cache is recovered from actual native bytes, not accepted as new evidence."""
    producer = _producer(tmp_path)
    producer.run(show_status=False)
    original_edges = producer.output_edge_file.read_bytes()
    payload = next(
        path for archive, path in producer._payload_cache.items() if archive.name == "annotated_genomes_isolates.tar.gz"
    )
    original_payload = payload.read_bytes()
    replacement = original_payload.replace(b"ENVO:00000373", b"ENVO:99999999")
    assert replacement != original_payload and len(replacement) == len(original_payload)
    payload.write_bytes(replacement)
    receipt_path = payload.with_name("extraction-receipt.json")
    receipt = json.loads(receipt_path.read_text())
    receipt["payload_sha256"] = hashlib.sha256(replacement).hexdigest()
    receipt_path.write_text(json.dumps(receipt))
    producer.run(show_status=False)
    producer.verify_consumed_inputs()
    assert payload.read_bytes() == original_payload
    assert producer.output_edge_file.read_bytes() == original_edges


def test_saved_member_locator_requires_native_archive_membership(tmp_path):
    """A plausible basename is insufficient proof that the exact member exists in the archive."""
    producer = _producer(tmp_path, records=[])
    producer.run(show_status=False)
    contract = copy.deepcopy(producer.producer_native_inputs)
    next(iter(contract["archives"].values()))["member"] = "never-existed/database_pairs.tsv"
    with pytest.raises(SourceFinalizationRequired, match="member|archive|provenance"):
        verify_native_contract(contract, producer.consumed_input_snapshots, producer.input_base_dir)


def test_saved_payload_claim_requires_native_archive_content(tmp_path):
    """A rewritten report and cached payload still cannot contradict the unchanged native archive."""
    producer = _producer(tmp_path)
    producer.run(show_status=False)
    archive, payload = next(iter(producer._payload_cache.items()))
    replacement = payload.read_bytes().replace(b"ENVO:00000373", b"ENVO:99999999")
    payload.write_bytes(replacement)
    digest = hashlib.sha256(replacement).hexdigest()
    contract, snapshots = producer.producer_native_inputs, producer.consumed_input_snapshots
    contract["archives"][str(archive.absolute())]["payload_sha256"] = digest
    snapshots[f"prego_payload_{archive.name}"]["sha256"] = digest
    with pytest.raises(SourceFinalizationRequired, match="archive member"):
        verify_native_contract(contract, snapshots, producer.input_base_dir)


def test_foodon_successor_does_not_inherit_legacy_envo_environmental_feature_category(tmp_path):
    """The reviewed successor receives its own meaning, never a donor namespace default."""
    producer = _producer(tmp_path)
    producer.run(show_status=False)
    producer.finalize(fresh_run=True)
    nodes = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    assert nodes["FOODON:00001002"]["category"] == "biolink:Food"
    assert nodes["FOODON:00001002"]["name"] == "food product"
    assert nodes["ENVO:01000159"]["deprecated"] == "True"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "symlink"])
def test_archive_member_structure_failure_preserves_prior_cached_member(tmp_path, damage):
    """Atomic extraction publishes nothing until exact regular-member uniqueness is established."""
    archive = tmp_path / "input.tar.gz"
    payload = tmp_path / "database_pairs.tsv"
    payload.write_bytes(b"prior verified bytes\n")
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo("unrelated.tsv" if damage == "missing" else "first/database_pairs.tsv")
        if damage == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "unrelated.tsv"
            stream.addfile(member)
        else:
            member.size = 4
            stream.addfile(member, io.BytesIO(b"new\n"))
        if damage == "duplicate":
            second = tarfile.TarInfo("second/database_pairs.tsv")
            second.size = 6
            stream.addfile(second, io.BytesIO(b"other\n"))
    with pytest.raises(SourceFinalizationRequired):
        archive_payload_identity(archive, destination=payload)
    assert payload.read_bytes() == b"prior verified bytes\n"
