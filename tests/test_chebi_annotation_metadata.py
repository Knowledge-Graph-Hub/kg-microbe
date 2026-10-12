"""Authority-backed annotation exclusion covers native, imported and fallback declarations."""

import csv
import hashlib
import json
import shutil
from pathlib import Path

import ijson
import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.ontology_metadata import annotation_property_ids, metadata_identifier
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

FIXTURE = Path(__file__).parent / "resources/chebi_annotation_metadata.json"
BASE = "http://purl.obolibrary.org/obo/chebi/"
COHORT = {"BRAND_NAME", "INN", "IUPAC_NAME", "1_STAR", "2_STAR", "3_STAR"}


@pytest.mark.parametrize("local", sorted(COHORT))
def test_generic_obo_alias_matches_only_exact_annotation_declaration(local):
    """All six current authority declarations match their KGX-produced CURIEs."""
    nodes = json.loads(FIXTURE.read_text())["graphs"][0]["nodes"]
    assert metadata_identifier("OBO:chebi/" + local) == BASE + local
    assert metadata_identifier("OBO:chebi/" + local) in annotation_property_ids(nodes)
    assert metadata_identifier("OBO:chebi/genuine_class") not in annotation_property_ids(nodes)
    assert metadata_identifier("OBO:unrelated/class") not in annotation_property_ids(nodes)


@pytest.mark.parametrize(
    "kind,property_type", [("CLASS", None), ("INDIVIDUAL", None), ("PROPERTY", "OBJECT"), ("PROPERTY", "DATA")]
)
def test_explicit_semantic_punning_protects_entities_across_graphs(tmp_path, kind, property_type):
    """The annotation-only decision must consider every authority declaration."""
    data = json.loads(FIXTURE.read_text())
    data["graphs"].append({"nodes": [{"id": "OBO:chebi/INN", "type": kind, "propertyType": property_type}]})
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(data))
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform._drop_deprecated_terms(path)
    assert BASE + "INN" not in transform._annotation_property_ids
    assert BASE + "BRAND_NAME" in transform._annotation_property_ids


@pytest.mark.parametrize("source", ["chebi", "uberon"])
def test_native_and_imported_nodes_and_incident_edges_are_audited(tmp_path, source):
    """Both endpoint orientations and metamodel edges retain original evidence; relation metadata remains."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.node_header = ["id", "category", "name"]
    transform.edge_header = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
    original = FIXTURE.read_bytes()
    transform._drop_deprecated_terms(FIXTURE)
    nodes, edges = tmp_path / f"{source}_nodes.tsv", tmp_path / f"{source}_edges.tsv"
    ids = ["OBO:chebi/" + local for local in sorted(COHORT)] + [
        "CHEBI:15377",
        "OBO:chebi/genuine_class",
        "OBO:unrelated/class",
    ]
    pd.DataFrame(
        [[identifier, "biolink:OntologyClass", "retained label"] for identifier in ids], columns=transform.node_header
    ).to_csv(nodes, sep="\t", index=False)
    rows = [
        ["OBO:chebi/BRAND_NAME", "biolink:related_to", "CHEBI:15377", "skos:related", "infores:chebi"],
        ["CHEBI:15377", "biolink:related_to", BASE + "INN", "skos:related", "infores:chebi"],
        ["OBO:chebi/1_STAR", "biolink:type", "CHEBI:15377", "type", "infores:chebi"],
        ["CHEBI:15377", "biolink:related_to", "OBO:chebi/genuine_class", "OBO:chebi/IUPAC_NAME", "infores:chebi"],
    ]
    pd.DataFrame(rows, columns=transform.edge_header).to_csv(edges, sep="\t", index=False)
    transform._normalize_schema(nodes, edges)
    assert {row["id"] for row in graph_rows(nodes)} == set(ids[-3:])
    assert [list(row.values()) for row in graph_rows(edges)] == [rows[-1]]
    audit = list(graph_rows(tmp_path / f"{source}_metadata_exclusions.tsv", quoting=csv.QUOTE_MINIMAL))
    assert len(audit) == 6
    assert {row["id"] for row in audit} == {BASE + local for local in COHORT}
    assert all(json.loads(row["original_record_json"])["name"] == "retained label" for row in audit)
    edge_audit = list(graph_rows(tmp_path / f"{source}_metadata_edge_exclusions.tsv", quoting=csv.QUOTE_MINIMAL))
    assert [tuple(row[column] for column in transform.edge_header) for row in edge_audit] == [
        tuple(row) for row in rows[:-1]
    ]
    assert FIXTURE.read_bytes() == original  # including real term's synonym metadata
    transform._normalize_schema(nodes, edges)
    assert list(graph_rows(tmp_path / f"{source}_metadata_exclusions.tsv")) == []
    assert list(graph_rows(tmp_path / f"{source}_metadata_edge_exclusions.tsv")) == []


def _fallback(tmp_path, authority=True):
    raw = tmp_path / "raw"
    raw.mkdir()
    transform = Transform("fixture", raw, tmp_path / "transformed")
    if authority:
        shutil.copyfile(FIXTURE, raw / "chebi.json")
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "fixture:1\tbiolink:NamedThing\tkeep\tinfores:fixture\n"
        "OBO:chebi/INN\tbiolink:ChemicalEntity\tfall back\tinfores:fixture\n"
        "OBO:chebi/genuine_class\tbiolink:ChemicalEntity\tBRAND NAME\tinfores:fixture\n"
        "OBO:unrelated/class\tbiolink:NamedThing\tkeep\tinfores:fixture\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tsource_assertion_id\n"
        "fixture:1\tbiolink:related_to\tOBO:chebi/INN\tskos:related\tinfores:fixture\tassertion:1\n"
        "http://purl.obolibrary.org/obo/chebi/IUPAC_NAME\tbiolink:related_to\tfixture:1\tskos:related\tinfores:fixture\tassertion:2\n"
        "fixture:1\tbiolink:related_to\tOBO:chebi/genuine_class\tOBO:chebi/IUPAC_NAME\tinfores:fixture\tassertion:3\n"
    )
    return transform


def test_finalization_stops_fallback_and_endpoint_only_reintroduction_with_bound_audit(tmp_path):
    """All source routes use declared authority, never labels or producer fallback categories."""
    transform = _fallback(tmp_path)
    original_authority = (transform.input_base_dir / "chebi.json").read_bytes()
    report = transform.finalize()
    assert {row["id"] for row in graph_rows(transform.output_node_file)} == {
        "fixture:1",
        "OBO:chebi/genuine_class",
        "OBO:unrelated/class",
    }
    rows = list(graph_rows(transform.output_edge_file))
    assert len(rows) == 1 and rows[0]["source_assertion_id"] == "assertion:3"
    assert rows[0]["relation"] == "OBO:chebi/IUPAC_NAME"
    audit_path = transform.output_dir / "source_metadata_exclusions.tsv"
    audit = list(graph_rows(audit_path, quoting=csv.QUOTE_MINIMAL))
    assert len(audit) == 3
    assert report["summaries"]["metadata"] == {"nodes": 1, "edges": 2}
    consumed = report["consumed_inputs"]["source_metadata_chebi"]
    assert {row["authority_sha256"] for row in audit} == {consumed["sha256"]}
    assert {row["authority"] for row in audit} == {consumed["path"]}
    assert any(row["path"] == consumed["path"] for row in report["inputs"])
    assert "source_metadata_exclusions.tsv" in report["audit_members"]
    assert {json.loads(row["original_row_json"]).get("source_assertion_id") for row in audit} == {
        None,
        "assertion:1",
        "assertion:2",
    }
    before = audit_path.read_bytes()
    transform.finalize()
    assert audit_path.read_bytes() == before
    assert (transform.input_base_dir / "chebi.json").read_bytes() == original_authority


@pytest.mark.parametrize("mode", ["missing", "malformed", "empty"])
def test_fallback_authority_failure_never_publishes_partial_results(tmp_path, mode):
    """Unavailable infrastructure is not silently treated as a metadata-free authority."""
    transform = _fallback(tmp_path, authority=False)
    if mode != "missing":
        (transform.input_base_dir / "chebi.json").write_text("{" if mode == "malformed" else '{"graphs": []}')
    original = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    with pytest.raises((FileNotFoundError, ValueError, ijson.JSONError, SourceFinalizationRequired)):
        transform.finalize()
    assert original == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_no_chebi_metadata_candidate_requires_no_authority(tmp_path):
    """An unrelated OBO identifier is not metadata and triggers no new raw dependency."""
    transform = _fallback(tmp_path, authority=False)
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\nOBO:other/1\tbiolink:NamedThing\tkeep\tinfores:fixture\n"
    )
    transform.output_edge_file.write_text("subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n")
    report = transform.finalize()
    assert report["summaries"]["metadata"] == {"nodes": 0, "edges": 0}
    assert "source_metadata_chebi" not in report["consumed_inputs"]


def test_finalizer_preserves_authority_punning_and_full_fields(tmp_path):
    """Conflicting semantic declarations protect real entities, without weakening other exclusions."""
    transform = _fallback(tmp_path)
    authority = transform.input_base_dir / "chebi.json"
    data = json.loads(authority.read_text())
    data["graphs"].append({"nodes": [{"id": "OBO:chebi/INN", "type": "CLASS"}]})
    authority.write_text(json.dumps(data))
    report = transform.finalize()
    nodes = {row["id"]: row for row in graph_rows(transform.output_node_file)}
    assert nodes["OBO:chebi/INN"]["category"] == "biolink:ChemicalEntity"
    assert nodes["OBO:chebi/INN"]["name"] == "fall back"
    assert {row["source_assertion_id"] for row in graph_rows(transform.output_edge_file)} == {
        "assertion:1",
        "assertion:3",
    }
    assert report["summaries"]["metadata"] == {"nodes": 0, "edges": 1}


def test_native_authority_parse_failure_is_not_silently_ignored(tmp_path):
    """Native metadata classification shares the fail-closed infrastructure boundary."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        transform._drop_deprecated_terms(path)
    with pytest.raises(FileNotFoundError):
        transform._drop_deprecated_terms(tmp_path / "missing.json")


def test_changed_selected_authority_invalidates_finalized_output(tmp_path):
    """A later edit cannot restamp the evidence consumed for an exclusion."""
    transform = _fallback(tmp_path)
    transform.finalize()
    authority = transform.input_base_dir / "chebi.json"
    authority.write_text(authority.read_text() + "\n")
    with pytest.raises(SourceFinalizationRequired, match="changed|differ|stale"):
        transform.finalize()


def _native_run(tmp_path, monkeypatch, *, selected="chebi.json", during_parse=None, native_authority=None):
    """Exercise the real native run and normalization with only the KGX reader stubbed."""
    from kg_microbe.transform_utils.ontologies import ontologies_transform as module

    raw = tmp_path / "raw"
    raw.mkdir()
    # This synthetic importer exercises metadata, not the independently pinned
    # UBERON native-RO retention contract. HP is an unprotected importer here.
    for name in ("chebi", "hp"):
        shutil.copyfile(FIXTURE, raw / f"{name}.json")
    if native_authority is not None:
        (raw / "hp.json").write_text(json.dumps(native_authority))
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    monkeypatch.setattr(module, "ONTOLOGIES_MAP", {"chebi": "chebi.json", "hp": "hp.json"})

    def kgx(*, inputs, input_format, output, output_format):
        """Keep original source basename provenance and metadata endpoints."""
        assert input_format == "obojson" and output_format == "tsv"
        assert Path(inputs[0]).parent == raw
        with Path(str(output) + "_nodes.tsv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=transform.node_header, delimiter="\t")
            writer.writeheader()
            for local in sorted(COHORT):
                writer.writerow(
                    {
                        "id": "OBO:chebi/" + local,
                        "category": "biolink:OntologyClass",
                        "name": local,
                        "provided_by": Path(inputs[0]).name,
                    }
                )
            writer.writerow(
                {
                    "id": "CHEBI:15377",
                    "category": "biolink:ChemicalEntity",
                    "name": "water",
                    "provided_by": Path(inputs[0]).name,
                }
            )
        with Path(str(output) + "_edges.tsv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=transform.edge_header, delimiter="\t")
            writer.writeheader()
            writer.writerow(
                {
                    "subject": "OBO:chebi/INN",
                    "predicate": "biolink:related_to",
                    "object": "CHEBI:15377",
                    "relation": "skos:related",
                    "primary_knowledge_source": "infores:chebi",
                }
            )
        if during_parse:
            during_parse(Path(inputs[0]))

    monkeypatch.setattr(module, "_run_kgx_transform", kgx)
    monkeypatch.setattr(
        transform,
        "post_process",
        lambda name: transform._normalize_schema(
            transform.output_dir / f"{name}_nodes.tsv", transform.output_dir / f"{name}_edges.tsv"
        ),
    )
    transform.run(data_file=selected)
    return transform


@pytest.mark.parametrize("selected,count,names", [("chebi.json", 7, {"chebi"}), (None, 14, {"chebi", "hp"})])
def test_native_aggregate_binds_exact_selected_run_original_rows_and_authorities(
    tmp_path, monkeypatch, selected, count, names
):
    """Single and multi-ontology runs bind complete evidence without stale other-file requirements."""
    transform = _native_run(tmp_path, monkeypatch, selected=selected)
    audit = transform.output_dir / "ontology_metadata_exclusions.tsv"
    original = audit.read_bytes()
    rows = list(graph_rows(audit, quoting=csv.QUOTE_MINIMAL))
    assert len(rows) == count
    assert {row["ontology"] for row in rows} == names
    for row in rows:
        identity = transform.consumed_input_snapshots["ontology_metadata_" + row["ontology"]]
        assert (row["authority"], row["authority_sha256"]) == (identity["path"], identity["sha256"])
        assert row["authority_sha256"] == hashlib.sha256(Path(row["authority"]).read_bytes()).hexdigest()
        record = json.loads(row["original_record_json"])
        if row["kind"] == "nodes":
            assert record["provided_by"] == row["ontology"] + ".json"
        else:
            assert record["subject"] == "OBO:chebi/INN"
    report = transform.finalize(fresh_run=True)
    assert report["audit_members"][audit.name] == transform.producer_audit_snapshots[audit.name]
    assert report["producer_audit_members"] == transform.producer_audit_snapshots
    assert audit.read_bytes() == original
    assert transform.finalize() == report


@pytest.mark.parametrize("damage", ["deleted", "tampered"])
def test_native_aggregate_cannot_be_restamped_at_finalization(tmp_path, monkeypatch, damage):
    """The aggregate is mandatory even though the downstream fallback audit is empty."""
    transform = _native_run(tmp_path, monkeypatch)
    audit = transform.output_dir / "ontology_metadata_exclusions.tsv"
    if damage == "deleted":
        audit.unlink()
    else:
        audit.write_bytes(audit.read_bytes() + b"tampered\n")
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        transform.finalize(fresh_run=True)
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_native_authority_changed_after_parse_cannot_be_restamped(tmp_path, monkeypatch):
    """Finalization checks producer-time JSON bytes, not a newly selected authority hash."""
    transform = _native_run(tmp_path, monkeypatch)
    authority = transform.input_base_dir / "chebi.json"
    authority.write_bytes(authority.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired, match="changed|differ|stale"):
        transform.finalize(fresh_run=True)


def test_native_authority_changed_during_kgx_read_aborts_run(tmp_path, monkeypatch):
    """The original basename does not permit authority drift between snapshot and native read."""

    def change(path):
        """Simulate authority drift during the native parser's read window."""
        path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(SourceFinalizationRequired, match="changed"):
        _native_run(tmp_path, monkeypatch, during_parse=change)
    assert not (tmp_path / "transformed/ontologies/ontology_metadata_exclusions.tsv").exists()


@pytest.mark.parametrize(
    "kind,property_type", [("CLASS", None), ("INDIVIDUAL", None), ("PROPERTY", "OBJECT"), ("PROPERTY", "DATA")]
)
def test_native_semantic_punning_survives_shared_fallback_filter(tmp_path, monkeypatch, kind, property_type):
    """A bound native semantic declaration protects both the node and its incident assertion."""
    data = json.loads(FIXTURE.read_text())
    data["graphs"].append({"nodes": [{"id": "OBO:chebi/INN", "type": kind, "propertyType": property_type}]})
    transform = _native_run(tmp_path, monkeypatch, selected="hp.json", native_authority=data)
    nodes = transform.output_dir / "hp_nodes.tsv"
    edges = transform.output_dir / "hp_edges.tsv"
    assert "OBO:chebi/INN" in {row["id"] for row in graph_rows(nodes)}
    report = transform.finalize(fresh_run=True)
    assert "OBO:chebi/INN" in {row["id"] for row in graph_rows(nodes)}
    assert [row["subject"] for row in graph_rows(edges)] == ["OBO:chebi/INN"]
    assert "ontology_metadata_hp" in report["consumed_inputs"]
    assert "source_metadata_chebi" in report["consumed_inputs"]
    assert report["summaries"]["metadata"] == {"nodes": 0, "edges": 0}


@pytest.mark.parametrize("mode", ["absent", "untyped"])
def test_native_unknown_declarations_do_not_bypass_chebi_fallback(tmp_path, monkeypatch, mode):
    """Only explicit semantics protect a native row; an absent or untyped ID is not evidence."""
    data = json.loads(FIXTURE.read_text())
    data["graphs"][0]["nodes"] = [node for node in data["graphs"][0]["nodes"] if node["id"] != BASE + "INN"]
    if mode == "untyped":
        data["graphs"][0]["nodes"].append({"id": "OBO:chebi/INN", "lbl": "legitimate sounding name"})
    transform = _native_run(tmp_path, monkeypatch, selected="hp.json", native_authority=data)
    nodes = transform.output_dir / "hp_nodes.tsv"
    assert "OBO:chebi/INN" in {row["id"] for row in graph_rows(nodes)}
    report = transform.finalize(fresh_run=True)
    assert "OBO:chebi/INN" not in {row["id"] for row in graph_rows(nodes)}
    assert report["summaries"]["metadata"] == {"nodes": 1, "edges": 1}


@pytest.mark.parametrize("damage", ["missing_binding", "authority_drift"])
def test_native_punning_protection_requires_unchanged_producer_bound_authority(tmp_path, monkeypatch, damage):
    """Neither an unbound native authority nor a changed one may be used for a preservation decision."""
    data = json.loads(FIXTURE.read_text())
    data["graphs"].append({"nodes": [{"id": "OBO:chebi/INN", "type": "CLASS"}]})
    transform = _native_run(tmp_path, monkeypatch, selected="hp.json", native_authority=data)
    if damage == "missing_binding":
        del transform._consumed_input_snapshots["ontology_metadata_hp"]
    else:
        path = transform.input_base_dir / "hp.json"
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired, match="not consumed|changed"):
        transform.finalize(fresh_run=True)
