"""Retain explicit BacDive name/ID conflicts without guessing mixture/member identity (#1185)."""

import csv
import io
import json
import tarfile
from copy import deepcopy
from multiprocessing.pool import ThreadPool
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import (
    ANTIBIOTIC_RESISTANCE,
    METABOLITE_UTILIZATION,
    PHYSIOLOGY_AND_METABOLISM,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.biolink_model import prepare_kgx
from kg_microbe.utils.source_finalization import graph_rows
from tests.test_bacdive_run_references import _run_fixture

FIXTURE = Path(__file__).parent / "resources/bacdive_polymyxin_conflicts/records.json"
LOCAL = "kgmicrobe.compound:bacdive_conflict_"
RESISTANT = "biolink:associated_with_resistance_to"
SENSITIVE = "biolink:associated_with_sensitivity_to"
NEGATIVE_ASSIMILATION = "METPO:2000027"


def _records():
    """Read exact projected raw records without mutating the immutable fixture."""
    return json.loads(FIXTURE.read_text())


def _run(tmp_path, monkeypatch, records, loader=None):
    """Exercise actual run/emission; only unrelated ontology setup uses the existing tiny fixture."""
    original = BacDiveTransform._prepare_assay_outputs

    def prepare(transform):
        """Keep the fixture setup and inject the reviewed chemical lookup and sign map."""
        original(transform)
        transform.chemical_loader = loader
        transform.metpo_metabolite_utilization_mappings["assimilation"] = {
            "+": {"curie": "METPO:2000002"},
            "-": {"curie": NEGATIVE_ASSIMILATION},
        }

    monkeypatch.setattr(BacDiveTransform, "_prepare_assay_outputs", prepare)
    edges, nodes = _run_fixture(tmp_path, monkeypatch, records)
    diagnostic = tmp_path / "transformed/bacdive" / module.CHEMICAL_IDENTITY_CONFLICTS_FILE
    return edges, nodes, [json.loads(line) for line in diagnostic.read_text().splitlines()]


def _local_edges(edges):
    """Select source-local material observations without conflating other BacDive edges."""
    return [row for row in edges if row["object"].startswith(LOCAL)]


@pytest.mark.parametrize("antibiotic_list", [False, True])
@pytest.mark.parametrize("utilization_list", [False, True])
@pytest.mark.parametrize("input_dict", [False, True])
def test_actual_run_preserves_both_raw_routes_and_own_citations(
    tmp_path, monkeypatch, antibiotic_list, utilization_list, input_dict
):
    """Both raw shapes retain source sign, original ID, own reference and complete typed context."""
    records = _records()
    for record, route, as_list in zip(
        records, [ANTIBIOTIC_RESISTANCE, METABOLITE_UTILIZATION], [antibiotic_list, utilization_list], strict=True
    ):
        if not as_list:
            record[PHYSIOLOGY_AND_METABOLISM][route] = record[PHYSIOLOGY_AND_METABOLISM][route][0]
        record["Reference"].append({"@id": 999, "doi/url": "10.1234/unrelated"})
    before = deepcopy(records)
    inputs = {str(index): record for index, record in enumerate(records)} if input_dict else records
    edges, nodes, diagnostics = _run(tmp_path, monkeypatch, inputs)
    local = _local_edges(edges)
    assert records == before
    assert len(local) == len(diagnostics) == 2
    assert len({row["object"] for row in local}) == 2
    assert {row["predicate"] for row in local} == {RESISTANT, NEGATIVE_ASSIMILATION}
    assert not any(row["object"] in {"CHEBI:8309", "NCIT:C61894"} for row in edges)
    by_target = {row["object"]: row for row in local}
    by_node = {row["id"]: row for row in nodes}
    for index, (record, route, as_list) in enumerate(
        zip(records, [ANTIBIOTIC_RESISTANCE, METABOLITE_UTILIZATION], [antibiotic_list, utilization_list], strict=True),
        1,
    ):
        diagnostic = diagnostics[index - 1]
        block = record[PHYSIOLOGY_AND_METABOLISM][route]
        item = block[0] if as_list else block
        assert diagnostic["source_record"] == item
        assert json.dumps(diagnostic["source_record"], sort_keys=True) == json.dumps(item, sort_keys=True)
        assert diagnostic["source_path"] == [PHYSIOLOGY_AND_METABOLISM, route] + ([0] if as_list else [])
        assert diagnostic["record_id"] == record["General"]["BacDive-ID"]
        assert diagnostic["record_position"] == index
        assert diagnostic["emitted"] is True
        edge = by_target[diagnostic["local_id"]]
        assert edge["original_object"] == diagnostic["original_object"] == "CHEBI:8309"
        assert edge["predicate"] == diagnostic["predicate"]
        assert edge["primary_knowledge_source"] == diagnostic["primary_knowledge_source"] == "infores:bacdive"
        assert (edge["knowledge_level"], edge["agent_type"]) == ("observation", "manual_agent")
        own_doi = "doi:" + record["Reference"][0]["doi/url"]
        assert diagnostic["item_publications"] == own_doi
        assert set(edge["publications"].split("|")) == {
            own_doi,
            f"https://bacdive.dsmz.de/strain/{record['General']['BacDive-ID']}",
        }
        node = by_node[diagnostic["local_id"]]
        assert node["name"] == "polymyxin b"
        assert node["category"] == "biolink:ChemicalEntity"
        assert node["provided_by"] == "infores:bacdive"
        assert "External identity is unresolved" in node["description"]
        assert not any(node.get(column) for column in ("xref", "synonym", "same_as"))


def test_duplicate_items_record_occurrences_and_original_gap_remain_distinct(tmp_path, monkeypatch):
    """Raw position is identity context, even for byte-identical repeats and reused record IDs."""
    records = _records()
    antibiotic = records[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    # Synthetic third observation differs in concentration, but has the same sign and source ID.
    records[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE] = [
        antibiotic,
        deepcopy(antibiotic),
        {**antibiotic, "resistance conc.": "100 Unit"},
    ]
    utilization = records[1][PHYSIOLOGY_AND_METABOLISM][METABOLITE_UTILIZATION][0]
    records[1][PHYSIOLOGY_AND_METABOLISM][METABOLITE_UTILIZATION] = [None] * 15 + [utilization]
    records += [deepcopy(records[0])]
    edges, _, diagnostics = _run(tmp_path, monkeypatch, records)
    assert len(_local_edges(edges)) == len(diagnostics) == 7
    assert len({row["local_id"] for row in diagnostics}) == 7
    assert diagnostics[3]["source_path"][-1] == 15
    assert diagnostics[3]["source_record"] == utilization
    assert diagnostics[0]["source_record"] == diagnostics[1]["source_record"]
    assert diagnostics[0]["record_id"] == diagnostics[4]["record_id"] == 76
    assert diagnostics[0]["record_position"] == 1
    assert diagnostics[4]["record_position"] == 3


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize("signs", [{}, {"is resistant": "no"}, {"is sensitive": "no"}, {"is resistant": "unknown"}])
def test_nonqualifying_antibiotic_items_are_diagnosed_without_new_sign(tmp_path, monkeypatch, as_list, signs):
    """The eighteen observed non-yes raw candidates must not gain invented biological polarity."""
    record = _records()[0]
    item = record[PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    item.pop("is resistant")
    item.update(signs)
    record[PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE] = [item] if as_list else item
    edges, nodes, diagnostics = _run(tmp_path, monkeypatch, [record])
    assert len(diagnostics) == 1
    assert diagnostics[0]["emitted"] is False
    assert diagnostics[0]["predicate"] is None
    assert diagnostics[0]["source_record"] == item
    assert not _local_edges(edges)
    assert not any(row["id"].startswith(LOCAL) for row in nodes)


@pytest.mark.parametrize(
    "signs,predicate",
    [
        ({"is sensitive": "yes"}, SENSITIVE),
        ({"is resistant": "yes", "is sensitive": "no"}, RESISTANT),
    ],
)
def test_existing_antibiotic_sign_precedence_is_preserved(tmp_path, monkeypatch, signs, predicate):
    """Only the existing selected observation is emitted; no negation is inferred from other fields."""
    record = _records()[0]
    item = record[PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    item.pop("is resistant")
    item.update(signs)
    edges, _, diagnostics = _run(tmp_path, monkeypatch, [record])
    assert [row["predicate"] for row in _local_edges(edges)] == [predicate]
    assert diagnostics[0]["source_record"] == item


@pytest.mark.parametrize("name,identifier", [("polymyxin B1", 8309), ("polymyxin B sulfate", 8310), ("water", 15377)])
@pytest.mark.parametrize("route", [ANTIBIOTIC_RESISTANCE, METABOLITE_UTILIZATION])
def test_explicit_authority_controls_are_not_remapped(tmp_path, monkeypatch, name, identifier, route):
    """The finite conflicting pair is not a blanket ban on supplied chemical IDs."""
    record = _records()[0 if route == ANTIBIOTIC_RESISTANCE else 1]
    item = record[PHYSIOLOGY_AND_METABOLISM][route][0]
    item["metabolite"] = name
    item["ChEBI" if route == ANTIBIOTIC_RESISTANCE else "Chebi-ID"] = identifier
    edges, _, diagnostics = _run(tmp_path, monkeypatch, [record])
    assert diagnostics == []
    assert not _local_edges(edges)
    claims = [row for row in edges if row["object"] == f"CHEBI:{identifier}"]
    assert len(claims) == 1
    assert claims[0]["original_object"] == ""


def test_id_without_optional_display_name_remains_explicit(tmp_path, monkeypatch):
    """The source ID alone is not newly rejected or silently redirected to a mixture."""
    record = _records()[1]
    record[PHYSIOLOGY_AND_METABOLISM][METABOLITE_UTILIZATION][0].pop("metabolite")
    edges, _, diagnostics = _run(tmp_path, monkeypatch, [record])
    assert diagnostics == []
    assert any(row["object"] == "CHEBI:8309" for row in edges)


@pytest.mark.parametrize("loader_result", [None, "CHEBI:8309"])
def test_stale_and_missing_unified_lookup_cannot_revive_legacy_false_pair(monkeypatch, loader_result):
    """Both unified and fallback lookup results must obey the existing reviewed scope policy."""
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda name: loader_result)
    monkeypatch.setattr(module, "METABOLITE_MAP", {"CHEBI:8309": "polymyxin b"})
    assert transform._lookup_chebi_by_name("polymyxin b") is None
    transform.chemical_loader = None
    assert transform._lookup_chebi_by_name("polymyxin b") is None
    monkeypatch.setattr(module, "METABOLITE_MAP", {"CHEBI:8309": "polymyxin B1", "CHEBI:8310": "polymyxin B sulfate"})
    assert transform._lookup_chebi_by_name("polymyxin B1") == "CHEBI:8309"
    assert transform._lookup_chebi_by_name("polymyxin B sulfate") == "CHEBI:8310"


def test_name_only_mixture_and_explicit_conflict_remain_separate_in_one_record(tmp_path, monkeypatch):
    """The reviewed name-only mixture route stays intact alongside a conflicting explicit raw ID."""
    record = _records()[0]
    record[PHYSIOLOGY_AND_METABOLISM]["antibiogram"] = {"polymyxin b": "5"}
    enrichment_calls = []

    def enrichment(identifier):
        """Reject enrichment of unresolved local materials and record native lookup calls."""
        enrichment_calls.append(identifier)
        assert not identifier.startswith(LOCAL)
        return {"xref": "", "synonym": ""}

    loader = SimpleNamespace(
        find_chebi_by_name=lambda name: "NCIT:C61894" if name == "polymyxin b" else None,
        get_node_enrichment=enrichment,
    )
    edges, _, diagnostics = _run(tmp_path, monkeypatch, [record], loader)
    mixture = [row for row in edges if row["object"] == "NCIT:C61894"]
    assert len(mixture) == len(_local_edges(edges)) == len(diagnostics) == 1
    assert mixture[0]["predicate"] == RESISTANT
    assert mixture[0]["original_object"] == ""
    assert "doi:" not in mixture[0]["publications"]
    assert enrichment_calls == ["NCIT:C61894"]


@pytest.mark.parametrize("reference", [None, 999, True])
def test_missing_or_invalid_item_pointer_does_not_borrow_record_doi(tmp_path, monkeypatch, reference):
    """A finite conflict carries only its own resolvable citation, never every paper on the strain."""
    record = _records()[0]
    item = record[PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    item["@ref"] = reference
    edges, _, diagnostics = _run(tmp_path, monkeypatch, [record])
    assert diagnostics[0]["item_publications"] == ""
    assert _local_edges(edges)[0]["publications"] == "https://bacdive.dsmz.de/strain/76"


def test_typed_identity_and_jsonl_validation_are_not_lossy():
    """Typed source IDs and complete item JSON are retained; invalid JSON cannot corrupt the next row."""
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.knowledge_source = "infores:bacdive"
    stream = io.StringIO()
    item = _records()[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    targets = []
    for record_id in [76, "76"]:
        context = {"record_id": record_id, "record_position": 1, "diagnostics": stream}
        target, conflict = transform._explicit_chemical_identity(
            item,
            "CHEBI:8309",
            "kgmicrobe.strain:bacdive_76",
            RESISTANT,
            {},
            [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE, 0],
            context,
        )
        assert conflict
        targets.append(target)
    assert len(set(targets)) == 2
    repeated, _ = transform._explicit_chemical_identity(
        item,
        "CHEBI:8309",
        "kgmicrobe.strain:bacdive_76",
        RESISTANT,
        {},
        [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE, 0],
        context,
    )
    assert repeated == targets[-1]
    prior = stream.getvalue()
    with pytest.raises(ValueError, match="Out of range float"):
        transform._explicit_chemical_identity(
            {**item, "nested": [float("nan")]},
            "CHEBI:8309",
            "organism",
            RESISTANT,
            {},
            [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE, 0],
            context,
        )
    assert stream.getvalue() == prior
    assert [type(json.loads(line)["record_id"]) for line in prior.splitlines()] == [int, str, str]


def test_failed_run_does_not_publish_partial_graph_or_conflict_diagnostic(tmp_path, monkeypatch):
    """Nested invalid JSON aborts the actual atomic writer scope without replacing prior artifacts."""
    output = tmp_path / "transformed/bacdive"
    output.mkdir(parents=True)
    prior = {}
    for name in ("nodes.tsv", "edges.tsv", module.CHEMICAL_IDENTITY_CONFLICTS_FILE):
        path = output / name
        path.write_text("previous complete artifact\n")
        prior[path] = path.read_bytes()
    record = _records()[0]
    item = record[PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    item["invalid_nested_evidence"] = [float("nan")]
    with pytest.raises(ValueError, match="Out of range float"):
        _run(tmp_path, monkeypatch, [record])
    assert all(path.read_bytes() == content for path, content in prior.items())
    assert list(output.glob("*.partial")) == []


@pytest.mark.parametrize(
    "context,path",
    [
        (None, [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE]),
        ({"record_id": 76, "record_position": 0}, [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE]),
        ({"record_id": 76, "record_position": 1}, None),
        ({"record_id": 76, "record_position": 1}, [PHYSIOLOGY_AND_METABOLISM, ANTIBIOTIC_RESISTANCE, True]),
    ],
)
def test_conflict_cannot_emit_without_full_occurrence_context(context, path):
    """A direct caller must not create an anonymous or guessed material identity."""
    transform = BacDiveTransform.__new__(BacDiveTransform)
    item = _records()[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    if context is not None:
        context = {**context, "diagnostics": io.StringIO()}
    with pytest.raises(ValueError, match="BacDive chemical identity conflict requires"):
        transform._explicit_chemical_identity(item, "CHEBI:8309", "organism", RESISTANT, {}, path, context)


def test_actual_finalization_and_kgx_archive_retain_materials_and_original_ids(tmp_path, monkeypatch):
    """Distinct repeated materials and their exact source metadata survive the public archive path."""
    records = _records()
    antibiotic = records[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE][0]
    records[0][PHYSIOLOGY_AND_METABOLISM][ANTIBIOTIC_RESISTANCE].append(deepcopy(antibiotic))
    edges, _, diagnostics = _run(tmp_path, monkeypatch, records)
    expected = {row["object"]: row for row in _local_edges(edges)}
    assert len(expected) == 3
    bundle = Transform("bacdive", tmp_path / "raw", tmp_path / "transformed")
    bundle.finalize()
    finalized = {row["object"]: row for row in graph_rows(bundle.output_edge_file) if row["object"] in expected}
    for target, row in finalized.items():
        for field in (
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "original_object",
            "publications",
        ):
            assert row[field] == expected[target][field]
    assert finalized.keys() == expected.keys()
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
                                "filename": [str(bundle.output_node_file), str(bundle.output_edge_file)],
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
        with archive.extractfile("merged_edges.tsv") as handle:
            merged = [
                row for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t") if row["object"] in expected
            ]
    assert len(merged) == len(diagnostics) == 3
    for row in merged:
        source = expected[row["object"]]
        for field in (
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "original_object",
        ):
            assert row[field] == source[field]
        assert set(row["publications"].split("|")) == set(source["publications"].split("|"))
