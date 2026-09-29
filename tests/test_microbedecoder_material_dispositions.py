"""Keep finite material review separate from chemical identities and graph mutations."""

import csv
import hashlib
import io
from collections import Counter
from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder.chemical_curation import canonical_raw_row_sha256
from kg_microbe.transform_utils.microbedecoder.material_dispositions import (
    DEFAULT_MATERIAL_DISPOSITIONS,
    MaterialDisposition,
    MaterialDispositionCuration,
)

RAW = Path(__file__).parent / "resources/microbedecoder/material_dispositions.csv"


def table(rows):
    """Serialize a tiny complete-schema curated table without touching production files."""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=[field.name for field in fields(MaterialDisposition)], delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return stream


def reviewed_rows(raw=RAW):
    """Bind immutable synthetic records using the same byte and complete-record contracts."""
    original = MaterialDispositionCuration()
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    with raw.open(newline="") as stream:
        records = list(csv.DictReader(stream))
    rows = []
    for ordinal, record in enumerate(records, start=1):
        rule = next(
            rule for rule in original.rules if rule.source_literal == record["Bergey_Substrates_for_end_products"]
        )
        row = asdict(rule)
        row.update(
            source_record=f"sha256:{sha}#record={ordinal}",
            raw_record_sha256=canonical_raw_row_sha256(record),
            subject=f"lpsn:{ordinal}",
            source_citation=record["Bergey_Article_link"],
        )
        rows.append(row)
    return rows


def edge(row):
    """Construct the full original scientific edge witness without curation metadata."""
    names = {
        "source_record",
        "subject",
        "source_column",
        "source_citation",
        "predicate",
        "relation",
        "primary_knowledge_source",
        "knowledge_level",
        "agent_type",
        "value_encoding",
    }
    return {**{name: row[name] for name in names}, "value": row["source_literal"], "object": row["object_curie"]}


def edges_file(tmp_path, rows):
    """Write an isolated finalized-source-shaped edge fixture."""
    path = tmp_path / "edges.tsv"
    keys = list(edge(reviewed_rows()[0]))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_complete_canonical_cohort_is_finite_unresolved_and_keeps_two_sugars():
    """Disposition completion is not chemical grounding or new organism-level evidence."""
    curation = MaterialDispositionCuration()
    assert len(curation.rules) == 240
    assert len({rule.source_record for rule in curation.rules}) == 235
    assert len({rule.object_curie for rule in curation.rules}) == 13
    assert all(rule.identity_status == "unresolved" and rule.identity_approved == "false" for rule in curation.rules)
    assert curation.source_sha256 == "0c6ff730a108720a5d6972400f2bccf2eca8621713b62736abdf5df0fb188c95"
    assert Counter(rule.disposition for rule in curation.rules) == {
        "unresolved_product_identity": 2,
        "reported_combined_culture_context": 1,
        "reported_joint_substrate_condition": 101,
        "reported_culture_medium": 114,
        "reviewed_source_culture_medium": 3,
        "unresolved_substrate_identity_taxon_caveat": 1,
        "reported_substrate_class_group": 1,
        "reported_undefined_protein_digest": 2,
        "approved_record_scoped_unresolved": 2,
        "reported_substrate_class_plural": 13,
    }
    sugars = [rule for rule in curation.rules if rule.source_literal == "sugar"]
    assert len(sugars) == 2
    assert {rule.source_record.rsplit("=", 1)[1] for rule in sugars} == {"1200", "6810"}
    assert {rule.object_curie for rule in sugars} == {
        "kgmicrobe.compound:microbedecoder_unresolved_26e1775f721e16c42822b09a5ccf52e5e4e16485be4484cd446043b4ad1112ce",
        "kgmicrobe.compound:microbedecoder_unresolved_e70afedebc63b126613fa7f69e55fcb21b4c504a87bb1c495f57f34a7bb811b2",
    }
    with pytest.raises(FrozenInstanceError):
        sugars[0].identity_approved = "true"


def test_exact_edge_resolution_is_nonmutating_and_preserves_roles():
    """The catalogue describes original nodes and edges, never substitutes a target."""
    curation = MaterialDispositionCuration()
    for rule in curation.rules:
        witness = edge(asdict(rule))
        before = dict(witness)
        assert curation.resolve_edge(witness) == rule
        assert witness == before


@pytest.mark.parametrize(
    "field",
    [
        "subject",
        "object",
        "source_citation",
        "predicate",
        "relation",
        "primary_knowledge_source",
        "knowledge_level",
        "agent_type",
        "value_encoding",
    ],
)
@pytest.mark.parametrize("value", ["", "changed"])
def test_known_source_use_rejects_changed_scientific_witness(field, value):
    """Correct literal spelling cannot mask citation, target, role or evidence drift."""
    curation = MaterialDispositionCuration()
    witness = edge(asdict(curation.rules[0]))
    witness[field] = value
    with pytest.raises(ValueError, match="source-use evidence changed"):
        curation.resolve_edge(witness)


@pytest.mark.parametrize("field", ["source_record", "source_column", "value"])
def test_unseen_scope_is_not_a_global_alias_or_a_transform_blocker(field):
    """Other snapshots, records, fields and spellings remain unreviewed by this catalogue."""
    curation = MaterialDispositionCuration()
    witness = edge(asdict(curation.rules[0]))
    witness[field] = "unreviewed"
    assert curation.resolve_edge(witness) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_record", "sha256:any#record=*"),
        ("raw_record_sha256", "bad"),
        ("subject", "NCBITaxon:1"),
        ("object_curie", "NCIT:C71939"),
        ("source_column", "BacDive_Motility"),
        ("predicate", "biolink:has_attribute"),
        ("relation", "RO:0002234"),
        ("primary_knowledge_source", "infores:bacdive"),
        ("knowledge_level", "prediction"),
        ("agent_type", "computational_model"),
        ("value_encoding", "none"),
        ("identity_status", "resolved"),
        ("identity_approved", "true"),
        ("disposition", "exactMatch"),
        ("evidence_uri", "http://example.org"),
        ("evidence_uri", "https://user:secret@example.org"),
        ("evidence_uri", "https:///missing"),
        ("curation_rationale", ""),
        ("source_literal", " H2+CO2"),
    ],
)
def test_unreviewed_or_incompatible_mapping_rows_fail_closed(field, value):
    """No malformed table row can silently turn review metadata into scientific facts."""
    rows = reviewed_rows()
    rows[0][field] = value
    with pytest.raises(ValueError):
        MaterialDispositionCuration(table(rows))


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "conflicting_hash",
        "mixed_snapshots",
        "empty",
        "short",
        "long",
        "duplicate_header",
        "missing_header",
    ],
)
def test_malformed_or_conflicting_catalogues_abort(kind):
    """Duplicate scopes and inconsistent record identities cannot choose a winner by row order."""
    rows = reviewed_rows()
    if kind == "duplicate":
        rows.append(dict(rows[0]))
    elif kind == "conflicting_hash":
        other = {**rows[0], "source_literal": "another", "raw_record_sha256": "0" * 64}
        rows.append(other)
    elif kind == "mixed_snapshots":
        rows[1]["source_record"] = "sha256:" + "0" * 64 + "#record=2"
    elif kind == "empty":
        rows = []
    stream = table(rows)
    lines = stream.getvalue().splitlines()
    if kind == "short":
        lines[1] = lines[1].rsplit("\t", 1)[0]
    elif kind == "long":
        lines[1] += "\textra"
    elif kind == "duplicate_header":
        names = lines[0].split("\t")
        names[-1] = names[0]
        lines[0] = "\t".join(names)
    elif kind == "missing_header":
        lines[0] = lines[0].rsplit("\t", 1)[0]
    with pytest.raises(ValueError):
        MaterialDispositionCuration(io.StringIO("\n".join(lines)))


def test_raw_validation_binds_complete_records_and_preserves_caller_stream():
    """Record hashes verify all fields independently of the ordinal's source-byte anchor."""
    stream = table(reviewed_rows())
    curation = MaterialDispositionCuration(stream)
    assert not stream.closed
    assert curation.validate_raw(RAW) == {
        "source_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
        "raw_records": 2,
        "reviewed_uses": 2,
    }
    rows = reviewed_rows()
    rows[0]["raw_record_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="complete material raw record changed"):
        MaterialDispositionCuration(table(rows)).validate_raw(RAW)


@pytest.mark.parametrize("change", ["citation", "literal", "ordinal", "snapshot"])
def test_raw_validation_detects_false_record_pins(change):
    """An asserted snapshot hash does not bypass literal, citation or full-record checks."""
    rows = reviewed_rows()
    if change == "citation":
        rows[0]["source_citation"] += "changed"
    elif change == "literal":
        rows[0]["source_literal"] = "unknown"
    elif change == "ordinal":
        rows[0]["source_record"] = rows[0]["source_record"].rsplit("=", 1)[0] + "=99"
    else:
        for row in rows:
            row["source_record"] = row["source_record"].replace(hashlib.sha256(RAW.read_bytes()).hexdigest(), "0" * 64)
    with pytest.raises(ValueError):
        MaterialDispositionCuration(table(rows)).validate_raw(RAW)


def test_edge_cohort_complete_partial_duplicate_and_unseen_snapshot(tmp_path):
    """Closed cohort coverage is explicit; partial fixtures and newer snapshots can stay unreviewed."""
    rows = reviewed_rows()
    curation = MaterialDispositionCuration(table(rows))
    path = edges_file(tmp_path, [edge(row) for row in rows])
    summary = curation.validate_edges(path)
    assert summary["reviewed_material_assertions"] == summary["reviewed_material_records"] == 2
    assert summary["cohort_complete"] and summary["source_snapshot_seen"]
    path = edges_file(tmp_path, [edge(rows[0])])
    assert curation.validate_edges(path, require_all=False)["missing_reviewed_uses"] == 1
    with pytest.raises(ValueError, match="Incomplete reviewed material cohort"):
        curation.validate_edges(path)
    path = edges_file(tmp_path, [edge(rows[0]), edge(rows[0])])
    with pytest.raises(ValueError, match="Duplicate reviewed material source assertion"):
        curation.validate_edges(path)
    future = edge(rows[0])
    future["source_record"] = "sha256:" + "0" * 64 + "#record=1"
    path = edges_file(tmp_path, [future])
    summary = curation.validate_edges(path, require_all=False)
    assert summary["reviewed_material_assertions"] == 0
    assert not summary["source_snapshot_seen"] and not summary["cohort_complete"]


def test_canonical_catalogue_is_not_an_external_ontology_mapping():
    """The literal table has no exact-match target or producer mutation field."""
    with DEFAULT_MATERIAL_DISPOSITIONS.open() as stream:
        header = csv.DictReader(stream, delimiter="\t").fieldnames
    assert "target_curie" not in header
    assert "same_as" not in header


@pytest.mark.parametrize("mode", ["raw", "edges"])
def test_diagnostic_input_drift_fails_closed(tmp_path, monkeypatch, mode):
    """Before/after hashes reject changed diagnostic inputs instead of certifying mixed bytes."""
    from kg_microbe.transform_utils.microbedecoder import material_dispositions as module

    rows = reviewed_rows()
    curation = MaterialDispositionCuration(table(rows))
    actual_hash = module._sha256
    calls = 0

    def drift(path):
        """Simulate a changed second read without modifying any real input bytes."""
        nonlocal calls
        calls += 1
        return actual_hash(path) if calls == 1 else "0" * 64

    monkeypatch.setattr(module, "_sha256", drift)
    with pytest.raises(ValueError, match="changed"):
        if mode == "raw":
            curation.validate_raw(RAW)
        else:
            curation.validate_edges(edges_file(tmp_path, [edge(row) for row in rows]))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "short", "long"])
def test_malformed_diagnostic_edges_are_not_partial_success(tmp_path, kind):
    """Schema and ragged-row errors abort even when full-cohort coverage is optional."""
    rows = reviewed_rows()
    curation = MaterialDispositionCuration(table(rows))
    path = edges_file(tmp_path, [edge(rows[0])])
    lines = path.read_text().splitlines()
    if kind == "missing":
        lines[0] = lines[0].replace("source_citation", "unknown_field")
    elif kind == "duplicate":
        keys = lines[0].split("\t")
        keys[-1] = keys[0]
        lines[0] = "\t".join(keys)
    elif kind == "short":
        lines[1] = lines[1].rsplit("\t", 1)[0]
    else:
        lines[1] += "\textra"
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        curation.validate_edges(path, require_all=False)
