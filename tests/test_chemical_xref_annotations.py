"""Correct annotation spelling without re-arbitrating historical identities (#1259)."""

import csv
import gzip
import hashlib
import json
from copy import deepcopy

import pytest

from kg_microbe.transform_utils.constants import ID_COLUMN, OBJECT_COLUMN, SOURCE_RECORD_COLUMN, XREF_COLUMN
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_bundle import ReviewedIngredientBundle
from tests.test_chemical_mapping_utils import reset_cache as reset_cache
from tests.test_mediadive_material_scope_audit import _producer
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

CANONICAL = "kegg.compound:C00865"
ALIAS = "kegg.compound:cpd:C00865"


def _load(tmp_path, rows, filename="mappings.tsv"):
    """Load a tiny original-row fixture through the actual shared reader."""
    path = tmp_path / filename
    _table(path, FIELDS, rows, _metadata())
    return runtime.ChemicalMappingLoader(path), path


@pytest.mark.parametrize("alias_first", [False, True])
def test_annotation_does_not_change_conflicting_literal_lookup_winners(tmp_path, alias_first):
    """Explicit canonical and alias choices survive either interleaving and reload."""
    alias = _row(ALIAS, "CHEBI:136912", "Alias fixture")
    canonical = _row(CANONICAL, "CHEBI:16247", "Canonical fixture")
    rows = [alias, canonical] if alias_first else [canonical, alias]
    rows.append(_row(CANONICAL, "CHEBI:1", "Later canonical fixture"))
    loader, path = _load(tmp_path, rows)
    original = path.read_bytes()
    original_indices = deepcopy(runtime._XREF_INDEX)
    original_xrefs = deepcopy(runtime._PRIMARY_XREFS_INDEX)
    for identifier in ("CHEBI:136912", "CHEBI:16247", "CHEBI:1"):
        assert runtime.get_xrefs(identifier) == [CANONICAL]
        assert loader.get_xrefs(identifier) == [CANONICAL]
        assert loader.get_node_enrichment(identifier)[XREF_COLUMN] == CANONICAL
    assert runtime._PRIMARY_XREFS_INDEX == original_xrefs
    assert runtime._XREF_INDEX == original_indices
    assert runtime.find_chebi_by_xref(CANONICAL) == "CHEBI:16247"
    assert runtime.find_chebi_by_xref(ALIAS) == "CHEBI:136912"
    _load(tmp_path, [_row("cas:7732-18-5", "CHEBI:15377", "Water")], "other.tsv")
    runtime.load_unified_mappings(path)
    assert runtime._XREF_INDEX == original_indices
    assert runtime._PRIMARY_XREFS_INDEX == original_xrefs
    assert path.read_bytes() == original
    assert runtime.get_xrefs("CHEBI:136912") == [CANONICAL]


def test_alias_only_does_not_add_an_unasserted_canonical_lookup(tmp_path):
    """Annotation formatting is not an extra identity fallback."""
    loader, _ = _load(tmp_path, [_row(ALIAS, "CHEBI:136912", "Alias fixture")])
    assert loader.get_xrefs("CHEBI:136912") == [CANONICAL]
    assert loader.find_chebi_by_xref(ALIAS) == "CHEBI:136912"
    assert loader.find_chebi_by_xref(CANONICAL) is None


def test_same_target_annotations_deduplicate_without_erasing_original_rows(tmp_path):
    """All repeated claims and original query keys remain available to the reader."""
    rows = [_row(value, "CHEBI:7070", "Fixture salt") for value in (ALIAS, CANONICAL, ALIAS)]
    loader, path = _load(tmp_path, rows)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert loader.get_xrefs("CHEBI:7070") == [CANONICAL]
    assert list(runtime._iter_sssom_rows(path)) == rows
    assert runtime._PRIMARY_XREFS_INDEX["CHEBI:7070"] == [CANONICAL, ALIAS]
    assert loader.find_chebi_by_xref(ALIAS) == loader.find_chebi_by_xref(CANONICAL) == "CHEBI:7070"
    returned = loader.get_xrefs("CHEBI:7070")
    returned.append("fixture:cannot_mutate_cache")
    assert loader.get_xrefs("CHEBI:7070") == [CANONICAL]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "identifier",
    [
        "kegg.compound:C12345",
        "cpd:C12345",
        "KEGG:C12345",
        "kegg.drug:D12345",
        "kegg.glycan:G12345",
        "kegg.drug:cpd:C12345",
        "kegg.compound:cpd:D12345",
        "kegg.compound:cpd:C1234",
        "kegg.compound:cpd:C123456",
        "kegg.compound:cpd:C12345extra",
        "kegg.compound:cpd:cpd:C12345",
        "kegg.compound:cpd:c12345",
        "KEGG.COMPOUND:cpd:C12345",
        "kegg.compound:CPD:C12345",
        "kegg.compound:cpd:C１２３４５",
        "hsa:12345",
        "pdb-ccd:https://example.org/entry",
        "https://example.org/kegg.compound:cpd:C12345",
        " kegg.compound:cpd:C12345",
        "kegg.compound:cpd:C12345\n",
        "",
    ],
)
def test_normalizer_does_not_rewrite_other_namespaces_or_malformed_forms(identifier):
    """Only the exact ASCII grammar is in scope, not arbitrary nested colons."""
    assert runtime._xref_annotation(identifier) == identifier


def test_exact_annotation_rule_is_idempotent():
    """Normalization of the selected syntax is stable on repeated output."""
    assert runtime._xref_annotation(ALIAS) == CANONICAL
    assert runtime._xref_annotation(runtime._xref_annotation(ALIAS)) == CANONICAL


@pytest.mark.parametrize(
    "predicate,comment",
    [
        ("skos:broadMatch", ""),
        ("skos:narrowMatch", ""),
        ("skos:closeMatch", ""),
        ("oboInOwl:hasDbXref", ""),
        ("skos:closeMatch", "recipe_equivalent_hydrate"),
    ],
)
def test_nonidentity_rows_are_not_promoted_into_xrefs(tmp_path, predicate, comment):
    """The syntax fix does not alter the existing identity-route admission."""
    loader, _ = _load(tmp_path, [_row(ALIAS, "CHEBI:7070", "Fixture", predicate=predicate, comment=comment)])
    assert loader.get_xrefs("CHEBI:7070") == []
    assert loader.find_chebi_by_xref(ALIAS) is None
    assert loader.find_chebi_by_xref(CANONICAL) is None


def test_actual_bundle_enrichment_preserves_annotation_boundary(tmp_path):
    """The real bundle merger cannot leak the old spelling after node enrichment."""
    loader, _ = _load(tmp_path, [_row(ALIAS, "CHEBI:7070", "Fixture salt")])
    # Exercise the real merger on an isolated, already-selected annotation state;
    # this is not a bypass for bundle admission or an identity assertion.
    bundle = ReviewedIngredientBundle.__new__(ReviewedIngredientBundle)
    bundle._covered = {"CHEBI:7070"}
    bundle._identities = {}
    bundle._xrefs = {"CHEBI:7070": {ALIAS, CANONICAL, "cas:75-57-0"}}
    result = runtime.get_node_enrichment("CHEBI:7070", ingredient_bundle=bundle)
    assert result[XREF_COLUMN] == "cas:75-57-0|" + CANONICAL
    assert bundle._xrefs["CHEBI:7070"] == {ALIAS, CANONICAL, "cas:75-57-0"}
    assert loader.find_chebi_by_xref(CANONICAL) is None


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_actual_mediadive_producer_uses_canonical_annotations_on_every_identity_route(tmp_path, monkeypatch, route):
    """The real recipe producer emits fixed xrefs without changing endpoint/context."""
    name = "Fixture salt" if route == "unified" else "Fixture source name"
    raw = {"compound_id": 99, "compound": name, "amount": 1, "unit": "g"}
    producer, mapping = _producer(
        tmp_path,
        monkeypatch,
        recipes={"1": {"recipe": [raw]}},
        unified=0,
        legacy=False,
        embedded={"99": {"name": name, **({"ChEBI": "7070"} if route == "embedded" else {})}},
    )
    source = tmp_path / "tiny.tsv"
    _table(source, FIELDS, [_row(ALIAS, "CHEBI:7070", "Fixture salt")], _metadata())
    with gzip.open(mapping, "wt", encoding="utf-8") as stream:
        stream.write(source.read_text())
    producer.chemical_loader = runtime.ChemicalMappingLoader(mapping)
    if route == "legacy":
        producer.compound_mappings[name.lower()] = "CHEBI:7070"
    producer.run(show_status=False)
    with producer.output_node_file.open() as stream:
        nodes = [row for row in csv.DictReader(stream, delimiter="\t") if row[ID_COLUMN] == "CHEBI:7070"]
    assert len(nodes) == 1
    assert nodes[0][XREF_COLUMN] == CANONICAL
    with producer.output_edge_file.open() as stream:
        edges = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(edges) == 1
    assert edges[0][OBJECT_COLUMN] == "CHEBI:7070"
    assert edges[0]["value"] == "1.0" and edges[0]["unit"] == "g"
    assert json.loads(edges[0][SOURCE_RECORD_COLUMN]) == raw
    assert runtime.find_chebi_by_xref(ALIAS) == "CHEBI:7070"
    assert runtime.find_chebi_by_xref(CANONICAL) is None
