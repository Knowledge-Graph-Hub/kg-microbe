"""Native runtime admission and lossless persistence for stable MIM candidates."""

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.stable_source_candidate import (
    CONTRACT,
    StableSourceCandidate,
    _Snapshots,
    producer_members,
)


def sha(path):
    """Fingerprint actual fixture bytes without changing them."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, value):
    """Write synthetic control metadata inside the test's private directory."""
    path.write_bytes(canonical_json(value) + b"\n")


def select(root, producer, executable, output, *, companion_mode="required/v1"):
    """Select genuine existing native products; hashes do not replace validation."""
    source = root / "candidate"
    companion = root / "companion-output"

    def head(folder):
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder).decode().strip()  # noqa: S607

    receipt = json.loads((source / "producer.json").read_bytes())
    selection = {
        "contract": CONTRACT,
        "mode": "candidate_only",
        "companion_mode": companion_mode,
        "profile_sha256": sha(Path(__file__).parents[1] / "kg_microbe/profiles/stable_source_kgx_v1.yaml"),
        "mim_root": str(root),
        "mim_revision": head(root),
        "producer_root": str(producer),
        "producer_revision": head(producer),
        "producer_files": {name: sha(producer / name) for name in producer_members(producer)},
        "python": {
            "path": str(executable),
            "realpath": str(executable.resolve()),
            "sha256": sha(executable.resolve()),
            "runtime": receipt["runtime"],
        },
        "source_review": {"path": "source-review.json", "sha256": sha(root / "source-review.json")},
        "source_output": {"path": "candidate", "manifest_sha256": sha(source / "manifest.json")},
        "companion_review": (
            {"path": "companion-review.json", "sha256": sha(root / "companion-review.json")}
            if companion_mode == "required/v1"
            else None
        ),
        "companion_output": (
            {"path": "companion-output", "manifest_sha256": sha(companion / "manifest.json")}
            if companion_mode == "required/v1"
            else None
        ),
        "lineage": None,
    }
    put(output, selection)
    return selection


@pytest.fixture
def native_selection(tmp_path):
    """Use explicitly selected real native fixtures, with no network or campaign writes."""
    names = ("MIM_STABLE_TEST_PRODUCTS", "MIM_STABLE_TEST_PRODUCER", "MIM_STABLE_TEST_PYTHON")
    if any(not os.environ.get(name) for name in names):
        pytest.skip("Explicit native MIM 3.13 runtime, code and genuine product fixture required")
    original, producer, executable = (Path(os.environ[name]).absolute() for name in names)
    root = tmp_path / "native-fixture"
    shutil.copytree(original, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    path = tmp_path / "selection.json"
    value = select(root, producer, executable, path)
    return root, path, value


def test_snapshot_same_bytes_replacement_refused(tmp_path):
    """A changed inode is refused even when replacement bytes match exactly."""
    original = tmp_path / "input"
    original.write_bytes(b"same")
    snapshot = _Snapshots()
    snapshot.add(original)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"same")
    assert replacement.stat().st_ino != original.stat().st_ino
    replacement.replace(original)
    with pytest.raises(ValueError, match="input changed between reads"):
        snapshot.verify()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "extra"])
def test_snapshot_alias_and_inventory_refused(tmp_path, kind):
    """A complete product may not gain an aliased or undeclared member."""
    original = tmp_path / "input"
    original.write_bytes(b"data")
    snapshot = _Snapshots()
    snapshot.add(original)
    snapshot.directory(tmp_path, ["input"])
    other = tmp_path / "other"
    if kind == "symlink":
        other.symlink_to(original)
    elif kind == "hardlink":
        os.link(original, other)
    else:
        other.write_bytes(b"data")
    with pytest.raises(ValueError, match="aliased|inventory|input changed"):
        snapshot.verify()
    if kind == "hardlink":
        with pytest.raises(ValueError, match="physical input alias"):
            snapshot.add(other)


def test_real_native_admission_persistence_and_reload(native_selection, tmp_path, local_source_schema):
    """Actual native validators and fresh reload retain both authorities and evidence."""
    root, path, _ = native_selection
    candidate = StableSourceCandidate(path, selection_sha256=sha(path))
    payload = candidate.payload()
    assert payload["status"] == "PRIVATE_NOT_KG_ACCEPTED"
    assert payload["production_authorized"] is False
    assert candidate.native_execution["exit_status"] == 0
    execution_copy = candidate.native_execution
    execution_copy["exit_status"] = 7
    selection_copy = candidate.selection
    selection_copy["companion_mode"] = "absent/v1"
    assert candidate.native_execution["exit_status"] == 0
    assert candidate.selection["companion_mode"] == "required/v1"
    for owner in payload["owners"].values():
        assert hashlib.sha256(owner["record_yaml_utf8"].encode()).hexdigest() == owner["sha256"]
    assert candidate.resolve_source("SOURCE:1") == "MIM.ingredient:0000001"
    assert candidate.resolve_source("SOURCE:4") == "MIM.ingredient:0000004"
    assert candidate.resolve_source("raw exact") is None
    assert candidate.resolve_source("CHEBI:1") is None
    with pytest.raises(ValueError, match="occurrence"):
        candidate.resolve_source("SOURCE:1", occurrence_position=99)
    assert payload["owners"]["MIM:0000004"]["record"]["mapping_status"] == "UNMAPPED"
    assert (
        payload["owners"]["MIM:0000001"]["record"]["identifier"]
        == payload["owners"]["MIM:0000005"]["record"]["identifier"]
    )
    assert len(payload["owners"]) == 5
    assert candidate.legacy_identifier_owners("CHEBI:1") == ["MIM:0000001", "MIM:0000005"]
    assert candidate.audit()["native_bound_owner_counts"] == {
        "exact_external": 1,
        "stable_mim_plus_inexact": 2,
        "stable_mim_only": 1,
    }
    assert {row["predicate_id"] for row in payload["external_supported"]} == {
        "skos:exactMatch",
        "skos:broadMatch",
        "skos:closeMatch",
    }
    assert len(payload["companion"]["mappings"]) == 1
    assert payload["source_decisions"][1]["payload"]["occurrences"]
    nodes, edges = candidate.graph_rows()
    assert all(edge["predicate"] != "biolink:subclass_of" for edge in edges)
    assert any(node["id"] == "MIM.ingredient:0000004" for node in nodes)
    payload["claims"].clear()
    assert candidate.payload()["claims"]
    output = tmp_path / "persisted"
    pin = candidate.export_candidate(output)
    loaded = StableSourceCandidate.reload(output, manifest_sha256=pin)
    assert loaded.payload() == candidate.payload()
    assert (output / "native-source/producer.json").read_bytes() == (root / "candidate/producer.json").read_bytes()
    assert loaded.native_execution["exit_status"] == 0
    finalize_and_reload(candidate, tmp_path)
    # A rehashed mode switch cannot silently strip a persisted companion lane.
    altered = json.loads((output / "selection.json").read_bytes())
    altered.update(companion_mode="absent/v1", companion_review=None, companion_output=None)
    put(output / "selection.json", altered)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["selection_sha256"] = manifest["files"]["selection.json"] = sha(output / "selection.json")
    put(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="persisted candidate mode"):
        StableSourceCandidate.reload(output, manifest_sha256=sha(output / "manifest.json"))


def finalize_and_reload(candidate, tmp_path):
    """Exercise actual native KG finalization/archive on actual native MIM assertions."""
    from kg_microbe.merge_utils.artifact_manifest import file_identity, write_graph_archive
    from kg_microbe.transform_utils.transform import Transform
    from kg_microbe.utils.graph_schema import canonical_header
    from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
    from kg_microbe.utils.tsv_io import tsv_dict_writer

    raw = tmp_path / "graph-raw"
    raw.mkdir()
    transform = Transform("stable_mim_native_candidate_fixture", raw, tmp_path / "graph")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    candidate.bind_to_transform(transform)
    nodes, edges = candidate.graph_rows()
    for path, rows, is_node in ((transform.output_node_file, nodes, True), (transform.output_edge_file, edges, False)):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = tsv_dict_writer(
                stream, fieldnames=canonical_header(rows[0], is_node), quoting=csv.QUOTE_NONE, quotechar=None
            )
            writer.writeheader()
            writer.writerows(rows)
    transform.finalize(fresh_run=True)
    paths = [transform.output_node_file, transform.output_edge_file]
    verify_finalized_source_files(paths)
    identities = {path.name: file_identity(path) for path in paths}
    finalized_nodes, finalized_edges = (list(graph_rows(path)) for path in paths)
    candidate.verify_graph_rows(finalized_nodes, finalized_edges)
    archive_path = tmp_path / "native-stable-candidate.tar.gz"
    provenance = {
        "mode": "candidate_only",
        "status": "PRIVATE_NOT_KG_ACCEPTED",
        "production_authorized": False,
        "selection_sha256": candidate.fingerprint,
        "source_manifest_sha256": candidate.selection["source_output"]["manifest_sha256"],
        "companion_mode": candidate.selection["companion_mode"],
        "profile_sha256": candidate.selection["profile_sha256"],
    }
    write_graph_archive(archive_path, paths, provenance, expected_members=identities)
    with tarfile.open(archive_path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert manifest["members"] == identities and manifest["provenance"] == provenance
        reloaded = []
        for name in ("nodes.tsv", "edges.tsv"):
            content = archive.extractfile(name).read()
            assert hashlib.sha256(content).hexdigest() == identities[name]["sha256"]
            reloaded.append(list(csv.DictReader(io.StringIO(content.decode()), delimiter="\t", quoting=csv.QUOTE_NONE)))
    candidate.verify_graph_rows(*reloaded)
    for control in ("profile", "fingerprint", "lost", "endpoint"):
        altered_nodes, altered_edges = deepcopy(reloaded)
        if control == "profile":
            altered_edges[0]["ingredient_profile"] = "mimprofile:ingredient-kgx/v1"
        elif control == "fingerprint":
            altered_edges[0]["ingredient_bundle_sha256"] = "0" * 64
        elif control == "lost":
            altered_edges.pop()
        else:
            altered_edges[0]["subject"] = "MIM.ingredient:0000005"
        with pytest.raises(ValueError, match="profile|fingerprint|graph rows"):
            candidate.verify_graph_rows(altered_nodes, altered_edges)


@pytest.mark.parametrize(
    "control",
    ["producer", "runtime", "revision", "missing_product", "extra_product", "source_review", "companion_review"],
)
def test_bad_selection_or_current_product_refused(native_selection, control):
    """Pins and complete current products fail before any consumer identity is exposed."""
    root, path, value = native_selection
    if control == "producer":
        value["producer_files"]["src/mediaingredientmech/export/source_bindings.py"] = "0" * 64
    elif control == "runtime":
        value["python"]["sha256"] = "0" * 64
    elif control == "revision":
        value["mim_revision"] = "0" * 40
    elif control == "missing_product":
        (root / "candidate/withheld-source-bindings.sssom.tsv").unlink()
    elif control == "extra_product":
        (root / "candidate/extra").write_bytes(b"unexpected")
    else:
        value[control]["sha256"] = "0" * 64
    put(path, value)
    with pytest.raises(ValueError, match="pin|inventory|revision"):
        StableSourceCandidate(path, selection_sha256=sha(path))


def test_rehashed_external_row_still_requires_native_reconstruction(native_selection):
    """Rehashing changed output cannot replace the native review/replay authority."""
    root, path, value = native_selection
    output = root / "candidate"
    member = output / "external-ingredient_mappings.sssom.tsv"
    member.write_bytes(member.read_bytes().replace(b"skos:broadMatch", b"skos:exactMatch"))
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["files"][member.name] = sha(member)
    put(output / "manifest.json", manifest)
    value["source_output"]["manifest_sha256"] = sha(output / "manifest.json")
    put(path, value)
    with pytest.raises(
        ValueError,
        match="native validation failed.*",
    ):
        StableSourceCandidate(path, selection_sha256=sha(path))


def test_mutation_after_native_validation_refused(native_selection, monkeypatch):
    """Late input drift prevents a success object even after real native validation."""
    root, path, _ = native_selection
    original = subprocess.run

    def change_after_native(argv, **kwargs):
        result = original(argv, **kwargs)
        if any(str(value).endswith("stable_source_native_bridge.py") for value in argv):
            assert result.returncode == 0, result.stderr.decode()
            with (root / "primary-source.txt").open("ab") as stream:
                stream.write(b"late fixture drift")
        return result

    monkeypatch.setattr(subprocess, "run", change_after_native)
    with pytest.raises(ValueError, match="input changed between reads"):
        StableSourceCandidate(path, selection_sha256=sha(path))


@pytest.mark.parametrize(
    "variant",
    [
        "narrow",
        "held",
        "empty",
        "rename",
        "terminal-invalid",
        "legacy-held",
        "all-withheld",
        "multiline",
        "multiline-withheld",
    ],
)
def test_actual_native_variant_through_consumer(tmp_path, local_source_schema, variant):
    """Keep genuine native synthetic science distinct through the actual KG boundary."""
    if not os.environ.get("MIM_STABLE_TEST_PRODUCER") or not os.environ.get("MIM_STABLE_TEST_PYTHON"):
        pytest.skip("Explicit native MIM 3.13 runtime and pinned code required")
    producer = Path(os.environ["MIM_STABLE_TEST_PRODUCER"])
    executable = Path(os.environ["MIM_STABLE_TEST_PYTHON"])
    helper = Path(__file__).parent / "resources/stable_mim_native_fixture.py"
    root = tmp_path / "new-native-fixture"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=producer).decode().strip()  # noqa: S607
    argv = [
        str(executable),
        "-I",
        "-B",
        str(helper),
        "--mim-root",
        str(producer),
        "--mim-head",
        head,
        "--fixture-sha256",
        sha(producer / "tests/test_source_bindings.py"),
        "--python",
        str(executable),
        "--python-sha256",
        sha(executable.resolve()),
        "--output",
        str(root),
        "--variant",
        variant,
    ]
    completed = subprocess.run(argv, cwd=tmp_path, capture_output=True, check=False)  # noqa: S603 - selected test runtime
    (tmp_path / "constructor-stdout.txt").write_bytes(completed.stdout)
    (tmp_path / "constructor-stderr.txt").write_bytes(completed.stderr)
    put(
        tmp_path / "constructor-command.json",
        {"argv": argv, "exit_status": completed.returncode, "helper_sha256": sha(helper), "synthetic_only": True},
    )
    assert completed.returncode == 0, completed.stderr.decode()
    result = json.loads(completed.stdout)
    if variant == "terminal-invalid":
        assert result["status"] == "EXPECTED_NATIVE_REFUSAL"
        assert "retired MIM ID" in result["refusal"]["message"]
        assert not (root / "candidate").exists()
        return
    assert result["status"] == "SYNTHETIC_NATIVE_PRODUCTS_COMPLETE"
    selection_path = tmp_path / "selection.json"
    select(root, producer, executable, selection_path, companion_mode=result["companion_mode"])
    candidate = StableSourceCandidate(selection_path, selection_sha256=sha(selection_path))
    payload = candidate.payload()
    if variant == "narrow":
        assert candidate.resolve_source("SOURCE:1") == "MIM.ingredient:0000001"
        assert candidate.resolve_source("SOURCE:5") == "MIM.ingredient:0000005"
        assert (
            sum(
                row["object_id"] == "CHEBI:1" and row["predicate_id"] == "skos:exactMatch"
                for row in payload["external_supported"]
            )
            == 2
        )
        assert any(row["predicate_id"] == "skos:narrowMatch" for row in payload["external_supported"])
    elif variant == "held":
        assert candidate.resolve_source("SOURCE:1") is None
        assert candidate.resolve_source("SOURCE:4") is None
        assert payload["source_decisions"][0]["payload"]["holds"]
        assert payload["source_decisions"][3]["payload"]["owner_record"] is None
        # Independent external/companion authority does not clear either source hold.
        assert any(row["subject_id"] == "MIM:0000001" for row in payload["external_supported"])
        assert payload["companion"]["mappings"][0]["ext_identity_authorized"] == "true"
    elif variant == "empty":
        assert payload["external_supported"] == payload["external_withheld"] == []
        assert payload["companion"] is None and payload["companion_mode"] == "absent/v1"
        assert not (root / "companion-output").exists()
        assert not (root / "companion-review.json").exists()
        assert len(payload["claims"]) == 4
        assert candidate.audit()["native_bound_owner_counts"] == {
            "exact_external": 0,
            "stable_mim_plus_inexact": 0,
            "stable_mim_only": 4,
        }
    elif variant == "rename":
        assert candidate.resolve_source("SOURCE:4") == "MIM.ingredient:0000004"
        assert payload["owners"]["MIM:0000004"]["path"].endswith("Renamed_material.yaml")
        assert {"MIM:Ungrounded", "MIM:Another_old_name"} <= set(
            payload["owners"]["MIM:0000004"]["record"]["legacy_identifiers"]
        )
        assert candidate.legacy_identifier_owners("MIM:Ungrounded") == ["MIM:0000004"]
    elif variant == "legacy-held":
        assert candidate.resolve_source("SOURCE:1") == "MIM.ingredient:0000001"
        assert candidate.resolve_source("SOURCE:5") == "MIM.ingredient:0000005"
        assert payload["lineage"]["status"] == "CONSUMER_LINEAGE_UNRESOLVED"
        assert payload["consumer_admission"]["held_owners"] == ["MIM:0000001"]
        assert payload["consumer_admission"]["held_external_supported_rows"] == 1
        assert payload["consumer_holds"][0]["legacy_subject"] == "MIM:L-alpha-Phosphatidylcholine"
        assert sum(row["object_id"] == "CHEBI:1" for row in payload["external_supported"]) == 2
        _, graph_edges = candidate.graph_rows()
        assert not any(row["subject"] == "MIM.ingredient:0000001" and row["object"] == "CHEBI:1" for row in graph_edges)
        assert any(row["subject"] == "MIM.ingredient:0000005" and row["object"] == "CHEBI:1" for row in graph_edges)
    elif variant in {"multiline", "multiline-withheld"}:
        lane = "external_supported" if variant == "multiline" else "external_withheld"
        row = payload[lane][0]
        assert row["comment"] == "Synthetic first line\r\n# literal quoted annotation line\r\nSynthetic last line"
        assert payload["external_dispositions"][0]["row_sha256"] == hashlib.sha256(canonical_json(row)).hexdigest()
        assert payload["external_dispositions"][0]["disposition"] == (
            "SUPPORTED" if variant == "multiline" else "WITHHOLD"
        )
    elif variant == "all-withheld":
        assert payload["external_supported"] == []
        assert len(payload["external_withheld"]) == 4
        assert {row["disposition"] for row in payload["external_dispositions"]} == {"WITHHOLD"}
        assert len(payload["claims"]) == 4
        assert payload["companion"] is None and payload["companion_mode"] == "absent/v1"
        assert candidate.audit()["external_withheld_rows"] == 4
    finalize_and_reload(candidate, tmp_path)
    if variant in {"empty", "all-withheld", "multiline-withheld"}:
        output = tmp_path / "persisted-source-only"
        pin = candidate.export_candidate(output)
        assert not (output / "native-companion").exists()
        restored = StableSourceCandidate.reload(output, manifest_sha256=pin)
        assert restored.payload() == payload
        assert restored.audit()["companion_counts"] is None
        assert not any(
            json.loads(edge["ingredient_assertion_json"])["lane"] == "companion" for edge in restored.graph_rows()[1]
        )
        if variant == "empty":
            # A rehashed fabricated companion member is still outside the
            # explicit absent-mode inventory; it cannot add annotation authority.
            invented = output / "native-companion/invented.json"
            invented.parent.mkdir()
            invented.write_bytes(b"{}\n")
            manifest = json.loads((output / "manifest.json").read_bytes())
            manifest["files"]["native-companion/invented.json"] = sha(invented)
            put(output / "manifest.json", manifest)
            with pytest.raises(ValueError, match="member inventory"):
                StableSourceCandidate.reload(output, manifest_sha256=sha(output / "manifest.json"))


@pytest.mark.parametrize(
    "control", ["missing_required", "absent_supplied", "unversioned", "invalid_supplied", "source_dependency"]
)
def test_companion_mode_is_explicit_and_never_a_fallback(native_selection, control):
    """Missing required evidence never becomes a source-only admission."""
    root, path, value = native_selection
    if control == "missing_required":
        value["companion_review"] = value["companion_output"] = None
    elif control == "absent_supplied":
        value["companion_mode"] = "absent/v1"
    elif control == "unversioned":
        value["companion_mode"] = "absent"
    elif control == "source_dependency":
        value.update(companion_mode="absent/v1", companion_review=None, companion_output=None)
        # This source-required review evidence is still mandatory in absent mode.
        (root / "primary-source.txt").unlink()
    else:
        (root / "companion-output/review.json").write_bytes(b"{}\n")
        manifest = json.loads((root / "companion-output/manifest.json").read_bytes())
        manifest["members"]["review.json"] = {"sha256": sha(root / "companion-output/review.json"), "bytes": 3}
        put(root / "companion-output/manifest.json", manifest)
        value["companion_output"]["manifest_sha256"] = sha(root / "companion-output/manifest.json")
    put(path, value)
    with pytest.raises(
        (ValueError, FileNotFoundError), match="fields|companion mode|native validation failed|primary-source"
    ):
        StableSourceCandidate(path, selection_sha256=sha(path))


def test_late_candidate_write_drift_preserves_failure(native_selection, tmp_path, monkeypatch):
    """A late output edit cannot produce a successful candidate installation."""
    root, path, _ = native_selection
    original_source = sha(root / "candidate/manifest.json")
    candidate = StableSourceCandidate(path, selection_sha256=sha(path))
    output = tmp_path / "failed-installation"
    original = _Snapshots.add

    def drift(snapshot, file, digest=None):
        result = original(snapshot, file, digest)
        if Path(file) == output / "manifest.json":
            with (output / "assertions.json").open("ab") as stream:
                stream.write(b"changed after publication")
        return result

    monkeypatch.setattr(_Snapshots, "add", drift)
    with pytest.raises(ValueError, match="input changed between reads"):
        candidate.export_candidate(output)
    assert (output / "FAILED.json").exists()
    assert json.loads((output / "FAILED.json").read_bytes())["status"] == "FAILED_CANDIDATE"
    assert sha(root / "candidate/manifest.json") == original_source


@pytest.mark.parametrize("product", ["source_output", "companion_output"])
@pytest.mark.parametrize("spelling", ["exact", "case-alias", "symlink", "dot-parent"])
def test_native_output_descendant_refused_before_writes(native_selection, tmp_path, product, spelling):
    """Reject #1829 overlap before changing any admitted product membership."""
    root, path, selection = native_selection
    candidate = StableSourceCandidate(path, selection_sha256=sha(path))
    directory = root / selection[product]["path"]
    before = {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()}
    if spelling == "case-alias":
        destination = directory.with_name(directory.name.upper()) / "new-child"
    elif spelling == "symlink":
        alias = tmp_path / "product-alias"
        alias.symlink_to(directory, target_is_directory=True)
        destination = alias / "new-child"
    elif spelling == "dot-parent":
        destination = directory / ".." / directory.name / "new-child"
    else:
        destination = directory / "new-child"
    with pytest.raises(ValueError, match="overlaps|aliased"):
        candidate.export_candidate(destination)
    assert not destination.exists()
    assert not (directory / "new-child").exists()
    assert {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()} == before
    candidate.verify_current()


@pytest.mark.parametrize("mutation", ["add", "remove", "case-alias", "symlink", "hardlink", "directory-alias"])
def test_native_owner_membership_drift_refused(native_selection, tmp_path, mutation):
    """Keep #1830 complete owner membership live after genuine native admission."""
    root, path, _ = native_selection
    candidate = StableSourceCandidate(path, selection_sha256=sha(path))
    directory = root / "data/ingredients/unmapped"
    original = next(directory.glob("*.yaml"))
    added = directory / "Unexpected_owner.yaml"
    if mutation == "add":
        added.write_bytes(original.read_bytes())
    elif mutation == "remove":
        original.unlink()
    elif mutation == "case-alias":
        original.rename(original.with_name(original.name.swapcase()))
    elif mutation == "symlink":
        added.symlink_to(original)
    elif mutation == "hardlink":
        os.link(original, added)
    else:
        moved = directory.with_name("moved-unmapped")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    # No replacement scientific vote, native revalidation, output or admission.
    for use in (candidate.verify_current, candidate.payload, candidate.graph_rows):
        with pytest.raises((ValueError, FileNotFoundError), match="owner|aliased|changed|No such file"):
            use()
    destination = tmp_path / "refused-candidate"
    with pytest.raises((ValueError, FileNotFoundError), match="owner|aliased|changed|No such file"):
        candidate.export_candidate(destination)
    assert not destination.exists()


@pytest.mark.parametrize("product", ["source_output", "companion_output"])
def test_native_unicode_physical_output_alias_refused(native_selection, tmp_path, product):
    """Check #1829 actual filesystem identity, and retain a genuinely disjoint export."""
    root, path, selection = native_selection
    composed = tmp_path / "café-native-fixture"
    decomposed = tmp_path / "cafe\u0301-native-fixture"
    root.rename(composed)
    selection["mim_root"] = str(composed)
    put(path, selection)
    candidate = StableSourceCandidate(path, selection_sha256=sha(path))
    directory = composed / selection[product]["path"]
    alias = decomposed / selection[product]["path"]
    destination = alias / "new-child" / "nested"
    before = {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()}
    physically_same = alias.exists() and alias.samefile(directory)
    put(
        tmp_path / "unicode-filesystem-observation.json",
        {
            "product": product,
            "composed": str(directory),
            "decomposed": str(alias),
            "physical_alias": physically_same,
            "composed_identity": [directory.stat().st_dev, directory.stat().st_ino],
            "alias_identity": [alias.stat().st_dev, alias.stat().st_ino] if alias.exists() else None,
        },
    )
    if physically_same:
        # This is the actual APFS regression. On non-normalizing filesystems,
        # these Unicode spellings denote disjoint paths and are safe to export.
        with pytest.raises(ValueError, match="physically overlaps"):
            candidate.export_candidate(destination)
        assert not (alias / "new-child").exists()
        destination = tmp_path / "disjoint-candidate"
    else:
        assert not alias.exists()
    assert {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()} == before
    candidate.verify_current()
    pin = candidate.export_candidate(destination)
    restored = StableSourceCandidate.reload(destination, manifest_sha256=pin)
    assert restored.payload() == candidate.payload()
    assert not (destination / "FAILED.json").exists()
    assert {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()} == before
