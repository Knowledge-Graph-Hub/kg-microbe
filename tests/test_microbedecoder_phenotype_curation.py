"""Keep report-only phenotype normalization scoped to reviewed explicit text."""

import csv
import io
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    DEFAULT_PHENOTYPE_MAPPINGS,
    PhenotypeCuration,
)

AUTHORITY = Path(__file__).parent / "resources" / "microbedecoder" / "metpo_nodes.tsv"
REVIEWED = {
    "BacDive_Gram_stain": {"positive": "1000698", "negative": "1000699", "variable": "1000700"},
    "BacDive_Cell_shape": {
        "coccus-shaped": "1000668",
        "diplococcus-shaped": "1000671",
        "ellipsoidal": "1000673",
        "ovoid-shaped": "1000677",
        "oval-shaped": "1000678",
        "pleomorphic-shaped": "1000679",
        "ring-shaped": "1000680",
        "rod-shaped": "1000681",
        "star-shaped": "1000685",
        "vibrio-shaped": "1000686",
    },
    "BacDive_Oxygen_tolerance": {
        "aerobe": "1000602",
        "anaerobe": "1000603",
        "microaerophile": "1000604",
        "facultative anaerobe": "1000605",
        "obligate aerobe": "1000606",
        "obligate anaerobe": "1000607",
        "facultative aerobe": "1000608",
        "aerotolerant": "1000609",
        "microaerotolerant": "1000610",
    },
}


def mapping_rows():
    """Read the committed curation table without touching production data."""
    with DEFAULT_PHENOTYPE_MAPPINGS.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def mapping_stream(rows):
    """Serialize tiny rule variants through the same parser as file inputs."""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return stream


def authority_stream():
    """Supply a tiny immutable native declaration excerpt as a caller-owned stream."""
    return io.StringIO(AUTHORITY.read_text(encoding="utf-8"))


@pytest.fixture
def curation():
    """Load all reviewed rules against the checked-in offline authority fixture."""
    return PhenotypeCuration(DEFAULT_PHENOTYPE_MAPPINGS, AUTHORITY)


def test_exact_twenty_two_rules_keep_native_category_and_source_evidence(curation):
    """Require native declarations without granting graph assertion or provenance fields."""
    rows = mapping_rows()
    assert len(rows) == sum(map(len, REVIEWED.values())) == 22
    assert {(row["source_column"], row["source_literal"]) for row in rows} == {
        (column, literal) for column, literals in REVIEWED.items() for literal in literals
    }
    for column, literals in REVIEWED.items():
        for literal, suffix in literals.items():
            rule = curation.resolve(column, literal)
            assert rule.target_curie == f"METPO:{suffix}"
            assert rule.source_column == column
            assert rule.source_literal == literal
            assert not hasattr(rule, "predicate")
            assert not hasattr(rule, "relation")
            assert rule.target_category == "biolink:OntologyClass"
            assert "872726c257b39d14ffb1827df09127b5c8ef72bb" in rule.evidence_uri
            assert "BacDive-origin" in rule.curation_rationale
            assert not hasattr(rule, "knowledge_level")
            assert not hasattr(rule, "agent_type")


@pytest.mark.parametrize(
    "column,literal",
    [
        ("BacDive_Gram_stain", "Positive"),
        ("BacDive_Gram_stain", " positive"),
        ("BacDive_Gram_stain", "positive "),
        ("BacDive_Gram_stain", "positive;negative"),
        ("BacDive_Gram_stain", "0"),
        ("BacDive_Gram_stain", "1"),
        ("BacDive_Gram_stain", "+"),
        ("BacDive_Gram_stain", "-"),
        ("BacDive_Motility", "1"),
        ("BacDive_Spore_formation", "0"),
        ("BacDive_Indole_test", "+"),
        ("BacDive_Voges_proskauer", "-"),
        ("BacDive_Flagellum_arrangement", "polar"),
        ("BacDive_Cell_shape", "other"),
        ("BacDive_Cell_shape", "filament-shaped"),
        ("BacDive_Cell_shape", "spiral-shaped"),
        ("BacDive_Cell_shape", "curved-shaped"),
        ("BacDive_Cell_shape", "sphere-shaped"),
        ("BacDive_Cell_shape", "helical-shaped"),
        ("BacDive_Cell_shape", "spore-shaped"),
        ("BacDive_Cell_shape", "flask-shaped"),
        ("BacDive_Cell_shape", "dumbbell-shaped"),
        ("BacDive_Cell_shape", "crescent-shaped"),
        ("BacDive_Cell_shape", "positive"),
        ("BacDive_Oxygen_tolerance", "aerobic"),
        ("BacDive_Oxygen_tolerance", "strictly anaerobic"),
        ("Bergey_Type_of_metabolism", "anaerobe"),
        ("BacDive_Metabolite_utilization", "glucose"),
        ("gram_stain", "positive"),
    ],
)
def test_unreviewed_literals_and_scopes_remain_attributes(curation, column, literal):
    """Never infer missing code meaning, cross-field synonyms or additional physiology."""
    assert curation.resolve(column, literal) is None


def test_each_multivalued_observation_remains_independent(curation):
    """Mixed positive/negative records do not become the distinct variable assertion."""
    rules = [curation.resolve("BacDive_Gram_stain", literal) for literal in ("positive", "negative")]
    assert {rule.target_curie for rule in rules} == {"METPO:1000698", "METPO:1000699"}
    assert all(rule.target_curie != "METPO:1000700" for rule in rules)
    assert curation.resolve("BacDive_Oxygen_tolerance", "obligate anaerobe").target_curie == "METPO:1000607"


def test_streams_remain_open_and_rules_are_immutable():
    """Caller-owned hashing streams retain ownership and rules cannot acquire provenance."""
    mappings, authority = mapping_stream(mapping_rows()), authority_stream()
    resolver = PhenotypeCuration(mappings, authority)
    assert not mappings.closed and not authority.closed
    with pytest.raises(FrozenInstanceError):
        resolver.resolve("BacDive_Gram_stain", "positive").target_label = "changed"


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("source_column", "BacDive_Motility", "source column scope"),
        ("source_column", "BacDive_Flagellum_arrangement", "source column scope"),
        ("source_column", "Bergey_Type_of_metabolism", "source column scope"),
        ("source_literal", " positive", "malformed"),
        ("target_curie", "METPO:2000015", "METPO class"),
        ("target_curie", "CHEBI:15377", "METPO class"),
        ("evidence_uri", "http://example.org", "evidence URI"),
        ("evidence_uri", "https://example.org|", "evidence URI"),
        ("evidence_uri", "https://exa mple.org", "evidence URI"),
        ("evidence_uri", "", "Incomplete"),
        ("curation_rationale", "", "Incomplete"),
    ],
)
def test_invalid_scopes_targets_and_evidence_abort(field, value, message):
    """Bad curated input aborts before any production assertions can be emitted."""
    rows = mapping_rows()
    rows[0][field] = value
    with pytest.raises(ValueError, match=message):
        PhenotypeCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_and_conflicting_rules_abort(conflicting):
    """Input ordering must not select one of two rules for the same source value."""
    rows = mapping_rows()
    duplicate = dict(rows[0])
    if conflicting:
        duplicate.update(target_curie="METPO:1000698", target_label="gram positive")
    rows.append(duplicate)
    with pytest.raises(ValueError, match="Duplicate or conflicting"):
        PhenotypeCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "short_row", "long_row", "empty"])
def test_malformed_mapping_tables_abort(kind):
    """Enforce the exact schema and reject ragged or empty mapping input."""
    lines = mapping_stream(mapping_rows()).getvalue().splitlines()
    header = lines[0].split("\t")
    if kind == "missing":
        header.pop()
    elif kind == "extra":
        header.append("unknown")
    elif kind == "duplicate":
        header[-1] = header[0]
    elif kind == "short_row":
        lines[1] = "\t".join(lines[1].split("\t")[:-1])
    elif kind == "long_row":
        lines[1] += "\textra"
    elif kind == "empty":
        lines = lines[:1]
    lines[0] = "\t".join(header)
    with pytest.raises(ValueError):
        PhenotypeCuration(io.StringIO("\n".join(lines)), authority_stream())


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("id", "METPO:1999999", "Missing authoritative"),
        ("name", "Changed label", "label/category"),
        ("category", "biolink:PhenotypicQuality", "label/category"),
        ("category", "", "label/category"),
        ("deprecated", "true", "Deprecated"),
        ("deprecated", "1", "Deprecated"),
        ("deprecated", "unknown", "invalid METPO target status"),
    ],
)
def test_missing_changed_or_deprecated_authority_aborts(field, value, message):
    """Curated targets cannot replace a missing or incompatible ontology declaration."""
    rows = list(csv.DictReader(authority_stream(), delimiter="\t"))
    rows[3][field] = value
    with pytest.raises(ValueError, match=message):
        PhenotypeCuration(DEFAULT_PHENOTYPE_MAPPINGS, mapping_stream(rows))


def test_duplicate_and_inconsistent_authority_expectations_abort():
    """Require unique native target declarations and consistent expected metadata."""
    lines = authority_stream().getvalue().splitlines()
    with pytest.raises(ValueError, match="Duplicate METPO target"):
        PhenotypeCuration(DEFAULT_PHENOTYPE_MAPPINGS, io.StringIO("\n".join([*lines, lines[4]])))
    rows = mapping_rows()
    rows[1]["target_curie"] = rows[0]["target_curie"]
    with pytest.raises(ValueError, match="Conflicting expected METPO declaration"):
        PhenotypeCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("field,value", [("predicate", "biolink:has_phenotype"), ("relation", "RO:0002200")])
def test_graph_assertion_fields_are_not_part_of_report_only_rules(field, value):
    """An earlier graph proposal must not be silently accepted as report-only curation."""
    rows = mapping_rows()
    for row in rows:
        row[field] = value
    with pytest.raises(ValueError, match="mapping columns"):
        PhenotypeCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("kind", ["missing_header", "duplicate_header", "short_target", "long_target"])
def test_malformed_authority_declarations_abort(kind):
    """Require explicit deprecation and structurally complete target rows."""
    lines = authority_stream().getvalue().splitlines()
    if kind == "missing_header":
        lines[0] = "id\tname\tcategory"
    elif kind == "duplicate_header":
        lines[0] += "\tid"
    elif kind == "short_target":
        lines[4] = lines[4].rstrip("\t")
    elif kind == "long_target":
        lines[4] += "\textra"
    with pytest.raises(ValueError):
        PhenotypeCuration(DEFAULT_PHENOTYPE_MAPPINGS, io.StringIO("\n".join(lines)))


def test_file_inputs_are_revalidated_without_cached_success(tmp_path):
    """Missing files or changes between resolver instances must fail closed."""
    mappings, authority = tmp_path / "mappings.tsv", tmp_path / "nodes.tsv"
    with pytest.raises(FileNotFoundError):
        PhenotypeCuration(mappings, authority)
    mappings.write_text(mapping_stream(mapping_rows()).getvalue(), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        PhenotypeCuration(mappings, authority)
    authority.write_text(authority_stream().getvalue(), encoding="utf-8")
    assert PhenotypeCuration(mappings, authority).resolve("BacDive_Gram_stain", "positive")
    authority.write_text("id\tname\tcategory\tdeprecated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing authoritative"):
        PhenotypeCuration(mappings, authority)
