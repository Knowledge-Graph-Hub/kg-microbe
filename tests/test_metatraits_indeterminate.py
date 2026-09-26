"""Keep explicitly indeterminate source summaries out of categorical assertions."""

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.constants import AUTOMATED_AGENT, CHEMICAL_CATEGORY, OBSERVATION
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform

FIXTURE = Path(__file__).parent / "resources/metatraits_indeterminate.json"
SENTINEL = "No robust majority"
POSITIVE = "METPO:2000017"
NEGATIVE = "METPO:2000044"
TAXON = "NCBITaxon:1462"
ROUTES = ["manual", "special", "tier1", "fermentation", "phenotype"]


def _record():
    """Load the immutable observed summary without changing its JSON types."""
    return json.loads(FIXTURE.read_text())


def _rows(path):
    """Read a tiny TSV test output."""
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _diagnostics(path):
    """Read all tiny diagnostic records, including duplicates."""
    return [json.loads(line) for line in path.read_text().splitlines()]


def _transform(tmp_path, monkeypatch, transform_type, route="manual"):
    """Initialize real serial/worker methods with bounded offline mapping inputs."""
    loader = SimpleNamespace(
        find_chebi_by_name=lambda name, **kwargs: "CHEBI:17234" if name == "d-glucose" else None,
        get_canonical_name=lambda curie: "D-glucose",
        get_node_enrichment=lambda curie: {"xref": "", "synonym": ""},
    )
    monkeypatch.setattr(metatraits, "ChemicalMappingLoader", lambda: loader)
    transform = transform_type.__new__(transform_type)
    name = _record()["tax_name"]
    shared = {
        "input_base_dir": str(tmp_path),
        "output_dir": str(tmp_path / "out"),
        "knowledge_source": (
            "infores:gtdb-metatraits" if transform_type is MetaTraitsGTDBTransform else "infores:metatraits"
        ),
        "ncbitaxon_name_to_id": {name.lower(): TAXON},
        "gtdb_to_ncbi": {name: {TAXON: 1}},
        "metpo_pattern_to_predicate": {
            "reduction": {"positive": POSITIVE, "negative": NEGATIVE},
            "fermentation": {"positive": "METPO:2000011", "negative": "METPO:2000037"},
        },
    }
    for key in [
        "trait_mapping",
        "microbial_mappings",
        "metpo_mappings",
        "metpo_binned_ranges",
        "metpo_label_to_class",
        "metpo_synonym_to_class",
        "special_chemical_mappings",
        "ec_to_go",
        "enzyme_name_to_go",
        "ncbi_to_gtdb_mappings",
    ]:
        shared[key] = {}
    transform._init_from_shared_data(shared)
    transform.output_dir.mkdir(parents=True)
    transform.output_node_file = transform.output_dir / "nodes.tsv"
    transform.output_edge_file = transform.output_dir / "edges.tsv"
    transform.unmapped_traits_file = transform.output_dir / "unmapped_traits.tsv"
    transform.measurement_traits_file = transform.output_dir / "measurement_traits.tsv"
    transform.unresolved_taxa_file = transform.output_dir / "unresolved_taxa.tsv"
    trait = _record()["summaries"][0]["name"]
    if route == "manual":
        transform.microbial_mappings[trait] = {
            "object_id": "CHEBI:29125",
            "object_label": "arsenate(3-)",
            "object_category": CHEMICAL_CATEGORY,
            "biolink_predicate": POSITIVE,
        }
    elif route == "special":
        # Exercise the real curated special reader and chemical resolver.
        transform.special_chemical_mappings = transform._load_special_chemical_mappings()
    elif route in {"tier1", "phenotype"}:
        trait = "gram positive"
        mapping = {
            "curie": "METPO:1000698",
            "name": "gram positive",
            "category": "biolink:PhenotypicQuality",
            "predicate": "biolink:has_phenotype",
        }
        target = transform.trait_mapping if route == "tier1" else transform.metpo_label_to_class
        target[trait] = mapping
    elif route == "fermentation":
        trait = "fermentation: D-glucose"
    return transform, trait


def _run(transform, mode, input_paths, tmp_path):
    """Use the real serial path or worker path followed by its production merger."""
    if mode == "serial":
        transform._run_sequential(input_paths, show_status=False)
    else:
        temp = tmp_path / "workers"
        temp.mkdir()
        shared = transform._get_shared_init_data()
        results = [metatraits._process_file_worker((path, temp, shared, False)) for path in input_paths]
        transform._merge_worker_outputs(results, temp)
    return _rows(transform.output_edge_file)


def _input(tmp_path, record, name="input.jsonl"):
    """Write an isolated tiny fixture-derived input, never repository data."""
    path = tmp_path / name
    path.write_text(json.dumps(record) + "\n")
    return path


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
@pytest.mark.parametrize("route", ROUTES)
def test_every_regular_route_defers_exact_sentinel(transform_type, mode, route, tmp_path, monkeypatch):
    """No dispatch tier may manufacture a node or either polarity from uncertainty."""
    transform, trait = _transform(tmp_path, monkeypatch, transform_type, route)
    record = _record()
    record["summaries"][0]["name"] = trait
    # Identical summaries are separate diagnostic observations, not deduplicated.
    record["summaries"] *= 2
    assert _run(transform, mode, [_input(tmp_path, record)], tmp_path) == []
    assert _rows(transform.output_node_file) == []
    expected = {
        "reason": SENTINEL,
        "primary_knowledge_source": transform.knowledge_source,
        "tax_name": record["tax_name"],
        "resolved_taxon": TAXON,
        "summary": record["summaries"][0],
    }
    assert _diagnostics(transform.indeterminate_traits_file) == [expected, expected]
    assert _rows(transform.unmapped_traits_file) == []
    assert _rows(transform.measurement_traits_file) == []


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
@pytest.mark.parametrize("route", ROUTES)
def test_explicit_polarities_empty_and_categorical_controls_unchanged(
    transform_type, mode, route, tmp_path, monkeypatch
):
    """The narrow fix does not rewrite true/false percentages or legacy other labels."""
    transform, trait = _transform(tmp_path, monkeypatch, transform_type, route)
    record = _record()
    record["summaries"] = [
        {"name": trait, "majority_label": label, "percentages": {"true": percentage}}
        for label, percentage in [("true: (100%)", 100.0), ("false: (100%)", 0.0), ("", 25.0), ("other", 30.0)]
    ]
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    if route in {"manual", "special"}:
        expected = [(POSITIVE, "100.0"), (NEGATIVE, "0.0"), (POSITIVE, "25.0"), (NEGATIVE, "30.0")]
    elif route == "fermentation":
        expected = [("METPO:2000011", "100.0")] + [("METPO:2000037", pct) for pct in ["0.0", "25.0", "30.0"]]
    else:
        expected = [("biolink:has_phenotype", pct) for pct in ["100.0", "0.0", "25.0", "30.0"]]
    assert sorted((row["predicate"], row["has_percentage"]) for row in edges) == sorted(expected)
    assert {row["subject"] for row in edges} == {TAXON}
    assert {row["primary_knowledge_source"] for row in edges} == {transform.knowledge_source}
    assert {row["knowledge_level"] for row in edges} == {OBSERVATION}
    assert {row["agent_type"] for row in edges} == {AUTOMATED_AGENT}
    assert transform.indeterminate_traits_file.read_bytes() == b""


@pytest.mark.parametrize("paired", [True, False])
def test_defensive_helper_distinguishes_unknown_from_unpaired_false(paired):
    """Only the exact enum is newly deferred, even when a negative exists."""
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    transform.metpo_pattern_to_predicate = {
        "reduction": {"positive": POSITIVE, "negative": NEGATIVE if paired else None}
    }
    mapping = {"predicate": POSITIVE}
    assert transform._apply_majority_label_to_predicate(mapping, SENTINEL) is None
    assert transform._apply_majority_label_to_predicate(mapping, "true: (80%)") == POSITIVE
    assert transform._apply_majority_label_to_predicate(mapping, "") == POSITIVE
    for label in ["false: (100%)", "no robust majority", " No robust majority", "No robust majority ", "other"]:
        assert transform._apply_majority_label_to_predicate(mapping, label) == (NEGATIVE if paired else None)


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
def test_mixed_same_target_preserves_independent_true_and_false(transform_type, mode, tmp_path, monkeypatch):
    """Defer a summary, not an SPO: independent assertions with equal percentages survive."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    record = _record()
    observed = deepcopy(record["summaries"][0])
    # Synthetic independent polarity controls deliberately share target and 80%.
    record["summaries"] += [
        {**deepcopy(observed), "majority_label": label} for label in ["true: (80%)", "false: (20%)"]
    ]
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    assert sorted((r["predicate"], r["object"], r["has_percentage"]) for r in edges) == [
        (POSITIVE, "CHEBI:29125", "80.0"),
        (NEGATIVE, "CHEBI:29125", "80.0"),
    ]
    diagnostics = _diagnostics(transform.indeterminate_traits_file)
    assert len(diagnostics) == 1
    assert diagnostics[0]["summary"] == observed
    assert {row["id"] for row in _rows(transform.output_node_file)} == {TAXON, "CHEBI:29125"}


def test_diagnostic_preserves_typed_full_summary_and_does_not_mutate_input(tmp_path, monkeypatch):
    """Nulls, booleans, nested context, zero and repeats survive JSON diagnostics."""
    transform, _ = _transform(tmp_path, monkeypatch, MetaTraitsTransform)
    summary = _record()["summaries"][0]
    summary.update({"context": {"null": None, "enabled": False, "values": [0, 0.0, "0", "µM"]}})
    summary["percentages"] = {"true": 0.0, "false": None}
    original = deepcopy(summary)
    stream = io.StringIO()
    assert transform._defer_indeterminate_trait(stream, summary, "original taxon", TAXON)
    emitted = json.loads(stream.getvalue())["summary"]
    assert json.dumps(emitted, sort_keys=True) == json.dumps(original, sort_keys=True)
    assert summary == original
    for label in ["no robust majority", " No robust majority", "No robust majority ", None, ""]:
        altered = {**summary, "majority_label": label}
        before = stream.getvalue()
        assert not transform._defer_indeterminate_trait(stream, altered, "original taxon", TAXON)
        assert stream.getvalue() == before


def test_nonfinite_summary_aborts_before_writing_partial_diagnostic(tmp_path, monkeypatch):
    """A rejected summary cannot corrupt previously complete JSONL records."""
    transform, _ = _transform(tmp_path, monkeypatch, MetaTraitsTransform)
    summary = _record()["summaries"][0]
    stream = io.StringIO()
    assert transform._defer_indeterminate_trait(stream, summary, "original taxon", TAXON)
    before = stream.getvalue()
    for number in [float("nan"), float("inf"), -float("inf")]:
        invalid = {**summary, "context": {"nested": [number]}}
        with pytest.raises(ValueError, match="Out of range float values"):
            transform._defer_indeterminate_trait(stream, invalid, "original taxon", TAXON)
        assert stream.getvalue() == before
    assert transform._defer_indeterminate_trait(stream, summary, "original taxon", TAXON)
    assert len([json.loads(line) for line in stream.getvalue().splitlines()]) == 2


@pytest.mark.parametrize("transform_type", [MetaTraitsTransform, MetaTraitsGTDBTransform])
@pytest.mark.parametrize("mode", ["serial", "worker"])
def test_measurement_and_numeric_extraction_are_unchanged(transform_type, mode, tmp_path, monkeypatch):
    """Indeterminate measurements stay separate; numeric phenotyping remains live."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    record = _record()
    record["summaries"] = [
        {"name": "genome size", "majority_label": SENTINEL, "num_observations": 0},
        {"name": "temperature growth", "majority_label": "Median: 37.0 Celsius"},
    ]
    transform.metpo_binned_ranges["temperature"] = [
        {"curie": "METPO:1000615", "label": "mesophilic", "range_min": 20.0, "range_max": 45.0}
    ]
    edges = _run(transform, mode, [_input(tmp_path, record)], tmp_path)
    assert transform.indeterminate_traits_file.read_bytes() == b""
    measurements = _rows(transform.measurement_traits_file)
    assert measurements[0] == {
        "trait_name": "genome size",
        "tax_name": record["tax_name"],
        "majority_label": SENTINEL,
        "num_observations": "0",
    }
    if mode == "worker":
        assert len(edges) == 1
        assert (edges[0]["value"], edges[0]["unit"], edges[0]["has_percentage"]) == ("37.0", "Celsius", "100.0")
        assert len(measurements) == 1
    else:
        # Sequential numeric treatment is an existing separate route, unchanged here.
        assert edges == []
        assert len(measurements) == 2


def test_worker_concatenation_matches_serial_exactly_and_keeps_duplicates(tmp_path, monkeypatch):
    """Two worker files concatenate once in input order, with no header or lost repeats."""
    record = _record()
    paths = [_input(tmp_path, record, "first.jsonl"), _input(tmp_path, record, "second.jsonl")]
    serial, _ = _transform(tmp_path / "serial", monkeypatch, MetaTraitsTransform)
    _run(serial, "serial", paths, tmp_path)
    worker, _ = _transform(tmp_path / "worker", monkeypatch, MetaTraitsTransform)
    _run(worker, "worker", paths, tmp_path)
    assert worker.indeterminate_traits_file.read_bytes() == serial.indeterminate_traits_file.read_bytes()
    assert len(_diagnostics(worker.indeterminate_traits_file)) == 2


def test_missing_worker_diagnostic_aborts_merge(tmp_path, monkeypatch):
    """Do not silently publish incomplete diagnostic evidence when a worker file is lost."""
    transform, _ = _transform(tmp_path, monkeypatch, MetaTraitsTransform)
    temp = tmp_path / "workers"
    temp.mkdir()
    result = transform._process_single_file(_input(tmp_path, _record()), temp, show_status=False)
    result["indeterminate_traits_file"].unlink()
    with pytest.raises(FileNotFoundError):
        transform._merge_worker_outputs([result], temp)
