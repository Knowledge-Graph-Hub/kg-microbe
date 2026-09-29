"""Exercise scoped #650 curation through real source emission and read-time guards."""

import csv
import json
import shutil
from collections import Counter

import pytest

from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import DEFAULT_PHENOTYPE_MAPPINGS
from kg_microbe.transform_utils.microbedecoder.process_scopes import DEFAULT_PROCESS_SCOPE_DEFINITIONS
from kg_microbe.transform_utils.microbedecoder.source_annotations import REPORTED_METABOLISM_ANNOTATIONS
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_transform import FIXTURE_DIR, _NoChebi, _supply_gold_fold_report


def _rows(path):
    """Read the tiny test output as literal TSV."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _transform(tmp_path):
    """Supply explicit immutable dependencies, with mutable private copies for drift tests."""
    _supply_gold_fold_report(tmp_path)
    mapping = tmp_path / "process.tsv"
    shutil.copyfile(DEFAULT_PROCESS_MAPPINGS, mapping)
    phenotypes = tmp_path / "phenotypes.tsv"
    shutil.copyfile(DEFAULT_PHENOTYPE_MAPPINGS, phenotypes)
    scopes = tmp_path / "process_scopes.tsv"
    shutil.copyfile(DEFAULT_PROCESS_SCOPE_DEFINITIONS, scopes)
    return MicrobeDecoderTransform(
        FIXTURE_DIR,
        tmp_path,
        chemical_loader=_NoChebi(),
        process_mappings=mapping,
        phenotype_mappings=phenotypes,
        process_scopes=scopes,
    )


def _write_source(tmp_path, records):
    """Write a small explicit source CSV without importing any live records."""
    path = tmp_path / "source.csv"
    fields = list(dict.fromkeys(key for row in records for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return path


def test_real_mapping_retains_source_evidence_and_has_no_ontology_stubs(tmp_path):
    """Mapped and fallback assertions preserve distinct evidence tiers and complete contexts."""
    transform = _transform(tmp_path)
    bind_fixture_quarantine_policy(transform, FIXTURE_DIR / "faprotax_evidence.csv")
    transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv")
    rows = _rows(transform.output_edge_file)
    mapped = [row for row in rows if row["object"] == "METPO:1002005"]
    assert len(mapped) == 8
    assert Counter(row["primary_knowledge_source"] for row in mapped) == {
        "infores:faprotax": 2,
        "infores:bergey-manual": 2,
        "infores:vpi-anaerobe-manual": 2,
        "infores:microbedecoder-literature": 2,
    }
    assert all(row["source_record"].startswith("sha256:") for row in mapped)
    assert all(row["source_column"] and row["value"] and row["value_encoding"] == "backslash" for row in mapped)
    assert len({row["source_record"] for row in mapped}) == 2
    assert not any(row["id"].startswith("METPO:") for row in _rows(transform.output_node_file))
    assert all(row["label"] != "fermentation" for row in _rows(transform.output_dir / "unmapped_labels.tsv"))
    assert set(transform.consumed_input_snapshots) == {
        "process_mappings",
        "process_authority",
        "process_go_authority",
        "phenotype_mappings",
        "process_scope_definitions",
        "chemical_authority",
        "crosswalk_raw",
        "crosswalk_policy",
        "crosswalk_decisions",
        "crosswalk_evidence",
    }


def test_missing_report_is_preserved_without_a_chemical_or_negative_assertion(tmp_path):
    """Only the exact reviewed Bergey substrate token becomes a missing-report attribute."""
    transform = _transform(tmp_path)
    source = tmp_path / "missing.csv"
    records = [
        {"LPSN_ID": "101", "Bergey_Substrates_for_end_products": "Not reported", "Bergey_Article_link": "doi:10.1/a"},
        {"LPSN_ID": "102", "Bergey_Substrates_for_end_products": "not reported", "Bergey_Article_link": "doi:10.1/b"},
        {"LPSN_ID": "103", "Literature_Substrates_for_end_products": "Not reported"},
    ]
    fields = list(dict.fromkeys(key for row in records for key in row))
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    rows = {row["subject"]: row for row in _rows(transform.output_edge_file)}
    note = rows["lpsn:101"]
    assert note["predicate"] == "biolink:has_attribute"
    assert note["relation"] == "SIO:000008"
    assert note["object"].startswith("kgmicrobe.source_attribute:")
    assert note["source_column"] == "Bergey_Substrates_for_end_products"
    assert note["value"] == "Not reported"
    assert note["source_citation"] == "doi:10.1/a"
    assert note["primary_knowledge_source"] == "infores:bergey-manual"
    assert note["knowledge_level"] == "knowledge_assertion"
    nodes = {row["id"]: row for row in _rows(transform.output_node_file)}
    assert nodes[note["object"]]["category"] == "biolink:Attribute"
    assert rows["lpsn:102"]["predicate"] == rows["lpsn:103"]["predicate"] == "biolink:consumes"
    assert not any("not_capable" in row["predicate"] for row in rows.values())


@pytest.mark.parametrize(
    "name",
    [
        "process_mappings",
        "process_authority",
        "process_go_authority",
        "phenotype_mappings",
        "process_scope_definitions",
        "chemical_authority",
    ],
)
def test_actual_consumed_curation_drift_is_rejected(tmp_path, name):
    """A successful producer read cannot be certified after either dependency changes."""
    transform = _transform(tmp_path)
    bind_fixture_quarantine_policy(transform, FIXTURE_DIR / "faprotax_evidence.csv")
    transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv")
    target = {
        "process_mappings": transform.process_mappings,
        "phenotype_mappings": transform.phenotype_mappings,
        "process_scope_definitions": transform.process_scopes,
        "process_authority": tmp_path / "ontologies/metpo_nodes.tsv",
        "process_go_authority": tmp_path / "ontologies/go_nodes.tsv",
        "chemical_authority": tmp_path / "ontologies/chebi_nodes.tsv",
    }[name]
    with target.open("a") as stream:
        stream.write("\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        transform.verify_consumed_inputs()


def test_missing_authority_fails_before_overwriting_graph_and_rerun_reloads(tmp_path):
    """Never cache past an authority change or publish invented target declarations."""
    transform = _transform(tmp_path)
    bind_fixture_quarantine_policy(transform, FIXTURE_DIR / "faprotax_evidence.csv")
    transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv")
    before = transform.output_edge_file.read_bytes()
    authority = tmp_path / "ontologies/metpo_nodes.tsv"
    authority.write_text("id\tname\tcategory\tdeprecated\n")
    with pytest.raises(ValueError, match="Missing authoritative"):
        bind_fixture_quarantine_policy(transform, FIXTURE_DIR / "faprotax_evidence.csv")
        transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv")
    assert transform.output_edge_file.read_bytes() == before
    shutil.copyfile(FIXTURE_DIR / "metpo_nodes.tsv", authority)
    bind_fixture_quarantine_policy(transform, FIXTURE_DIR / "faprotax_evidence.csv")
    transform.run(data_file=FIXTURE_DIR / "faprotax_evidence.csv")
    assert transform.output_edge_file.read_bytes() == before


def test_reported_phenotype_groundings_preserve_originals_and_do_not_emit_invalid_edges(tmp_path):
    """Review exact text without new schema-invalid edges or collapsing positive and negative."""
    transform = _transform(tmp_path)
    source = _write_source(
        tmp_path,
        [
            {
                "LPSN_ID": "101",
                "BacDive_Gram_stain": "positive; negative; variable",
                "BacDive_Cell_shape": "rod-shaped; other",
                "BacDive_Motility": "0; 1",
                "BacDive_Indole_test": "+; -",
            },
            {"LPSN_ID": "102", "BacDive_Gram_stain": "Positive", "BacDive_Cell_shape": "0"},
        ],
    )
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    edges = _rows(transform.output_edge_file)
    attributes = [row for row in edges if row["predicate"] == "biolink:has_attribute"]
    phenotypes = _rows(transform.output_dir / "phenotype_normalizations.tsv")
    assert len(attributes) == 11
    assert len(phenotypes) == 8
    assert len(edges) == 11
    assert not any(row["predicate"] == "biolink:has_phenotype" for row in edges)
    for phenotype in phenotypes:
        original = [
            row
            for row in attributes
            if all(
                row[key] == phenotype[key]
                for key in (
                    "subject",
                    "source_record",
                    "source_column",
                    "value",
                )
            )
        ]
        assert len(original) == 1
        for key in ("primary_knowledge_source", "knowledge_level", "agent_type", "value_encoding"):
            assert phenotype[key] == original[0][key]
        assert phenotype["disposition"] == "reviewed_literal_grounding_not_graph_assertion"
        assert phenotype["evidence_uri"].startswith("https:")
    assert {row["target_curie"] for row in phenotypes if row["source_column"] == "BacDive_Gram_stain"} == {
        "METPO:1000698",
        "METPO:1000699",
        "METPO:1000700",
    }
    assert not any(row["id"].startswith("METPO:") for row in _rows(transform.output_node_file))


def test_rerun_clears_phenotype_report_and_never_caches_previous_observations(tmp_path):
    """An empty later cohort writes a new header-only report, not prior reviewed rows."""
    transform = _transform(tmp_path)
    source = _write_source(tmp_path, [{"LPSN_ID": "101", "BacDive_Gram_stain": "positive"}])
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    assert len(_rows(transform.output_dir / "phenotype_normalizations.tsv")) == 1
    source = _write_source(tmp_path, [{"LPSN_ID": "101", "BacDive_Gram_stain": "Positive"}])
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    assert _rows(transform.output_dir / "phenotype_normalizations.tsv") == []


@pytest.mark.parametrize("column,literal", sorted(REPORTED_METABOLISM_ANNOTATIONS))
def test_reported_group_disposition_never_fabricates_a_process(tmp_path, column, literal):
    """Finite field-scoped annotations preserve provenance and do not become habitat/infection claims."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", column: literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    rows = _rows(transform.output_edge_file)
    assert len(rows) == 1
    row = rows[0]
    assert (row["predicate"], row["relation"]) == ("biolink:has_attribute", "SIO:000008")
    assert row["object"].startswith("kgmicrobe.source_attribute:")
    assert (row["source_column"], row["value"]) == (column, literal)
    predicted = column.startswith("FAPROTAX_")
    assert (row["knowledge_level"], row["agent_type"]) == (
        ("prediction", "computational_model") if predicted else ("knowledge_assertion", "manual_agent")
    )
    assert _rows(transform.output_node_file)[0]["category"] == "biolink:Attribute"


def test_annotation_routes_are_case_and_column_specific(tmp_path):
    """No broad name heuristic or inferred missing-report status is introduced."""
    transform = _transform(tmp_path)
    source = _write_source(
        tmp_path,
        [
            {"LPSN_ID": "101", "Bergey_Type_of_metabolism": "other"},
            {"LPSN_ID": "102", "Literature_Type_of_metabolism": "Other"},
            {"LPSN_ID": "103", "FAPROTAX_Type_of_metabolism": "knallgas_bacteria"},
        ],
    )
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    assert all(row["predicate"] == "biolink:capable_of" for row in _rows(transform.output_edge_file))


def test_reviewed_tartrate_record_keeps_source_spelling_and_does_not_mint_old_stub(tmp_path):
    """Bind the complete immutable record rather than adding a global typo alias."""
    transform = _transform(tmp_path)
    record = json.loads((FIXTURE_DIR / "bergey_tartate_record.json").read_text())
    quarantine_source = _write_source(tmp_path, [record])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    matches = [
        row for row in _rows(transform.output_edge_file) if row["source_column"] == "Bergey_Substrates_for_end_products"
    ]
    assert len(matches) == 1
    row = matches[0]
    assert (row["object"], row["original_object"], row["value"]) == (
        "CHEBI:132950",
        "kgmicrobe.compound:tartate",
        "tartate",
    )
    assert row["source_citation"] == record["Bergey_Article_link"]
    assert row["predicate"] == "biolink:consumes"
    assert not any(
        node["id"] in {"CHEBI:132950", "kgmicrobe.compound:tartate"} for node in _rows(transform.output_node_file)
    )


@pytest.mark.parametrize("missing", ["", "NA", None])
def test_known_tartrate_record_cannot_bypass_admission_by_empty_substrate(tmp_path, missing):
    """Validate the known record before any source-role/empty-token filtering."""
    transform = _transform(tmp_path)
    record = json.loads((FIXTURE_DIR / "bergey_tartate_record.json").read_text())
    record["Bergey_Substrates_for_end_products"] = missing
    with pytest.raises(ValueError, match="tartrate record/field evidence changed"):
        quarantine_source = _write_source(tmp_path, [record])
        bind_fixture_quarantine_policy(transform, quarantine_source)
        transform.run(data_file=quarantine_source)


@pytest.mark.parametrize("identifier", ["777027 ", " 777027", "\t777027"])
def test_known_tartrate_id_normalization_cannot_bypass_evidence_guard(tmp_path, identifier):
    """Identify guarded records as the producer does, but admit only exact original evidence."""
    transform = _transform(tmp_path)
    record = json.loads((FIXTURE_DIR / "bergey_tartate_record.json").read_text())
    record["LPSN_ID"] = identifier
    with pytest.raises(ValueError, match="tartrate record/field evidence changed"):
        quarantine_source = _write_source(tmp_path, [record])
        bind_fixture_quarantine_policy(transform, quarantine_source)
        transform.run(data_file=quarantine_source)


@pytest.mark.parametrize(
    "literal,target",
    [
        ("nitrate_denitrification", "GO:0019333"),
        ("ureolysis", "GO:0043419"),
    ],
)
def test_go_process_uses_authority_without_upgrading_prediction(tmp_path, literal, target):
    """Retain raw FAPROTAX evidence while normalizing only reviewed exact process objects."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", "FAPROTAX_Type_of_metabolism": literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    edge = _rows(transform.output_edge_file)[0]
    assert (edge["object"], edge["predicate"], edge["relation"]) == (target, "biolink:capable_of", "RO:0002215")
    assert (edge["knowledge_level"], edge["agent_type"]) == ("prediction", "computational_model")
    assert edge["value"] == literal
    assert not any(row["id"].startswith("GO:") for row in _rows(transform.output_node_file))
