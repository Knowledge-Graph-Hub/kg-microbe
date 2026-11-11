"""Keep the thirty reviewed source dispositions finite, qualified and lossless (#1847)."""

import io
import json
from collections import Counter

import pytest

from kg_microbe.transform_utils.microbedecoder import faprotax_dispositions as fap
from kg_microbe.transform_utils.microbedecoder import observation_audit
from kg_microbe.utils.source_finalization import verify_finalized_source_files
from tests.microbedecoder_join_fixtures import prepare
from tests.test_microbedecoder_bacdive_join_dispositions import _native_report, _rows, _write

# Independent expected targets from the approved primary-source/native-ontology review.
TARGETS = {
    "chemoheterotrophy": "METPO:1000636",
    "aerobic_chemoheterotrophy": "METPO:1000636",
    "photoautotrophy": "METPO:1000656",
    "oxygenic_photoautotrophy": "METPO:1000656",
    "photosynthetic_cyanobacteria": "METPO:1000656",
    "anoxygenic_photoautotrophy": "METPO:1000656",
    "anoxygenic_photoautotrophy_S_oxidizing": "METPO:1000656",
    "anoxygenic_photoautotrophy_Fe_oxidizing": "METPO:1000656",
    "anoxygenic_photoautotrophy_H2_oxidizing": "METPO:1000656",
    "methylotrophy": "METPO:1000651",
    "photoheterotrophy": "METPO:1000657",
    "aerobic_anoxygenic_phototrophy": "METPO:1000657",
    "plant_pathogen": "METPO:1004003",
    "human_pathogens_all": "METPO:1004004",
    "human_pathogens_meningitis": "METPO:1004004",
    "human_pathogens_septicemia": "METPO:1004004",
    "human_pathogens_gastroenteritis": "METPO:1004004",
    "human_pathogens_pneumonia": "METPO:1004004",
    "human_pathogens_diarrhea": "METPO:1004004",
    "human_pathogens_nosocomia": "METPO:1004004",
}
AUDIT_ONLY = {
    "phototrophy",
    "animal_parasites_or_symbionts",
    "human_associated",
    "intracellular_parasites",
    "mammal_gut",
    "human_gut",
    "invertebrate_parasites",
    "predatory_or_exoparasitic",
    "oil_bioremediation",
    "fish_parasites",
}


def _run(tmp_path, monkeypatch):
    """Run the actual producer with explicit synthetic protocol anchors and all thirty literals."""
    native = {
        "LPSN_ID": "101",
        "BacDive_ID": "",
        "IMG_Genome_ID": "123,456,123",
        fap.COLUMN: ";".join([*sorted(TARGETS), *sorted(AUDIT_ONLY), "chemoheterotrophy"]),
        "Bergey_Type_of_metabolism": "Other",
        "Bergey_Substrates_for_end_products": "Not reported",
    }
    transform, source, _, _, _ = prepare(
        tmp_path, monkeypatch, selected=(), native_cases=[{"native_row": native}], include_bacdive_snapshot=False
    )
    transform.run(source)
    return transform, native


def _replay(transform):
    """Read the complete current outputs from a detached recorded producer report."""
    return fap.verify_recorded(_native_report(transform), transform.output_dir, transform.edge_header)


def test_complete_thirty_dispositions_preserve_source_predictions_and_all_occurrences(tmp_path, monkeypatch):
    """Twenty predicates are qualified predictions; ten unsupported literals remain complete evidence."""
    transform, native = _run(tmp_path, monkeypatch)
    edges = [row for row in _rows(transform.output_edge_file) if row["source_column"] == fap.COLUMN]
    assert len(edges) == 20 and len(set(TARGETS.values())) == 6
    nodes = {row["id"]: row for row in _rows(transform.output_node_file)}
    assert {row["value"]: nodes[row["object"]]["has_attribute_type"] for row in edges} == TARGETS
    assert {(row["predicate"], row["relation"]) for row in edges} == {("biolink:has_attribute", "SIO:000008")}
    assert {(row["knowledge_level"], row["agent_type"], row["primary_knowledge_source"]) for row in edges} == {
        ("prediction", "computational_model", "infores:faprotax")
    }
    assert all(row["subject"] == "lpsn:101" and row["source_record"].endswith("#record=1") for row in edges)
    rows = [
        row for row in _rows(transform.output_dir / observation_audit.AUDIT_FILE) if row["source_column"] == fap.COLUMN
    ]
    assert len(rows) == 31
    assert Counter(json.loads(row["original_claim_json"])["value"] for row in rows)["chemoheterotrophy"] == 2
    for row in rows:
        original, emitted = json.loads(row["original_claim_json"]), json.loads(row["emitted_claim_json"])
        assert json.loads(row["source_cell_json"]) == native[fap.COLUMN]
        assert original["predicate"] == "biolink:has_attribute"
        assert "/issues/1847" in row["evidence_uri"] and "/issues/1850" in row["evidence_uri"]
        assert row["curation_rationale"]
        if original["value"] in AUDIT_ONLY:
            assert emitted is None and row["disposition"] == fap.AUDIT_DISPOSITION
        else:
            assert emitted == original
            assert nodes[emitted["object"]]["has_attribute_type"] == TARGETS[original["value"]]
    attributes = [row for row in nodes.values() if row["id"].startswith("kgmicrobe.source_attribute:")]
    assert len(attributes) == 20
    assert all(row["category"] == "biolink:Attribute" for row in attributes)
    assert all(row["has_attribute_type"] in TARGETS.values() for row in attributes)
    assert not any(row["id"].startswith(("METPO:", "lpsn:")) for row in nodes.values())
    _replay(transform).verify()
    transform.verify_native_inputs()


@pytest.mark.parametrize("mutation", ["lost", "duplicate", "cell", "claim", "unsupported_projection"])
def test_complete_faprotax_audit_replay_refuses_changed_occurrences(tmp_path, monkeypatch, mutation):
    """A changed digest cannot legitimize altered native values, pairing or disposition."""
    transform, _ = _run(tmp_path, monkeypatch)
    path = transform.output_dir / observation_audit.AUDIT_FILE
    rows = _rows(path)
    index = next(i for i, row in enumerate(rows) if row["source_column"] == fap.COLUMN)
    if mutation == "lost":
        rows.pop(index)
    elif mutation == "duplicate":
        rows.append(dict(rows[index]))
    elif mutation == "cell":
        rows[index]["source_cell_json"] = '"invented"'
    elif mutation == "claim":
        claim = json.loads(rows[index]["original_claim_json"])
        claim["knowledge_level"] = "knowledge_assertion"
        rows[index]["original_claim_json"] = fap.encoded(claim)
    else:
        target = next(row for row in rows if row["disposition"] == fap.AUDIT_DISPOSITION)
        target["emitted_claim_json"] = target["original_claim_json"]
    _write(path, rows, observation_audit.AUDIT_FIELDS)
    with pytest.raises(ValueError, match="audit differs"):
        _replay(transform)


@pytest.mark.parametrize(
    "field,value",
    [
        ("knowledge_level", "knowledge_assertion"),
        ("agent_type", "manual_agent"),
        ("object", "METPO:1000682"),
        ("value", "human_associated"),
        ("source_column", "Bergey_Type_of_metabolism"),
    ],
)
def test_faprotax_full_graph_replay_refuses_wrong_biology_or_lost_qualifiers(tmp_path, monkeypatch, field, value):
    """Every complete emitted claim must remain paired with its original reviewed source value."""
    transform, _ = _run(tmp_path, monkeypatch)
    path = transform.output_edge_file
    rows = _rows(path)
    next(row for row in rows if row["source_column"] == fap.COLUMN)[field] = value
    _write(path, rows, transform.edge_header)
    with pytest.raises(ValueError, match="graph differs"):
        _replay(transform)


def test_unknown_or_other_source_labels_do_not_acquire_global_aliases(tmp_path, monkeypatch):
    """The policy is field-specific and retains exact qualifiers instead of guessing synonyms."""
    transform, _ = _run(tmp_path, monkeypatch)
    policy = transform._faprotax_curation
    for column, literal in [
        ("Bergey_Type_of_metabolism", "photoautotrophy"),
        (fap.COLUMN, "Photoautotrophy"),
        (fap.COLUMN, "unknown_process"),
    ]:
        assert policy.resolve(column, literal) is None


def test_wrong_native_target_label_is_refused_before_output(tmp_path, monkeypatch):
    """A valid-shaped CURIE with the wrong native meaning cannot pass label matching."""
    transform, _ = _run(tmp_path, monkeypatch)
    authority = (transform.output_dir.parent / "ontologies/metpo_nodes.tsv").read_text()
    with fap.DEFAULT_DISPOSITIONS.open() as policy, pytest.raises(ValueError, match="target label/category"):
        fap.FaprotaxDispositions(policy, io.StringIO(authority.replace("methylotrophic", "invented")))


def test_registered_finalization_and_merge_admission_preserve_img_and_prediction_rows(
    tmp_path, monkeypatch, local_source_schema
):
    """Use real source finalization and merge admission, retaining both declared IMG genomes."""
    transform, _ = _run(tmp_path, monkeypatch)
    before = _rows(transform.output_edge_file)
    report = transform.finalize(fresh_run=True)
    assert report["producer_native_inputs"][fap.CONTRACT_KEY]["source_observations"] == 31
    assert report["producer_native_inputs"][fap.CONTRACT_KEY]["audit_only_observations"] == 10
    assert Counter(tuple(sorted(row.items())) for row in before) == Counter(
        tuple(sorted(row.items())) for row in _rows(transform.output_edge_file)
    )
    genomes = {row["id"]: row for row in _rows(transform.output_node_file) if row["id"].startswith("IMG:")}
    assert set(genomes) == {"IMG:123", "IMG:456"}
    assert all(row["category"] == "biolink:Genome" for row in genomes.values())
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "biolink:PhenotypicFeature"),
        ("has_attribute_type", "METPO:1000682"),
        ("name", "invented phenotype"),
        ("attribute_type_evidence", ""),
        ("attribute_type_rationale", "invented"),
        ("provided_by", "infores:other"),
    ],
)
def test_native_attribute_declaration_tampering_is_refused(tmp_path, monkeypatch, field, value):
    """Original edges cannot conceal retyped, invented or ungrounded Attribute nodes."""
    transform, _ = _run(tmp_path, monkeypatch)
    path = transform.output_node_file
    rows = _rows(path)
    next(row for row in rows if row["category"] == "biolink:Attribute")[field] = value
    _write(path, rows, transform.node_header)
    with pytest.raises(ValueError, match="Attribute typing differs"):
        _replay(transform)


def test_actual_attribute_endpoints_fit_pinned_biolink_without_retyping(tmp_path, monkeypatch):
    """Check actual emitted categories and forbid the discarded direct phenotype signature (#1850)."""
    from pathlib import Path

    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    transform, _ = _run(tmp_path, monkeypatch)
    schema = Path(__file__).parent / "resources/microbedecoder/biolink-4.4.2-attributes.yaml"
    toolkit = Toolkit(schema=str(schema))
    taxon = next(
        row for row in _rows(transform.output_dir.parent / "ontologies/fixture_nodes.tsv") if row["id"] == "lpsn:101"
    )
    assert taxon["category"] == "biolink:OrganismTaxon"
    attribute = toolkit.get_element("has attribute")
    slot = toolkit.get_element("has attribute type")
    assert taxon["category"] in toolkit.get_descendants(attribute.domain, formatted=True, reflexive=True)
    nodes = {row["id"]: row for row in _rows(transform.output_node_file)}
    authorities = {row["id"]: row for row in _rows(transform.output_dir.parent / "ontologies/metpo_nodes.tsv")}
    for row in _rows(transform.output_edge_file):
        if row["source_column"] != fap.COLUMN:
            continue
        node = nodes[row["object"]]
        assert node["category"] in toolkit.get_descendants(attribute.range, formatted=True, reflexive=True)
        assert node["category"] in toolkit.get_descendants(slot.domain, formatted=True, reflexive=True)
        assert authorities[node["has_attribute_type"]]["category"] == "biolink:OntologyClass"
        assert slot.range == "ontology class" and slot.multivalued is False
    phenotype = toolkit.get_element("has phenotype")
    assert taxon["category"] not in toolkit.get_descendants(phenotype.domain, formatted=True, reflexive=True)
    assert "biolink:OntologyClass" not in toolkit.get_descendants(phenotype.range, formatted=True, reflexive=True)
    assert not any(
        row["predicate"] in {"biolink:has_phenotype", "biolink:has_attribute_type"}
        for row in _rows(transform.output_edge_file)
    )


@pytest.mark.parametrize("literal", ["chemoheterotrophy", "human_associated"])
def test_extra_foreign_column_claim_to_protected_attribute_is_refused(tmp_path, monkeypatch, literal):
    """Extra assertions cannot hide beside the genuine edge or revive audit-only labels (#1853)."""
    transform, _ = _run(tmp_path, monkeypatch)
    audit = next(
        row
        for row in _rows(transform.output_dir / observation_audit.AUDIT_FILE)
        if row["source_column"] == fap.COLUMN and json.loads(row["original_claim_json"])["value"] == literal
    )
    forged = json.loads(audit["original_claim_json"])
    assert forged["object"] == observation_audit.source_attribute_curie(fap.COLUMN, literal)
    original = _rows(transform.output_edge_file)
    genuine = [row for row in original if row["source_column"] == fap.COLUMN and row["value"] == literal]
    assert len(genuine) == (1 if literal in TARGETS else 0)
    if literal in AUDIT_ONLY:
        assert audit["emitted_claim_json"] == "null"
    forged["source_column"] = "Bergey_Type_of_metabolism"
    _write(transform.output_edge_file, [*original, forged], transform.edge_header)
    # The complete genuine original cohort remains; failure must concern the added assertion.
    assert _rows(transform.output_edge_file)[:-1] == original
    with pytest.raises(ValueError, match="graph differs"):
        _replay(transform)


def test_actual_kgx_merge_preserves_declared_img_genomes(tmp_path, monkeypatch, local_source_schema):
    """Merge genuine tiny producer TSVs and inspect the published archive, not only source admission."""
    import csv
    import tarfile
    from multiprocessing.pool import ThreadPool

    import yaml

    from kg_microbe.merge_utils import kgx_source, merge_kg
    from kg_microbe.utils.biolink_model import prepare_kgx

    transform, _ = _run(tmp_path / "producer", monkeypatch)
    transform.finalize(fresh_run=True)
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    audit_path = transform.output_dir / observation_audit.AUDIT_FILE
    audit_before = audit_path.read_bytes()
    prepare_kgx()
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    output = tmp_path / "merged"
    config = {
        # This test exercises real KGX ingestion/export, not a dispatcher-complete release.
        # The source above is genuinely finalized; its synthetic siblings have no CLI markers.
        "configuration": {"output_directory": str(output), "allow_unfinalized_sources": True},
        "merged_graph": {
            "source": {
                "microbedecoder": {
                    "input": {
                        "format": "tsv",
                        "filename": [str(transform.output_node_file), str(transform.output_edge_file)],
                    }
                }
            },
            "destination": {"release": {"format": "tsv", "filename": "tiny", "compression": "tar.gz"}},
        },
    }
    config_path = tmp_path / "merge.yaml"
    config_path.write_text(yaml.safe_dump(config))
    with kgx_source.local_prefix_context():
        merge_kg.load_and_merge(str(config_path), processes=1)
    with tarfile.open(output / "tiny.tar.gz") as archive:
        nodes = list(csv.DictReader(io.StringIO(archive.extractfile("tiny_nodes.tsv").read().decode()), delimiter="\t"))
        edges = list(csv.DictReader(io.StringIO(archive.extractfile("tiny_edges.tsv").read().decode()), delimiter="\t"))
    genomes = {row["id"]: row for row in nodes if row["id"].startswith("IMG:")}
    assert set(genomes) == {"IMG:123", "IMG:456"}
    assert all(row["category"] == "biolink:Genome" for row in genomes.values())
    assert all(row["provided_by"] == "infores:microbedecoder" for row in genomes.values())
    memberships = [row for row in edges if row["subject"].startswith("IMG:")]
    assert len(memberships) == 2
    assert {(row["subject"], row["predicate"], row["relation"], row["object"]) for row in memberships} == {
        (genome, "biolink:in_taxon", "RO:0002162", "lpsn:101") for genome in genomes
    }
    for field in ("primary_knowledge_source", "knowledge_level", "agent_type", "source_column", "source_record"):
        expected = {row[field] for row in _rows(transform.output_edge_file) if row["subject"].startswith("IMG:")}
        assert {row[field] for row in memberships} == expected
    assert audit_path.read_bytes() == audit_before
