"""Keep two ambiguous Bergey sugar materials record-scoped without changing native Sugar (#1180)."""

import base64
import csv
import hashlib
import io
import json
import shutil
import tarfile
from copy import deepcopy
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.constants import GOLD_ORGANISM_FOLD_FILE
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.test_chemical_mapping_utils import reset_cache as reset_cache

FIXTURES = Path(__file__).parent / "resources/microbedecoder"
FIXTURE = FIXTURES / "bergey_unresolved_sugar.json"
COLUMN = "Bergey_Substrates_for_end_products"
OLD = "NCIT:C71939"


class ChemicalLookup:
    """Resolve the reviewed external targets without any ontology/database access."""

    def __init__(self, sugar=OLD):
        """Allow finite negative controls to change the old Sugar route."""
        self.sugar = sugar

    def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
        """Keep unrelated chemistry on its existing missing-match path."""
        return {"sugar": self.sugar, "mucin": "NCIT:C16883", "Sugar": OLD}.get(label)

    def get_canonical_name(self, curie):
        """Supply synthetic local metadata only for a changed-route negative."""
        return "sugar"

    def get_category(self, curie):
        """Supply the deliberately generic local material category."""
        return "biolink:ChemicalEntity"


def _fixture():
    """Load only immutable saved source projections, never production records."""
    return json.loads(FIXTURE.read_text())


def _records():
    """Return both own-record Sugar claims plus the unrelated Mucin control."""
    return [deepcopy(_fixture()["raw_records"][key]) for key in ("1200", "6810", "944")]


def _read(path):
    """Read tiny generated fixture TSVs with the actual literal escaping policy."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _run(tmp_path, records=None, lookup=None):
    """Run the unchanged full producer pipeline on a fresh tiny CSV."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = _records() if records is None else records
    source = tmp_path / "database.csv"
    fields = list(dict.fromkeys(field for record in records for field in record))
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    for name, filename in (("gold", GOLD_ORGANISM_FOLD_FILE), ("gtdb", "nodes.tsv")):
        destination = tmp_path / name
        destination.mkdir()
        shutil.copyfile(FIXTURES / (filename if name == "gold" else "gtdb_nodes.tsv"), destination / filename)
    transform = MicrobeDecoderTransform(tmp_path, tmp_path, chemical_loader=lookup or ChemicalLookup())
    transform.run(data_file=source, show_status=False)
    return transform, _read(transform.output_node_file), _read(transform.output_edge_file), source


def _substrates(edges):
    """Select the actual field, not any edge sharing a chemical target."""
    return [edge for edge in edges if edge["source_column"] == COLUMN]


def _scoped_id(record):
    """Independently calculate the documented local identity without calling the producer."""
    text = json.dumps(
        ["microbedecoder", record, COLUMN, "sugar"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        "kgmicrobe.compound:microbedecoder_unresolved_"
        + hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()
    )


def test_two_full_records_keep_exact_observations_and_distinct_local_nodes(tmp_path):
    """Change only the unsupported target plus explicit disposition/original-object evidence."""
    transform, nodes, edges, source = _run(tmp_path)
    selected = _substrates(edges)
    assert len(selected) == 3
    historical = {row["subject"]: row for row in _fixture()["historical_edges"]}
    node_map = {row["id"]: row for row in nodes}
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for position, record in enumerate(_records(), start=1):
        subject = "lpsn:" + record["LPSN_ID"]
        row = next(row for row in selected if row["subject"] == subject)
        expected = historical[subject]
        for field in expected.keys() - {"object", "original_object", "source_record", "original_subject"}:
            assert row[field] == expected[field]
        assert row["source_record"] == f"sha256:{digest}#record={position}"
        assert base64.b64decode(row["source_citation_base64"]).decode() == record["Bergey_Article_link"]
        if record["Bergey_Substrates_for_end_products"] == "mucin":
            assert row["object"] == "NCIT:C16883"
            assert row["original_object"] == row["description"] == ""
            continue
        assert row["object"] == _scoped_id(record)
        assert row["original_object"] == OLD
        node = node_map[row["object"]]
        assert "withdrawn for this record/field only" in node["description"]
        assert node["name"] == "sugar"
        assert node["category"] == "biolink:ChemicalEntity"
        assert node["provided_by"] == "infores:microbedecoder"
        assert not node.get("xref") and not node.get("same_as") and not node.get("synonym")
    local = [row for row in selected if row["original_object"] == OLD]
    assert len({row["object"] for row in local}) == 2
    assert not any(row["object"] == OLD for row in selected)
    queue = _read(transform.output_dir / "unmapped_labels.tsv")
    local_queue = [row for row in queue if row["placeholder_curie"] in {edge["object"] for edge in local}]
    assert len(local_queue) == 2
    assert all(row["source_columns"] == COLUMN and row["occurrences"] == "1" for row in local_queue)


def test_row_and_column_reordering_do_not_change_local_material_ids(tmp_path):
    """CSV locators follow the new input bytes/positions, but material IDs do not use them."""
    records = _records()
    _, _, first, _ = _run(tmp_path / "first", records)
    reversed_records = [dict(reversed(list(record.items()))) for record in reversed(records)]
    _, _, second, _ = _run(tmp_path / "second", reversed_records)
    assert {row["subject"]: row["object"] for row in _substrates(first)} == {
        row["subject"]: row["object"] for row in _substrates(second)
    }
    assert {row["source_record"] for row in first}.isdisjoint({row["source_record"] for row in second})


def test_distinct_record_contexts_do_not_pool_and_duplicate_assertions_survive(tmp_path):
    """Same taxon/field/label can report distinct materials; identical rows keep distinct locators."""
    first = _records()[0]
    changed = {**first, "Bergey_Strain": "independent synthetic strain"}
    _, nodes, edges, _ = _run(tmp_path, [first, first, changed])
    selected = _substrates(edges)
    assert len(selected) == 3
    assert len({row["source_record"] for row in selected}) == 3
    assert selected[0]["object"] in {_scoped_id(first), _scoped_id(changed)}
    assert {row["object"] for row in selected} == {_scoped_id(first), _scoped_id(changed)}
    assert len([row for row in nodes if row["id"] in {edge["object"] for edge in selected}]) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Bergey_Article_link", "https://doi.org/10.1002/9781118960608.gbm00020"),
        ("Bergey_Article_link", ""),
        ("Bergey_Text_for_substrates", ""),
        ("Bergey_Text_for_substrates", "sucrose"),
        (COLUMN, "sugar;glucose"),
        (COLUMN, " sugar "),
        (COLUMN, "Sugar"),
        (COLUMN, "glucose"),
        (COLUMN, ""),
        (COLUMN, "NA"),
        ("LPSN_ID", " 773071"),
    ],
)
def test_changed_finite_evidence_aborts_without_replacing_existing_outputs(tmp_path, field, value):
    """A changed known Sugar claim requires review rather than automatic reuse or unsafe fallback."""
    transform, _, _, _ = _run(tmp_path)
    before = (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    records = _records()
    records[0][field] = value
    source = tmp_path / "changed.csv"
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    with pytest.raises(ValueError, match="Reviewed unresolved Bergey sugar evidence changed"):
        transform.run(data_file=source, show_status=False)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())


@pytest.mark.parametrize("target", [None, "CHEBI:17992", "NCIT:C16883", "kgmicrobe.compound:sugar"])
def test_changed_mapping_cannot_silently_reinterpret_the_reviewed_disposition(tmp_path, target):
    """The historical target anchor is explicit, not guessed from current output."""
    with pytest.raises(ValueError, match="Reviewed unresolved Bergey sugar mapping evidence changed"):
        _run(tmp_path, lookup=ChemicalLookup(target))


def test_missing_whole_bergey_group_cannot_skip_the_finite_guard(tmp_path):
    """Admission precedes even the source-group emptiness filter, not only sugar token handling."""
    with pytest.raises(ValueError, match="Reviewed unresolved Bergey sugar evidence changed"):
        _run(tmp_path, records=[{"LPSN_ID": "773071"}])


def test_infrastructure_failure_is_not_an_unresolved_context_disposition(tmp_path):
    """The finite preservation rule cannot swallow a failed mapping authority."""

    class BrokenLookup(ChemicalLookup):
        """Model an infrastructure error instead of an ordinary missing match."""

        def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
            """Fail before any identity is accepted."""
            raise OSError("mapping input unavailable")

    with pytest.raises(OSError, match="mapping input unavailable"):
        _run(tmp_path, lookup=BrokenLookup())


def test_other_records_fields_and_native_sugar_resolution_are_unchanged(tmp_path):
    """Keep other Sugar uses outside the finite record-field disposition."""
    source = _records()[0]
    other = {**source, "LPSN_ID": "999999"}
    known = {
        **source,
        "Bergey_Major_end_products": "sugar",
        "Literature_Substrates_for_end_products": "sugar",
        "Literature_Citation": "PMID:12345",
    }
    transform, _, edges, _ = _run(tmp_path, [known, other, _records()[2]])
    selected = [
        row
        for row in edges
        if row["value"] == "sugar" and (row["subject"] == "lpsn:999999" or row["source_column"] != COLUMN)
    ]
    assert len(selected) == 3
    assert all(row["object"] == OLD and row["original_object"] == "" for row in selected)
    node_stream = io.StringIO()
    assert transform._resolve_chemical_curie("Sugar", csv.writer(node_stream), "ingredient") == OLD
    assert transform._resolve_chemical_curie("sugar", csv.writer(node_stream), "native_label") == OLD
    assert node_stream.getvalue() == ""
    assert next(row for row in _substrates(edges) if row["value"] == "mucin")["object"] == "NCIT:C16883"


def test_real_loader_retains_supported_ingredient_and_native_sugar(tmp_path):
    """Existing MIM:Sugar and native-name rows still resolve to their unchanged external identity."""
    from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

    controls = _fixture()["sugar_mapping_controls"]
    mapping = tmp_path / "sugar.sssom.tsv"
    with mapping.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(controls[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(controls)
    lookup = ChemicalMappingLoader(mapping)
    assert lookup.find_chebi_by_xref("MIM:Sugar") == OLD
    assert lookup.find_chebi_by_name("Sugar") == lookup.find_chebi_by_name("sugar") == OLD
    transform = MicrobeDecoderTransform(tmp_path, tmp_path, chemical_loader=lookup)
    nodes = io.StringIO()
    assert transform._resolve_chemical_curie("Sugar", csv.writer(nodes), "ingredient") == OLD
    assert nodes.getvalue() == ""


def test_actual_kgx_archive_retains_scoped_identity_and_full_evidence(tmp_path, monkeypatch):
    """The actual public miniature merge must retain both observations and their original target."""
    from kg_microbe.merge_utils.merge_kg import merge
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    transform, _, before, _ = _run(tmp_path)
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
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "scoped"}},
                },
            }
        )
    )
    merge(str(config), processes=1)
    with tarfile.open(tmp_path / "scoped.tar.gz") as archive:
        with archive.extractfile("scoped_edges.tsv") as stream:
            after = list(csv.DictReader(io.TextIOWrapper(stream), delimiter="\t", quoting=csv.QUOTE_NONE))
        with archive.extractfile("scoped_nodes.tsv") as stream:
            nodes = list(csv.DictReader(io.TextIOWrapper(stream), delimiter="\t", quoting=csv.QUOTE_NONE))
    expected = _substrates(before)
    observed = _substrates(after)
    assert len(observed) == len(expected) == 3
    for old in expected:
        matches = [row for row in observed if row["subject"] == old["subject"]]
        assert len(matches) == 1
        assert all(matches[0][field] == old[field] for field in old)
    node_map = {row["id"]: row for row in nodes}
    for edge in expected:
        if edge["original_object"] == OLD:
            assert node_map[edge["object"]]["name"] == "sugar"
            assert node_map[edge["object"]]["category"] == "biolink:ChemicalEntity"
            assert not node_map[edge["object"]].get("xref")
            assert not node_map[edge["object"]].get("same_as")
