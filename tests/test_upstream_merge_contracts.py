"""The producer-to-archive boundary preserves already finalized source assertions."""

import csv
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.utils.source_finalization import graph_rows
from kg_microbe.utils.transform_fingerprint import data_fingerprint
from tests.test_merge_source_freshness import merge_config, prepare_source, record_source

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "resources/upstream_merge_legacy_edges.json"
POLICY = "mappings/ingredient_identity_exclusions.tsv"
pytestmark = pytest.mark.usefixtures("local_source_schema")


def test_ingredient_identity_policy_is_a_shared_content_dependency(tmp_path):
    """Policy edits and deletion invalidate prepared data even without producer-code changes."""
    policy = tmp_path / POLICY
    policy.parent.mkdir()
    policy.write_text("first policy\n")
    before = data_fingerprint(tmp_path, [])
    policy.touch()
    assert data_fingerprint(tmp_path, []) == before
    policy.write_text("second policy\n")
    assert data_fingerprint(tmp_path, []) != before
    policy.unlink()
    assert data_fingerprint(tmp_path, []) != before


@pytest.mark.parametrize("compressed", [False, True])
def test_legacy_source_finalizes_once_then_roundtrips_through_public_merge(tmp_path, compressed):
    """Real KGX merge preserves independent source evidence, scalar extensions, and source IDs."""
    source = prepare_source(tmp_path, "rhea_mappings")
    source.TSV_QUOTING = csv.QUOTE_NONE
    rows = json.loads(FIXTURE.read_text())
    with source.output_edge_file.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            quotechar=None,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    source.finalize(fresh_run=True)
    record_source(source)
    prepared_rows = list(graph_rows(source.output_edge_file))
    assert all(row["primary_knowledge_source"] == "infores:bacdive" for row in prepared_rows)
    assert {row["source_assertion_id"] for row in prepared_rows} == {"assertion:12", "assertion:13"}
    assert str((ROOT / POLICY).resolve()) in source.finalization_inputs
    prepared_bytes = {path.name: path.read_bytes() for path in source.output_dir.iterdir()}
    config = merge_config(tmp_path, [source])
    if compressed:
        payload = yaml.safe_load(config.read_text())
        payload["merged_graph"]["destination"]["tsv"]["compression"] = "tar.gz"
        config.write_text(yaml.safe_dump(payload))
    config_bytes = config.read_bytes()

    graph = merge_kg.load_and_merge(str(config), processes=1)
    assert graph.number_of_edges() == 2
    published = tmp_path / "published"
    if compressed:
        with tarfile.open(published / "fixture.tar.gz") as archive:
            edge_bytes = archive.extractfile("fixture_edges.tsv").read()
            manifest = json.load(archive.extractfile("manifest.json"))
            assert manifest["members"]["fixture_edges.tsv"]["sha256"] == hashlib.sha256(edge_bytes).hexdigest()
        assert not (published / "fixture_edges.tsv").exists()
    else:
        edge_bytes = (published / "fixture_edges.tsv").read_bytes()
    assert b"\r" not in edge_bytes
    merged_rows = list(csv.DictReader(io.StringIO(edge_bytes.decode()), delimiter="\t", quoting=csv.QUOTE_NONE))
    assert len(merged_rows) == 2
    assert not ({"id", "key", "knowledge_source"} & set(merged_rows[0]))
    merged_by_id = {row["source_assertion_id"]: row for row in merged_rows}
    for row in prepared_rows:
        merged = merged_by_id[row["source_assertion_id"]]
        for field, value in row.items():
            if field == "publications":
                assert set(merged[field].split("|")) == set(value.split("|"))
            else:
                assert merged[field] == value
    assert prepared_bytes == {path.name: path.read_bytes() for path in source.output_dir.iterdir()}
    assert config.read_bytes() == config_bytes
