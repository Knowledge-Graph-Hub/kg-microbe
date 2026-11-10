"""Candidate-only stable profile survives native finalization and archive transport."""

import csv
import hashlib
import io
import json
import tarfile
from copy import deepcopy
from importlib.resources import files

import pytest

from kg_microbe.merge_utils.artifact_manifest import file_identity, write_graph_archive
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.graph_schema import canonical_header, validate_canonical_tsv
from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.ingredient_kgx import ingredient_kgx_profile, validate_ingredient_fields
from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
from kg_microbe.utils.stable_ingredient_kgx import (
    ASSERTION_JSON,
    PREDICATES,
    STABLE_PREFIX,
    STABLE_PROFILE,
    project_stable_candidate,
    stable_graph_id,
    stable_identifier_uri,
)
from kg_microbe.utils.tsv_io import tsv_dict_writer

MANIFEST = "a" * 64


def digest(value):
    """Use the native deterministic full-row identity, including every evidence cell."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def source_payload():
    """Construct explicit synthetic judgments; this is not campaign scientific approval."""
    result = {
        "manifest_sha256": MANIFEST,
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "production_authorized": False,
        "companion_mode": "required/v1",
        "profile_sha256": hashlib.sha256(
            files("kg_microbe").joinpath("profiles/stable_source_kgx_v1.yaml").read_bytes()
        ).hexdigest(),
        "curie_map": {"MIM": STABLE_PREFIX, "MIM.ingredient": STABLE_PREFIX},
        "claims": [],
        "source_decisions": [],
        "external_supported": [],
        "external_withheld": [],
        "external_dispositions": [],
        "companion": {"mappings": [], "identifiers": [], "products": [], "occurrences": []},
        "consumer_holds": [],
    }
    for index in range(1, 7):
        owner = f"MIM:{index:07d}"
        payload = {
            "source_id": f"SOURCE:{index}",
            "mim_id": owner,
            "mapping_status": "UNMAPPED",
            "holds": [],
            "occurrences": [{"recipe": "A|B", "quantity": "2\tmg\n", "position": 1}],
        }
        binding = {
            "subject_id": f"SOURCE:{index}",
            "subject_label": f"source {index}",
            "object_id": owner,
            "object_label": f"owner {index}",
            "predicate_id": "skos:exactMatch",
            "comment": 'original evidence | quote " preserved',
        }
        decision = {
            "disposition": "SUPPORTED",
            "binding": binding,
            "payload": payload,
            "payload_sha256": digest(payload),
            "primary": {"identity": "author"},
            "skeptic": {"identity": "independent"},
        }
        result["source_decisions"].append(decision)
        result["claims"].append(
            dict(
                binding,
                original_subject_id=binding["subject_id"],
                original_object_id=owner,
                object_id=stable_graph_id(owner),
                payload_sha256=digest(payload),
            )
        )
    for index, predicate in enumerate(sorted(PREDICATES), 1):
        row = {
            "subject_id": f"MIM:{index:07d}",
            "subject_label": f"owner {index}",
            "predicate_id": predicate,
            "object_id": "CHEBI:12345",
            "object_label": "synthetic external term",
            "mapping_date": "2026-11-10",
            "source": "original:curator",
            "comment": "Preserve full exact provenance",
            "other": "alias one|alias two",
        }
        add_external(result, row, "SUPPORTED")
    held = {
        "disposition": "WITHHOLD",
        "binding": None,
        "payload_sha256": "b" * 64,
        "payload": {
            "source_id": "SOURCE:held",
            "mim_id": None,
            "holds": ["ambiguous identity"],
            "occurrences": [{"quantity": "unknown"}],
        },
    }
    result["source_decisions"].append(held)
    result["companion"]["occurrences"] = [
        {
            "occurrence_id": "MIM.occurrence:fixture",
            "owner_id": "MIM:0000001",
            "raw_name": "retained | name",
            "holds": ["not an identity approval"],
        }
    ]
    result["companion"]["identifiers"] = [
        {"owner_id": "MIM:0000001", "identifier": "cas:1-00-0", "review_status": "unreviewed"}
    ]
    return result


def add_external(payload, row, status):
    """Bind the complete source row to its independent native disposition."""
    payload["external_supported" if status == "SUPPORTED" else "external_withheld"].append(row)
    payload["external_dispositions"].append(
        {
            "row_sha256": digest(row),
            "disposition": status,
            "subject_id": row["subject_id"],
            "predicate_id": row["predicate_id"],
            "object_id": row["object_id"],
            "evidence": "synthetic reviewed source",
        }
    )


def envelopes(edges, representation=None):
    """Read actual scalar JSON transported on edges."""
    result = [json.loads(row[ASSERTION_JSON]) for row in edges]
    return [row for row in result if representation is None or row["representation"] == representation]


@pytest.mark.parametrize("value", ["MIM:0000001", "MIM.ingredient:0000001", STABLE_PREFIX + "0000001"])
def test_explicit_stable_namespace_and_legacy_independence(value):
    """Explicit ingredient expansion agrees without changing biomedical or filename namespaces."""
    assert stable_graph_id(value) == "MIM.ingredient:0000001"
    assert stable_identifier_uri(value) == STABLE_PREFIX + "0000001"
    assert compact_identifier("MIM:123456") == "MIM:123456"
    assert ingredient_kgx_profile()["prefixes"]["MIM.ingredient"].endswith("data/ingredients/mapped/")


@pytest.mark.parametrize(
    "value", ["MIM:Renamed", "MIM:0000000", "MIM:123456", "MIM:１２３４５６７", "MIM.ingredient:Renamed"]
)
def test_no_filename_or_biomedical_identity_guess(value):
    """Only positive seven-digit ingredient IDs enter the explicit profile."""
    with pytest.raises(ValueError, match="seven-digit"):
        stable_graph_id(value)


def test_projection_preserves_four_predicates_and_separate_complete_lanes():
    """Shared external IDs never replace distinct stable owners or source decisions."""
    payload = source_payload()
    nodes, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    active = envelopes(edges, "active_mapping")
    external = [row for row in active if row["lane"] == "external_mapping"]
    assert {row["payload"]["predicate_id"] for row in external} == PREDICATES
    assert len({row["payload"]["subject_id"] for row in external}) == 4
    assert len({row["payload"]["object_id"] for row in external}) == 1
    assert {row["id"] for row in nodes if row["ingredient_record_kind"] == "stable_concept"} == {
        f"MIM.ingredient:{i:07d}" for i in range(1, 7)
    }
    assert [row["payload"] for row in envelopes(edges) if row["lane"] == "source_decision"] == payload[
        "source_decisions"
    ]
    assert [
        row["payload"] for row in envelopes(edges, "information_assertion") if row["lane"] == "external_mapping"
    ] == payload["external_supported"]
    assert [row["payload"] for row in envelopes(edges) if row["lane"] == "companion"] == payload["companion"][
        "identifiers"
    ] + payload["companion"]["occurrences"]
    assert not any("subclass" in row["predicate"] for row in edges)
    assert not any(row["subject"] == "SOURCE:held" for row in edges)


def test_empty_external_product_keeps_mim_only_and_unmapped():
    """An absent ontology mapping does not suppress source identity or change UNMAPPED."""
    payload = source_payload()
    for key in ("external_supported", "external_withheld", "external_dispositions"):
        payload[key] = []
    _, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    active = envelopes(edges, "active_mapping")
    assert len(active) == 6 and {row["lane"] for row in active} == {"source_identity"}
    assert all(
        row["payload"]["payload"]["mapping_status"] == "UNMAPPED"
        for row in envelopes(edges)
        if row["lane"] == "source_decision" and row["payload"]["disposition"] == "SUPPORTED"
    )


def test_publisher_support_does_not_override_consumer_or_source_holds():
    """Separate consumer holds suppress active external edges while retaining the original support."""
    payload = source_payload()
    row = payload["external_supported"][0]
    payload["consumer_holds"] = [
        {
            "owner_id": row["subject_id"],
            "row_sha256": digest(row),
            "reason": "reviewed predecessor hold",
            "legacy_subject": "MIM:old_label",
            "review": "fixture:lineage",
        }
    ]
    withheld = dict(row, subject_id="MIM:0000005", comment="unresolved external proposal")
    add_external(payload, withheld, "WITHHOLD")
    _, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    external = [item for item in envelopes(edges, "active_mapping") if item["lane"] == "external_mapping"]
    assert len(external) == 3
    retained = [item for item in envelopes(edges, "information_assertion") if item["lane"] == "external_mapping"]
    assert retained[0]["native_disposition"] == "SUPPORTED" and retained[0]["consumer_disposition"] == "WITHHOLD"
    assert retained[0]["payload"] == row and retained[0]["consumer_holds"] == payload["consumer_holds"]
    assert retained[-1]["payload"] == withheld and retained[-1]["native_disposition"] == "WITHHOLD"
    assert len([item for item in envelopes(edges, "active_mapping") if item["lane"] == "source_identity"]) == 6


def test_owner_hold_does_not_spread_through_shared_external_identifier():
    """An explicit predecessor hold affects one owner, never everyone sharing CHEBI:86658."""
    payload = source_payload()
    for key in ("external_supported", "external_withheld", "external_dispositions"):
        payload[key] = []
    for owner in ("MIM:0000001", "MIM:0000002"):
        add_external(
            payload,
            {
                "subject_id": owner,
                "object_id": "CHEBI:86658",
                "predicate_id": "skos:exactMatch",
                "comment": "original independent row",
            },
            "SUPPORTED",
        )
    payload["consumer_holds"] = [
        {
            "owner_id": "MIM:0000001",
            "legacy_subject": "MIM:old_label",
            "reason": "explicit native-verified lineage hold",
        }
    ]
    _, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    active = [item for item in envelopes(edges, "active_mapping") if item["lane"] == "external_mapping"]
    assert [item["payload"]["subject_id"] for item in active] == ["MIM:0000002"]
    audit = [item for item in envelopes(edges, "information_assertion") if item["lane"] == "external_mapping"]
    assert len(audit) == 2
    assert sum(item["consumer_disposition"] == "WITHHOLD" for item in audit) == 1
    assert all(item["native_disposition"] == "SUPPORTED" for item in audit)
    assert len([item for item in envelopes(edges, "active_mapping") if item["lane"] == "source_identity"]) == 6


@pytest.mark.parametrize(
    "mutation",
    ["fingerprint", "prefix", "missing_claim", "held_claim", "duplicate_claim", "external_decision", "subclass"],
)
def test_missing_or_cross_lane_authority_refused(mutation):
    """Transport requires complete exact joins; unrelated external support cannot admit a source."""
    payload = source_payload()
    if mutation == "fingerprint":
        payload["manifest_sha256"] = "b" * 64
    elif mutation == "prefix":
        payload["curie_map"]["MIM.ingredient"] = "https://example.invalid/wrong/"
    elif mutation == "missing_claim":
        payload["claims"].pop()
    elif mutation == "held_claim":
        payload["source_decisions"][0]["disposition"] = "WITHHOLD"
    elif mutation == "duplicate_claim":
        payload["claims"].append(deepcopy(payload["claims"][0]))
    elif mutation == "external_decision":
        payload["external_dispositions"].pop()
    else:
        payload["external_supported"][0]["predicate_id"] = "rdfs:subClassOf"
    with pytest.raises(ValueError):
        project_stable_candidate(payload, manifest_sha256=MANIFEST)


@pytest.mark.parametrize("mutation", ["profile", "digest", "scalar", "predicate", "endpoints", "hold"])
def test_native_boundary_rejects_invalid_stable_extensions(mutation):
    """The existing validator dispatch retains strict stable-profile assertions."""
    _, edges = project_stable_candidate(source_payload(), manifest_sha256=MANIFEST)
    row = next(row for row in edges if json.loads(row[ASSERTION_JSON])["representation"] == "active_mapping")
    if mutation == "profile":
        row["ingredient_profile"] = STABLE_PROFILE + "-unknown"
    elif mutation == "digest":
        row["ingredient_bundle_sha256"] = "bad"
    elif mutation == "scalar":
        row[ASSERTION_JSON] = json.loads(row[ASSERTION_JSON])
    elif mutation == "predicate":
        row["predicate"] = "biolink:subclass_of"
    elif mutation == "endpoints":
        row["object"] = "CHEBI:12345"
    else:
        value = json.loads(row[ASSERTION_JSON])
        value["consumer_holds"] = [{"reason": "held"}]
        row[ASSERTION_JSON] = canonical_json(value).decode()
    with pytest.raises(ValueError):
        validate_ingredient_fields(row, is_node=False)


def test_native_finalization_archive_and_reload_preserve_scalar_claims(tmp_path, local_source_schema):
    """Exercise real finalization and atomic archive APIs, never a transform run or KG merge."""
    payload = source_payload()
    payload["consumer_holds"] = [
        {"owner_id": "MIM:0000006", "reason": "synthetic terminal hold; no external authority"}
    ]
    nodes, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    raw = tmp_path / "raw"
    raw.mkdir()
    source = Transform("stable_source_candidate_fixture", raw, tmp_path / "candidate")
    source.TSV_QUOTING = csv.QUOTE_NONE
    input_path = raw / "source-payload.json"
    input_path.write_bytes(canonical_json(payload))
    with source.consume_input("native_source_payload", input_path) as stream:
        assert json.load(stream) == payload
    for path, rows, is_node in ((source.output_node_file, nodes, True), (source.output_edge_file, edges, False)):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = tsv_dict_writer(
                stream, fieldnames=canonical_header(rows[0], is_node), quoting=csv.QUOTE_NONE, quotechar=None
            )
            writer.writeheader()
            writer.writerows(rows)
    source.finalize(fresh_run=True)
    paths = [source.output_node_file, source.output_edge_file]
    verify_finalized_source_files(paths)
    for path, is_node in zip(paths, (True, False), strict=True):
        validate_canonical_tsv(path, is_node=is_node)
    finalized = list(graph_rows(source.output_edge_file))
    assert envelopes(finalized) == envelopes(edges)
    assert {row["predicate"] for row in finalized if row["predicate"] != "biolink:related_to"} == PREDICATES
    identities = {path.name: file_identity(path) for path in paths}
    archive_path = tmp_path / "stable-candidate.tar.gz"
    provenance = {
        "mode": "candidate_only",
        "production_authorized": False,
        "profile": STABLE_PROFILE,
        "source_manifest_sha256": MANIFEST,
    }
    write_graph_archive(archive_path, paths, provenance, expected_members=identities)
    with tarfile.open(archive_path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert manifest["members"] == identities and manifest["provenance"] == provenance
        content = archive.extractfile("edges.tsv").read()
        assert hashlib.sha256(content).hexdigest() == identities["edges.tsv"]["sha256"]
        reloaded = list(csv.DictReader(io.StringIO(content.decode()), delimiter="\t", quoting=csv.QUOTE_NONE))
    assert reloaded == finalized
    assert envelopes(reloaded) == envelopes(edges)
    for row in reloaded:
        validate_ingredient_fields(row, is_node=False)


@pytest.mark.parametrize("mode", ["required/v1", "absent/v1"])
def test_explicit_companion_mode_survives_in_graph_context(mode):
    """Graph context carries the explicit mode; absent mode supplies no companion facts."""
    payload = source_payload()
    payload["companion_mode"] = mode
    payload["selection_sha256"] = "c" * 64
    if mode == "absent/v1":
        payload["companion"] = None
    _, edges = project_stable_candidate(payload, manifest_sha256=MANIFEST)
    context = [item for item in envelopes(edges) if item["lane"] == "candidate_context"]
    assert len(context) == 1
    assert context[0]["representation"] == "information_assertion"
    assert context[0]["payload"] == {
        "companion_mode": mode,
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "production_authorized": False,
        "source_manifest_sha256": MANIFEST,
        "profile_sha256": payload["profile_sha256"],
        "profile_id": STABLE_PROFILE,
        "profile_version": 1,
        "selection_sha256": "c" * 64,
    }
    companion = [item for item in envelopes(edges) if item["lane"] == "companion"]
    assert len(companion) == (0 if mode == "absent/v1" else 2)
    assert len([item for item in envelopes(edges) if item["lane"] == "source_identity"]) == 6


@pytest.mark.parametrize(
    "case",
    [
        "missing_mode",
        "unknown_mode",
        "required_none",
        "required_incomplete",
        "absent_dict",
        "absent_missing",
        "status",
        "selection",
        "profile",
    ],
)
def test_companion_mode_is_never_inferred_or_used_as_error_fallback(case):
    """Contradictory, missing or unversioned companion choices fail before projection."""
    payload = source_payload()
    if case == "missing_mode":
        del payload["companion_mode"]
    elif case == "unknown_mode":
        payload["companion_mode"] = "absent/v2"
    elif case == "required_none":
        payload["companion"] = None
    elif case == "required_incomplete":
        del payload["companion"]["occurrences"]
    elif case == "absent_dict":
        payload["companion_mode"] = "absent/v1"
        payload["companion"] = {key: [] for key in ("mappings", "identifiers", "products", "occurrences")}
    elif case == "absent_missing":
        payload["companion_mode"] = "absent/v1"
        del payload["companion"]
    elif case == "status":
        payload["status"] = "PRODUCTION_ACCEPTED"
    elif case == "profile":
        payload["profile_sha256"] = "0" * 64
    else:
        payload["selection_sha256"] = "bad"
    with pytest.raises(ValueError):
        project_stable_candidate(payload, manifest_sha256=MANIFEST)


@pytest.mark.parametrize(
    "field,value",
    [
        ("companion_mode", "absent/v2"),
        ("source_manifest_sha256", "b" * 64),
        ("profile_sha256", "b" * 64),
        ("production_authorized", True),
        ("status", "PRODUCTION_ACCEPTED"),
    ],
)
def test_native_scalar_boundary_rejects_tampered_candidate_context(field, value):
    """Native TSV validation preserves context identity and explicit candidate-only status."""
    _, edges = project_stable_candidate(source_payload(), manifest_sha256=MANIFEST)
    row = next(row for row in edges if json.loads(row[ASSERTION_JSON])["lane"] == "candidate_context")
    envelope = json.loads(row[ASSERTION_JSON])
    envelope["payload"][field] = value
    row[ASSERTION_JSON] = canonical_json(envelope).decode()
    with pytest.raises(ValueError, match="Candidate context"):
        validate_ingredient_fields(row, is_node=False)


def test_new_profile_context_rechecks_bytes_without_cached_parse(tmp_path, monkeypatch):
    """A changed private profile cannot inherit a prior successful profile read."""
    from kg_microbe.utils import stable_ingredient_kgx as stable

    profile = tmp_path / "profiles/stable_source_kgx_v1.yaml"
    profile.parent.mkdir()
    original = files("kg_microbe").joinpath("profiles/stable_source_kgx_v1.yaml").read_bytes()
    profile.write_bytes(original)
    monkeypatch.setattr(stable, "files", lambda package: tmp_path)
    assert stable.stable_ingredient_kgx_profile()["profile_id"] == STABLE_PROFILE
    first_hash = stable.stable_profile_sha256()
    profile.write_bytes(original.replace(b"profile_version: 1", b"profile_version: 2"))
    assert stable.stable_profile_sha256() != first_hash
    with pytest.raises(ValueError, match="Unsupported stable ingredient profile"):
        stable.stable_ingredient_kgx_profile()
