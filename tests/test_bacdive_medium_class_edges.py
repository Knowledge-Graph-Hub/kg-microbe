"""Recipe-class provenance and relation must not invent METPO recipe assertions."""

import ast
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.bacdive.emission import StrainProvenanceWriter
from kg_microbe.transform_utils.constants import (
    BACDIVE_GROWTH_MEDIUM_CLASS,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.utils.tsv_io import tsv_writer

FIXTURE = Path(__file__).parent / "resources/bacdive_medium_class_edges.json"


def _transform():
    transform = BacDiveTransform.__new__(BacDiveTransform)
    transform.knowledge_source = "infores:bacdive"
    return transform


@pytest.mark.parametrize("item", json.loads(FIXTURE.read_text()))
def test_exact_recipe_and_unchanged_growth_rows(item):
    """The actual helper/writer preserves both polarities and keeps ambiguous growth absent."""
    before = FIXTURE.read_bytes()
    transform = _transform()
    output = io.StringIO()
    writer = StrainProvenanceWriter(
        tsv_writer(output),
        knowledge_source=transform.knowledge_source,
        ks_column_index=4,
        publications_column_index=10,
    )
    subject = "kgmicrobe.strain:bacdive_140179"
    transform._write_medium_edges(subject, item["medium"], item["growth"], writer)
    rows = [line.split("\t") for line in output.getvalue().splitlines()]
    assert rows[0][:7] == [
        item["medium"],
        SUBCLASS_PREDICATE,
        BACDIVE_GROWTH_MEDIUM_CLASS,
        RDFS_SUBCLASS_OF,
        "infores:bacdive",
        KNOWLEDGE_ASSERTION,
        MANUAL_AGENT,
    ]
    assert len(rows) == (2 if item["predicate"] else 1)
    if item["predicate"]:
        # Metadata uses the unchanged production classification, not a test override.
        metadata = list(transform._add_edge_metadata(item["predicate"], item["predicate"], item["medium"]))
        assert rows[1][:7] == [
            subject,
            item["predicate"],
            item["medium"],
            item["predicate"],
            "infores:bacdive",
            *metadata,
        ]
        assert "https://bacdive.dsmz.de/strain/140179" in rows[1]
    assert "infores:metpo" not in output.getvalue() and "rdf:type" not in output.getvalue()
    assert FIXTURE.read_bytes() == before


@pytest.mark.parametrize("growth", [None, "", True, 1, [], {}, " yes ", "variable"])
def test_nonobservations_do_not_create_growth_claims(growth):
    """Preserve the old exact yes/no routing, without new trimming or truthiness inference."""
    output = io.StringIO()
    _transform()._write_medium_edges("kgmicrobe.strain:bacdive_1", "mediadive.medium:1672", growth, tsv_writer(output))
    assert len(output.getvalue().splitlines()) == 1


def test_production_loop_calls_recipe_emitter():
    """The real transform uses the tested emission path, not a disconnected helper."""
    import inspect

    tree = ast.parse(inspect.getsource(BacDiveTransform))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_write_medium_edges"
    ]
    assert len(calls) == 1
    assert [arg.id for arg in calls[0].args] == ["organism_id", "mid", "growth", "edge_writer"]
