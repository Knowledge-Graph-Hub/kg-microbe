"""Finite source-row corrections preserve original evidence, independent assay outputs and admission."""

import copy
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as producer
from kg_microbe.transform_utils.bacdive import ec_substrate_corrections as correction
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.test_bacdive_run_references import FIXTURE as RECORDS
from tests.test_bacdive_run_references import _run_fixture

FIXTURE = Path(__file__).parent / "resources/bacdive_ec_substrate_corrections/authority.json"


def _evidence():
    """Read complete immutable original/native records without production data access."""
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "9dac3cd68874e887e116426e26f120b3ff6e8e04ae7d24210ae0f049a054abb6"
    return json.loads(raw)


def _originals():
    """Return the complete reviewed legacy cells, including the trailing space and contradictory KEGG."""
    return [(row["line_number"], row["row"]) for row in _evidence()["legacy_rows"]["selected_rows"]]


def _policy():
    """Read the actual finite canonical policy through its production parser."""
    with correction.POLICY_PATH.open() as stream:
        return correction.load_policy(stream)


def _apply(rows, policies=None):
    """Exercise production correction, never a copied mapping loop."""
    return correction.apply_corrections(
        rows, _policy() if policies is None else policies, knowledge_source="infores:bacdive"
    )


def _write_source(path, rows):
    """Serialize a tiny selected source cohort with real schema and original cell values."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=correction.SOURCE_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(row for _, row in rows)


def _run(tmp_path, monkeypatch, rows, records=None, during_prepare=None):
    """Run the existing tiny real producer fixture, injecting only its finite legacy source table."""
    real_prepare = correction.prepare_corrections
    captured = []

    def prepare(transform, legacy_path):
        """Use actual snapshots and correction after writing a synthetic source before its read."""
        _write_source(legacy_path, rows)
        captured.append(transform)
        result = real_prepare(transform, legacy_path)
        if during_prepare:
            during_prepare(transform, legacy_path, result)
        return result

    monkeypatch.setattr(producer, "prepare_corrections", prepare)
    edges, nodes = _run_fixture(tmp_path, monkeypatch, [] if records is None else records)
    return captured[0], edges, nodes


def test_policy_exact_original_cells_and_independent_stereostructures():
    """Four original rows match four finite rules; the two molecular stereoisomers never collapse."""
    evidence = _evidence()
    assert {tuple(rule[key] for key in correction.SOURCE_FIELDS) for rule in _policy()} == {
        tuple(row[key] for key in correction.SOURCE_FIELDS) for _, row in _originals()
    }
    native = {
        item["node"]["id"].rsplit("_", 1)[-1]: item["node"]
        for item in evidence["raw_selected_nodes_or_exact_identifier_references"]
    }
    for source, identifier in zip(evidence["primary_structure_witnesses"], ("91122", "546840"), strict=True):
        properties = {p["pred"].rsplit("/", 1)[-1]: p["val"] for p in native[identifier]["meta"]["basicPropertyValues"]}
        assert properties["inchi_string"] == source["inchi"]
        assert properties["inchi_key_string"] == source["inchi_key"]
    assert native["91122"]["meta"]["definition"]["val"].startswith("An α-")
    assert "β-" in native["91122"]["meta"]["definition"]["val"]  # Original prose caveat retained.
    assert evidence["withheld_kegg_witness"]["name"] == "alpha,alpha-Trehalose"


def test_four_complete_rows_correct_only_their_reviewed_targets_and_withhold_wrong_kegg():
    """Line120's ancillary contradiction is audit-only; no raw cells are mutated."""
    originals = _originals()
    before = copy.deepcopy(originals)
    rows, audit = _apply(originals)
    assert originals == before
    assert [row["CHEBI_ID"] for row in rows] == ["CHEBI:546840", "CHEBI:91122", "CHEBI:546840", "CHEBI:546840"]
    assert [entry["source_line"] for entry in audit] == ["28", "119", "120", "271"]
    assert rows[2]["KEGG_ID"] == ""
    assert json.loads(audit[2]["source_row_json"])["KEGG_ID"] == "KEGG:C01083"
    assert audit[2]["withheld_source_fields"] == "KEGG_ID"
    assert all(entry["status"] == "corrected" for entry in audit)
    for row, entry in zip(rows, audit, strict=True):
        edge = json.loads(entry["emitted_edge_json"])
        assert edge == {
            "subject": row["EC_ID"],
            "predicate": "biolink:has_input",
            "object": row["CHEBI_ID"],
            "relation": "RO:0002233",
            "primary_knowledge_source": "infores:bacdive",
            "knowledge_level": "knowledge_assertion",
            "agent_type": "manual_agent",
        }


@pytest.mark.parametrize("field", correction.SOURCE_FIELDS)
@pytest.mark.parametrize("index", range(4))
def test_one_changed_original_cell_cannot_inherit_reviewed_correction(field, index):
    """A known row cannot evade exact review by changing or blanking any source field."""
    rows = _originals()
    rows[index][1][field] = "" if rows[index][1][field] else "changed"
    with pytest.raises(ValueError, match="scope changed"):
        _apply(rows)


def test_unrelated_old_id_is_not_a_global_alias_and_does_not_gain_new_identity():
    """An unrelated EC/source record keeps every cell; policy does not rewrite an ontology ID globally."""
    row = {**_originals()[0][1], "EC_ID": "EC:1.1.1.1", "CAS_RN_ID": "", "pseudo_CURIE": "kgmicrobe.assay:other"}
    rows, audit = _apply([(7, row)])
    assert rows == [row] and audit == []


def test_duplicates_and_already_corrected_rows_keep_full_multiplicity():
    """Reordered physical rows stay scoped by complete cells, not a historical ordinal allowlist."""
    original = _originals()[1][1]
    first, audit = _apply([(11, original), (9, original)])
    assert len(first) == len(audit) == 2
    assert [entry["source_line"] for entry in audit] == ["11", "9"]
    second, second_audit = _apply(list(enumerate(first, 40)))
    assert second == first
    assert all(entry["status"] == "already_corrected" for entry in second_audit)


@pytest.mark.parametrize(
    "field,value",
    [
        ("corrected_chebi_id", "CHEBI:54684"),
        ("corrected_chebi_id", "CHEBI:x"),
        ("withheld_source_fields", "EC_ID"),
        ("evidence_uri", ""),
        ("reason", ""),
        ("pseudo_CURIE", ""),
        ("EC_ID", "not-an-EC"),
    ],
)
def test_malformed_policy_rejected(field, value):
    """Policy metadata cannot turn partial/ambiguous context into a scientific correction."""
    rule = dict(_policy()[0], **{field: value})
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=correction.POLICY_FIELDS, delimiter="\t")
    writer.writeheader()
    writer.writerow(rule)
    text.seek(0)
    with pytest.raises(ValueError, match="Invalid"):
        correction.load_policy(text)


@pytest.mark.parametrize("damage", ["duplicate-rule", "duplicate-header", "short-row", "empty-policy", "extra-header"])
def test_ambiguous_policy_shape_rejected(damage):
    """Dictionary parsing cannot silently discard duplicate or malformed authoritative fields."""
    text = correction.POLICY_PATH.read_text()
    header, *lines = text.splitlines()
    if damage == "duplicate-rule":
        text += lines[0] + "\n"
    elif damage == "duplicate-header":
        text = header + "\tCHEBI_ID\n" + lines[0] + "\tCHEBI:54684\n"
    elif damage == "short-row":
        text = header + "\nshort\n"
    elif damage == "empty-policy":
        text = header + "\n"
    else:
        text = header + "\tunused\n" + lines[0] + "\tvalue\n"
    with pytest.raises(ValueError):
        correction.load_policy(io.StringIO(text))


@pytest.mark.parametrize("damage", ["duplicate-header", "short-row", "extra-cell"])
def test_malformed_source_shape_rejected(damage):
    """Complete-row matching never proceeds after a malformed source header or record."""
    if damage == "duplicate-header":
        text = "EC_ID\tCHEBI_ID\tsubstrate\tCHEBI_ID\n"
    elif damage == "short-row":
        text = "EC_ID\tCHEBI_ID\tsubstrate\nEC:1\tCHEBI:1\n"
    else:
        text = "EC_ID\tCHEBI_ID\tsubstrate\nEC:1\tCHEBI:1\twater\textra\n"
    with pytest.raises(ValueError):
        list(correction._rows(io.StringIO(text)))


def test_actual_run_retains_assay_observations_and_full_audit(tmp_path, monkeypatch):
    """Only the finite EC/substrate assertions change; independent strain observations remain identical."""
    records = json.loads(RECORDS.read_text())
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _, old_edges, _ = _run(baseline, monkeypatch, [], records)
    transform, new_edges, nodes = _run(candidate, monkeypatch, _originals(), records)
    additions = [row for row in new_edges if row["predicate"] == "biolink:has_input"]
    assert {(row["subject"], row["object"]) for row in additions} == {
        ("EC:3.2.1.20", "CHEBI:91122"),
        ("EC:3.2.1.22", "CHEBI:546840"),
    }
    assert Counter(
        tuple(sorted(row.items())) for row in new_edges if row["predicate"] != "biolink:has_input"
    ) == Counter(tuple(sorted(row.items())) for row in old_edges)
    assert not any(row["object"].startswith(("CAS", "cas:", "KEGG:")) for row in additions)
    assert not any(node["id"] == "CHEBI:54684" for node in nodes)
    audit = list(graph_rows(transform.output_dir / correction.AUDIT_FILE))
    assert len(audit) == 4
    assert [json.loads(row["source_row_json"]) for row in audit] == [row for _, row in _originals()]
    for row in audit:
        assert row["source_sha256"] == hashlib.sha256(Path(row["source_file"]).read_bytes()).hexdigest()
        assert row["policy_sha256"] == hashlib.sha256(Path(row["policy_file"]).read_bytes()).hexdigest()
    assert set(transform.consumed_input_snapshots) == set(correction.REQUIRED_INPUTS)
    verify_producer_audits(transform)


def test_absent_cohort_still_binds_policy_source_and_header_only_audit(tmp_path, monkeypatch):
    """Removing a reviewed source claim is normal, not a forced historical count or hidden fixture bypass."""
    transform, edges, nodes = _run(tmp_path, monkeypatch, [])
    assert not edges and not nodes
    assert list(graph_rows(transform.output_dir / correction.AUDIT_FILE)) == []
    assert set(transform.consumed_input_snapshots) == set(correction.REQUIRED_INPUTS)
    verify_producer_audits(transform)


@pytest.mark.parametrize("damage", ["policy", "source", "symlink-retarget"])
def test_changed_prepared_inputs_abort_without_replacing_prior_graph(tmp_path, monkeypatch, damage):
    """The original admission and immutable snapshots remain guards through atomic output publication."""
    output = tmp_path / "transformed/bacdive"
    output.mkdir(parents=True)
    prior = {}
    for name in ("nodes.tsv", "edges.tsv", correction.AUDIT_FILE):
        path = output / name
        path.write_text("previous complete artifact\n")
        prior[path] = path.read_bytes()
    selected_policy = tmp_path / "policy.tsv"
    selected_policy.write_bytes(correction.POLICY_PATH.read_bytes())
    real_prepare = correction.prepare_corrections

    def prepare(transform, legacy):
        """Mutate only temporary fixture inputs after their actual read."""
        _write_source(legacy, _originals())
        if damage == "symlink-retarget":
            original = legacy.with_suffix(".original")
            original.write_bytes(legacy.read_bytes())
            legacy.unlink()
            legacy.symlink_to(original)
        result = real_prepare(transform, legacy, policy_path=selected_policy)
        if damage == "symlink-retarget":
            replacement = legacy.with_suffix(".replacement")
            replacement.write_bytes(legacy.read_bytes())
            legacy.unlink()
            legacy.symlink_to(replacement)
        else:
            target = selected_policy if damage == "policy" else legacy
            target.write_text(target.read_text() + "changed\n")
        return result

    monkeypatch.setattr(producer, "prepare_corrections", prepare)
    with pytest.raises((SourceFinalizationRequired, ValueError, RuntimeError)):
        _run_fixture(tmp_path, monkeypatch, [])
    assert all(path.read_bytes() == content for path, content in prior.items())


@pytest.mark.usefixtures("local_source_schema")
def test_actual_finalization_repeat_and_public_admission_require_original_audit(tmp_path, monkeypatch):
    """A normal real producer with no reviewed cohort still publishes a mandatory consumed/audit contract."""
    transform, _, _ = _run(tmp_path, monkeypatch, [])
    audit = transform.output_dir / correction.AUDIT_FILE
    before = audit.read_bytes()
    report = transform.finalize(fresh_run=True)
    assert (
        report["producer_audit_members"][correction.AUDIT_FILE]
        == transform.producer_audit_snapshots[correction.AUDIT_FILE]
    )
    assert set(report["consumed_inputs"]) == set(correction.REQUIRED_INPUTS)
    assert transform.finalize() == report
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    assert audit.read_bytes() == before
    audit.write_bytes(before + b"tampered\n")
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
def test_actual_corrected_graph_finalizes_with_native_targets_and_unchanged_audit(tmp_path, monkeypatch):
    """The real finite graph and original audit survive native closure and strict source admission."""
    transform, _, _ = _run(tmp_path, monkeypatch, _originals())
    native = transform.output_base_dir / "ontologies"
    native.mkdir()
    evidence = _evidence()
    chebi_rows = evidence["native_chebi_rows"]
    (native / "chebi_nodes.tsv").write_text(
        "\t".join(chebi_rows["header"])
        + "\n"
        + "".join(entry["original_line"] for entry in chebi_rows["selected_rows"])
    )
    (native / "ec_nodes.tsv").write_text(
        "id\tcategory\tname\tprovided_by\n"
        "EC:3.2.1.20\tbiolink:MolecularActivity|biolink:Protein\talpha-glucosidase\tinfores:ec\n"
        "EC:3.2.1.22\tbiolink:MolecularActivity|biolink:Protein\talpha-galactosidase\tinfores:ec\n"
    )
    (transform.input_base_dir / "chebi.json").write_text(
        json.dumps(
            {
                "graphs": [
                    {
                        "nodes": [
                            entry["node"] for entry in evidence["raw_selected_nodes_or_exact_identifier_references"]
                        ]
                    }
                ]
            }
        )
    )
    before = (transform.output_dir / correction.AUDIT_FILE).read_bytes()
    report = transform.finalize(fresh_run=True)
    assert (transform.output_dir / correction.AUDIT_FILE).read_bytes() == before
    assert len(list(graph_rows(transform.output_edge_file))) == 2
    assert (
        report["producer_audit_members"][correction.AUDIT_FILE]
        == transform.producer_audit_snapshots[correction.AUDIT_FILE]
    )
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
