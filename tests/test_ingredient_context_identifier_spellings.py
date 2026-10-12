"""Canonical identifier spellings cannot bypass the finite Catalase context denial."""

import copy

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils import ingredient_context as context
from tests import test_mediadive_catalase_scope as native
from tests import test_mim_conservative_refresh as candidate

CATALASE_IDENTIFIERS = (
    "NCIT:C61062",
    "ncit:c61062",
    "http://purl.obolibrary.org/obo/NCIT_C61062",
    "https://purl.obolibrary.org/obo/NCIT_C61062",
)


@pytest.mark.parametrize("identifier", CATALASE_IDENTIFIERS)
def test_ingredient_identity_rejected_in_both_xref_directions(identifier):
    """Neither supported IRIs nor existing CURIE case variants grant material identity."""
    assert not context.ingredient_context_allowed(identifier)
    assert not context.ingredient_context_pair_allowed("CHEBI:15377", identifier)
    assert not context.ingredient_context_pair_allowed(identifier, "CHEBI:15377")


@pytest.mark.parametrize("identifier", CATALASE_IDENTIFIERS)
def test_native_metadata_reconstruction_preserves_original_identifier_bytes(identifier):
    """Only predicate/comment change; the exact source spelling remains audit-recoverable."""
    row = copy.deepcopy(native._saved()["native_mapping_rows"][0])
    row["object_id"] = identifier
    before = dict(row)
    result = context.contextualize_ingredient_row(row)
    assert row == before
    assert result == {**before, "predicate_id": "skos:relatedMatch", "comment": context.AUTHORITY_COMMENT}
    assert context.context_metadata_row(result)
    assert context.contextualize_ingredient_row(result) == result


@pytest.mark.parametrize("identifier", CATALASE_IDENTIFIERS)
def test_real_runtime_lexical_index_cannot_admit_equivalent_target(identifier, tmp_path, monkeypatch):
    """The actual consolidated-table loader applies the same canonical context boundary."""
    rows = copy.deepcopy(native._saved()["native_mapping_rows"])
    for row in rows:
        row["object_id"] = identifier
    path = tmp_path / "native-spelling.tsv"
    candidate._table(path, candidate.FIELDS, rows, candidate._metadata())
    native._load_runtime(path, monkeypatch)
    assert runtime.find_chebi_by_name("Catalase") is None


@pytest.mark.parametrize(
    "identifier",
    [
        "CHEBI:15377",
        "http://purl.obolibrary.org/obo/CHEBI_15377",
        "https://purl.obolibrary.org/obo/NCIT_C61063",
        "https://example.org/NCIT_C61062",
    ],
)
def test_unrelated_identifiers_and_unregistered_lookalike_urls_are_unchanged(identifier):
    """The fix is a finite identity guard, never a substring or whole-namespace ban."""
    assert context.ingredient_context_allowed(identifier)
    row = {"subject_id": "kgm.name:control", "object_id": identifier, "predicate_id": "skos:exactMatch"}
    assert context.contextualize_ingredient_row(row) == row


def test_same_native_concept_declaration_is_not_ingredient_identity():
    """An equivalent self-declaration is preserved without granting ingredient lookup."""
    row = {
        "subject_id": CATALASE_IDENTIFIERS[0],
        "object_id": CATALASE_IDENTIFIERS[2],
        "predicate_id": "skos:exactMatch",
    }
    assert context.contextualize_ingredient_row(row) == row
    assert not context.ingredient_context_pair_allowed(row["subject_id"], row["object_id"])
