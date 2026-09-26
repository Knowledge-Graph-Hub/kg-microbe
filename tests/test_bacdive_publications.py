"""Keep item-specific BacDive DOI evidence separate from scalar primary provenance."""

import csv
import io
import json
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.bacdive.emission import StrainProvenanceWriter
from kg_microbe.transform_utils.bacdive.references import item_publications, publication_doi, reference_dois
from kg_microbe.transform_utils.constants import PUBLICATIONS_COLUMN
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.biolink_model import prepare_kgx
from kg_microbe.utils.source_finalization import graph_rows
from kg_microbe.utils.tsv_io import tsv_writer

FIXTURES = Path(__file__).parent / "resources" / "bacdive_publications"


@pytest.mark.parametrize(
    "value", ["10.1234/ABC", "doi:10.1234/ABC", "https://doi.org/10.1234/abc", "http://dx.doi.org/10.1234/AbC"]
)
def test_doi_spellings_have_one_identity(value):
    """Case, DOI CURIE, and resolver-URL forms denote the same publication token."""
    assert publication_doi(value) == "doi:10.1234/abc"


@pytest.mark.parametrize(
    "value",
    [
        None,
        7,
        {},
        "",
        "10.1/bad",
        "10.1234/null\x00byte",
        "10.1234/delete\x7fbyte",
        "10.1234/has space",
        "10.1234/one|doi:10.1234/two",
        "https://example.org/10.1234/paper",
        "https://www.dsmz.de/collection/DSM-1",
        "10.13145/bacdive1.20221219.7",
        "https://doi.org/10.13145/BacDive1.7",
    ],
)
def test_nonpublication_and_malformed_values_are_not_guessed(value):
    """A catalogue URL or record DOI cannot masquerade as supporting literature."""
    assert publication_doi(value) is None


def test_reference_shapes_keys_duplicates_and_ambiguity():
    """Only explicit, unambiguous numeric reference pointers establish publication support."""
    entries = [
        {"@id": 7, "doi/url": "10.1234/ABC"},
        {"@id": "007", "doi/url": "https://doi.org/10.1234/abc"},
        {"@id": 8, "doi/url": "10.1234/one"},
        {"@id": "8", "doi/url": "10.1234/other"},
        {"@id": True, "doi/url": "10.1234/not-numeric"},
        {"@id": "bad", "doi/url": "10.1234/invalid-key"},
        None,
    ]
    assert reference_dois({"Reference": entries}) == {"7": "doi:10.1234/abc"}
    references = reference_dois({"Reference": entries[0]})
    assert item_publications({"@ref": [7, "007", 404]}, references) == "doi:10.1234/abc"
    assert item_publications({"@ref": True}, references) == ""
    for shape in (None, "bad", 4, []):
        assert reference_dois({"Reference": shape}) == {}


class _Nodes:
    """Collect producer node rows for its normal deduplication boundary."""

    def __init__(self):
        """Start a stable node ID index."""
        self.rows = {}

    def writerow(self, row):
        """Retain one declaration per node, as BacDive's final deduplication does."""
        self.rows[row[0]] = row


@pytest.fixture
def utilization_bundle(tmp_path):
    """Run the actual utilization emitter/writer on both immutable input shapes."""
    raw = tmp_path / "raw"
    raw.mkdir()
    # The generic finalization wrapper tests schema/provenance admission without
    # pretending this small fixture ran BacDive's unrelated ontology/assay setup.
    bundle = Transform("bacdive", raw, tmp_path / "transformed")
    bundle.edge_header.extend(["value", "unit", PUBLICATIONS_COLUMN])
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.node_header = bundle.node_header
    transform.knowledge_source = "infores:bacdive"
    transform.chemical_loader = None
    transform.chebi_categories = {}
    transform.metpo_metabolite_utilization_mappings = {
        "carbon source": {"+": {"curie": "METPO:2000006"}, "-": {"curie": "METPO:2000031"}}
    }
    nodes = _Nodes()
    with bundle.output_edge_file.open("w", newline="") as handle:
        raw_writer = tsv_writer(handle)
        raw_writer.writerow(bundle.edge_header)
        writer = StrainProvenanceWriter(
            raw_writer,
            knowledge_source="infores:bacdive",
            ks_column_index=4,
            publications_column_index=bundle.edge_header.index(PUBLICATIONS_COLUMN),
        )
        for record in json.loads((FIXTURES / "records.json").read_text()):
            identifier = f"kgmicrobe.strain:bacdive_{record['General']['BacDive-ID']}"
            nodes.writerow(transform._create_node_row(identifier, "biolink:OrganismTaxon", identifier))
            transform._emit_metabolite_utilization(
                record["Physiology and metabolism"]["metabolite utilization"],
                identifier,
                nodes,
                writer,
                reference_dois(record),
            )
        # An unrelated assertion gets record evidence, never an arbitrary record DOI.
        writer.writerow(
            [
                "kgmicrobe.strain:bacdive_1",
                "biolink:related_to",
                "CHEBI:17234",
                "skos:related",
                "infores:bacdive",
                "observation",
                "manual_agent",
            ]
        )
    with bundle.output_node_file.open("w", newline="") as handle:
        writer = tsv_writer(handle)
        writer.writerow(bundle.node_header)
        writer.writerows(nodes.rows.values())
    return bundle


def _assert_scoped_evidence(rows):
    """Check polarity, citation pairing, and absence of record-wide DOI leakage."""
    assert len(rows) == 6
    assert {row["primary_knowledge_source"] for row in rows} == {"infores:bacdive"}
    for row in rows:
        assert row["knowledge_level"] == "observation"
        assert row["agent_type"] == "manual_agent"
        assert "unrelated" not in row["publications"]
        assert len(row["publications"].split("|")) == len(set(row["publications"].split("|")))
    keyed = {(row["subject"], row["predicate"], frozenset(row["publications"].split("|"))) for row in rows}
    first = "https://bacdive.dsmz.de/strain/1"
    second = "https://bacdive.dsmz.de/strain/2"
    assert keyed == {
        ("kgmicrobe.strain:bacdive_1", "METPO:2000006", frozenset([first, "doi:10.1234/positive"])),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000031", frozenset([first, "doi:10.1234/negative"])),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000006", frozenset([first, "doi:10.1234/positive-second"])),
        ("kgmicrobe.strain:bacdive_1", "METPO:2000006", frozenset([first])),
        ("kgmicrobe.strain:bacdive_2", "METPO:2000006", frozenset([second, "doi:10.1234/second-record"])),
        ("kgmicrobe.strain:bacdive_1", "biolink:related_to", frozenset([first])),
    }


def test_real_utilization_emission_and_source_finalization(utilization_bundle):
    """The source emits canonical provenance; finalization retains the same six observations."""
    before = list(graph_rows(utilization_bundle.output_edge_file))
    _assert_scoped_evidence(before)
    utilization_bundle.finalize()
    after = list(graph_rows(utilization_bundle.output_edge_file))
    _assert_scoped_evidence(after)
    assert [row["publications"] for row in before] == [row["publications"] for row in after]


@pytest.mark.parametrize("as_list", [False, True])
def test_utilization_without_optional_display_name_retains_identity_and_evidence(tmp_path, as_list):
    """A ChEBI identifier supplies identity even when its optional source display name is absent."""
    bundle = Transform("bacdive", tmp_path / "raw", tmp_path / "transformed")
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.node_header = bundle.node_header
    transform.knowledge_source = "infores:bacdive"
    transform.chemical_loader = None
    transform.chebi_categories = {}
    transform.metpo_metabolite_utilization_mappings = {"carbon source": {"+": {"curie": "METPO:2000006"}}}
    item = {
        "Chebi-ID": "17234",
        "kind of utilization tested": "carbon source",
        "utilization activity": "+",
        "@ref": "7",
    }
    nodes = _Nodes()
    stream = io.StringIO(newline="")
    writer = StrainProvenanceWriter(
        tsv_writer(stream), knowledge_source="infores:bacdive", ks_column_index=4, publications_column_index=7
    )
    transform._emit_metabolite_utilization(
        [item] if as_list else item,
        "kgmicrobe.strain:bacdive_1",
        nodes,
        writer,
        {"7": "doi:10.1234/positive"},
    )
    assert nodes.rows["CHEBI:17234"][bundle.node_header.index("name")] is None
    row = next(csv.reader(io.StringIO(stream.getvalue()), delimiter="\t"))
    assert row[:3] == ["kgmicrobe.strain:bacdive_1", "METPO:2000006", "CHEBI:17234"]
    assert row[4] == "infores:bacdive"
    assert set(row[7].split("|")) == {"doi:10.1234/positive", "https://bacdive.dsmz.de/strain/1"}


def test_writer_unions_existing_publications_and_deduplicates_doi_urls():
    """Explicit DOI evidence is additive, never a replacement for record URLs or other citations."""
    stream = io.StringIO(newline="")
    writer = StrainProvenanceWriter(
        tsv_writer(stream), knowledge_source="infores:bacdive", ks_column_index=4, publications_column_index=7
    )
    existing = "PMID:123|https://doi.org/10.1234/ABC|https://bacdive.dsmz.de/strain/1"
    writer.writerow(
        [
            "kgmicrobe.strain:bacdive_1",
            "METPO:2000006",
            "CHEBI:17234",
            "RO:0000057",
            "infores:bacdive",
            "observation",
            "manual_agent",
            existing,
        ],
        publications="doi:10.1234/abc",
    )
    row = next(csv.reader(io.StringIO(stream.getvalue()), delimiter="\t"))
    assert row[4] == "infores:bacdive"
    assert row[7].split("|") == ["PMID:123", "doi:10.1234/abc", "https://bacdive.dsmz.de/strain/1"]


def test_actual_kgx_archive_preserves_item_publication_pairing(utilization_bundle, tmp_path, monkeypatch):
    """Different papers stay paired with their own assertion through public KGX serialization."""
    utilization_bundle.finalize()
    prepare_kgx()
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": {
                        "bacdive": {
                            "input": {
                                "format": "tsv",
                                "filename": [
                                    str(utilization_bundle.output_node_file),
                                    str(utilization_bundle.output_edge_file),
                                ],
                            }
                        }
                    },
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "merged"}},
                },
            }
        )
    )
    merge(str(config), processes=1)
    with tarfile.open(tmp_path / "merged.tar.gz") as archive:
        with archive.extractfile("merged_edges.tsv") as stream:
            _assert_scoped_evidence(list(csv.DictReader(io.TextIOWrapper(stream), delimiter="\t")))
