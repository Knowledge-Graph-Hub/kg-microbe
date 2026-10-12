"""Finite native FOODON schema-property exclusion preserves entity and relation evidence."""

import csv
import hashlib
import json
import shutil
from itertools import chain
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.ontology_metadata import reviewed_foodon_schema_property_ids
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files

FIXTURE = Path(__file__).parent / "resources" / "foodon_schema_property_declarations.json"
IDS = {"FOODON:00001301", "FOODON:00001563", "FOODON:00002420"}


def _document():
    """Load unchanged native declarations, never synthetic claims about their types."""
    return json.loads(FIXTURE.read_text())


def _declarations(document):
    """Visit every graph so a later semantic declaration cannot be lost."""
    return chain.from_iterable(graph.get("nodes", []) for graph in document["graphs"])


def test_exact_native_property_cohort_does_not_exclude_other_object_properties():
    """Three explicit OBJECT declarations authorize only the reviewed finite IDs."""
    document = _document()
    assert reviewed_foodon_schema_property_ids(_declarations(document)) == IDS
    native = {compact_identifier(node["id"]): node for node in _declarations(document)}
    assert native["RO:0000086"]["type"] == "PROPERTY"
    assert native["RO:0000086"]["propertyType"] == "OBJECT"
    assert "RO:0000086" not in reviewed_foodon_schema_property_ids(_declarations(document))


@pytest.mark.parametrize(
    "representation", ["FOODON:00001301", "OBO:FOODON_00001301", "http://purl.obolibrary.org/obo/FOODON_00001301"]
)
def test_known_identifier_aliases_require_the_same_live_property_record(representation):
    """Alias matching changes neither the finite scope nor declaration requirement."""
    assert reviewed_foodon_schema_property_ids(
        [{"id": representation, "type": "PROPERTY", "propertyType": "OBJECT"}]
    ) == {"FOODON:00001301"}


@pytest.mark.parametrize("kind", [None, "CLASS", "INDIVIDUAL"])
def test_missing_or_nonproperty_declaration_never_authorizes_exclusion(kind):
    """A reviewed ID and an attractive label alone are insufficient."""
    node = {"id": "FOODON:00001301", "lbl": "has food substance analog"}
    if kind:
        node["type"] = kind
    assert reviewed_foodon_schema_property_ids([node]) == set()


@pytest.mark.parametrize("property_type", [None, "ANNOTATION", "DATA"])
def test_other_property_kinds_are_outside_the_reviewed_contract(property_type):
    """The native OBJECT evidence is not permission to remove arbitrary property declarations."""
    assert (
        reviewed_foodon_schema_property_ids(
            [{"id": "FOODON:00001301", "type": "PROPERTY", "propertyType": property_type}]
        )
        == set()
    )


@pytest.mark.parametrize(
    "meta",
    [
        {"deprecated": True},
        {"basicPropertyValues": [{"pred": "http://www.w3.org/2002/07/owl#deprecated", "val": "true"}]},
        {"basicPropertyValues": [{"pred": "owl:deprecated", "val": "1"}]},
    ],
)
def test_retired_property_is_not_a_live_exclusion_authority(meta):
    """Retirement handling is a different native decision from this live-property cohort."""
    node = {"id": "FOODON:00001301", "type": "PROPERTY", "propertyType": "OBJECT", "meta": meta}
    assert reviewed_foodon_schema_property_ids([node]) == set()


@pytest.mark.parametrize("kind", ["CLASS", "INDIVIDUAL"])
def test_cross_graph_entity_punning_protects_node_and_incident_rows(tmp_path, kind):
    """An explicit semantic declaration protects the ID from the finite schema exclusion."""
    document = _document()
    document["graphs"].append({"nodes": [{"id": "OBO:FOODON_00001301", "type": kind}]})
    assert reviewed_foodon_schema_property_ids(_declarations(document)) == IDS - {"FOODON:00001301"}
    authority = tmp_path / "foodon.json"
    authority.write_text(json.dumps(document))
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.node_header = ["id", "category", "name"]
    transform.edge_header = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
    transform._drop_deprecated_terms(authority)
    nodes, edges = tmp_path / "foodon_nodes.tsv", tmp_path / "foodon_edges.tsv"
    nodes.write_text(
        "id\tcategory\tname\nFOODON:00001301\tbiolink:NamedThing\tPunned entity\n"
        "fixture:1\tbiolink:NamedThing\tTarget\n"
    )
    edges.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\nFOODON:00001301\tbiolink:related_to\tfixture:1\tskos:related\tinfores:foodon\n"
    )
    transform._normalize_schema(nodes, edges)
    assert "FOODON:00001301" in {row["id"] for row in graph_rows(nodes)}
    assert [row["subject"] for row in graph_rows(edges)] == ["FOODON:00001301"]
    assert not list(graph_rows(tmp_path / "foodon_metadata_exclusions.tsv"))
    assert not list(graph_rows(tmp_path / "foodon_metadata_edge_exclusions.tsv"))


def _native_run(tmp_path, monkeypatch):
    """Exercise real native snapshot/normalization/finalization with only KGX export stubbed."""
    from kg_microbe.transform_utils.ontologies import ontologies_transform as module

    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copyfile(FIXTURE, raw / "foodon.json")
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    original_rows = {"nodes": [], "edges": []}

    def kgx(*, inputs, input_format, output, output_format):
        """Emit exact synthetic transport rows to test lossless native boundary auditing."""
        assert input_format == "obojson" and output_format == "tsv"
        declarations = {compact_identifier(node["id"]): node for node in _declarations(_document())}
        for identifier in sorted(IDS | {"FOODON:00002403", "RO:0000086"}):
            original_rows["nodes"].append(
                {
                    "id": identifier,
                    "category": "biolink:Food" if identifier.startswith("FOODON:") else "biolink:NamedThing",
                    "name": declarations[identifier]["lbl"],
                    "provided_by": Path(inputs[0]).name,
                    "raw_node_column": "preserve original exclusion payload",
                }
            )
        original_rows["edges"] = [
            {
                "subject": "FOODON:00001301",
                "predicate": "biolink:related_to",
                "object": "FOODON:00002403",
                "relation": "skos:related",
            },
            {
                "subject": "FOODON:00002403",
                "predicate": "biolink:related_to",
                "object": "http://purl.obolibrary.org/obo/FOODON_00001563",
                "relation": "skos:related",
            },
            {
                "subject": "FOODON:00002403",
                "predicate": "FOODON:00002420",
                "object": "FOODON:00002403",
                "relation": "FOODON:00002420",
            },
            {
                "subject": "FOODON:00002403",
                "predicate": "biolink:related_to",
                "object": "FOODON:00002403",
                "relation": "FOODON:00001301",
            },
        ]
        for index, row in enumerate(original_rows["edges"]):
            row.update({"primary_knowledge_source": "infores:foodon", "raw_edge_column": f"original assertion {index}"})
        for kind, header, extra in (
            ("nodes", transform.node_header, "raw_node_column"),
            ("edges", transform.edge_header, "raw_edge_column"),
        ):
            with Path(str(output) + f"_{kind}.tsv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[*header, extra], delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(original_rows[kind])

    monkeypatch.setattr(module, "_run_kgx_transform", kgx)
    monkeypatch.setattr(
        transform,
        "post_process",
        lambda name: transform._normalize_schema(
            transform.output_dir / f"{name}_nodes.tsv", transform.output_dir / f"{name}_edges.tsv"
        ),
    )
    transform.run(data_file="foodon.json")
    return transform, original_rows


def test_native_schema_nodes_and_endpoint_rows_have_exact_bound_audits(tmp_path, monkeypatch):
    """Only nodes and endpoint use leave the entity graph; relation use and original evidence survive."""
    transform, original = _native_run(tmp_path, monkeypatch)
    nodes, edges = transform.output_dir / "foodon_nodes.tsv", transform.output_dir / "foodon_edges.tsv"
    assert {row["id"] for row in graph_rows(nodes)} == {"FOODON:00002403", "RO:0000086"}
    kept = list(graph_rows(edges))
    assert [(row["predicate"], row["relation"]) for row in kept] == [
        ("FOODON:00002420", "FOODON:00002420"),
        ("biolink:related_to", "FOODON:00001301"),
    ]
    audit = transform.output_dir / "ontology_metadata_exclusions.tsv"
    rows = list(graph_rows(audit, quoting=csv.QUOTE_MINIMAL))
    assert len(rows) == 5
    assert {row["reason"] for row in rows} == {
        "reviewed_foodon_schema_property",
        "reviewed_foodon_schema_property_endpoint",
    }
    identity = transform.consumed_input_snapshots["ontology_metadata_foodon"]
    assert {row["authority_sha256"] for row in rows} == {identity["sha256"]}
    assert identity["sha256"] == hashlib.sha256((transform.input_base_dir / "foodon.json").read_bytes()).hexdigest()
    for row in rows:
        record = json.loads(row["original_record_json"])
        candidates = original[row["kind"]]
        assert any(all(record[key] == value for key, value in candidate.items()) for candidate in candidates)
    before = audit.read_bytes()
    report = transform.finalize(fresh_run=True)
    assert audit.read_bytes() == before
    assert report["producer_audit_members"][audit.name] == transform.producer_audit_snapshots[audit.name]
    curation = report["consumed_inputs"]["foodon_schema_dispositions"]
    assert curation in report["inputs"]
    assert [(row["predicate"], row["relation"]) for row in graph_rows(edges)] == [
        (row["predicate"], row["relation"]) for row in kept
    ]
    verify_finalized_source_files([nodes, edges])


@pytest.mark.parametrize("damage", ["native_authority", "curated_cohort"])
def test_changed_property_exclusion_authority_cannot_be_restamped(tmp_path, monkeypatch, damage):
    """Both native declaration bytes and the finite reviewed cohort are bound before export."""
    from kg_microbe.utils import foodon_classification

    curation = tmp_path / "foodon_model_dispositions.tsv"
    shutil.copyfile(foodon_classification.DISPOSITIONS_FILE, curation)
    monkeypatch.setattr(foodon_classification, "DISPOSITIONS_FILE", curation)
    transform, _ = _native_run(tmp_path, monkeypatch)
    before = {
        name: (transform.output_dir / name).read_bytes()
        for name in ("foodon_nodes.tsv", "foodon_edges.tsv", "ontology_metadata_exclusions.tsv")
    }
    authority = transform.input_base_dir / "foodon.json" if damage == "native_authority" else curation
    authority.write_bytes(authority.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired, match="changed|differ|stale"):
        transform.finalize(fresh_run=True)
    assert all((transform.output_dir / name).read_bytes() == content for name, content in before.items())
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.parametrize("identifier", sorted(IDS))
def test_unreviewed_importer_cannot_silently_retype_or_drop_property(tmp_path, identifier):
    """Shared finalization refuses leaked property entities; only the native bounded route excludes them."""
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copyfile(FIXTURE, raw / "foodon.json")
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.output_node_file.write_text(f"id\tcategory\tname\n{identifier}\tbiolink:Food\tUnreviewed imported node\n")
    transform.output_edge_file.write_text("subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n")
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    with pytest.raises((ValueError, SourceFinalizationRequired), match="live FOODON CLASS|live CLASS"):
        transform.finalize()
    assert (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()) == before
    assert not (transform.output_dir / "source_finalization.json").exists()
