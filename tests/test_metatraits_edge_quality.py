"""Source-record polarity, categorical values, and conservative synonym collisions (#1842)."""

import json
from copy import deepcopy

import pytest

from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from tests.test_metatraits_indeterminate import NEGATIVE, POSITIVE, _input, _record, _run, _transform

TYPES = [MetaTraitsTransform, MetaTraitsGTDBTransform]
MODES = ["serial", "worker"]


def _mapping(curie, name, predicate="biolink:has_phenotype"):
    """Build an explicit finite synthetic ontology entry."""
    return {"curie": curie, "name": name, "category": "biolink:PhenotypicQuality", "predicate": predicate}


def _summary(name, label="true: (80%)", percentages=None, **context):
    """Keep source support and additional evidence explicit."""
    return {
        "name": name,
        "majority_label": label,
        "percentages": {"true": 80.0} if percentages is None else percentages,
        **context,
    }


def _run_summaries(transform, mode, tmp_path, summaries):
    """Exercise a real serial or worker TSV emission path."""
    record = _record()
    record["summaries"] = summaries
    return _run(transform, mode, [_input(tmp_path, record)], tmp_path)


@pytest.mark.parametrize("transform_type", TYPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("route", ["tier1", "trophic", "phenotype"])
@pytest.mark.parametrize("paired", [True, False])
def test_all_previous_bypasses_apply_polarity(tmp_path, monkeypatch, transform_type, mode, route, paired):
    """False summaries use a declared negative predicate or produce no positive assertion."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    predicate = POSITIVE if paired else "biolink:has_phenotype"
    mapping = _mapping("METPO:1000602", "aerobic", predicate)
    transform.metpo_pattern_to_predicate["has phenotype"] = {
        "positive": predicate,
        "negative": NEGATIVE if paired else None,
    }
    name = "growth: aerobic" if route == "trophic" else "aerobic"
    if route == "tier1":
        transform.trait_mapping[name] = mapping
    else:
        transform.metpo_label_to_class["aerobic"] = mapping
    rows = _run_summaries(
        transform,
        mode,
        tmp_path,
        [
            _summary(name, "true: (80%)"),
            _summary(name, "false: (100%)", {"true": 0.0, "false": 100.0}),
            _summary(name, "No robust majority", {"true": 50.0, "false": 50.0}),
        ],
    )
    expected = [(predicate, "80.0")]
    if paired:
        expected.append((NEGATIVE, "0.0"))
    assert sorted((row["predicate"], row["has_percentage"]) for row in rows) == sorted(expected)
    assert len(transform.indeterminate_traits_file.read_text().splitlines()) == 1


@pytest.mark.parametrize("transform_type", TYPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "name,winner,target",
    [
        ("cell shape", "rod-shaped", "METPO:1000681"),
        ("oxygen preference", "anaerobic", "METPO:1000603"),
        ("temperature preference", "mesophilic", "METPO:1000615"),
        ("biosafety level", "1", "METPO:1001102"),
        ("biosafety level", "level 1", "METPO:1001102"),
        ("pH preference", "acidophilic", "METPO:1003003"),
    ],
)
def test_categorical_headers_emit_winner_and_its_support(
    tmp_path, monkeypatch, transform_type, mode, name, winner, target
):
    """The winning ontology value carries its category percentage, never a bare header."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    transform.trait_mapping[name.lower()] = _mapping("METPO:parent", name)
    key = "biosafety level 1" if name == "biosafety level" else winner
    transform.metpo_synonym_to_class[key] = _mapping(target, key)
    transform.metpo_synonym_to_class["1"] = _mapping("METPO:unrelated", "unrelated numeric synonym")
    rows = _run_summaries(
        transform,
        mode,
        tmp_path,
        [
            _summary(name, f"{winner}: (75%)", {winner: 75.0, "other": 25.0}),
            _summary(name, "unresolved: (90%)", {"unresolved": 90.0}),
            _summary(name, f"{name}: (100%)", {name: 100.0}),
            _summary(name, f"{winner}: (75%)", {}),
        ],
    )
    assert [(row["object"], row["has_percentage"], row["value"], row["unit"]) for row in rows] == [
        (target, "75.0", "", "")
    ]


@pytest.mark.parametrize("transform_type", TYPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "name,value,unit", [("GC content", 65.2, "%"), ("cell width", 0.5, "µm"), ("cell length", 2.0, "um")]
)
def test_continuous_headers_retain_native_median_and_unit(
    tmp_path, monkeypatch, transform_type, mode, name, value, unit
):
    """Numeric zero is valid; absent and nonfinite medians cannot emit empty parent edges."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    transform.trait_mapping[name.lower()] = _mapping("METPO:measurement", name, "biolink:has_attribute")
    summaries = [_summary(name, f"Median: {number} {unit}", {}) for number in [value, 0.0]] + [
        _summary(name, label, {})
        for label in ["", "Median: unknown", "Median: NaN", "Median: 1e999 %", "Median: 1.2.3 µm"]
    ]
    rows = _run_summaries(transform, mode, tmp_path, summaries)
    assert sorted((float(row["value"]), row["unit"], row["has_percentage"]) for row in rows) == [
        (0.0, unit, ""),
        (value, unit, ""),
    ]
    assert {row["object"] for row in rows} == {"METPO:measurement"}


@pytest.mark.parametrize("transform_type", TYPES)
@pytest.mark.parametrize("mode", MODES)
def test_record_synonyms_keep_max_support_but_distinct_evidence(tmp_path, monkeypatch, transform_type, mode):
    """Only equal-context synonyms merge; independent repeated names and evidence remain."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    for name in ["aerobic", "aerobe"]:
        transform.trait_mapping[name] = _mapping("METPO:1000602", "aerobic")
    summaries = [
        _summary("aerobic", percentages={"true": 80.0}, num_observations=10),
        _summary("aerobe", percentages={"true": 90.0}, num_observations=10),
        _summary("aerobic", percentages={"true": 70.0}, num_observations=10),
        _summary("aerobe", percentages={"true": 60.0}, num_observations=20),
        _summary("aerobe", percentages={"true": 50.0}, publications=["doi:test"]),
    ]
    before = deepcopy(summaries)
    rows = _run_summaries(transform, mode, tmp_path, summaries)
    assert sorted(float(row["has_percentage"]) for row in rows) == [50.0, 60.0, 70.0, 90.0]
    assert summaries == before


@pytest.mark.parametrize("mode", MODES)
def test_distinct_gtdb_records_sharing_ncbi_subject_do_not_pool_support(tmp_path, monkeypatch, mode):
    """The maximum is local to a source record, not the shared NCBI subject or worker."""
    transform, _ = _transform(tmp_path, monkeypatch, MetaTraitsGTDBTransform)
    transform.trait_mapping["aerobic"] = _mapping("METPO:1000602", "aerobic")
    first = _record()
    second = deepcopy(first)
    second["tax_name"] = "Separate species"
    transform.gtdb_to_ncbi[second["tax_name"]] = {"NCBITaxon:1462": 1}
    for record, percentage in [(first, 60.0), (second, 90.0)]:
        record["summaries"] = [_summary("aerobic", percentages={"true": percentage})]
    path = tmp_path / "two-records.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in [first, second]))
    rows = _run(transform, mode, [path], tmp_path)
    assert {row["subject"] for row in rows} == {"NCBITaxon:1462"}
    assert sorted(float(row["has_percentage"]) for row in rows) == [60.0, 90.0]


def test_distinct_quantitative_contexts_are_not_collapsed():
    """Equal SPOs with different literal values, units or relations are separate observations."""
    rows = []

    class Writer:
        def write_row(self, row):
            rows.append(row)

    base = [
        "NCBITaxon:1",
        "biolink:has_attribute",
        "METPO:x",
        "RO:x",
        "infores:metatraits",
        "observation",
        "automated_agent",
        80.0,
        1.0,
        "um",
    ]
    observations = [(base[:], _summary("first"))]
    for index, value in [(3, "RO:other"), (8, 2.0), (9, "mm")]:
        row = base[:]
        row[index] = value
        observations.append((row, _summary("synonym")))
    MetaTraitsTransform._write_record_trait_edges(Writer(), observations)
    assert len(rows) == 4


@pytest.mark.parametrize("transform_type", TYPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("predicate", ["biolink:has_phenotype", "biolink:capable_of", "biolink:has_attribute"])
def test_zero_or_missing_positive_support_cannot_emit_empty_assertion(
    tmp_path, monkeypatch, transform_type, mode, predicate
):
    """Unknown support does not become a positive empty class assertion on any emission path."""
    transform, _ = _transform(tmp_path, monkeypatch, transform_type)
    transform.trait_mapping["trait"] = _mapping("METPO:trait", "trait", predicate)
    rows = _run_summaries(
        transform,
        mode,
        tmp_path,
        [
            _summary("trait", "true: (100%)", {"true": 0.0}),
            _summary("trait", "", {}),
            _summary("trait", "true: (80%)", {"true": 80.0}),
        ],
    )
    assert [(row["predicate"], row["has_percentage"]) for row in rows] == [(predicate, "80.0")]
