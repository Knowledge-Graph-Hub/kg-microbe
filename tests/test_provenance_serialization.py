"""Keep BacDive record attribution machine-readable through real KGX merging (#1070)."""

import csv
import io
import json
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path
from unittest import mock

import pytest
import yaml

from kg_microbe.transform_utils.bacdive.emission import StrainProvenanceWriter
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.biolink_model import prepare_kgx
from kg_microbe.utils.provenance import (
    knowledge_source_tokens,
    primary_source_and_publications,
    serialize_knowledge_sources,
)
from kg_microbe.utils.tsv_io import tsv_writer

FIXTURES = Path(__file__).parent / "resources" / "provenance_serialization"


@pytest.fixture
def media_transform(tmp_path, monkeypatch):
    """Run the real growth-edge writer against immutable, offline MediaDive inputs."""
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", FIXTURES)
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)
    with (
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(mod.MediaDiveTransform, "_load_micromediaparam_mappings"),
        mock.patch.object(mod.MediaDiveTransform, "_load_bulk_data"),
        mock.patch.object(mod, "ChemicalMappingLoader"),
    ):
        transform = mod.MediaDiveTransform(input_dir=FIXTURES, output_dir=tmp_path / "out")
    transform.using_bulk_data = True
    strains = json.loads((FIXTURES / "medium_strains.json").read_text())

    def fixture_response(path, endpoint, directory):
        """No solutions are needed to exercise positive, negative, and unknown growth."""
        return strains if endpoint.startswith(mod.MEDIUM_STRAINS) else {}

    monkeypatch.setattr(transform, "get_json_object", fixture_response)
    transform.run(show_status=False)
    return transform


def _growth_rows(transform):
    """Read just the strain-growth rows emitted by the small fixture transform."""
    with transform.output_edge_file.open(newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if row["subject"].startswith("kgmicrobe.strain:")]


def test_serialization_flattens_tokens_without_losing_record_attribution():
    """Separate records remain distinct; repeated source tokens collapse once."""
    values = ["PMID:1|https://bacdive.dsmz.de/strain/1", ["PMID:1", "PMID:2"], None]
    assert knowledge_source_tokens(values) == ["PMID:1", "https://bacdive.dsmz.de/strain/1", "PMID:2"]
    assert serialize_knowledge_sources(values) == "PMID:1|https://bacdive.dsmz.de/strain/1|PMID:2"


@pytest.mark.parametrize(
    "legacy", ["['infores:bacdive', 'bacdive:1']", "infores:bacdive|bacdive:1", ["infores:bacdive", "bacdive:1"]]
)
def test_legacy_record_attribution_migrates_to_publications_idempotently(legacy):
    """Old syntax migrates without discarding a supplied publication or inventing a provider."""
    expected = ("infores:bacdive", ["PMID:7", "https://bacdive.dsmz.de/strain/1"])
    assert primary_source_and_publications(legacy, "PMID:7") == expected
    assert primary_source_and_publications(*expected) == expected


def test_multiple_primary_resources_fail_without_replicating_combined_evidence():
    """A legacy pooled primary-source field cannot establish each provider's observation."""
    with pytest.raises(ValueError, match="Multiple primary information resources"):
        primary_source_and_publications("infores:one|infores:two", "PMID:1|PMID:2")


@pytest.mark.parametrize(
    "alias,resource",
    [
        ("chebi.json", "infores:chebi"),
        ("ncbitaxon_removed_subset.json", "infores:ncbitaxon"),
        ("mediadive", "infores:mediadive"),
        ("MediaDive", "infores:mediadive"),
    ],
)
def test_only_verified_legacy_resource_aliases_are_migrated(alias, resource):
    """Recognize known producer placeholders without minting resources from arbitrary filenames."""
    assert primary_source_and_publications(alias) == (resource, [])
    with pytest.raises(ValueError, match="must identify an information resource"):
        primary_source_and_publications("an_unregistered_resource.json")


def test_mediadive_growth_provenance_matches_bacdive_and_retains_polarity(media_transform):
    """Changing syntax must not alter attribution, growth polarity, or evidence metadata."""
    rows = _growth_rows(media_transform)
    assert len(rows) == 3
    assert {row["primary_knowledge_source"] for row in rows} == {"infores:bacdive"}
    assert {row["publications"] for row in rows} == {
        "https://bacdive.dsmz.de/strain/160227",
        "https://bacdive.dsmz.de/strain/160228",
        "https://bacdive.dsmz.de/strain/999",
    }
    for row in rows:
        assert row["knowledge_level"] == "observation"
        assert row["agent_type"] == "manual_agent"
        if row["subject"].endswith("999"):
            assert row["predicate"] == mod.NCBI_TO_MEDIUM_NEGATIVE_EDGE
            assert row["relation"] == mod.DOES_NOT_GROW_IN
        else:
            assert row["predicate"] == mod.NCBI_TO_MEDIUM_EDGE
            assert row["relation"] == mod.IS_GROWN_IN
        if row["publications"].endswith("160228"):
            continue  # This fixture's second record maps to the same strain.
        stream = io.StringIO(newline="")
        writer = StrainProvenanceWriter(
            tsv_writer(stream), knowledge_source="infores:bacdive", ks_column_index=4, publications_column_index=9
        )
        values = [row[column] for column in media_transform.edge_header]
        values[4] = "infores:bacdive"
        writer.writerow(values)
        assert next(csv.reader(io.StringIO(stream.getvalue()), delimiter="\t")) == [
            row[column] for column in media_transform.edge_header
        ]


def test_real_kgx_archive_round_trip_unions_individual_source_and_record_tokens(media_transform, tmp_path, monkeypatch):
    """Both producers pass through actual source ingestion, graph merge, and tar export."""
    prepare_kgx()

    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    bacdive_edges = tmp_path / "bacdive_edges.tsv"
    with bacdive_edges.open("w", newline="") as handle:
        raw_writer = tsv_writer(handle)
        raw_writer.writerow(media_transform.edge_header)
        writer = StrainProvenanceWriter(
            raw_writer, knowledge_source="infores:bacdive", ks_column_index=4, publications_column_index=9
        )
        for row in _growth_rows(media_transform):
            if row["publications"].endswith("160228"):
                continue  # BacDive's direct record is distinct from MediaDive's second record.
            values = [row[column] for column in media_transform.edge_header]
            values[4] = "infores:bacdive"
            writer.writerow(values)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": {
                        "bacdive": {"input": {"format": "tsv", "filename": [str(bacdive_edges)]}},
                        "mediadive": {"input": {"format": "tsv", "filename": [str(media_transform.output_edge_file)]}},
                    },
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "merged"}},
                },
            }
        ),
        encoding="utf-8",
    )
    merge(str(config), processes=2)
    with tarfile.open(tmp_path / "merged.tar.gz") as archive:
        with archive.extractfile("merged_edges.tsv") as handle:
            rows = list(csv.DictReader(io.TextIOWrapper(handle), delimiter="\t"))
    growth = {row["publications"]: row for row in rows if row["subject"].startswith("kgmicrobe.strain:")}
    assert len(growth) == 3
    assert growth["https://bacdive.dsmz.de/strain/160227"]["subject"] == "kgmicrobe.strain:bacdive_160227"
    assert growth["https://bacdive.dsmz.de/strain/160228"]["subject"] == "kgmicrobe.strain:bacdive_160227"
    assert growth["https://bacdive.dsmz.de/strain/999"]["subject"] == "kgmicrobe.strain:bacdive_999"
    for row in growth.values():
        assert row["primary_knowledge_source"] == "infores:bacdive"
        assert row["knowledge_level"] == "observation"
        assert row["agent_type"] == "manual_agent"
