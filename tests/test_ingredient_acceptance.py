"""Acceptance across actual producer claims, scoped lookup and merged KGX."""

import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe.utils.ingredient_bundle import ReviewedIngredientBundle, load_ingredient_lookup_bundle
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, content_sha256
from tests.test_ingredient_bundle import lookup_bundle as lookup_bundle
from tests.test_ingredient_bundle import producer_bundle as producer_bundle
from tests.test_ingredient_bundle import reset_lookup_cache as reset_lookup_cache


@pytest.fixture(scope="module")
def acceptance_runs(tmp_path_factory):
    """Use fresh subprocesses so unrelated tests cannot substitute a minimal KGX model."""
    root = Path(__file__).resolve().parents[1]
    reports = []
    for index, flags in enumerate(([], ["--reverse"], ["--synthetic"])):
        output = tmp_path_factory.mktemp("ingredient-acceptance") / str(index)
        result = subprocess.run(  # noqa: S603 - fixed first-party module and pytest-owned paths, no shell
            [sys.executable, "-m", "tests.ingredient_acceptance_runner", str(output), *flags],
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(root)},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((output / "acceptance.json").read_text())
        assert report["status"] == "PASS"
        assert report["mode"] == "candidate_only"
        assert report["production_promotion_authorized"] is False
        reports.append(report)
    return reports


def test_real_producer_native_scope_and_kgx_archive_acceptance(acceptance_runs):
    """All original claims and two native classification edges survive the public merge."""
    normal, reverse, synthetic = acceptance_runs
    assert normal["projected"]["nodes"] == 71
    assert normal["projected"]["edges"] == 51
    assert normal["merged_edges"] == 53
    assert normal["audit"]["policy_parity"]["status"] == "PASS"
    assert normal["graph_semantics_sha256"] == reverse["graph_semantics_sha256"]
    assert normal["claim_payloads_sha256"] == reverse["claim_payloads_sha256"]
    assert synthetic["synthetic_software_fixture"]
    assert synthetic["projected"]["edges"] == 57
    assert synthetic["audit"]["retained_product_records"] == 5
    assert synthetic["audit"]["retained_occurrence_records"] == 12


@pytest.mark.parametrize("reverse_rows", [False, True])
@pytest.mark.parametrize("padded", [False, True])
def test_rehashed_legacy_identity_conflict_blocks_candidate(lookup_bundle, tmp_path, reverse_rows, padded):
    """An independently pinned wrapper cannot authorize incompatible exact and broader claims."""
    from kg_microbe.utils.chemical_mapping_utils import _iter_sssom_rows

    directory = tmp_path / "contradictory"
    shutil.copytree(lookup_bundle[0], directory)
    path = directory / "legacy.sssom.tsv.gz"
    fixture = Path(__file__).parent / "resources/ingredient_bundle/native/legacy-conflict.sssom.tsv"
    origin = json.loads(fixture.with_name("legacy-conflict-origin.json").read_text())
    assert content_sha256(fixture.read_bytes()) == origin["fixture_sha256"]
    with gzip.open(path, "rt") as stream:
        metadata = []
        for line in stream:
            if not line.startswith("#"):
                break
            metadata.append(line)
    rows = [*list(_iter_sssom_rows(path)), *list(_iter_sssom_rows(fixture))]
    if padded:
        for row in rows:
            if row["predicate_id"] == "skos:exactMatch":
                for key in ("subject_id", "object_id"):
                    row[key] = " " + row[key] + " "
    if reverse_rows:
        rows.reverse()
    with gzip.open(path, "wt", newline="") as stream:
        stream.writelines(metadata)
        writer = csv.DictWriter(stream, sorted({key for row in rows for key in row}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = directory / "lookup_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["members"][path.name] = content_sha256(path.read_bytes())
    content = canonical_json(manifest) + b"\n"
    manifest_path.write_bytes(content)
    with pytest.raises(ValueError, match="Conflicting exact/nonidentity mappings require review"):
        load_ingredient_lookup_bundle(directory, manifest_sha256=content_sha256(content))


def test_unknown_required_capability_refuses_rehashed_bundle(producer_bundle, tmp_path):
    """A successful old consumer cannot activate a bundle requiring a future behavior."""
    directory = tmp_path / "future-capability"
    shutil.copytree(producer_bundle.directory, directory)
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["required_capabilities"].append("conditional-identity-v999")
    content = canonical_json(manifest) + b"\n"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="lacks required ingredient bundle capabilities"):
        ReviewedIngredientBundle(directory, manifest_sha256=content_sha256(content))


@pytest.mark.parametrize("bad_boolean", [True, 1, "1", "yes"])
def test_identity_extension_types_are_not_truthy_coerced(producer_bundle, bad_boolean):
    """Preserve the declared SSSOM lexical type instead of Python truthiness."""
    from kg_microbe.utils.ingredient_scope import read_profile_table, validate_scope_row

    metadata, _, rows = read_profile_table((producer_bundle.directory / "ingredient_mappings.sssom.tsv").read_bytes())
    row = rows[0]
    row["ext_identity_authorized"] = bad_boolean
    with pytest.raises(ValueError, match="TSV boolean"):
        validate_scope_row(row, metadata)
