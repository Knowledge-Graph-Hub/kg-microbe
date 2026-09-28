"""Bind #650's tartrate correction to its complete immutable source record."""

import csv
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder.chemical_curation import (
    PRIMARY_EVIDENCE_URI,
    REVIEWED_RAW_ROW_SHA256,
    RecordChemicalCuration,
    canonical_raw_row_sha256,
)

RESOURCES = Path(__file__).parent / "resources" / "microbedecoder"


@pytest.fixture
def reviewed_row():
    """Read all original fields, including unrelated source fields and the 16S sequence."""
    return json.loads((RESOURCES / "bergey_tartate_record.json").read_text(encoding="utf-8"))


@pytest.fixture
def curation():
    """Validate an exact native ChEBI row excerpt without loading any runtime mappings."""
    return RecordChemicalCuration(RESOURCES / "chebi_record_nodes.tsv")


def authority_stream(**changes):
    """Mutate only an isolated native declaration to exercise fail-closed parsing."""
    with (RESOURCES / "chebi_record_nodes.tsv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = reader.fieldnames
        row = next(reader)
    row.update(changes)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    stream.seek(0)
    return stream


def test_complete_reviewed_record_resolves_without_mutation(curation, reviewed_row):
    """The positive control uses the true frozen full-row digest, never a monkeypatched pin."""
    before = deepcopy(reviewed_row)
    assert canonical_raw_row_sha256(reviewed_row) == REVIEWED_RAW_ROW_SHA256
    assert REVIEWED_RAW_ROW_SHA256 == "de979939d39a74aad45a0edffe59cde4e11b6d294ee9fb22e848a12bd0dda13f"
    assert PRIMARY_EVIDENCE_URI == "https://d-nb.info/1105570576/34"
    assert curation.resolve(reviewed_row, "bergey:substrates", "tartate") == "CHEBI:132950"
    assert reviewed_row == before
    reordered = dict(reversed(list(reviewed_row.items())))
    assert curation.resolve(reordered, "bergey:substrates", "tartate") == "CHEBI:132950"


@pytest.mark.parametrize("literal", ["tartrate", " tartate", "tartate ", "Tartate", "sugar", "", "NA", None])
def test_changed_known_record_literal_is_rejected(curation, reviewed_row, literal):
    """Empty or normalized replacements are new evidence, not an automatic fallback."""
    with pytest.raises(ValueError, match="record/field evidence changed"):
        curation.resolve(reviewed_row, "bergey:substrates", literal)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Bergey_Substrates_for_end_products", "tartrate"),
        ("Bergey_Substrates_for_end_products", "NA"),
        ("Bergey_Article_link", "https://doi.org/10.1002/9781118960608.other"),
        ("Bergey_Strain", "another strain"),
        ("Bergey_Major_end_products", "acetate"),
        ("BacDive_Temperature_for_growth", 30),
        ("BacDive_Temperature_for_growth", "30.0"),
        ("LPSN_16S_Ribosomal_sequence", "NA"),
        ("Literature_Citation", "new evidence"),
        ("additional_field", "NA"),
    ],
)
def test_any_full_record_change_is_rejected(curation, reviewed_row, field, value):
    """Do not selectively ignore upstream edits to unselected columns or scalar types."""
    reviewed_row[field] = value
    with pytest.raises(ValueError, match="record/field evidence changed"):
        curation.resolve(reviewed_row, "bergey:substrates", "tartate")


def test_missing_full_record_field_is_rejected(curation, reviewed_row):
    """A reduced context is not the reviewed complete record."""
    del reviewed_row["Literature_Citation"]
    with pytest.raises(ValueError, match="record/field evidence changed"):
        curation.resolve(reviewed_row, "bergey:substrates", "tartate")


@pytest.mark.parametrize(
    "source_key",
    [
        "literature:substrates",
        "vpi:substrates",
        "bergey:major_end_products",
        "bergey:minor_end_products",
        "Bergey_Substrates_for_end_products",
    ],
)
def test_other_sources_and_roles_are_not_global_aliases(curation, reviewed_row, source_key):
    """Do not extend the spelling correction to an unreviewed assertion role."""
    assert curation.resolve(reviewed_row, source_key, "tartate") is None


@pytest.mark.parametrize("lpsn", ["777028", None])
def test_other_records_do_not_resolve(curation, reviewed_row, lpsn):
    """A spelling alone cannot establish another organism's substrate identity."""
    reviewed_row["LPSN_ID"] = lpsn
    assert curation.resolve(reviewed_row, "bergey:substrates", "tartate") is None


@pytest.mark.parametrize("lpsn", ["777027 ", " 777027", "\t777027\n", 777027])
def test_normalized_producer_identity_cannot_bypass_record_guard(curation, reviewed_row, lpsn):
    """Match the producer's candidate-ID normalization only to reject changed raw evidence."""
    reviewed_row["LPSN_ID"] = lpsn
    with pytest.raises(ValueError, match="record/field evidence changed"):
        curation.resolve(reviewed_row, "bergey:substrates", "tartate")


def test_generic_peptones_and_sugar_are_not_curated(curation):
    """Keep both scientific holds outside the tartrate exception."""
    for label in ("peptones", "sugar", "3-methylacetate", "PYGS"):
        assert curation.resolve({"LPSN_ID": "another"}, "bergey:substrates", label) is None


@pytest.mark.parametrize("deprecated", ["", "false", "0", " FALSE "])
def test_native_active_flags_and_caller_owned_streams(deprecated):
    """Accept active native spellings without closing the caller's consumption stream."""
    stream = authority_stream(deprecated=deprecated)
    RecordChemicalCuration(stream)
    assert not stream.closed


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"id": "CHEBI:30924"}, "Missing authoritative"),
        ({"name": "L-tartrate"}, "label/category"),
        ({"name": "tartrate "}, "label/category"),
        ({"category": "biolink:OntologyClass"}, "label/category"),
        ({"deprecated": "true"}, "Deprecated"),
        ({"deprecated": "unknown"}, "Deprecated"),
    ],
)
def test_wrong_native_identity_or_status_is_rejected(changes, error):
    """Do not select another tartrate species or silently reuse a deprecated target."""
    with pytest.raises(ValueError, match=error):
        RecordChemicalCuration(authority_stream(**changes))


def test_duplicate_native_target_is_rejected():
    """Repeated declarations remain ambiguous even when their text is identical."""
    text = authority_stream().getvalue()
    duplicate = text + text.splitlines(keepends=True)[1]
    with pytest.raises(ValueError, match="Duplicate ChEBI"):
        RecordChemicalCuration(io.StringIO(duplicate))


@pytest.mark.parametrize(
    "text",
    [
        "id\tname\tcategory\n",
        "id\tname\tcategory\tdeprecated\tid\n",
        "id\tname\tcategory\tdeprecated\nCHEBI:132950\ttartrate\tbiolink:ChemicalEntity\n",
        "id\tname\tcategory\tdeprecated\nCHEBI:132950\ttartrate\tbiolink:ChemicalEntity\t\textra\n",
    ],
)
def test_malformed_target_tables_are_rejected(text):
    """Malformed headers or incomplete/extra target cells must fail clearly."""
    with pytest.raises(ValueError, match="columns|Malformed"):
        RecordChemicalCuration(io.StringIO(text))
