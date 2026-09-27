"""Cache ordinary taxonomy misses without changing resolution or worker assertions."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kg_microbe.transform_utils.constants import HAS_PHENOTYPE_PREDICATE, METATRAITS, PHENOTYPIC_CATEGORY
from kg_microbe.transform_utils.metatraits import metatraits
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError


def _transform():
    """Create only the worker-local taxonomy state, without any real database."""
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    transform._ncbi_adapter = object()
    transform.ncbitaxon_name_to_id = {}
    transform.ncbi_to_gtdb_mappings = {}
    return transform


def test_repeated_misses_and_higher_rank_searches_are_cached(monkeypatch):
    """The repeated genus and suffix lookups run once per exact label."""
    transform = _transform()
    query = Mock(return_value=[])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    for _ in range(4):
        assert transform._search_ncbitaxon_by_label("Bacillales") is None
        assert transform._search_higher_ranks_in_ncbitaxon("Bacillales") is None
    assert [call.args[1] for call in query.call_args_list] == [
        "Bacillales",
        "Bacillalesaceae",
        "Bacillalesales",
        "Bacillalesia",
        "Bacillalesota",
    ]
    assert all(call.kwargs == {"limit": 1} for call in query.call_args_list)


def test_positive_index_and_original_first_match_behavior_are_unchanged(monkeypatch):
    """Do not alter existing positive case folding or multi-result selection."""
    transform = _transform()
    query = Mock(return_value=["NCBITaxon:562", "NCBITaxon:561"])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    assert transform._search_ncbitaxon_by_label("Escherichia coli") == "NCBITaxon:562"
    assert transform._search_ncbitaxon_by_label("ESCHERICHIA COLI") == "NCBITaxon:562"
    assert query.call_count == 1


def test_negative_queries_preserve_case_and_positive_index_precedence(monkeypatch):
    """A failed lowercase query cannot hide a differently cased authority label."""
    transform = _transform()
    query = Mock(side_effect=lambda adapter, label, **kwargs: ["NCBITaxon:561"] if label == "Escherichia" else [])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    assert transform._search_ncbitaxon_by_label("escherichia") is None
    assert transform._search_ncbitaxon_by_label("Escherichia") == "NCBITaxon:561"
    assert transform._search_ncbitaxon_by_label("escherichia") == "NCBITaxon:561"
    assert query.call_count == 2


@pytest.mark.parametrize("failure", [OntologyDbUnavailableError("unavailable"), RuntimeError("SQL failed")])
def test_search_errors_propagate_and_are_not_cached(monkeypatch, failure):
    """Failed ontology access is never stored as evidence that a label is absent."""
    transform = _transform()
    query = Mock(side_effect=[failure, ["NCBITaxon:561"]])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    with pytest.raises(type(failure), match=str(failure)):
        transform._search_ncbitaxon_by_label("Escherichia")
    assert transform._search_ncbitaxon_by_label("Escherichia") == "NCBITaxon:561"
    assert query.call_count == 2


def test_miss_cache_is_bound_to_adapter_and_worker(monkeypatch):
    """Replacement adapters and fresh worker instances cannot inherit negative results."""
    transform = _transform()
    query = Mock(side_effect=[[], ["NCBITaxon:561"], []])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    assert transform._search_ncbitaxon_by_label("Escherichia") is None
    transform._ncbi_adapter = object()
    assert transform._search_ncbitaxon_by_label("Escherichia") == "NCBITaxon:561"
    assert _transform()._search_ncbitaxon_by_label("Escherichia") is None
    assert query.call_count == 3


def test_real_oak_wrapper_exhausts_generator_and_propagates_partial_failure(monkeypatch):
    """Do not turn partially consumed failed OAK results into a cached absence."""
    transform = _transform()
    query = Mock()

    def broken_results():
        """Simulate infrastructure loss partway through an OAK iterator."""
        yield "NCBITaxon:561"
        raise OntologyDbUnavailableError("iteration interrupted")

    query.side_effect = [broken_results(), iter(()), iter(("NCBITaxon:561",))]
    transform._ncbi_adapter = SimpleNamespace(basic_search=query)
    with pytest.raises(OntologyDbUnavailableError, match="iteration interrupted"):
        transform._search_ncbitaxon_by_label("Escherichia")
    assert transform._search_ncbitaxon_by_label("Escherichia") is None
    assert transform._search_ncbitaxon_by_label("Escherichia") is None
    assert transform._search_ncbitaxon_by_label("ESCHERICHIA") == "NCBITaxon:561"
    assert [call.args[0] for call in query.call_args_list] == ["Escherichia", "Escherichia", "ESCHERICHIA"]
    assert all(call.kwargs["config"].limit == 1 for call in query.call_args_list)


def test_adapter_initialization_failure_propagates_and_retry_remains_possible(monkeypatch):
    """A failed connection before the first query must not poison the negative cache."""
    transform = _transform()
    transform._ncbi_adapter = None
    factory = Mock(side_effect=[OntologyDbUnavailableError("cannot open"), object()])
    query = Mock(return_value=[])
    monkeypatch.setattr(metatraits, "_get_ncbitaxon_adapter", factory)
    monkeypatch.setattr(metatraits, "search_by_label", query)
    with pytest.raises(OntologyDbUnavailableError, match="cannot open"):
        transform._search_ncbitaxon_by_label("absent")
    assert transform._search_ncbitaxon_by_label("absent") is None
    assert transform._search_ncbitaxon_by_label("absent") is None
    assert factory.call_count == 2
    assert query.call_count == 1


def test_cached_primary_miss_does_not_skip_new_gtdb_fallback(monkeypatch):
    """Cache the ontology query, not the higher-level resolver's mutable mappings."""
    transform = _transform()
    query = Mock(side_effect=lambda adapter, label, **kwargs: ["NCBITaxon:562"] if label == "Escherichia coli" else [])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    assert transform._search_ncbitaxon_by_label("unresolved fixture") is None
    transform.ncbi_to_gtdb_mappings["unresolved fixture"] = {
        "gtdb_genus": "Escherichia",
        "gtdb_species": "coli",
        "mapping_type": "exact_species",
    }
    assert transform._search_ncbitaxon_by_label("unresolved fixture") == "NCBITaxon:562"
    assert [call.args[1] for call in query.call_args_list] == ["unresolved fixture", "Escherichia coli"]


def test_gtdb_species_and_genus_misses_share_exact_query_cache(monkeypatch):
    """Distinct source names can reuse identical unsuccessful fallback queries."""
    transform = _transform()
    query = Mock(return_value=[])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    for name in ("source one", "source two"):
        transform.ncbi_to_gtdb_mappings[name] = {
            "gtdb_genus": "Unresolved",
            "gtdb_species": "species",
            "mapping_type": "exact_species",
        }
        assert transform._search_ncbitaxon_by_label(name) is None
    assert Counter(call.args[1] for call in query.call_args_list) == {
        "source one": 1,
        "source two": 1,
        "Unresolved species": 1,
        "Unresolved": 1,
    }


def _worker(tmp_path, monkeypatch):
    """Initialize the real streaming worker with tiny offline trait and taxonomy inputs."""
    loader = SimpleNamespace(get_node_enrichment=lambda curie: {"xref": "", "synonym": ""})
    monkeypatch.setattr(metatraits, "ChemicalMappingLoader", lambda: loader)
    transform = _transform()
    shared = {
        "input_base_dir": str(tmp_path),
        "output_dir": str(tmp_path),
        "knowledge_source": f"infores:{METATRAITS}",
        "trait_mapping": {
            "gram positive": {
                "curie": "METPO:1000698",
                "name": "gram positive",
                "category": PHENOTYPIC_CATEGORY,
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
    transform._init_from_shared_data(shared)
    transform._ncbi_adapter = object()
    return transform


def test_negative_cache_is_not_shared_with_reconstructed_worker(tmp_path, monkeypatch):
    """Use the actual worker initialization boundary, not a manually copied cache."""
    parent = _worker(tmp_path, monkeypatch)
    query = Mock(return_value=[])
    monkeypatch.setattr(metatraits, "search_by_label", query)
    assert parent._search_ncbitaxon_by_label("absent") is None
    shared = parent._get_shared_init_data()
    assert "_ncbi_label_miss_cache" not in shared
    worker = MetaTraitsTransform.__new__(MetaTraitsTransform)
    worker._init_from_shared_data(shared)
    monkeypatch.setattr(metatraits, "_get_ncbitaxon_adapter", lambda: object())
    assert worker._search_ncbitaxon_by_label("absent") is None
    assert query.call_count == 2


def test_streaming_worker_output_and_unresolved_decisions_match_uncached_strategy(tmp_path, monkeypatch):
    """Compare complete node/edge/diagnostic bytes and unresolved results, not just counts."""
    results, calls = [], []
    for cached in (False, True):
        output = tmp_path / str(cached)
        output.mkdir()
        transform = _worker(output, monkeypatch)
        query = Mock(
            side_effect=lambda adapter, label, **kwargs: {
                "Escherichia coli": ["NCBITaxon:562"],
                "Escherichia": ["NCBITaxon:561"],
            }.get(label, [])
        )
        monkeypatch.setattr(metatraits, "search_by_label", query)
        if not cached:
            # Same resolver and worker; restore only the original uncached OAK call.
            monkeypatch.setattr(
                transform,
                "_search_ncbitaxon_label",
                lambda label, query=query, transform=transform: query(transform._get_ncbitaxon_impl(), label, limit=1),
            )
        result = transform._process_single_file(
            Path(__file__).parent / "resources/metatraits_taxonomy_cache.jsonl", output, False
        )
        results.append({key: value.read_bytes() if isinstance(value, Path) else value for key, value in result.items()})
        calls.append(query.call_count)
    assert results[0] == results[1]
    assert calls[1] < calls[0]
    assert results[1]["unresolved_taxa"]
