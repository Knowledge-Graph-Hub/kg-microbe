"""Keep #650 process normalization limited to reviewed source assertions."""

import csv
import io
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder.curation import (
    DEFAULT_PROCESS_MAPPINGS,
    ProcessCuration,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import REPORTED_METABOLISM_ANNOTATIONS

AUTHORITY_HEADER = ("id", "name", "category", "deprecated")
AUTHORITY_ROWS = (
    ("METPO:1002005", "Fermentation", "biolink:BiologicalProcess", ""),
    ("METPO:1000844", "Methanogenesis", "biolink:BiologicalProcess", "false"),
    ("METPO:1005039", "nitrogen fixation", "biolink:BiologicalProcess", "0"),
)
REVIEWED_PAIRS = (
    ("bergey", "Fermentation", "METPO:1002005"),
    ("faprotax", "fermentation", "METPO:1002005"),
    ("vpi", "Fermentation", "METPO:1002005"),
    ("literature", "Fermentation", "METPO:1002005"),
    ("faprotax", "nitrogen_fixation", "METPO:1005039"),
    ("faprotax", "methanogenesis", "METPO:1000844"),
    ("bergey", "Methanogenesis", "METPO:1000844"),
    ("literature", "Methanogenesis", "METPO:1000844"),
    ("faprotax", "nitrate_denitrification", "GO:0019333"),
    ("faprotax", "aerobic_nitrite_oxidation", "GO:0019332"),
    ("faprotax", "acetoclastic_methanogenesis", "GO:0019385"),
    ("faprotax", "ureolysis", "GO:0043419"),
    ("faprotax", "xylanolysis", "GO:0045493"),
    ("faprotax", "cellulolysis", "GO:0030245"),
    ("faprotax", "chitinolysis", "GO:0006032"),
    ("faprotax", "ligninolysis", "GO:0046274"),
    ("faprotax", "hydrocarbon_degradation", "GO:0120253"),
)
GO_FIXTURE = Path(__file__).parent / "resources" / "microbedecoder" / "go_nodes.tsv"


def go_authority_stream():
    """Use the immutable nine-declaration fixture, not live ontology outputs."""
    return io.StringIO(GO_FIXTURE.read_text(encoding="utf-8"))


def authority_stream(rows=AUTHORITY_ROWS, header=AUTHORITY_HEADER):
    """Build an offline declaration excerpt; never read real raw/transformed data."""
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    stream.seek(0)
    return stream


def mapping_rows():
    """Read the committed curated rules as test input."""
    with DEFAULT_PROCESS_MAPPINGS.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def mapping_stream(rows):
    """Serialize tiny mapping variants to exercise the real TSV parser."""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return stream


@pytest.fixture
def curation(tmp_path):
    """Load committed rules against isolated immutable declaration values."""
    authority = tmp_path / "metpo_nodes.tsv"
    authority.write_text(authority_stream().getvalue(), encoding="utf-8")
    return ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority, go_authority_stream())


def test_all_reviewed_source_pairs_and_evidence(curation):
    """Keep the seventeen selected routes explicit without creating global aliases."""
    rows = mapping_rows()
    assert len(rows) == len(REVIEWED_PAIRS) == 17
    assert {(row["source_key"].split(":")[0], row["source_literal"], row["target_curie"]) for row in rows} == set(
        REVIEWED_PAIRS
    )
    for group, literal, target in REVIEWED_PAIRS:
        rule = curation.resolve(f"{group}:type_of_metabolism", literal)
        assert rule is not None
        assert rule.target_curie == target
        prefix = {"faprotax": "FAPROTAX", "vpi": "VPI", "bergey": "Bergey", "literature": "Literature"}[group]
        assert rule.source_column == f"{prefix}_Type_of_metabolism"
        assert rule.source_literal == literal
        assert rule.predicate == "biolink:capable_of"
        assert rule.relation == "RO:0002215"
        assert rule.target_category == "biolink:BiologicalProcess"
        assert rule.evidence_type == "source_term_normalization"
        assert rule.evidence_uri.startswith("https://")
        assert rule.curation_rationale
        if group == "faprotax":
            assert (rule.knowledge_level, rule.agent_type) == ("prediction", "computational_model")
        else:
            assert (rule.knowledge_level, rule.agent_type) == ("knowledge_assertion", "manual_agent")


def test_every_curated_process_object_satisfies_the_pinned_predicate_range(curation):
    """Neither METPO nor GO normalization may introduce an OntologyClass range violation."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    schema = Path(__file__).parent / "resources/metpo_process_categories/biolink-4.4.2-processes.yaml"
    toolkit = Toolkit(schema=str(schema))
    predicate = toolkit.get_element("capable of")
    assert predicate.range == "occurrent"
    allowed = toolkit.get_descendants(predicate.range, formatted=True)
    assert "biolink:BiologicalProcess" in allowed
    assert "biolink:OntologyClass" not in allowed
    assert "biolink:OrganismTaxon" in toolkit.get_descendants(predicate.domain, formatted=True)
    for group, literal, _ in REVIEWED_PAIRS:
        rule = curation.resolve(f"{group}:type_of_metabolism", literal)
        assert rule.target_category in allowed
        assert rule.relation in predicate.exact_mappings


@pytest.mark.parametrize("category", ["biolink:OntologyClass", "biolink:PhenotypicQuality", "biolink:Attribute"])
def test_metpo_process_rules_cannot_admit_generic_or_nonprocess_types(category):
    """Even an identically typed ontology declaration cannot certify an invalid rule."""
    rows = mapping_rows()
    for row in rows:
        if row["target_curie"].startswith("METPO:"):
            row["target_category"] = category
    with pytest.raises(ValueError, match="METPO biological process"):
        ProcessCuration(mapping_stream(rows), authority_stream(), go_authority_stream())


@pytest.mark.parametrize(
    "source_key,literal",
    [
        ("bergey:type_of_metabolism", "fermentation"),
        ("faprotax:type_of_metabolism", "Fermentation"),
        ("faprotax:type_of_metabolism", "nitrogen fixation"),
        ("bergey:type_of_metabolism", " Fermentation"),
        ("bergey:type_of_metabolism", "Fermentation "),
        ("bergey:type_of_metabolism", "Non-fermentative"),
        ("bergey:type_of_metabolism", "No fermentation"),
        ("faprotax:type_of_metabolism", "methanogenesis_by_CO2_reduction_with_H2"),
        ("faprotax:type_of_metabolism", "aerobic_chemoheterotrophy"),
        ("faprotax:type_of_metabolism", "nitrate_reduction"),
        ("faprotax:type_of_metabolism", "methanotrophy"),
        ("faprotax:type_of_metabolism", "nitrification"),
        ("faprotax:type_of_metabolism", "aerobic_ammonia_oxidation"),
        ("faprotax:type_of_metabolism", "denitrification"),
        ("faprotax:type_of_metabolism", "nitrite_denitrification"),
        ("faprotax:type_of_metabolism", "nitrous_oxide_denitrification"),
        ("faprotax:type_of_metabolism", "reductive_acetogenesis"),
        ("faprotax:type_of_metabolism", "aromatic_compound_degradation"),
        ("faprotax:type_of_metabolism", "methanol_oxidation"),
        ("faprotax:type_of_metabolism", "Nitrate_denitrification"),
        ("faprotax:type_of_metabolism", "nitrate_denitrification "),
        ("bergey:type_of_metabolism", "nitrate_denitrification"),
        ("faprotax:substrates", "ureolysis"),
        ("faprotax2:type_of_metabolism", "ureolysis"),
        ("vpi:type_of_metabolism", "Methanogenesis"),
        ("literature:type_of_metabolism", "nitrogen_fixation"),
        ("faprotax2:type_of_metabolism", "fermentation"),
        ("bergey:major_end_products", "Fermentation"),
        ("bergey:substrates", "Fermentation"),
        ("bacdive:type_of_metabolism", "Fermentation"),
        ("Bergey_Type_of_metabolism", "Fermentation"),
        ("BacDive_Oxygen_tolerance", "Fermentation"),
    ],
)
def test_unreviewed_literals_case_sources_and_roles_do_not_resolve(curation, source_key, literal):
    """Narrower/negative terms and other fields must retain their existing fallback."""
    assert curation.resolve(source_key, literal) is None


def test_caller_owned_streams_remain_open_and_rules_are_immutable():
    """Permit consumed-input fingerprinting without taking ownership of its streams."""
    mappings = mapping_stream(mapping_rows())
    authority = authority_stream()
    go_authority = go_authority_stream()
    curation = ProcessCuration(mappings, authority, go_authority)
    assert not mappings.closed
    assert not authority.closed
    assert not go_authority.closed
    with pytest.raises(FrozenInstanceError):
        curation.resolve("faprotax:type_of_metabolism", "fermentation").knowledge_level = "observation"


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("source_column", "VPI_Type_of_metabolism", "source column/role"),
        ("source_key", "bergey:substrates", "source column/role"),
        ("source_key", "faprotax2:type_of_metabolism", "source column/role"),
        ("target_curie", "METPO:2000011", "METPO class"),
        ("target_curie", "CHEBI:15366", "METPO class"),
        ("predicate", "biolink:has_phenotype", "predicate/relation"),
        ("relation", "METPO:2000011", "predicate/relation"),
        ("knowledge_level", "observation", "evidence provenance"),
        ("agent_type", "computational_model", "evidence provenance"),
        ("evidence_type", "experimental_confirmation", "evidence type"),
        ("evidence_uri", "", "Incomplete"),
        ("evidence_uri", "file:///tmp/evidence", "evidence URI"),
        ("evidence_uri", "https://example.org|", "evidence URI"),
        ("curation_rationale", "", "Incomplete"),
        ("source_literal", " Fermentation", "malformed"),
    ],
)
def test_invalid_scopes_and_incomplete_evidence_are_rejected(field, value, expected_error):
    """A malformed curation file must abort rather than silently omit rules."""
    rows = mapping_rows()
    rows[0][field] = value
    with pytest.raises(ValueError, match=expected_error):
        ProcessCuration(mapping_stream(rows), authority_stream())


def test_faprotax_prediction_cannot_be_upgraded():
    """Manual term curation does not make organism assignments observations."""
    rows = mapping_rows()
    faprotax = next(row for row in rows if row["source_key"] == "faprotax:type_of_metabolism")
    faprotax.update(knowledge_level="knowledge_assertion", agent_type="manual_agent")
    with pytest.raises(ValueError, match="evidence provenance"):
        ProcessCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_and_conflicting_rules_abort(conflicting):
    """Do not allow row ordering to choose a mapping when keys repeat."""
    rows = mapping_rows()
    duplicate = dict(rows[0])
    if conflicting:
        duplicate.update(target_curie="METPO:1000844", target_label="Methanogenesis")
    rows.append(duplicate)
    with pytest.raises(ValueError, match="Duplicate or conflicting"):
        ProcessCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "short_row", "long_row", "no_rows"])
def test_malformed_mapping_table_aborts(kind):
    """Reject unknown schema, duplicate headers and ragged TSV rows."""
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
    elif kind == "no_rows":
        lines = lines[:1]
    lines[0] = "\t".join(header)
    with pytest.raises(ValueError):
        ProcessCuration(io.StringIO("\n".join(lines)), authority_stream())


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("id", "METPO:1999999", "Missing authoritative"),
        ("name", "fermentation", "label/category"),
        ("category", "biolink:PhenotypicQuality", "label/category"),
        ("category", "", "label/category"),
        ("deprecated", "true", "Deprecated"),
        ("deprecated", "1", "Deprecated"),
        ("deprecated", "unknown", "invalid METPO target status"),
    ],
)
def test_wrong_missing_and_deprecated_authoritative_declarations_abort(field, value, expected_error):
    """A rule cannot stand in for a missing or changed ontology declaration."""
    rows = [list(row) for row in AUTHORITY_ROWS]
    rows[0][AUTHORITY_HEADER.index(field)] = value
    with pytest.raises(ValueError, match=expected_error):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(rows))


def test_duplicate_authority_and_conflicting_expected_declarations_abort():
    """Require a unique authority declaration and consistent expectations per target."""
    with pytest.raises(ValueError, match="Duplicate METPO target"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream((*AUTHORITY_ROWS, AUTHORITY_ROWS[0])))
    rows = mapping_rows()
    rows[0]["target_label"] = "Another process"
    with pytest.raises(ValueError, match="Conflicting expected METPO declaration"):
        ProcessCuration(mapping_stream(rows), authority_stream())


@pytest.mark.parametrize("header", [AUTHORITY_HEADER[:-1], (*AUTHORITY_HEADER, "id")])
def test_authority_schema_must_include_deprecation_without_duplicate_headers(header):
    """Missing status cannot be silently treated as known nondeprecated."""
    with pytest.raises(ValueError, match="Missing or duplicate METPO declaration columns"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(header=header))


def test_authority_ragged_target_row_aborts():
    """A truncated declaration is not an implicitly active target."""
    with pytest.raises(ValueError, match="Malformed METPO target declaration"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream((AUTHORITY_ROWS[0][:-1], *AUTHORITY_ROWS[1:])))


def test_missing_files_and_changed_files_are_revalidated(tmp_path):
    """Missing inputs fail; later instances may not reuse a stale successful load."""
    authority = tmp_path / "metpo_nodes.tsv"
    mappings = tmp_path / "process_mappings.tsv"
    with pytest.raises(FileNotFoundError):
        ProcessCuration(mappings, authority)
    mappings.write_text(mapping_stream(mapping_rows()).getvalue(), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        ProcessCuration(mappings, authority)
    authority.write_text(authority_stream().getvalue(), encoding="utf-8")
    assert ProcessCuration(mappings, authority, go_authority_stream()).resolve(
        "bergey:type_of_metabolism", "Fermentation"
    )
    authority.write_text(authority_stream(AUTHORITY_ROWS[1:]).getvalue(), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing authoritative"):
        ProcessCuration(mappings, authority)
    authority.write_text(authority_stream().getvalue(), encoding="utf-8")
    rows = mapping_rows()
    rows[0]["source_column"] = "Wrong_column"
    mappings.write_text(mapping_stream(rows).getvalue(), encoding="utf-8")
    with pytest.raises(ValueError, match="source column/role"):
        ProcessCuration(mappings, authority)


def test_go_authority_is_required_only_for_go_rules(tmp_path):
    """Legacy/custom METPO-only tables do not acquire a GO input dependency."""
    metpo_only = [row for row in mapping_rows() if row["target_curie"].startswith("METPO:")]
    assert ProcessCuration(mapping_stream(metpo_only), authority_stream()).resolve(
        "bergey:type_of_metabolism", "Fermentation"
    )
    with pytest.raises(ValueError, match="Missing authoritative GO input"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream())
    with pytest.raises(FileNotFoundError):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), tmp_path / "absent-go.tsv")


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("id", "GO:9999999", "Missing authoritative GO targets"),
        ("name", "Chitin catabolic process", "Unexpected GO target label/category"),
        ("category", "biolink:OntologyClass", "Unexpected GO target label/category"),
        ("category", "", "Unexpected GO target label/category"),
        ("deprecated", "true", "Deprecated or invalid GO target status"),
        ("deprecated", "1", "Deprecated or invalid GO target status"),
        ("deprecated", "unknown", "Deprecated or invalid GO target status"),
    ],
)
def test_go_authority_failures_abort(field, value, expected_error):
    """An explicit GO authority is necessary but is never sufficient unvalidated."""
    rows = list(csv.reader(go_authority_stream(), delimiter="\t"))[1:]
    rows[0][AUTHORITY_HEADER.index(field)] = value
    with pytest.raises(ValueError, match=expected_error):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), authority_stream(rows))


@pytest.mark.parametrize("kind", ["duplicate", "missing_header", "duplicate_header", "ragged", "extra_cell"])
def test_go_authority_schema_and_uniqueness(kind):
    """GO and METPO exports receive the same fail-closed structural checks."""
    rows = list(csv.reader(go_authority_stream(), delimiter="\t"))[1:]
    header = AUTHORITY_HEADER
    if kind == "duplicate":
        rows.append(rows[0])
        error = "Duplicate GO target declaration"
    elif kind == "missing_header":
        header = header[:-1]
        error = "Missing or duplicate GO declaration columns"
    elif kind == "duplicate_header":
        header = (*header, "id")
        error = "Missing or duplicate GO declaration columns"
    elif kind == "ragged":
        rows[0] = rows[0][:-1]
        error = "Malformed GO target declaration"
    else:
        rows[0].append("extra")
        error = "Malformed GO target declaration"
    with pytest.raises(ValueError, match=error):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), authority_stream(rows, header))


def test_go_authority_does_not_fall_back_to_metpo_export():
    """An authority supplied for a different namespace cannot satisfy GO."""
    with pytest.raises(ValueError, match="Missing authoritative GO targets"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), authority_stream())


def test_conflicting_expected_go_declarations_abort():
    """Different source rules may not disagree about a shared GO declaration."""
    rows = mapping_rows()
    duplicate = dict(next(row for row in rows if row["target_curie"] == "GO:0006032"))
    duplicate.update(source_literal="another_reviewed_literal", target_label="Another process")
    rows.append(duplicate)
    with pytest.raises(ValueError, match="Conflicting expected GO declaration"):
        ProcessCuration(mapping_stream(rows), authority_stream(), go_authority_stream())


@pytest.mark.parametrize("target", ["GO:6032", "GO:00060320", "go:0006032", "GO:abcdefg"])
def test_go_curie_syntax_is_strict(target):
    """Malformed identifiers do not enter authority matching."""
    rows = mapping_rows()
    rows[-1]["target_curie"] = target
    with pytest.raises(ValueError, match="GO class target"):
        ProcessCuration(mapping_stream(rows), authority_stream(), go_authority_stream())


def test_go_molecular_function_cannot_be_used_as_process_object():
    """Even a declared molecular-function class is not a reviewed process class."""
    rows = mapping_rows()
    rows[-1].update(
        target_curie="GO:0009039", target_label="urease activity", target_category="biolink:MolecularActivity"
    )
    with pytest.raises(ValueError, match="GO biological process"):
        ProcessCuration(mapping_stream(rows), authority_stream(), go_authority_stream())


def test_go_path_is_revalidated_on_each_load(tmp_path):
    """A previous successful GO authority must not survive later replacement."""
    authority = tmp_path / "go_nodes.tsv"
    authority.write_text(go_authority_stream().getvalue(), encoding="utf-8")
    assert ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), authority).resolve(
        "faprotax:type_of_metabolism", "ureolysis"
    )
    rows = list(csv.reader(go_authority_stream(), delimiter="\t"))[1:]
    rows[0][-1] = "true"
    authority.write_text(authority_stream(rows).getvalue(), encoding="utf-8")
    with pytest.raises(ValueError, match="Deprecated or invalid GO target status"):
        ProcessCuration(DEFAULT_PROCESS_MAPPINGS, authority_stream(), authority)


@pytest.mark.parametrize("column,literal", sorted(REPORTED_METABOLISM_ANNOTATIONS))
def test_reported_nonprocess_annotations_cannot_be_shadowed(column, literal):
    """A curated table cannot silently undo the finite non-process dispositions."""
    template = next(row for row in mapping_rows() if row["source_column"] == column)
    row = dict(template, source_literal=literal)
    with pytest.raises(ValueError, match="Non-process source annotation"):
        ProcessCuration(mapping_stream([row]), authority_stream(), go_authority_stream())
