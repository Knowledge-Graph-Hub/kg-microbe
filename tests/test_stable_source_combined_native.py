"""Genuine native combined reconstruction and explicit final-consumer admission."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from kg_microbe.utils.stable_source_candidate import StableSourceCandidate
from kg_microbe.utils.stable_source_integration import (
    CONTRACT,
    FINAL_CONTRACT,
    FINAL_MODE,
    verify_final_combined,
)
from kg_microbe.utils.stable_source_native_bridge import CONSERVATION_CAPABILITY
from tests.test_stable_source_candidate import finalize_and_reload, put, select, sha

pytestmark = pytest.mark.native_mim_combined
PRODUCER_HEAD = "68bba8a68c79049e7602e4b10a12b1baf700d840"
UPSTREAM_FIXTURE_SHA256 = "36a15b47b30d2c19b6e1daac2bcf0eb4dfdc9fae0683a217a331309204cfc368"
SELECTORS = ("MIM_STABLE_TEST_PRODUCTS", "MIM_STABLE_TEST_PRODUCER", "MIM_STABLE_TEST_PYTHON")


@pytest.fixture(scope="session")
def genuine_combined_products(tmp_path_factory):
    """Build one small real native fixture with explicit maintained prerequisites."""
    if any(not os.environ.get(name) for name in SELECTORS):
        pytest.skip("Explicit native MIM 3.13 runtime, code and genuine product fixture required")
    baseline, producer, executable = (Path(os.environ[name]).absolute() for name in SELECTORS)
    assert baseline.is_dir(), "Selected baseline native products do not exist"
    container = tmp_path_factory.mktemp("genuine-combined-native")
    output = container / "products"
    scratch = container / "runtime-tmp"
    scratch.mkdir()
    helper = Path(__file__).parent / "resources/stable_mim_combined_fixture.py"
    argv = [
        str(executable),
        "-I",
        "-B",
        str(helper),
        "--mim-root",
        str(producer),
        "--mim-head",
        PRODUCER_HEAD,
        "--fixture-sha256",
        UPSTREAM_FIXTURE_SHA256,
        "--helper-sha256",
        sha(helper),
        "--python",
        str(executable),
        "--python-sha256",
        sha(executable.resolve()),
        "--output",
        str(output),
        "--review-transitions",
    ]
    environment = {
        "PATH": os.defpath,
        "HOME": str(Path.home()),
        "TMPDIR": str(scratch),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    put(container / "command.json", {"argv": argv, "environment_keys": sorted(environment)})
    with (container / "stdout.log").open("wb") as stdout, (container / "stderr.log").open("wb") as stderr:
        result = subprocess.run(  # noqa: S603 - explicitly selected interpreter/code, owned output
            argv,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            check=False,
            timeout=180,
        )
    put(
        container / "execution.json",
        {
            "returncode": result.returncode,
            "stdout_sha256": sha(container / "stdout.log"),
            "stderr_sha256": sha(container / "stderr.log"),
        },
    )
    assert result.returncode == 0, f"Genuine native combined construction failed; see {container / 'stderr.log'}"
    metadata = json.loads((output / "combined-fixture.json").read_bytes())
    assert metadata["synthetic_only"] is True and metadata["production_authorized"] is False
    assert metadata["synthetic_transition_reviews_constructed"] is True
    return output, producer, executable, metadata


@pytest.fixture
def combined_selection(genuine_combined_products, tmp_path):
    """Copy each native candidate while retaining the immutable selected KG origin."""
    original, producer, executable, metadata = genuine_combined_products
    root = tmp_path / "combined-native"
    shutil.copytree(original, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    native_path = tmp_path / "native-selection.json"
    native = select(root, producer, executable, native_path, companion_mode="absent/v1")
    artifact = metadata["combined_source_scope"]["artifacts"]["cm_reconciliation"]
    selection = {
        "contract": FINAL_CONTRACT,
        "mode": FINAL_MODE,
        "culturemech": metadata["culturemech"],
        "kgm_source_receipt": metadata["kgm_source_receipt"],
        "current_kgm": metadata["current_kgm"],
        "reconciliation": {"path": artifact, "sha256": sha(root / artifact)},
        "expected_counts": metadata["expected_counts"],
        "native_occurrence_payload_column": "original_occurrence_json",
        "combined_source_scope": metadata["combined_source_scope"],
        "combined_source_declaration": metadata["combined_source_declaration"],
        "owner_transitions": metadata["owner_transitions"],
    }
    path = tmp_path / "final-selection.json"
    put(path, selection)
    return {"root": root, "native_path": native_path, "native": native, "path": path, "selection": selection}


def candidate_for(fixture):
    """Use the actual selected native validator, without a stubbed payload."""
    return StableSourceCandidate(fixture["native_path"], selection_sha256=sha(fixture["native_path"]))


def test_genuine_combined_final_admission_persistence_and_archive(combined_selection, tmp_path, local_source_schema):
    """Real native proof, reviewed transitions, graph persistence and archive agree."""
    fixture = combined_selection
    candidate = candidate_for(fixture)
    result = verify_final_combined(candidate, fixture["path"], selection_sha256=sha(fixture["path"]))
    assert result["status"] == "PRIVATE_NOT_KG_ACCEPTED"
    assert result["production_authorized"] is False and result["medium_presence_authorized"] is False
    assert result["admission_scope"] == FINAL_MODE
    assert result["counts"] == {"positive_inventory": 2, "context_only": 1, "held": 1}
    assert result["binding_counts"] == {"supported_bindings": 2, "withheld_bindings": 2}
    assert result["reconciled_cm_occurrences"] == 4 and result["other_native_occurrences"] == 5
    assert result["owner_transitions"] == {"reconciled_binding_transitions": 4, "transition_occurrences": 4}
    assert result["conservation"]["profile"] == CONSERVATION_CAPABILITY
    assert result["conservation"]["kg_source_ids"] == 3
    assert result["conservation"]["scientific_report_count"] == 2
    assert result["conservation"]["native_reconstruction_required"] is True
    assert candidate.native_execution["exit_status"] == 0
    output = tmp_path / "persisted"
    pin = candidate.export_candidate(output)
    loaded = StableSourceCandidate.reload(output, manifest_sha256=pin)
    assert loaded.payload() == candidate.payload()
    assert loaded.native_execution["exit_status"] == 0
    repeated = verify_final_combined(loaded, fixture["path"], selection_sha256=sha(fixture["path"]))
    assert repeated == result
    finalize_and_reload(loaded, tmp_path)
    put(tmp_path / "final-combined-check.json", result)


def test_genuine_final_bundle_canary_core(combined_selection, tmp_path, local_source_schema):
    """The actual bounded canary persists, re-admits and audits native graph artifacts."""
    from scripts.check_stable_mim_final_bundle import check_bundle

    fixture = combined_selection
    candidate = candidate_for(fixture)
    output = tmp_path / "isolated-canary"
    result = check_bundle(
        candidate,
        integration_path=fixture["path"],
        integration_sha256=sha(fixture["path"]),
        output=output,
    )
    assert result["status"] == "PRIVATE_NOT_KG_ACCEPTED"
    assert result["production_authorized"] is False and result["release_authorized"] is False
    assert result["medium_presence_authorized"] is False
    assert result["native_execution"]["exit_status"] == result["reload_native_execution"]["exit_status"] == 0
    assert result["admission"]["owner_transitions"]["reconciled_binding_transitions"] == 4
    assert result["graph_projection"]["nodes"] > 0 and result["graph_projection"]["edges"] > 0
    assert json.loads((output / "canary-result.json").read_bytes()) == result
    assert (output / "candidate-projection.tar.gz").is_file()


@pytest.mark.parametrize("control", ["missing_conservation", "unknown_capability"])
def test_rehashed_native_capability_flags_are_not_proof(combined_selection, control):
    """A reselected manifest is refused by real native reconstruction or negotiation."""
    fixture = combined_selection
    path = fixture["root"] / "candidate/manifest.json"
    manifest = json.loads(path.read_bytes())
    if control == "missing_conservation":
        manifest["required_capabilities"].remove(CONSERVATION_CAPABILITY)
    else:
        manifest["required_capabilities"].append("unreviewed-combined-capability-v999")
    put(path, manifest)
    fixture["native"]["source_output"]["manifest_sha256"] = sha(path)
    put(fixture["native_path"], fixture["native"])
    with pytest.raises(ValueError, match="native|capabilit|manifest"):
        candidate_for(fixture)


def reselect_invalid_position_map(fixture, tmp_path):
    """Prepare a coherent adversarial review envelope without repairing its false relation."""
    script = tmp_path / "reselect-invalid-position-map.py"
    script.write_text(
        textwrap.dedent("""\
        import hashlib, importlib.util, json, sys
        from pathlib import Path
        import yaml

        producer, root, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        helper = producer / "scripts/record_review.py"
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha(helper) == expected == sha(root / "scripts/record_review.py")
        spec = importlib.util.spec_from_file_location("selected_native_review_renderer", helper)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        assert Path(renderer.__file__).resolve() == helper.resolve()
        write = lambda path, value: path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n")
        metadata = json.loads((root / "combined-fixture.json").read_bytes())
        name = metadata["combined_source_scope"]["artifacts"]["combined_position_map"]
        path = root / name
        positions = json.loads(path.read_bytes())
        assert positions[0]["original_position"] == positions[0]["native_position"] == 1
        positions[0]["native_position"] = 2
        write(path, positions)
        review_path = root / "source-review.json"
        review = json.loads(review_path.read_bytes())
        review["inputs"][name] = sha(path)
        reports = {case[role]["path"] for case in review["cases"] for role in ("primary", "skeptic")}
        assert len(reports) == 2
        for report_name in sorted(reports):
            report_path = root / report_name
            report = yaml.safe_load(report_path.read_bytes())
            selected = [entry for entry in report["source"]["inputs"] if entry["path"] == name]
            assert len(selected) == 1
            selected[0]["sha256"] = sha(path)
            report_path.write_text(yaml.safe_dump(report, sort_keys=False))
            markdown = report_path.with_name("review.md")
            markdown.write_text(renderer.render_markdown(report))
            for member in (report_path, markdown):
                review["inputs"][member.relative_to(root).as_posix()] = sha(member)
        write(review_path, review)
        manifest_path = root / "candidate/manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["inputs"].update(review["inputs"])
        manifest["inputs"]["source-review.json"] = sha(review_path)
        write(manifest_path, manifest)
        print(json.dumps({"artifact": name, "sha256": sha(path), "paired_reports": len(reports)}))
        """)
    )
    native = fixture["native"]
    metadata = json.loads((fixture["root"] / "combined-fixture.json").read_bytes())
    executable = native["python"]["path"]
    argv = [
        executable,
        "-I",
        "-B",
        str(script),
        native["producer_root"],
        str(fixture["root"]),
        metadata["producer_inputs"]["scripts/record_review.py"]["sha256"],
    ]
    result = subprocess.run(  # noqa: S603 - fixed owned script, explicitly selected native renderer
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    put(
        tmp_path / "semantic-negative-reselection.json",
        {
            "argv": argv,
            "exit_status": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "result": json.loads(result.stdout),
        },
    )
    native["source_review"]["sha256"] = sha(fixture["root"] / "source-review.json")
    native["source_output"]["manifest_sha256"] = sha(fixture["root"] / "candidate/manifest.json")
    put(fixture["native_path"], native)


def test_actual_native_inverse_conservation_refuses_reselected_false_relation(combined_selection, tmp_path):
    """Fresh hash/report bindings cannot replace the actual original-to-native relation (#1896)."""
    fixture = combined_selection
    manifest_path = fixture["root"] / "candidate/manifest.json"
    before = json.loads(manifest_path.read_bytes())
    reselect_invalid_position_map(fixture, tmp_path)
    after = json.loads(manifest_path.read_bytes())
    assert after["required_capabilities"] == before["required_capabilities"]
    assert after["files"] == before["files"]
    assert {name: sha(manifest_path.parent / name) for name in before["files"]} == before["files"]
    # Retain the real failed instance solely to save its actual child receipt.
    candidate = StableSourceCandidate.__new__(StableSourceCandidate)
    with pytest.raises(ValueError, match="actual emitted position map differs") as error:
        candidate.__init__(fixture["native_path"], selection_sha256=sha(fixture["native_path"]))
    execution = candidate.native_execution
    assert execution["exit_status"] != 0
    assert "actual emitted position map differs" in execution["stderr"]
    put(tmp_path / "semantic-negative-refusal.json", {"native_refusal": str(error.value), "execution": execution})


@pytest.mark.parametrize("control", ["historical_route", "missing_transition", "wrong_carrier"])
def test_final_combined_selection_cannot_downgrade(combined_selection, control):
    """Actual native success cannot excuse omitted final-consumer obligations."""
    fixture = combined_selection
    candidate = candidate_for(fixture)
    selection = fixture["selection"]
    if control == "historical_route":
        selection.update(contract=CONTRACT, mode="diagnostic_only")
        for key in ("combined_source_scope", "combined_source_declaration", "owner_transitions"):
            selection.pop(key)
        expected = "historical diagnostic route"
    elif control == "missing_transition":
        selection["owner_transitions"] = None
        expected = "transition requires reviewed reconciliation"
    else:
        selection["native_occurrence_payload_column"] = "an_unselected_carrier"
        expected = "CM carrier differs"
    put(fixture["path"], selection)
    with pytest.raises(ValueError, match=expected):
        verify_final_combined(candidate, fixture["path"], selection_sha256=sha(fixture["path"]))


def test_admitted_combined_input_late_drift_is_refused(combined_selection):
    """An admitted native capture cannot change after the final join succeeds."""
    fixture = combined_selection
    candidate = candidate_for(fixture)
    verify_final_combined(candidate, fixture["path"], selection_sha256=sha(fixture["path"]))
    evidence = fixture["root"] / "transition-source.txt"
    evidence.write_bytes(evidence.read_bytes() + b"Changed after admission.\n")
    with pytest.raises(ValueError, match="changed|fingerprint"):
        candidate.verify_current()
