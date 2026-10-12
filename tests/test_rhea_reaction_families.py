"""Finite offline tests for native Rhea family identities and direction evidence."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from io import StringIO

import pytest

from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
    BIDIRECTIONAL_REACTION,
    DIRECTIONAL_REACTION,
    DIRECTIONS_HEADER,
    RDFS_LABEL,
    RHEA_RDF_BASE,
    RHEA_STATUS_FIELD,
    ReactionFamily,
    load_reaction_families,
    validate_family_cohort,
    validate_family_evidence,
)

HEADER = "\t".join(DIRECTIONS_HEADER) + "\n"
ROW = "10000\t11091\t14005\t20008\n"


def _family():
    return load_reaction_families(StringIO(HEADER + ROW))[0]


def _evidence():
    """Match native RDF predicates with deliberately nonconsecutive reaction IDs."""
    rh = RHEA_RDF_BASE
    return {
        "RHEA:10000": {
            RDFS_LABEL: ["A = B"],
            rh + "status": [rh + "Approved"],
            rh + "directionalReaction": [rh + "14005", rh + "11091"],
            rh + "bidirectionalReaction": [rh + "20008"],
            rh + "side": [rh + "10000_R", rh + "10000_L"],
        },
        "RHEA:11091": {
            RDFS_LABEL: ["A => B"],
            rh + "status": [rh + "Approved"],
            rh + "substrates": [rh + "10000_L"],
            rh + "products": [rh + "10000_R"],
        },
        "RHEA:14005": {
            RDFS_LABEL: ["B => A"],
            rh + "status": [rh + "Approved"],
            rh + "substrates": [rh + "10000_R"],
            rh + "products": [rh + "10000_L"],
        },
        "RHEA:20008": {
            RDFS_LABEL: ["A <=> B"],
            rh + "status": [rh + "Approved"],
            rh + "substratesOrProducts": [rh + "10000_L", rh + "10000_R"],
        },
    }


def test_explicit_nonconsecutive_ids_and_native_links():
    """Neither variant roles nor graph links are reconstructed by ID arithmetic."""
    family = _family()
    assert family.members == (
        ("RHEA:10000", "UN"),
        ("RHEA:11091", "LR"),
        ("RHEA:14005", "RL"),
        ("RHEA:20008", "BI"),
    )
    assert family.links == (
        ("RHEA:10000", DIRECTIONAL_REACTION, "RHEA:11091"),
        ("RHEA:10000", DIRECTIONAL_REACTION, "RHEA:14005"),
        ("RHEA:10000", BIDIRECTIONAL_REACTION, "RHEA:20008"),
    )
    assert DIRECTIONAL_REACTION == "rheav:directionalReaction"
    assert BIDIRECTIONAL_REACTION == "rheav:bidirectionalReaction"
    for identifier, direction in family.members:
        assert family.node_annotations(identifier) == {"rhea_direction": direction, "rhea_master_id": family.master}
    with pytest.raises(ValueError, match="not a member"):
        family.node_annotations("RHEA:10001")
    with pytest.raises(FrozenInstanceError):
        family.master = "RHEA:99999"


def test_row_order_and_line_endings_do_not_assign_direction():
    """The named columns, not file ordering, are the role authority."""
    rows = (ROW, "34051\t80000\t45672\t12000\n")
    forward = load_reaction_families(StringIO(HEADER + "".join(rows)))
    reverse = load_reaction_families(StringIO((HEADER + "".join(reversed(rows))).replace("\n", "\r\n")))
    assert forward == tuple(reversed(reverse))


@pytest.mark.parametrize(
    "text",
    [
        "",
        HEADER,
        HEADER + "\n",
        HEADER + ROW + "\n",
        HEADER.rstrip("\n") + "\textra\n" + ROW,
        "\t".join(reversed(DIRECTIONS_HEADER)) + "\n" + ROW,
        "RHEA_ID_MASTER\tRHEA_ID_LR\tRHEA_ID_RL\tRHEA_ID_RL\n" + ROW,
        HEADER + ROW.rstrip("\n") + "\textra\n",
        HEADER + "10000\t11091\t14005\n",
        HEADER + "10000\t11091\t14005\t\n",
        HEADER + "10000\t10000\t14005\t20008\n",
        HEADER + ROW + ROW,
        HEADER + ROW + "20008\t30000\t30001\t30002\n",
        HEADER + ROW + "30000\t11091\t30001\t30002\n",
    ],
)
def test_reject_malformed_or_ambiguous_tables(text):
    """Missing cells, duplicate families and cross-family reuse cannot be certified."""
    with pytest.raises(ValueError):
        load_reaction_families(StringIO(text))


@pytest.mark.parametrize("value", ["0", "-1", "00100", "1.0", " 10000", "10000 ", "RHEA:10000", "１", '"10000"'])
def test_reject_noncanonical_identifiers(value):
    """Literal source IDs are validated without trimming, coercing, or prefix guessing."""
    with pytest.raises(ValueError, match="numeric identifiers"):
        load_reaction_families(StringIO(HEADER + ROW.replace("10000", value)))


@pytest.mark.parametrize("value", [None, 10000, "10000", "rhea:10000", "RHEA:00010", "RHEA:1.0"])
def test_direct_family_construction_has_same_identity_boundary(value):
    """Bypassing the TSV reader does not bypass the canonical identity contract."""
    with pytest.raises(ValueError, match="canonical Rhea"):
        ReactionFamily(value, "RHEA:2", "RHEA:3", "RHEA:4")


def test_valid_native_evidence_is_not_rewritten_and_does_not_infer_flux():
    """Distinct UN/BI and exact LR/RL roles remain literal with unrelated evidence intact."""
    evidence = _evidence()
    evidence["RHEA:10000"][RHEA_RDF_BASE + "citation"] = ["http://rdf.ncbi.nlm.nih.gov/pubmed/11453462"]
    before = deepcopy(evidence)
    assert validate_family_evidence(_family(), evidence) is None
    assert evidence == before
    assert _family().node_annotations("RHEA:10000")["rhea_direction"] == "UN"
    assert _family().node_annotations("RHEA:20008")["rhea_direction"] == "BI"


@pytest.mark.parametrize(
    "identifier,predicate,values",
    [
        ("RHEA:10000", "directionalReaction", ["11091"]),
        ("RHEA:10000", "directionalReaction", ["11091", "14005", "99999"]),
        ("RHEA:10000", "bidirectionalReaction", ["14005"]),
        ("RHEA:11091", "directionalReaction", ["10000"]),
        ("RHEA:10000", "side", ["10000_L"]),
        ("RHEA:10000", "side", ["other_L", "other_R"]),
        ("RHEA:10000", "substrates", ["10000_L"]),
        ("RHEA:11091", "substrates", ["10000_R"]),
        ("RHEA:11091", "products", ["10000_L"]),
        ("RHEA:11091", "side", ["10000_L", "10000_R"]),
        ("RHEA:14005", "substrates", ["10000_L"]),
        ("RHEA:14005", "products", ["10000_R"]),
        ("RHEA:20008", "substratesOrProducts", ["10000_L"]),
        ("RHEA:20008", "substratesOrProducts", ["10000_L", "other_R"]),
        ("RHEA:20008", "substrates", ["10000_L"]),
        ("RHEA:20008", "status", ["Preliminary"]),
        ("RHEA:11091", "status", ["Approved", "Obsolete"]),
    ],
)
def test_native_contradictions_fail(identifier, predicate, values):
    """Exact native links and side evidence constrain each member independently."""
    evidence = _evidence()
    evidence[identifier][RHEA_RDF_BASE + predicate] = [RHEA_RDF_BASE + value for value in values]
    with pytest.raises(ValueError, match="RDF evidence disagrees"):
        validate_family_evidence(_family(), evidence)


def test_coherently_swapped_lr_rl_still_fails():
    """Opposite directions alone are insufficient if LR/RL columns have been swapped."""
    evidence = _evidence()
    for identifier in ("RHEA:11091", "RHEA:14005"):
        record = evidence[identifier]
        a, b = RHEA_RDF_BASE + "substrates", RHEA_RDF_BASE + "products"
        record[a], record[b] = record[b], record[a]
    with pytest.raises(ValueError, match="RDF evidence disagrees"):
        validate_family_evidence(_family(), evidence)


@pytest.mark.parametrize("identifier", ["RHEA:10000", "RHEA:11091", "RHEA:14005", "RHEA:20008"])
@pytest.mark.parametrize("field", ["record", "label", "status"])
def test_every_family_member_requires_native_evidence(identifier, field):
    """A valid master cannot substitute for a missing or unapproved variant record."""
    evidence = _evidence()
    if field == "record":
        del evidence[identifier]
    else:
        del evidence[identifier][RDFS_LABEL if field == "label" else RHEA_RDF_BASE + "status"]
    with pytest.raises(ValueError):
        validate_family_evidence(_family(), evidence)


@pytest.mark.parametrize("labels", [[], [""], [" \t"], ["A = B", "different"], "A = B", [None], [1], [[]], {}, None])
def test_native_label_must_be_single_literal(labels):
    """A missing, ambiguous or scalar-container label cannot become a complete declaration."""
    evidence = _evidence()
    evidence["RHEA:10000"][RDFS_LABEL] = labels
    with pytest.raises(ValueError):
        validate_family_evidence(_family(), evidence)


@pytest.mark.parametrize("evidence", [None, [], "record"])
def test_native_evidence_requires_a_record_mapping(evidence):
    """Malformed top-level evidence fails explicitly rather than bypassing validation."""
    with pytest.raises(ValueError, match="mapping of reaction records"):
        validate_family_evidence(_family(), evidence)


def test_rdf_duplicate_triples_and_collection_order_are_semantically_irrelevant():
    """Native RDF triples form sets; duplicate serialization is not new biological evidence."""
    evidence = _evidence()
    for record in evidence.values():
        for predicate, values in record.items():
            record[predicate] = list(reversed(values)) + values
    validate_family_evidence(_family(), evidence)


@pytest.mark.parametrize("status", ["Approved", "Preliminary"])
def test_both_released_active_statuses_are_preserved_without_promotion(status):
    """A uniformly Preliminary family is complete evidence, not a dropped or approved family."""
    evidence = _evidence()
    for record in evidence.values():
        record[RHEA_RDF_BASE + "status"] = [RHEA_RDF_BASE + status]
    original = deepcopy(evidence)
    validate_family_evidence(_family(), evidence)
    assert RHEA_STATUS_FIELD == "rhea_status"
    assert validate_family_cohort([_family()], evidence) == {
        "families": 1,
        "members": 4,
        "family_status_counts": {"Approved": int(status == "Approved"), "Preliminary": int(status == "Preliminary")},
        "obsolete_ids": (),
    }
    assert evidence == original


def test_cohort_counts_two_distinct_active_states_and_explicit_obsolete_nonmembers():
    """All active families must be present; obsolete RDF-only records need no labels."""
    first = _family()
    second = ReactionFamily("RHEA:30000", "RHEA:35001", "RHEA:37002", "RHEA:45003")
    evidence = _evidence()
    second_evidence = deepcopy(evidence)
    names = dict(zip((member for member, _ in first.members), (member for member, _ in second.members), strict=True))
    for original, record in second_evidence.items():
        for predicate, values in record.items():
            record[predicate] = [value.replace(RHEA_RDF_BASE + "10000_", RHEA_RDF_BASE + "30000_") for value in values]
            for old, new in names.items():
                record[predicate] = [
                    RHEA_RDF_BASE + new.split(":")[1] if value == RHEA_RDF_BASE + old.split(":")[1] else value
                    for value in record[predicate]
                ]
        record[RHEA_RDF_BASE + "status"] = [RHEA_RDF_BASE + "Preliminary"]
        evidence[names[original]] = record
    evidence["RHEA:99002"] = {RHEA_RDF_BASE + "status": [RHEA_RDF_BASE + "Obsolete"]}
    evidence["RHEA:99001"] = {RHEA_RDF_BASE + "status": [RHEA_RDF_BASE + "Obsolete"]}
    original = deepcopy(evidence)
    assert validate_family_cohort([first, second], evidence) == {
        "families": 2,
        "members": 8,
        "family_status_counts": {"Approved": 1, "Preliminary": 1},
        "obsolete_ids": ("RHEA:99001", "RHEA:99002"),
    }
    assert evidence == original


@pytest.mark.parametrize("status", ["Approved", "Preliminary"])
def test_active_rdf_nonmember_is_not_silently_excluded(status):
    """Matching every listed family is insufficient if active RDF content was omitted."""
    evidence = _evidence()
    evidence["RHEA:99999"] = {RHEA_RDF_BASE + "status": [RHEA_RDF_BASE + status]}
    with pytest.raises(ValueError, match="missing_from_table=.*RHEA:99999"):
        validate_family_cohort([_family()], evidence)


@pytest.mark.parametrize("statuses", [[], ["Unreviewed"], ["Approved", "Preliminary"], ["Obsolete", "Approved"]])
@pytest.mark.parametrize("identifier", ["RHEA:11091", "RHEA:99999"])
def test_missing_unknown_or_ambiguous_status_fails_even_outside_table(identifier, statuses):
    """The obsolete exemption requires an exact positive singleton native status."""
    evidence = _evidence()
    evidence.setdefault(identifier, {})[RHEA_RDF_BASE + "status"] = [RHEA_RDF_BASE + value for value in statuses]
    with pytest.raises(ValueError, match="native status"):
        validate_family_cohort([_family()], evidence)


@pytest.mark.parametrize("identifier", ["RHEA:10000", "RHEA:11091", "RHEA:14005", "RHEA:20008"])
def test_mixed_family_status_cannot_be_hidden_by_cohort_counts(identifier):
    """Every family, not merely the dataset as a whole, must have one coherent status."""
    evidence = _evidence()
    evidence[identifier][RHEA_RDF_BASE + "status"] = [RHEA_RDF_BASE + "Preliminary"]
    with pytest.raises(ValueError, match="across family statuses"):
        validate_family_cohort([_family()], evidence)


def test_obsolete_family_members_cannot_be_reactivated_by_table_membership():
    """Even four coherently Obsolete records cannot pass the active family contract."""
    evidence = _evidence()
    for record in evidence.values():
        record[RHEA_RDF_BASE + "status"] = [RHEA_RDF_BASE + "Obsolete"]
    with pytest.raises(ValueError, match="native status"):
        validate_family_cohort([_family()], evidence)


@pytest.mark.parametrize("families", [[], [None], [_family(), _family()]])
def test_cohort_revalidates_direct_call_membership(families):
    """A caller cannot bypass table cardinality or uniqueness by building a list directly."""
    with pytest.raises(ValueError):
        validate_family_cohort(families, _evidence())


@pytest.mark.parametrize("identifier", ["RHEA:0001", "rhea:99999", "RHEA:Reaction", "99999"])
def test_obsolete_exemption_does_not_admit_invalid_reaction_ids(identifier):
    """The finite status exemption still requires canonical numeric reaction identity."""
    evidence = _evidence()
    evidence[identifier] = {RHEA_RDF_BASE + "status": [RHEA_RDF_BASE + "Obsolete"]}
    with pytest.raises(ValueError, match="canonical Rhea"):
        validate_family_cohort([_family()], evidence)
