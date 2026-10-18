"""Rhea node scalars survive aggregation without pooling directions or selecting conflicts."""

import csv
from contextlib import contextmanager
from pathlib import Path

import pytest

from kg_microbe.merge_utils.kgx_source import (
    ProvenancePreservingTransformer,
    RelationAwareTsvSink,
    merge_assertion_graphs,
    parse_source,
)
from kg_microbe.merge_utils.local_context import local_prefix_context
from kg_microbe.transform_utils.rhea_mappings.native_graph import POLYMERIZATION_FIELD
from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
    RHEA_DIRECTION_FIELD,
    RHEA_MASTER_FIELD,
    RHEA_STATUS_FIELD,
)
from tests.test_rhea_native_transform import _producer, _rows

FIELDS = (RHEA_DIRECTION_FIELD, RHEA_MASTER_FIELD, RHEA_STATUS_FIELD, POLYMERIZATION_FIELD)
VALID = dict(zip(FIELDS, ("UN", "RHEA:100", "Approved", "n+1"), strict=True))


@pytest.fixture(autouse=True)
def pinned_schema(monkeypatch):
    """Keep the real KGX serializer offline and independent of ambient ontology files."""
    schema = Path(__file__).parent / "resources/merge_offline_context/biolink-model.yaml"
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(schema))


@contextmanager
def _sink(tmp_path, *, node_properties=FIELDS, edge_properties=()):
    """Exercise the production first-write serializer, not a rewritten TSV copy."""
    with local_prefix_context():
        sink = RelationAwareTsvSink(
            ProvenancePreservingTransformer(),
            str(tmp_path / "first-write"),
            "tsv",
            node_properties=set(node_properties),
            edge_properties=set(edge_properties),
        )
    try:
        yield sink
    finally:
        sink.NFH.close()
        sink.EFH.close()


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("shape", ["scalar", "list", "tuple", "set", "with_absences", "absent"])
def test_identical_rhea_scalars_and_absences_have_one_literal_value(tmp_path, field, shape):
    """Exact duplicates coalesce; absent contributions cannot become pipe text."""
    value = VALID[field]
    choices = {
        "scalar": value,
        "list": [value, value],
        "tuple": (value, value),
        "set": {value},
        "with_absences": [None, "", value, value, ""],
        "absent": ["", None, ""],
    }
    with _sink(tmp_path) as sink:
        sink.write_node({"id": "RHEA:100", field: choices[shape]})
    assert _rows(Path(sink.nodes_file_name))[0][field] == ("" if shape == "absent" else value)


@pytest.mark.parametrize(
    "field,value",
    [(RHEA_DIRECTION_FIELD, state) for state in ("UN", "LR", "RL", "BI")]
    + [(RHEA_STATUS_FIELD, status) for status in ("Approved", "Preliminary")],
)
def test_each_released_native_direction_and_active_status_remains_literal(tmp_path, field, value):
    """Undefined is not reversible, and preliminary is neither dropped nor promoted."""
    with _sink(tmp_path) as sink:
        sink.write_node({"id": "RHEA:100", field: [value, "", value]})
    assert _rows(Path(sink.nodes_file_name))[0][field] == value


@pytest.mark.parametrize(
    "field,value",
    [
        (RHEA_DIRECTION_FIELD, ["UN", "BI"]),
        (RHEA_MASTER_FIELD, ["RHEA:100", "RHEA:200"]),
        (RHEA_STATUS_FIELD, ["Approved", "Preliminary"]),
        (POLYMERIZATION_FIELD, ["n", "n+1"]),
    ],
)
def test_conflicting_nonempty_rhea_contributions_fail_before_row_write(tmp_path, field, value):
    """A source disagreement is not resolved by selecting, joining or reinterpreting values."""
    with _sink(tmp_path) as sink:
        with pytest.raises(ValueError, match="Conflicting Rhea node field"):
            sink.write_node({"id": "RHEA:100", field: value})
    assert _rows(Path(sink.nodes_file_name)) == []


@pytest.mark.parametrize(
    "field,value",
    [
        (RHEA_DIRECTION_FIELD, "neutral"),
        (RHEA_DIRECTION_FIELD, "left_to_right"),
        (RHEA_DIRECTION_FIELD, "UN|UN"),
        (RHEA_DIRECTION_FIELD, " LR"),
        (RHEA_MASTER_FIELD, "RHEA:0"),
        (RHEA_MASTER_FIELD, "RHEA:0100"),
        (RHEA_MASTER_FIELD, "RHEA:-100"),
        (RHEA_MASTER_FIELD, "rheav:100"),
        (RHEA_MASTER_FIELD, "http://rdf.rhea-db.org/100"),
        (RHEA_MASTER_FIELD, "RHEA:100|RHEA:100"),
        (RHEA_STATUS_FIELD, "approved"),
        (RHEA_STATUS_FIELD, "Obsolete"),
        (RHEA_STATUS_FIELD, "Approved|Approved"),
        (RHEA_STATUS_FIELD, "Unknown"),
        (POLYMERIZATION_FIELD, [True]),
        (POLYMERIZATION_FIELD, 1),
        (POLYMERIZATION_FIELD, [["n"]]),
    ],
)
def test_invalid_rhea_scalar_is_not_repaired_at_serialization(tmp_path, field, value):
    """Direction/master/status tokens are exact native forms, not pipe-encoded collections."""
    with _sink(tmp_path) as sink:
        with pytest.raises(ValueError, match="Invalid Rhea node field"):
            sink.write_node({"id": "RHEA:100", field: value})
    assert _rows(Path(sink.nodes_file_name)) == []


def test_non_rhea_list_fields_and_literal_polymer_text_are_unchanged(tmp_path):
    """Multivalued list fields and native polymer expressions survive general scalar canonicalization (#1674)."""
    properties = (*FIELDS, "xref", "unrelated_extension")
    with _sink(tmp_path, node_properties=properties) as sink:
        sink.write_node(
            {
                "id": "rheav:Polymer_1",
                POLYMERIZATION_FIELD: ["n|m", "n|m", ""],
                "xref": ["xref:2", "xref:1"],
                "unrelated_extension": ["value:1", "value:1", ""],
            }
        )
    row = _rows(Path(sink.nodes_file_name))[0]
    assert row[POLYMERIZATION_FIELD] == "n|m"
    assert row["xref"] == "xref:1|xref:2"
    assert row["unrelated_extension"] == "value:1"


def test_actual_native_emission_and_duplicate_merge_preserve_rhea_scalars_and_edges(tmp_path, monkeypatch):
    """All four states and absent chemical annotations survive real parsing/union/first serialization."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    source = {"input": {"format": "tsv", "filename": [str(producer.output_node_file), str(producer.output_edge_file)]}}
    stores = [parse_source(name, source, str(tmp_path)) for name in ("original", "independent-copy")]
    graph = merge_assertion_graphs(store.graph for store in stores)
    with _sink(tmp_path, node_properties=producer.node_header, edge_properties=producer.edge_header) as sink:
        for _, row in graph.nodes(data=True):
            sink.write_node(row)
        for _, _, row in graph.edges(data=True):
            sink.write_edge(row)
    source_nodes = {row["id"]: {field: row[field] for field in FIELDS} for row in _rows(producer.output_node_file)}
    merged_nodes = {row["id"]: {field: row[field] for field in FIELDS} for row in _rows(Path(sink.nodes_file_name))}
    assert source_nodes == merged_nodes
    assert {row[RHEA_DIRECTION_FIELD] for row in source_nodes.values()} == {"", "UN", "LR", "RL", "BI"}
    with producer.output_edge_file.open(newline="") as stream:
        expected = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert sorted(tuple(sorted(row.items())) for row in expected) == sorted(
        tuple(sorted(row.items())) for row in _rows(Path(sink.edges_file_name))
    )
