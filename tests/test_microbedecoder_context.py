"""Regression fixtures for source dimensions and evidence lost before merging (#1076)."""

import base64
import csv
import io
import json
import shutil
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.constants import GOLD_ORGANISM_FOLD_FILE
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

FIXTURES = Path(__file__).parent / "resources" / "microbedecoder"


class NoChemicals:
    """Keep the source-context regression independent of ontology services."""

    def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
        """Exercise the local placeholder path."""
        return None


def read_tsv(path):
    """Read only the tiny immutable fixture's generated output."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def run_fixture(tmp_path, fixture="snapshot_context.csv"):
    """Execute the actual producer including its final source deduplication."""
    input_path = FIXTURES / fixture
    if input_path.suffix == ".json":
        from kg_microbe.transform_utils.microbedecoder.utils import BACDIVE_SNAPSHOT_COLUMNS

        source_rows = json.loads(input_path.read_text())
        input_path = tmp_path / input_path.with_suffix(".csv").name
        with input_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["LPSN_ID", *BACDIVE_SNAPSHOT_COLUMNS])
            writer.writeheader()
            writer.writerows(source_rows)
    for source, dependency_fixture, target in (
        ("gold", GOLD_ORGANISM_FOLD_FILE, GOLD_ORGANISM_FOLD_FILE),
        ("gtdb", "gtdb_nodes.tsv", "nodes.tsv"),
    ):
        destination = tmp_path / source
        destination.mkdir(exist_ok=True)
        shutil.copyfile(FIXTURES / dependency_fixture, destination / target)
    transform = MicrobeDecoderTransform(FIXTURES, tmp_path, chemical_loader=NoChemicals())
    transform.run(data_file=input_path, show_status=False)
    return transform, read_tsv(transform.output_node_file), read_tsv(transform.output_edge_file)


def test_snapshot_preserves_dimensions_operators_and_record_context(tmp_path):
    """Motility/spores/temperature and inequalities must not become one generic number."""
    _, nodes, edges = run_fixture(tmp_path)
    snapshots = [edge for edge in edges if edge["predicate"] == "biolink:has_attribute"]
    assert len(snapshots) == 11
    assert all(edge["source_column"] and edge["source_record"] and edge["value"] for edge in snapshots)
    salt = [
        edge
        for edge in snapshots
        if edge["subject"] == "lpsn:101" and edge["source_column"] == "BacDive_Salt_concentration"
    ]
    assert {edge["value"] for edge in salt} == {"<1", "1", ">1"}
    assert len({edge["object"] for edge in salt}) == 3
    zeroes = [edge for edge in snapshots if edge["subject"] == "lpsn:101" and edge["value"] == "0"]
    assert len(zeroes) == 3
    assert len({edge["object"] for edge in zeroes}) == 2
    motility = [edge for edge in zeroes if edge["source_column"] == "BacDive_Motility"]
    assert len({edge["source_record"] for edge in motility}) == 2
    assert not any(node["id"] in {"kgmicrobe.trait:0", "kgmicrobe.trait:1"} for node in nodes)
    labels = {node["id"]: node["name"] for node in nodes}
    assert all(edge["value"] in labels[edge["object"]] for edge in salt)


def test_all_snapshot_families_are_reported_source_attributes(tmp_path):
    """Replay every source field without promoting codes, units or contexts to phenotypes."""
    from kg_microbe.transform_utils.microbedecoder.utils import BACDIVE_SNAPSHOT_COLUMNS

    source_rows = json.loads((FIXTURES / "source_attributes.json").read_text())
    _, nodes, edges = run_fixture(tmp_path, "source_attributes.json")
    attributes = [edge for edge in edges if edge["source_column"].startswith("BacDive_")]
    by_id = {node["id"]: node for node in nodes}
    expected = {
        (f"lpsn:{row['LPSN_ID']}", column, value)
        for row in source_rows
        for column, value in row.items()
        if column != "LPSN_ID"
    }
    assert {(edge["subject"], edge["source_column"], edge["value"]) for edge in attributes} == expected
    assert {edge["source_column"] for edge in attributes} == set(BACDIVE_SNAPSHOT_COLUMNS)
    assert all(edge["predicate"] == "biolink:has_attribute" for edge in attributes)
    assert all(edge["relation"] == "SIO:000008" for edge in attributes)
    assert all(edge["primary_knowledge_source"] == "infores:microbedecoder" for edge in attributes)
    assert all(edge["source_record"] and edge["value_encoding"] == "backslash" for edge in attributes)
    assert all(edge["object"].startswith("kgmicrobe.source_attribute:microbedecoder_") for edge in attributes)
    assert all(by_id[edge["object"]]["category"] == "biolink:Attribute" for edge in attributes)
    assert all("reported" in by_id[edge["object"]]["name"] for edge in attributes)
    assert all("not a decoded phenotype" in by_id[edge["object"]]["description"] for edge in attributes)
    assert not any(node["id"].startswith("kgmicrobe.trait:") for node in nodes)
    assert not any(edge["predicate"] == "biolink:has_phenotype" for edge in edges)
    # Gram-negative is a reported stain value, not a negated generic attribute;
    # 0/1 and +/- are also retained literally rather than decoded into biology.
    signed = {(edge["source_column"], edge["value"]) for edge in attributes}
    for field, values in {
        "BacDive_Gram_stain": {"positive", "negative"},
        "BacDive_Motility": {"0", "1"},
        "BacDive_Spore_formation": {"0", "1"},
        "BacDive_Indole_test": {"+", "-"},
        "BacDive_Voges_proskauer": {"+", "-"},
    }.items():
        assert all((field, value) in signed for value in values)


def test_source_attribute_signature_satisfies_pinned_biolink():
    """The explicit reported-attribute model fits both endpoints without retyping taxa."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    # Immutable excerpt of the pinned 4.4.2 definitions, independent of raw downloads.
    toolkit = Toolkit(schema=str(FIXTURES / "biolink-4.4.2-attributes.yaml"))
    attribute = toolkit.get_element("has attribute")
    assert "biolink:OrganismTaxon" in toolkit.get_descendants(attribute.domain, formatted=True)
    assert "biolink:Attribute" in toolkit.get_descendants(attribute.range, formatted=True)
    assert "SIO:000008" in attribute.exact_mappings
    phenotype = toolkit.get_element("has phenotype")
    assert "biolink:OrganismTaxon" not in toolkit.get_descendants(phenotype.domain, formatted=True)
    assert "biolink:PhenotypicQuality" not in toolkit.get_descendants(phenotype.range, formatted=True)


@pytest.mark.parametrize(
    "column,value,expected",
    [
        ("BacDive_Indole_test", "+", ["+"]),
        ("BacDive_Indole_test", " - ", ["-"]),
        ("BacDive_Voges_proskauer", "-", ["-"]),
        ("BacDive_Voges_proskauer", "+,-", ["+", "-"]),
        ("BacDive_Indole_test", "NA", []),
        ("BacDive_Voges_proskauer", None, []),
        ("BacDive_Motility", "-", []),
        ("BacDive_Indole_test", "", []),
        ("BacDive_Motility", "0", ["0"]),
        ("BacDive_Metabolite_utilization", "2,3-butanediol, glucose", ["2,3-butanediol", "glucose"]),
    ],
)
def test_snapshot_signed_field_tokens_do_not_change_generic_missingness(column, value, expected):
    """Lone '-' survives only in the two signed assay fields, with no biological decoding."""
    from kg_microbe.transform_utils.microbedecoder.utils import split_snapshot_values

    assert split_snapshot_values(column, value) == expected


def test_source_attribute_namespace_and_relation_are_registered():
    """The explicit dynamic namespace and pinned SIO IRI are registered for graph consumers."""
    root = Path(__file__).resolve().parents[1]
    registry = yaml.safe_load((root / "kg_microbe/transform_utils/custom_curies.yaml").read_text())
    prefixmap = json.loads((root / "kg_microbe/transform_utils/prefixmap.json").read_text())
    assert "kgmicrobe.source_attribute" in registry
    assert "kgmicrobe.source_attribute" in prefixmap
    assert prefixmap["SIO"] == "http://semanticscience.org/resource/SIO_"


def test_metabolism_citations_and_major_minor_qualifiers_survive_source_dedup(tmp_path):
    """The same producer helper also discarded citations and major/minor qualifiers."""
    _, _, edges = run_fixture(tmp_path)
    products = [edge for edge in edges if edge["predicate"] == "biolink:produces"]
    assert len(products) == 2
    assert {edge["description"] for edge in products} == {"major", "minor"}
    assert {edge["publications"] for edge in products} == {"PMID:12345"}


def test_repeat_run_is_byte_identical(tmp_path):
    """Reusing a producer must reset per-run node and context state."""
    transform, _, _ = run_fixture(tmp_path)
    before = (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    transform.run(data_file=FIXTURES / "snapshot_context.csv", show_status=False)
    assert (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()) == before


def test_later_run_without_placeholders_clears_old_curation_rows(tmp_path):
    """Rerun reset must include the persisted curation queue, not just node caches."""
    transform, _, _ = run_fixture(tmp_path)
    report = transform.output_dir / "unmapped_labels.tsv"
    assert read_tsv(report)
    source = tmp_path / "crosswalk_only.csv"
    source.write_text("LPSN_ID,NCBI_Taxonomy_ID\n101,1\n")
    transform.run(data_file=source, show_status=False)
    assert read_tsv(report) == []


def test_mapping_lookup_io_failure_is_not_an_unmapped_chemical(tmp_path):
    """A missing match is None; failed authority infrastructure must abort the source."""
    transform, _, _ = run_fixture(tmp_path)
    before = (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())

    class BrokenMapping:
        """Simulate an unavailable mapping authority during lookup."""

        def find_chebi_by_name(self, *args, **kwargs):
            """Raise an IO failure rather than returning a legitimate no-match."""
            raise OSError("mapping authority read failed")

    transform.chemical_loader = BrokenMapping()
    with pytest.raises(OSError, match="mapping authority read failed"):
        transform.run(data_file=FIXTURES / "snapshot_context.csv", show_status=False)
    assert (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()) == before


def test_required_mapping_initialization_failure_preserves_outputs(tmp_path, monkeypatch):
    """A broken required map must fail before replacing a previously emitted pair."""
    import kg_microbe.utils.chemical_mapping_utils as mappings

    transform, _, _ = run_fixture(tmp_path)
    before = (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())

    def fail_load():
        """Simulate a missing required curation input."""
        raise FileNotFoundError("required mapping is missing")

    monkeypatch.setattr(mappings, "ChemicalMappingLoader", fail_load)
    transform.chemical_loader = None
    with pytest.raises(FileNotFoundError, match="required mapping is missing"):
        transform.run(data_file=FIXTURES / "snapshot_context.csv", show_status=False)
    assert (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()) == before


@pytest.mark.parametrize("fixture", ["snapshot_context.csv", "citation_context.csv", "source_attributes.json"])
def test_actual_kgx_archive_retains_source_context(tmp_path, monkeypatch, fixture):
    """Source dimensions and major/minor citations survive the real KGX pipeline."""
    from kg_microbe.merge_utils.merge_kg import merge
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    transform, _, before = run_fixture(tmp_path, fixture)
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": {
                        "microbedecoder": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(transform.output_node_file), str(transform.output_edge_file)],
                            }
                        }
                    },
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "context"}},
                },
            }
        )
    )
    merge(str(config), processes=1)
    with tarfile.open(tmp_path / "context.tar.gz") as archive:
        with archive.extractfile("context_edges.tsv") as stream:
            after = list(csv.DictReader(io.TextIOWrapper(stream), delimiter="\t", quoting=csv.QUOTE_NONE))
    fields = (
        "subject",
        "predicate",
        "object",
        "source_column",
        "source_record",
        "value",
        "value_encoding",
        "description",
        "publications",
        "source_citation",
        "source_citation_base64",
    )
    assert {tuple(edge.get(field, "") for field in fields) for edge in after} == {
        tuple(edge[field] for field in fields) for edge in before
    }
    assert len(after) == len(before)


def test_citation_prose_and_all_recognized_identifiers_survive(tmp_path):
    """Round-1 review #1083: prose is evidence even when it has no identifier."""
    _, _, edges = run_fixture(tmp_path, "citation_context.csv")
    assert len(edges) == 4
    keyed = {edge["source_citation"]: edge for edge in edges}
    assert set(keyed) == {
        "PMID:123; PMID:456; 10.1234/demo",
        'Author "Title" (1989).\\nSecond line',
        "Author B, book (1980)",
        "https://doi.org/10.1002/9781118960608.gbm00580",
    }
    assert set(keyed["PMID:123; PMID:456; 10.1234/demo"]["publications"].split("|")) == {
        "PMID:123",
        "PMID:456",
        "doi:10.1234/demo",
    }
    assert keyed['Author "Title" (1989).\\nSecond line']["publications"] == ""
    assert keyed["Author B, book (1980)"]["publications"] == ""
    assert (
        keyed["https://doi.org/10.1002/9781118960608.gbm00580"]["publications"] == "doi:10.1002/9781118960608.gbm00580"
    )
    assert (
        base64.b64decode(keyed['Author "Title" (1989).\\nSecond line']["source_citation_base64"])
        == b'Author "Title" (1989).\nSecond line'
    )


def test_non_utf8_citation_bytes_are_recoverable(tmp_path):
    """A rare Latin-1 byte in otherwise UTF-8 source text must not erase the citation."""
    transform, _, _ = run_fixture(tmp_path)
    source = tmp_path / "mixed_encoding.csv"
    source.write_bytes(b"LPSN_ID,Literature_Major_end_products,Literature_Citation\n101,acetate,Pr\xe9vot (1989)\n")
    transform.run(data_file=source, show_status=False)
    edge = read_tsv(transform.output_edge_file)[0]
    assert edge["source_citation"] == "Pr\ufffdvot (1989)"
    assert base64.b64decode(edge["source_citation_base64"]) == b"Pr\xe9vot (1989)"
    assert edge["publications"] == ""


def test_source_locants_retain_independently_expected_tokens(tmp_path):
    """Real-source locant shapes must not produce chemical fragments as separate assertions."""
    _, _, edges = run_fixture(tmp_path, "locant_context.csv")
    assert {(edge["source_column"], edge["value"]) for edge in edges} == {
        ("BacDive_Metabolite_utilization", "2,3-butanediol"),
        ("BacDive_Metabolite_utilization", "acetate"),
        ("BacDive_Enzyme_activity", "endo-1,4-beta-xylanase"),
        ("Bergey_Major_end_products", "2,3-butanediol"),
        ("Bergey_Major_end_products", "ethanol"),
    }


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("1,2,3-trihydroxybenzene;acetate", ["1,2,3-trihydroxybenzene", "acetate"]),
        ("1,2,3", ["1", "2", "3"]),
        ("acetate, lactate", ["acetate", "lactate"]),
        ("endo-1,4-beta-xylanase;enzyme (1,2)", ["endo-1,4-beta-xylanase", "enzyme (1,2)"]),
    ],
)
def test_locant_protection_is_not_general_comma_suppression(cell, expected):
    """Numeric lists remain lists; bracket content and chemical locants remain intact."""
    from kg_microbe.transform_utils.microbedecoder.utils import split_multivalue

    assert split_multivalue(cell) == expected


def test_literal_context_does_not_use_csv_quoting_or_coerce_numbers(tmp_path, monkeypatch):
    """Quotes, control characters, zeros and leading zeros remain distinguishable."""
    from kg_microbe.merge_utils.kgx_source import parse_source

    transform, _, _ = run_fixture(tmp_path)
    source = tmp_path / "literal.csv"
    labels = ['"quoted"', "0", "00", "<1", ">1", "line\nbreak", "tab\there", r"literal\n"]
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["LPSN_ID", "BacDive_Oxygen_tolerance"])
        writer.writerows([101, value] for value in labels)
    transform.run(data_file=source, show_status=False)
    edges = read_tsv(transform.output_edge_file)
    assert len(edges) == len(labels)
    assert len({edge["object"] for edge in edges}) == len(labels)
    assert {edge["value"] for edge in edges} == {
        '"quoted"',
        "0",
        "00",
        "<1",
        ">1",
        r"line\nbreak",
        r"tab\there",
        r"literal\\n",
    }
    assert {edge["value_encoding"] for edge in edges} == {"backslash"}
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    parsed = parse_source(
        "microbedecoder",
        {
            "input": {
                "format": "tsv",
                "filename": [str(transform.output_node_file), str(transform.output_edge_file)],
            }
        },
        str(tmp_path / "parsed"),
    )
    assert {edge["value"] for _, _, edge in parsed.graph.edges(data=True)} == {edge["value"] for edge in edges}
