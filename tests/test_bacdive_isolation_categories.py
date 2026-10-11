"""BacDive headings remain source observations without invented PRIDE/physical identity."""

import copy
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import isolation_categories as policy_module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.isolation_source_mapping_utils import load_isolation_source_mappings
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_bacdive_run_references import _run_fixture

FIXTURE = Path(__file__).parent / "resources/bacdive_isolation_categories.json"
SECTION = "Isolation, sampling and environmental information"
CATEGORIES = "isolation source categories"


def _records():
    """Use only saved literal native record excerpts, not invented passing biology."""
    return json.loads(FIXTURE.read_text())["records"]


def _run(tmp_path, monkeypatch, records, during_prepare=None):
    """Run the production emitter and real policy reader with tiny offline ontology context."""
    captured = []
    real_prepare = policy_module.prepare_policy

    def prepare(transform):
        """Supply only unrelated constructor context skipped by the existing tiny run harness."""
        captured.append(transform)
        transform.isolation_source_mappings = load_isolation_source_mappings()
        transform.ncbitaxon_labels = {}
        result = real_prepare(transform)
        if during_prepare:
            during_prepare(transform, result)
        return result

    monkeypatch.setattr(policy_module, "prepare_policy", prepare)
    edges, nodes = _run_fixture(tmp_path, monkeypatch, records)
    transform = captured[0]
    with (Path(transform.output_dir) / policy_module.AUDIT_FILE).open() as stream:
        audit = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    return transform, edges, nodes, audit


def _counter(rows):
    """Compare entire serialized rows independently of producer sorting."""
    return Counter(json.dumps(row, sort_keys=True) for row in rows)


def test_native_targets_are_metadata_context_not_cross_kingdom_source_identity():
    """Pin both human-context native parents and genuine plant/nonhuman source counterexamples."""
    with policy_module.POLICY_PATH.open() as stream:
        policy = policy_module.load_policy(stream)
    assert policy["native_authority"]["sha256"] == "11a3d2ad9bf36221b3329b4d9abd633f1f4dcd9be79d1a800ab45e0d3bff4001"
    assert "human biological" in policy["native_authority"]["stanzas"]["NCIT:C12219"]
    records = _records()
    assert "koala faeces" in records[0][SECTION]["isolation"]["sample type"]
    assert records[1][SECTION][CATEGORIES][1]["Cat2"] == "#Plant"
    assert records[-1][SECTION][CATEGORIES][-1]["Cat2"] == "#Plant"
    mappings = load_isolation_source_mappings()
    assert "host body site" not in mappings and "host body product" not in mappings


def test_actual_run_retains_each_heading_and_all_other_assertions(tmp_path, monkeypatch):
    """Six raw heading occurrences become six attributes; all Cat2/3 and other nodes/edges stay exact."""
    records = _records()
    before = copy.deepcopy(records)
    stripped = copy.deepcopy(records)
    for record in stripped:
        for category in record[SECTION][CATEGORIES]:
            if category.get("Cat1") in {"#Host Body Product", "#Host Body-Site"}:
                category.pop("Cat1")
    baseline_dir, candidate_dir = tmp_path / "baseline", tmp_path / "candidate"
    baseline_dir.mkdir()
    candidate_dir.mkdir()
    _, baseline_edges, baseline_nodes, baseline_audit = _run(baseline_dir, monkeypatch, stripped)
    monkeypatch.undo()
    transform, edges, nodes, audit = _run(candidate_dir, monkeypatch, records)
    assert records == before
    assert not baseline_audit
    attrs = [node for node in nodes if node["id"].startswith("kgmicrobe.isolation_category:")]
    attr_ids = {node["id"] for node in attrs}
    attr_edges = [edge for edge in edges if edge["object"] in attr_ids]
    assert len(attrs) == len(attr_ids) == len(attr_edges) == len(audit) == 6
    assert {node["category"] for node in attrs} == {"biolink:Attribute"}
    assert {node["has_attribute_type"] for node in attrs} == {policy_module.ATTRIBUTE_TYPE}
    attribute_types = [node for node in nodes if node["id"] == policy_module.ATTRIBUTE_TYPE]
    assert len(attribute_types) == 1 and attribute_types[0]["category"] == "biolink:OntologyClass"
    assert _counter(edge for edge in edges if edge["object"] not in attr_ids) == _counter(baseline_edges)
    assert _counter(node for node in nodes if node["id"] not in attr_ids | {policy_module.ATTRIBUTE_TYPE}) == _counter(
        baseline_nodes
    )
    assert not any("PRIDE:" in edge["subject"] or "PRIDE:" in edge["object"] for edge in edges)
    indexed_edges = {edge["object"]: edge for edge in attr_edges}
    for row in audit:
        original = json.loads(row["original_edge_json"])
        replacement = json.loads(row["emitted_edge_json"])
        assert original["predicate"] == "biolink:location_of"
        assert original["subject"] in {"PRIDE:0000685", "PRIDE:0000686"}
        assert replacement["subject"] == original["object"] == row["organism_id"]
        assert replacement["predicate"] == "biolink:has_attribute"
        assert replacement["relation"] == "SIO:000008"
        assert replacement["knowledge_level"] == "observation"
        assert replacement["agent_type"] == "manual_agent"
        assert all(indexed_edges[row["attribute_id"]][key] == value for key, value in replacement.items())
        assert json.loads(row["source_category_json"])["Cat1"] == row["raw_value"]
        assert row["attribute_type"] == policy_module.ATTRIBUTE_TYPE
        assert json.loads(row["source_path_json"])[-1] == "Cat1"
        snapshots = json.loads(row["consumed_inputs_json"])
        assert snapshots == {
            role: transform.consumed_input_snapshots[role]
            for role in (*policy_module.REQUIRED_INPUTS, policy_module.RAW_INPUT)
        }
    verify_producer_audits(transform)


def test_repeated_positions_and_distinct_records_have_stable_distinct_identity(tmp_path, monkeypatch):
    """Exact duplicate source blocks remain separate observations, including across records."""
    record = _records()[1]
    category = record[SECTION][CATEGORIES][-1]
    record[SECTION][CATEGORIES] = [copy.deepcopy(category), copy.deepcopy(category)]
    other = copy.deepcopy(record)
    other["General"]["BacDive-ID"] = 93
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _, edges1, nodes1, audit1 = _run(first, monkeypatch, [record, other])
    monkeypatch.undo()
    _, edges2, nodes2, audit2 = _run(second, monkeypatch, [other, record])
    assert len({row["attribute_id"] for row in audit1}) == 4
    assert _counter(edges1) == _counter(edges2) and _counter(nodes1) == _counter(nodes2)
    assert {row["attribute_id"] for row in audit1} == {row["attribute_id"] for row in audit2}


def test_dict_category_keeps_literal_path_without_list_index(tmp_path, monkeypatch):
    """Native producer supports both source container shapes without inventing a list ordinal."""
    record = _records()[1]
    record[SECTION][CATEGORIES] = record[SECTION][CATEGORIES][-1]
    _, _, _, audit = _run(tmp_path, monkeypatch, [record])
    assert json.loads(audit[0]["source_path_json"]) == [SECTION, CATEGORIES, "Cat1"]


@pytest.mark.parametrize("damage", ["wrong-field", "whitespace", "case", "unknown-container", "nonobject-entry"])
def test_reviewed_scope_drift_cannot_reenter_placeholder_route(tmp_path, monkeypatch, damage):
    """Near-matches and misplaced headings require review rather than becoming false environmental sites."""
    record = _records()[1]
    category = record[SECTION][CATEGORIES][-1]
    if damage == "wrong-field":
        category["Cat2"] = category.pop("Cat1")
    elif damage == "whitespace":
        category["Cat1"] += " "
    elif damage == "case":
        category["Cat1"] = category["Cat1"].lower()
    elif damage == "unknown-container":
        record[SECTION][CATEGORIES] = "#Host Body Product"
    else:
        record[SECTION][CATEGORIES] = ["#Host Body Product"]
    with pytest.raises(ValueError, match="category"):
        _run(tmp_path, monkeypatch, [record])


@pytest.mark.parametrize("mutation", ["commit", "target", "field", "duplicate", "sha256", "missing-native-parent"])
def test_policy_rejects_changed_or_ambiguous_authority(mutation):
    """No wildcard labels, mutable URL or unsupported target can inherit the finite reviewed policy."""
    policy = json.loads(policy_module.POLICY_PATH.read_text())
    if mutation == "commit":
        policy["native_authority"]["commit"] = "master"
    elif mutation == "target":
        policy["rules"][0]["rejected_mapping"]["object_id"] = "PRIDE:0000685"
    elif mutation == "field":
        policy["rules"][0]["raw_field"] = "Cat2"
    elif mutation == "duplicate":
        policy["rules"][1] = policy["rules"][0]
    elif mutation == "sha256":
        policy["native_authority"]["sha256"] = "0" * 64
    else:
        policy["native_authority"]["stanzas"]["PRIDE:0000686"] = "[Term]\nid: PRIDE:0000686\n"
    with pytest.raises(ValueError):
        policy_module.load_policy(io.StringIO(json.dumps(policy)))


def test_mapping_reintroduction_fails_before_graph_open(tmp_path, monkeypatch):
    """A newly reintroduced exact identity cannot be silently overridden or emitted."""
    original = policy_module.prepare_policy
    mapping_path = tmp_path / "mapping.tsv"
    text = policy_module.MAPPING_PATH.read_text().replace(
        "Host-Body-Product\thost body product\t\t", "Host-Body-Product\thost body product\tPRIDE:0000686\t"
    )
    mapping_path.write_text(text)

    def prepare(transform):
        """Keep actual consumed snapshots while selecting a deliberately contradicted table."""
        return original(transform, mapping_path=mapping_path)

    monkeypatch.setattr(policy_module, "prepare_policy", prepare)
    with pytest.raises(ValueError, match="reintroduced"):
        _run_fixture(tmp_path, monkeypatch, _records())
    assert not (tmp_path / "transformed/bacdive/nodes.tsv").exists()


@pytest.mark.parametrize("value", [" #Host Body Product", "#Host Body-(Site)", '#Host Body-"Site"'])
def test_legacy_identifier_sanitization_cannot_restore_false_identity(tmp_path, monkeypatch, value):
    """Guard both literal lookup and the actual legacy identifier sanitizer without expanding accepted values."""
    record = _records()[1]
    record[SECTION][CATEGORIES][-1]["Cat1"] = value
    with pytest.raises(ValueError, match="category source field/value"):
        _run(tmp_path, monkeypatch, [record])


@pytest.mark.parametrize("identity", [None, "", 0, -1, True, 94.0, "094", "94/other"])
def test_native_record_identity_required_for_reviewed_observations(tmp_path, monkeypatch, identity):
    """Never fabricate a BacDive identifier or citation from a record offset or malformed identifier."""
    record = _records()[1]
    if identity is None:
        record["General"].pop("BacDive-ID")
    else:
        record["General"]["BacDive-ID"] = identity
    expected = (
        r"^BacDive taxonomy evidence: native record lacks its BacDive ID$"
        if identity is None or identity == ""
        else "BacDive record identity"
    )
    with pytest.raises(ValueError, match=expected):
        _run(tmp_path, monkeypatch, [record])


@pytest.mark.parametrize("damage", ["truncated-header", "duplicate-header", "short-row", "long-row"])
def test_mapping_shape_is_validated_before_output(tmp_path, damage):
    """A current input receipt cannot certify a partial or ambiguously shaped mapping table."""
    text = policy_module.MAPPING_PATH.read_text()
    lines = text.splitlines()
    if damage == "truncated-header":
        text = "subject_label_normalized\nhost body product\nhost body site\n"
    elif damage == "duplicate-header":
        header = lines[0].split("\t")
        header[-1] = header[0]
        lines[0] = "\t".join(header)
        text = "\n".join(lines) + "\n"
    elif damage == "short-row":
        lines[1] = "\t".join(lines[1].split("\t")[:-1])
        text = "\n".join(lines) + "\n"
    else:
        lines[1] += "\textra"
        text = "\n".join(lines) + "\n"
    mapping = tmp_path / "mapping.tsv"
    mapping.write_text(text)
    transform = Transform("bacdive", tmp_path / "raw", tmp_path / "output")
    with pytest.raises(ValueError, match="mapping (header|row shape)"):
        policy_module.prepare_policy(transform, mapping_path=mapping)


def test_consumed_mapping_replaces_constructor_cached_dictionary(tmp_path, monkeypatch):
    """The receipt's bytes, not a constructor-time cache, determine nonreviewed Cat2/3 mappings."""
    old_path = tmp_path / "old.tsv"
    old_path.write_text(
        policy_module.MAPPING_PATH.read_text().replace("Plant\tplant\tNCBITaxon:33090", "Plant\tplant\tNCBITaxon:2")
    )
    stale = load_isolation_source_mappings(old_path)
    original = policy_module.prepare_policy
    captured = []

    def prepare(transform):
        """Inject only an old constructor lookup; use the real current consumed mapping file."""
        transform.isolation_source_mappings = stale
        transform.ncbitaxon_labels = {}
        captured.append(transform)
        return original(transform)

    monkeypatch.setattr(policy_module, "prepare_policy", prepare)
    edges, _ = _run_fixture(tmp_path, monkeypatch, [_records()[1]])
    captured[0].verify_consumed_inputs()
    assert any(row["subject"] == "NCBITaxon:33090" and row["object"] == "kgmicrobe.strain:bacdive_94" for row in edges)
    assert not any(row["subject"] == "NCBITaxon:2" and row["object"] == "kgmicrobe.strain:bacdive_94" for row in edges)


def test_actual_assay_generation_uses_final_attribute_header(tmp_path, monkeypatch):
    """Prebuilt native assay and target rows must use the extended header before graph output."""
    from kg_microbe.utils import go_authority
    from tests.test_assay_reference_repairs import _read_assays
    from tests.test_assay_reference_repairs import authority as native_assay_authority

    selected_authority = native_assay_authority.__wrapped__()
    monkeypatch.setattr(go_authority, "load_go_authority", lambda raw: selected_authority)
    original = BacDiveTransform._prepare_assay_outputs

    def prepare_assays(transform):
        """Exercise the real assay generators with the saved native well and authority slice."""
        transform.assay_kit_mappings = {"native fixture": {}}
        transform.assay_raw_data = _read_assays()
        original(transform)

    monkeypatch.setattr(BacDiveTransform, "_prepare_assay_outputs", prepare_assays)
    transform, _, nodes, _ = _run(tmp_path, monkeypatch, _records())
    assert transform.assay_nodes_generated and transform.assay_target_nodes_generated
    assert all(
        len(row) == len(transform.node_header)
        for row in (*transform.assay_nodes_generated, *transform.assay_target_nodes_generated)
    )
    assert all("has_attribute_type" in row for row in nodes)
    assert any(row["id"].startswith("kgmicrobe.assay:") for row in nodes)


@pytest.mark.parametrize("damage", ["raw", "policy", "audit"])
def test_post_run_mutation_cannot_be_readmitted(tmp_path, monkeypatch, damage):
    """Changed evidence after emission is rejected, never restamped as original input."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(policy_module.POLICY_PATH.read_bytes())
    original = policy_module.prepare_policy

    def prepare(transform):
        """Use a mutable test-local policy so the committed evidence remains untouched."""
        transform.isolation_source_mappings = load_isolation_source_mappings()
        transform.ncbitaxon_labels = {}
        captured.append(transform)
        return original(transform, policy_path=policy_path)

    captured = []
    monkeypatch.setattr(policy_module, "prepare_policy", prepare)
    _run_fixture(tmp_path, monkeypatch, _records())
    transform = captured[0]
    path = {
        "raw": tmp_path / "raw/bacdive_strains.json",
        "policy": policy_path,
        "audit": Path(transform.output_dir) / policy_module.AUDIT_FILE,
    }[damage]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(path.read_bytes() + b"\n")
    assert hashlib.sha256(path.read_bytes()).hexdigest() != before
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(transform) if damage == "audit" else transform.verify_consumed_inputs()
