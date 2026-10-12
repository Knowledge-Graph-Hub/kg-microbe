"""Name-derived MetaTraits hierarchy remains prediction in both actual emitters."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    HAS_PHENOTYPE,
    HAS_PHENOTYPE_PREDICATE,
    INFERRED_SUBCLASS_RELATION,
    NCBI_CATEGORY,
    OBSERVATION,
    PHENOTYPIC_CATEGORY,
    PREDICTION,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb import MetaTraitsGTDBTransform
from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

FIXTURE = Path(__file__).parent / "resources/metatraits_inferred_taxonomy"
NATIVE_SHA = "1881360fb0ae1f28bdbd7d307ed0f7815044b0aa8ad0d769e0ee68f64d431ce7"
EXCERPT_SHA = "edbb3d486545f511de4bac266e4f00bb5d76bd0a35615da25a6db02dba9c801e"
NATIVE_COORDINATES = (
    (4676, "6a74b3b01b2e6bae2d73b108973ab153e770359639515f43f8a4620a1a5609f2"),
    (9556, "7e9a8a371018cb719826257cb660b3dfc167cb5e6d5bdd002f9badf39fcbe9dd"),
    (17218, "9e38fbd0dc49b512e67a6f716cbaf30270ec1daa3c260a9b75b4180d41c6e6ed"),
)
MODES = ("serial", "worker")
TRAIT = "METPO:1000698"
GENUS = "NCBITaxon:561"
SPECIES = "NCBITaxon:562"
HIGHER = "NCBITaxon:543"
STRAIN = "kgmicrobe.strain:Escherichia_coli_TEST"
PROVISIONAL_SPECIES = "kgmicrobe.species:Escherichia_coli"


def _records():
    """Load unmodified complete native records after independent byte checks."""
    payload = (FIXTURE / "native_records.jsonl").read_bytes()
    origin = json.loads((FIXTURE / "origin.json").read_text())
    assert hashlib.sha256(payload).hexdigest() == EXCERPT_SHA
    assert origin["native_input"]["sha256"] == NATIVE_SHA
    assert origin["native_input"]["bytes"] == 915078003
    assert origin["native_records_total"] == 54654
    lines = payload.splitlines(keepends=True)
    assert len(lines) == len(origin["records"]) == len(NATIVE_COORDINATES)
    for index, (line, witness, (coordinate, digest)) in enumerate(
        zip(lines, origin["records"], NATIVE_COORDINATES, strict=True), 1
    ):
        assert witness["fixture_line"] == index
        assert witness["physical_line"] == coordinate
        assert witness["native_line_sha256"] == hashlib.sha256(line).hexdigest() == digest
        assert witness["native_line_bytes"] == len(line)
        record = json.loads(line)
        assert set(record) == {"tax_name", "summaries"}
        assert record["tax_name"] == witness["tax_name"]
        assert len(record["summaries"]) == witness["summary_count"]
    return lines, origin["records"]


def _synthetic(name, majority="true: (100%)"):
    """Create an explicitly synthetic parser-branch control, never native evidence."""
    return {
        "tax_name": name,
        "summaries": [
            {
                "name": "gram positive",
                "is_discrete": True,
                "num_observations": 7,
                "unique_databases": 2,
                "majority_label": majority,
                "percentages": {"true": 75.0, "false": 25.0},
            }
        ],
    }


def _ready(tmp_path, monkeypatch, labels=None, crosswalk=None, transform_type=MetaTraitsTransform):
    """Initialize actual worker state and hermetic lookups without replacing emitters."""
    labels = dict(labels or {})
    loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: None,
        get_canonical_name=lambda curie: None,
        get_node_enrichment=lambda curie: {"xref": "", "synonym": ""},
    )
    monkeypatch.setattr(metatraits, "ChemicalMappingLoader", lambda: loader)
    monkeypatch.setattr(metatraits, "_get_ncbitaxon_adapter", lambda: object())
    monkeypatch.setattr(
        metatraits,
        "search_by_label",
        lambda adapter, label, **kwargs: [labels[label]] if label in labels else [],
    )
    shared = {
        "input_base_dir": str(tmp_path),
        "output_dir": str(tmp_path / "out"),
        "knowledge_source": "infores:gtdb-metatraits"
        if transform_type is MetaTraitsGTDBTransform
        else "infores:metatraits",
        "trait_mapping": {
            "gram positive": {
                "curie": TRAIT,
                "category": PHENOTYPIC_CATEGORY,
                "name": "gram positive",
                "predicate": HAS_PHENOTYPE_PREDICATE,
            }
        },
    }
    for key in (
        "ncbitaxon_name_to_id",
        "microbial_mappings",
        "metpo_mappings",
        "metpo_binned_ranges",
        "metpo_label_to_class",
        "metpo_synonym_to_class",
        "metpo_pattern_to_predicate",
        "special_chemical_mappings",
        "ec_to_go",
        "enzyme_name_to_go",
        "ncbi_to_gtdb_mappings",
    ):
        shared[key] = {}
    shared["ncbi_to_gtdb_mappings"] = dict(crosswalk or {})
    transform = transform_type.__new__(transform_type)
    transform._init_from_shared_data(shared)
    transform.output_dir.mkdir(parents=True)
    for attribute, name in (
        ("output_node_file", "nodes.tsv"),
        ("output_edge_file", "edges.tsv"),
        ("unmapped_traits_file", "unmapped_traits.tsv"),
        ("measurement_traits_file", "measurement_traits.tsv"),
        ("unresolved_taxa_file", "unresolved_taxa.tsv"),
    ):
        setattr(transform, attribute, transform.output_dir / name)
    return transform


def _rows(path):
    """Read complete output rows while treating empty trailing TSV cells as empty strings."""
    with path.open(newline="") as handle:
        return [{key: value or "" for key, value in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def _run(transform, mode, payload):
    """Exercise real serial or reconstructed-worker emission and production deduplication."""
    input_path = transform.input_base_dir / "input.jsonl"
    input_path.write_bytes(payload)
    if mode == "serial":
        transform._run_sequential([input_path], show_status=False)
    else:
        temp = transform.output_dir / "workers"
        temp.mkdir()
        result = metatraits._process_file_worker((input_path, temp, transform._get_shared_init_data(), False))
        transform._merge_worker_outputs([result], temp)
    return _rows(transform.output_edge_file)


def _payload(record):
    """Serialize a labelled synthetic test input, distinct from exact native fixture bytes."""
    return (json.dumps(record) + "\n").encode()


def _edge(transform, subject, object_id, *, hierarchy=True, percentage="75.0"):
    """Build the complete independently expected row, including blank qualifiers."""
    result = dict.fromkeys(transform.edge_header, "")
    result.update(
        subject=subject,
        predicate=SUBCLASS_PREDICATE if hierarchy else HAS_PHENOTYPE_PREDICATE,
        object=object_id,
        relation=INFERRED_SUBCLASS_RELATION if hierarchy else HAS_PHENOTYPE,
        primary_knowledge_source=transform.knowledge_source,
        knowledge_level=PREDICTION if hierarchy else OBSERVATION,
        agent_type=AUTOMATED_AGENT,
    )
    if not hierarchy:
        result["has_percentage"] = percentage
    return result


def _counter(rows):
    """Compare every assertion field and its multiplicity without depending on row order."""
    return Counter(tuple(sorted(row.items())) for row in rows)


CASES = (
    ("genus_strain", "Escherichia sp. TEST", {"Escherichia": GENUS}, [("kgmicrobe.strain:Escherichia_sp_TEST", GENUS)]),
    (
        "higher_strain",
        "Escherichia sp. TEST",
        {"Escherichiaaceae": HIGHER},
        [("kgmicrobe.strain:Escherichia_sp_TEST", HIGHER)],
    ),
    (
        "bacterium_strain",
        "Escherichia bacterium TEST",
        {"Escherichia": GENUS},
        [("kgmicrobe.strain:Escherichia_sp_TEST", GENUS)],
    ),
    ("matched_species", "Escherichia coli TEST", {"Escherichia coli": SPECIES}, [(STRAIN, SPECIES)]),
    (
        "provisional_parent_genus",
        "Escherichia coli TEST",
        {"Escherichia": GENUS},
        [(PROVISIONAL_SPECIES, GENUS), (STRAIN, PROVISIONAL_SPECIES)],
    ),
    (
        "provisional_parent_higher",
        "Escherichia coli TEST",
        {"Escherichiaaceae": HIGHER},
        [(PROVISIONAL_SPECIES, HIGHER), (STRAIN, PROVISIONAL_SPECIES)],
    ),
    ("unresolved_parent_retained", "Escherichia coli TEST", {}, [(STRAIN, PROVISIONAL_SPECIES)]),
    ("species_genus", "Escherichia coli", {"Escherichia": GENUS}, [(PROVISIONAL_SPECIES, GENUS)]),
    ("species_higher", "Escherichia coli", {"Escherichiaaceae": HIGHER}, [(PROVISIONAL_SPECIES, HIGHER)]),
)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case,name,labels,pairs", CASES, ids=[case[0] for case in CASES])
def test_all_name_derived_hierarchy_branches_have_inference_metadata(
    tmp_path, monkeypatch, mode, case, name, labels, pairs
):
    """Every actual write site preserves all fields while distinguishing inferred ancestry."""
    transform = _ready(tmp_path, monkeypatch, labels)
    rows = _run(transform, mode, _payload(_synthetic(name)))
    subject = (
        STRAIN
        if "coli TEST" in name
        else PROVISIONAL_SPECIES
        if name == "Escherichia coli"
        else "kgmicrobe.strain:Escherichia_sp_TEST"
    )
    expected = [_edge(transform, source, target) for source, target in pairs]
    expected.append(_edge(transform, subject, TRAIT, hierarchy=False))
    assert _counter(rows) == _counter(expected)
    nodes = _rows(transform.output_node_file)
    for row in nodes:
        assert row["provided_by"] == transform.knowledge_source
        assert row["category"] == (PHENOTYPIC_CATEGORY if row["id"] == TRAIT else NCBI_CATEGORY)
    source_node = next(row for row in nodes if row["id"] == subject)
    assert source_node["name"] == name
    assert not _rows(transform.unresolved_taxa_file)


@pytest.mark.parametrize("mode", MODES)
def test_parsed_species_lookup_can_use_gtdb_fallback_without_native_parent_claim(tmp_path, monkeypatch, mode):
    """A successful genus fallback for a parsed binomial is still inferred, not observed."""
    crosswalk = {"escherichia coli": {"gtdb_genus": "Pseudomonas", "gtdb_species": "NA", "mapping_type": "genus_level"}}
    transform = _ready(tmp_path, monkeypatch, {"Pseudomonas": GENUS}, crosswalk)
    rows = _run(transform, mode, _payload(_synthetic("Escherichia coli TEST")))
    assert _counter(rows) == _counter(
        [
            _edge(transform, STRAIN, GENUS),
            _edge(transform, STRAIN, TRAIT, hierarchy=False),
        ]
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("index", range(3))
def test_complete_native_records_retain_original_endpoints_and_trait_provenance(tmp_path, monkeypatch, mode, index):
    """Replay full immutable records; do not replace their summaries with synthetic evidence."""
    records, witnesses = _records()
    transform = _ready(tmp_path, monkeypatch, {"Arthrobacter": "NCBITaxon:1663", "Dokdonia": "NCBITaxon:326319"})
    rows = _run(transform, mode, records[index])
    original = witnesses[index]["historical_assertion"]
    expected = _edge(transform, original["subject"], original["object"])
    hierarchy = [row for row in rows if row["predicate"] == SUBCLASS_PREDICATE]
    assert hierarchy == [expected]
    for field, value in original.items():
        if field in expected and field != "knowledge_level":
            assert expected[field] == value
    for row in rows:
        if row["predicate"] != SUBCLASS_PREDICATE:
            assert row["knowledge_level"] == OBSERVATION
            assert row["agent_type"] == AUTOMATED_AGENT
            assert row["primary_knowledge_source"] == transform.knowledge_source
    if index == 0:
        assert _counter(rows) == _counter(
            [expected, _edge(transform, original["subject"], TRAIT, hierarchy=False, percentage="100.0")]
        )


@pytest.mark.parametrize("mode", MODES)
def test_complete_name_resolution_does_not_create_parent_inference(tmp_path, monkeypatch, mode):
    """Existing direct subject resolution and complete trait metadata remain untouched."""
    name = "Escherichia coli TEST"
    transform = _ready(tmp_path, monkeypatch, {name: SPECIES})
    rows = _run(transform, mode, _payload(_synthetic(name)))
    assert rows == [_edge(transform, SPECIES, TRAIT, hierarchy=False)]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", ["Escherichia sp. TEST", "Escherichia coli", "unparseable-record"])
def test_missing_parent_and_unparseable_cases_are_not_silently_promoted(tmp_path, monkeypatch, mode, name):
    """Keep pre-existing no-edge and unresolved diagnostics when lookup evidence is absent."""
    transform = _ready(tmp_path, monkeypatch)
    assert _run(transform, mode, _payload(_synthetic(name))) == []
    assert _rows(transform.unresolved_taxa_file) == [{"tax_name": name}]


@pytest.mark.parametrize("mode", MODES)
def test_taxonomy_infrastructure_failure_still_propagates(tmp_path, monkeypatch, mode):
    """Metadata repair must not convert a failing ontology query into evidence of absence."""
    transform = _ready(tmp_path, monkeypatch)

    def fail(adapter, label, **kwargs):
        """Represent an unavailable authority, not an ordinary empty result."""
        raise OntologyDbUnavailableError("fixture authority unavailable")

    monkeypatch.setattr(metatraits, "search_by_label", fail)
    with pytest.raises(OntologyDbUnavailableError, match="fixture authority unavailable"):
        _run(transform, mode, _payload(_synthetic("Escherichia sp. TEST")))


@pytest.mark.parametrize("mode", MODES)
def test_duplicate_indeterminate_records_keep_diagnostics_and_deduplicate_hierarchy(tmp_path, monkeypatch, mode):
    """Source diagnostic multiplicity and existing graph deduplication are independent."""
    transform = _ready(tmp_path, monkeypatch, {"Escherichia": GENUS})
    record = _synthetic("Escherichia sp. TEST", "No robust majority")
    subject = "kgmicrobe.strain:Escherichia_sp_TEST"
    rows = _run(transform, mode, _payload(record) * 2)
    assert rows == [_edge(transform, subject, GENUS)]
    diagnostics = [json.loads(line) for line in transform.indeterminate_traits_file.read_text().splitlines()]
    expected = {
        "reason": "No robust majority",
        "primary_knowledge_source": transform.knowledge_source,
        "tax_name": record["tax_name"],
        "resolved_taxon": subject,
        "summary": record["summaries"][0],
    }
    assert diagnostics == [expected, expected]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("current", [True, False])
def test_actual_gtdb_name_override_keeps_its_existing_subject_and_observation(tmp_path, monkeypatch, mode, current):
    """The inherited hierarchy repair does not enter or rewrite GTDB correspondence policy."""
    transform = _ready(tmp_path, monkeypatch, transform_type=MetaTraitsGTDBTransform)
    name = "Escherichia coli" if current else "Escherichia sp030433645"
    if current:
        transform.gtdb_to_ncbi[name] = Counter({SPECIES: 1})
    subject = SPECIES if current else "GTDB:s__Escherichia_sp030433645"
    assert _run(transform, mode, _payload(_synthetic(name))) == [_edge(transform, subject, TRAIT, hierarchy=False)]
