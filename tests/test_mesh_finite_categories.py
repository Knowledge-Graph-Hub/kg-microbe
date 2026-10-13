"""Finite native MeSH categories retain literal evidence and immutable source-finalization guards."""

import copy
import csv
import gzip
import io
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import mesh_finite_categories as finite
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files

FIXTURE = Path(__file__).parent / "resources/mesh_finite_categories"
POLICY = json.loads(finite.POLICY_FILE.read_text())
ORIGIN = json.loads((FIXTURE / "origin_and_source_rows.json").read_text())
NATIVE = (FIXTURE / "mesh2026-core-excerpt.nt").read_bytes()


def write_nodes(path, rows):
    """Preserve all source fields in literal TSV fixtures without inventing ontology content."""
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["id", "category", "name"]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare(tmp_path, monkeypatch):
    """Use honest complete native excerpts; explicitly replace only the fixture model identity."""
    assert finite.digest(NATIVE) == ORIGIN["origin"]["native_excerpt_sha256"]
    # Policy version 2 binds the statements, not the export's bytes (#1420), so the excerpt
    # needs no repin. The reviewed export stays recorded for provenance.
    assert POLICY["native_reviewed_export"] == {
        "sha256": ORIGIN["origin"]["native_sha256"],
        "bytes": ORIGIN["origin"]["native_bytes"],
    }
    assert POLICY["native_statements_sha256"] == ORIGIN["origin"]["native_sorted_statements_sha256"]
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    native = gzip.compress(NATIVE, mtime=0)
    (raw / "mesh2026.nt.gz").write_bytes(native)
    model = {"version": POLICY["model_version"], "classes": POLICY["model_classes"]}
    (raw / "biolink-model.yaml").write_text(json.dumps(model))
    policy = copy.deepcopy(POLICY)
    policy["model_sha256"] = finite.digest((raw / "biolink-model.yaml").read_bytes())
    policy_path = tmp_path / "mesh_finite_category_dispositions.json"
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_FILE", policy_path)
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    opened = []

    def opener(path):
        """Record selected authority names and use the real immutable reader."""
        opened.append(Path(path).name)
        return transform.consume_input("category_authority_" + Path(path).stem, path)

    authority = finite.FiniteMeshCategoryAuthority(raw, opener=opener)
    return raw, policy_path, policy, transform, authority, opened


def prepare_projected(tmp_path, monkeypatch):
    """Exercise all 27 saved importer declarations without changing names, metadata or identity."""
    raw, policy_path, policy, transform, authority, opened = prepare(tmp_path, monkeypatch)
    rows = [dict(item["row"]) for item in ORIGIN["source_rows"]]
    for row in rows:
        row["category"] = finite.apply_category(row["category"], authority.category_for(row["id"]))
    path = transform.output_node_file
    write_nodes(path, rows)
    authority.bind_node_members([path])
    authority.verify(transform.consumed_input_snapshots, output_dir=path.parent)
    report = {
        finite.CONTRACT_KEY: authority.contract(),
        "members": {path.name: {"sha256": finite.digest(path.read_bytes()), "bytes": path.stat().st_size}},
        "consumed_inputs": copy.deepcopy(transform.consumed_input_snapshots),
        "raw_input_directory": str(raw.resolve()),
    }
    report_path = path.parent / "source_finalization.json"
    return raw, policy_path, policy, transform, authority, opened, report, report_path


@pytest.mark.parametrize("identifier", sorted(finite.FINITE_IDS))
def test_all17_exact_native_categories_and_generic_only_replacement(tmp_path, monkeypatch, identifier):
    """Every reviewed record is read from actual RDF; truthful categories do not assert identity."""
    _, _, policy, transform, authority, opened = prepare(tmp_path, monkeypatch)
    expected = policy["records"][identifier]["category"]
    assert authority.category_for(identifier) == expected
    authority.verify(transform.consumed_input_snapshots)
    assert opened.count("mesh2026.nt.gz") == 1
    assert sum(map(len, json.loads(authority._evidence_json).values())) == 522
    for old in ("", "biolink:NamedThing", "biolink:OntologyClass", expected, expected + "|biolink:OntologyClass"):
        assert finite.apply_category(old, expected) == expected
    with pytest.raises(ValueError, match="Conflicting substantive"):
        finite.apply_category("biolink:Disease|biolink:OntologyClass", expected)


def test_all27_importer_rows_converge_with_one_native_decompression_per_run(tmp_path, monkeypatch):
    """Preserve source-specific labels and all other fields, including repeated declaration IDs."""
    calls = []
    original = finite.read_native_evidence

    def counted(*args):
        """Count native decompressions while retaining the original parser result."""
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(finite, "read_native_evidence", counted)
    _, _, _, transform, authority, opened, report, report_path = prepare_projected(tmp_path, monkeypatch)
    assert len(calls) == opened.count("mesh2026.nt.gz") == 1
    rows = list(graph_rows(transform.output_node_file))
    assert len(rows) == 27
    for row, original_row in zip(rows, ORIGIN["source_rows"], strict=True):
        assert {k: v for k, v in row.items() if k != "category"} == {
            k: v for k, v in original_row["row"].items() if k != "category"
        }
    assert sum(authority.contract()["occurrences"].values()) == 27
    finite.verify_recorded_inputs(report, report_path)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "identifier",
    ["mesh:D000038", "mesh:D007249", "mesh:D010514", "mesh:D014947", "mesh:D044002", "mesh:C1", "MESH:D004531"],
)
def test_unrelated_ids_and_clinical_cohort_do_not_open_new_authorities(tmp_path, identifier):
    """No prefix widening or interference with already reviewed clinical cases."""

    def forbidden(path):
        """Fail on any authority read outside the finite selected cohort."""
        raise AssertionError(path)

    authority = finite.FiniteMeshCategoryAuthority(tmp_path, opener=forbidden)
    assert authority.category_for(identifier) is None
    assert authority.source_paths == set()
    assert authority.contract() == {"version": 1, "authority": None}
    # The separate clinical policy may consume this same file legitimately.
    authority.verify({finite.NATIVE_ROLE: {"path": "clinical", "sha256": "clinical"}})


def test_model_boundaries_and_sphagnopsida_preferred_concept_are_explicit(tmp_path, monkeypatch):
    """Reject the natural-environment shortcut and preserve the class/genus distinction."""
    _, _, policy, _, authority, _ = prepare(tmp_path, monkeypatch)
    assert authority.category_for("mesh:D000076624") == "biolink:PhysicalEntity"
    assert "natural environment" in policy["model_classes"]["environmental feature"]["description"]
    assert authority.category_for("mesh:D044003") == "biolink:OrganismTaxon"
    assert policy["records"]["mesh:D044003"]["preferred_concept"].endswith("/M0444134")
    assert (
        authority.category_for("mesh:D000083422") == authority.category_for("mesh:D015048") == "biolink:PhysicalEntity"
    )


@pytest.mark.parametrize(
    "damage", ["missing_rule", "extra_rule", "category", "native_digest", "rationale", "preferred_genus", "truncated"]
)
def test_changed_policy_is_not_self_authenticating(damage):
    """Decisions and their interpretation are anchored together, not mutable witness receipts."""
    policy = copy.deepcopy(POLICY)
    record = policy["records"]["mesh:D044003"]
    if damage == "missing_rule":
        policy["records"].pop("mesh:D004531")
    elif damage == "extra_rule":
        policy["records"]["mesh:D1"] = record
    elif damage == "category":
        record["category"] = "biolink:PhysicalEntity"
    elif damage == "native_digest":
        policy["native_statements_sha256"] = "forged"
    elif damage == "rationale":
        record["rationale"] = "claim genus equivalence"
    elif damage == "preferred_genus":
        record["preferred_concept"] = record["preferred_concept"].replace("M0444134", "M0028465")
    else:
        policy = {}
    with pytest.raises(ValueError, match="Unreviewed"):
        finite.load_policy(io.StringIO(json.dumps(policy)))


def test_duplicate_policy_keys_fail_closed():
    """A repeated mapping key is never a silent override."""
    with pytest.raises(ValueError, match="Duplicate"):
        finite.load_policy(io.StringIO('{"version":1,"version":1}'))


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "extra",
        "duplicate",
        "namespace",
        "native_type",
        "preferred_genus",
        "definition",
        "escaped_short",
        "escaped_long",
        "invalid_escape",
    ],
)
def test_changed_native_records_refuse_without_any_fullfile_pin(tmp_path, monkeypatch, damage):
    """With no whole-file pin left (#1420), the statement digest alone detects every change."""
    raw, _, _, _, authority, _ = prepare(tmp_path, monkeypatch)
    selected = next(line for line in NATIVE.splitlines(keepends=True) if b"/D044003>" in line)
    content = NATIVE
    if damage == "missing":
        content = content.replace(selected, b"", 1)
    elif damage == "extra":
        content += b'<http://id.nlm.nih.gov/mesh/2026/D044003> <http://example.org/new> "added" .\n'
    elif damage == "duplicate":
        content += selected
    elif damage == "namespace":
        content = content.replace(b"/2026/D044003>", b"/2025/D044003>")
    elif damage == "native_type":
        content = content.replace(b"vocab#SCR_Chemical>", b"vocab#TopicalDescriptor>", 1)
    elif damage == "preferred_genus":
        content = content.replace(b"/M0444134>", b"/M0028465>")
    elif damage == "definition":
        content = content.replace(b"A class of BRYOPHYTA", b"A genus of BRYOPHYTA")
    elif damage == "escaped_short":
        content += selected.replace(b"/D044003>", rb"/\u0044044003>")
    elif damage == "escaped_long":
        content += selected.replace(b"/D044003>", rb"/\U00000044044003>")
    else:
        content += selected.replace(b"/D044003>", rb"/\uD800044003>")
    (raw / "mesh2026.nt.gz").write_bytes(gzip.compress(content, mtime=0))
    with pytest.raises(ValueError, match="Finite MeSH"):
        authority.category_for("mesh:D044003")


def republish_export(raw):
    """Write the reviewed statements in new export bytes, as NLM republishes mesh2026.nt.gz."""
    unrelated = b'<http://id.nlm.nih.gov/mesh/2026/D999999> <http://www.w3.org/2000/01/rdf-schema#label> "x"@en .\n'
    native = gzip.compress(unrelated + NATIVE, mtime=1)
    (raw / "mesh2026.nt.gz").write_bytes(native)
    return native


def test_republished_export_with_reviewed_statements_is_accepted_and_recorded(tmp_path, monkeypatch):
    """No whole-file pin (#1420): new export bytes pass on their statements, and the receipt records them."""
    raw, _, policy, transform, authority, _ = prepare(tmp_path, monkeypatch)
    assert {"native_sha256", "native_bytes"}.isdisjoint(policy)
    native = republish_export(raw)
    assert finite.digest(native) != policy["native_reviewed_export"]["sha256"]
    assert authority.category_for("mesh:D004531") == policy["records"]["mesh:D004531"]["category"]
    authority.verify(transform.consumed_input_snapshots)
    recorded = json.loads(authority._contract_json)["authority"]
    assert (recorded["sha256"], recorded["bytes"]) == (finite.digest(native), len(native))
    assert transform.consumed_input_snapshots[finite.NATIVE_ROLE]["sha256"] == finite.digest(native)


def test_admission_compares_the_export_this_run_read_not_the_reviewed_one(tmp_path, monkeypatch):
    """The fixture export is not the reviewed one and is admitted; a later replacement is not."""
    raw, _, policy, _, _, _, report, report_path = prepare_projected(tmp_path, monkeypatch)
    assert report[finite.CONTRACT_KEY]["authority"]["sha256"] != policy["native_reviewed_export"]["sha256"]
    finite.verify_recorded_inputs(report, report_path)
    republish_export(raw)
    with pytest.raises(SourceFinalizationRequired, match="finite MeSH") as info:
        finite.verify_recorded_inputs(report, report_path)
    assert "locator or bytes changed" in str(info.value.__cause__)


@pytest.mark.parametrize("damage", ["policy", "witness", "receipt", "missing_role", "rebound_role", "scope"])
def test_live_cached_witness_original_roles_and_member_scope_are_sealed(tmp_path, monkeypatch, damage):
    """Original interpreted evidence remains binding through final publication."""
    _, _, _, transform, authority, _, _, _ = prepare_projected(tmp_path, monkeypatch)
    snapshots = copy.deepcopy(transform.consumed_input_snapshots)
    if damage == "policy":
        authority._policy_json = "{}"
    elif damage == "witness":
        authority._evidence_json = "{}"
    elif damage == "receipt":
        contract = json.loads(authority._contract_json)
        contract["native_evidence_sha256"] = "forged"
        authority._contract_json = finite.canonical(contract)
    elif damage == "missing_role":
        snapshots.pop(finite.NATIVE_ROLE)
    elif damage == "rebound_role":
        snapshots[finite.NATIVE_ROLE]["path"] += ".rebound"
    else:
        authority._node_members = ("other_nodes.tsv",)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.verify(snapshots, output_dir=transform.output_dir)


@pytest.mark.parametrize(
    "damage",
    [
        "removed_contract",
        "null_contract",
        "removed_policy_role",
        "removed_native_role",
        "changed_category",
        "partial_duplicate_loss",
        "removed_all_rows",
        "rewritten_count",
        "wrong_scope",
    ],
)
def test_recorded_admission_rejects_finite_contract_erasure_or_partial_evidence(tmp_path, monkeypatch, damage):
    """Rewritten outer member receipts cannot conceal lost finite authority or occurrences."""
    _, _, _, transform, _, _, report, report_path = prepare_projected(tmp_path, monkeypatch)
    if damage == "removed_contract":
        report.pop(finite.CONTRACT_KEY)
    elif damage == "null_contract":
        report[finite.CONTRACT_KEY] = {"version": 1, "authority": None}
    elif damage == "removed_policy_role":
        report["consumed_inputs"].pop(finite.POLICY_ROLE)
    elif damage == "removed_native_role":
        report["consumed_inputs"].pop(finite.NATIVE_ROLE)
    elif damage in {"changed_category", "partial_duplicate_loss", "removed_all_rows"}:
        rows = list(graph_rows(transform.output_node_file))
        if damage == "changed_category":
            rows[0]["category"] = "biolink:OntologyClass"
        elif damage == "partial_duplicate_loss":
            rows.pop(0)
        else:
            rows.clear()
        write_nodes(transform.output_node_file, rows)
        report["members"][transform.output_node_file.name] = {
            "sha256": finite.digest(transform.output_node_file.read_bytes()),
            "bytes": transform.output_node_file.stat().st_size,
        }
    elif damage == "rewritten_count":
        report[finite.CONTRACT_KEY]["occurrences"]["mesh:D004531"] = True
    else:
        report[finite.CONTRACT_KEY]["node_members"] = ["other_nodes.tsv"]
    with pytest.raises(SourceFinalizationRequired, match="finite MeSH"):
        finite.verify_recorded_inputs(report, report_path)


def test_explicit_member_scope_survives_unrelated_sameid_files_and_fresh_repeat(tmp_path, monkeypatch):
    """Repeated prefix-scoped finalization must ignore unrelated ontology members."""
    raw, _, _, transform, authority, _, report, report_path = prepare_projected(tmp_path, monkeypatch)
    unrelated = transform.output_dir / "other_nodes.tsv"
    write_nodes(unrelated, [{"id": "mesh:D004531", "name": "other epoch", "category": "biolink:OntologyClass"}])
    authority.verify(transform.consumed_input_snapshots, output_dir=transform.output_dir)
    finite.verify_recorded_inputs(report, report_path)
    fresh = Transform("fixture", raw, transform.output_base_dir)
    fresh.TSV_QUOTING = csv.QUOTE_NONE
    restored = finite.restore_recorded_guard(fresh, report, report_path)
    assert restored.contract() == report[finite.CONTRACT_KEY]
    restored.verify(fresh.consumed_input_snapshots, output_dir=fresh.output_dir)


@pytest.mark.parametrize("when", ["before", "after", "after_admission"])
def test_native_drift_fails_at_every_admission_boundary(tmp_path, monkeypatch, when):
    """No source, runtime, or recorded admission stage accepts a later native replacement."""
    raw, _, _, transform, authority, _, report, report_path = prepare_projected(tmp_path, monkeypatch)
    guard = finite.verify_recorded_inputs(report, report_path) if when == "after_admission" else None
    (raw / "mesh2026.nt.gz").write_bytes(gzip.compress(b"unrelated RDF", mtime=0))
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        if when == "before":
            finite.verify_recorded_inputs(report, report_path)
        elif when == "after":
            authority.verify(transform.consumed_input_snapshots)
        else:
            guard.verify(metadata_only=True)


def test_native_parser_requires_actual_private_snapshot_and_original_locator(tmp_path, monkeypatch):
    """A correct policy cannot authorize parsing mutable original files or a foreign raw locator."""
    raw, _, _, _, _, _ = prepare(tmp_path, monkeypatch)
    direct = finite.FiniteMeshCategoryAuthority(raw, opener=lambda path: path.open())
    with pytest.raises(ValueError, match="immutable private snapshot"):
        direct.category_for("mesh:D004531")
    outside = tmp_path / "outside.nt.gz"
    shutil.copyfile(raw / "mesh2026.nt.gz", outside)
    (raw / "mesh2026.nt.gz").unlink()
    (raw / "mesh2026.nt.gz").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        direct.category_for("mesh:D004531")


def test_truthful_zero_contract_requires_no_native_input_or_new_policy(tmp_path):
    """Ordinary sources need the explicit versioned zero receipt, not a MeSH dependency."""
    path = tmp_path / "nodes.tsv"
    write_nodes(path, [{"id": "example:1", "name": "unrelated", "category": "biolink:NamedThing"}])
    report = {finite.CONTRACT_KEY: {"version": 1, "authority": None}, "members": {path.name: {}}, "consumed_inputs": {}}
    finite.verify_recorded_inputs(report, tmp_path / "source_finalization.json")


def prepare_source(tmp_path, monkeypatch):
    """Supply actual importer rows to the public finalizer, not a preprojected substitute."""
    from tests.go_subject_restrictions_fixtures import write_rows

    raw, _, _, transform, _, _ = prepare(tmp_path, monkeypatch)
    rows = [dict(item["row"]) for item in ORIGIN["source_rows"]]
    write_rows(transform.output_node_file, rows)
    write_rows(
        transform.output_edge_file,
        [],
        fields=[
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "publications",
        ],
    )
    return raw, transform, rows


@pytest.mark.usefixtures("local_source_schema")
def test_actual_finalizer_all27_importer_rows_and_public_admission(tmp_path, monkeypatch):
    """All observed copies converge upstream with no noncategory or edge change."""
    raw, transform, original = prepare_source(tmp_path, monkeypatch)
    before_edges = transform.output_edge_file.read_bytes()
    report = transform.finalize(fresh_run=True)
    assert list(graph_rows(transform.output_node_file)) == [
        {**row, "category": POLICY["records"][row["id"]]["category"]} for row in original
    ]
    assert transform.output_edge_file.read_bytes() == before_edges
    assert sum(report[finite.CONTRACT_KEY]["occurrences"].values()) == 27
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    transform.finalize()
    fresh = Transform("fixture", raw, tmp_path / "transformed")
    fresh.finalize()
    assert before == {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    fresh.verify_consumed_inputs()


@pytest.mark.usefixtures("local_source_schema")
def test_public_prefix_scoped_finalization_ignores_neighbor_sameid_nodes(tmp_path, monkeypatch):
    """A neighboring ontology is not admitted implicitly during finalization, repeat or validation."""
    raw, transform, _ = prepare_source(tmp_path, monkeypatch)
    node_path, edge_path = transform.output_dir / "selected_nodes.tsv", transform.output_dir / "selected_edges.tsv"
    transform.output_node_file.rename(node_path)
    transform.output_edge_file.rename(edge_path)
    neighbor = transform.output_dir / "other_nodes.tsv"
    write_nodes(neighbor, [ORIGIN["source_rows"][0]["row"]])
    before = neighbor.read_bytes()
    report = transform.finalize(file_prefix="selected_", fresh_run=True)
    assert report[finite.CONTRACT_KEY]["node_members"] == [node_path.name]
    transform.finalize(file_prefix="selected_")
    fresh = Transform("fixture", raw, tmp_path / "transformed")
    fresh.finalize(file_prefix="selected_")
    fresh.verify_consumed_inputs()
    verify_finalized_source_files([node_path, edge_path])
    assert neighbor.read_bytes() == before


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("damage", ["missing_contract", "null_contract", "missing_role", "inventory", "scope"])
def test_public_admission_requires_finite_authority_even_if_ordinary_report_survives(tmp_path, monkeypatch, damage):
    """The public merge admission path must invoke the finite contract, not only check TSV hashes."""
    _, transform, _ = prepare_source(tmp_path, monkeypatch)
    report = transform.finalize(fresh_run=True)
    if damage == "missing_contract":
        report.pop(finite.CONTRACT_KEY)
    elif damage == "null_contract":
        report[finite.CONTRACT_KEY] = {"version": 1, "authority": None}
    elif damage == "missing_role":
        report["consumed_inputs"].pop(finite.NATIVE_ROLE)
    elif damage == "inventory":
        report[finite.CONTRACT_KEY]["occurrences"].pop("mesh:C008328")
    else:
        report[finite.CONTRACT_KEY]["node_members"] = []
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("damage", ["policy", "all_evidence", "scope", "seen"])
def test_late_cached_evidence_deletion_cannot_publish_partial_category_changes(tmp_path, monkeypatch, damage):
    """Clearing cache fields cannot turn a consumed finite source into a truthful zero cohort."""
    from kg_microbe.utils import source_finalization

    _, transform, _ = prepare_source(tmp_path, monkeypatch)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original = source_finalization._publish_finalization

    def damage_then_publish(producer, prepared):
        """Erase cached proof immediately before the real publication checkpoint."""
        guard = producer._mesh_finite_category_guard
        if damage == "policy":
            guard._policy_json = None
        elif damage == "all_evidence":
            guard._policy_json = guard._evidence_json = guard._contract_json = None
            guard._seen.clear()
        elif damage == "scope":
            guard._node_members = ()
        else:
            guard._seen.clear()
        return original(producer, prepared)

    monkeypatch.setattr(source_finalization, "_publish_finalization", damage_then_publish)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


@pytest.mark.usefixtures("local_source_schema")
def test_new_run_resets_old_guard_and_truthful_zero_has_no_native_mesh_dependency(tmp_path, monkeypatch):
    """A subsequent actual producer epoch cannot reuse old finite evidence or require unrelated raw inputs."""
    raw, transform, _ = prepare_source(tmp_path, monkeypatch)
    transform.finalize(fresh_run=True)
    assert transform._mesh_finite_category_guard is not None
    transform.begin_consumed_inputs()
    assert transform._mesh_finite_category_guard is None
    (raw / "mesh2026.nt.gz").unlink()
    write_nodes(
        transform.output_node_file,
        [{"id": "example:1", "name": "unrelated", "category": "biolink:NamedThing", "provided_by": "infores:fixture"}],
    )
    report = transform.finalize(fresh_run=True)
    assert report[finite.CONTRACT_KEY] == {"version": 1, "authority": None}
    assert finite.POLICY_ROLE not in report["consumed_inputs"]
    assert finite.NATIVE_ROLE not in report["consumed_inputs"]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("damage", ["deprecated", "abstract", "mixin", "definition", "missing"])
def test_changed_model_cannot_approve_projection_after_fullfile_test_repin(tmp_path, monkeypatch, damage):
    """Selected native model semantics, not just a mutable whole-file hash, constrain each category."""
    raw, policy_path, policy, _, authority, _ = prepare(tmp_path, monkeypatch)
    model_path = raw / "biolink-model.yaml"
    model = json.loads(model_path.read_text())
    if damage == "missing":
        model["classes"].pop("food")
    elif damage == "definition":
        model["classes"]["environmental feature"]["description"] = "also manufactured objects"
    else:
        model["classes"]["food"][damage] = True
    model_path.write_text(json.dumps(model))
    policy["model_sha256"] = finite.digest(model_path.read_bytes())
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    with pytest.raises(ValueError, match="model definitions"):
        authority.category_for("mesh:D004531")


def test_same_byte_native_symlink_retarget_remains_a_locator_change(tmp_path, monkeypatch):
    """Byte equality cannot restamp a different original native authority after consumption."""
    raw, _, _, transform, authority, _ = prepare(tmp_path, monkeypatch)
    first, second = raw / "original.nt.gz", raw / "replacement.nt.gz"
    (raw / "mesh2026.nt.gz").rename(first)
    shutil.copyfile(first, second)
    (raw / "mesh2026.nt.gz").symlink_to(first)
    authority.category_for("mesh:D004531")
    (raw / "mesh2026.nt.gz").unlink()
    (raw / "mesh2026.nt.gz").symlink_to(second)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        authority.verify(transform.consumed_input_snapshots)
