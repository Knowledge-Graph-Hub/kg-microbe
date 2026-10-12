"""Finite NCIT13 and separately approved Lesion extension, without identity or edge rewrites."""

import copy
import hashlib
import io
import json
import sqlite3

import pytest

from kg_microbe.transform_utils.constants import CATEGORY_COLUMN, ID_COLUMN, NAMED_THING_CATEGORY
from kg_microbe.utils import ncit_eight_categories as finite
from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
from tests.go_subject_restrictions_fixtures import write_rows
from tests.ncit_eight_fixtures import FIXTURE, NATIVE, POLICY, SOURCE_ROWS, prepare

NEW_THIRTEEN = frozenset(
    {
        "NCIT:C113696",
        "NCIT:C120264",
        "NCIT:C120561",
        "NCIT:C13347",
        "NCIT:C28176",
        "NCIT:C29298",
        "NCIT:C29321",
        "NCIT:C77500",
        "NCIT:C77524",
        "NCIT:C77916",
        "NCIT:C85253",
        "NCIT:C85509",
        "NCIT:C87343",
    }
)
LESION = "NCIT:C3824"
NEW_IDS = NEW_THIRTEEN | {LESION}
EDGES = json.loads((FIXTURE / "extension_incident_edges.json").read_text())
HEADERS = json.loads((FIXTURE / "extension_source_headers.json").read_text())


def test_distinct_review_groups_and_original_native_contract_remain_explicit():
    """An approved finding projection cannot silently turn the thirteen-ID package into a broad rule."""
    assert len(POLICY["review_groups"]["original_eight"]) == 8
    assert set(POLICY["review_groups"]["native_thirteen"]) == NEW_THIRTEEN
    assert POLICY["review_groups"]["lesion_primary_finding"] == [LESION]
    assert finite.FINITE_IDS == set(POLICY["review_groups"]["original_eight"]) | NEW_IDS
    assert len(finite.FINITE_IDS) == 22
    assert len(NATIVE["statements"]) == 75
    assert sum(map(len, NATIVE["statements"].values())) == 5460
    assert len(SOURCE_ROWS) == 38
    assert len([item for item in SOURCE_ROWS if item["row"][ID_COLUMN] in NEW_IDS]) == 24
    assert len(EDGES) == 202
    assert sum(any(item["row"][key] == LESION for key in ("subject", "object")) for item in EDGES) == 4


def test_lesion_primary_finding_and_secondary_tissue_definition_are_both_retained():
    """PhenotypicFeature follows the separately approved primary meaning, never location edge pressure."""
    decision = POLICY["records"][LESION]
    assert decision["category"] == "biolink:PhenotypicFeature"
    assert decision["root_path"] == [LESION, "NCIT:C3367"]
    assert decision["native_definitions"] == [
        "A localized pathological or traumatic structural change, damage, deformity, "
        "or discontinuity of tissue, organ, or body part."
    ]
    assert (
        "An area of abnormal tissue. A lesion may be benign (not cancer) or malignant (cancer)."
        in decision["native_additional_definitions"]
    )
    assert "no physical-location" in decision["rationale"]


@pytest.mark.parametrize(
    "identifier, category, anchor",
    [
        ("NCIT:C13347", "biolink:MaterialSample", "NCIT:C19157"),
        ("NCIT:C28176", "biolink:PhysicalEntity", "NCIT:C14376"),
        ("NCIT:C85253", "biolink:ChemicalEntity", "NCIT:C735"),
        ("NCIT:C29321", "biolink:ChemicalEntity", "NCIT:C802"),
        ("NCIT:C85509", "biolink:ChemicalMixture", "NCIT:C85504"),
    ],
)
def test_definition_supported_specific_choices_are_not_label_or_prefix_fallbacks(identifier, category, anchor):
    """Each chosen category has its own reviewed path instead of one generic Food/animal root."""
    decision = POLICY["records"][identifier]
    assert decision["category"] == category
    assert decision["root_path"][-1] == anchor
    assert anchor not in finite.FINITE_IDS
    finite.validate_statements(POLICY["native_statements"], POLICY)


@pytest.mark.parametrize("identifier", sorted(NEW_IDS))
def test_every_new_category_rejects_incompatible_substantive_typing(identifier):
    """The extension does not silently repair unknown class meanings with a category union."""
    expected = POLICY["records"][identifier]["category"]
    for wrong in {"biolink:OrganismTaxon", "biolink:ClinicalFinding", "biolink:Protein", "biolink:AnatomicalEntity"}:
        assert wrong != expected
        with pytest.raises(ValueError, match="Conflicting substantive"):
            finite.apply_category(wrong + "|biolink:OntologyClass", expected)


@pytest.mark.parametrize("identifier", ["NCIT:C735", "NCIT:C802", "NCIT:C14376", "NCIT:C85504", "CHEBI:C3824"])
def test_new_reviewed_roots_and_lookalikes_do_not_propagate_a_category(tmp_path, identifier):
    """A witness ancestor is evidence, not an eligible output ID or an automatic subtree rule."""
    authority = finite.FiniteNcitCategoryAuthority(tmp_path, opener=lambda path: pytest.fail(f"Unexpected read {path}"))
    assert authority.category_for(identifier) is None
    assert authority.contract() == {"version": 1, "authority": None}


@pytest.mark.parametrize("identifier", ["NCIT:C77500", "NCIT:C85253", "NCIT:C87343"])
def test_real_missing_definitions_cannot_be_filled_by_native_receipt_repin(tmp_path, monkeypatch, identifier):
    """A byte-valid new database cannot invent the missing definition behind a finite category."""
    raw, path, policy, _, authority = prepare(tmp_path, monkeypatch)
    assert policy["records"][identifier]["native_definitions"] == []
    with sqlite3.connect(raw / "ncit.db") as connection:
        connection.execute(
            "INSERT INTO statements VALUES(?,?,?,?,?,?)", (identifier, "IAO:0000115", None, "invented", None, None)
        )
    policy["native_sha256"] = finite.digest((raw / "ncit.db").read_bytes())
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    with pytest.raises(ValueError, match="native statements changed"):
        authority.category_for(identifier)


def test_lesion_secondary_native_sense_cannot_be_dropped_after_explicit_db_repin(tmp_path, monkeypatch):
    """Selecting a primary category does not authorize erasing inconvenient additional native meaning."""
    raw, path, policy, _, authority = prepare(tmp_path, monkeypatch)
    with sqlite3.connect(raw / "ncit.db") as connection:
        connection.execute("DELETE FROM statements WHERE subject=? AND predicate='NCIT:P325'", (LESION,))
    policy["native_sha256"] = finite.digest((raw / "ncit.db").read_bytes())
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    with pytest.raises(ValueError, match="native statements changed"):
        authority.category_for(LESION)


@pytest.mark.parametrize(
    "key", ["chemical entity", "material sample", "physical entity", "chemical mixture", "phenotypic feature"]
)
@pytest.mark.parametrize("flag", ["mixin", "abstract", "deprecated"])
def test_all_new_model_categories_must_remain_concrete_even_with_fixture_policy_repin(key, flag):
    """Model receipt agreement cannot authorize a mixin/abstract/deprecated target."""
    policy = copy.deepcopy(POLICY)
    model = json.loads((FIXTURE / "biolink.json").read_text())
    model["classes"][key][flag] = True
    policy["model_classes"][key] = model["classes"][key]
    with pytest.raises(ValueError, match="active concrete"):
        finite.validate_model(model, policy)


def test_missing_lesion_or_new_policy_decision_cannot_self_approve():
    """The complete independently sealed finite policy cannot lose an approved decision."""
    for identifier in sorted(NEW_IDS):
        policy = copy.deepcopy(POLICY)
        del policy["records"][identifier]
        with pytest.raises(ValueError, match="Unreviewed"):
            finite.load_policy(io.StringIO(json.dumps(policy)))


@pytest.mark.usefixtures("local_source_schema")
def test_public_extension_finalization_preserves_all202_actual_incident_rows(tmp_path, monkeypatch):
    """Real shared finalization changes only 24 new category cells; every native/source edge stays literal."""
    _, _, policy, transform, _ = prepare(tmp_path, monkeypatch)
    target_rows = [dict(entry["row"]) for entry in SOURCE_ROWS if entry["row"][ID_COLUMN] in NEW_IDS]
    fields = list(target_rows[0])
    declared = {row[ID_COLUMN] for row in target_rows}
    endpoints = {entry["row"][key] for entry in EDGES for key in ("subject", "object")}
    # These test-only closure nodes are not claimed as recovered native declarations.
    closure = [
        {
            **dict.fromkeys(fields, ""),
            ID_COLUMN: identifier,
            CATEGORY_COLUMN: NAMED_THING_CATEGORY,
            "name": identifier,
            "provided_by": "infores:fixture",
        }
        for identifier in sorted(endpoints - declared)
    ]
    write_rows(transform.output_node_file, target_rows + closure, fields=fields)
    paths = []
    for source_file, header in HEADERS.items():
        entries = [entry for entry in EDGES if entry["file"] == source_file]
        filename = source_file.split("/")[-2] + "_edges.tsv"
        path = transform.output_dir / filename
        write_rows(path, [entry["row"] for entry in entries], fields=header)
        lines = path.read_bytes().splitlines(keepends=True)[1:]
        assert [hashlib.sha256(line).hexdigest() for line in lines] == [
            entry["literal_row_sha256"] for entry in entries
        ]
        paths.append(path)
    before_edges = {path.name: path.read_bytes() for path in paths}
    report = transform.finalize(fresh_run=True)
    after = list(graph_rows(transform.output_node_file))
    assert after[:24] == [
        {**row, CATEGORY_COLUMN: policy["records"][row[ID_COLUMN]]["category"]} for row in target_rows
    ]
    assert after[24:] == closure
    assert report[finite.CONTRACT_KEY]["identifiers"] == sorted(NEW_IDS)
    assert {path.name: path.read_bytes() for path in paths} == before_edges
    verify_finalized_source_files([transform.output_node_file, *paths])
    transform.finalize()
    assert {path.name: path.read_bytes() for path in paths} == before_edges
