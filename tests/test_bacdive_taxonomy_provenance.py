"""Computed taxon-name fallback must not impersonate a supplied native taxid (#1279)."""

import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    INFERRED_SUBCLASS_RELATION,
    MANUAL_AGENT,
    OBSERVATION,
    PREDICTION,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from tests.bacdive_synthetic_fallback_context import assert_actual_native_batch
from tests.bacdive_synthetic_fallback_context import synthetic_fallback_context as _synthetic_fallback_context
from tests.test_bacdive_run_references import _run_fixture

FIXTURE = Path(__file__).parent / "resources/bacdive_taxonomy_provenance_controls.json"
synthetic_fallback_context = _synthetic_fallback_context


def test_actual_run_separates_direct_cached_and_uncached_fallback(tmp_path, monkeypatch, synthetic_fallback_context):
    """Only inference provenance changes; direct taxids, selected parents and other observations survive."""
    records = json.loads(FIXTURE.read_text())["records"]
    captured, _ = synthetic_fallback_context({"Fixture species": "NCBITaxon:11"})
    edges, nodes = _run_fixture(tmp_path, monkeypatch, records)
    taxon_edges = [row for row in edges if row["object"] == "NCBITaxon:11"]
    assert len(taxon_edges) == 4
    child = assert_actual_native_batch(captured[0], expected_targets={"NCBITaxon:11"}, expected_eligible=2)
    assert child["native_queries"]["exact_label_batch"]["queries"] == ["Fixture", "Fixture species"]
    assert len(captured[0].ncbitaxon_fallback_cache) == 1, "Equal selectors retain one inference-aware cache slot"
    for row in taxon_edges:
        direct = row["subject"] in {"kgmicrobe.strain:bacdive_1", "kgmicrobe.strain:bacdive_4"}
        assert row["predicate"] == SUBCLASS_PREDICATE
        assert row["relation"] == (RDFS_SUBCLASS_OF if direct else INFERRED_SUBCLASS_RELATION)
        assert row["knowledge_level"] == (OBSERVATION if direct else PREDICTION)
        assert row["agent_type"] == (MANUAL_AGENT if direct else AUTOMATED_AGENT)
        assert row["primary_knowledge_source"] == "infores:bacdive"
        assert row["publications"] == "https://bacdive.dsmz.de/strain/" + row["subject"].rsplit("_", 1)[1]
    others = [row for row in edges if row["object"] != "NCBITaxon:11"]
    assert len(others) == 4
    assert all(row["knowledge_level"] == OBSERVATION and row["agent_type"] == MANUAL_AGENT for row in others)
    assert {node["id"] for node in nodes if node["id"].startswith("kgmicrobe.strain:")} == {
        f"kgmicrobe.strain:bacdive_{number}" for number in range(1, 5)
    }


@pytest.mark.parametrize("object_id", ["NCBITaxon:11", "kgmicrobe.genus:Unresolved"])
def test_existing_explicit_inference_routes_use_computational_metadata(object_id):
    """All later inference branches share the same exact derivation metadata contract."""
    transform = BacDiveTransform.__new__(BacDiveTransform)
    assert transform._add_edge_metadata(SUBCLASS_PREDICATE, INFERRED_SUBCLASS_RELATION, object_id) == (
        PREDICTION,
        AUTOMATED_AGENT,
    )
    assert transform._add_edge_metadata(SUBCLASS_PREDICATE, RDFS_SUBCLASS_OF, object_id) == (OBSERVATION, MANUAL_AGENT)
