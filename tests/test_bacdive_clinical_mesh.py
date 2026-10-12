"""Finite clinical classification identities remain native-grounded and wholly upstream."""

import copy
import csv
import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import clinical_categories as clinical
from kg_microbe.transform_utils.bacdive import isolation_categories as pride
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import clinical_mesh_categories as authority
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.test_bacdive_isolation_categories import CATEGORIES, SECTION, _run

FIXTURE = Path(__file__).parent / "resources/bacdive_clinical_mesh"


def _policy():
    """Read the actual code-pinned curated policy without fixture-specific authority substitution."""
    with authority.CLINICAL_MESH_POLICY_FILE.open() as stream:
        return authority.load_clinical_mesh_policy(stream)


def _native():
    """Use an explicitly documented complete selected-subject excerpt, not a fictional full file hash."""
    return (FIXTURE / "mesh2026-clinical-excerpt.nt").read_bytes()


def _evidence(native=None):
    """Exercise gzip/native parsing on real selected RDF bytes."""
    return authority.load_clinical_mesh_evidence(
        _policy(), io.BytesIO(gzip.compress(_native() if native is None else native, mtime=0))
    )


def _records():
    """Exclude fixture-only provenance metadata from the literal saved source records."""
    return [
        {key: value for key, value in row.items() if key != "native_array_index"}
        for row in json.loads((FIXTURE / "records.json").read_text())["records"]
    ]


def _audit(transform):
    """Read actual producer-owned clinical audit bytes."""
    return list(graph_rows(Path(transform.output_dir) / clinical.AUDIT_FILE))


def test_exact_native_definitions_support_only_two_finite_site_projections():
    """Process/injury tags are not promoted to physical entities, and pocket sites are not human-only."""
    evidence = _evidence()
    assert {key: row.category for key, row in evidence.items()} == {
        "mesh:D000038": "biolink:PhysicalEntity",
        "mesh:D010514": "biolink:PathologicalAnatomicalStructure",
    }
    assert len(_native().splitlines()) == 228
    assert {row["General"]["BacDive-ID"] for row in _records()} >= {12504, 132848, 132849}
    assert b"Accumulation of purulent material" in _native()
    assert b"An abnormal extension of a gingival sulcus" in _native()
    for decision in evidence.values():
        assert decision.native_statements_sha256 == authority.NATIVE_STATEMENTS_SHA256
        assert (
            authority.apply_clinical_mesh_category("biolink:Disease|biolink:OntologyClass", decision)
            == decision.category
        )
        assert authority.apply_clinical_mesh_category(decision.category, decision) == decision.category
        with pytest.raises(ValueError, match="substantive category"):
            authority.apply_clinical_mesh_category("biolink:ChemicalEntity", decision)


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "definition", "release", "preferred-concept", "additional", "tabbed-extra"]
)
def test_actual_native_evidence_drift_aborts(damage):
    """A changed native claim cannot be legalized by merely restamping policy metadata."""
    native = _native()
    if damage == "missing":
        native = b"\n".join(native.splitlines()[1:]) + b"\n"
    elif damage == "duplicate":
        native += native.splitlines()[0] + b"\n"
    elif damage == "definition":
        native = native.replace(b"Accumulation of purulent material", b"A fictitious diagnostic process")
    elif damage == "release":
        native = native.replace(b"/mesh/2026/", b"/mesh/2025/")
    elif damage == "preferred-concept":
        native = native.replace(b"/2026/M0000059>", b"/2026/M0023019>", 1)
    elif damage == "additional":
        native += b'<http://id.nlm.nih.gov/mesh/2026/D000038> <http://example.org/obsolete> "true" .\n'
    else:
        native += b' \t<http://id.nlm.nih.gov/mesh/2026/D000038>\t<http://example.org/obsolete> "true" .\n'
    with pytest.raises(ValueError, match="Clinical MeSH native"):
        _evidence(native)


@pytest.mark.parametrize(
    "subject",
    [
        r"http://id.nlm.nih.gov/mesh/2026/D00003\u0038",
        r"http://id.nlm.nih.gov/mesh/2026/\U00000044000038",
        r"http://id.nlm.nih.gov/mesh/2026/M000005\u0039",
        r"http://id.nlm.nih.gov/mesh/2026\u002FD000038",
        r"http://id.nlm.nih.gov/mesh/2026/\uD800",
        r"http://id.nlm.nih.gov/mesh/2026/\U00110000",
        r"http://id.nlm.nih.gov/mesh/2026/\uZZZZ",
    ],
)
def test_escaped_subjects_cannot_hide_additional_selected_native_claims(subject):
    """Select semantic IRI identity first but retain original statement spelling in the pin."""
    additional = f'<{subject}> <http://www.w3.org/2000/01/rdf-schema#label> "changed" .\n'.encode()
    with pytest.raises(ValueError, match="Clinical MeSH native"):
        _evidence(_native() + additional)


@pytest.mark.parametrize("damage", ["rule-deleted", "category", "action", "digest", "duplicate-key", "raw-path"])
def test_policy_cohort_and_scientific_decisions_fail_closed(damage):
    """The entire finite rule cohort and evidence identity are code-bound, not self-authenticating."""
    policy = _policy()
    if damage == "rule-deleted":
        policy["rules"].pop()
    elif damage == "category":
        policy["rules"][0]["projection"] = "biolink:PathologicalAnatomicalStructure"
    elif damage == "action":
        policy["rules"][1]["action"] = "retain_source_site"
    elif damage == "digest":
        policy["selected_native_statements_sha256"] = "0" * 64
    elif damage == "raw-path":
        policy["rules"][0]["category"]["Cat1"] = "#Infection"
    text = json.dumps(policy)
    if damage == "duplicate-key":
        text = text.replace('"version": 1', '"version": 1, "version": 1')
    with pytest.raises(ValueError, match="policy"):
        authority.load_clinical_mesh_policy(io.StringIO(text))


def test_actual_run_conserves_every_native_occurrence_and_pride_identity(tmp_path, monkeypatch):
    """All four paths are audited, sites stay exact, and original full blocks preserve existing PRIDE IDs."""
    records = _records()
    before = copy.deepcopy(records)
    transform, edges, nodes, pride_audit = _run(tmp_path, monkeypatch, records)
    audit = _audit(transform)
    assert records == before
    originals = {f"kgmicrobe.strain:bacdive_{record['General']['BacDive-ID']}": record for record in records}
    wanted = {rule["category"][rule["field"]]: rule for rule in _policy()["rules"]}
    expected = Counter(
        value
        for record in records
        for category in record[SECTION][CATEGORIES]
        for value in category.values()
        if value in wanted
    )
    assert Counter(row["raw_value"] for row in audit) == expected
    emitted_sites = []
    observed_attributes = set()
    for row in audit:
        original, emitted = json.loads(row["original_edge_json"]), json.loads(row["emitted_edge_json"])
        section = originals[row["organism_id"]][SECTION]
        source_path = json.loads(row["source_path_json"])
        assert json.loads(row["source_isolation_json"]) == section
        assert json.loads(row["source_category_json"]) == section[CATEGORIES][source_path[2]]
        assert row["raw_value"] == json.loads(row["source_category_json"])[json.loads(row["source_path_json"])[-1]]
        assert any(all(edge[key] == value for key, value in emitted.items()) for edge in edges)
        assert emitted["knowledge_level"] == "observation" and emitted["agent_type"] == "manual_agent"
        assert set(json.loads(row["consumed_inputs_json"])) == {
            *clinical.REQUIRED_INPUTS,
            *pride.REQUIRED_INPUTS,
            pride.RAW_INPUT,
        }
        if row["status"] == "retain_source_site":
            assert emitted == original
            assert not row["attribute_id"] and not row["attribute_type"]
            emitted_sites.append(emitted["subject"])
        else:
            assert original["subject"] in {"mesh:D007249", "mesh:D014947"}
            assert emitted["predicate"] == "biolink:has_attribute"
            assert row["attribute_type"] == pride.ATTRIBUTE_TYPE
            observed_attributes.add(row["attribute_id"])
    assert Counter(
        edge["subject"] for edge in edges if edge["subject"] in authority.CLINICAL_MESH_IDENTIFIERS
    ) == Counter(emitted_sites)
    assert not any(edge["subject"] in {"mesh:D007249", "mesh:D014947"} for edge in edges)
    assert {row["id"] for row in nodes if row["id"] in observed_attributes} == observed_attributes
    expected_pride = set()
    for organism, record in originals.items():
        for index, category in enumerate(record[SECTION][CATEGORIES]):
            if category.get("Cat1") in {"#Host Body-Site", "#Host Body Product"}:
                witness = {
                    "organism_id": organism,
                    "source_path": [SECTION, CATEGORIES, index, "Cat1"],
                    "category": category,
                }
                expected_pride.add(
                    "kgmicrobe.isolation_category:" + hashlib.sha256(pride._json(witness).encode()).hexdigest()
                )
    assert {row["attribute_id"] for row in pride_audit} == expected_pride
    for row in pride_audit:
        witness = {
            "organism_id": row["organism_id"],
            "source_path": json.loads(row["source_path_json"]),
            "category": json.loads(row["source_category_json"]),
        }
        assert (
            row["attribute_id"]
            == "kgmicrobe.isolation_category:" + hashlib.sha256(pride._json(witness).encode()).hexdigest()
        )
    transform.verify_consumed_inputs()
    verify_producer_audits(transform)


@pytest.mark.parametrize("as_dict", [False, True])
def test_repeated_positions_and_original_dict_shape_are_lossless(tmp_path, monkeypatch, as_dict):
    """Repeated positions remain in attributes/audit; ordinary producer graph deduplication remains unchanged."""
    categories = [copy.deepcopy(rule["category"]) for rule in _policy()["rules"]]
    record = {"General": {"BacDive-ID": 194}, SECTION: {CATEGORIES: categories * 2}}
    if as_dict:
        record[SECTION][CATEGORIES] = categories[1]
    transform, edges, _, pride_audit = _run(tmp_path, monkeypatch, [record])
    audit = _audit(transform)
    assert len(audit) == (1 if as_dict else 8)
    attributes = [row["attribute_id"] for row in audit if row["attribute_id"]]
    assert len(attributes) == len(set(attributes)) == (1 if as_dict else 4)
    assert len([edge for edge in edges if edge["subject"] in authority.CLINICAL_MESH_IDENTIFIERS]) == (
        0 if as_dict else 2
    )
    assert len([row for row in audit if row["status"] == "retain_source_site"]) == (0 if as_dict else 4)
    if as_dict:
        assert json.loads(audit[0]["source_path_json"]) == [SECTION, CATEGORIES, "Cat2"]
    else:
        assert len(pride_audit) == 6


@pytest.mark.parametrize("damage", ["field", "path", "case", "whitespace", "extra-field", "sanitizer"])
def test_source_scope_drift_does_not_enter_legacy_fallback(tmp_path, monkeypatch, damage):
    """A similar label in a new raw context requires review rather than an automatic site identity."""
    category = copy.deepcopy(_policy()["rules"][-1]["category"])
    if damage == "field":
        category["Cat2"] = category.pop("Cat3")
    elif damage == "path":
        category["Cat2"] = "#Infection"
    elif damage == "case":
        category["Cat3"] = "#wound"
    elif damage == "whitespace":
        category["Cat3"] += " "
    elif damage == "extra-field":
        category["Cat4"] = "#New"
    else:
        category["Cat3"] = '#Wou"nd'
    with pytest.raises(ValueError, match="clinical isolation source"):
        _run(tmp_path, monkeypatch, [{"General": {"BacDive-ID": 194}, SECTION: {CATEGORIES: [category]}}])


def test_wound_fluid_and_other_literal_routes_are_not_intercepted(tmp_path, monkeypatch):
    """The reviewed Wound label does not generalize to Wound fluid or unrelated leaves."""
    record = {"General": {"BacDive-ID": 194}, SECTION: {CATEGORIES: {"Cat3": "#Wound-fluid"}}}
    transform, edges, _, _ = _run(tmp_path, monkeypatch, [record])
    assert not _audit(transform)
    assert len(edges) == 1 and edges[0]["predicate"] == "biolink:location_of"


def test_empty_cohort_still_requires_real_native_inputs_and_audit(tmp_path, monkeypatch):
    """An empty current cohort does not bypass the producer contract or manufacture evidence receipts."""
    transform, _, _, _ = _run(tmp_path, monkeypatch, [])
    assert not _audit(transform)
    assert set(clinical.REQUIRED_INPUTS) <= transform.consumed_input_snapshots.keys()
    assert clinical.AUDIT_FILE in transform.producer_audit_snapshots
    transform.verify_consumed_inputs()
    verify_producer_audits(transform)
    transform._consumed_input_snapshots.pop(clinical.REQUIRED_INPUTS[1])
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["native", "audit"])
def test_completed_emission_cannot_restamp_changed_evidence(tmp_path, monkeypatch, damage):
    """Native and audit bytes remain bound after the producer finishes."""
    transform, _, _, _ = _run(tmp_path, monkeypatch, _records())
    path = tmp_path / "raw/mesh2026.nt.gz" if damage == "native" else Path(transform.output_dir) / clinical.AUDIT_FILE
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs() if damage == "native" else verify_producer_audits(transform)


@pytest.mark.parametrize("target", ["Inflammation", "Wound", "Abscess", "Periodontal-pocket"])
def test_mapping_identity_drift_is_rejected_before_graph_open(tmp_path, monkeypatch, target):
    """Neither unresolved legacy fallbacks nor a changed retained site can bypass admitted mapping checks."""
    mapping_path = tmp_path / "mapping.tsv"
    lines = pride.MAPPING_PATH.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(target + "\t"):
            values = line.split("\t")
            values[2] = "mesh:D000001"
            lines[index] = "\t".join(values)
    mapping_path.write_text("\n".join(lines) + "\n")
    original = pride.prepare_policy

    def prepare(transform):
        """Read actual temporary mapping bytes with the normal consumed-input hook."""
        return original(transform, mapping_path=mapping_path)

    monkeypatch.setattr(pride, "prepare_policy", prepare)
    with pytest.raises(ValueError, match="clinical isolation"):
        _run(tmp_path, monkeypatch, _records())
    assert not (tmp_path / "transformed/bacdive/nodes.tsv").exists()


@pytest.mark.parametrize("identity", [None, "", 0, -1, True, "0194", "194/other"])
def test_clinical_source_record_identity_cannot_be_invented(tmp_path, monkeypatch, identity):
    """Use the Infection leaf to exercise clinical identity checks before any PRIDE heading hook."""
    record = {"General": {"BacDive-ID": identity}, SECTION: {CATEGORIES: _policy()["rules"][1]["category"]}}
    expected = (
        r"^BacDive taxonomy evidence: native record lacks its BacDive ID$"
        if identity == ""
        else "BacDive record identity"
    )
    with pytest.raises(ValueError, match=expected):
        _run(tmp_path, monkeypatch, [record])


@pytest.mark.parametrize("provider", ["infores:mesh", "infores:gold"])
def test_actual_source_finalization_converges_imported_and_native_copies(tmp_path, provider):
    """Source finalization performs and audits finite changes, preserving every edge and original category."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "mesh2026.nt.gz").write_bytes(gzip.compress(_native(), mtime=0))
    producer = Transform("fixture", raw, tmp_path / "transformed")
    with producer.output_node_file.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "category", "name", "provided_by"])
        writer.writerow(["mesh:D000038", "biolink:Disease", "Abscess", provider])
        writer.writerow(["mesh:D010514", "biolink:Disease|biolink:OntologyClass", "Periodontal Pocket", provider])
    producer.output_edge_file.write_text("subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n")
    report = producer.finalize()
    nodes = list(graph_rows(producer.output_node_file))
    assert {row["id"]: row["category"] for row in nodes} == {key: item.category for key, item in _evidence().items()}
    assert all(row["provided_by"] == provider for row in nodes)
    audits = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    assert len(audits) == 2
    assert all("biolink:Disease" in json.loads(row["original_row_json"])["category"] for row in audits)
    assert {Path(row["path"]).name for row in report["consumed_inputs"].values()} == {
        "mesh2026.nt.gz",
        "bacdive_clinical_mesh_policy.json",
    }
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
